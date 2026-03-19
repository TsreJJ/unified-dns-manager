#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : dns_cli.py
Function: 统一多平台 DNS 记录变更 CLI
Author  : jim
Created : 2026-03-19
Version : 1.0.0
说明: 自动判别域名归属平台，完成 DNS 解析记录 CRUD
使用: python3 dns_cli.py <command> <domain> [options]
"""

import os
import sys
import json
import argparse
import logging

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.dns_provider_base import RecordInfo, OperationResult
from lib.dns_provider_factory import DNSProviderFactory, ProviderType


def load_env_file(env_file: str):
    """
    加载环境变量文件

    Args:
        env_file: .env 文件路径
    """
    if not os.path.exists(env_file):
        print(f"错误: 环境变量文件不存在: {env_file}", file=sys.stderr)
        sys.exit(1)

    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                os.environ[key] = val


def print_table(headers: list, rows: list):
    """打印表格"""
    if not rows:
        print("无数据")
        return

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    header_line = "  ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))

    for row in rows:
        print("  ".join(f"{str(cell):<{widths[i]}}" for i, cell in enumerate(row)))


def get_provider(args):
    """根据参数获取 Provider"""
    if args.provider:
        return DNSProviderFactory.get_provider(args.provider)
    return DNSProviderFactory.auto_detect(args.domain)


def cmd_detect(args):
    """检测域名归属平台"""
    from lib.ns_detector import resolve_ns, NSDetectorService

    ns_servers = resolve_ns(args.domain)
    if not ns_servers:
        print(f"错误: 无法解析域名 {args.domain} 的 NS 记录", file=sys.stderr)
        return 1

    detector = NSDetectorService()
    result = detector.detect_provider(ns_servers)

    if args.output == "json":
        result["domain"] = args.domain
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"域名: {args.domain}")
        print(f"平台: {result['provider_name']}")
        print(f"类型: {result['provider_type']}")
        print(f"置信度: {result['confidence']:.0%}")
        print(f"NS 服务器: {', '.join(result['all_ns'])}")
    return 0


def cmd_list(args):
    """列出解析记录"""
    provider = get_provider(args)

    try:
        records = provider.list_records(
            args.domain,
            rr_keyword=args.rr,
            type_keyword=args.type,
        )

        if args.output == "json":
            print(json.dumps([r.to_dict() for r in records], indent=2, ensure_ascii=False))
        else:
            headers = ["记录ID", "主机记录", "类型", "值", "TTL", "状态"]
            rows = []
            for r in records:
                val = r.value[:50] + "..." if len(r.value) > 50 else r.value
                rows.append([r.record_id[:20], r.rr, r.type, val, r.ttl, r.status])
            print_table(headers, rows)
            print(f"\n平台: {provider.provider_name} | 共 {len(records)} 条记录")
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    finally:
        provider.close()


def cmd_add(args):
    """添加解析记录"""
    if args.dry_run:
        print(f"[DRY-RUN] 将添加记录:")
        print(f"  域名: {args.domain}")
        print(f"  主机记录: {args.rr}")
        print(f"  类型: {args.type}")
        print(f"  值: {args.value}")
        print(f"  TTL: {args.ttl}")
        if args.priority:
            print(f"  优先级: {args.priority}")
        return 0

    provider = get_provider(args)

    try:
        result = provider.add_record(
            args.domain,
            args.rr,
            args.type,
            args.value,
            ttl=args.ttl,
            priority=args.priority,
        )

        if args.output == "json":
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            if result.success:
                print(f"记录添加成功")
                if result.data and result.data.get("record_id"):
                    print(f"记录 ID: {result.data['record_id']}")
            else:
                print(f"记录添加失败: {result.error_message}", file=sys.stderr)
                return 1
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    finally:
        provider.close()


def cmd_update(args):
    """更新解析记录"""
    record_id = args.record_id

    if args.dry_run:
        print(f"[DRY-RUN] 将更新记录:")
        print(f"  域名: {args.domain}")
        print(f"  主机记录: {args.rr}")
        print(f"  类型: {args.type}")
        print(f"  新值: {args.value}")
        print(f"  TTL: {args.ttl}")
        if record_id:
            print(f"  记录ID: {record_id}")
        return 0

    provider = get_provider(args)

    try:
        if not record_id:
            records = provider.list_records(args.domain, rr_keyword=args.rr, type_keyword=args.type)
            matching = [r for r in records if r.rr == args.rr and r.type.upper() == args.type.upper()]
            if not matching:
                print(f"错误: 找不到匹配的记录 {args.rr} ({args.type})", file=sys.stderr)
                return 1
            if len(matching) > 1:
                print(f"警告: 找到 {len(matching)} 条匹配记录，使用第一条", file=sys.stderr)
            record_id = matching[0].record_id

        result = provider.update_record(
            record_id,
            args.rr,
            args.type,
            args.value,
            ttl=args.ttl,
            priority=args.priority,
            domain_name=args.domain,
        )

        if args.output == "json":
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            if result.success:
                print(f"记录更新成功: {record_id}")
            else:
                print(f"记录更新失败: {result.error_message}", file=sys.stderr)
                return 1
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    finally:
        provider.close()


def cmd_delete(args):
    """删除解析记录"""
    record_id = args.record_id

    if args.dry_run:
        print(f"[DRY-RUN] 将删除记录:")
        print(f"  域名: {args.domain}")
        print(f"  主机记录: {args.rr}")
        print(f"  类型: {args.type}")
        if record_id:
            print(f"  记录ID: {record_id}")
        return 0

    provider = get_provider(args)

    try:
        value = None
        if not record_id:
            if not args.rr or not args.type:
                print("错误: 删除记录需要 --record-id 或 --rr + --type", file=sys.stderr)
                return 1
            records = provider.list_records(args.domain, rr_keyword=args.rr, type_keyword=args.type)
            matching = [r for r in records if r.rr == args.rr and r.type.upper() == args.type.upper()]
            if not matching:
                print(f"错误: 找不到匹配的记录 {args.rr} ({args.type})", file=sys.stderr)
                return 1
            if len(matching) > 1:
                print(f"警告: 找到 {len(matching)} 条匹配记录，使用第一条", file=sys.stderr)
            record_id = matching[0].record_id
            value = matching[0].value

        result = provider.delete_record(
            record_id,
            domain_name=args.domain,
            rr=args.rr,
            record_type=args.type,
            value=value,
        )

        if args.output == "json":
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            if result.success:
                print(f"记录删除成功: {record_id}")
            else:
                print(f"记录删除失败: {result.error_message}", file=sys.stderr)
                return 1
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    finally:
        provider.close()


def create_parser() -> argparse.ArgumentParser:
    """创建命令行解析器"""
    parser = argparse.ArgumentParser(
        description="统一多平台 DNS 记录变更工具 v1.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 检测域名归属平台
  %(prog)s detect example.com

  # 列出解析记录
  %(prog)s list example.com --type A --rr www

  # 新增记录
  %(prog)s add example.com --rr www --type A --value 1.2.3.4 --ttl 600

  # 更新记录（自动查找 record-id）
  %(prog)s update example.com --rr www --type A --value 5.6.7.8

  # 删除记录
  %(prog)s delete example.com --rr www --type A

  # 强制指定平台
  %(prog)s list example.com --provider cloudflare

  # JSON 输出
  %(prog)s list example.com -o json

  # Dry-run 模式
  %(prog)s add example.com --rr test --type A --value 1.1.1.1 --dry-run

支持平台: aliyun, cloudflare, aws, cdnw
环境变量:
  ALICLOUD_ACCESS_KEY_ID / ALICLOUD_ACCESS_KEY_SECRET / ALICLOUD_ROLE_ARN
  CLOUDFLARE_API_TOKEN
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  CDNW_ACCESS_KEY / CDNW_SECRET_KEY
        """,
    )

    # 全局选项
    parser.add_argument(
        "--provider",
        choices=[t.value for t in ProviderType],
        help="强制指定平台（跳过 NS 检测）",
    )
    parser.add_argument(
        "--env-file",
        help="指定环境变量文件",
    )
    parser.add_argument(
        "-o", "--output",
        choices=["table", "json"],
        default="table",
        help="输出格式（默认: table）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示将执行的操作，不实际执行",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # detect
    detect_parser = subparsers.add_parser("detect", help="检测域名归属平台")
    detect_parser.add_argument("domain", help="域名")

    # list
    list_parser = subparsers.add_parser("list", help="列出解析记录")
    list_parser.add_argument("domain", help="域名")
    list_parser.add_argument("--type", help="记录类型过滤")
    list_parser.add_argument("--rr", help="主机记录过滤")

    # add
    add_parser = subparsers.add_parser("add", help="添加解析记录")
    add_parser.add_argument("domain", help="域名")
    add_parser.add_argument("--rr", required=True, help="主机记录（www, @, *）")
    add_parser.add_argument("--type", required=True, help="记录类型（A, AAAA, CNAME, MX, TXT）")
    add_parser.add_argument("--value", required=True, help="记录值")
    add_parser.add_argument("--ttl", type=int, default=600, help="TTL（默认: 600）")
    add_parser.add_argument("--priority", type=int, help="MX 优先级")

    # update
    update_parser = subparsers.add_parser("update", help="更新解析记录")
    update_parser.add_argument("domain", help="域名")
    update_parser.add_argument("--rr", required=True, help="主机记录")
    update_parser.add_argument("--type", required=True, help="记录类型")
    update_parser.add_argument("--value", required=True, help="新记录值")
    update_parser.add_argument("--ttl", type=int, default=600, help="TTL（默认: 600）")
    update_parser.add_argument("--priority", type=int, help="MX 优先级")
    update_parser.add_argument("--record-id", help="记录 ID（可选，不指定则自动查找）")

    # delete
    delete_parser = subparsers.add_parser("delete", help="删除解析记录")
    delete_parser.add_argument("domain", help="域名")
    delete_parser.add_argument("--rr", help="主机记录")
    delete_parser.add_argument("--type", help="记录类型")
    delete_parser.add_argument("--record-id", help="记录 ID（可选，不指定则通过 rr+type 查找）")

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # 配置日志
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 加载环境变量文件
    if args.env_file:
        load_env_file(args.env_file)

    # 分发命令
    commands = {
        "detect": cmd_detect,
        "list": cmd_list,
        "add": cmd_add,
        "update": cmd_update,
        "delete": cmd_delete,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
