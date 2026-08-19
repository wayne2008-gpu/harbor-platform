# Synthetic Data Platform Auth/RBAC Design

## 目标

把 `synthetic-data-platform` 从当前的最小安全门禁推进到可面向真实用户的
登录和细粒度 RBAC：

- 保留现有 service token、tenant header、`X-End-User` audit correlation。
- 不把业务用户权限下沉到 `harbor-api`；`harbor-api` 继续只理解服务间调用、
  tenant、runner/control-plane scope。
- 在 `synthetic-data-platform` 内集中实现用户身份解析、权限判断和审计上下文，
  避免每个 route 自己拼权限逻辑。
- 支持先从可信网关/SSO 注入身份开始，后续平滑切到 JWT/JWKS 校验或企业 OIDC。

## 非目标

- 不在 `harbor-runtime` 或 `harbor-runner` 中引入业务用户模型。
- 不让前端自己决定权限；前端只做展示和交互降级。
- 不把 `X-End-User` 当作公网可直接信任的登录机制。只有在入口网关会清洗并重新
  注入该 header 时，它才可作为 trusted-header identity。
- 不在第一步实现完整组织管理、邀请流、密码找回、MFA、SCIM 同步。

## 当前基线

当前已经具备三层最小能力：

1. Service access：`synthetic-data-platform [auth]` 支持 Bearer token、
   `X-Tenant-ID` 和 `read/write` token scopes。
2. End-user correlation：synthetic API 会把入站 `X-Request-ID` 和
   `X-End-User` 透传到 `harbor-api`，control-plane audit events 可按
   `end_user` 查询。
3. Minimal user gate：`[end_user_permissions]` 可基于可信 `X-End-User` 做粗粒度
   `read/write` 拦截，`/settings` 只暴露聚合配置状态。

这仍然不是完整用户登录/RBAC，因为身份来源、角色绑定、资源级权限、会话生命周期
和权限变更审计还没有持久化模型。

## 目标架构

```text
Browser
  -> Gateway / SSO / Ingress
     - authenticates real user
     - strips incoming identity headers
     - injects trusted identity headers or forwards signed JWT
  -> synthetic-data-platform
     - validates service access where configured
     - resolves RequestIdentity
     - authorizes BusinessAction against ResourceRef
     - records audit metadata
  -> harbor-api
     - validates service token / tenant / scope
     - persists control-plane audit correlation
  -> harbor-runner / harbor-runtime / agent-runtime
```

`synthetic-data-platform` owns business auth because it owns dataset、task、trial
review、result dataset、export、audit 等业务对象。`harbor-api` 不应该知道“谁能
审核样本”或“谁能发布结果集”。

## 核心模块

新增一个深模块：`synthetic_data_platform.access_control`。

它的外部 Interface 应尽量小：

```python
class AccessControl:
    def evaluate(
        self,
        request: Request,
        *,
        action: str,
        resource: ResourceRef | None = None,
    ) -> AccessDecision: ...

    def settings_summary(self) -> dict[str, Any]: ...
```

调用方只需要知道：

- 当前 route 对应的 `action`。
- 可选 `resource`，例如 `dataset:dataset-1`、`task:task-1`、
  `result_dataset:result-1`。
- `AccessDecision` 成功时提供 `identity` 和 audit metadata；失败时提供 HTTP
  status、detail、error_type 和 safe extra fields。

复杂实现藏在模块内部：

- service token validation
- trusted header / JWT identity resolution
- tenant extraction
- role binding lookup
- permission inheritance
- route action mapping
- settings safe summary

这样 route 只做：

```python
decision = access_control.evaluate(
    request,
    action="task.cancel",
    resource=ResourceRef(type="synthetic_task", id=task_id),
)
if decision.denied:
    return decision.to_response(request)
```

后续如果从 trusted header 切 JWT，只换 IdentityProvider adapter，不改 route。

## 内部 Interface

### RequestIdentity

```python
class RequestIdentity(BaseModel):
    tenant_id: str | None
    subject_id: str
    external_subject: str
    email: str | None = None
    display_name: str | None = None
    source: Literal["trusted_header", "jwt", "local_dev"]
    groups: list[str] = []
```

`subject_id` 是平台内部稳定 ID。`external_subject` 是网关/JWT 给出的用户唯一值。

### IdentityProvider

```python
class IdentityProvider(Protocol):
    def resolve(self, request: Request) -> IdentityResult: ...
    def settings_summary(self) -> dict[str, Any]: ...
```

需要两个 adapter：

- `TrustedHeaderIdentityProvider`：读取网关注入的 `X-End-User`、可选
  `X-End-User-ID`、`X-End-User-Email`、`X-End-User-Groups`。
- `JwtIdentityProvider`：验证 `Authorization: Bearer <jwt>`，通过 JWKS 校验
  issuer、audience、signature、exp，然后映射 subject/email/groups。

第一阶段可以只实现 trusted header adapter，但 Interface 不能把 header 细节泄漏
到 route。

### PolicyStore

```python
class PolicyStore(Protocol):
    def roles_for_identity(
        self,
        identity: RequestIdentity,
        *,
        resource: ResourceRef | None,
    ) -> list[RoleGrant]: ...

    def settings_summary(self) -> dict[str, Any]: ...
```

需要两个 adapter：

- `ConfigPolicyStore`：兼容当前 `[end_user_permissions]`，用于本地和过渡期。
- `SqlPolicyStore`：生产持久化角色、权限和绑定。

### Authorizer

```python
class Authorizer:
    def is_allowed(
        self,
        identity: RequestIdentity,
        *,
        action: str,
        resource: ResourceRef | None,
    ) -> bool: ...
```

Authorizer 只理解 action 和 role grants，不读 FastAPI request。

## 权限矩阵

先定义稳定 action，不再只按 HTTP method 映射：

| 领域 | Action |
| --- | --- |
| Settings | `settings.view` |
| Dataset | `dataset.view`, `dataset.create`, `dataset.upload`, `dataset.update`, `dataset.delete` |
| Task | `task.view`, `task.create`, `task.cancel`, `task.retry`, `task.sync`, `task.ingest`, `task.publish` |
| Trial | `trial.view`, `trial.review` |
| Result dataset | `result.view`, `result.review`, `result.export`, `result.download`, `result.publish` |
| Audit | `audit.view`, `audit.export` |
| Admin | `admin.user.view`, `admin.user.write`, `admin.role.write` |

内置角色建议：

| Role | Permissions |
| --- | --- |
| `viewer` | settings/dataset/task/trial/result read-only |
| `reviewer` | viewer + `trial.review` + `result.review` |
| `operator` | reviewer + dataset upload/create + task create/cancel/retry/sync/ingest + result export/download |
| `publisher` | operator + `task.publish` + `result.publish` |
| `admin` | publisher + audit/admin actions |

第一版可以先做 tenant-wide role binding。资源级 binding 留作后续，因为 dataset/task
owner、project、workspace 等概念还没有稳定。

## SQL 模型

建议在 `synthetic-data-platform` 自己的数据库中新增：

```text
platform_subjects
  id
  tenant_id
  external_subject
  email
  display_name
  status
  metadata
  created_at
  updated_at

platform_roles
  id
  tenant_id
  name
  permissions_json
  built_in
  created_at
  updated_at

platform_role_bindings
  id
  tenant_id
  subject_id
  role_id
  resource_type nullable
  resource_id nullable
  created_at
  updated_at
```

索引：

- `platform_subjects(tenant_id, external_subject)` unique
- `platform_roles(tenant_id, name)` unique
- `platform_role_bindings(tenant_id, subject_id, resource_type, resource_id)`

后续如果需要 group 继承，再加 `platform_groups` 和 `platform_group_role_bindings`，
不要在第一版强行做。

## 审计

`SyntheticTaskRepository.record_audit_event` 当前已经记录 actor 和 metadata。
RBAC 后应扩展 metadata，而不是先扩 DB 字段：

```json
{
  "actor_subject_id": "sub_...",
  "actor_external_subject": "oidc|...",
  "actor_source": "trusted_header",
  "required_action": "task.cancel",
  "resource_type": "synthetic_task",
  "resource_id": "task-1",
  "decision": "allowed"
}
```

如果后续 audit 查询需要按 `actor_subject_id` 高频过滤，再把它提升成独立列并加迁移。

## 前端行为

前端通过 `/settings.auth` 和后续 `/me` 获取能力摘要：

- 隐藏用户没有权限的危险动作，或者降级为 disabled 按钮。
- 403 响应展示可恢复错误，不伪造成功态。
- Settings 显示 auth/RBAC readiness，但不展示 token、env var、完整用户列表。
- Audit 页面允许 admin/operator 查询自己的相关审计；全局审计只给 admin。

前端不是权限来源。所有 mutation endpoint 必须以后端 Authorizer 为准。

## 部署要求

Trusted-header 模式上线时，Ingress/Gateway 必须：

- 清洗外部请求自带的 `X-End-User`、`X-End-User-ID`、`X-End-User-Email`、
  `X-End-User-Groups`。
- 只在认证成功后重新注入这些 header。
- 保持 synthetic API 不直接暴露给公网绕过网关。
- 继续给 synthetic API 注入 service token 和 tenant header，或让内部入口使用
  mTLS/网关认证。

JWT 模式上线时，synthetic API 必须校验 issuer、audience、signature、expiry 和
clock skew，JWKS 缓存要有 TTL 和失败降级策略。

## 迭代排期

| 版本 | 内容 | 验收 |
| --- | --- | --- |
| V4-95 | 设计 auth/RBAC seam、权限矩阵、SQL 模型和部署约束 | 本文档 + roadmap 更新 |
| V4-96 | 已完成：抽 `access_control` 模块，保留现有 token/gate 行为 | `app.py` 中间件只把 `AccessDecision` 转成审计和 HTTP 响应；模块单测覆盖现有 gate 语义 |
| V4-97 | 增加 SQL PolicyStore 和 Alembic migrations | role/subject/binding CRUD repo 测试通过 |
| V4-98 | 增加 `/me` 和 trusted-header IdentityProvider | 能返回当前用户、角色、permission summary |
| V4-99 | 前端按 `/me` 做动作降级和 403 恢复提示 | Playwright 覆盖 viewer/reviewer/operator |
| V4-100 | JWT/JWKS IdentityProvider 生产化 | issuer/audience/signature/expiry 测试通过 |

## 验收命令

后续实现每个切片至少运行：

```bash
cd synthetic-data-platform
uv run ruff check .
uv run pytest -q
npm --prefix web run verify
```

父仓库同步 submodule 后运行 GitHub Actions 全套检查。
