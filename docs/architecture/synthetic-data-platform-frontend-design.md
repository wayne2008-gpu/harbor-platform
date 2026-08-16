# Synthetic Data Platform Frontend Design

## 目标

`synthetic-data-platform` 前端是后训练 agent 轨迹数据合成平台的业务工作台，不是 Harbor 的运维控制台，也不是产品官网。

前端第一阶段要让使用者完成四条闭环：

1. 管理输入 dataset，并确认 dataset 是否可用于 Harbor runtime。
2. 基于 dataset 创建 synthetic task，选择 agent-runtime provider，例如 `tke`。
3. 查看任务执行状态、trial、trajectory、artifact、sample 导入和 publish 状态。
4. 查看并下载发布后的 result dataset，回溯来源任务、trial 和 artifact。

设计原则来自 `ui-ux-pro-max` 的 Data-Dense Dashboard 方向：高密度、可扫描、低装饰、状态清晰、键盘可达。丢弃官网型 Enterprise Gateway / landing page pattern。

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
- Dataset 上传/登记、详情、基于 dataset 创建任务。
- Task 创建、列表、详情、sync/cancel/retry/artifact retry。
- Samples ingest 和 publish。
- Trial 详情、trajectory provenance、summary/timeline/OpenAI messages/raw JSON tabs。
- Result dataset 列表、详情、JSONL/JSON 下载。
- Playwright 响应式 smoke 覆盖多个 viewport。

需要继续优化：

- Artifact/provenance 表在两列详情布局里保持可读宽度和滚动。
- Workbench 减少“卡片堆叠感”，把 readiness、metrics、recent runs 的层级进一步拉开。
- Tasks/Results 列表需要更稳定的筛选状态保留和 URL query 同步。
- Trial 页面需要把 tool call / observation 展示得更像审核流，而不是普通 timeline 文本。
- Result dataset lineage 需要补更强的可视化关系，而不是纯文本摘要。

## 开发排期

### F1：前端设计基线与表格可读性

目标：

- 固化本设计文档。
- 修复 compact 表格在详情双列布局中的断词问题。
- 保持现有 Playwright viewport smoke 通过。

验收：

- `npm run build`
- `npm run test:ui`
- 桌面 task detail 的 artifacts 表路径不再一字一行。

### F2：Task Detail 审核运营体验

目标：

- 优化 execution chain 和 run controls 的信息层级。
- 将 samples 区域改为“导入状态 + preview + publish readiness”。
- 强化失败任务恢复路径。

验收：

- succeeded / failed / running 三类 mock 或 fixture 截图可读。
- cancel/retry/artifact retry 的 disabled reason 清晰。

### F3：Trajectory Review

目标：

- Timeline 区分 user / assistant / tool call / observation。
- OpenAI Messages tab 显示 role、content、tool_calls、tool_call_id。
- provenance 表支持 schema 快速识别和下载。

验收：

- ATIF 和 OpenAI messages 两种 schema 都能从 trial 页稳定查看。
- trajectory 缺失时恢复路径明确。

### F4：Result Dataset Review

目标：

- 强化 samples preview。
- 结果数据集 lineage 明确展示 input dataset、task、trial、artifact。
- 下载区解释 JSONL/JSON 两种 contract。

验收：

- 从 result dataset 能跳回 source task/trial/artifact。
- JSONL/JSON 下载入口可用，错误有恢复提示。

### F5：Workbench 收敛

目标：

- Workbench 从“卡片集合”收敛成运营首页。
- 最近任务、失败任务、最新结果变成主要扫描内容。
- readiness 只保留影响下一步操作的状态。

验收：

- 首屏能判断平台是否可运行、是否有失败任务、下一步应该做什么。
- 移动端首屏优先展示状态和主动作。
