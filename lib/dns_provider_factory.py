#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_provider_factory.py
Function: DNS Provider 工厂 + 自动检测
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 根据平台类型或域名 NS 记录自动创建对应 Provider
"""

import logging
from enum import Enum
from typing import Optional

from lib.dns_provider_base import DNSProvider

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    """支持的 Provider 类型"""
    ALIYUN = "aliyun"
    CLOUDFLARE = "cloudflare"
    AWS = "aws"
    CDNW = "cdnw"


class DNSProviderFactory:
    """DNS Provider 工厂"""

    @staticmethod
    def get_provider(provider_type: str, **kwargs) -> DNSProvider:
        """
        根据类型创建 Provider

        Args:
            provider_type: 平台类型（aliyun/cloudflare/aws/cdnw）
            **kwargs: 平台特定凭证参数

        Returns:
            DNSProvider 实例
        """
        ptype = provider_type.lower()

        if ptype == ProviderType.ALIYUN:
            from lib.dns_provider_aliyun import AliyunDNSProvider
            return AliyunDNSProvider(
                access_key_id=kwargs.get("access_key_id"),
                access_key_secret=kwargs.get("access_key_secret"),
                role_arn=kwargs.get("role_arn"),
            )

        elif ptype == ProviderType.CLOUDFLARE:
            from lib.dns_provider_cloudflare import CloudflareDNSProvider
            return CloudflareDNSProvider(
                api_token=kwargs.get("api_token"),
            )

        elif ptype == ProviderType.AWS:
            from lib.dns_provider_route53 import Route53DNSProvider
            return Route53DNSProvider(
                aws_access_key_id=kwargs.get("aws_access_key_id"),
                aws_secret_access_key=kwargs.get("aws_secret_access_key"),
                region_name=kwargs.get("region_name", "us-east-1"),
            )

        elif ptype == ProviderType.CDNW:
            from lib.dns_provider_cdnw import CDNWDNSProvider
            return CDNWDNSProvider(
                access_key=kwargs.get("access_key"),
                secret_key=kwargs.get("secret_key"),
            )

        else:
            raise ValueError(
                f"不支持的平台类型: {provider_type}，"
                f"支持: {', '.join(t.value for t in ProviderType)}"
            )

    @staticmethod
    def auto_detect(domain: str, **kwargs) -> DNSProvider:
        """
        通过 NS 检测自动创建 Provider

        Args:
            domain: 域名
            **kwargs: 凭证参数（透传给 get_provider）

        Returns:
            DNSProvider 实例
        """
        from lib.ns_detector import resolve_ns, NSDetectorService

        ns_servers = resolve_ns(domain)
        if not ns_servers:
            raise ValueError(f"无法解析域名 {domain} 的 NS 记录")

        detector = NSDetectorService()
        result = detector.detect_provider(ns_servers)

        provider_type = result.get("provider_type", "unknown")
        confidence = result.get("confidence", 0)

        if provider_type == "unknown" or confidence < 0.5:
            raise ValueError(
                f"无法识别域名 {domain} 的托管平台 "
                f"(NS: {', '.join(ns_servers)})"
            )

        supported = {t.value for t in ProviderType}
        if provider_type not in supported:
            raise ValueError(
                f"域名 {domain} 托管在 {result.get('provider_name')} ({provider_type})，"
                f"当前仅支持: {', '.join(supported)}"
            )

        logger.info(
            "域名 %s 检测到托管平台: %s (置信度: %.0f%%)",
            domain, result.get("provider_name"), confidence * 100,
        )

        return DNSProviderFactory.get_provider(provider_type, **kwargs)

    @staticmethod
    def list_supported() -> list:
        """列出支持的平台"""
        return [{"type": t.value, "name": t.name} for t in ProviderType]
