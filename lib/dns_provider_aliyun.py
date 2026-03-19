#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_provider_aliyun.py
Function: 阿里云 DNS Provider 实现
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 自包含 HMAC-SHA1 签名 + STS AssumeRole
环境变量: ALICLOUD_ACCESS_KEY_ID, ALICLOUD_ACCESS_KEY_SECRET, ALICLOUD_ROLE_ARN(可选)
"""

import os
import json
import hmac
import base64
import hashlib
import urllib.parse
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional

import requests

from lib.dns_provider_base import DNSProvider, RecordInfo, OperationResult

logger = logging.getLogger(__name__)


class AliyunDNSProvider(DNSProvider):
    """阿里云 DNS Provider"""

    DNS_ENDPOINT = "alidns.aliyuncs.com"
    DNS_API_VERSION = "2015-01-09"
    STS_ENDPOINT = "sts.aliyuncs.com"
    STS_API_VERSION = "2015-04-01"

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        access_key_secret: Optional[str] = None,
        role_arn: Optional[str] = None,
    ):
        """
        初始化阿里云 Provider

        Args:
            access_key_id: AK，默认从环境变量获取
            access_key_secret: SK，默认从环境变量获取
            role_arn: STS Role ARN（可选）
        """
        self._ak = access_key_id or os.getenv("ALICLOUD_ACCESS_KEY_ID")
        self._sk = access_key_secret or os.getenv("ALICLOUD_ACCESS_KEY_SECRET")
        self._role_arn = role_arn or os.getenv("ALICLOUD_ROLE_ARN")

        if not self._ak or not self._sk:
            self._load_from_config()

        if not self._ak or not self._sk:
            raise ValueError("请设置 ALICLOUD_ACCESS_KEY_ID 和 ALICLOUD_ACCESS_KEY_SECRET")

        self._sts_creds = None

    def _load_from_config(self):
        """从 aliyun CLI 配置文件加载凭证"""
        config_path = os.path.expanduser("~/.aliyun/config.json")
        if not os.path.exists(config_path):
            return

        profile = os.getenv("ALICLOUD_PROFILE", "a05_devuser01")
        with open(config_path, "r") as f:
            config = json.load(f)

        for p in config.get("profiles", []):
            if p.get("name") == profile:
                self._ak = self._ak or p.get("access_key_id")
                self._sk = self._sk or p.get("access_key_secret")
                break

    @property
    def provider_name(self) -> str:
        return "aliyun"

    def _sign(self, params: dict, secret: str) -> str:
        """HMAC-SHA1 签名"""
        sorted_params = sorted(params.items())
        query = urllib.parse.urlencode(sorted_params, quote_via=urllib.parse.quote)
        string_to_sign = f"GET&%2F&{urllib.parse.quote(query, safe='')}"
        key = (secret + "&").encode("utf-8")
        sig = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1)
        return base64.b64encode(sig.digest()).decode("utf-8")

    def _call_api(
        self,
        endpoint: str,
        action: str,
        version: str,
        ak: str,
        sk: str,
        security_token: Optional[str] = None,
        extra_params: Optional[dict] = None,
    ) -> dict:
        """调用阿里云 API"""
        params = {
            "Action": action,
            "Format": "JSON",
            "Version": version,
            "AccessKeyId": ak,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
        }
        if security_token:
            params["SecurityToken"] = security_token
        if extra_params:
            params.update(extra_params)

        params["Signature"] = self._sign(params, sk)
        resp = requests.get(f"https://{endpoint}/", params=params, timeout=30)
        result = resp.json()

        if "Code" in result and result["Code"] != "OK":
            raise RuntimeError(f"API 错误: {result.get('Message', result)}")
        return result

    def _ensure_sts(self):
        """确保 STS 凭证可用"""
        if not self._role_arn:
            return
        if self._sts_creds:
            return

        result = self._call_api(
            self.STS_ENDPOINT, "AssumeRole", self.STS_API_VERSION,
            self._ak, self._sk,
            extra_params={
                "RoleArn": self._role_arn,
                "RoleSessionName": "dns-manager",
            },
        )
        creds = result.get("Credentials")
        if not creds:
            raise RuntimeError(f"AssumeRole 失败: {result}")

        self._sts_creds = {
            "ak": creds["AccessKeyId"],
            "sk": creds["AccessKeySecret"],
            "token": creds["SecurityToken"],
        }

    def _dns_api(self, action: str, params: Optional[dict] = None) -> dict:
        """调用 DNS API"""
        self._ensure_sts()
        if self._sts_creds:
            return self._call_api(
                self.DNS_ENDPOINT, action, self.DNS_API_VERSION,
                self._sts_creds["ak"], self._sts_creds["sk"],
                security_token=self._sts_creds["token"],
                extra_params=params,
            )
        return self._call_api(
            self.DNS_ENDPOINT, action, self.DNS_API_VERSION,
            self._ak, self._sk,
            extra_params=params,
        )

    def list_records(
        self,
        domain_name: str,
        rr_keyword: Optional[str] = None,
        type_keyword: Optional[str] = None,
    ) -> List[RecordInfo]:
        """列出解析记录"""
        all_records = []
        page = 1

        while True:
            params = {
                "DomainName": domain_name,
                "PageSize": "100",
                "PageNumber": str(page),
            }
            if rr_keyword:
                params["RRKeyWord"] = rr_keyword
            if type_keyword:
                params["TypeKeyWord"] = type_keyword

            result = self._dns_api("DescribeDomainRecords", params)
            records = result.get("DomainRecords", {}).get("Record", [])
            if not records:
                break

            for r in records:
                all_records.append(RecordInfo(
                    record_id=r["RecordId"],
                    domain_name=domain_name,
                    rr=r["RR"],
                    type=r["Type"],
                    value=r["Value"],
                    ttl=r.get("TTL", 600),
                    priority=r.get("Priority"),
                    line=r.get("Line", "default"),
                    status=r.get("Status", "ENABLE"),
                    remark=r.get("Remark"),
                ))

            if len(records) < 100:
                break
            page += 1

        return all_records

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
        params = {
            "DomainName": domain_name,
            "RR": rr,
            "Type": record_type.upper(),
            "Value": value,
            "TTL": str(ttl),
            "Line": line,
        }
        if priority is not None:
            params["Priority"] = str(priority)

        try:
            result = self._dns_api("AddDomainRecord", params)
            return OperationResult(
                success=True,
                data={"record_id": result.get("RecordId")},
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
        params = {
            "RecordId": record_id,
            "RR": rr,
            "Type": record_type.upper(),
            "Value": value,
            "TTL": str(ttl),
            "Line": line,
        }
        if priority is not None:
            params["Priority"] = str(priority)

        try:
            self._dns_api("UpdateDomainRecord", params)
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
        try:
            self._dns_api("DeleteDomainRecord", {"RecordId": record_id})
            return OperationResult(success=True, data={"record_id": record_id})
        except Exception as e:
            return OperationResult(success=False, error_message=str(e))
