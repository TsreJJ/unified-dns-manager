#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : cdnw_client.py
Function: CDNetworks Cloud DNS API 客户端（精简版，仅 DNS 操作）
Author  : Jimmy Lin
Created : 2025-11-19
Version : 1.2.0
说明: CNC-HMAC-SHA256 签名认证，支持 Cloud DNS Zone/Record CRUD
"""

import os
import json
import time
import hmac
import hashlib
import logging
from typing import Dict, Optional, Tuple
from urllib.parse import unquote

import requests

logger = logging.getLogger(__name__)


class CDNWClient:
    """CDNetworks Cloud DNS API 客户端"""

    DEFAULT_ENDPOINT = "api.cdnetworks.com"
    DEFAULT_TIMEOUT = 30
    SIGNED_HEADERS = "content-type;host"
    AUTH_ALGORITHM = "CNC-HMAC-SHA256"
    AUTH_METHOD = "AKSK"

    def __init__(self, access_key: str = None, secret_key: str = None,
                 endpoint: str = None, timeout: Optional[int] = None):
        """
        初始化客户端

        Args:
            access_key: API Access Key，默认从 CDNW_ACCESS_KEY 获取
            secret_key: API Secret Key，默认从 CDNW_SECRET_KEY 获取
            endpoint: API 端点，默认 api.cdnetworks.com
            timeout: HTTP 超时（秒），默认 30
        """
        self.access_key = access_key or os.getenv("CDNW_ACCESS_KEY")
        self.secret_key = secret_key or os.getenv("CDNW_SECRET_KEY")
        self.endpoint = endpoint or self.DEFAULT_ENDPOINT
        env_timeout = os.getenv("CDNW_TIMEOUT")
        self.timeout = timeout or (int(env_timeout) if env_timeout else self.DEFAULT_TIMEOUT)
        self.scheme = os.getenv("CDNW_API_SCHEME", "https")

        if not self.access_key or not self.secret_key:
            raise ValueError("请设置 CDNW_ACCESS_KEY 和 CDNW_SECRET_KEY 环境变量")

    def _split_uri(self, uri: str, method: str = "GET") -> Tuple[str, str]:
        """
        拆分 URI，返回 (path, query_string)

        注意: CDNW 签名规范中 POST 方法不将 query string 纳入签名计算，
        与官方 SDK get_query_string() 行为一致。
        """
        if '?' in uri:
            path, query = uri.split('?', 1)
        else:
            path, query = uri, ''
        if not path:
            path = '/'
        # POST 方法的 query string 不参与签名
        if method.upper() == "POST":
            return path, ''
        return path, unquote(query)

    def _canonical_headers(self, headers: Dict[str, str]) -> str:
        """生成 canonical headers 字串"""
        normalized = {k.lower(): v for k, v in headers.items()}
        lines = []
        for header in self.SIGNED_HEADERS.split(';'):
            header = header.strip()
            value = normalized.get(header, '')
            lines.append(f"{header}:{(value or '').strip().lower()}\n")
        return ''.join(lines)

    def _create_authorization(self, method: str, uri: str,
                              body_str: str, headers: Dict[str, str],
                              timestamp: str) -> str:
        """根据 AK/SK 规则生成 Authorization 标头"""
        path, query = self._split_uri(uri, method)
        hashed_payload = hashlib.sha256(body_str.encode('utf-8')).hexdigest()
        canonical_headers = self._canonical_headers(headers)
        canonical_request = (
            f"{method}\n{path}\n{query}\n"
            f"{canonical_headers}\n"
            f"{self.SIGNED_HEADERS}\n{hashed_payload}"
        )

        hashed_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        string_to_sign = f"{self.AUTH_ALGORITHM}\n{timestamp}\n{hashed_request}"
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha256
        ).hexdigest().lower()

        return (
            f"{self.AUTH_ALGORITHM} Credential={self.access_key}, "
            f"SignedHeaders={self.SIGNED_HEADERS}, Signature={signature}"
        )

    def _perform_request(self, uri: str, method: str, body_str: str = "") -> str:
        """执行带签名的 HTTP 请求"""
        method = method.upper()
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "x-cnc-auth-method": self.AUTH_METHOD,
            "Host": self.endpoint,
            "x-cnc-accessKey": self.access_key,
            "x-cnc-timestamp": timestamp,
        }

        authorization = self._create_authorization(method, uri, body_str, headers, timestamp)
        headers["Authorization"] = authorization

        url = f"{self.scheme}://{self.endpoint}{uri}"
        # POST/PUT/PATCH/DELETE 必须发送 body（即使为空字符串），以确保签名一致
        data = body_str if method in {"POST", "PUT", "PATCH", "DELETE"} else None

        try:
            response = requests.request(
                method, url, headers=headers, data=data, timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.HTTPError as exc:
            # CDNW 自定义状态码（如 462）携带业务语义，返回 body 供上层判断
            if exc.response is not None:
                logger.debug("CDNW API HTTP %s: %s", exc.response.status_code, uri)
                return exc.response.text or ""
            raise
        except requests.RequestException as exc:
            logger.error("CDNW API 请求失败: %s", exc)
            raise

    def request(self, uri: str, method: str = "GET", body: Optional[dict] = None) -> dict:
        """
        发送 API 请求

        Args:
            uri: API URI
            method: HTTP 方法
            body: 请求体

        Returns:
            dict: 响应数据
        """
        body_str = json.dumps(body) if body is not None else ""
        response = self._perform_request(uri, method, body_str)

        if response is None:
            raise ValueError("CDNW API 返回空响应")

        response = response.strip()
        return json.loads(response)
