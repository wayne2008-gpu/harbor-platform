# Synthetic Data Platform Frontend Implementation Plan

> V4 平台化研发方案见
> [`synthetic-data-platform-v4-platformization-plan.md`](synthetic-data-platform-v4-platformization-plan.md)。
> 本文保留前端 MVP/V3 的设计冻结、实施切片和验收记录；V3 前端产品化设计见
> [`synthetic-data-platform-frontend-v3-design.md`](synthetic-data-platform-frontend-v3-design.md)。

## 2026-08-17 设计冻结：产品化前端下一轮

本轮先冻结前端设计，再进入开发。开发方式不是重写已有 MVP，而是在当前
`synthetic-data-platform/web` 基础上把“从浏览器完成端到端跑数”的产品体验补齐：

```text
上传/登记 dataset
  -> 创建 TKE synthetic task
  -> 观察运行和恢复失败
  -> 审核 trial trajectory / OpenAI messages
  -> ingest samples
  -> publish result dataset
  -> 下载 JSONL/JSON 并回溯 lineage
```

### Skill 查询依据

按要求使用 `ui-ux-pro-max` 做设计基线，当前前端栈识别为：

```text
React 19 + Vite + React Router + TanStack Query + lucide-react + Playwright
```

本轮采用的 skill 查询：

```text
internal analytics dashboard ai data operations
variance: 4/10
motion: 3/10
density: 9/10

dashboard navigation task list
error summary validation
keyboard focus tab
status dashboard workflow
icon button accessible label
rerender data table list
```

采用结论：

- 产品形态：Data-Dense Dashboard，高信息密度的业务工作台。
- 首屏：直接进入 Workbench，不做 landing page、hero、行业方案或营销 CTA。
- 视觉：浅色控制台为主，深色 sidebar 承载导航；蓝色用于主动作和信息状态，绿色/琥珀色/红色分别表达成功、待审、失败，避免全局单一蓝色。
- 动效：只保留 150-300ms 的 hover、focus、tab、loading、filter 反馈；不引入 GSAP，不做自动播放或滚动动画。
- 图表：MVP 不上复杂图表；运行态摘要优先用可访问的 KPI 文本、stage stepper、状态表。后续需要阈值目标时再用 compact bullet chart。
- 无障碍：所有 icon-only 控件必须有 accessible name；带文字按钮内图标 `aria-hidden`；表单错误同时有顶部 error summary 和字段内错误。
- React：列表项使用稳定业务 ID；query key 包含 search/filter/page；高频搜索用 debounce 或 `useDeferredValue`。

### 信息架构

顶层导航继续冻结为 5 个入口：

```text
Workbench | Datasets | Tasks | Results | Settings
```

不新增 Harbor 运维入口。Harbor 概念只作为 provenance 和 diagnostics 出现：

| Harbor 字段 | 前端位置 |
| --- | --- |
| `harbor_job_id` | Task Detail 状态和 lineage |
| `trial_id` | Trial Review 和 Result lineage |
| artifact kind/schema/path/COS URI | Task artifacts、Trial provenance、Result audit |
| runner/lease/execution namespace | Task diagnostics 底部 |

### 页面规格

#### Workbench

目标：用户进来 10 秒内知道“现在能不能跑、哪里失败、下一步点哪里”。

首屏顺序：

1. Readiness strip：Synthetic API、Harbor control-plane、Dataset COS、COS credential flag、runner/runtime readiness。
2. Next actions：setup blocker、failed task、active task、publish candidate、latest result。
3. Failure causes：dataset materialization、runtime/trial、artifact upload、sample ingest、publish。
4. Recent runs 和 latest result datasets。

约束：

- 不做复杂配置页。
- 失败和阻塞状态优先于普通统计。
- 每个 action 都跳到具体 dataset/task/result 详情页。

#### Datasets

目标：让 dataset 能被确认、上传、登记，并能一键进入任务创建。

列表字段：

```text
name | version | source | format | task_names | checksum/size | created | action
```

新建页：

- segmented control：Upload archive / Register COS URI。
- 表单字段有 visible label、inline error、顶部 error summary。
- payload preview 展示将提交的 dataset contract。
- 上传/登记成功后进入 dataset detail。

详情页：

- 展示 source URI、checksum、size、task_names、metadata。
- readiness 明确：是否有 task_name、checksum、可创建 task。
- 主动作：Create task from dataset，并通过 URL query 预填 `/tasks/new?datasetId=...`。

#### Tasks

目标：创建任务、观察运行、处理恢复动作。

Task Builder：

```text
left: dataset/task/runtime/agent/model/concurrency form
right: readiness gates + JobConfig preview
```

runtime 用 radio card 表达：

```text
docker | ags | tke
```

每个 runtime 显示实际 `environment.type`，避免用户把 agent-runtime 和
harbor-runtime 混在一起。

Task Detail：

```text
status header
execution chain: Queued -> Input ready -> Runtime -> Artifacts -> Samples -> Published
action queue: Sync / Cancel / Retry run / Retry artifacts / Ingest / Publish
trial review queue
artifacts
samples publish readiness
raw Harbor diagnostics
```

规则：

- failed 状态优先展示 retry run / retry artifacts。
- succeeded 状态优先展示 ingest / publish。
- published 状态优先展示 result dataset 链接。
- 每个 mutation 都有 pending/success/error live region 和下一步检查项。

#### Trial / Trajectory Review

目标：这是平台核心页，回答“这个 trial 是否适合进入后训练数据集”。

tab 冻结为：

```text
Summary | Timeline | OpenAI Messages | Raw JSON
```

URL 必须表达当前视图：

```text
/tasks/:task_id/trials/:trial_id?view=summary|timeline|messages|raw
```

Summary：

- Review decision：Ready / Needs review / Blocked / Checking。
- quality gates：reward、verifier、exception、schema readiness。
- schema alignment：ATIF/default trajectory 与 OpenAI messages 的覆盖情况。
- tool call mapping、content diff、message diff。
- anomaly summary，并可跳到 Timeline/OpenAI Messages。

Timeline：

- 按 step/message/tool call/observation 顺序展示。
- 支持 search、anomaly-only。

OpenAI Messages：

- 按后训练消费视角展示 `role/content/tool_calls/tool_call_id`。
- 标出 duplicate tool call id、missing tool response、orphan tool response。

Raw JSON：

- 放最后，只做兜底。

#### Results

目标：审核、下载、回溯发布后的 result dataset。

列表字段：

```text
name | version | sample_count | source task | source dataset | created | download
```

详情页：

```text
result metrics
delivery decision
samples review
field coverage / field profile
lineage: input dataset -> synthetic task -> Harbor job -> trial -> result dataset
trajectory audit links
download JSONL / JSON
```

规则：

- JSONL 是默认后训练消费格式。
- JSON 保留完整 metadata 和 lineage。
- 每个 source trial 都要能回跳到 Trial Review。
- 下载失败或空 result dataset 要给恢复路径。

#### Settings

目标：只读运行配置和本地 E2E 检查。

允许展示：

- Harbor control-plane base URL。
- dataset storage backend。
- COS bucket、region、prefix、endpoint。
- secret configured flags。
- 本地 COS + TKE E2E 命令和 manual checkpoints。

禁止展示：

- database password。
- COS secret_id。
- COS secret_key。
- session_token 明文。

### 组件规格

先复用 `synthetic-data-platform/web/src/ui.tsx`，不先拆独立设计系统包。

| 组件 | 用途 | 必须状态 |
| --- | --- | --- |
| `PageHeader` | 页面目标、上下文、主动作 | action 可为空，summary 可换行 |
| `DataTable` | 桌面扫描表格 | 移动端局部滚动或卡片化，不让页面横向溢出 |
| `StatusBadge` | 状态表达 | 文案独立表达含义，颜色只辅助 |
| `RunStageStepper` | task 执行链路 | done/active/pending/blocked |
| `ReadinessGate` | 提交前检查 | ready/warning/blocked + reason + action |
| `ActionQueue` | 恢复动作队列 | available/waiting/blocked + next check |
| `TrajectoryTabs` | 轨迹审核 | URL tab、键盘可达、焦点可见 |
| `LineageFlow` | 来源回溯 | dataset/task/job/trial/result 可点击 |
| `MutationStatus` | 异步动作反馈 | `role=status`，不打断焦点 |
| `JsonBlock` | 原始 JSON 兜底 | 默认下沉，不抢主流程 |

### 下一轮开发排期

以当前已有 MVP 为基础，按“端到端可用优先”推进：

| 阶段 | 工作量 | 内容 | 验收 |
| --- | --- | --- | --- |
| FE-N0 设计冻结 | 0.5d | 对齐本文、design-system、API 缺口、页面优先级 | 文档可直接拆任务 |
| FE-N1 Dataset 真实上传体验 | 1d | 上传/登记表单、进度/错误、成功跳转、dataset readiness | 浏览器完成 dataset 上传/登记 |
| FE-N2 TKE Task Builder | 1d | runtime radio、JobConfig preview、URL 预填、提交前 gates | 从 dataset 创建 TKE task |
| FE-N3 Task 运行恢复 | 1.5d | stage stepper、action queue、cancel/retry/artifact retry/ingest/publish 反馈 | 失败/成功任务都有明确下一步 |
| FE-N4 Trajectory Review | 2d | Summary、Timeline、OpenAI Messages、diff/anomaly、tab deep link | 可审核 trial 是否适合后训练 |
| FE-N5 Result Review/Download | 1.5d | delivery decision、samples review、lineage、JSONL/JSON 下载 | 可回溯并下载 result dataset |
| FE-N6 Workbench/Settings/E2E | 1d | readiness、failure causes、E2E 命令、响应式和 live test | 本地 COS + TKE E2E 可用 |

预计 8.5 个工作日。若只做“能跑通 demo”，可压缩到 4-5 个工作日，先实现
FE-N1、FE-N2、FE-N3、FE-N5，Trajectory Review 保留基础 Raw/Message 查看。

当前进度：

- `FE-N1 Dataset 真实上传体验` 已完成：上传文件格式/空文件校验、上传/登记
  readiness panel、pending live feedback、登记 integrity metadata readiness、UI
  smoke 覆盖均已落地。
- `FE-N2 TKE Task Builder` 已完成：Task builder/input/request contract 检查项
  增加显式状态标签，TKE execution handoff 明确展示 harbor-control-plane 到
  harbor-runner 再到 Harbor runtime 的 `provider=tke` / `environment.type=tke`
  路径，URL 预填、runtime radio、payload preview 和错误恢复继续由 UI smoke 覆盖。
- `FE-N3 Task 运行恢复` 已完成：Task Detail 已覆盖 status overview、execution
  chain、action queue、run controls、operation feedback、cancel/retry/artifact
  retry/ingest/publish；本轮补充 failure recovery 的推荐动作状态和诊断确认
  checklist，input failure 与 artifact persistence failure 均有 UI smoke 覆盖。
- `FE-N4 Trajectory Review` 已完成：Trial Summary 增加
  `Trajectory audit checklist`，统一展示 trial-result、ATIF/default、
  OpenAI messages、tool call mapping、content diff、message diff、anomaly
  review 的审核状态、数量指标和跳转动作；Timeline/OpenAI Messages 的 tab
  deep link、anomaly-only、schema alignment、mapping/content/message diff 继续由
  UI smoke 覆盖。
- `FE-N5 Result Review/Download` 已完成：Result Detail 已覆盖 delivery
  decision、result review checklist、samples review、field profile、lineage、
  trajectory audit links、export contract、JSONL/JSON 下载；本轮补充
  `Result download recovery`，下载失败时给出错误原因和同格式重试，空 result
  dataset 时给出 source task / samples / lineage 的恢复路径，UI smoke 已覆盖成功、
  失败重试和空结果阻塞状态。
- `FE-N6 Workbench/Settings/E2E` 已完成：Workbench 已覆盖 readiness strip、
  prioritized next actions、failure causes、runtime/provider load、recent runs、
  latest results 和 local E2E 快捷入口；Settings 已覆盖 safe runtime/COS config、
  secret configured flags、Local E2E readiness、execution plan、manual checkpoints
  和可复制命令；`npm run verify` 覆盖响应式 UI smoke，`npm run test:live`
  提供真实 COS/TKE 前端联调用例，缺少 live env 时按设计 skip。

### 开发验收命令

前端每个切片结束后运行：

```bash
cd synthetic-data-platform/web
npm run verify
```

真实联调时运行：

```bash
cd deploy/docker-compose
HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=go-http-tracing \
HARBOR_E2E_FRONTEND_LIVE_CHECK=1 \
HARBOR_E2E_TIMEOUT_SEC=1800 \
./scripts/synthetic-cos-tke-e2e.sh
```

## 设计结论

本轮前端先按“后训练 agent 轨迹数据合成工作台”设计和开发，不做 Harbor
运维控制台，也不做官网式 landing page。

设计基线来自 `ui-ux-pro-max`：

```text
internal data platform dashboard operations
variance: 4/10
motion: 3/10
density: 9/10
stack: React 19 + Vite + React Router + TanStack Query
```

技能查询命中了 `Data-Dense Dashboard` 风格，这是本平台采用的方向。生成器同时命中了
`Enterprise Gateway` 官网结构，这部分不采用。设计系统已落到：

```text
design-system/synthetic-data-platform/MASTER.md
```

## 产品定位

前端主流程是：

```text
Dataset -> Synthetic task -> Trial trajectory -> Samples -> Result dataset
```

Harbor 概念只作为执行证据和诊断信息出现：

- `harbor_job_id`：任务详情和 lineage。
- `trial_id`：trial 轨迹审核和 result 回溯。
- `artifact kind/schema/path/cos_uri`：artifact 表、下载和 provenance。
- `runner_id`、`lease_id`、`execution_id`：诊断区，不进入主导航。

## MVP 信息架构

顶层导航固定为 5 个入口：

```text
Workbench | Datasets | Tasks | Results | Settings
```

路由范围：

```text
/workbench
/datasets
/datasets/new
/datasets/:dataset_id
/tasks
/tasks/new
/tasks/:task_id
/tasks/:task_id/trials/:trial_id?view=summary|timeline|messages|raw
/results
/results/:result_dataset_id
/settings
```

关键状态必须进入 URL：

- 列表 search/filter/page。
- task builder 的 `datasetId` 预填。
- trial trajectory 的 `view` tab。
- result dataset 回跳 trial 时的目标 view。

## 页面设计

### Workbench

目标：回答“现在能不能跑、哪里失败了、下一步做什么”。

首屏顺序：

1. Readiness：Synthetic API、Harbor control-plane、Dataset COS、COS credential flag。
2. Next actions：blocked、failed、active、publish candidate、latest result。
3. Failure causes：input materialization、runtime/trial、artifact persistence、sample/publish。
4. Active runs、recent runs、latest results。

Workbench 不承载复杂配置，所有动作跳到对应详情页。

### Datasets

目标：管理输入数据并确认是否可用于 Harbor runtime。

能力：

- 上传 archive 或登记 COS URI。
- 展示 name、version、source、format、task_names、checksum、size。
- 从 dataset 详情创建 task，并把 `datasetId` 写入 `/tasks/new` query。
- 显示 dataset 使用过的 recent tasks 和 result datasets。

表单规则：

- visible label。
- 字段内错误。
- 顶部 error summary，失败提交后 focus 到 summary。
- payload preview 展示即将提交的 dataset contract。

### Tasks

目标：创建任务、观察执行、处理恢复动作。

任务创建：

- 必填：dataset、task_name、runtime provider、agent。
- 可选：model、concurrency。
- runtime 用 radio card 表达 `docker`、`ags`、`tke`，并展示实际
  `environment.type`。
- 右侧展示 JobConfig preview 和 readiness gates。

任务详情：

```text
status header
execution chain: Queued -> Input ready -> Runtime -> Artifacts -> Samples -> Published
action queue: Sync / Cancel / Retry run / Retry artifacts / Ingest / Publish
trial review queue
artifacts
samples publish readiness
raw Harbor job / diagnostics
```

失败任务优先展示恢复动作，成功任务优先展示 ingest / publish，已发布任务优先展示
result dataset 链接。

### Trial / Trajectory

目标：审核 trial 是否适合进入后训练数据集。

默认 tab：

```text
Summary | Timeline | OpenAI Messages | Raw JSON
```

规则：

- 默认进入 Summary。
- `?view=` 表达当前 tab。
- Summary 展示 quality gates、schema alignment、tool call mapping、content diff、
  message diff。
- Timeline 和 OpenAI Messages 支持 search/filter/anomaly-only。
- Raw JSON 放最后，只做兜底。
- trajectory 缺失时提供 artifact retry 或返回 task artifacts 的恢复路径。

### Results

目标：审核、下载和回溯发布后的 result dataset。

能力：

- result metrics。
- samples review：quality summary、search、anomaly-only、pagination。
- field coverage 和 field profile：Result Detail 使用后端
  `/result-datasets/{id}/samples/field-profile` 汇总服务端匹配样本集。
- lineage：input dataset -> synthetic task -> Harbor run -> result dataset。
- download：JSONL 优先，JSON 保留完整 metadata。
- source trial 分组回跳到 trajectory audit。
- delivery decision：把样本、reward、lineage、trajectory audit、export
  contract 汇总成 Ready / Needs review / Blocked / Checking。

### Settings

目标：本地 E2E 和运行配置只读检查。

允许展示：

- Harbor control-plane base URL。
- dataset storage backend。
- COS bucket、region、prefix、endpoint。
- secret configured flags。
- E2E readiness gates 和命令。

禁止展示：

- database password。
- COS secret_id。
- COS secret_key。
- session_token 明文。

## 组件模型

先复用当前 `synthetic-data-platform/web/src/ui.tsx`，不先抽设计系统包。

核心组件：

- `PageHeader`：页面目标、上下文、主动作。
- `PanelHeader`：单个 panel 的标题、摘要、局部动作。
- `DataTable`：桌面表格，移动端局部横向滚动或记录卡片。
- `StatusBadge`：文字独立表达状态，颜色只做辅助。
- `RunStageStepper`：任务执行链路。
- `ReadinessGate`：ready/warning/blocked 三态，附原因和下一步动作。
- `ActionQueue`：按优先级展示可执行动作和 blocked reason。
- `LineageFlow`：dataset/task/trial/artifact/result 可点击来源链。
- `TrajectoryTabs`：tab state 进入 URL query，键盘可切换。
- `DiffTable`：schema alignment、tool call mapping、message/content diff。
- `JsonBlock`：Raw JSON 兜底查看。

## 技术约束

当前前端栈：

```text
React 19
Vite
React Router
TanStack Query
lucide-react
Playwright
```

实现规则：

- 列表 query key 必须包含 search/filter/page。
- 列表项使用稳定业务 ID 作为 key。
- 搜索输入使用 `useDeferredValue` 或 debounce，避免按键触发重计算。
- 危险动作必须有确认流程。
- mutation 结果使用 live region。
- 所有 icon 使用 lucide-react。
- 组件圆角不超过 8px。
- 不做 hero、渐变装饰、营销卡片、自动播放动画。
- 支持 375、768、1024、1440px 视口。

## API 依赖

前端第一版优先使用现有 `synthetic-data-platform` API：

| 页面 | API 能力 |
| --- | --- |
| Workbench | settings、datasets、synthetic tasks、result datasets、task results |
| Datasets | list/register/upload/get dataset、关联 tasks/results |
| Task Builder | list datasets、create synthetic task |
| Task Detail | get task results、generation cost breakdown、budget status、sync、cancel、retry、artifact retry、ingest、publish |
| Trial Review | get trial trajectory、artifact download |
| Results | list/get/download result dataset |
| Settings | safe settings summary |

如果后端暂时没有服务端分页或完整 trajectory summary，MVP 可以先在前端用现有
artifacts/trials/trajectory JSON 派生展示；后续再把高成本计算下沉到后端。

## 开发排期

以 2026-08-17 起的工作日估算，先做 UI 闭环，再补更多管理能力。

| 阶段 | 状态 | 工作量 | 内容 | 验收 |
| --- | --- | --- | --- | --- |
| FE-0 设计基线 | Done | 0.5d | 对齐 design-system、CSS token、页面密度、按钮/表格/面板规范 | 设计文档和 token 可引用 |
| FE-1 Dataset + Task Builder | Done | 1.5d | dataset 上传/登记体验、builder readiness、payload preview、error summary | 可从 dataset 创建 TKE task |
| FE-2 Task Detail 恢复闭环 | Done | 1.5d | execution chain、action queue、cancel/retry/artifact retry/ingest/publish feedback | 失败和成功任务都有明确下一步 |
| FE-3 Trial / Trajectory Review | Done | 2d | Summary、Timeline、OpenAI Messages、Raw JSON、anomaly-only、diff tables | 可审核 ATIF 和 OpenAI messages |
| FE-4 Results Review | Done | 1.5d | result list/detail、delivery decision、samples review、field profile、lineage、download | 可下载并回溯 source trial |
| FE-5 Workbench + Settings E2E | Done | 1d | readiness、next actions、failure causes、本地 E2E 命令、响应式截图 | 375/768/1024/1440px smoke 通过 |

总计约 8 个工作日。当前代码已经有不少基础页面，实际开发可以按缺口抵扣，不需要重写。

## 验收命令

每个切片结束后运行：

```bash
cd synthetic-data-platform/web
npm run build
npm run test:ui
npm run verify
```

端到端联调时再启动本地 compose，并跑 COS + TKE 流程：

```bash
cd deploy/docker-compose
HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=go-http-tracing \
HARBOR_E2E_TIMEOUT_SEC=1800 \
./scripts/synthetic-cos-tke-e2e.sh
```

## 当前状态

截至 2026-08-17：

- FE-0 已完成：`styles.css` 补齐 design-system token 别名，主要可点击控件使用
  44px 触达尺寸，表单错误态覆盖 input、select、textarea。
- FE-1 已完成：`/datasets/new` 展示 dataset contract preview，支持 checksum
  格式校验和 error summary focus；`/tasks/new` 的 builder readiness、input
  readiness、request contract、payload preview、TKE payload 和错误 summary 已有
  Playwright 覆盖。
- FE-2 已完成：Task Detail 覆盖状态总览、execution chain、action queue、
  cancel/retry/artifact retry/ingest/publish 反馈；operation feedback 增加
  `Next check`，明确每个恢复动作后应该观察的状态字段或入口。
- FE-3 已完成：Trial Summary 增加 `Review decision`，把 reward、verifier、
  exception、schema、anomaly、mapping、content diff、message diff 归纳为
  Ready / Needs review / Blocked / Checking，并提供 Timeline / OpenAI Messages
  快捷审核入口；Playwright 覆盖 Summary 决策、tab deep link、anomaly-only、
  schema alignment、tool call mapping、content diff 和 message diff。
- FE-4 已完成：Result Detail 增加 `Result delivery decision`，把 sample
  count、sample anomaly、reward coverage、source lineage、trajectory audit、
  export contract 汇总为 Ready / Needs review / Blocked / Checking，并提供
  samples、trajectory audit、downloads 三个审核落点；Playwright 覆盖结果交付决策、
  lineage、source trial 回跳、artifact 下载入口、samples review、后端 field
  profile 和 JSONL/JSON download feedback。
- FE-5 已完成：Workbench 首屏覆盖 Platform API、Harbor control-plane、Dataset COS、
  COS credentials、Datasets readiness，并保留 next actions、failure causes、
  runtime/provider load、recent runs、latest results；V4-77 后 Summary API 区块
  展示 generation usage metrics，包括 sample yield、observed runtime、
  runtime/model/provider bucket 和 reported token usage；V4-78 后同一区块展示
  configured cost estimate 和 costed model evidence；V4-79 后 Task Detail 展示
  单任务 generation cost breakdown，包括 runtime/model/provider、trial/token
  evidence、sample yield 和 configured cost estimate；V4-80 后 Workbench 和
  Task Detail 展示 configured budget status；V4-82 后 Result Detail 展示
  发布时冻结的 `generation_cost_snapshot`，用于结果交付成本审计；V4-83 后 snapshot
  和 `cost_estimate` 携带 operator-defined `price_table_version`；V4-84 后 Workbench
  和 Task Detail 直接展示当前估算使用的 price table version。Settings 展示只读安全配置、
  Local E2E readiness、COS/TKE preflight、Full COS/TKE E2E 命令和 manual
  checkpoints，Playwright 覆盖 375/768/1024/1440/wide 响应式截图和无横向溢出。
- 前端入口已改为 route-level lazy loading：Workbench、Datasets、Tasks/Trials、
  Results 页面按路由拆包，首包从约 519KB 降到约 294KB，Vite 大 chunk 警告消失。
- 移动端 app shell 已修正为稳定紧凑 top rail：小屏 sidebar 不再被外层 grid stretch
  撑高，主导航保持横向滚动，Playwright 覆盖 375px 视口。
- 本轮按 `ui-ux-pro-max` 重新确认设计冻结后，复跑前端验收命令：
  `npm run verify` 已通过，结果为 build 通过、Playwright `24 passed`。

前端 MVP UI 闭环已完成。下一步建议进入后端接口/真实 E2E 差距收敛，或者启动
tenant/auth/权限与任务管理的下一轮平台能力设计。
