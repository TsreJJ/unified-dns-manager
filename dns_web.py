#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_web.py
Function: 统一多平台 DNS 记录变更 Web UI
Author  : jim
Created : 2026-03-19
Version : 1.1.1
说明: 基于 Flask 的 REST API + 单页 Web UI，复用 lib/dns_api.py facade
使用: python3 dns_web.py [--host 127.0.0.1] [--port 5000]
"""

import os
import sys
import json
import logging
import argparse
import secrets
from functools import wraps

from flask import Flask, request, jsonify, render_template, abort

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

    Args:
        fqdn: 完整域名（如 test2345.zc2tv.com 或 a.b.example.co.uk）
    Returns:
        (root_domain, subdomain_rr)
        示例: ("zc2tv.com", "test2345") 或 ("example.co.uk", "a.b")
        若输入本身就是根域名则 subdomain_rr 为空字符串
    """
    fqdn = fqdn.strip().rstrip(".").lower()
    parts = fqdn.split(".")

    if len(parts) <= 2:
        return fqdn, ""

    # 检查是否命中多段式 TLD
    two_part_suffix = ".".join(parts[-2:])
    if two_part_suffix in _MULTI_TLDS:
        # 需要至少 3 段才构成根域名（如 example.co.uk）
        if len(parts) <= 3:
            return fqdn, ""
        root = ".".join(parts[-3:])
        sub = ".".join(parts[:-3])
        return root, sub

    # 普通 TLD（.com, .net, .org 等）
    root = ".".join(parts[-2:])
    sub = ".".join(parts[:-2])
    return root, sub

# ---------- 认证 ----------

def _get_auth_token() -> str:
    """
    获取认证 token
    优先从环境变量 WEB_AUTH_TOKEN 读取，未设置则自动生成并打印
    """
    token = os.environ.get("WEB_AUTH_TOKEN", "")
    if not token:
        token = secrets.token_urlsafe(32)
        os.environ["WEB_AUTH_TOKEN"] = token
        print(f"\n[安全] 未设置 WEB_AUTH_TOKEN，已自动生成:")
        print(f"  Token: {token}")
        print(f"  请保存此 token 用于 Web UI 登录\n")
    return token


def require_auth(f):
    """
    认证装饰器 — 校验 Bearer Token
    GET /api/* 读操作也需认证（DNS 记录属于敏感信息）
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "缺少认证 token"}), 401
        token = auth_header[7:]
        if not secrets.compare_digest(token, _get_auth_token()):
            return jsonify({"error": "认证 token 无效"}), 403
        return f(*args, **kwargs)
    return decorated


# ---------- 页面路由 ----------

@app.route("/")
def index():
    """Web UI 主页"""
    return render_template("index.html")


# ---------- API 路由 ----------

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
        # rr_keyword 是 provider 端模糊搜索，需后端精确过滤
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


# ---------- 入口 ----------

def create_parser() -> argparse.ArgumentParser:
    """创建命令行解析器"""
    parser = argparse.ArgumentParser(
        description="统一 DNS 管理 Web UI v1.1.0",
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
    """加载环境变量文件"""
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

    # 初始化 token（启动时打印）
    _get_auth_token()

    print(f"启动 DNS Web UI: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
