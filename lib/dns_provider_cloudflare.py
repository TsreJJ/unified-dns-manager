#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_provider_cloudflare.py
Function: Cloudflare DNS Provider 实现
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 基于 Cloudflare API v4，使用 API Token 认证
环境变量: CLOUDFLARE_API_TOKEN
"""

import os
import logging
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from lib.dns_provider_base import DNSProvider, RecordInfo, OperationResult

logger = logging.getLogger(__name__)


class CloudflareDNSProvider(DNSProvider):
    """Cloudflare DNS Provider"""

    def __init__(self, api_token: Optional[str] = None):
        """
        初始化 Cloudflare Provider

        Args:
            api_token: API Token，默认从 CLOUDFLARE_API_TOKEN 环境变量获取
        """
        self._api_token = api_token or os.getenv("CLOUDFLARE_API_TOKEN")
        if not self._api_token:
            raise ValueError("请设置 CLOUDFLARE_API_TOKEN 环境变量")

        self._base_url = "https://api.cloudflare.com/client/v4"
        self._session = requests.Session()
        retry = Retry(total=3, status_forcelist=[429, 500, 502, 503, 504], backoff_factor=1)
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.headers.update({
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        })

        # zone_id 缓存
        self._zone_cache: dict = {}

    @property
    def provider_name(self) -> str:
        return "cloudflare"

    def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """发送 API 请求"""
        url = f"{self._base_url}{endpoint}"
        resp = self._session.request(method, url, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _get_zone_id(self, domain: str) -> str:
        """获取域名的 Zone ID（带缓存）"""
        parts = domain.split(".")
        zone_name = ".".join(parts[-2:]) if len(parts) >= 2 else domain

        if zone_name in self._zone_cache:
            return self._zone_cache[zone_name]

        resp = self._request("GET", f"/zones?name={zone_name}")
        if not resp.get("success") or not resp.get("result"):
            raise ValueError(f"找不到域名 {zone_name} 的 Zone")

        zone_id = resp["result"][0]["id"]
        self._zone_cache[zone_name] = zone_id
        return zone_id

    def _to_fqdn(self, rr: str, domain: str) -> str:
        """将主机记录转为 FQDN"""
        if rr == "@":
            return domain
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        if rr.endswith(f".{zone}"):
            return rr
        return f"{rr}.{zone}"

    def _extract_rr(self, name: str, domain: str) -> str:
        """从 FQDN 提取主机记录"""
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        if name == zone:
            return "@"
        suffix = f".{zone}"
        if name.endswith(suffix):
            return name[: -len(suffix)]
        return name

    def list_records(
        self,
        domain_name: str,
        rr_keyword: Optional[str] = None,
        type_keyword: Optional[str] = None,
    ) -> List[RecordInfo]:
        """列出解析记录"""
        zone_id = self._get_zone_id(domain_name)
        endpoint = f"/zones/{zone_id}/dns_records"

        params = []
        if type_keyword:
            params.append(f"type={type_keyword.upper()}")
        if rr_keyword:
            fqdn = self._to_fqdn(rr_keyword, domain_name)
            params.append(f"name={fqdn}")

        if params:
            endpoint += "?" + "&".join(params)

        resp = self._request("GET", endpoint)
        if not resp.get("success"):
            raise RuntimeError(f"查询失败: {resp.get('errors')}")

        records = []
        parts = domain_name.split(".")
        zone = ".".join(parts[-2:]) if len(parts) >= 2 else domain_name
        for r in resp.get("result", []):
            records.append(RecordInfo(
                record_id=r["id"],
                domain_name=zone,
                rr=self._extract_rr(r["name"], domain_name),
                type=r["type"],
                value=r["content"],
                ttl=r.get("ttl", 1),
                priority=r.get("priority"),
                line="default",
                status="ENABLE",
                remark=r.get("comment"),
            ))
        return records

    def add_record(
        self,
        domain_name: str,
        rr: str,
        record_type: str,
        value: str,
        ttl: int = 600,
        priority: Optional[int] = None,
        line: str = "default",
    ) -> OperationResult:
        """添加解析记录"""
        zone_id = self._get_zone_id(domain_name)
        data = {
            "type": record_type.upper(),
            "name": self._to_fqdn(rr, domain_name),
            "content": value,
            "ttl": ttl,
        }
        if priority is not None:
            data["priority"] = priority

        try:
            resp = self._request("POST", f"/zones/{zone_id}/dns_records", data)
            if resp.get("success"):
                return OperationResult(
                    success=True,
                    data={"record_id": resp["result"]["id"]},
                )
            return OperationResult(
                success=False,
                error_message=str(resp.get("errors")),
            )
        except Exception as e:
            return OperationResult(success=False, error_message=str(e))

    def update_record(
        self,
        record_id: str,
        rr: str,
        record_type: str,
        value: str,
        ttl: int = 600,
        priority: Optional[int] = None,
        line: str = "default",
        domain_name: Optional[str] = None,
    ) -> OperationResult:
        """更新解析记录"""
        if not domain_name:
            return OperationResult(
                success=False,
                error_message="Cloudflare 更新记录需要 domain_name 参数",
            )
        zone_id = self._get_zone_id(domain_name)
        data = {
            "type": record_type.upper(),
            "name": self._to_fqdn(rr, domain_name),
            "content": value,
            "ttl": ttl,
        }
        if priority is not None:
            data["priority"] = priority

        try:
            resp = self._request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", data)
            if resp.get("success"):
                return OperationResult(success=True, data={"record_id": record_id})
            return OperationResult(
                success=False,
                error_message=str(resp.get("errors")),
            )
        except Exception as e:
            return OperationResult(success=False, error_message=str(e))

    def delete_record(
        self,
        record_id: str,
        domain_name: Optional[str] = None,
        rr: Optional[str] = None,
        record_type: Optional[str] = None,
        value: Optional[str] = None,
    ) -> OperationResult:
        """删除解析记录"""
        if not domain_name:
            return OperationResult(
                success=False,
                error_message="Cloudflare 删除记录需要 domain_name 参数",
            )
        zone_id = self._get_zone_id(domain_name)

        try:
            resp = self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
            if resp.get("success"):
                return OperationResult(success=True, data={"record_id": record_id})
            return OperationResult(
                success=False,
                error_message=str(resp.get("errors")),
            )
        except Exception as e:
            return OperationResult(success=False, error_message=str(e))

    def close(self) -> None:
        """关闭 session"""
        self._session.close()
