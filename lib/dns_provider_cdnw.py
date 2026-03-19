#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_provider_cdnw.py
Function: CDNetworks DNS Provider 实现
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 内置 AkSk 签名认证，写操作后自动 deploy
环境变量: CDNW_ACCESS_KEY, CDNW_SECRET_KEY
"""

import logging
from typing import List, Optional

from lib.dns_provider_base import DNSProvider, RecordInfo, OperationResult
from lib.cdnw_client import CDNWClient

logger = logging.getLogger(__name__)


class CDNWDNSProvider(DNSProvider):
    """CDNetworks DNS Provider"""

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        """
        初始化 CDNW Provider

        Args:
            access_key: AK，默认从 CDNW_ACCESS_KEY 环境变量获取
            secret_key: SK，默认从 CDNW_SECRET_KEY 环境变量获取
        """
        self._client = CDNWClient(access_key=access_key, secret_key=secret_key)
        # zone_id 缓存: domain_name -> zone_id
        self._zone_cache: dict = {}

    @property
    def provider_name(self) -> str:
        return "cdnw"

    def _get_zone_id(self, domain_name: str) -> int:
        """获取域名的 Zone ID（带缓存）"""
        if domain_name in self._zone_cache:
            return self._zone_cache[domain_name]

        data = self._client.request(f"/api/clouddns/zones?name={domain_name}&pageSize=100")
        if data.get("code") != "0":
            raise ValueError(f"查询 Zone 失败: {data.get('message', data)}")

        results = data.get("data", {}).get("results", [])
        for zone in results:
            if zone.get("name") == domain_name:
                zone_id = zone["zoneId"]
                self._zone_cache[domain_name] = zone_id
                return zone_id

        raise ValueError(f"找不到域名 {domain_name} 的 Zone")

    def _deploy(self, zone_id: int) -> bool:
        """部署 Zone 到 production 环境"""
        try:
            data = self._client.request(
                f"/api/clouddns/zones/{zone_id}/deployment?deployType=production",
                method="POST",
            )
            if data.get("code") == "0":
                logger.info("Zone %s 部署到 production 成功", zone_id)
                return True
            logger.warning("Zone %s 部署失败: %s", zone_id, data.get("message"))
            return False
        except Exception as e:
            logger.warning("Zone %s 部署异常: %s", zone_id, e)
            return False

    def list_records(
        self,
        domain_name: str,
        rr_keyword: Optional[str] = None,
        type_keyword: Optional[str] = None,
    ) -> List[RecordInfo]:
        """列出解析记录"""
        zone_id = self._get_zone_id(domain_name)
        uri = f"/api/clouddns/zones/{zone_id}/records"

        params = []
        if rr_keyword:
            params.append(f"hostName={rr_keyword}")
        if type_keyword:
            params.append(f"types={type_keyword.upper()}")
        if params:
            uri += "?" + "&".join(params)

        data = self._client.request(uri)
        if data.get("code") != "0":
            raise RuntimeError(f"查询记录失败: {data.get('message', data)}")

        records = []
        response_data = data.get("data", {})
        for record_type, record_list in response_data.items():
            if not isinstance(record_list, list):
                continue
            for r in record_list:
                host_name = r.get("hostName", "@")
                value = r.get("value", "")
                if record_type.upper() == "MX":
                    priority = r.get("preference") or r.get("data")
                else:
                    priority = None

                records.append(RecordInfo(
                    record_id=str(r.get("recordId", "")),
                    domain_name=domain_name,
                    rr=host_name,
                    type=record_type.upper(),
                    value=value,
                    ttl=r.get("ttl", 3600),
                    priority=priority,
                    line="default",
                    status="ENABLE",
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

        record = {
            "hostName": rr,
            "type": record_type.upper(),
            "value": value,
            "ttl": ttl,
        }
        if record_type.upper() == "MX" and priority is not None:
            record["data"] = priority

        body = {"data": [record]}

        try:
            data = self._client.request(
                f"/api/clouddns/zones/{zone_id}/records",
                method="POST",
                body=body,
            )

            if data.get("code") != "0":
                error_msg = (
                    data.get("message")
                    or data.get("msg")
                    or data.get("errorMessage")
                    or "Unknown error"
                )
                return OperationResult(
                    success=False,
                    error_code=data.get("code"),
                    error_message=error_msg,
                )

            record_id = None
            response_data = data.get("data", {})
            for rtype, items in response_data.items():
                if isinstance(items, list) and items:
                    record_id = items[0].get("recordId")
                    break

            self._deploy(zone_id)

            return OperationResult(
                success=True,
                data={"record_id": str(record_id) if record_id else None, "zone_id": zone_id},
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
        """更新解析记录（先删除再新增）"""
        if not domain_name:
            return OperationResult(
                success=False,
                error_message="CDNW 更新记录需要 domain_name 参数",
            )

        del_result = self._delete_by_id(record_id, domain_name)
        if not del_result.success:
            return del_result

        return self.add_record(domain_name, rr, record_type, value, ttl, priority, line)

    def _delete_by_id(self, record_id: str, domain_name: str) -> OperationResult:
        """按 record_id 删除记录"""
        zone_id = self._get_zone_id(domain_name)

        try:
            data = self._client.request(
                f"/api/clouddns/zones/{zone_id}/records/{record_id}",
                method="DELETE",
            )

            if data.get("code") != "0":
                error_msg = data.get("message") or data.get("msg") or "Unknown error"
                return OperationResult(
                    success=False,
                    error_code=data.get("code"),
                    error_message=error_msg,
                )

            self._deploy(zone_id)
            return OperationResult(success=True, data={"record_id": record_id})
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
                error_message="CDNW 删除记录需要 domain_name 参数",
            )
        return self._delete_by_id(record_id, domain_name)
