# Unified DNS Manager - 统一多平台 DNS 记录变更系统

统一 CLI 入口，自动判别域名归属平台，完成 DNS 解析记录 CRUD。

## 支持平台

| 平台 | Provider | 环境变量 |
|------|----------|----------|
| 阿里云 DNS | `aliyun` | `ALICLOUD_ACCESS_KEY_ID`, `ALICLOUD_ACCESS_KEY_SECRET`, `ALICLOUD_ROLE_ARN`(可选) |
| Cloudflare | `cloudflare` | `CLOUDFLARE_API_TOKEN` |
| AWS Route53 | `aws` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| CDNetworks | `cdnw` | `CDNW_ACCESS_KEY`, `CDNW_SECRET_KEY` |

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

```bash
# 检测域名归属平台
python3 dns_cli.py detect example.com

# 列出解析记录
python3 dns_cli.py list example.com

# 按类型过滤
python3 dns_cli.py list example.com --type A --rr www

# 新增记录
python3 dns_cli.py add example.com --rr www --type A --value 1.2.3.4 --ttl 600

# 更新记录（自动查找 record-id）
python3 dns_cli.py update example.com --rr www --type A --value 5.6.7.8

# 删除记录
python3 dns_cli.py delete example.com --rr www --type A
```

## 全局选项

```
--provider {aliyun,cloudflare,aws,cdnw}   强制指定平台（跳过 NS 检测）
--env-file FILE                           指定环境变量文件
-o {table,json}                           输出格式（默认 table）
--dry-run                                 仅显示将执行的操作
-v, --verbose                             显示详细日志
```

## 项目结构

```
unified-dns-manager/
├── dns_cli.py                    # CLI 入口
├── requirements.txt              # Python 依赖
├── lib/
│   ├── __init__.py
│   ├── dns_provider_base.py      # ABC + 数据类
│   ├── dns_provider_aliyun.py    # 阿里云实现
│   ├── dns_provider_cloudflare.py # Cloudflare 实现
│   ├── dns_provider_route53.py   # Route53 实现
│   ├── dns_provider_cdnw.py      # CDNetworks 实现
│   ├── dns_provider_factory.py   # 工厂 + 自动检测
│   ├── ns_detector.py            # NS 识别服务
│   └── cdnw_client.py            # CDNW API 签名客户端
└── README.md
```

## 架构设计

- CLI 层仅负责参数解析和输出格式化
- 业务逻辑全部在 `lib/` 模块中
- 未来 Web API 直接调用同一套 lib/ 模块
- 各 Provider 可选导入（缺 boto3 不影响其他平台）

## 依赖

- Python 3.8+
- `requests` — 所有平台 HTTP 调用
- `boto3` — 仅 Route53（可选）
- `dnspython` — NS 检测（可选，fallback 到 dig）

## 版本

- v1.0.0 - 初始版本，支持 4 平台 DNS 记录 CRUD
