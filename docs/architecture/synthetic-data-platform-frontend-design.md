# Synthetic Data Platform Frontend Design

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
- 主动作是 “Create task from dataset”。
- 后续 dataset 管理能力增强后，补充版本差异、使用过该 dataset 的任务列表、可复用的 task_name 映射。

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
- 提交前展示 JobConfig 摘要，减少“发错 runtime / 发错 dataset”的风险。

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
- Summary tab 提供 tool call id 级别的跨 schema 明细映射和基础 diff，方便定位 ATIF call/observation 与 OpenAI call/response 是否对应、name/arguments/response 是否一致。
- Timeline / OpenAI Messages 提供异常摘要、anomaly-only 过滤和行级异常标签。
- Raw JSON 只作为兜底，不作为默认阅读方式。
- 后续增强支持完整 step/message 文本 diff 和更深的 verifier 质量规则。

### Results

定位：发布后的业务结果数据集目录。

列表页：

- 字段：name、version、sample_count、source_task、created、download/action。
- 支持按 name/version/source task 搜索。

详情页：

- 顶部 metric：sample_count、source task、source dataset、created。
- Samples preview 用表格，避免直接堆 JSON。
- Lineage 展示 input dataset -> synthetic task -> trials/artifacts -> result dataset。
- Download panel 明确两种格式：
  - JSONL：后训练样本消费优先格式。
  - JSON：包含元数据和 samples 的完整导出。
- Samples review 提供质量摘要、本地 search、异常样本过滤、行级异常标签和分页。

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
- Workbench、Datasets、Tasks、Results、Settings 页面。
- Dataset 上传/登记、列表筛选、详情、task_name 过滤、基于 dataset 创建任务。
- Task 创建、列表、详情、sync/cancel/retry/artifact retry。
- Samples ingest 和 publish。
- Task detail status overview：根据 running / succeeded / failed / published 状态给出当前 checkpoint 和下一步动作。
- Task detail sample publish readiness：展示 source artifacts、ingested samples、runtime gate、publish readiness。
- Task operation disabled reason：cancel / retry / artifact retry / ingest / publish 的等待原因可见。
- Task detail diagnostics：聚合 trial state、trial exception、artifact kind/schema、缺失 trajectory、runtime duration、失败根因和 artifact retry wake-up 状态。
- Workbench operations status：根据 readiness、failed runs、active runs、result datasets 给出下一步主动作。
- Workbench operational priorities：失败任务、活跃运行、输入 dataset、结果 sample 的可点击优先级入口。
- Workbench failure cause summary：失败任务按 input materialization、artifact persistence、trial/runtime 等最强信号聚合。
- Workbench runtime/provider load：按 `environment.type` 聚合 total、active、failed、completed 任务数。
- Tasks/Results 列表 active filter summary：URL query 中的筛选条件可见、可单项移除、可一键清空。
- Tasks/Results 列表搜索使用 deferred query value，减少快速输入时的列表请求抖动。
- Trial 详情、trajectory provenance、summary/timeline/OpenAI messages/raw JSON tabs。
- Timeline 基础结构化审核视图：source、message、tool_calls、observation。
- OpenAI messages 基础结构化审核视图：role、content、tool_calls、tool_call_id。
- Trajectory 审核过滤：Timeline 支持 source/search 过滤，OpenAI Messages 支持 role/search 过滤。
- Trajectory schema alignment：Summary tab 对齐 ATIF/default 与 OpenAI messages 的覆盖、行数、tool call、observation/tool response 和异常数。
- Trajectory schema mapping：Summary tab 按 tool call id 映射 ATIF call/observation 与 OpenAI call/response，并标记 aligned / partial / unlinked 与基础 diff。
- Trajectory anomaly review：Timeline / OpenAI Messages 支持异常摘要、anomaly-only 过滤和行级异常标签。
- Trajectory 明细折叠：tool call / observation 可折叠并保留隐藏数量提示。
- Result dataset 列表、详情、JSONL/JSON 下载。
- Result dataset lineage flow：input dataset -> synthetic task -> Harbor run -> result dataset。
- Samples review coverage：样本数、可见行数、字段数、可见字段覆盖行数。
- Result dataset sample review：质量摘要、本地 search、异常样本过滤、行级异常标签和分页。
- Result dataset source review：source trials 支持 state 筛选，source artifacts 支持 kind/search 筛选。
- Result dataset field profile：按字段展示覆盖率、缺失数、类型和样例值。
- Playwright 响应式 smoke 覆盖多个 viewport。

需要继续优化：

- Trial 页面后续可继续增加完整 step/message 文本 diff 和更细的 verifier 质量规则。
- Result dataset 页面后续可继续增强服务端分页、抽样策略、多维质量规则和 trajectory diff 回跳。
- Workbench 后续可继续增加成本摘要；该项需要后端先补充 token/runtime/provider cost 字段。
- Task detail 后续可继续增加 cost breakdown；该项需要后端先补充 token/runtime/provider cost 字段。

## 开发排期

前端开发按“可用闭环优先”推进，不先做完整设计系统抽象：

1. 先把核心任务闭环跑通：dataset -> task -> trial/trajectory -> samples -> result dataset。
2. 再增强审核效率：trajectory timeline、OpenAI messages、result lineage、sample coverage。
3. 最后收敛运营首页和配置页，避免 Workbench 先变成静态指标墙。

### F1：前端设计基线与表格可读性

状态：基础版已完成，已增加 source review 筛选和字段 profile。

目标：

- 固化本设计文档。
- 修复 compact 表格在详情双列布局中的断词问题。
- 保持现有 Playwright viewport smoke 通过。

验收：

- `npm run build`
- `npm run test:ui`
- 桌面 task detail 的 artifacts 表路径不再一字一行。

### F2：Task Detail 审核运营体验

状态：基础版已完成，已增加 failure recovery、运行诊断汇总、artifact retry wake-up 状态和操作 disabled reason。

目标：

- 优化 execution chain 和 run controls 的信息层级。
- 将 samples 区域改为“导入状态 + preview + publish readiness”。
- 强化失败任务恢复路径。

验收：

- succeeded / failed / running 三类 mock 或 fixture 截图可读。
- cancel/retry/artifact retry 的 disabled reason 清晰。

### F3：Trajectory Review

状态：基础版已完成，已增加过滤、折叠、基础异常定位、schema alignment、tool call id 映射和基础 diff 能力，后续继续增强审核效率。

目标：

- Timeline 区分 user / assistant / tool call / observation。
- OpenAI Messages tab 显示 role、content、tool_calls、tool_call_id。
- provenance 表支持 schema 快速识别和下载。
- Summary tab 对齐 ATIF/default 与 OpenAI messages 的覆盖、行数、tool call、observation/tool response 和异常数。
- Summary tab 按 tool call id 展示 ATIF call/observation 与 OpenAI call/response 的映射状态和 name/arguments/response diff。
- 对缺 source、缺内容、错误信号、tool response 关联问题做基础异常定位。

验收：

- ATIF 和 OpenAI messages 两种 schema 都能从 trial 页稳定查看。
- trajectory 缺失时恢复路径明确。
- Summary tab 能判断两种 schema 是否齐全，以及 tool call / response 信号是否一致。
- Summary tab 能看到每个 tool call id 的 aligned / partial / unlinked 映射状态和 Match / mismatch diff 摘要。
- 能切换 anomaly-only 模式快速定位异常 timeline event / OpenAI message。

### F4：Result Dataset Review

状态：基础版已完成，已增加样本审核分页、异常定位和字段 profile。

目标：

- 强化 samples review：分页、搜索、异常定位、字段覆盖和字段 profile。
- 结果数据集 lineage 明确展示 input dataset、task、trial、artifact。
- 下载区解释 JSONL/JSON 两种 contract。

验收：

- 从 result dataset 能跳回 source task/trial/artifact。
- JSONL/JSON 下载入口可用，错误有恢复提示。
- 能在 result dataset 中直接定位缺 content、缺 reward、低 reward、空字符串、稀疏样本。

### F5：Workbench 收敛

状态：基础版已完成，已增加失败原因聚合和 runtime/provider 运行摘要。

目标：

- Workbench 从“卡片集合”收敛成运营首页。
- 最近任务、失败任务、最新结果变成主要扫描内容。
- readiness 只保留影响下一步操作的状态。

验收：

- 首屏能判断平台是否可运行、是否有失败任务、下一步应该做什么。
- 移动端首屏优先展示状态和主动作。
