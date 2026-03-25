# Unified DNS Manager v2.1.0

统一多平台 DNS 记录变更系统 — CLI + Web UI + Python API 三入口，自动判别域名归属平台，完成 DNS 解析记录 CRUD。

v2.1.0 新增：批量操作（批量修改 TTL、批量修改 Status、批量删除）。

v2.0.0 新增：用户管理 (RBAC)、域名级权限控制、写操作审计日志。认证委托 Cloudflare Access + Auth0，项目仅负责 RBAC 与审计。

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

# RBAC + 审计（v2.0.0）
CF_ACCESS_TEAM_NAME=<team>.cloudflareaccess.com
CF_ACCESS_AUDIENCE=<Application AUD Tag>
INITIAL_ADMIN_EMAIL=jim@example.com
DB_PATH=~/.credentials/unified-dns-manager.db
WEB_AUTH_TOKEN=<existing-token>   # CLI/自动化 fallback
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
- `flask>=3.0.0` — Web UI
- `PyJWT>=2.8.0` — CF Access JWT 验证
- `cryptography>=41.0.0` — JWT 签名验证

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

### 架构（v2.0.0）

```
用户浏览器
  │
  ▼
Cloudflare Access (Auth0 IdP 登录)  ← 认证在此完成
  │  Cf-Access-Jwt-Assertion header
  ▼
CF Tunnel (cloudflared)
  │
  ▼
Flask (127.0.0.1:5000)
  ├─ lib/database.py          → SQLite 连接 + schema
  ├─ lib/cf_access_auth.py    → CF JWT 验证 + require_auth
  ├─ lib/rbac.py              → 角色 + 域名权限检查
  ├─ lib/audit.py             → 写操作审计日志
  └─ dns_web.py               → 路由集成
```

### 认证模式

1. **CF Access JWT**（推荐）：通过 Cloudflare Access 登录后，自动携带 `Cf-Access-Jwt-Assertion` header，后端验证签名并从 JWT 中提取 email
2. **Bearer Token**（兼容）：CLI 和自动化脚本使用 `Authorization: Bearer <WEB_AUTH_TOKEN>` header，映射为 admin 权限

### 角色权限模型

| 角色 | 读操作 | 写操作 | 域名范围 | 管理/审计 |
|------|--------|--------|----------|-----------|
| admin | 全部 | 全部 | 全部域名 | 可以 |
| operator | 授权域名 | 授权域名 | domain_permissions | 不可 |
| viewer | 授权域名 | 禁止 | domain_permissions | 不可 |

### 启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动（默认 127.0.0.1:5000，自动创建数据库并种入 INITIAL_ADMIN_EMAIL）
python3 dns_web.py

# 自定义地址和端口
python3 dns_web.py --host 0.0.0.0 --port 8080

# 指定环境变量文件
python3 dns_web.py --env-file /path/to/credentials.env
```

### 功能

- **域名检测** — 输入域名后自动识别托管平台（阿里云/Cloudflare/AWS/CDNetworks）
- **记录列表** — 表格展示所有解析记录，支持按类型、主机记录过滤
- **添加/编辑/删除记录** — 基于角色权限控制，viewer 隐藏写操作按钮
- **用户管理** — admin 可创建/编辑/删除用户，分配角色和域名权限
- **审计日志** — admin 可查询所有写操作记录，支持按用户/域名/时间过滤

### REST API

| Method | Path | 功能 | 权限 |
|--------|------|------|------|
| `GET` | `/api/me` | 当前用户信息 | 需认证 |
| `GET` | `/api/providers` | 列出支持的平台 | 需认证 |
| `GET` | `/api/detect/<domain>` | 检测域名归属平台 | 需认证 + 域名权限 |
| `GET` | `/api/records/<domain>` | 列出记录 | 需认证 + 域名权限 |
| `POST` | `/api/records/<domain>` | 添加记录 | admin/operator + 域名权限 |
| `PUT` | `/api/records/<domain>` | 更新记录 | admin/operator + 域名权限 |
| `DELETE` | `/api/records/<domain>` | 删除记录 | admin/operator + 域名权限 |
| `GET` | `/api/admin/users` | 用户列表 | admin |
| `POST` | `/api/admin/users` | 创建用户 | admin |
| `PUT` | `/api/admin/users/<id>` | 编辑用户 | admin |
| `DELETE` | `/api/admin/users/<id>` | 删除用户 | admin |
| `GET` | `/api/admin/users/<id>/domains` | 查看域名权限 | admin |
| `PUT` | `/api/admin/users/<id>/domains` | 设置域名权限 | admin |
| `GET` | `/api/admin/audit` | 审计日志查询 | admin |

### 安全

- Cloudflare Access 网关级认证（JWT 签名验证，非仅信任 header）
- Bearer Token 向后兼容 CLI/自动化
- 基于角色 + 域名的细粒度权限控制
- 所有写操作自动审计（记录操作者、IP、请求体、结果）
- 默认绑定 `127.0.0.1`，通过 CF Tunnel 暴露

## Cloudflare Tunnel + Access 配置

### 1. 安装 cloudflared 并创建 Tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create dns-mgr
```

### 2. 配置 Tunnel

编辑 `~/.cloudflared/config.yml`：

```yaml
tunnel: dns-mgr
credentials-file: /home/<user>/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: dns-mgr.<your-domain>.com
    service: http://127.0.0.1:5000
  - service: http_status:404
```

### 3. 添加 DNS 路由

```bash
cloudflared tunnel route dns dns-mgr dns-mgr.<your-domain>.com
```

### 4. 配置 Cloudflare Access

1. 登录 [CF Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. **Settings > Authentication > Add IdP** — 添加 Auth0 为 OIDC IdP：
   - Auth0 Domain: `<tenant>.auth0.com`
   - Client ID / Secret: 从 Auth0 Application 获取
3. **Access > Applications > Add Self-hosted Application**
   - Application domain: `dns-mgr.<your-domain>.com`
   - Session duration: 24h
4. **Access Policy**：配置允许的用户 email 或 email group
5. 记录 **Application Audience (AUD) Tag** → 写入 `CF_ACCESS_AUDIENCE` 环境变量

### 5. 启动 Tunnel

```bash
# 前台运行
cloudflared tunnel run dns-mgr

# 建议: systemd 管理
sudo cloudflared service install
```

### 6. 验证

1. 启动 Flask → DB 自动创建 → 默认 admin (`INITIAL_ADMIN_EMAIL`) 种入
2. 浏览器访问 `dns-mgr.<your-domain>.com` → 跳转 Auth0 登录
3. 登录后页面显示用户 email + role badge
4. admin 点击 ADMIN 按钮 → 管理用户 + 查看审计日志
5. `curl -H "Authorization: Bearer $WEB_AUTH_TOKEN" http://127.0.0.1:5000/api/me` → Legacy 模式验证

## 项目结构

```
unified-dns-manager/
├── dns_cli.py                     # CLI 入口 (v1.1.0)
├── dns_web.py                     # Web UI 入口 (v2.0.0)
├── requirements.txt               # Python 依赖
├── README.md
├── templates/
│   └── index.html                 # 单页 Web UI（含 admin 面板）
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
│   ├── ns_detector.py             # NS 记录检测服务（支持 12 家云商识别）
│   ├── database.py                # SQLite 连接管理 + schema (v2.0.0)
│   ├── cf_access_auth.py          # CF Access JWT 验证 + 双模式认证 (v2.0.0)
│   ├── rbac.py                    # 角色 + 域名权限检查 (v2.0.0)
│   └── audit.py                   # 写操作审计日志 (v2.0.0)
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
         │
         ▼ (Web UI v2.0.0)
┌─────────────────────────────────┐
│ CF Access (Auth0) → JWT 验证     │  ← 认证层
├─────────────────────────────────┤
│ RBAC (角色 + 域名权限)           │  ← 授权层
├─────────────────────────────────┤
│ Audit Log (SQLite)              │  ← 审计层
└─────────────────────────────────┘
```

## 版本历史

- **v2.0.0** — 用户管理 + RBAC（角色 + 域名权限）+ 写操作审计日志；认证委托 CF Access + Auth0；Web UI 新增 admin 面板（用户管理 + 审计查询）；Bearer Token 向后兼容 CLI/自动化
- **v1.1.0** — 新增 Web UI（Flask + REST API），支持浏览器操作 DNS 记录 CRUD，Bearer Token 认证
- **v1.0.1** — 新增 `dns_api.py` facade 供外部项目 import 调用；CLI 自动加载默认 env 文件
- **v1.0.0** — 初始版本，支持 4 平台 DNS 记录 CRUD + NS 自动检测
