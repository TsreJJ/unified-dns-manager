#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_provider_base.py
Function: DNS Provider 同步抽象基类 + 数据类
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 定义统一 DNS 记录 CRUD 接口，CLI 和 Web API 均可直接使用
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import List, Optional, Any


@dataclass
class RecordInfo:
    """DNS 记录信息数据类"""

    record_id: str
    domain_name: str
    rr: str          # 主机记录（www, @, *）
    type: str        # A, AAAA, CNAME, MX, TXT
    value: str
    ttl: int = 600
    priority: Optional[int] = None
    line: str = "default"
    status: str = "ENABLE"
    remark: Optional[str] = None

    def to_dict(self) -> dict:
        """转为字典，方便 JSON 序列化"""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class OperationResult:
    """操作结果数据类"""

    success: bool
    data: Optional[Any] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """转为字典，方便 JSON 序列化"""
        return {k: v for k, v in asdict(self).items() if v is not None}


class DNSProvider(ABC):
    """
    DNS Provider 同步抽象基类
    聚焦 DNS 记录 CRUD，所有平台 Provider 必须实现此接口
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 名称标识（aliyun / cloudflare / aws / cdnw）"""
        pass

    @abstractmethod
    def list_records(
        self,
        domain_name: str,
        rr_keyword: Optional[str] = None,
        type_keyword: Optional[str] = None,
    ) -> List[RecordInfo]:
        """
        列出域名的解析记录

        参数：
            domain_name: 域名
            rr_keyword: 主机记录关键字
            type_keyword: 记录类型过滤
        返回：
            记录列表
        """
        pass

    @abstractmethod
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
        """
        添加解析记录

        参数：
            domain_name: 域名
            rr: 主机记录（如 www, @, *）
            record_type: 记录类型（A, AAAA, CNAME, MX, TXT）
            value: 记录值
            ttl: TTL（秒）
            priority: MX 优先级
            line: 解析线路
        返回：
            操作结果（data 中包含 record_id）
        """
        pass

    @abstractmethod
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
        """
        更新解析记录

        参数：
            record_id: 记录 ID
            rr: 主机记录
            record_type: 记录类型
            value: 记录值
            ttl: TTL（秒）
            priority: MX 优先级
            line: 解析线路
            domain_name: 域名（部分平台需要）
        返回：
            操作结果
        """
        pass

    @abstractmethod
    def delete_record(
        self,
        record_id: str,
        domain_name: Optional[str] = None,
        rr: Optional[str] = None,
        record_type: Optional[str] = None,
        value: Optional[str] = None,
    ) -> OperationResult:
        """
        删除解析记录

        参数：
            record_id: 记录 ID
            domain_name: 域名（部分平台需要）
            rr: 主机记录（Route53 需要）
            record_type: 记录类型（Route53 需要）
            value: 记录值（Route53 需要）
        返回：
            操作结果
        """
        pass

    def close(self) -> None:
        """关闭 Provider，释放资源"""
        pass

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
