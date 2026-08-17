# Synthetic Data Platform V4 Platformization Plan

## 目标效果

这一轮完成后，`synthetic-data-platform` 不只是能演示端到端跑通，而是进入
“可持续生产后训练 agent 轨迹数据”的平台化版本。

用户侧应达到的效果：

- 可以从浏览器完成 dataset 上传或 COS 登记、创建 TKE synthetic task、查看运行状态、
  审核 trajectory/OpenAI messages、保存审核结论、ingest samples、publish result
  dataset、下载 JSONL/JSON。
- 任务失败时能看到明确的失败阶段、恢复动作和下一步检查项，而不是只看到 Harbor 原始
  JSON 或异常字符串。
- 大样本 result dataset 和 task samples 不再依赖前端全量加载后过滤，查询行为逐步下沉
  到后端持久化查询。
- 审核队列、result lineage、artifact download、operation idempotency、audit trail
  都有清晰的接口和验收口径。
- 本地 COS + TKE smoke 和生产参数化 E2E smoke 能作为每轮发布前的验证门禁。

非目标：

- 不把 `synthetic-data-platform` 做成 Harbor 运维后台。
- 不在这一轮做完整用户登录、细粒度 RBAC、审批流、成本账单或 prompt/template 管理。
- 不把 COS、TKE、RabbitMQ、MySQL secret 暴露给前端。

## 当前基线

当前 P0 闭环已经具备：

- Dataset 上传、COS URI 登记、archive catalog validation。
- Synthetic task 创建，支持 dataset `input_datasets` 透传到 Harbor。
- TKE/AGS/Docker runtime capability 展示和 task builder 选择。
- Task detail 的 execution stage、cancel、retry、artifact retry、ingest、publish。
- Trial trajectory 的 ATIF/default、OpenAI messages schema、人工审核结论保存。
- 全局 trial review queue。
- Result dataset 发布、samples 搜索/分页、JSONL/JSON 下载、source trial 回跳。
- Synthetic API 入站 token scope baseline。
- Cancel/retry/artifact-retry operation idempotency 持久化。

需要注意的当前限制：

- `GET /synthetic-tasks/{id}/samples` 和 `GET /result-datasets/{id}/samples` 已有
  API 分页参数，但样本仍主要存放在 task/result 行内 `samples_json`，后端查询会先读取
  整个样本列表再过滤分页。这能支撑 MVP，不适合作为大规模样本查询模型。
- Synthetic operation idempotency 已覆盖顺序重放，但并发同 key 请求的原子 reservation
  语义还需要专门加固，尤其是 `retry` 这种会创建新 synthetic task 的操作。
- Workbench 和 review queue 目前以现有接口聚合为主，数据量增长后需要 SQL 聚合或专用
  query endpoint。
- 安全侧仍是服务级 token/scope baseline，不是最终用户权限模型。

## UI/UX 设计依据

本轮继续使用 `ui-ux-pro-max`。当前前端栈为：

```text
React 19 + Vite + React Router + TanStack Query + lucide-react + Playwright
```

本轮查询：

```text
workflow audit queue data operations
variance: 4/10
motion: 3/10
density: 9/10

error summary validation recovery
large table pagination review
rerender memo list performance
```

采用结论：

- 继续采用 `Data-Dense Dashboard`，强调高密度、可扫描、低装饰、强状态。
- 表单失败保留顶部可聚焦 error summary、字段 inline error 和恢复动作。
- 大表格在移动端使用记录卡片或局部横向滚动，页面不能整体横向溢出。
- 大列表查询要避免渲染数千 DOM 节点；React memo 只用于实测热点，列表 key 使用稳定
  业务 ID。
- 继续用 TanStack Query 表达 search/filter/page query key，支持 URL 深链恢复。

拒绝结论：

- 生成器再次命中 `Enterprise Gateway`，这适合官网和销售入口，不适合本平台。
- 不采用 hero、Contact Sales、客户 logo、行业入口、自动播放媒体或滚动动画。

## V4 产品边界

V4 主流程保持：

```text
Dataset -> Synthetic task -> Harbor run -> Trial trajectory
  -> Samples -> Result dataset -> Download / lineage audit
```

一级导航继续保持：

```text
Workbench | Datasets | Tasks | Reviews | Results | Settings
```

变化点：

- `Reviews` 可以从 V4 开始进入一级导航，因为全局 trial review queue 已经成为核心生产
  工作流，而不是偶发诊断入口。
- Harbor runner、lease、queue、K8s/TKE 细节仍不进入一级导航，只在 Settings 或 Task
  diagnostics 中作为证据展示。

## 接口和数据模型方向

### 1. 样本持久化查询

目标：把 sample 从 task/result 行内 JSON 扩展为可查询、可分页、可审计的业务记录。

建议新增：

```text
synthetic_samples
  id
  task_id
  result_dataset_id nullable
  source_trial_id nullable
  source_artifact_id nullable
  sample_type
  sample_json
  searchable_text
  reward nullable
  quality_flags_json
  created_at

synthetic_sample_sources
  sample_id
  artifact_id
  trial_id nullable
  relative_path nullable
  schema nullable
```

接口演进：

```text
GET /synthetic-tasks/{id}/samples?search=&limit=&offset=&quality_flag=
GET /result-datasets/{id}/samples?search=&limit=&offset=&quality_flag=
```

兼容要求：

- API response 和 pagination headers 保持现有合同。
- 行内 `samples_json` 可以短期作为兼容字段，但新查询路径优先读 `synthetic_samples`。
- publish result dataset 时冻结 sample snapshot，保证下载结果可复现。

### 2. Operation idempotency 原子化

目标：同一个 `task_id + operation + idempotency_key` 的并发请求只能有一个执行副作用。

建议把当前 idempotency record 扩展为 reservation：

```text
status: in_progress | completed | failed
response_task_id
error_json nullable
expires_at nullable
```

当前兼容实现可以先把 `status` 和 `error_json` 写入现有 `metadata_json` 的保留键，
避免阻塞已有本地库；后续正式迁移时再把它们提升为独立列。

行为：

- 首个请求插入 `in_progress` reservation 后执行副作用。
- 并发重复请求命中 `in_progress` 时返回 `409 Operation is already in progress`，或在后续版本
  支持短等待后返回最终结果。
- 完成后写入 `completed + response_task_id`，重复请求返回第一次结果。
- 失败后写入 `failed + error_json`，客户端可以换新的 idempotency key 重试。

### 3. 审核工作流

目标：把 trajectory review 从“逐条看详情”提升为批量生产队列。

建议增强：

```text
GET /reviews/trials/query
POST /reviews/trials/batch-decision
GET /reviews/summary
```

V4 前端：

- `Reviews` 一级导航。
- 队列支持 state、task、runtime、schema readiness、quality flag、reviewer 过滤。
- 快捷键或批量操作只做低风险动作，危险/不可逆动作必须二次确认。
- 每个 decision 保留 reviewer、rationale、labels、updated_at 和 source task/trial link。

### 4. Workbench 聚合

目标：Workbench 不再通过多个宽列表派生关键状态。

建议增强：

```text
GET /workbench/summary
```

返回：

- readiness gates。
- active/failed/publish-ready/review-open/result-ready counts。
- prioritized next actions。
- recent failures by phase。
- latest result datasets。

### 5. 审计和安全

目标：服务级 token baseline 后，补足面向用户动作的审计语义。

V4 先做：

- Synthetic API action audit：dataset upload/register、task create/cancel/retry、review
  decision、sample ingest、publish、download。
- 前端 Settings 只展示安全摘要和配置状态，不展示 secret 明文。
- API 返回 `request_id`，前端错误详情可展示 request ID，便于排查。

V4 不做：

- 完整登录态。
- 细粒度 RBAC。
- 审批流。

## 页面方案

### Workbench

首屏回答三件事：

- 当前是否具备跑数条件。
- 哪些任务或审核项需要处理。
- 哪些结果可以交付下载。

V4 增强：

- `GET /workbench/summary` 优先，失败时 fallback 到当前多接口派生。
- Next actions 增加 review queue、sample publish、download validation。
- Failure causes 增加 request ID 和跳转到对应 task event。

### Reviews

V4 新增一级入口。

页面结构：

```text
review queue header
filters: state / task / runtime / schema / quality flag / reviewer
summary metrics
queue table or mobile cards
quick decision panel
deep link to Trial Summary / Timeline / OpenAI Messages / schema diff
```

验收：

- URL 能恢复 filters/page。
- 保存 decision 后队列和 Workbench 同步刷新。
- 失败保存不丢失输入，并展示 error summary。

### Samples

Samples 不新增一级导航，仍从 Task Detail 和 Result Detail 进入。

V4 增强：

- 后端 SQL 分页和搜索。
- quality flag 过滤。
- field coverage 基于当前 query scope 明确标注。
- 大列表后续再引入 virtualization，先以服务端分页控制 DOM 数量。

### Settings

V4 增强：

- 展示 synthetic API、Harbor API、COS、RabbitMQ/TDMQ、TencentDB migration、
  runtime capabilities 的 readiness。
- 展示 local/production E2E command template。
- 展示 secret configured flags 和 auth scope summary，不展示 secret 明文。

## 研发排期

建议按 9 到 12 个工作日推进，继续用小 PR 切片。

| 里程碑 | 工作量 | 范围 | 验收 |
| --- | --- | --- | --- |
| V4-0 方案冻结 | 0.5d | 本文档、范围确认、接口和数据模型拆分 | 可拆 GitHub issues / PR |
| V4-1 Sample SQL model | 2d | `synthetic_samples` 表、ingest 写入、task/result samples 查询读新表 | API 合同不变，分页不再全量扫行内 JSON |
| V4-2 Publish snapshot | 1.5d | result dataset 发布冻结 sample snapshot、下载读 snapshot | JSONL/JSON 下载可复现 |
| V4-3 Idempotency reservation | 1d | cancel/retry/artifact-retry 并发同 key 原子化 | 并发 retry 不创建重复 synthetic task |
| V4-4 Reviews 一级工作台 | 1.5d | Reviews nav、query filters、queue summary、quick decision 强化 | 审核队列可深链、可保存、可恢复错误 |
| V4-5 Workbench SQL summary | 1d | 后端聚合 summary，前端 fallback 保留 | 大列表增长后首页不依赖宽列表聚合 |
| V4-6 Synthetic audit baseline | 1.5d | 关键写动作和下载动作审计、request ID 暴露 | 操作可按 request/task/result 追踪 |
| V4-7 E2E release gate | 1d | 本地 COS+TKE 和生产参数化 smoke 收口 | `npm run verify` + E2E smoke 通过 |

压缩版 demo 只做：

1. V4-1 Sample SQL model。
2. V4-3 Idempotency reservation。
3. V4-4 Reviews 一级工作台。
4. V4-7 E2E release gate。

## 验收命令

当前状态：

- V4-0 已完成：方案文档和 roadmap 入口已冻结。
- V4-1 已完成第一版：新增 SQL-backed `synthetic_samples` 和
  `synthetic_sample_sources`，`ingest_samples` 会写入 task sample rows，publish
  会把 sample rows 绑定到 result dataset；task/result samples API 保持原 response
  和 pagination headers，同时支持 `search/q`、`limit`、`offset` 和
  `quality_flag`。旧 `samples_json` 仍作为兼容快照和 fallback。
- V4-3 已完成：Synthetic API 在 cancel、retry、artifact retry 执行副作用前先创建
  operation idempotency reservation；同 key 并发请求命中 `in_progress` 时返回 409，
  不再调用 Harbor；完成后重复请求返回首次结果；失败记录为 `failed` 并要求客户端使用新
  idempotency key 重试。兼容实现先把 reservation 状态写入现有
  `metadata_json` 保留键。

已验证：

```text
cd synthetic-data-platform
uv run ruff check .
uv run pytest -q
```

结果：`82 passed`。

Synthetic API：

```bash
cd synthetic-data-platform
uv run ruff check .
uv run pytest -q
```

Frontend：

```bash
cd synthetic-data-platform/web
npm run verify
```

本地 COS + TKE：

```bash
cd deploy/docker-compose
HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=go-http-tracing \
HARBOR_E2E_FRONTEND_LIVE_CHECK=1 \
HARBOR_E2E_REQUIRE_PUBLISH=1 \
HARBOR_E2E_TIMEOUT_SEC=1800 \
./scripts/synthetic-cos-tke-e2e.sh
```

## 完成判定

V4 完成时必须能证明：

- 浏览器主链路端到端可用。
- 样本查询后端分页是真分页，不是前端或 API 层全量加载后切片。
- 同 key 并发 retry 不会创建重复 synthetic task。
- Review queue 是一级生产入口，审核状态可保存、可搜索、可深链。
- Workbench 不依赖全量 task/result 列表才能展示关键摘要。
- 关键写动作和下载动作有 request ID 和 audit evidence。
- 本地 COS + TKE smoke、前端 `npm run verify`、后端 `uv run pytest -q` 均通过。
