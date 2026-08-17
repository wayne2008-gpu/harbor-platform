# Synthetic Data Platform Frontend V2 Design

## 背景

当前 `synthetic-data-platform/web` 已经具备 MVP 级工作台能力：dataset 上传/登记、
TKE task 创建、任务恢复动作、trial trajectory 审核、result dataset 下载、Workbench
和 Settings 基础检查都已经落地。

下一轮前端不从零重写，而是在现有 React/Vite 前端上做产品化升级，目标是让用户可以稳定
从浏览器完成：

```text
上传或登记 dataset
  -> 创建 TKE synthetic task
  -> 观察运行状态和恢复失败
  -> 审核 trial trajectory / OpenAI messages
  -> ingest samples
  -> publish result dataset
  -> 下载 JSONL/JSON 并回溯 lineage
```

## UI/UX Skill 结论

本轮按要求使用 `ui-ux-pro-max` 校准设计。查询输入：

```text
internal analytics dashboard ai data operations
variance: 4/10
motion: 3/10
density: 9/10
stack: React 19 + Vite + React Router + TanStack Query + lucide-react
```

采用：

- `Data-Dense Dashboard`：高密度、可扫描、少装饰的运营工作台。
- 低强度动效：150-300ms hover、focus、tab、loading、filter 反馈。
- 表格和状态队列优先：首屏回答“能不能跑、哪里失败、下一步做什么”。
- 错误恢复优先：失败原因、下一步动作、重试入口必须同屏可见。
- 可深链：列表 search/filter/page、task builder 预填、trial tab 都进入 URL。
- React 列表使用稳定业务 ID；高频 search/filter 使用 debounce 或 `useDeferredValue`。

不采用：

- `Enterprise Gateway` 的官网结构：hero、行业方案、客户 logo、Contact Sales。
- 装饰性大图、渐变背景、自动播放动画、营销式卡片堆叠。
- Harbor 运维入口作为一级导航。Harbor 字段只作为 provenance 和 diagnostics。

## 产品定位

前端是“后训练 agent 轨迹数据合成平台”的业务工作台，不是 Harbor 运维后台。

主流程语言固定为：

```text
Dataset -> Synthetic task -> Trial trajectory -> Samples -> Result dataset
```

Harbor 内部概念的展示位置：

| Harbor 字段 | 前端位置 |
| --- | --- |
| `harbor_job_id` | Task Detail 状态、Result lineage |
| `trial_id` | Trial Review、Result source trial |
| artifact kind/schema/path/COS URI | Task artifacts、Trial provenance、Result audit |
| runner/lease/execution namespace | Task diagnostics 底部 |

## 信息架构

一级导航继续保持 5 个入口：

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
/tasks/new?datasetId=...
/tasks/:task_id
/tasks/:task_id/trials/:trial_id?view=summary|timeline|messages|raw
/results
/results/:result_dataset_id
/settings
```

页面结构：

```text
┌─────────────────────────────────────────────────────────────┐
│ Skip link                                                   │
├──────────────┬──────────────────────────────────────────────┤
│ Sidebar      │ Page header: title / context / primary action│
│              ├──────────────────────────────────────────────┤
│ Primary nav  │ Readiness / filters / status summary         │
│              ├──────────────────────────────────────────────┤
│              │ Main workflow panel                          │
│              │ Secondary diagnostics / raw details last     │
└──────────────┴──────────────────────────────────────────────┘
```

响应式规则：

- 桌面端使用 sidebar + 内容区，详情页可以双列，但主审核区域占主要宽度。
- 平板端保留表格扫描能力，辅助面板下沉或缩窄。
- 手机端表格转记录卡片或表格容器内横向滚动，页面本身不能横向溢出。
- COS URI、artifact path、checksum、job id 使用可换行容器或局部滚动。

## 视觉系统

基线来自 `design-system/synthetic-data-platform/MASTER.md`：

- 主色：`#1E40AF`
- 强调色：`#D97706`
- 背景：`#F8FAFC`
- 表面：`#FFFFFF`
- 边框：`#DBEAFE`
- 破坏性状态：`#DC2626`

需要补充的状态色：

| 语义 | 建议 |
| --- | --- |
| Success / Ready | 深绿，服务于 succeeded、published、ready gate |
| Warning / Needs review | 琥珀色，服务于 anomaly、partial、missing optional |
| Danger / Blocked | 红色，服务于 failed、exception、blocked gate |
| Neutral / Checking | slate/gray，服务于 pending、unknown、empty |

约束：

- 不把整站做成单一蓝色。
- 卡片圆角不超过 8px。
- 页面 section 不做悬浮大卡片；卡片只用于重复项、modal、工具面板。
- icon 使用 `lucide-react`，有文字的按钮内 icon 设置为装饰性，icon-only 控件必须有
  accessible name。
- body 字号保持 16px 基线；长 ID、JSON、COS key 使用 monospace。

## 页面设计

### Workbench

目标：用户进来 10 秒内知道“现在能不能跑、哪里失败、下一步点哪里”。

首屏顺序：

1. Readiness strip：Synthetic API、Harbor API、Dataset COS、COS credential flag、
   runner/runtime readiness。
2. Next actions：setup blocker、failed task、active task、publish candidate、latest
   result。
3. Failure causes：dataset materialization、runtime/trial、artifact upload、sample
   ingest、publish。
4. Recent runs、latest result datasets、provider load。

设计规则：

- 不承载复杂配置。
- 失败和阻塞状态优先于普通统计。
- 每个 action 都跳到具体 dataset/task/result 页面。

### Datasets

目标：让用户确认输入数据是否能被 Harbor runtime 使用。

列表字段：

```text
name | version | source | format | task_names | checksum/size | created | action
```

新建页：

- Segmented control：Upload archive / Register COS URI。
- 顶部 error summary + 字段 inline error。
- Payload preview 展示将提交的 dataset contract。
- 成功后进入 dataset detail。

详情页：

- source URI、checksum、size、task_names、metadata。
- readiness：是否有 task_name、checksum、可创建 task。
- version family、recent tasks、result datasets。
- 主动作：Create task from dataset，并写入 `/tasks/new?datasetId=...`。

### Tasks

目标：创建任务、观察执行、处理失败恢复。

Task Builder：

```text
left: dataset / task_name / runtime / agent / model / concurrency form
right: readiness gates + JobConfig preview
```

runtime 用 radio card 表达：

```text
docker | ags | tke
```

每个 runtime 显示实际 `environment.type`，避免用户混淆 harbor-runtime 和
agent-runtime。

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
- mutation 反馈使用 `role=status`，不打断焦点。

### Trial / Trajectory Review

目标：核心审核页，判断一个 trial 是否适合进入后训练数据集。

tab：

```text
Summary | Timeline | OpenAI Messages | Raw JSON
```

URL：

```text
/tasks/:task_id/trials/:trial_id?view=summary|timeline|messages|raw
```

Summary：

- Review decision：Ready / Needs review / Blocked / Checking。
- Quality gates：reward、verifier、exception、schema readiness。
- Schema alignment：ATIF/default trajectory 与 OpenAI messages 覆盖情况。
- Tool call mapping、content diff、message diff。
- Anomaly summary，并可跳到 Timeline / OpenAI Messages。

Timeline：

- 按 step/message/tool call/observation 顺序展示。
- 支持 search、anomaly-only。

OpenAI Messages：

- 按后训练消费视角展示 `role/content/tool_calls/tool_call_id`。
- 标出 duplicate tool call id、missing tool response、orphan tool response。

Raw JSON：

- 放最后，只做兜底。

### Results

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
- 每个 source trial 都能回跳到 Trial Review。
- 空 result dataset 或下载失败必须给恢复路径。

### Settings

目标：只读运行配置和本地 E2E 检查。

允许展示：

- Harbor API base URL。
- dataset storage backend。
- COS bucket、region、prefix、endpoint。
- secret configured flags。
- COS + TKE E2E readiness gates、命令和 manual checkpoints。

禁止展示：

- database password。
- COS secret_id。
- COS secret_key。
- session_token 明文。

## API 依赖和缺口

当前前端可以先使用现有 API 完成大部分展示：

| 页面 | 已有 API 能力 |
| --- | --- |
| Workbench | settings、datasets、tasks、result datasets 派生摘要 |
| Datasets | list/register/upload/get dataset |
| Task Builder | list datasets、create task |
| Task Detail | get task、sync、cancel、retry、artifact retry、ingest、publish |
| Trial Review | task/trial/artifact/trajectory 派生展示 |
| Results | list/get/download result dataset |
| Settings | safe settings summary |

下一轮如果要更像生产平台，需要补充或明确：

| 缺口 | 影响 | 优先级 |
| --- | --- | --- |
| Workbench summary API | 当前依赖前端拉多组列表派生摘要，大数据量时效率差 | P1 |
| Dataset 服务端分页/搜索/版本族 | dataset 数量变多后列表和版本回溯会重 | P1 |
| Trajectory review decision 持久化 | 目前只能展示审核判断，不能保存人工审核结果 | P1 |
| Result sample 服务端分页/搜索/异常过滤 | result dataset 变大后不能靠前端全量处理 | P1 |
| Artifact download signed URL / proxy 策略 | 浏览器直接下载 COS 需要权限和过期策略 | P1 |
| Task event stream 或轻量 polling summary | 长任务观察需要更稳定的实时状态 | P2 |
| Runtime/provider capability API | 前端不应硬编码 TKE/AGS/docker 可用性 | P2 |

## 组件模型

先复用 `synthetic-data-platform/web/src/ui.tsx`，不先抽独立 npm 包。

| 组件 | 用途 | 必须状态 |
| --- | --- | --- |
| `PageHeader` | 页面目标、上下文、主动作 | action 可为空，summary 可换行 |
| `PanelHeader` | 面板标题、摘要、局部动作 | 标题层级正确 |
| `DataTable` | 桌面扫描表格 | 移动端局部滚动或卡片化 |
| `StatusBadge` | 状态表达 | 文案独立表达含义，颜色只辅助 |
| `RunStageStepper` | task 执行链路 | done/active/pending/blocked |
| `ReadinessGate` | 提交前检查 | ready/warning/blocked + reason + action |
| `ActionQueue` | 恢复动作队列 | available/waiting/blocked + next check |
| `TrajectoryTabs` | 轨迹审核 | URL tab、键盘可达、焦点可见 |
| `LineageFlow` | 来源回溯 | dataset/task/job/trial/result 可点击 |
| `MutationStatus` | 异步动作反馈 | `role=status`，不打断焦点 |
| `JsonBlock` | 原始 JSON 兜底 | 默认下沉，不抢主流程 |

## 开发排期

按 2026-08-17 起的工作日估算。由于 MVP 已完成，下面是产品化增量，不是重写。

| 阶段 | 工作量 | 内容 | 验收 |
| --- | --- | --- | --- |
| FE-V2-0 设计冻结 | 0.5d | 对齐本文、现有 MVP、API 缺口、页面优先级 | 文档可直接拆任务 |
| FE-V2-1 App shell 和组件治理 | 1d | 统一 token、状态色、按钮/表格/面板、空态/错误态、移动端 shell | 375/768/1024/1440 无横向溢出 |
| FE-V2-2 Dataset 管理增强 | 1.5d | 上传/登记体验、版本族、readiness、server search 接入预留 | 可从 dataset 稳定创建 TKE task |
| FE-V2-3 Task 创建和运行控制增强 | 2d | TKE builder、provider capability、execution chain、恢复动作队列、polling summary | 失败/成功/发布态都有明确下一步 |
| FE-V2-4 Trajectory 审核工作台 | 2.5d | review decision、schema alignment、OpenAI messages、diff/anomaly、审核结果持久化预留 | 可判断 trial 是否进入后训练数据集 |
| FE-V2-5 Result dataset 审核和下载 | 1.5d | delivery decision、sample server paging 预留、lineage、signed/proxy download | 可回溯并下载 JSONL/JSON |
| FE-V2-6 Workbench/Settings/E2E 验收 | 1.5d | Workbench summary、失败队列、COS/TKE 配置检查、live E2E smoke | 浏览器端 COS + TKE 主链路通过 |

总计约 10.5 个工作日。如果只做演示级升级，可以压缩到 5-6 个工作日，优先做
FE-V2-1、FE-V2-3、FE-V2-4、FE-V2-5，把服务端分页和审核持久化先作为后端缺口记录。

当前进度：

- `FE-V2-1 App shell 和组件治理` 已启动并完成第一批基础治理：shell landmark 命名、
  可聚焦表格区域、统一 `StatusBadge` tone/aria contract、`MutationStatus` tone 扩展、
  run stage 当前步骤语义和对应 UI smoke。
- `FE-V2-3 Task 创建和运行控制增强` 已启动并完成第一批 handoff 增强：Task
  Builder 和 Task Detail 统一展示 runtime handoff checklist，把提交请求、COS 输入
  materialization、runner lease、runtime start、artifact/sample handoff 串成可扫描检查点，
  并补充 UI smoke 覆盖 runtime 切换、运行详情和失败恢复场景。
- `FE-V2-4 Trajectory 审核工作台` 已启动并完成第一批后训练 handoff 增强：Trial
  Summary 新增 `Post-training handoff`，把 trial quality、OpenAI message contract、
  tool thread integrity、schema parity、audit provenance 汇总成训练数据消费视角的
  Ready / Needs review / Blocked / Checking 判断，并补充正常轨迹和异常 OpenAI tool
  thread 的 UI smoke。
- `FE-V2-5 Result dataset 审核和下载` 已启动并完成第一批结果交付增强：Result
  Detail 已覆盖 delivery decision、review checklist、lineage flow、trajectory audit
  links、export contract、JSONL/JSON download recovery、sample quality summary、field
  profile；本轮补充 `Result sample review scope`，明确 full / partial / empty
  preview 的审核范围，当 API reported `sample_count` 大于返回 `samples.length`
  时把完整交付路径导向 JSONL/JSON downloads，并补充 partial preview UI smoke。

## 开发顺序

建议顺序：

1. 先做 `FE-V2-1`，把视觉和交互基础收敛，避免后续页面各写一套样式。
2. 再做 `FE-V2-3`，因为任务创建和运行恢复是端到端跑数主链路。
3. 接着做 `FE-V2-4`，这是后训练 agent 轨迹数据平台的核心差异化页面。
4. 然后做 `FE-V2-5`，把发布结果、下载和 lineage 闭环补完整。
5. 最后做 `FE-V2-2` 和 `FE-V2-6` 的管理与验收增强。

## 验收

每个前端切片结束后运行：

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

UI 验收必须覆盖：

- 375、768、1024、1440px。
- 无页面级横向滚动。
- keyboard tab 顺序和可见 focus。
- 表单 error summary focus 和字段 inline error。
- icon-only 控件 accessible name。
- reduced-motion 下无关键内容丢失。
- Settings 不泄露 database password、COS secret_id、secret_key、session_token。
