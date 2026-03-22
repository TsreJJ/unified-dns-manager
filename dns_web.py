#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_web.py
Function: 统一多平台 DNS 记录变更 Web UI（含 RBAC + 审计）
Author  : jim
Created : 2026-03-19
Version : 2.0.0
说明: 基于 Flask 的 REST API + 单页 Web UI，复用 lib/dns_api.py facade
     认证: CF Access JWT 优先，Bearer Token 兼容 CLI/自动化
     权限: 角色 (admin/operator/viewer) + 域名级细粒度控制
     审计: 所有写操作自动记录
使用: python3 dns_web.py [--host 127.0.0.1] [--port 5000]
"""

import os
import sys
import json
import logging
import argparse

from flask import Flask, request, jsonify, render_template, g

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.dns_api import (
    dns_list_records,
    dns_add_record,
    dns_update_record,
    dns_delete_record,
)
from lib.dns_provider_factory import DNSProviderFactory, ProviderType
from lib.ns_detector import resolve_ns, NSDetectorService
from lib.database import init_db, get_db
from lib.cf_access_auth import require_auth, require_role
from lib.rbac import require_domain_access, check_domain_permission
from lib.audit import audit_log, query_audit_logs

logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------- 域名清洗 ----------

# 已知多段式 TLD（ccSLD），输入 foo.com.cn 时根域名是 foo.com.cn 而非 com.cn
_MULTI_TLDS = {
    "com.cn", "net.cn", "org.cn", "gov.cn", "ac.cn",
    "com.tw", "org.tw", "net.tw", "gov.tw",
    "com.hk", "org.hk", "net.hk", "gov.hk",
    "co.uk", "org.uk", "ac.uk", "gov.uk",
    "co.jp", "or.jp", "ne.jp", "ac.jp",
    "com.au", "net.au", "org.au",
    "co.kr", "or.kr", "ne.kr",
    "co.in", "net.in", "org.in",
    "com.sg", "org.sg", "net.sg",
    "com.my", "net.my", "org.my",
    "com.br", "net.br", "org.br",
    "co.nz", "net.nz", "org.nz",
    "co.za", "net.za", "org.za",
    "co.th", "or.th", "in.th",
}


def extract_root_domain(fqdn: str) -> tuple:
    """
    从完整域名中提取根域名和子域名前缀

    参数: fqdn - 完整域名（如 test2345.zc2tv.com 或 a.b.example.co.uk）
    返回值: (root_domain, subdomain_rr)
    示例: ("zc2tv.com", "test2345") 或 ("example.co.uk", "a.b")
    """
    fqdn = fqdn.strip().rstrip(".").lower()
    parts = fqdn.split(".")

    if len(parts) <= 2:
        return fqdn, ""

    # 检查是否命中多段式 TLD
    two_part_suffix = ".".join(parts[-2:])
    if two_part_suffix in _MULTI_TLDS:
        if len(parts) <= 3:
            return fqdn, ""
        root = ".".join(parts[-3:])
        sub = ".".join(parts[:-3])
        return root, sub

    root = ".".join(parts[-2:])
    sub = ".".join(parts[:-2])
    return root, sub


# ---------- 页面路由 ----------

@app.route("/")
def index():
    """Web UI 主页"""
    return render_template("index.html")


# ---------- 用户信息 ----------

@app.route("/api/me", methods=["GET"])
@require_auth
def api_me():
    """当前用户信息"""
    result = {
        "email": g.user_email,
        "role": g.user_role,
        "display_name": getattr(g, "user_display_name", ""),
        "auth_method": g.auth_method,
    }

    # 非 admin 用户返回其授权域名列表
    if g.user_role != "admin" and g.user_id > 0:
        db = get_db()
        rows = db.execute(
            "SELECT domain FROM domain_permissions WHERE user_id = ? ORDER BY domain",
            (g.user_id,),
        ).fetchall()
        result["domains"] = [r["domain"] for r in rows]

    return jsonify(result)


# ---------- DNS API 路由 ----------

@app.route("/api/providers", methods=["GET"])
@require_auth
def api_providers():
    """列出支持的平台"""
    providers = [t.value for t in ProviderType]
    return jsonify({"providers": providers})


@app.route("/api/parse-domain/<path:fqdn>", methods=["GET"])
@require_auth
def api_parse_domain(fqdn):
    """解析域名，返回根域名和子域名前缀"""
    root, sub = extract_root_domain(fqdn)
    return jsonify({"input": fqdn, "root_domain": root, "subdomain_rr": sub})


@app.route("/api/detect/<path:fqdn>", methods=["GET"])
@require_auth
@require_domain_access("fqdn")
def api_detect(fqdn):
    """检测域名归属平台（自动提取根域名）"""
    root_domain, subdomain_rr = extract_root_domain(fqdn)
    try:
        ns_servers = resolve_ns(root_domain)
        if not ns_servers:
            return jsonify({"error": f"无法解析域名 {root_domain} 的 NS 记录"}), 400

        detector = NSDetectorService()
        result = detector.detect_provider(ns_servers)
        result["domain"] = root_domain
        result["input"] = fqdn
        result["subdomain_rr"] = subdomain_rr
        return jsonify(result)
    except Exception as e:
        logger.exception("检测域名失败: %s (root: %s)", fqdn, root_domain)
        return jsonify({"error": str(e)}), 500


@app.route("/api/records/<path:fqdn>", methods=["GET"])
@require_auth
@require_domain_access("fqdn")
def api_list_records(fqdn):
    """列出解析记录（自动提取根域名，子域名作为 rr 过滤）"""
    root_domain, subdomain_rr = extract_root_domain(fqdn)
    rr = request.args.get("rr") or (subdomain_rr if subdomain_rr else None)
    record_type = request.args.get("type")
    provider = request.args.get("provider")

    try:
        records = dns_list_records(
            root_domain, rr=rr, record_type=record_type, provider=provider,
        )
        if rr:
            records = [r for r in records if r.rr == rr]
        return jsonify({
            "domain": root_domain,
            "input": fqdn,
            "subdomain_rr": subdomain_rr,
            "count": len(records),
            "records": [r.to_dict() for r in records],
        })
    except Exception as e:
        logger.exception("列出记录失败: %s (root: %s)", fqdn, root_domain)
        return jsonify({"error": str(e)}), 500


@app.route("/api/records/<path:fqdn>", methods=["POST"])
@require_auth
@require_role("admin", "operator")
@require_domain_access("fqdn")
@audit_log("add")
def api_add_record(fqdn):
    """添加解析记录（自动提取根域名）"""
    root_domain, _ = extract_root_domain(fqdn)
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体必须为 JSON"}), 400

    required = ["rr", "type", "value"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"缺少必填字段: {', '.join(missing)}"}), 400

    try:
        result = dns_add_record(
            root_domain,
            rr=data["rr"],
            record_type=data["type"],
            value=data["value"],
            ttl=int(data.get("ttl", 600)),
            priority=int(data["priority"]) if data.get("priority") else None,
            provider=data.get("provider"),
        )
        if result.success:
            return jsonify(result.to_dict()), 201
        return jsonify(result.to_dict()), 400
    except Exception as e:
        logger.exception("添加记录失败: %s (root: %s)", fqdn, root_domain)
        return jsonify({"error": str(e)}), 500


@app.route("/api/records/<path:fqdn>", methods=["PUT"])
@require_auth
@require_role("admin", "operator")
@require_domain_access("fqdn")
@audit_log("update")
def api_update_record(fqdn):
    """更新解析记录（自动提取根域名）"""
    root_domain, _ = extract_root_domain(fqdn)
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体必须为 JSON"}), 400

    required = ["rr", "type", "value"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"缺少必填字段: {', '.join(missing)}"}), 400

    try:
        result = dns_update_record(
            root_domain,
            rr=data["rr"],
            record_type=data["type"],
            value=data["value"],
            ttl=int(data.get("ttl", 600)),
            priority=int(data["priority"]) if data.get("priority") else None,
            record_id=data.get("record_id"),
            provider=data.get("provider"),
        )
        if result.success:
            return jsonify(result.to_dict())
        return jsonify(result.to_dict()), 400
    except Exception as e:
        logger.exception("更新记录失败: %s (root: %s)", fqdn, root_domain)
        return jsonify({"error": str(e)}), 500


@app.route("/api/records/<path:fqdn>", methods=["DELETE"])
@require_auth
@require_role("admin", "operator")
@require_domain_access("fqdn")
@audit_log("delete")
def api_delete_record(fqdn):
    """删除解析记录（自动提取根域名）"""
    root_domain, _ = extract_root_domain(fqdn)
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体必须为 JSON"}), 400

    record_id = data.get("record_id")
    rr = data.get("rr")
    record_type = data.get("type")

    if not record_id and (not rr or not record_type):
        return jsonify({"error": "需要 record_id 或 rr + type"}), 400

    try:
        result = dns_delete_record(
            root_domain,
            rr=rr,
            record_type=record_type,
            record_id=record_id,
            provider=data.get("provider"),
        )
        if result.success:
            return jsonify(result.to_dict())
        return jsonify(result.to_dict()), 400
    except Exception as e:
        logger.exception("删除记录失败: %s (root: %s)", fqdn, root_domain)
        return jsonify({"error": str(e)}), 500


# ---------- Admin API ----------

@app.route("/api/admin/users", methods=["GET"])
@require_auth
@require_role("admin")
def api_admin_list_users():
    """用户列表"""
    db = get_db()
    rows = db.execute(
        "SELECT id, email, role, display_name, is_active, created_at, updated_at FROM users ORDER BY id",
    ).fetchall()
    users = []
    for row in rows:
        user = dict(row)
        # 附加域名权限
        domains = db.execute(
            "SELECT domain FROM domain_permissions WHERE user_id = ? ORDER BY domain",
            (row["id"],),
        ).fetchall()
        user["domains"] = [d["domain"] for d in domains]
        users.append(user)
    return jsonify({"users": users})


@app.route("/api/admin/users", methods=["POST"])
@require_auth
@require_role("admin")
def api_admin_create_user():
    """创建用户"""
    data = request.get_json(silent=True)
    if not data or not data.get("email"):
        return jsonify({"error": "缺少 email"}), 400

    email = data["email"].strip().lower()
    role = data.get("role", "viewer")
    if role not in ("admin", "operator", "viewer"):
        return jsonify({"error": "无效角色，可选: admin, operator, viewer"}), 400

    display_name = data.get("display_name", "")
    domains = data.get("domains", [])

    db = get_db()
    # 检查重复
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return jsonify({"error": f"用户 {email} 已存在"}), 409

    cursor = db.execute(
        "INSERT INTO users (email, role, display_name) VALUES (?, ?, ?)",
        (email, role, display_name),
    )
    user_id = cursor.lastrowid

    # 写入域名权限
    for domain in domains:
        domain = domain.strip().lower()
        if domain:
            db.execute(
                "INSERT OR IGNORE INTO domain_permissions (user_id, domain) VALUES (?, ?)",
                (user_id, domain),
            )
    db.commit()

    logger.info("admin %s 创建用户: %s (role=%s)", g.user_email, email, role)
    return jsonify({"id": user_id, "email": email, "role": role}), 201


@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
@require_auth
@require_role("admin")
def api_admin_update_user(user_id):
    """编辑用户"""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体必须为 JSON"}), 400

    updates = []
    params = []

    if "role" in data:
        role = data["role"]
        if role not in ("admin", "operator", "viewer"):
            return jsonify({"error": "无效角色"}), 400
        updates.append("role = ?")
        params.append(role)

    if "display_name" in data:
        updates.append("display_name = ?")
        params.append(data["display_name"])

    if "is_active" in data:
        updates.append("is_active = ?")
        params.append(1 if data["is_active"] else 0)

    if updates:
        updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')")
        params.append(user_id)
        db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()

    logger.info("admin %s 更新用户 #%d: %s", g.user_email, user_id, data)
    return jsonify({"message": "更新成功"})


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@require_auth
@require_role("admin")
def api_admin_delete_user(user_id):
    """删除用户"""
    db = get_db()
    user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404

    # 禁止删除自己
    if user["email"] == g.user_email:
        return jsonify({"error": "不能删除自己"}), 400

    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()

    logger.info("admin %s 删除用户: %s (#%d)", g.user_email, user["email"], user_id)
    return jsonify({"message": f"用户 {user['email']} 已删除"})


@app.route("/api/admin/users/<int:user_id>/domains", methods=["GET"])
@require_auth
@require_role("admin")
def api_admin_get_domains(user_id):
    """查看用户域名权限"""
    db = get_db()
    user = db.execute("SELECT email, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404

    rows = db.execute(
        "SELECT domain FROM domain_permissions WHERE user_id = ? ORDER BY domain",
        (user_id,),
    ).fetchall()
    return jsonify({
        "user_id": user_id,
        "email": user["email"],
        "role": user["role"],
        "domains": [r["domain"] for r in rows],
    })


@app.route("/api/admin/users/<int:user_id>/domains", methods=["PUT"])
@require_auth
@require_role("admin")
def api_admin_set_domains(user_id):
    """设置用户域名权限（全量替换）"""
    db = get_db()
    user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return jsonify({"error": "用户不存在"}), 404

    data = request.get_json(silent=True)
    if not data or "domains" not in data:
        return jsonify({"error": "缺少 domains 字段"}), 400

    domains = data["domains"]
    if not isinstance(domains, list):
        return jsonify({"error": "domains 必须为数组"}), 400

    # 全量替换
    db.execute("DELETE FROM domain_permissions WHERE user_id = ?", (user_id,))
    for domain in domains:
        domain = domain.strip().lower()
        if domain:
            db.execute(
                "INSERT OR IGNORE INTO domain_permissions (user_id, domain) VALUES (?, ?)",
                (user_id, domain),
            )
    db.commit()

    logger.info("admin %s 设置用户 #%d 域名权限: %s", g.user_email, user_id, domains)
    return jsonify({"message": "域名权限已更新", "domains": domains})


@app.route("/api/admin/audit", methods=["GET"])
@require_auth
@require_role("admin")
def api_admin_audit():
    """审计日志查询"""
    result = query_audit_logs(
        user=request.args.get("user", ""),
        domain=request.args.get("domain", ""),
        action=request.args.get("action", ""),
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        limit=int(request.args.get("limit", 100)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify(result)


# ---------- 入口 ----------

def create_parser() -> argparse.ArgumentParser:
    """创建命令行解析器"""
    parser = argparse.ArgumentParser(
        description="统一 DNS 管理 Web UI v2.0.0",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="监听地址（默认: 127.0.0.1）",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="监听端口（默认: 5000）",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="启用 Flask debug 模式（仅开发用）",
    )
    parser.add_argument(
        "--env-file",
        help="指定环境变量文件",
    )
    return parser


def load_env_file(env_file: str):
    """
    加载环境变量文件
    参数: env_file - 文件路径
    """
    if not os.path.exists(env_file):
        print(f"错误: 环境变量文件不存在: {env_file}", file=sys.stderr)
        sys.exit(1)
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip().strip("'\"")


def main():
    parser = create_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 加载环境变量
    if args.env_file:
        load_env_file(args.env_file)
    else:
        default_env = os.path.expanduser("~/.credentials/unified-dns-manager.env")
        if os.path.exists(default_env):
            load_env_file(default_env)

    # 初始化数据库（建表 + 种子 admin）
    init_db(app)

    print(f"启动 DNS Web UI v2.0.0: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
