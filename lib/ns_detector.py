#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : ns_detector.py
Function: NS 记录识别服务，根据 NS 服务器名称识别域名托管平台
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 纯 Python 实现，零外部依赖（dnspython 可选）
"""

import re
import subprocess
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class NSDetectorService:
    """
    NS 记录识别服务

    根据 NS 服务器名称模式识别域名托管平台
    """

    # NS 服务器匹配规则（按优先级排序）
    NS_PATTERNS: Dict[str, Dict[str, Any]] = {
        "aliyun": {
            "patterns": [
                r"\.alidns\.com$",
                r"dns\d+\.hichina\.com$",
                r"vip\d+\.alidns\.com$",
            ],
            "name": "阿里云 DNS",
            "provider_type": "aliyun",
        },
        "cloudflare": {
            "patterns": [
                r"\.ns\.cloudflare\.com$",
            ],
            "name": "Cloudflare",
            "provider_type": "cloudflare",
        },
        "aws": {
            "patterns": [
                r"\.awsdns-\d+\.(com|net|org|co\.uk)$",
            ],
            "name": "AWS Route53",
            "provider_type": "aws",
        },
        "dnspod": {
            "patterns": [
                r"\.dnspod\.net$",
                r"f1g1ns\d+\.dnspod\.net$",
            ],
            "name": "DNSPod (腾讯云)",
            "provider_type": "dnspod",
        },
        "cloudns": {
            "patterns": [
                r"ns\d+\.dns\.com$",
                r"\.cloudns\.net$",
            ],
            "name": "Cloud DNS",
            "provider_type": "cloudns",
        },
        "huaweicloud": {
            "patterns": [
                r"\.hwclouds-dns\.com$",
                r"ns\d+\.hwclouds-dns\.com$",
            ],
            "name": "华为云 DNS",
            "provider_type": "huaweicloud",
        },
        "godaddy": {
            "patterns": [
                r"\.domaincontrol\.com$",
            ],
            "name": "GoDaddy",
            "provider_type": "godaddy",
        },
        "namecheap": {
            "patterns": [
                r"\.registrar-servers\.com$",
            ],
            "name": "Namecheap",
            "provider_type": "namecheap",
        },
        "azure": {
            "patterns": [
                r"\.azure-dns\.(com|net|org|info)$",
            ],
            "name": "Azure DNS",
            "provider_type": "azure",
        },
        "google_cloud": {
            "patterns": [
                r"\.googledomains\.com$",
                r"ns-cloud-[a-z]\d+\.googledomains\.com$",
            ],
            "name": "Google Cloud DNS",
            "provider_type": "google_cloud",
        },
        "scdn": {
            "patterns": [
                r"\.byteshieldns\.com$",
            ],
            "name": "白山云 DNS",
            "provider_type": "scdn",
        },
        "cdnw": {
            "patterns": [
                r"\.cdnetdns\.net$",
            ],
            "name": "CDNetworks DNS",
            "provider_type": "cdnw",
        },
    }

    def __init__(self, custom_patterns: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        初始化 NS 识别服务

        Args:
            custom_patterns: 自定义平台匹配规则（可选）
        """
        self.patterns = self.NS_PATTERNS.copy()
        if custom_patterns:
            self.patterns.update(custom_patterns)

        # 预编译正则表达式
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        for provider_key, config in self.patterns.items():
            self._compiled_patterns[provider_key] = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in config["patterns"]
            ]

    def detect_provider(self, ns_servers: List[str]) -> Dict[str, Any]:
        """
        根据 NS 服务器列表识别托管平台

        Args:
            ns_servers: NS 服务器列表

        Returns:
            识别结果字典
        """
        if not ns_servers:
            return self._unknown_result([])

        match_counts: Dict[str, int] = {}
        matched_ns_by_provider: Dict[str, List[str]] = {}

        for ns_server in ns_servers:
            ns_lower = ns_server.lower().rstrip(".")

            for provider_key, patterns in self._compiled_patterns.items():
                for pattern in patterns:
                    if pattern.search(ns_lower):
                        match_counts[provider_key] = match_counts.get(provider_key, 0) + 1
                        if provider_key not in matched_ns_by_provider:
                            matched_ns_by_provider[provider_key] = []
                        matched_ns_by_provider[provider_key].append(ns_server)
                        break

        if not match_counts:
            return self._unknown_result(ns_servers)

        best_key = max(match_counts, key=match_counts.get)
        confidence = round(match_counts[best_key] / len(ns_servers), 2)
        config = self.patterns[best_key]

        return {
            "provider_key": best_key,
            "provider_name": config["name"],
            "provider_type": config["provider_type"],
            "confidence": confidence,
            "matched_ns": matched_ns_by_provider[best_key],
            "all_ns": ns_servers,
        }

    def _unknown_result(self, ns_servers: List[str]) -> Dict[str, Any]:
        """返回未知平台结果"""
        return {
            "provider_key": "unknown",
            "provider_name": "未知平台",
            "provider_type": "unknown",
            "confidence": 0.0,
            "matched_ns": [],
            "all_ns": ns_servers,
        }

    def get_supported_providers(self) -> List[Dict[str, str]]:
        """获取支持的平台列表"""
        return [
            {
                "provider_key": key,
                "provider_name": config["name"],
                "provider_type": config["provider_type"],
            }
            for key, config in self.patterns.items()
        ]


def resolve_ns(domain: str) -> List[str]:
    """
    解析域名的 NS 记录

    优先使用 dnspython，fallback 到 dig 子进程

    Args:
        domain: 域名

    Returns:
        NS 服务器列表
    """
    # 尝试 dnspython
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "NS")
        return [str(rdata.target).rstrip(".") for rdata in answers]
    except ImportError:
        logger.debug("dnspython 未安装，使用 dig fallback")
    except Exception as e:
        logger.warning("dnspython 查询失败: %s，尝试 dig fallback", e)

    # fallback: dig
    try:
        result = subprocess.run(
            ["dig", "+short", "NS", domain],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [ns.rstrip(".") for ns in result.stdout.strip().split("\n") if ns.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("dig 查询失败: %s", e)

    return []


def detect_domain_provider(domain: str) -> Dict[str, Any]:
    """
    便捷函数：解析 NS 并识别平台

    Args:
        domain: 域名

    Returns:
        识别结果字典
    """
    ns_servers = resolve_ns(domain)
    detector = NSDetectorService()
    result = detector.detect_provider(ns_servers)
    result["domain"] = domain
    return result
