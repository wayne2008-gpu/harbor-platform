# Synthetic Data Platform Frontend Design

> 开发入口文档：
> [`synthetic-data-platform-frontend-implementation-plan.md`](synthetic-data-platform-frontend-implementation-plan.md)。
> 本文保留详细页面设计和交互规则，实施排期、切片验收和当前开发顺序以前者为准。

## 目标

`synthetic-data-platform` 前端是后训练 agent 轨迹数据合成平台的业务工作台，不是 Harbor 的运维控制台，也不是产品官网。

前端第一阶段要让使用者完成四条闭环：

1. 管理输入 dataset，并确认 dataset 是否可用于 Harbor runtime。
2. 基于 dataset 创建 synthetic task，选择 agent-runtime provider，例如 `tke`。
3. 查看任务执行状态、trial、trajectory、artifact、sample 导入和 publish 状态。
4. 查看并下载发布后的 result dataset，回溯来源任务、trial 和 artifact。

设计原则来自 `ui-ux-pro-max` 的 Data-Dense Dashboard 方向：高密度、可扫描、低装饰、状态清晰、键盘可达。丢弃官网型 Enterprise Gateway / landing page pattern。

## 设计系统决策

本轮使用 `ui-ux-pro-max` 做前端设计基线查询，输入为：

```text
internal data platform dashboard operations
variance: 4/10
motion: 3/10
density: 9/10
```

采用结论：

- 产品形态采用 Data-Dense Dashboard，而不是官网型 Enterprise Gateway。
- 页面首屏直接进入业务工作台，不做 hero、营销 CTA、行业/角色方案区。
- 密度偏高，优先展示任务状态、dataset、runtime、artifact、sample、result dataset 等可操作信息。
- 动效保持低强度，只用于 hover、loading、filter、tab 切换和状态反馈；支持 `prefers-reduced-motion`。
- 数据表移动端使用卡片化或局部横向滚动，不能让页面整体横向溢出。
- React 实现上，表单使用 controlled components；搜索/筛选输入后续使用 deferred value 或 debounce，避免大列表每次按键全量重算。

不采用结论：

- 不采用 Enterprise Gateway 的 Hero、Solutions by Industry、Client Logos、Contact Sales。
- 不使用自动播放视频、旋转 logo、装饰性大图或渐变背景。
- 不为了“看起来像平台”堆叠大量无操作价值的卡片。

## 开发前设计冻结

本轮前端设计先冻结“后训练 agent 轨迹数据合成工作台”的操作体验，再进入开发。设计
查询继续使用 `ui-ux-pro-max`：

```text
internal data platform dashboard operations
variance: 4/10
motion: 3/10
density: 9/10
stack: React 19 + Vite + React Router + TanStack Query
```

采用 Data-Dense Dashboard 作为视觉和交互基线；查询返回的 Enterprise Gateway
营销结构不适合本产品，继续排除。关键 UX 规则落实为：

- URL 必须表达关键状态：列表 search/filter/page、task builder 预填参数、trial
  trajectory tab 都要支持 deep link。
- 错误必须可恢复：失败任务、上传失败、artifact retry、sample ingest、publish
  都要给出原因、下一步动作和重试入口。
- 表格优先服务扫描效率：桌面端表格，移动端记录卡片或表格容器内横向滚动，不能造成
  页面级横向滚动。
- 表单必须有 visible label、字段内错误和顶部 error summary；提交期间按钮 disabled
  并展示提交状态。
- 复杂数据只在需要时展开：Raw JSON、COS key、Harbor job 原始字段放在详情/诊断区，
  不抢占主流程。

### 设计对象

前端不是 Harbor 运维后台，而是合成数据生产工作台。页面语言以业务流程为中心：

```text
Dataset -> Synthetic task -> Trial trajectory -> Samples -> Result dataset
```

Harbor 内部字段只作为可追溯证据出现：

- `harbor_job_id`：任务详情和 lineage。
- `trial_id`：trial 详情、result dataset 回跳。
- `artifact kind/schema/path/cos_uri`：artifact 表和 provenance。
- `runner_id`、`lease_id`、`execution_id`：诊断区，不进入主导航。

### 首屏结构

顶层导航保持 5 个入口，不增加 Harbor 运维入口：

```text
Workbench | Datasets | Tasks | Results | Settings
```

布局保持固定结构：

```text
┌──────────────────────────────────────────────────────────────┐
│ skip link                                                     │
├──────────────┬───────────────────────────────────────────────┤
│ sidebar      │ page header: title / context / primary action │
│              ├───────────────────────────────────────────────┤
│ primary nav  │ operational strip / filters / status summary  │
│              ├───────────────────────────────────────────────┤
│              │ main workflow panel                           │
│              │ secondary diagnostics / raw details last      │
└──────────────┴───────────────────────────────────────────────┘
```

移动端保留同样的信息顺序：状态和主动作先出现，表格转记录卡片；长 ID、URI、checksum
使用可换行容器或局部滚动。

### 页面设计冻结

#### Workbench

目标：回答“现在能不能跑、哪里失败了、下一步做什么”。

首屏顺序：

1. Readiness strip：Synthetic API、Harbor API、Dataset COS、COS credential flag。
2. Next actions：按 blocker、failed、active、publish candidate、latest result 排序。
3. Failure causes：input materialization、runtime/trial、artifact persistence、sample/publish。
4. Active runs 和 recent runs。
5. Latest result datasets。

Workbench 不承载复杂配置；所有动作必须跳到对应详情页，避免首页变成不可维护的控制台。

#### Datasets

目标：让用户确认输入数据是否能被 Harbor runtime 使用。

列表页：

- Search/filter 进入 URL query。
- 字段聚焦 name、version、source、format、task_names、checksum/size readiness、action。
- 空状态主动作是 Upload/Register dataset。

新建页：

- Segmented control：Upload archive / Register COS URI。
- 右侧或底部 payload preview 展示即将传给后端的 dataset contract。
- checksum、task_names、format 的缺失要提示影响，而不是用技术异常拦住用户。

详情页：

- Dataset source、task_names、checksum、size、created。
- 同名 version family。
- 使用该 dataset 的 recent tasks 和 result datasets。
- 主动作：Create task from dataset，预填 dataset/task_name。

#### Task Builder

目标：降低“选错 dataset、task_name、runtime”的概率。

布局：

```text
left: task form
right: readiness + JobConfig preview
```

必填字段：dataset、task_name、runtime provider、agent。可选字段：model、concurrency。
runtime 用 radio cards 表达 `docker`、`ags`、`tke`，并展示实际 `environment.type`。

提交前 readiness：

- dataset source 是否可用。
- task_name 是否在 dataset catalog 中。
- checksum 是否存在。
- provider/runtime 是否已选择。
- concurrency 是否为正整数。

#### Task Detail

目标：任务运行和恢复，不做 Harbor 原始对象浏览器。

主结构：

```text
status header
execution chain: Queued -> Input ready -> Runtime -> Artifacts -> Samples -> Published
action queue: Sync / Cancel / Retry run / Retry artifacts / Ingest / Publish
trial review queue
artifacts
samples publish readiness
raw Harbor job / diagnostics
```

关键规则：

- 所有动作展示 available/waiting/blocked reason。
- failed 状态优先展示恢复入口。
- succeeded 状态优先展示 ingest samples / publish。
- published 状态优先展示 result dataset 链接。
- diagnostics 只解释问题，不抢主流程。

#### Trial / Trajectory Review

目标：核心审核页，判断 trial 是否可进入后训练数据集。

页面结构：

```text
trial metrics: state / reward / verifier / exception
trajectory provenance: trial-result / ATIF / OpenAI messages / raw artifacts
tabs: Summary | Timeline | OpenAI Messages | Raw JSON
```

设计冻结：

- 默认进入 Summary。
- `?view=summary|timeline|messages|raw` 表达当前 tab，result dataset 回跳要能打开目标视图。
- Summary 展示 quality gates、schema alignment、tool call mapping、content diff、message diff。
- Timeline 和 OpenAI Messages 支持 search/filter/anomaly-only。
- Raw JSON 放最后，只做兜底。
- trajectory 缺失时提供 artifact retry 或返回 task artifact 的恢复路径。

#### Results

目标：发布结果数据集审核、下载和 lineage 回溯。

列表页：

- Search/filter 进入 URL query。
- 字段聚焦 name、version、sample_count、source task、source dataset、created、download。

详情页：

```text
result metrics
samples review: quality summary / search / anomaly-only / pagination
field coverage and field profile
lineage: input dataset -> synthetic task -> Harbor run -> result dataset
trajectory audit links grouped by source trial
download: JSONL / JSON
```

关键规则：

- JSONL 是后训练消费优先格式，JSON 是带元数据完整导出。
- download panel 显示 contract gate：sample rows、metadata、source trials、source artifacts。
- 每个 source trial 都要能回跳到 trial trajectory review。

#### Settings

目标：本地 E2E 和运行配置只读检查。

必须隐藏 database password、COS secret_id、secret_key、session_token 明文。可以展示：

- Harbor API base URL。
- dataset storage backend。
- COS bucket、region、prefix、endpoint。
- secret configured flags。
- E2E readiness gates 和可复制命令。

### 组件模型

优先复用这些组件，不先抽象复杂设计系统包：

- `PageHeader`：页面目标、上下文、主动作。
- `PanelHeader`：单个 panel 的标题、摘要、局部动作。
- `DataTable`：桌面表格，移动端容器内滚动或记录卡片。
- `StatusBadge`：状态文字必须独立表达含义，颜色只是辅助。
- `ReadinessGate`：ready/warning/blocked 三态，带原因和下一步动作。
- `ActionQueue`：按优先级展示可执行动作和 blocked reason。
- `LineageFlow`：dataset/task/trial/artifact/result 的可点击来源链。
- `TrajectoryTabs`：tab state 进入 URL query，支持键盘左右切换和焦点可见。
- `DiffTable`：schema alignment、tool call mapping、message/content diff 的统一表格模型。
- `JsonBlock`：Raw JSON 兜底查看，默认折叠或放到页面末尾。

### 前端开发切片

进入开发时按以下顺序推进：

1. **FE-A：Trial deep link 和 result 回跳**
   - `TrialPage` 支持 `?view=summary|timeline|messages|raw`。
   - Task/result/artifact 的 trajectory 链接带目标 view。
   - Playwright 覆盖直接打开 URL、点击 tab、键盘切换、result 回跳。

2. **FE-B：Task Builder readiness**
   - 状态：已完成 dataset 选择写回 `datasetId` query、builder readiness gates 和 Playwright 覆盖。
   - dataset/task_name/runtime/concurrency 的提交前检查更清楚。
   - payload preview 和错误 summary 聚合。
   - 从 dataset 详情进入 task builder 的预填状态进入 URL。

3. **FE-C：Task Detail 恢复体验**
   - 状态：已完成 operation feedback panel，集中展示 pending / success / error 和恢复建议，并补充 Playwright 覆盖。
   - action queue 的 available/waiting/blocked reason 收敛。
   - failed/succeeded/published 三种状态首屏主动作稳定。
   - artifact retry、ingest、publish 的成功/失败反馈使用 live region。

4. **FE-D：Result Dataset 审核效率**
   - 状态：基础版已完成，已增加 result review checklist、sample review 深链、多维质量规则矩阵和 `sample_min_reward` reward 阈值配置；首屏聚合 samples、异常、reward、lineage 和 export contract 的交付判断。
   - trajectory audit links 以 source trial 聚合。
   - samples review 的抽样策略、更完整规则配置、字段 profile 和分页继续打磨。
   - 下载失败或空数据集显示恢复路径。

5. **FE-E：Workbench 和 Settings 验收**
   - 状态：基础版已完成，本轮新增 Settings local E2E execution plan，把上传、TKE 任务、轨迹审核、发布下载串成可扫描步骤。
   - Workbench 首屏 next actions 和 failure causes 作为运营入口。
   - Settings 作为本地 E2E 检查入口，确认 secret 不泄露。
   - 补齐 375/768/1024/1440px Playwright 截图或 smoke。

每个切片完成后都跑：

```bash
cd synthetic-data-platform/web
npm run build
npm run test:ui
npm run verify
```

## 前端目标态设计基线

本平台前端按“后训练 agent 轨迹数据合成控制台”设计，不按 Harbor
运维后台、数据标注工具或普通 BI 报表工具设计。核心判断标准是：

- 用户能否在 1 个入口判断平台当前是否可跑数。
- 用户能否从 dataset 一路走到 task、trial、trajectory、sample、result dataset。
- 用户能否在失败时快速知道问题更像 dataset、runtime、artifact storage 还是 sample publish。
- 用户能否从发布后的 result dataset 回溯到 input dataset、Harbor job、trial 和 trajectory artifact。

前端页面不直接暴露 Harbor 内部概念作为主导航。`harbor_job_id`、lease、
runner、artifact key、COS key 等只在详情页或诊断区出现；主流程语言使用
synthetic task、dataset、trial、trajectory、sample、result dataset。

### 角色和主要任务

平台第一阶段面向四类使用者：

- 数据/算法研发：上传或登记输入 dataset，创建合成任务，选择 `tke` 等 runtime。
- 轨迹质检人员：查看 trial、trajectory、OpenAI messages schema 和异常标记。
- 平台研发：检查 Harbor job、runner、artifact、COS 上传和失败恢复动作。
- 数据消费方：查看发布后的 result dataset，下载 JSONL/JSON，并确认 lineage。

### 前端工作流

标准闭环：

```text
Datasets
  -> New task
  -> Task detail
  -> Trial / trajectory review
  -> Ingest samples
  -> Publish result dataset
  -> Result dataset review/download
```

恢复闭环：

```text
Workbench
  -> Failed task queue
  -> Task diagnostics
  -> Retry run / retry artifacts / cancel
  -> Re-ingest samples
  -> Publish result dataset
```

回溯闭环：

```text
Result dataset
  -> Source task
  -> Source trial
  -> Trajectory artifact
  -> Input dataset
```

### MVP 页面能力边界

MVP 必须覆盖：

- dataset 上传/登记、列表、详情、task_name 可用性、source URI 和 checksum。
- task 创建、runtime/provider 选择、任务列表、任务详情、运行控制和恢复动作。
- trial 详情、ATIF trajectory、OpenAI messages trajectory、schema alignment 和 anomaly-only 过滤。
- sample ingest、publish、result dataset 列表、详情、lineage、download。
- Workbench 的 readiness、失败任务、active run、latest result 和 provider load。
- Settings 的只读安全配置摘要，隐藏数据库密码和 COS 密钥明文。

MVP 暂不覆盖：

- 多租户、登录鉴权、角色权限。
- prompt/template 管理。
- 成本账单、token 报表和 provider 成本拆分。
- 数据集版本 diff、在线标注、人工审核队列流转。
- 大规模 result dataset 服务端分页和抽样策略。

这些能力需要后端 contract 和权限模型稳定后再设计，不放入当前前端首版。

### 组件设计约束

全局组件按“可扫描、可恢复、可深链”来设计：

- `PageHeader`：只放页面目的、当前上下文和主动作，不放营销描述。
- `PanelHeader`：每个 panel 只表达一个任务，例如 readiness、failure causes、samples review。
- `DataTable`：桌面端表格优先；移动端转记录卡片或表格容器局部横向滚动。
- `StatusBadge`：颜色只是辅助，状态文字必须可独立理解。
- `RunStageStepper`：用于 task detail 的执行链路，不用于普通数据展示。
- `EmptyState`：必须给出下一步动作，不能只有“暂无数据”。
- `ErrorState`：展示错误和恢复入口；任务失败类错误需要跳转到诊断或 retry。
- `MutationStatus`：异步动作使用 live region 告知结果，不打断当前焦点。

React 实现规则：

- 列表项使用稳定业务 ID 作为 key，不使用数组 index。
- 只在有真实渲染成本的纯组件上使用 `React.memo`，不全局盲目 memo。
- 搜索、筛选、分页状态进入 URL query，保证 deep link 可复现。
- TanStack Query 的 query key 必须包含筛选条件和分页条件。
- 危险动作使用确认流程；提交期间按钮 disabled，并显示 waiting/blocked reason。

## 用户与场景

目标用户是平台研发、算法/数据工程、数据标注与质检人员。

主要使用场景：

- 本地或云上发起一批 agent 轨迹合成任务。
- 对失败任务做 cancel/retry/artifact retry。
- 检查每个 trial 的 reward、异常、ATIF trajectory、OpenAI messages trajectory。
- 从 artifacts 中导入业务 samples。
- 发布 result dataset 并下载 JSONL/JSON。
- 追踪某个 result dataset 来自哪个 input dataset、synthetic task、trial 和 artifact。

## 信息架构

顶层导航保留 5 个一级入口：

```text
Workbench
Datasets
Tasks
Results
Settings
```

全局布局：

```text
┌────────────────────────────────────────────────────────────┐
│ Skip link                                                  │
├──────────────┬─────────────────────────────────────────────┤
│ Sidebar      │ Top context bar / page title / primary CTA  │
│              ├─────────────────────────────────────────────┤
│ Workbench    │ Page content                                │
│ Datasets     │ - status strip / filters                    │
│ Tasks        │ - primary table or detail console           │
│ Results      │ - secondary panels                          │
│ Settings     │ - raw/debug section last                    │
└──────────────┴─────────────────────────────────────────────┘
```

响应式规则：

- 桌面端使用 sidebar + 内容区，详情页可使用双列，但主审核区域必须占主要宽度。
- 平板端保留导航和表格扫描能力，详情页的辅助面板下沉或缩窄。
- 手机端导航改为可收起或顶部入口，表格转为记录卡片；只允许表格容器内部横向滚动。
- ID、COS URI、artifact path、checksum 等长文本使用 `overflow-wrap:anywhere`，避免单字断裂。

页面层级：

```text
/workbench
  平台健康、最近任务、失败任务、快捷入口

/datasets
  dataset 列表、筛选、上传/登记入口
/datasets/new
  上传本地 archive 或登记已有 COS URI
/datasets/:dataset_id
  dataset 元数据、task_names、checksum、source、可创建任务入口

/tasks
  synthetic task 列表、筛选、状态扫描
/tasks/new
  task builder：dataset、task_name、runtime、agent、模型、并发
/tasks/:task_id
  单次任务控制台：状态链路、run controls、trials、artifacts、samples、publish
/tasks/:task_id/trials/:trial_id
  核心轨迹审核页：trial result、trajectory provenance、summary、timeline、OpenAI messages、raw JSON

/results
  published result dataset 列表
/results/:result_dataset_id
  result dataset 详情、samples preview、lineage、下载

/settings
  只读运行配置，隐藏数据库/COS secrets
```

## 页面设计

### Workbench

定位：平台入口和运行态摘要，不承载复杂操作。

布局：

- 顶部 readiness strip：Synthetic API、Harbor API、dataset storage、dataset count。
- Metrics：datasets、task_names、active runs、result datasets。
- Next actions：按 setup blocker、failed runs、active runs、publish candidates、latest result、create task 生成首屏动作队列。
- Quick start：创建任务、上传/登记 dataset、打开本地 E2E、查看 results。
- Needs attention：失败任务和恢复入口。
- Recent runs：最近 synthetic tasks 表格。
- Latest results / Catalog health：结果数据集和目录健康摘要。

设计约束：

- 不使用大 hero，不做营销文案。
- readiness 和 metrics 用紧凑信息块，避免过多装饰卡片。
- 最近任务优先显示 task name、state、dataset、runtime、updated、action。
- 失败任务和阻塞状态优先于普通统计露出，确保用户能判断下一步操作。

### Datasets

定位：输入数据目录。

列表页：

- 支持按名称/版本/source/task_name 筛选。
- 表格字段：name、version、source、format、task_names、size、created、action。
- 空状态直接给 “Upload/Register dataset” 动作。

新建页：

- 两种 source 通过 segmented control 表达：Upload archive / Register COS URI。
- 上传模式字段：file、name、version、format、task_names。
- 登记模式字段：COS URI、checksum、size、task_names。
- 右侧或底部 preview 显示即将提交的 dataset contract。

详情页：

- 展示 dataset source、COS/local URI、checksum、size、task_names。
- 明确 readiness：是否具备 task_name、是否有 checksum、是否可创建任务。
- 展示使用过该 dataset 的最近 synthetic tasks，并可跳转到完整任务列表。
- 展示由该 dataset 发布出来的 result datasets，并可跳转到完整结果列表。
- 主动作是 “Create task from dataset”。
- 后续 dataset 管理能力增强后，补充版本差异和可复用的 task_name 映射。

### Tasks

定位：任务运行与恢复入口。

列表页：

- 支持 search、state、runtime、dataset 维度筛选。
- 表格字段：name、state、harbor state、dataset、runtime、updated、action。
- 状态要同时呈现 synthetic task state 和 Harbor job state，避免用户混淆。

新建页：

- 使用 builder 布局：左侧表单，右侧 sticky payload preview 和 readiness checks。
- 必填：dataset、task_name、runtime、agent。
- 可选：model、concurrency。
- runtime 用 radio card：docker、ags、tke。每个选项显示实际 `environment.type`。
- 提交前展示 JobConfig 摘要和 dataset readiness checks：dataset source、runner download、checksum、task catalog、selected task coverage，减少“发错 runtime / 发错 dataset / 发错 task_name”的风险。

详情页：

- 顶部动作：Back、Sync、Cancel、Retry run、Retry artifacts。
- Execution chain 是主视觉：Queued -> Input ready -> Runtime -> Artifacts -> Samples -> Published。
- Run controls 显示每个动作的 available/waiting/blocked 状态。
- Trials 和 Artifacts 是任务排查入口。
- Samples 区域承接 `ingest-samples` 和 `publish`。
- Raw Harbor job 放在页面底部，作为调试补充，不参与主要阅读路径。

关键状态：

- queued/running：展示当前阶段和下一次 refresh 结果。
- succeeded：主动作转为 ingest samples / publish result dataset。
- failed：顶部露出异常摘要，恢复动作优先展示 retry run / retry artifacts。
- cancelling/cancelled：展示取消来源和取消时间，避免用户误以为任务失败。

### Trial / Trajectory

定位：平台最核心的轨迹审核页。

页面结构：

- 顶部 metric：state、reward、trial_name、exception。
- Trajectory provenance：列出 trial-result、ATIF trajectory、OpenAI messages trajectory 等 artifact 记录。
- Trajectory tabs：
  - Summary：trial-result 摘要。
  - Timeline：ATIF steps/messages/tool calls/observations 的人类可读时间线。
  - OpenAI Messages：OpenAI message schema，用于后训练数据消费检查。
  - Raw JSON：原始 trajectory。

设计约束：

- trajectory tab 是页面核心内容，不能被 Raw JSON 淹没。
- 如果 trajectory artifact 缺失，要显示清晰恢复路径：检查 artifacts 或 retry artifact collection。
- provenance 表要保留可读最小宽度，路径和 COS key 可以横向滚动，不应在窄列中被拆成单字。

审核体验：

- Timeline 默认按 step 顺序展示，并保留 message、tool call、observation 的视觉区分。
- OpenAI Messages tab 用后训练消费视角展示 role/content/tool_calls/tool_call_id。
- Summary tab 展示 ATIF/default 与 OpenAI messages 的 schema alignment：覆盖、行数、tool call、observation/tool response 和异常数。
- Summary tab 展示 trial quality gates：reward、verifier、exception 和轨迹 schema readiness，前置判断 trial 是否适合进入后训练数据集审核；verifier 支持 status、reason、score、threshold、label 等结构化信号，并支持 `verifier_min_score` URL 规则配置。
- Summary tab 提供 tool call id 级别的跨 schema 明细映射和基础 diff，方便定位 ATIF call/observation 与 OpenAI call/response 是否对应、name/arguments/response 是否一致。
- Summary tab 提供 content diff table，按 tool call id 对比 function name、arguments、response 三类可消费信号，并展示两种 schema 的原始可读值。
- Summary tab 提供 message diff table，按 role 和 turn 对比 ATIF/default 与 OpenAI messages 的 system/developer/user/assistant 自然语言消息内容，并展示缺失/不同/匹配的 Text delta 与两侧完整文本。
- Summary tab 提供 step text diff table，逐条检查 ATIF/default timeline step 文本是否进入 OpenAI messages，并把缺失 step text 纳入 Summary decision、handoff 和 audit checklist。
- Summary tab 汇总 Timeline anomalies、OpenAI message anomalies 和 schema mapping gaps，并提供直达对应审核 tab 的快捷入口。
- Timeline / OpenAI Messages 提供异常摘要、anomaly-only 过滤和行级异常标签。
- OpenAI Messages 审核补充线程级 tool call 规则：重复 tool call id、缺 tool response、orphan tool response、重复 tool response 都应作为后训练消费质量信号。
- Raw JSON 只作为兜底，不作为默认阅读方式。
- 后续增强支持更细粒度 verifier 专项规则配置和更完整的文本对齐策略；`verifier_min_score` 和 Step text diff 基础规则已具备。

### Results

定位：发布后的业务结果数据集目录。

列表页：

- 字段：name、version、sample_count、source_task、source_dataset、created、download/action。
- 支持按 name/version/source task/source dataset 搜索和筛选。

详情页：

- 顶部 metric：sample_count、source task、source dataset、created。
- Samples preview 用表格，避免直接堆 JSON。
- Lineage 展示 input dataset -> synthetic task -> trials/artifacts -> result dataset。
- Trajectory audit links 按 source trial 聚合 trial-result、trajectory、OpenAI messages 和 sample source artifact 状态，并直达源 trial 轨迹审核页。
- Download panel 明确两种格式：
  - JSONL：后训练样本消费优先格式。
  - JSON：包含元数据和 samples 的完整导出。
- Export contract gate 明确 JSONL 样本行、完整 JSON 元数据、source trials 和 source artifacts 是否满足交付审计。
- Samples review 提供质量摘要、服务端 search/pagination、URL 深链恢复、
  `sample_min_reward` reward 阈值、异常样本过滤、行级异常标签和分页。

结果审核重点：

- 用户必须能从 result dataset 回溯到 input dataset、synthetic task、Harbor job、trial、trajectory artifact。
- samples review 需要显示字段覆盖情况，例如当前可见行里每个字段有多少行具备值。
- samples review 需要能定位缺内容、缺 reward、低 reward、空字符串字段、稀疏行等基础异常。
- 下载入口要解释格式差异，但不能用大段说明挤占样本预览区域。

### Settings

定位：只读运行配置。

必须隐藏：

- database password
- COS secret_id / secret_key / session_token 明文

可以显示：

- API base path
- Harbor API base URL
- dataset storage backend
- COS bucket/region/prefix/endpoint
- secret 是否 configured
- 安全和本地 E2E readiness gates：secret display、Harbor API、Database、Dataset COS、COS credential flags、E2E commands
- 本地验证命令

## 视觉系统

基调：

- 工作台型 SaaS / 数据运营后台。
- 高密度但不拥挤。
- 不使用 landing hero、大幅插画、渐变背景、装饰光斑。

色彩：

- background: `#f8fafc`
- surface: `#ffffff`
- sidebar: `#0f172a`
- primary: `#1e40af`
- accent/warning: `#d97706`
- success: `#15803d`
- danger: `#dc2626`
- border: `#dbeafe`

字体：

- 当前实现使用系统 sans；代码/ID/JSON 使用 Fira Code fallback。
- 后续如果引入 Web font，优先考虑 `Fira Sans + Fira Code`，并使用 `font-display: swap`。

间距与形状：

- 使用 4/8px spacing rhythm。
- 面板和控件 radius 最大 8px。
- 页面区块使用全宽布局或无框布局；卡片只用于重复项、面板、modal、状态块。

组件规范：

- 表格：桌面优先，列头固定语义；路径/URI 列用 mono 字体和局部横向滚动。
- 状态徽标：颜色只作为辅助，文字必须表达状态。
- 操作按钮：危险动作使用确认弹窗；异步动作显示 loading/disabled reason。
- Tabs：用于 trajectory schema / raw view 切换，不用于隐藏关键操作。
- Empty state：必须提供下一步动作，例如上传 dataset、创建 task、同步状态。
- Error state：展示用户可执行恢复动作，不只展示异常字符串。

图标：

- 使用 `lucide-react`。
- 图标旁有可见文字时，图标 `aria-hidden="true"`。
- 不使用 emoji 作为结构图标。

## 交互与可访问性

必须满足：

- 顶层导航有图标和文字，当前页高亮。
- route change 后焦点进入 main content。
- 提供 skip link。
- 所有表单字段有 visible label。
- 表单错误同时有顶部 summary 和字段内错误。
- destructive action 使用确认弹窗，例如 cancel。
- async action 禁用按钮并显示明确状态，例如 Syncing、Ingesting、Publishing。
- `role="status"` / live region 用于异步结果反馈，不抢焦点。
- 所有关键页面可通过 URL deep link 访问。
- 移动端不能出现页面级横向滚动；数据表在移动端转卡片，在桌面窄面板里允许表格容器横向滚动。
- 支持 `prefers-reduced-motion`，动画只用于状态反馈，不作为功能依赖。

## 当前实现覆盖

已具备：

- React 19 + Vite + React Router + TanStack Query。
- 顶层 app shell、sidebar、skip link、route focus management。
- 移动端 app shell 使用 sticky 顶部应用栏和容器内横向 primary navigation rail，避免页面级横向滚动。
- Workbench、Datasets、Tasks、Results、Settings 页面。
- Dataset 上传/登记、列表筛选、详情、task_name 过滤、version family、使用记录、result datasets 回溯、基于 dataset 创建任务。
- Task 创建、提交前 dataset readiness / task builder readiness 检查、`datasetId` query 同步、payload preview、列表、已发布结果直达、详情、sync/cancel/retry/artifact retry。
- Samples ingest 和 publish。
- Task detail status overview：根据 running / succeeded / failed / published 状态给出当前 checkpoint 和下一步动作；published 状态可直接打开 result dataset。
- Task detail action queue：根据 runtime、artifact、sample、publish 状态给出优先级恢复/发布动作，并复用安全确认流程。
- Task detail operation feedback：集中展示 sync/cancel/retry/artifact retry/ingest/publish 的 pending、success、error 和下一步恢复建议。
- Task detail sample publish readiness：展示 source artifacts、ingested samples、runtime gate、publish readiness。
- Task detail sample preview：ingested samples 通过服务端 search/pagination
  查询，分页/搜索状态进入 URL query；publish readiness 使用未过滤 total，样本表使用当前搜索后的 total。
- Task operation disabled reason：cancel / retry / artifact retry / ingest / publish 的等待原因可见。
- Task detail diagnostics：聚合 trial state、trial exception、artifact kind/schema、缺失 trajectory、runtime duration、失败根因和 artifact retry wake-up 状态。
- Task detail trajectory review queue：按异常、缺 trajectory、缺 OpenAI messages、ready 状态排序 trial，展示 Needs review / OpenAI messages / Ready 摘要，并提供首个问题和单 trial 轨迹审核入口。
- Workbench operations status：根据 readiness、failed runs、active runs、result datasets 给出下一步主动作。
- Workbench operational priorities：失败任务、活跃运行、输入 dataset、结果 sample 的可点击优先级入口。
- Workbench next actions：按阻塞、失败、活跃、待发布、结果导出交付状态和创建任务生成首屏动作队列。
- Workbench failure cause summary：失败任务按 input materialization、artifact persistence、trial/runtime 等最强信号聚合。
- Workbench generation usage metrics：通过 `/workbench/summary` 的
  `generation_metrics` 展示 total/completed/failed task、sample yield、observed
  runtime、runtime/model/provider bucket、reported token usage 和 configured
  cost estimate。
- Settings security and E2E readiness：只显示 secret configured flags，检查 Harbor API、Database、Dataset COS、COS credential flags 和 copyable E2E commands。
- Settings result export worker readiness：显示 COS export worker 是否启用、是否具备
  durable queue，以及 stale running export recovery 窗口，不暴露数据库或 COS secret。
- Tasks/Results 列表 active filter summary：URL query 中的筛选条件可见、可单项移除、可一键清空。
- Tasks/Results 列表搜索使用 deferred query value，减少快速输入时的列表请求抖动。
- Trial 详情、trajectory provenance、summary/timeline/OpenAI messages/raw JSON tabs，且
  tab 支持 `?view=summary|timeline|messages|raw` deep link。
- Timeline 基础结构化审核视图：source、message、tool_calls、observation。
- OpenAI messages 基础结构化审核视图：role、content、tool_calls、tool_call_id。
- Trajectory 审核过滤：Timeline 支持 source/search 过滤，OpenAI Messages 支持 role/search 过滤。
- Trajectory schema alignment：Summary tab 对齐 ATIF/default 与 OpenAI messages 的覆盖、行数、tool call、observation/tool response 和异常数。
- Trajectory schema mapping：Summary tab 按 tool call id 映射 ATIF call/observation 与 OpenAI call/response，并标记 aligned / partial / unlinked 与基础 diff。
- Trajectory content diff：Summary tab 按 tool call id 对比 function name、arguments、response，并保留 ATIF/default 与 OpenAI messages 两侧的可读内容。
- Trajectory message diff：Summary tab 按 role/turn 对比 system/developer/user/assistant 文本内容，标记 match/mismatch/missing，并展示 Text delta、缺失方向、差异起点和两侧完整文本。
- Trajectory step text diff：Summary tab 按 ATIF/default timeline step 检查文本是否出现在 OpenAI messages 中，展示 match/missing、Text delta 和 OpenAI match。
- Trial quality gates：Summary tab 前置展示 reward、verifier、exception 和 ATIF/OpenAI schema readiness；verifier 支持 status、reason、score、threshold、label 结构化摘要和 `verifier_min_score` URL 阈值配置，帮助判断 trial 是否可进入样本发布审核。
- Trial Summary review issues：汇总 Timeline anomalies、OpenAI message anomalies 和 schema mapping gaps，并提供 tab 快捷跳转。
- Trajectory anomaly review：Timeline / OpenAI Messages 支持异常摘要、anomaly-only 过滤和行级异常标签。
- OpenAI message thread review：检测重复 tool call id、缺 tool response、orphan tool response、重复 tool response，并进入 anomaly-only 过滤。
- Global trial review guidance：`/reviews/trials` 队列按 saved/current/suggested 区分人工结论和系统建议，基于 quality flags、trajectory/OpenAI messages、artifact 和 reward 信号给出可扫描的 quick decision guidance。
- Trajectory 明细折叠：tool call / observation 可折叠并保留隐藏数量提示。
- Result dataset 列表、source task/source dataset 筛选和回跳、详情、source dataset 直达、JSONL/JSON 下载。
- Result dataset lineage flow：input dataset -> synthetic task -> Harbor run -> result dataset。
- Result dataset export contract gates：检查 JSONL rows、Full JSON metadata、source trials 和 source artifacts 是否可交付。
- Samples review coverage：样本数、可见行数、字段数、可见字段覆盖行数。
- Result dataset sample review：质量摘要、服务端 search/pagination、URL 深链恢复、多维质量规则矩阵、`sample_min_reward` reward 阈值、异常样本过滤和行级异常标签。
- Result dataset source review：source trials 支持 state 筛选，source artifacts 支持 kind/search 筛选。
- Result dataset trajectory audit links：按 source trial 汇总 trial-result、trajectory、OpenAI messages、sample source artifact 状态，并提供带目标 view/hash 的源 trajectory 审核回跳，覆盖 Summary decision、Timeline、OpenAI Messages 和 schema diff 区域。
- Result dataset field profile：按字段展示覆盖率、缺失数、类型和样例值；Result
  Detail 已接入 `GET /result-datasets/{id}/samples/field-profile`，按服务端
  search/quality 过滤后的样本集汇总，而不是只统计当前分页。
- Result dataset export history：COS 后台导出完成后走 record-level download；pending/running
  记录显示等待状态，failed 记录提供 `Retry export` 重新排队入口。
- Playwright 响应式 smoke 覆盖多个 viewport。
- Playwright 前端质量门覆盖导航焦点、长列表、长文本、loading、error、empty state 和页面级横向溢出检查。

需要继续优化：

- Trial 页面后续可继续增加更细粒度 verifier 专项规则配置和更完整的文本对齐策略；`verifier_min_score` 和 Step text diff 基础规则已具备。
- Result dataset 页面后续可继续增强抽样策略和更完整可配置质量规则；trajectory diff 回跳已具备基础深链能力。
- Workbench 已有配置化金额估算；后续可继续增加预算阈值、趋势和账单对账视图。
- Task detail 后续可继续增加 cost breakdown；该项需要 trial/task 粒度成本归因和
  价格版本快照。

## 下一轮前端开发排期

这轮前端开发按“先把平台操作闭环做顺，再做视觉精修”的顺序推进。每个切片
控制在 0.5-1.5 天；第一轮以 5 个工作日为一个可验收窗口。如果后端接口或
测试数据不稳定，优先保留页面骨架和 mock-driven smoke，避免阻塞整体交互设计。

### FE0：设计冻结和现状校准

周期：0.5 天。

目标：

- 固化本设计文档作为前端开发基线。
- 对照当前页面确认已实现、需增强、依赖后端的能力。
- 确认本地开发命令、API base path、Playwright smoke 和 mock fixture。

验收：

- 设计文档说明页面、组件、工作流、MVP 边界和排期。
- 当前实现差距能映射到后续 FE1-FE6，不出现“边开发边改产品方向”。

### FE1：App Shell 和设计系统收敛

周期：0.5-1 天。

目标：

- 收敛 sidebar、topbar、skip link、route focus、按钮、状态徽标、表格、empty/error/loading。
- 统一颜色 token、spacing、radius、focus ring、移动端断点和长文本换行规则。
- 检查所有 icon 使用 `lucide-react`，图标按钮具备可访问名称。

验收：

- `/workbench`、`/datasets`、`/tasks`、`/results`、`/settings` 在 375/768/1024/1440px 可读。
- 键盘能进入主内容、导航、表单和主要动作。
- 页面级不出现横向滚动；只有表格容器可局部滚动。

### FE2：Dataset 管理闭环

周期：1 天。状态：基础版已完成，已增加同名 dataset version family 对比和指定版本创建任务入口。

目标：

- 完成 dataset 列表筛选、上传/登记、详情、readiness 和 task_name 展示。
- 从 dataset 详情直达创建任务，并把 dataset/task_name 预填到 task builder。
- 展示该 dataset 关联的 synthetic tasks 和 result datasets。
- 展示同名 dataset 的版本族，能比较当前版本和 sibling versions 的 source、task_count、checksum，并选择指定版本创建任务。

验收：

- 用户能上传或登记一个 COS/local dataset，并从详情页发起任务。
- dataset 缺 task_name、checksum、size 时有清晰提示，不阻塞可选能力。
- dataset -> task -> result dataset 的回跳路径可用。

### FE3：Task 创建、运行和恢复

周期：1.5 天。

目标：

- Task builder 支持 dataset、task_name、runtime、agent、model、concurrency。
- Task detail 展示 execution chain、Harbor state、input/materialization、artifact/sample/publish 状态。
- cancel、retry run、retry artifacts、ingest samples、publish result dataset 的 available/waiting/blocked reason 可见。
- Task detail 的 trajectory review queue 汇总待审核 trial、OpenAI messages 覆盖和 ready 数量，失败任务能优先打开首个问题 trial。

验收：

- 用户能从前端创建 `tke` runtime 任务。
- running/succeeded/failed/cancelled/published 状态都有明确下一步动作。
- 失败任务可以从 Workbench 和 task list 进入恢复流程。

### FE4：Trial 和 Trajectory 审核

周期：1.5 天。

目标：

- Trial 页以 trajectory 审核为中心，不让 raw JSON 成为默认视图。
- 支持 Summary、Timeline、OpenAI Messages、Raw JSON tabs。
- Summary 展示 ATIF/default 与 OpenAI messages 的覆盖、tool call/response 映射和基础 diff。
- Timeline 和 OpenAI Messages 支持 source/role/search/anomaly-only 过滤。

验收：

- 用户能判断一个 trial 是否产出了 ATIF trajectory 和 OpenAI messages trajectory。
- tool call 与 observation/tool response 的映射状态可见。
- trajectory 缺失、schema 异常、内容缺失时有明确异常标签和恢复入口。

### FE5：Result Dataset 审核和下载

周期：1 天。

目标：

- Result 列表支持 name/version/source task/source dataset 查询。
- Result 详情展示 sample_count、samples preview、field coverage、field profile、lineage 和下载入口。
- JSONL/JSON 下载路径、格式差异和错误提示清晰。

验收：

- 用户能从 result dataset 回溯到 source dataset、source task、source trials 和 source artifacts。
- 用户能在前端定位缺 content、缺 reward、低 reward、空字符串和稀疏样本。
- JSONL/JSON 下载入口可用。

### FE6：Workbench 和 Settings 收敛

周期：0.5-1 天。

目标：

- Workbench 首屏回答三个问题：现在能不能跑、哪里失败了、下一步做什么。
- 展示 readiness、next actions、failed runs、failure causes、active runs、runtime/provider load、latest results。
- Settings 只读展示安全配置摘要、E2E readiness gates 和本地 E2E 命令，不暴露 secret 明文。

验收：

- 首屏能定位平台阻塞点和恢复入口。
- 失败任务、运行中任务、最新结果都有直达链接。
- Settings readiness summary 能判断 secret display、Harbor API、Database、Dataset COS、COS credentials、E2E commands 是否 ready。
- 本地 E2E 上传 COS、TKE runtime、结果下载的验证命令可复制。

### FE7：前端验收和回归

周期：0.5 天。

状态：滚动执行中。本轮已把 loading、error、empty state 纳入 Playwright
质量门，并继续保留导航焦点、长列表、响应式 viewport 和页面级横向溢出检查。

目标：

- 补齐核心路径 Playwright smoke。
- 检查无障碍、响应式、长文本、空状态、错误状态、loading 状态。
- 截图检查 Workbench、Task Detail、Trial、Result Detail 的桌面和移动端布局。

验收命令：

```bash
cd synthetic-data-platform/web
npm run build
npm run test:ui
npm run verify
```

前端进入开发时，优先顺序是 FE1 -> FE3 -> FE4 -> FE5 -> FE6。FE2
当前已经具备基础能力，并已补充 dataset version family 管理体验；FE7 每个阶段
都要滚动执行，不只在最后做。

## 历史开发排期和当前状态

前端开发按“可用闭环优先”推进，不先做完整设计系统抽象：

1. 先把核心任务闭环跑通：dataset -> task -> trial/trajectory -> samples -> result dataset。
2. 再增强审核效率：trajectory timeline、OpenAI messages、result lineage、sample coverage。
3. 最后收敛运营首页和配置页，避免 Workbench 先变成静态指标墙。

### F1：前端设计基线与表格可读性

状态：基础版已完成，已增加 source review 筛选、字段 profile 和移动端顶部导航 rail。

目标：

- 固化本设计文档。
- 修复 compact 表格在详情双列布局中的断词问题。
- 保持现有 Playwright viewport smoke 通过。

验收：

- `npm run build`
- `npm run test:ui`
- 桌面 task detail 的 artifacts 表路径不再一字一行。

### F2：Task Detail 审核运营体验

状态：基础版已完成，已增加 action queue、failure recovery、运行诊断汇总、artifact retry wake-up 状态、操作 disabled reason，以及 Task samples 服务端分页/搜索预览。

目标：

- 优化 execution chain 和 run controls 的信息层级。
- 将 samples 区域改为“导入状态 + preview + publish readiness”。
- 强化失败任务恢复路径。

验收：

- succeeded / failed / running 三类 mock 或 fixture 截图可读。
- cancel/retry/artifact retry 的 disabled reason 清晰。

### F3：Trajectory Review

状态：基础版已完成，已增加 Task detail trajectory review queue、全局
`/reviews/trials` 审核队列页、队列快速审核决策、队列摘要、首个问题入口、过滤、分页、折叠、
基础异常定位、schema alignment、tool call id 映射、基础 diff、完整 message
text delta、结构化 verifier quality gate、Summary review issues 和 Trial view
deep link 能力，后续继续增强审核效率。
本轮继续增强 Summary content diff，按 tool call id 展示 function name、arguments、response 的 match/mismatch/missing 状态和两侧可读值。
本轮继续增强 OpenAI Messages 线程级 tool call 审核，覆盖重复 id、缺 response、orphan response 和重复 response。
本轮继续增强 Summary message diff，按 role/turn 对比 system/developer/user/assistant 自然语言消息内容。
本轮继续增强 Trial quality gates，按 reward、verifier、exception 和轨迹 schema readiness 前置展示 trial 进入后训练数据集审核的质量门，并增加 `verifier_min_score` URL 阈值配置。
本轮继续增强 Summary step text diff，检查 ATIF/default timeline step 文本是否进入 OpenAI messages，并将 step text gap 纳入 Summary decision、post-training handoff 和 audit checklist。
本轮继续增强 Manual review suggestion，基于 trajectory review 和 post-training handoff 信号生成建议 decision、labels 和 rationale，审核员可一键填入但仍需显式保存。
本轮继续增强 Review queue guidance，在全局 `/reviews/trials` 表格中展示 saved/current/suggested decision，未审核 trial 可直接看到阻塞或通过建议，并把建议 labels/metadata 带入 quick decision。
本轮继续将 Review queue guidance 下沉到 Synthetic API contract，`decision_guidance` 由服务端返回，前端优先使用服务端判断并保留本地 fallback。
本轮继续让 Review queue guidance 可操作化，`/reviews/trials` 增加 guidance decision/source URL 筛选，并把同一筛选范围用于 summary 和批量审核决策。
本轮继续增强 Review queue summary，服务端返回 guidance decision/source 分布，前端摘要区展示 saved/current/suggested 与建议决策构成。
本轮继续把 Review queue summary 带到 Workbench 首屏，全局 trial review 面板展示 open 队列的 guidance decision/source rollup。
本轮继续把 Workbench next actions 接入 review guidance，按 blocked、needs review、rejected、approved guidance 生成可深链恢复的审核动作。
本轮继续把 Result export handoff 带到 Workbench next actions，首页读取最近结果数据集的 export history，优先提示失败、运行中、缺失 export 或缺失下载链接的结果交付风险。
本轮继续把 Result export readiness 带到 Results 列表，当前页结果数据集直接展示 Checking、Failed、Running、No export、No link、Ready 状态，并链接到下载区。
本轮继续把 Result export readiness 汇总下沉到 `/result-datasets/summary`，Results 摘要区展示当前筛选范围的 export-ready 指标、readiness buckets 和 status buckets。
本轮继续让 Results 支持 `export_readiness` URL 筛选，结果列表和 summary 使用同一筛选范围，便于直接进入 failed、running、missing export、missing link 或 download-ready 队列。

目标：

- Timeline 区分 user / assistant / tool call / observation。
- OpenAI Messages tab 显示 role、content、tool_calls、tool_call_id。
- provenance 表支持 schema 快速识别和下载。
- Summary tab 对齐 ATIF/default 与 OpenAI messages 的覆盖、行数、tool call、observation/tool response 和异常数。
- Summary tab 按 tool call id 展示 ATIF call/observation 与 OpenAI call/response 的映射状态和 name/arguments/response diff。
- Summary tab 按 ATIF/default timeline step 展示 step text 与 OpenAI messages 的 match/missing 状态和 Text delta。
- Summary tab 聚合 Timeline/OpenAI/schema mapping 审核问题，并能直达 Timeline 或 OpenAI Messages。
- 对缺 source、缺内容、错误信号、tool response 关联问题做基础异常定位。

验收：

- ATIF 和 OpenAI messages 两种 schema 都能从 trial 页稳定查看。
- trajectory 缺失时恢复路径明确。
- Summary tab 能判断两种 schema 是否齐全，以及 tool call / response 信号是否一致。
- Summary tab 能看到每个 tool call id 的 aligned / partial / unlinked 映射状态和 Match / mismatch diff 摘要。
- 能切换 anomaly-only 模式快速定位异常 timeline event / OpenAI message。

### F4：Result Dataset Review

状态：基础版已完成，已增加样本审核服务端分页/搜索、URL 深链恢复、多维质量规则矩阵、`sample_min_reward` reward 阈值配置、异常定位、字段 profile、
export contract gates、source trajectory audit links、source trial 精确 deep link 回跳、result review checklist、durable result export worker 交付模式、每条 export 的
worker claim 元数据可视化，以及 Results 列表/摘要层的 export readiness。

目标：

- 强化 samples review：分页、搜索、异常定位、字段覆盖和字段 profile。
- 结果数据集 lineage 明确展示 input dataset、task、trial、artifact。
- 从 result dataset 的质量问题能直接回跳到 source trial trajectory 审核页。
- 下载区解释 JSONL/JSON 两种 contract，并以 gate 形式提示样本、元数据、source trials、source artifacts 是否满足交付。

验收：

- 从 result dataset 能跳回 source task/trial/artifact。
- JSONL/JSON 下载入口可用，错误有恢复提示。
- Export contract 能判断 JSONL、Full JSON、source trials、source artifacts 是否 ready。
- Results 列表和 summary 能判断 result export 是否 ready、failed、running、missing export 或缺少下载链接。
- Results 支持按 export readiness 深链筛选，列表、summary 和 active filter summary 保持一致。
- 能在 result dataset 中直接定位缺 content、缺 reward、低 reward、空字符串、稀疏样本。

### F5：Workbench 收敛

状态：基础版已完成，已增加失败原因聚合、runtime/provider 运行摘要和首屏 next actions 队列。

目标：

- Workbench 从“卡片集合”收敛成运营首页。
- 最近任务、失败任务、最新结果变成主要扫描内容。
- 按阻塞、失败、活跃、待发布、结果导出交付状态和创建任务生成 next actions。
- readiness 只保留影响下一步操作的状态。

验收：

- 首屏能判断平台是否可运行、是否有失败任务、下一步应该做什么。
- Next actions 能直达 failed queue、active tasks、publish candidates、result export history、latest result 或 task creation。
- 移动端首屏优先展示状态和主动作。

### F6：Settings 收敛

状态：基础版已完成，已增加安全配置摘要、E2E readiness gates、local E2E execution plan、命令复制和 secret 明文隐藏验证。

目标：

- 只读展示运行配置，不暴露 database password、COS secret_id、secret_key、session_token 明文。
- 用 readiness gates 判断 Harbor API、Database、Dataset COS、COS credential flags 和 E2E commands 是否可用于本地验证。
- 本地 E2E 上传 COS、TKE runtime、结果下载的验证命令可复制。

验收：

- Settings readiness summary 能显示安全配置和本地 E2E 阻塞点。
- Safe config JSON 不包含 secret 明文。
- Frontend quality gate、COS/TKE preflight、Full COS/TKE E2E 命令可复制。
