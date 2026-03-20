#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_api.py
Function: 统一 DNS 操作 Facade — 供外部项目一行调用
Author  : jim
Created : 2026-03-19
Version : 1.1.0
说明: 封装 Provider 创建、环境变量加载、资源释放，外部只需 import 函数即可
使用:
    from lib.dns_api import dns_add_record, dns_list_records
    dns_add_record("zc2tv.com", "test", "CNAME", "test.zc2tv.com.wcdnga.com")
"""

import os
import logging
from typing import List, Optional

from lib.dns_provider_base import RecordInfo, OperationResult
from lib.dns_provider_factory import DNSProviderFactory

logger = logging.getLogger(__name__)

# 默认环境变量文件
_DEFAULT_ENV = os.path.expanduser("~/.credentials/unified-dns-manager.env")


def _ensure_env():
    """
    确保环境变量已加载
    如果关键凭证变量均为空，自动加载默认 env 文件
    """
    key_vars = [
        "ALICLOUD_ACCESS_KEY_ID", "CLOUDFLARE_API_TOKEN",
        "AWS_ACCESS_KEY_ID", "CDNW_ACCESS_KEY",
    ]
    if any(os.getenv(v) for v in key_vars):
        return

    if os.path.exists(_DEFAULT_ENV):
        with open(_DEFAULT_ENV, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    os.environ[k.strip()] = v.strip().strip("'\"")
        logger.debug("已自动加载环境变量: %s", _DEFAULT_ENV)


def _get_provider(domain: str, provider: Optional[str] = None):
    """
    获取 Provider 实例

    Args:
        domain: 域名
        provider: 平台类型（可选，不指定则自动检测）
    Returns:
        DNSProvider 实例
    """
    _ensure_env()
    if provider:
        return DNSProviderFactory.get_provider(provider)
    return DNSProviderFactory.auto_detect(domain)


def dns_list_records(
    domain: str,
    rr: Optional[str] = None,
    record_type: Optional[str] = None,
    provider: Optional[str] = None,
) -> List[RecordInfo]:
    """
    列出 DNS 记录

    Args:
        domain: 域名（如 zc2tv.com）
        rr: 主机记录过滤（如 www）
        record_type: 记录类型过滤（如 A, CNAME）
        provider: 强制指定平台（可选）
    Returns:
        RecordInfo 列表
    """
    p = _get_provider(domain, provider)
    try:
        return p.list_records(domain, rr_keyword=rr, type_keyword=record_type)
    finally:
        p.close()


def dns_add_record(
    domain: str,
    rr: str,
    record_type: str,
    value: str,
    ttl: int = 600,
    priority: Optional[int] = None,
    provider: Optional[str] = None,
) -> OperationResult:
    """
    添加 DNS 记录

    Args:
        domain: 域名（如 zc2tv.com）
        rr: 主机记录（如 www, @, *）
        record_type: 记录类型（A, AAAA, CNAME, MX, TXT）
        value: 记录值
        ttl: TTL 秒数（默认 600）
        priority: MX 优先级（可选）
        provider: 强制指定平台（可选）
    Returns:
        OperationResult
    """
    p = _get_provider(domain, provider)
    try:
        return p.add_record(domain, rr, record_type, value, ttl=ttl, priority=priority)
    finally:
        p.close()


def dns_update_record(
    domain: str,
    rr: str,
    record_type: str,
    value: str,
    ttl: int = 600,
    priority: Optional[int] = None,
    record_id: Optional[str] = None,
    provider: Optional[str] = None,
) -> OperationResult:
    """
    更新 DNS 记录（未指定 record_id 时自动查找）

    Args:
        domain: 域名
        rr: 主机记录
        record_type: 记录类型
        value: 新记录值
        ttl: TTL 秒数（默认 600）
        priority: MX 优先级（可选）
        record_id: 记录 ID（可选，不指定则按 rr+type 自动匹配）
        provider: 强制指定平台（可选）
    Returns:
        OperationResult
    """
    p = _get_provider(domain, provider)
    try:
        # 未指定 record_id 时自动查找
        if not record_id:
            records = p.list_records(domain, rr_keyword=rr, type_keyword=record_type)
            matching = [r for r in records if r.rr == rr and r.type.upper() == record_type.upper()]
            if not matching:
                return OperationResult(
                    success=False,
                    error_message=f"找不到匹配的记录 {rr} ({record_type})",
                )
            record_id = matching[0].record_id

        return p.update_record(
            record_id, rr, record_type, value,
            ttl=ttl, priority=priority, domain_name=domain,
        )
    finally:
        p.close()


def dns_delete_record(
    domain: str,
    rr: Optional[str] = None,
    record_type: Optional[str] = None,
    record_id: Optional[str] = None,
    provider: Optional[str] = None,
) -> OperationResult:
    """
    删除 DNS 记录（未指定 record_id 时按 rr+type 自动查找）

    Args:
        domain: 域名
        rr: 主机记录（和 record_type 配合自动查找）
        record_type: 记录类型
        record_id: 记录 ID（可选）
        provider: 强制指定平台（可选）
    Returns:
        OperationResult
    """
    p = _get_provider(domain, provider)
    try:
        value = None
        if not record_id:
            if not rr or not record_type:
                return OperationResult(
                    success=False,
                    error_message="删除记录需要 record_id 或 rr + record_type",
                )
            records = p.list_records(domain, rr_keyword=rr, type_keyword=record_type)
            matching = [r for r in records if r.rr == rr and r.type.upper() == record_type.upper()]
            if not matching:
                return OperationResult(
                    success=False,
                    error_message=f"找不到匹配的记录 {rr} ({record_type})",
                )
            record_id = matching[0].record_id
            value = matching[0].value

        return p.delete_record(
            record_id, domain_name=domain,
            rr=rr, record_type=record_type, value=value,
        )
    finally:
        p.close()
