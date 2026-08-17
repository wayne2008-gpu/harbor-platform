# Synthetic Data Platform Frontend V3 Design

## 目标

本轮前端要把 `synthetic-data-platform` 做成“后训练 agent 轨迹数据合成平台”的
业务工作台。它不是 Harbor 运维后台，也不是展示型官网。

用户应该可以从浏览器完成这条主链路：

```text
上传或登记 dataset
  -> 创建 TKE synthetic task
  -> 查看运行状态和失败恢复入口
  -> 审核 trial trajectory / OpenAI messages
  -> 保存人工审核结论
  -> ingest samples
  -> publish result dataset
  -> 下载 JSONL/JSON 并回溯 lineage
```

## UI/UX 设计依据

按要求使用 `ui-ux-pro-max` 设计。当前前端栈是：

```text
React 19 + Vite + React Router + TanStack Query + lucide-react + Playwright
```

本轮查询：

```text
agent trajectory data operations dashboard
variance: 4/10
motion: 3/10
density: 9/10

inline validation error
live status feedback
icon button accessible label
rerender memo list
```

采用结论：

- 产品形态采用 `Data-Dense Dashboard`，即高密度、可扫描、少装饰的运营工作台。
- 页面首屏直接进入业务流程，不做 hero、营销 CTA、客户 logo、行业方案。
- 动效只用于 hover、focus、tab、loading、filter 状态反馈，控制在 150-300ms。
- 表单错误使用顶部 error summary + 字段 inline error。
- 异步动作使用 `role=status` 或等价 live region，不能点击后无反馈。
- icon 使用 `lucide-react`；带文字按钮里的 icon 作为装饰，icon-only 按钮必须有
  accessible name。
- 列表使用稳定业务 ID 作为 React key；搜索和筛选后续用 debounce 或
  `useDeferredValue`，避免大列表输入卡顿。

沿用现有设计系统：

- `design-system/synthetic-data-platform/MASTER.md`
- 主色 `#1E40AF`，强调色 `#D97706`，背景 `#F8FAFC`。
- 保持浅色数据工作台，不把整站做成单一蓝色。
- 卡片圆角不超过 8px。

## 信息架构

一级导航保持 5 个入口：

```text
Workbench | Datasets | Tasks | Results | Settings
```

暂不新增 `Harbor` 运维入口。Harbor 字段只作为 provenance 和 diagnostics 出现。

建议路由：

```text
/workbench
/datasets
/datasets/new
/datasets/:dataset_id
/tasks
/tasks/new?datasetId=...&taskName=...
/tasks/:task_id
/tasks/:task_id/trials/:trial_id?view=summary|timeline|messages|raw
/results
/results/:result_dataset_id
/settings
```

后续如果跨任务审核队列变成主工作流，再评估新增：

```text
/reviews?state=needs_review
```

本轮不先加顶级 Reviews，避免导航提前膨胀。

## 页面蓝图

### Workbench

目标：用户进入后 10 秒内知道“当前能不能跑、哪里失败、下一步做什么”。

页面顺序：

1. Readiness strip：Synthetic API、Harbor API、Dataset COS、COS credentials、
   runtime provider。
2. Next actions：按 blocker、failed、active、publish candidate、latest result 排序。
3. Failure causes：dataset materialization、runtime/trial、artifact upload、
   sample ingest、publish。
4. Active runs / recent runs。
5. Latest result datasets。

交互规则：

- 每个 action 都跳到具体 dataset/task/result/trial 页面。
- failed 状态优先于普通统计展示。
- Workbench 不承载复杂配置，配置检查跳 Settings。

### Datasets

目标：管理输入数据，并确认 dataset 能被 Harbor runtime 使用。

列表字段：

```text
name | version | source | format | task_names | checksum/size | created | action
```

新建页：

- Segmented control：`Upload archive` / `Register COS URI`。
- 上传支持本地 archive，登记支持已有 `cos://...`。
- 表单右侧或下方展示 dataset contract preview。
- 成功后跳转 dataset detail。

详情页：

- 展示 source URI、checksum、size、task_names、metadata。
- 展示 version family、recent tasks、result datasets。
- 主动作是 `Create task from dataset`，通过 URL query 预填 task builder。

需要注意：

- `task_names` 缺失不是纯技术错误，要明确提示“无法精确创建 Harbor benchmark task”。
- 长 COS URI、checksum 必须换行或局部滚动，不能撑破移动端。

### Task Builder

目标：降低选错 dataset、task_name、runtime provider 的概率。

布局：

```text
left: dataset / task_name / runtime / agent / model / concurrency form
right: readiness gates + JobConfig preview
```

runtime 以 radio cards 表达：

```text
docker | ags | tke
```

每个 runtime card 显示实际 `environment.type`，避免混淆：

- `harbor-runtime`：Harbor CLI 执行控制代码。
- `agent-runtime`：agent 真正执行任务的容器、TKE、AGS 或沙箱环境。

提交前 readiness：

- dataset source 是否可用。
- task_name 是否来自 dataset catalog。
- checksum 是否存在。
- runtime provider 是否已选择。
- concurrency 是否为正整数。

### Task Detail

目标：观察运行、恢复失败、进入 trial 审核。

结构：

```text
status header
execution chain: Queued -> Input ready -> Runtime -> Artifacts -> Samples -> Published
action queue: Sync / Cancel / Retry run / Retry artifacts / Ingest / Publish
trial review queue
artifacts
sample publish readiness
raw Harbor diagnostics
```

状态优先级：

- `failed`：优先展示 retry run / retry artifacts。
- `succeeded`：优先展示 ingest samples / publish。
- `published`：优先展示 result dataset 链接。
- `running`：展示 polling 状态和当前 execution stage。

动作反馈：

- mutation pending 时按钮 disabled，并显示当前操作。
- 成功后提示下一步检查项。
- 失败后展示可恢复动作，不只展示异常字符串。

### Trial / Trajectory Review

目标：判断一个 trial 是否适合进入后训练数据集。这是本轮前端的核心页面。

Tab 固定为：

```text
Summary | Timeline | OpenAI Messages | Raw JSON
```

URL 使用：

```text
/tasks/:task_id/trials/:trial_id?view=summary|timeline|messages|raw
```

Summary：

- Trial metrics：state、reward、verifier、exception、duration、model。
- Review decision：`approved`、`needs_review`、`rejected`、`blocked`。
- Quality gates：reward、verifier、exception、schema readiness。
- Schema alignment：ATIF/default trajectory 与 OpenAI messages 覆盖情况。
- Tool thread integrity：duplicate tool call id、missing tool response、
  orphan tool response。
- Audit provenance：source artifact、schema、COS URI、checksum。

人工审核持久化：

```text
decision: approved | needs_review | rejected | blocked
reviewer: string
rationale: string
labels: string[]
updated_at: datetime
```

设计原则：

- 自动质量判断和人工审核结论分开展示。
- 自动判断可以提示 `Ready / Needs review / Blocked / Checking`。
- 人工结论必须可保存、可回显、可覆盖更新。
- 保存失败时保留用户输入，不丢失草稿。

Timeline：

- 按 step/message/tool call/observation 顺序展示。
- 支持 search。
- 支持 anomaly-only。
- artifact 引用可跳转或下载。

OpenAI Messages：

- 按后训练消费视角展示 `role/content/tool_calls/tool_call_id`。
- `assistant` tool_calls 与 `tool` responses 应该视觉成组。
- schema 问题直接标到对应 message。
- 支持复制单条 message JSON 和完整 messages JSON。

Raw JSON：

- 放最后，只做兜底诊断。
- 默认折叠大对象，避免抢占审核主流程。

### Results

目标：审核、下载、回溯发布后的 result dataset。

列表字段：

```text
name | version | sample_count | source task | source dataset | created | download
```

详情页结构：

```text
result metrics
delivery decision
sample review scope
samples table / preview
field coverage / field profile
lineage: input dataset -> synthetic task -> Harbor job -> trial -> result dataset
trajectory audit links
download JSONL / JSON
```

规则：

- JSONL 是默认后训练消费格式。
- JSON 保留完整 metadata 和 lineage。
- 当 API 返回的 samples 只是 preview 时，要明确提示完整数据通过 download 获取。
- 每个 source trial 都要能回跳到 Trial Review。

### Settings

目标：只读展示运行配置和端到端测试检查。

允许展示：

- Harbor API base URL。
- dataset storage backend。
- COS bucket、region、prefix、endpoint。
- secret configured flags。
- local COS/TKE E2E command 和 manual checkpoints。

禁止展示：

- database password。
- COS secret_id。
- COS secret_key。
- session_token 明文。

## 当前 API 适配

已有 API 足够支撑 MVP 页面主链路：

| 能力 | 当前 API |
| --- | --- |
| dataset 上传/登记 | `POST /datasets/upload`、`POST /datasets/register` |
| dataset 查询 | `GET /datasets`、`GET /datasets/{id}` |
| 创建 synthetic task | `POST /synthetic-tasks` |
| task 查询和控制 | `GET /synthetic-tasks/{id}`、`sync`、`cancel`、`retry` |
| artifact retry | `POST /synthetic-tasks/{id}/artifacts/retry` |
| task results | `GET /synthetic-tasks/{id}/results` |
| trial trajectory | `GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory` |
| OpenAI messages trajectory | `GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory?schema=openai_messages` |
| 人工审核结论 | `GET/PUT /synthetic-tasks/{id}/trials/{trial_id}/review-decision` |
| ingest samples | `POST /synthetic-tasks/{id}/ingest-samples` |
| publish result dataset | `POST /synthetic-tasks/{id}/publish` |
| result datasets | `GET /result-datasets`、`GET /result-datasets/{id}` |
| result download | `GET /result-datasets/{id}/download?format=jsonl|json` |
| workbench summary | `GET /workbench/summary` |
| safe settings | `GET /settings` |

本轮前端要补齐的后端缺口：

| 缺口 | 建议 API | 优先级 |
| --- | --- | --- |
| result samples 分页/搜索 | `GET /result-datasets/{id}/samples?page=...&q=...` | P1 |
| task/trial 审核队列聚合 | `GET /reviews/trials?state=...` | P2 |
| task event stream | `GET /synthetic-tasks/{id}/events` 或轻量 polling summary | P2 |
| artifact browser 下载策略 | signed URL 或 API proxy 明确化 | P2 |

已完成：

| 能力 | API | 状态 |
| --- | --- | --- |
| 人工审核结论持久化 | `GET/PUT /synthetic-tasks/{task_id}/trials/{trial_id}/review-decision` | FE-V3-1 已实现 |

## 开发切片

本轮建议先按“可交付闭环”做，不重写现有页面。

| 阶段 | 工期 | 内容 | 验收 |
| --- | --- | --- | --- |
| FE-V3-0 设计冻结 | 0.5d | 本文档、接口缺口、页面优先级确认 | 可直接拆 PR |
| FE-V3-1 Review decision API + UI | 1.5d | 后端保存/查询人工审核结论；Trial Summary 增加审核表单和回显 | 审核结论刷新后仍保留 |
| FE-V3-2 Dataset Console 强化 | 1d | 上传/登记体验、contract preview、readiness 文案、移动端长 URI | 可从页面完成 dataset 上传并创建任务 |
| FE-V3-3 Task Run Console 强化 | 1.5d | Task Builder/Detail 的 runtime、execution chain、恢复动作反馈打磨 | TKE task 从创建到恢复动作都有明确下一步 |
| FE-V3-4 Trajectory Reviewer 强化 | 2d | Summary/Timeline/Messages 搜索、anomaly-only、tool thread 分组、复制 JSON | 能人工审核 OpenAI messages 轨迹 |
| FE-V3-5 Result Dataset Console 强化 | 1.5d | sample preview 范围、field profile、lineage、JSONL/JSON 下载反馈 | 可回溯并下载结果数据集 |
| FE-V3-6 Live E2E UI 验收 | 1d | Playwright live 覆盖 dataset -> TKE task -> result download | 本地 COS + TKE 端到端通过 |

总计约 9 个工作日。

当前进度：

- `FE-V3-0 设计冻结` 已完成：设计入口为本文档，视觉基线沿用
  `design-system/synthetic-data-platform/MASTER.md`。
- `FE-V3-1 Review decision API + UI` 已完成第一版：后端新增
  `synthetic_trial_review_decisions` 持久化表，synthetic API 新增
  `GET/PUT /synthetic-tasks/{task_id}/trials/{trial_id}/review-decision`，
  Trial Summary 新增 `Manual review decision` 表单，支持 reviewer 必填校验、
  decision 保存、labels/rationale 保存、刷新后回显。

如果要压缩成演示版，优先做：

1. `FE-V3-1 Review decision API + UI`
2. `FE-V3-3 Task Run Console 强化`
3. `FE-V3-4 Trajectory Reviewer 强化`
4. `FE-V3-6 Live E2E UI 验收`

这样可以最快证明“轨迹数据生成、审核、导出”的核心平台价值。

## 验收标准

每个前端切片至少运行：

```bash
cd synthetic-data-platform/web
npm run verify
```

真实联调运行：

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

UI 验收：

- 375、768、1024、1440px 无页面级横向滚动。
- keyboard tab 顺序可用，focus ring 可见。
- 表单有 visible label、inline error、顶部 error summary。
- 异步动作有 pending/success/error 状态反馈。
- icon-only 控件有 accessible name。
- 长 ID、COS URI、checksum、JSON 不撑破布局。
- `prefers-reduced-motion` 下不丢失关键内容。
- Settings 不泄露 database password、COS secret_id、secret_key、session_token。
