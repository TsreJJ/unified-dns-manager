# Unified DNS Manager API Reference v2.1.0

Base URL: `https://dns-mgr.rptops.com` (production) / `http://127.0.0.1:5000` (local)

---

## Authentication

支持三种认证方式，按优先级排列：

### 1. CF Access JWT (浏览器用户)

通过 Cloudflare Access + Auth0 登录后自动携带，无需手动设置 header。

### 2. CF Access Service Token (外部 API 调用)

```bash
curl -H "CF-Access-Client-Id: <client_id>" \
     -H "CF-Access-Client-Secret: <client_secret>" \
     https://dns-mgr.rptops.com/api/me
```

首次请求后可复用返回的 `CF_Authorization` cookie。映射为 admin 权限。

### 3. Bearer Token (本地 CLI/自动化)

```bash
curl -H "Authorization: Bearer $WEB_AUTH_TOKEN" \
     http://127.0.0.1:5000/api/me
```

仅限本地访问（不经过 CF Tunnel）。映射为 admin 权限。

---

## Error Response

所有错误统一格式：

```json
{"error": "错误描述"}
```

| HTTP Code | 含义 |
|-----------|------|
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 已认证但无权限 |
| 404 | 资源不存在 |
| 409 | 资源冲突（如用户已存在） |
| 500 | 服务端异常 |

---

## Role Permissions

| 角色 | 读操作 | 写操作 | 域名范围 | Admin API |
|------|--------|--------|----------|-----------|
| admin | 全部 | 全部 | 全部域名 | 可以 |
| operator | 授权域名 | 授权域名 | domain_permissions 表 | 不可 |
| viewer | 授权域名 | 禁止 | domain_permissions 表 | 不可 |
| service_token | 全部 | 全部 | 全部域名 | 可以 |
| bearer_token | 全部 | 全部 | 全部域名 | 可以 |

---

## Domain Handling

所有 `<domain>` 路径参数支持完整域名（FQDN），系统自动提取根域名：

- `example.com` → root: `example.com`, rr: ``
- `www.example.com` → root: `example.com`, rr: `www`
- `a.b.example.co.uk` → root: `example.co.uk`, rr: `a.b`

---

## Endpoints

### User Info

#### GET /api/me

当前认证用户信息。

**权限**: 需认证

**Response** `200`:
```json
{
  "email": "tsrejjj@gmail.com",
  "role": "admin",
  "display_name": "Initial Admin",
  "auth_method": "cf_access"
}
```

非 admin 用户额外返回 `domains` 字段：
```json
{
  "email": "bob@example.com",
  "role": "operator",
  "display_name": "Bob",
  "auth_method": "cf_access",
  "domains": ["example.com", "rptops.com"]
}
```

---

### DNS Operations

#### GET /api/providers

列出支持的 DNS 平台。

**权限**: 需认证

**Response** `200`:
```json
{
  "providers": ["aliyun", "cloudflare", "aws", "cdnw"]
}
```

---

#### GET /api/parse-domain/\<domain\>

解析域名，返回根域名和子域名前缀。

**权限**: 需认证

**Example**: `GET /api/parse-domain/www.example.com`

**Response** `200`:
```json
{
  "input": "www.example.com",
  "root_domain": "example.com",
  "subdomain_rr": "www"
}
```

---

#### GET /api/detect/\<domain\>

检测域名归属 DNS 平台（通过 NS 记录）。

**权限**: 需认证 + 域名权限

**Example**: `GET /api/detect/example.com`

**Response** `200`:
```json
{
  "domain": "example.com",
  "input": "example.com",
  "subdomain_rr": "",
  "provider_type": "cloudflare",
  "provider_name": "Cloudflare",
  "confidence": 1.0,
  "matched_ns": ["ns1.cloudflare.com", "ns2.cloudflare.com"],
  "all_ns": ["ns1.cloudflare.com", "ns2.cloudflare.com"]
}
```

---

#### GET /api/records/\<domain\>

列出 DNS 解析记录。

**权限**: 需认证 + 域名权限

**Query Parameters**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `type` | string | 按记录类型过滤 (A, AAAA, CNAME, MX, TXT, NS, SRV) |
| `rr` | string | 按主机记录过滤 |
| `provider` | string | 强制指定平台 (aliyun, cloudflare, aws, cdnw) |

**Example**: `GET /api/records/example.com?type=A&rr=www`

**Response** `200`:
```json
{
  "domain": "example.com",
  "input": "example.com",
  "subdomain_rr": "",
  "count": 1,
  "records": [
    {
      "record_id": "abc123",
      "domain_name": "example.com",
      "rr": "www",
      "type": "A",
      "value": "1.2.3.4",
      "ttl": 600,
      "priority": null,
      "status": "ENABLE",
      "remark": ""
    }
  ]
}
```

---

#### POST /api/records/\<domain\>

添加 DNS 解析记录。

**权限**: admin / operator + 域名权限

**Request Body**:
```json
{
  "rr": "www",
  "type": "A",
  "value": "1.2.3.4",
  "ttl": 600,
  "priority": 10,
  "provider": "cloudflare"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `rr` | 是 | 主机记录 (www, @, *, mail 等) |
| `type` | 是 | 记录类型 (A, AAAA, CNAME, MX, TXT, NS, SRV) |
| `value` | 是 | 记录值 |
| `ttl` | 否 | TTL 秒数，默认 600 |
| `priority` | 否 | MX 优先级 |
| `provider` | 否 | 强制指定平台，不填则自动检测 |

**Response** `201`:
```json
{
  "success": true,
  "data": {"record_id": "abc123"},
  "error_code": "",
  "error_message": ""
}
```

**Response** `400` (失败):
```json
{
  "success": false,
  "data": null,
  "error_code": "InvalidParameter",
  "error_message": "The domain name belongs to other users."
}
```

---

#### PUT /api/records/\<domain\>

更新 DNS 解析记录。

**权限**: admin / operator + 域名权限

**Request Body**:
```json
{
  "rr": "www",
  "type": "A",
  "value": "5.6.7.8",
  "ttl": 300,
  "record_id": "abc123",
  "provider": "cloudflare"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `rr` | 是 | 主机记录 |
| `type` | 是 | 记录类型 |
| `value` | 是 | 新记录值 |
| `ttl` | 否 | 新 TTL，默认 600 |
| `priority` | 否 | MX 优先级 |
| `record_id` | 否 | 不填则按 rr + type 自动查找 |
| `provider` | 否 | 强制指定平台 |

**Response** `200`:
```json
{
  "success": true,
  "data": {"record_id": "abc123"},
  "error_code": "",
  "error_message": ""
}
```

---

#### DELETE /api/records/\<domain\>

删除 DNS 解析记录。

**权限**: admin / operator + 域名权限

**Request Body**:
```json
{
  "record_id": "abc123",
  "rr": "www",
  "type": "A",
  "provider": "cloudflare"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `record_id` | 二选一 | 指定 record_id |
| `rr` + `type` | 二选一 | 按 rr + type 查找删除 |
| `provider` | 否 | 强制指定平台 |

**Response** `200`:
```json
{
  "success": true,
  "data": null,
  "error_code": "",
  "error_message": ""
}
```

---

### Batch Operations

#### PUT /api/batch/\<domain\>

批量更新记录（TTL 或 Status）。

**权限**: admin / operator + 域名权限

**Request Body (批量修改 TTL)**:
```json
{
  "field": "ttl",
  "value": 300,
  "records": [
    {"record_id": "abc123", "rr": "www", "type": "A", "value": "1.2.3.4"},
    {"record_id": "def456", "rr": "mail", "type": "MX", "value": "mail.example.com"}
  ],
  "provider": "cloudflare"
}
```

**Request Body (批量修改 Status)**:
```json
{
  "field": "status",
  "value": "ENABLE",
  "records": [
    {"record_id": "abc123"},
    {"record_id": "def456"}
  ],
  "provider": "aliyun"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `field` | 是 | `ttl` 或 `status` |
| `value` | 是 | 新值（TTL 为整数，Status 为 ENABLE/DISABLE） |
| `records` | 是 | 记录数组，每条需含 `record_id`；TTL 更新还需 `rr`, `type`, `value` |
| `provider` | 否 | 强制指定平台 |

**Response** `200`:
```json
{
  "success_count": 2,
  "fail_count": 0,
  "results": [
    {"record_id": "abc123", "success": true},
    {"record_id": "def456", "success": true}
  ]
}
```

---

#### DELETE /api/batch/\<domain\>

批量删除记录。

**权限**: admin / operator + 域名权限

**Request Body**:
```json
{
  "records": [
    {"record_id": "abc123"},
    {"record_id": "def456", "rr": "mail", "type": "MX"}
  ],
  "provider": "cloudflare"
}
```

**Response** `200`:
```json
{
  "success_count": 2,
  "fail_count": 0,
  "results": [
    {"record_id": "abc123", "success": true},
    {"record_id": "def456", "success": true}
  ]
}
```

---

### Admin API

所有 Admin 端点仅 **admin** 角色可访问。

#### GET /api/admin/users

列出所有用户。

**Response** `200`:
```json
{
  "users": [
    {
      "id": 1,
      "email": "tsrejjj@gmail.com",
      "role": "admin",
      "display_name": "Initial Admin",
      "is_active": 1,
      "created_at": "2026-03-22T17:06:49Z",
      "updated_at": "2026-03-22T17:06:49Z",
      "domains": []
    },
    {
      "id": 2,
      "email": "bob@example.com",
      "role": "operator",
      "display_name": "Bob",
      "is_active": 1,
      "created_at": "2026-03-24T02:00:00Z",
      "updated_at": "2026-03-24T02:00:00Z",
      "domains": ["example.com", "rptops.com"]
    }
  ]
}
```

---

#### POST /api/admin/users

创建用户。

**Request Body**:
```json
{
  "email": "bob@example.com",
  "role": "operator",
  "display_name": "Bob",
  "domains": ["example.com", "rptops.com"]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `email` | 是 | 用户邮箱（Auth0 登录邮箱） |
| `role` | 否 | admin / operator / viewer，默认 viewer |
| `display_name` | 否 | 显示名称 |
| `domains` | 否 | 授权域名数组（admin 不需要） |

**Response** `201`:
```json
{
  "id": 2,
  "email": "bob@example.com",
  "role": "operator"
}
```

---

#### PUT /api/admin/users/\<id\>

编辑用户。

**Request Body** (所有字段可选):
```json
{
  "role": "admin",
  "display_name": "Bob Admin",
  "is_active": true
}
```

**Response** `200`:
```json
{"message": "更新成功"}
```

---

#### DELETE /api/admin/users/\<id\>

删除用户。不能删除自己。

**Response** `200`:
```json
{"message": "用户 bob@example.com 已删除"}
```

---

#### GET /api/admin/users/\<id\>/domains

查看用户域名权限。

**Response** `200`:
```json
{
  "user_id": 2,
  "email": "bob@example.com",
  "role": "operator",
  "domains": ["example.com", "rptops.com"]
}
```

---

#### PUT /api/admin/users/\<id\>/domains

设置用户域名权限（全量替换）。

**Request Body**:
```json
{
  "domains": ["example.com", "newdomain.com"]
}
```

**Response** `200`:
```json
{
  "message": "域名权限已更新",
  "domains": ["example.com", "newdomain.com"]
}
```

---

#### GET /api/admin/audit

查询审计日志。

**Query Parameters**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `user` | string | 按用户邮箱过滤 |
| `domain` | string | 按域名过滤 |
| `action` | string | 按操作类型 (add, update, delete) |
| `start` | string | 起始时间 (ISO 8601) |
| `end` | string | 结束时间 (ISO 8601) |
| `limit` | int | 返回条数，默认 100，最大 500 |
| `offset` | int | 偏移量，默认 0 |

**Example**: `GET /api/admin/audit?domain=example.com&action=delete&limit=10`

**Response** `200`:
```json
{
  "total": 42,
  "logs": [
    {
      "id": 10,
      "timestamp": "2026-04-09T06:35:27Z",
      "user_email": "tsrejjj@gmail.com",
      "action": "delete",
      "domain": "example.com",
      "rr": "test",
      "record_type": "A",
      "value": "1.2.3.4",
      "request_body": "{\"rr\":\"test\",\"type\":\"A\",\"record_id\":\"abc123\"}",
      "result_success": 1,
      "result_message": "success",
      "ip_address": "114.32.28.150"
    }
  ]
}
```

---

## Quick Start Examples

### Service Token: 查询记录

```bash
ST_ID="52db28a20f3c215090e0420e1bf56964.access"
ST_SECRET="3a50a22f96ccdce07e6d9ec697a416b6afe016502567377b5ddf33afb40eb4a6"

curl -s \
  -H "CF-Access-Client-Id: $ST_ID" \
  -H "CF-Access-Client-Secret: $ST_SECRET" \
  "https://dns-mgr.rptops.com/api/records/example.com?type=A"
```

### Service Token: 添加记录

```bash
curl -s -X POST \
  -H "CF-Access-Client-Id: $ST_ID" \
  -H "CF-Access-Client-Secret: $ST_SECRET" \
  -H "Content-Type: application/json" \
  "https://dns-mgr.rptops.com/api/records/example.com" \
  -d '{"rr":"www","type":"A","value":"1.2.3.4","ttl":600}'
```

### Service Token: 更新记录

```bash
curl -s -X PUT \
  -H "CF-Access-Client-Id: $ST_ID" \
  -H "CF-Access-Client-Secret: $ST_SECRET" \
  -H "Content-Type: application/json" \
  "https://dns-mgr.rptops.com/api/records/example.com" \
  -d '{"rr":"www","type":"A","value":"5.6.7.8","ttl":300}'
```

### Service Token: 删除记录

```bash
curl -s -X DELETE \
  -H "CF-Access-Client-Id: $ST_ID" \
  -H "CF-Access-Client-Secret: $ST_SECRET" \
  -H "Content-Type: application/json" \
  "https://dns-mgr.rptops.com/api/records/example.com" \
  -d '{"rr":"www","type":"A"}'
```

### Bearer Token: 本地调用

```bash
TOKEN="wHSH7cZJ8dA5sELp0JVRlcbmlgf2O66rIVmuxaOO"

# 查询
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:5000/api/records/example.com"

# 添加
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "http://127.0.0.1:5000/api/records/example.com" \
  -d '{"rr":"www","type":"A","value":"1.2.3.4"}'
```
