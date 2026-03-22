#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : lib/cf_access_auth.py
Function: Cloudflare Access JWT 验证 + 双模式认证装饰器
Author  : jim
Created : 2026-03-22
Version : 2.0.0
说明: CF JWT 优先认证，Bearer Token 作为 CLI/自动化 fallback
"""

import os
import time
import secrets
import logging
from functools import wraps

import jwt
import requests
from flask import request, jsonify, g

from lib.database import get_db

logger = logging.getLogger(__name__)

# ---------- JWKS 缓存 ----------

_jwks_cache = {"keys": [], "fetched_at": 0}
_JWKS_TTL = 3600  # 1 小时


def _get_jwks_url() -> str:
    """
    构造 CF Access JWKS URL
    返回值: JWKS endpoint URL
    """
    team = os.environ.get("CF_ACCESS_TEAM_NAME", "")
    if not team:
        return ""
    # 支持传入完整域名或仅 team name
    if not team.endswith(".cloudflareaccess.com"):
        team = f"{team}.cloudflareaccess.com"
    return f"https://{team}/cdn-cgi/access/certs"


def _fetch_jwks(force: bool = False) -> list:
    """
    获取 CF Access JWKS 公钥（带内存缓存）
    参数: force - 强制刷新
    返回值: JWKS keys 列表
    """
    now = time.time()
    if not force and _jwks_cache["keys"] and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL:
        return _jwks_cache["keys"]

    url = _get_jwks_url()
    if not url:
        logger.warning("CF_ACCESS_TEAM_NAME 未配置，JWKS 不可用")
        return []

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        keys = data.get("keys", [])
        if keys:
            _jwks_cache["keys"] = keys
            _jwks_cache["fetched_at"] = now
            logger.info("JWKS 已刷新，共 %d 个公钥", len(keys))
        return keys
    except Exception as e:
        logger.error("获取 JWKS 失败: %s", e)
        return _jwks_cache["keys"]  # 返回旧缓存


def _validate_cf_jwt(token: str) -> dict | None:
    """
    验证 CF Access JWT 签名并返回 payload
    参数: token - JWT 字符串
    返回值: JWT payload dict，验证失败返回 None
    """
    audience = os.environ.get("CF_ACCESS_AUDIENCE", "")
    if not audience:
        logger.warning("CF_ACCESS_AUDIENCE 未配置")
        return None

    keys = _fetch_jwks()
    if not keys:
        return None

    # 尝试验证，失败后强制刷新 JWKS 再试一次（应对 key rotation）
    for attempt in range(2):
        try:
            # 构建 PyJWT 所需的 jwk set
            jwk_set = jwt.PyJWKSet.from_dict({"keys": keys})
            # 获取 token header 中的 kid
            header = jwt.get_unverified_header(token)
            kid = header.get("kid", "")

            signing_key = None
            for k in jwk_set.keys:
                if k.key_id == kid:
                    signing_key = k
                    break

            if not signing_key:
                if attempt == 0:
                    keys = _fetch_jwks(force=True)
                    continue
                logger.warning("未找到匹配的签名密钥 kid=%s", kid)
                return None

            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                options={"require": ["exp", "iat", "email"]},
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("CF JWT 已过期")
            return None
        except jwt.InvalidTokenError as e:
            if attempt == 0:
                keys = _fetch_jwks(force=True)
                continue
            logger.warning("CF JWT 验证失败: %s", e)
            return None

    return None


def _get_client_ip() -> str:
    """
    获取客户端 IP（兼容 CF 代理）
    返回值: IP 地址字符串
    """
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or ""
    )


# ---------- 认证装饰器 ----------


def require_auth(f):
    """
    双模式认证装饰器：
    1. Cf-Access-Jwt-Assertion → CF JWKS 公钥验证 → email → 查 users 表
    2. Authorization: Bearer <token> → 比对 WEB_AUTH_TOKEN → admin
    3. 都没有 → 401
    4. email 不在 users 表或 is_active=0 → 403
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # 模式 1: CF Access JWT
        cf_jwt = request.headers.get("Cf-Access-Jwt-Assertion", "")
        if cf_jwt:
            payload = _validate_cf_jwt(cf_jwt)
            if payload:
                email = payload.get("email", "").lower()
                if not email:
                    return jsonify({"error": "JWT 中缺少 email"}), 401

                db = get_db()
                user = db.execute(
                    "SELECT id, email, role, display_name, is_active FROM users WHERE email = ?",
                    (email,),
                ).fetchone()

                if not user:
                    return jsonify({"error": f"用户 {email} 未授权，请联系管理员"}), 403
                if not user["is_active"]:
                    return jsonify({"error": f"用户 {email} 已被停用"}), 403

                g.user_id = user["id"]
                g.user_email = user["email"]
                g.user_role = user["role"]
                g.user_display_name = user["display_name"]
                g.auth_method = "cf_access"
                g.client_ip = _get_client_ip()
                return f(*args, **kwargs)
            # JWT 存在但验证失败
            return jsonify({"error": "CF Access JWT 验证失败"}), 401

        # 模式 2: Bearer Token (Legacy CLI/自动化)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            expected = os.environ.get("WEB_AUTH_TOKEN", "")
            if expected and secrets.compare_digest(token, expected):
                g.user_id = 0
                g.user_email = "cli@localhost"
                g.user_role = "admin"
                g.user_display_name = "CLI/Automation"
                g.auth_method = "bearer_token"
                g.client_ip = _get_client_ip()
                return f(*args, **kwargs)
            return jsonify({"error": "Bearer Token 无效"}), 401

        # 无认证信息
        return jsonify({"error": "需要认证"}), 401

    return decorated


def require_role(*roles):
    """
    角色检查装饰器（必须在 require_auth 之后使用）
    参数: *roles - 允许的角色列表，如 require_role("admin", "operator")
    示例: @require_role("admin")
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_role = getattr(g, "user_role", "")
            if user_role not in roles:
                return jsonify({
                    "error": f"权限不足，需要角色: {', '.join(roles)}",
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
