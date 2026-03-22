#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : lib/rbac.py
Function: 基于角色 + 域名的细粒度权限检查
Author  : jim
Created : 2026-03-22
Version : 2.0.0
说明: admin 隐含全部域名权限，operator/viewer 受 domain_permissions 约束
"""

import logging
from functools import wraps

from flask import g, jsonify

from lib.database import get_db

logger = logging.getLogger(__name__)


def check_domain_permission(user_id: int, role: str, domain: str) -> bool:
    """
    检查用户是否有指定域名的访问权限
    参数: user_id - 用户 ID
          role    - 用户角色
          domain  - 域名
    返回值: True=有权限, False=无权限
    """
    # admin 拥有全部域名权限
    if role == "admin":
        return True

    # Bearer Token (CLI) 始终是 admin，已由上面处理
    if user_id == 0:
        return True

    db = get_db()
    row = db.execute(
        "SELECT 1 FROM domain_permissions WHERE user_id = ? AND domain = ?",
        (user_id, domain),
    ).fetchone()
    return row is not None


def require_domain_access(domain_param: str):
    """
    域名权限装饰器（必须在 require_auth 之后使用）
    参数: domain_param - 路由参数名（如 "fqdn"），会从 kwargs 中取值并提取根域名
    示例: @require_domain_access("fqdn")
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from dns_web import extract_root_domain

            fqdn = kwargs.get(domain_param, "")
            root_domain, _ = extract_root_domain(fqdn)

            user_id = getattr(g, "user_id", 0)
            user_role = getattr(g, "user_role", "")

            if not check_domain_permission(user_id, user_role, root_domain):
                return jsonify({
                    "error": f"无权访问域名: {root_domain}",
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator
