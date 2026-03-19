#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_provider_route53.py
Function: AWS Route53 DNS Provider 实现
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 使用 boto3 同步客户端，Hosted Zone 自动查找
环境变量: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
"""

import os
import base64
import logging
from typing import List, Optional

from lib.dns_provider_base import DNSProvider, RecordInfo, OperationResult

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError, NoCredentialsError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


class Route53DNSProvider(DNSProvider):
    """AWS Route53 DNS Provider"""

    def __init__(
        self,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region_name: str = "us-east-1",
    ):
        """
        初始化 Route53 Provider

        Args:
            aws_access_key_id: AK，默认从环境变量获取
            aws_secret_access_key: SK，默认从环境变量获取
            region_name: AWS 区域
        """
        if not HAS_BOTO3:
            raise ImportError("Route53 Provider 需要 boto3，请执行: pip install boto3")

        ak = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        sk = aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")

        config = BotoConfig(
            region_name=region_name,
            retries={"max_attempts": 3, "mode": "adaptive"},
            read_timeout=30,
            connect_timeout=10,
        )

        try:
            if ak and sk:
                self._client = boto3.client(
                    "route53",
                    aws_access_key_id=ak,
                    aws_secret_access_key=sk,
                    config=config,
                )
            else:
                self._client = boto3.client("route53", config=config)
        except NoCredentialsError:
            raise ValueError("未找到 AWS 凭证，请设置 AWS_ACCESS_KEY_ID 和 AWS_SECRET_ACCESS_KEY")

        # hosted zone 缓存
        self._zone_cache: dict = {}

    @property
    def provider_name(self) -> str:
        return "aws"

    def _get_zone_id(self, domain: str) -> str:
        """获取 Hosted Zone ID（带缓存）"""
        parts = domain.split(".")
        zone_name = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        if not zone_name.endswith("."):
            zone_name += "."

        if zone_name in self._zone_cache:
            return self._zone_cache[zone_name]

        paginator = self._client.get_paginator("list_hosted_zones")
        for page in paginator.paginate():
            for zone in page["HostedZones"]:
                if zone["Name"] == zone_name:
                    zone_id = zone["Id"].replace("/hostedzone/", "")
                    self._zone_cache[zone_name] = zone_id
                    return zone_id

        raise ValueError(f"找不到域名 {zone_name} 的 Hosted Zone")

    @staticmethod
    def _make_record_id(name: str, rtype: str, value: str) -> str:
        """合成 record_id（Route53 无原生 record ID）"""
        raw = f"{name}:{rtype}:{value}"
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @staticmethod
    def _extract_rr(name: str, domain: str) -> str:
        """从 FQDN 提取主机记录"""
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        fqdn = name.rstrip(".")
        if fqdn == zone:
            return "@"
        suffix = f".{zone}"
        if fqdn.endswith(suffix):
            return fqdn[: -len(suffix)]
        return fqdn

    def _to_fqdn(self, rr: str, domain: str) -> str:
        """将主机记录转为 FQDN"""
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        if rr == "@":
            name = zone
        else:
            name = f"{rr}.{zone}"
        if not name.endswith("."):
            name += "."
        return name

    def list_records(
        self,
        domain_name: str,
        rr_keyword: Optional[str] = None,
        type_keyword: Optional[str] = None,
    ) -> List[RecordInfo]:
        """列出解析记录"""
        zone_id = self._get_zone_id(domain_name)
        paginator = self._client.get_paginator("list_resource_record_sets")
        records = []

        for page in paginator.paginate(HostedZoneId=zone_id):
            for rset in page["ResourceRecordSets"]:
                rtype = rset["Type"]
                rr = self._extract_rr(rset["Name"], domain_name)

                if type_keyword and rtype.upper() != type_keyword.upper():
                    continue
                if rr_keyword and rr_keyword.lower() not in rr.lower():
                    continue

                values = []
                if "ResourceRecords" in rset:
                    values = [r["Value"] for r in rset["ResourceRecords"]]
                elif "AliasTarget" in rset:
                    values = [rset["AliasTarget"]["DNSName"]]

                ttl = rset.get("TTL", 300)

                for val in values:
                    display_val = val.strip('"') if rtype == "TXT" else val
                    records.append(RecordInfo(
                        record_id=self._make_record_id(rset["Name"], rtype, val),
                        domain_name=domain_name,
                        rr=rr,
                        type=rtype,
                        value=display_val,
                        ttl=ttl,
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
        fqdn = self._to_fqdn(rr, domain_name)

        resource_records = []
        if record_type.upper() == "TXT":
            resource_records.append({"Value": f'"{value}"'})
        elif record_type.upper() == "MX" and priority is not None:
            resource_records.append({"Value": f"{priority} {value}"})
        else:
            resource_records.append({"Value": value})

        change_batch = {
            "Changes": [{
                "Action": "CREATE",
                "ResourceRecordSet": {
                    "Name": fqdn,
                    "Type": record_type.upper(),
                    "TTL": ttl,
                    "ResourceRecords": resource_records,
                },
            }],
        }

        try:
            resp = self._client.change_resource_record_sets(
                HostedZoneId=zone_id, ChangeBatch=change_batch,
            )
            record_id = self._make_record_id(fqdn, record_type.upper(), resource_records[0]["Value"])
            return OperationResult(
                success=True,
                data={"record_id": record_id, "change_id": resp["ChangeInfo"]["Id"]},
            )
        except ClientError as e:
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
        """更新解析记录（Route53 使用 UPSERT）"""
        if not domain_name:
            return OperationResult(
                success=False,
                error_message="Route53 更新记录需要 domain_name 参数",
            )
        zone_id = self._get_zone_id(domain_name)
        fqdn = self._to_fqdn(rr, domain_name)

        resource_records = []
        if record_type.upper() == "TXT":
            resource_records.append({"Value": f'"{value}"'})
        elif record_type.upper() == "MX" and priority is not None:
            resource_records.append({"Value": f"{priority} {value}"})
        else:
            resource_records.append({"Value": value})

        change_batch = {
            "Changes": [{
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": fqdn,
                    "Type": record_type.upper(),
                    "TTL": ttl,
                    "ResourceRecords": resource_records,
                },
            }],
        }

        try:
            resp = self._client.change_resource_record_sets(
                HostedZoneId=zone_id, ChangeBatch=change_batch,
            )
            new_id = self._make_record_id(fqdn, record_type.upper(), resource_records[0]["Value"])
            return OperationResult(
                success=True,
                data={"record_id": new_id, "change_id": resp["ChangeInfo"]["Id"]},
            )
        except ClientError as e:
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
        if not all([domain_name, rr, record_type, value]):
            return OperationResult(
                success=False,
                error_message="Route53 删除记录需要 domain_name, rr, record_type, value 参数",
            )
        zone_id = self._get_zone_id(domain_name)
        fqdn = self._to_fqdn(rr, domain_name)

        resource_records = []
        if record_type.upper() == "TXT":
            resource_records.append({"Value": f'"{value}"'})
        else:
            resource_records.append({"Value": value})

        change_batch = {
            "Changes": [{
                "Action": "DELETE",
                "ResourceRecordSet": {
                    "Name": fqdn,
                    "Type": record_type.upper(),
                    "TTL": 300,
                    "ResourceRecords": resource_records,
                },
            }],
        }

        try:
            self._client.change_resource_record_sets(
                HostedZoneId=zone_id, ChangeBatch=change_batch,
            )
            return OperationResult(success=True, data={"record_id": record_id})
        except ClientError as e:
            return OperationResult(success=False, error_message=str(e))
