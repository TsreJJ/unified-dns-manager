# Unified DNS Manager v1.1.0

统一多平台 DNS 记录变更系统 — CLI + Web UI + Python API 三入口，自动判别域名归属平台，完成 DNS 解析记录 CRUD。

## 支持平台

| 平台 | Provider | 认证方式 | 环境变量 |
|------|----------|----------|----------|
| 阿里云 DNS | `aliyun` | HMAC-SHA1 签名 / STS AssumeRole | `ALICLOUD_ACCESS_KEY_ID`, `ALICLOUD_ACCESS_KEY_SECRET`, `ALICLOUD_ROLE_ARN`(可选) |
| Cloudflare | `cloudflare` | Bearer Token | `CLOUDFLARE_API_TOKEN` |
| AWS Route53 | `aws` | AWS SigV4 (boto3) | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| CDNetworks | `cdnw` | CNC-HMAC-SHA256 签名 | `CDNW_ACCESS_KEY`, `CDNW_SECRET_KEY` |

## 凭证配置

统一凭证文件路径：`~/.credentials/unified-dns-manager.env`

CLI 和 Python API 均会自动加载此文件，无需手动 export 环境变量。也可通过 `--env-file` 指定其他路径。

```ini
# ~/.credentials/unified-dns-manager.env
ALICLOUD_ACCESS_KEY_ID=your_key
ALICLOUD_ACCESS_KEY_SECRET=your_secret
CLOUDFLARE_API_TOKEN=your_token
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
CDNW_ACCESS_KEY=your_key
CDNW_SECRET_KEY=your_secret
```

> 文件权限应设为 600：`chmod 600 ~/.credentials/unified-dns-manager.env`

## 安装

```bash
pip install -r requirements.txt
```

依赖：
- `requests>=2.28.0` — HTTP 客户端
- `dnspython>=2.4.0` — NS 自动检测（可选，fallback 到 dig）
- `boto3>=1.28.0` — 仅 Route53 需要（可选）

## CLI 使用

### 检测域名归属平台

```bash
python3 dns_cli.py detect example.com
```

### 列出解析记录

```bash
# 列出所有记录
python3 dns_cli.py list example.com

# 按类型和主机记录过滤
python3 dns_cli.py list example.com --type A --rr www

# JSON 输出
python3 dns_cli.py -o json list example.com

# 强制指定平台（跳过 NS 检测）
python3 dns_cli.py --provider cloudflare list example.com
```

### 添加记录

```bash
python3 dns_cli.py add example.com --rr www --type A --value 1.2.3.4 --ttl 600

# MX 记录（带优先级）
python3 dns_cli.py add example.com --rr @ --type MX --value mail.example.com --priority 10

# Dry-run 预览
python3 dns_cli.py --dry-run add example.com --rr test --type A --value 1.1.1.1
```

### 更新记录

```bash
# 自动按 rr + type 查找 record_id
python3 dns_cli.py update example.com --rr www --type A --value 5.6.7.8

# 指定 record_id
python3 dns_cli.py update example.com --rr www --type A --value 5.6.7.8 --record-id 12345
```

### 删除记录

```bash
# 按 rr + type 查找并删除
python3 dns_cli.py delete example.com --rr www --type A

# 指定 record_id
python3 dns_cli.py delete example.com --record-id 12345
```

### 全局选项

| 选项 | 说明 |
|------|------|
| `--provider {aliyun,cloudflare,aws,cdnw}` | 强制指定平台（跳过 NS 检测） |
| `--env-file FILE` | 指定环境变量文件（默认 `~/.credentials/unified-dns-manager.env`） |
| `-o {table,json}` | 输出格式（默认 table） |
| `--dry-run` | 仅显示将执行的操作，不实际执行 |
| `-v, --verbose` | 显示详细日志 |

## Python API（供外部项目调用）

`lib/dns_api.py` 提供 4 个 facade 函数，外部项目可直接 import 使用：

```python
import sys
sys.path.insert(0, "/home/jim/gitrepo/unified-dns-manager")

from lib.dns_api import dns_list_records, dns_add_record, dns_update_record, dns_delete_record
```

### dns_list_records

```python
records = dns_list_records("zc2tv.com")
records = dns_list_records("zc2tv.com", rr="www", record_type="CNAME")
records = dns_list_records("example.com", provider="cloudflare")

# 返回 List[RecordInfo]，每条记录包含:
# record_id, domain_name, rr, type, value, ttl, status
```

### dns_add_record

```python
result = dns_add_record("zc2tv.com", "test", "CNAME", "test.zc2tv.com.wcdnga.com", ttl=600)
result = dns_add_record("example.com", "@", "MX", "mail.example.com", priority=10)

# 返回 OperationResult: result.success, result.data, result.error_message
```

### dns_update_record

```python
# 自动按 rr + type 查找 record_id
result = dns_update_record("zc2tv.com", "test", "CNAME", "new-target.com")

# 指定 record_id
result = dns_update_record("zc2tv.com", "test", "CNAME", "new-target.com", record_id="12345")
```

### dns_delete_record

```python
result = dns_delete_record("zc2tv.com", rr="test", record_type="CNAME")
result = dns_delete_record("zc2tv.com", record_id="12345")
```

### 特性

- **凭证自动加载**：自动读取 `~/.credentials/unified-dns-manager.env`
- **平台自动检测**：通过 NS 记录判别域名托管平台，无需手动指定 provider
- **record_id 自动查找**：update/delete 可按 rr + type 自动匹配，无需先查 ID
- **资源自动释放**：函数内部管理 Provider 生命周期

### ops_deploy 集成示例

```python
# 在 ops_deploy Phase 2 中替换原有 CDNW DNS 逻辑：
import sys
sys.path.insert(0, "/home/jim/gitrepo/unified-dns-manager")
from lib.dns_api import dns_add_record

# 添加 CDN CNAME
result = dns_add_record("zc2tv.com", hostname, "CNAME", f"{hostname}.zc2tv.com.wcdnga.com", ttl=600)
if not result.success:
    raise RuntimeError(f"DNS 添加失败: {result.error_message}")

# 添加 ACME 验证记录
result = dns_add_record("zc2tv.com", "_acme-challenge", "CNAME",
                        "zc2tv.com.aliasdomainforcertvalidtiononly.com", ttl=120)
```

## Web UI

### 启动

```bash
# 安装依赖
pip install -r requirements.txt

# 设置认证 token（不设置则自动生成并打印到终端）
export WEB_AUTH_TOKEN="your-secret-token"

# 启动（默认 127.0.0.1:5000）
python3 dns_web.py

# 自定义地址和端口
python3 dns_web.py --host 0.0.0.0 --port 8080

# 指定环境变量文件
python3 dns_web.py --env-file /path/to/credentials.env
```

### 功能

- **域名检测** — 输入域名后自动识别托管平台（阿里云/Cloudflare/AWS/CDNetworks）
- **记录列表** — 表格展示所有解析记录，支持按类型、主机记录过滤
- **添加记录** — 表单填写 rr、type、value、TTL、priority
- **编辑记录** — 点击编辑按钮修改记录值
- **删除记录** — 带二次确认弹窗，防误删

### REST API

| Method | Path | 功能 |
|--------|------|------|
| `GET` | `/api/providers` | 列出支持的平台 |
| `GET` | `/api/detect/<domain>` | 检测域名归属平台 |
| `GET` | `/api/records/<domain>` | 列出记录（query: `rr`, `type`, `provider`） |
| `POST` | `/api/records/<domain>` | 添加记录 |
| `PUT` | `/api/records/<domain>` | 更新记录 |
| `DELETE` | `/api/records/<domain>` | 删除记录 |

所有 API 需 `Authorization: Bearer <token>` header。

### 安全

- Bearer Token 认证，token 从 `WEB_AUTH_TOKEN` 环境变量读取
- 默认绑定 `127.0.0.1`，仅本机可访问
- 远程访问建议配合 Nginx 反向代理 + HTTPS

## 项目结构

```
unified-dns-manager/
├── dns_cli.py                     # CLI 入口 (v1.1.0)
├── dns_web.py                     # Web UI 入口 (v1.1.0)
├── requirements.txt               # Python 依赖
├── README.md
├── templates/
│   └── index.html                 # 单页 Web UI
├── lib/
│   ├── __init__.py
│   ├── dns_api.py                 # Facade — 外部项目统一调用入口
│   ├── dns_provider_base.py       # ABC 抽象基类 + RecordInfo / OperationResult 数据类
│   ├── dns_provider_factory.py    # Provider 工厂 + NS 自动检测
│   ├── dns_provider_aliyun.py     # 阿里云 DNS 实现 (HMAC-SHA1 + STS)
│   ├── dns_provider_cloudflare.py # Cloudflare 实现 (Bearer Token + 自动重试)
│   ├── dns_provider_route53.py    # AWS Route53 实现 (boto3 SigV4)
│   ├── dns_provider_cdnw.py       # CDNetworks 实现 (自动 deploy 到生产)
│   ├── cdnw_client.py             # CDNetworks API 签名客户端 (CNC-HMAC-SHA256)
│   └── ns_detector.py             # NS 记录检测服务（支持 12 家云商识别）
```

## 架构设计

```
┌─────────────┐  ┌─────────────┐  ┌──────────────────┐
│  dns_cli.py │  │ dns_web.py  │  │ 外部项目 (import) │
│   (CLI)     │  │  (Web UI)   │  │ ops_deploy 等     │
└──────┬──────┘  └──────┬──────┘  └────────┬─────────┘
       │                │                  │
       ▼                ▼                  ▼
┌─────────────────────────────────┐
│         lib/dns_api.py          │  ← Facade 统一入口
│  (自动加载凭证、平台检测、资源释放) │
├─────────────────────────────────┤
│     lib/dns_provider_factory.py │  ← 工厂 + NS 检测
├──────┬───────┬───────┬──────────┤
│Aliyun│  CF   │Route53│  CDNW    │  ← 各平台 Provider
└──────┴───────┴───────┴──────────┘
```

## 版本历史

- **v1.1.0** — 新增 Web UI（Flask + REST API），支持浏览器操作 DNS 记录 CRUD，Bearer Token 认证
- **v1.0.1** — 新增 `dns_api.py` facade 供外部项目 import 调用；CLI 自动加载默认 env 文件
- **v1.0.0** — 初始版本，支持 4 平台 DNS 记录 CRUD + NS 自动检测
