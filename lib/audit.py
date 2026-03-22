#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : lib/audit.py
Function: 写操作审计日志记录与查询
Author  : jim
Created : 2026-03-22
Version : 2.0.0
说明: 通过装饰器自动记录 add/update/delete 操作
"""

import json
import logging
from functools import wraps

from flask import request, g

from lib.database import get_db

logger = logging.getLogger(__name__)


def audit_log(action: str):
    """
    审计日志装饰器 — 记录写操作的请求与结果
    参数: action - 操作类型 ('add', 'update', 'delete')
    示例: @audit_log("add")
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from dns_web import extract_root_domain

            # 提取请求信息
            fqdn = kwargs.get("fqdn", "")
            root_domain, _ = extract_root_domain(fqdn)
            body = request.get_json(silent=True) or {}

            rr = body.get("rr", "")
            record_type = body.get("type", "")
            value = body.get("value", "")
            user_email = getattr(g, "user_email", "unknown")
            client_ip = getattr(g, "client_ip", "")

            # 执行原函数
            response = f(*args, **kwargs)

            # 解析结果
            result_success = 0
            result_message = ""
            try:
                if hasattr(response, "__iter__") and len(response) == 2:
                    resp_data, status_code = response
                else:
                    resp_data = response
                    status_code = 200

                if hasattr(resp_data, "get_json"):
                    resp_json = resp_data.get_json(silent=True) or {}
                elif hasattr(resp_data, "json"):
                    resp_json = resp_data.json
                else:
                    resp_json = {}

                result_success = 1 if (200 <= status_code < 300) else 0
                result_message = resp_json.get("error_message", resp_json.get("error", ""))
                if result_success and not result_message:
                    result_message = "success"
            except Exception:
                pass

            # 写入审计日志
            try:
                db = get_db()
                db.execute(
                    """INSERT INTO audit_logs
                       (user_email, action, domain, rr, record_type, value,
                        request_body, result_success, result_message, ip_address)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_email, action, root_domain, rr, record_type, value,
                        json.dumps(body, ensure_ascii=False)[:2000],
                        result_success, result_message[:500], client_ip,
                    ),
                )
                db.commit()
            except Exception as e:
                logger.error("审计日志写入失败: %s", e)

            return response

        return decorated
    return decorator


def query_audit_logs(
    user: str = "",
    domain: str = "",
    action: str = "",
    start: str = "",
    end: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    查询审计日志
    参数: user   - 按用户邮箱过滤
          domain - 按域名过滤
          action - 按操作类型过滤
          start  - 起始时间 (ISO 8601)
          end    - 结束时间 (ISO 8601)
          limit  - 返回条数（默认 100，最大 500）
          offset - 偏移量
    返回值: {"total": int, "logs": list[dict]}
    """
    limit = min(max(1, limit), 500)
    offset = max(0, offset)

    conditions = []
    params = []

    if user:
        conditions.append("user_email = ?")
        params.append(user)
    if domain:
        conditions.append("domain = ?")
        params.append(domain)
    if action:
        conditions.append("action = ?")
        params.append(action)
    if start:
        conditions.append("timestamp >= ?")
        params.append(start)
    if end:
        conditions.append("timestamp <= ?")
        params.append(end)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    db = get_db()

    # 总数
    total = db.execute(f"SELECT COUNT(*) FROM audit_logs{where}", params).fetchone()[0]

    # 分页数据
    rows = db.execute(
        f"SELECT * FROM audit_logs{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    logs = [dict(row) for row in rows]

    return {"total": total, "logs": logs}
