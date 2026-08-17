# Synthetic Frontend Local E2E With COS And TKE

本 runbook 用于本地验证 synthetic-data-platform 前端闭环：

```text
Browser :5173
  -> synthetic-data-platform API :8081
  -> harbor-api :8080
  -> MySQL + RabbitMQ in Compose
  -> host-side harbor-runner
  -> harbor-runtime
  -> TKE agent-runtime
  -> COS artifacts / result downloads
```

它覆盖：

- 上传本地 Harbor benchmark 归档到 COS。
- 从前端或脚本创建 TKE synthetic task。
- 等待 Harbor job 完成并上传 artifacts。
- 查看 Task、Trial、Artifact download URL，并实际下载一个结果 artifact。
- 当 agent 产出 trajectory 时，查看 Trajectory 和 OpenAI messages。
- 执行 samples ingest。
- 当样本源存在时 publish result dataset，并下载 JSONL / JSON。

## 代码和配置目录

本地默认目录：

```text
/home/ubuntu/project/harbor-platform
/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags
```

运行配置仍放在各组件子仓库，不放在 super repo 的 `deploy/` 下：

```text
/home/ubuntu/project/harbor-platform/harbor/config/runner.local.toml
/home/ubuntu/project/harbor-platform/harbor-control-plane/config/control-plane.local.toml
/home/ubuntu/project/harbor-platform/synthetic-data-platform/config/platform.local.toml
```

这三个文件是本地部署配置，可能包含 COS 明文凭证，不能提交。

## 前置条件

1. `harbor/config/runner.local.toml`
   - `[artifact_storage] backend = "cos"`
   - `[artifact_storage.cos]` 配置结果 artifact bucket、region、prefix、secret。
   - `[input_materialization] backend = "cos"`
   - `[input_materialization.cos]` 配置输入 dataset bucket、region、prefix、secret。
   - `[capabilities] providers` 包含 `tke`。
   - 如果任务 runtime 是 `tke`，但 runner 只声明 `providers = ["docker"]`，runner
     仍会 online 和 heartbeat，但 control-plane 不会把 TKE job lease 给它。
2. `harbor-control-plane/config/control-plane.local.toml`
   - `[artifact_storage] backend = "cos"`
   - COS bucket、region、prefix 与 runner artifact storage 对齐。
3. `synthetic-data-platform/config/platform.local.toml`
   - `[dataset_storage] backend = "cos"`
   - COS bucket、region、prefix 指向输入 dataset 上传位置。
4. TKE 运行时配置已按 `harbor/readme-tke.md` 准备。
5. 本机有 `curl`、`jq`、`tar`、`sha256sum`、`docker compose`、`uv`。

## 启动服务

从 super repo 启动本地控制面和前端：

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose
docker compose -f compose.dev.yml -f compose.synthetic-upload.yml up --build -d
```

服务地址：

```text
harbor-api:                 http://localhost:8080
synthetic-data-platform API: http://localhost:8081
synthetic-data-platform Web: http://localhost:5173
RabbitMQ management:         http://localhost:15672
```

启动宿主机 runner：

```bash
cd /home/ubuntu/project/harbor-platform/harbor
uv sync --all-extras --dev

# 按 harbor/readme-tke.md 设置 TKE 和模型相关环境变量。
uv run harbor runner start --config config/runner.local.toml --keep-alive
```

## 脚本化验证

先做 preflight，只检查服务、前端、dataset 目录和 online runner，不上传、不创建任务：

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose

HARBOR_E2E_PREFLIGHT_ONLY=1 \
HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=go-http-tracing \
./scripts/synthetic-cos-tke-e2e.sh
```

生产或网关鉴权环境可配置 API/Web 地址和认证：

```bash
SYNTHETIC_API_BASE=https://<synthetic-api> \
HARBOR_API_BASE=https://<harbor-api> \
SYNTHETIC_WEB_BASE=https://<synthetic-web> \
HARBOR_E2E_BEARER_TOKEN='<token>' \
HARBOR_E2E_DATASET_DIR=/path/to/dataset \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=<task-name> \
./scripts/synthetic-cos-tke-e2e.sh
```

也可以用显式 header：

```bash
HARBOR_E2E_AUTH_HEADER='Authorization: Bearer <token>' ./scripts/synthetic-cos-tke-e2e.sh
```

如果 synthetic API、harbor API、Web 经过不同入口或不同认证，可分别设置：

```text
HARBOR_E2E_SYNTHETIC_AUTH_HEADER
HARBOR_E2E_HARBOR_AUTH_HEADER
HARBOR_E2E_WEB_AUTH_HEADER
HARBOR_E2E_SYNTHETIC_BEARER_TOKEN
HARBOR_E2E_HARBOR_BEARER_TOKEN
HARBOR_E2E_WEB_BEARER_TOKEN
```

如果 runner 还没启动，可以临时缩短等待时间快速检查服务和诊断输出：

```bash
HARBOR_E2E_PREFLIGHT_ONLY=1 \
HARBOR_E2E_RUNNER_TIMEOUT_SEC=5 \
HARBOR_E2E_POLL_INTERVAL_SEC=1 \
./scripts/synthetic-cos-tke-e2e.sh
```

preflight 通过后，在另一个终端执行完整链路：

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose

HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=go-http-tracing \
HARBOR_E2E_TIMEOUT_SEC=1800 \
HARBOR_E2E_REQUIRE_TRAJECTORY=1 \
HARBOR_E2E_REQUIRE_OPENAI_TRAJECTORY=1 \
HARBOR_E2E_REQUIRE_PUBLISH=1 \
HARBOR_E2E_FRONTEND_LIVE_CHECK=1 \
./scripts/synthetic-cos-tke-e2e.sh
```

如果要稳定覆盖 trajectory、OpenAI messages、样本导入、result dataset publish
和 JSONL / JSON 下载，使用 super repo 内置 smoke dataset：

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose

HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor-platform/deploy/docker-compose/smoke/synthetic-trajectory-sample-dataset \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=trajectory-sample-smoke \
HARBOR_E2E_TIMEOUT_SEC=1800 \
HARBOR_E2E_REQUIRE_TRAJECTORY=1 \
HARBOR_E2E_REQUIRE_OPENAI_TRAJECTORY=1 \
HARBOR_E2E_REQUIRE_PUBLISH=1 \
./scripts/synthetic-cos-tke-e2e.sh
```

这个 smoke dataset 只有一个 Harbor task。`oracle` agent 会执行任务自带
`solution/solve.sh`，写出：

- `agent/trajectory.json`
- `artifacts/.../samples.json`

runner 收集阶段会把 ATIF trajectory 转换并登记为
`agent/trajectory.openai-messages.json`，用于验证 OpenAI messages schema 查询链路。

它用于验证平台链路，不替代真实 benchmark 质量验收。

脚本会：

1. 检查 `http://localhost:5173`、`http://localhost:8081/health`、online runner。
2. 打包并上传 `otel-bench-ags` 到 synthetic dataset storage COS。传入
   benchmark 集合目录时，脚本会打包目录内容，确保归档根目录直接包含
   Harbor task 子目录；传入单个 task 目录时，脚本会把该 task 目录作为
   归档根目录下的一个子目录。
3. 创建 synthetic task，并通过 `dataset_id` 让 backend 透传 `input_datasets`。
4. 等待 Harbor job 进入 `succeeded`。
5. 断言：
   - dataset upload 返回 `cos://` URI 和 `metadata.storage_key`。
   - `input_state = "succeeded"`
   - `materialized_inputs` 至少 1 条。
   - artifacts 至少包含 1 条 `kind = "input-manifest"`。
   - 至少 1 条 trial
   - 至少 1 条 artifact
   - 至少 1 条带 `storage_type = "cos"` 和 `storage_key` 的 artifact
6. 如果存在 OpenAI messages trajectory，通过 synthetic API 获取并校验。
7. 通过 synthetic API 获取 artifact download URL，并下载一个非空 artifact 文件。
8. 调用 `POST /synthetic-tasks/{task_id}/ingest-samples`。
9. 如果 ingest 到样本，则 publish result dataset，并下载 JSONL / JSON。
10. 如果设置 `HARBOR_E2E_FRONTEND_LIVE_CHECK=1`，脚本会把本次真实
    dataset/task/trial/result ID 传给 `synthetic-data-platform/web` 的
    Playwright live test，实际打开前端页面验证工作流。

### Trajectory 验证说明

默认 `HARBOR_E2E_AGENT_NAME=oracle` 用于验证 COS 输入上传、TKE 执行、结果
artifact 上传和 artifact 下载 URL。部分 agent 不会写出原生 ATIF 轨迹；此时
`harbor-runtime` 会基于 trial result 写出兜底 `agent/trajectory.json`，runner
随后登记 ATIF artifact，并生成/登记
`agent/trajectory.openai-messages.json`。

如果要强制验证 trajectory 和 OpenAI messages sidecar，显式打开断言：

```bash
HARBOR_E2E_REQUIRE_TRAJECTORY=1 \
HARBOR_E2E_REQUIRE_OPENAI_TRAJECTORY=1 \
./scripts/synthetic-cos-tke-e2e.sh
```

没有对应 artifact 时脚本会失败。

### 样本 publish 说明

当前 synthetic-data-platform 的样本导入仍然依赖 Harbor artifact 中存在：

- `kind = "sample"`
- `kind = "samples"`
- 或 `kind = "trial-result"` 且 JSON 内有可抽取的 `samples`
- 或 `kind = "trajectory"` 且 `metadata.schema = "openai_messages"`，此时平台会
  把整段 OpenAI messages 转成一个 `{sample_type, messages, source_artifact}`
  样本，用于后训练数据集审核和 JSONL 导出

因此，旧任务或非 JSON artifact-only 任务可能只会验证到 artifact / download
URL，不会自动生成 result dataset。当前 `otel-bench-ags` + `oracle` + fallback
OpenAI messages trajectory 路径可以 ingest 1 条
`openai_messages_trajectory` 样本，并 publish result dataset。

如果你要强制验证 result dataset publish 和下载，使用带样本源的任务，并设置：

```bash
HARBOR_E2E_REQUIRE_PUBLISH=1 ./scripts/synthetic-cos-tke-e2e.sh
```

没有 ingest 到样本时脚本会失败。

### COS I/O Gate

脚本默认打开这些 COS 输入/输出断言：

```text
HARBOR_E2E_REQUIRE_DATASET_COS_URI=1
HARBOR_E2E_REQUIRE_INPUT_STATE=succeeded
HARBOR_E2E_REQUIRE_MATERIALIZED_INPUTS=1
HARBOR_E2E_REQUIRE_INPUT_MANIFEST=1
HARBOR_E2E_REQUIRE_COS_ARTIFACTS=1
```

这组断言覆盖：

- synthetic API 上传 dataset archive 到 COS。
- harbor-api 把 `input_datasets` 透传给 runner。
- runner 从 COS 下载、校验、解压输入 dataset，并写回 `materialized_inputs`。
- runner 登记 `input-manifest`。
- runner 上传结果 artifacts 到 COS。
- synthetic API 通过 harbor-api 获取 artifact download URL，并下载非空内容。

2026-08-17 本地 M38 smoke 已使用
`deploy/docker-compose/smoke/synthetic-trajectory-sample-dataset`、runtime `tke`
跑通以上 gate，并额外验证了 OpenAI messages trajectory、samples ingest、result
dataset publish、JSONL / JSON 下载。

2026-08-17 M39 smoke 已在同一脚本新增生产参数化能力后再次跑通，覆盖自定义
base URL、runtime、dataset、timeout 和可选 API/Web auth header/bearer token。

2026-08-17 真实 benchmark E2E 已使用
`/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags`、runtime `tke`、
task `go-http-tracing` 跑通：

- dataset archive 上传到 COS，并由 runner materialize 到本地。
- Harbor job `3389c95efdd343ddaffc9f223cfc2333` 进入 `succeeded`。
- synthetic task `7ee08516b4324c58b01c5ebeefec2d7f` 进入 `published`。
- `input_state = succeeded`，`artifact_state = succeeded`。
- 1 个 trial，155 个 COS artifacts。
- 2 个 trajectory artifacts，其中 1 个为 OpenAI messages schema。
- OpenAI messages trajectory API 返回 2 条 messages。
- sample ingest 得到 1 条 sample。
- result dataset `dd57447867404faba36ea0b333a37738` 发布成功。
- JSONL 下载 8756 bytes，JSON 下载 9467 bytes。
- 已追加 live 前端验收：
  `SYNTHETIC_LIVE_* npm run test:live` 通过，浏览器实际打开 Workbench、
  Dataset Detail、Task Detail、Trial OpenAI Messages、Result Detail，并触发
  `Download JSONL` 前端下载流程。

2026-08-17 追加脚本集成验收：同一真实 benchmark 再次运行完整脚本，并设置
`HARBOR_E2E_FRONTEND_LIVE_CHECK=1`，确认 shell E2E 会在 publish 后自动触发
Playwright live test。

- dataset `bcb0161c210846b69d40d055c5106f34` 上传到 COS。
- synthetic task `bc5d079cdec84139b098c26290ebde2b` 跑通并进入 result publish。
- Harbor job `85540649fc8d4549a1211d92a4116c8f` 进入 `succeeded`。
- 1 个 trial，155 个 COS artifacts，2 个 trajectory artifacts，1 个 OpenAI
  messages trajectory。
- artifact download、sample ingest、result publish、JSONL / JSON download 均通过。
- 脚本内自动运行 `npm run test:live`，Playwright `1 passed`。
- result dataset `b98b7d1b248d470ba750bf9181460e5b` 可在前端 Result Detail 打开。

## 前端手工验收

脚本跑完后打开：

```text
http://localhost:5173
```

按脚本输出的 URL 检查：

1. `Datasets`
   - 新 dataset 可见。
   - Detail 页面显示 COS URI、checksum、task name。
2. `Tasks`
   - 新 task 可见，runtime 为 `tke`。
   - Detail 页面 `Input ready`、`Runtime`、`Artifacts` 阶段状态正确。
   - Artifacts 表格显示 `kind`、`schema`、`relative_path`、`storage_key`。
   - `Download` 按钮显示 pending/success 状态。
3. `Trial Detail`
   - `Timeline` 可查看。
   - `OpenAI Messages` tab 请求 `schema=openai_messages`。
   - 页面展示 schema 摘要和 message role 计数。
   - 长 trace / URL / COS key 在 375px 和 812x375 下不横向溢出。
4. `Results`
   - 如果已 publish，Result Detail 显示 lineage、source trials、source artifacts、samples。
   - `Download JSONL` 和 `Download JSON` 都有 pending/success 反馈。

## 前端质量门禁

在 synthetic-data-platform 前端目录运行：

```bash
cd /home/ubuntu/project/harbor-platform/synthetic-data-platform/web
npm run verify
```

该命令包含：

- TypeScript + Vite production build。
- Playwright UI 回归。
- 375x812、812x375、768x1024、1024x768、1440x900 视口截图。
- 核心路径 mock E2E。
- 键盘焦点、focus ring、长 token、75 条任务列表压力检查。

真实 compose 前端验收可以单独运行：

```bash
cd /home/ubuntu/project/harbor-platform/synthetic-data-platform/web

SYNTHETIC_LIVE_BASE_URL=http://localhost:5173 \
SYNTHETIC_LIVE_DATASET_ID=<dataset_id> \
SYNTHETIC_LIVE_DATASET_NAME=<dataset_name> \
SYNTHETIC_LIVE_TASK_ID=<synthetic_task_id> \
SYNTHETIC_LIVE_TASK_NAME=<task_name> \
SYNTHETIC_LIVE_TRIAL_ID=<trial_id> \
SYNTHETIC_LIVE_RESULT_DATASET_ID=<result_dataset_id> \
SYNTHETIC_LIVE_RUNTIME=tke \
npm run test:live
```

该 live test 不 mock API。它验证：

- Workbench 和 run readiness 可渲染。
- Dataset Detail 显示真实 dataset 和 task name。
- Task Detail 显示 published/succeeded 状态、input/artifact/sample 阶段和
  trajectory review queue。
- Trial 页面可通过 `?view=messages` 打开 OpenAI Messages tab。
- Result Detail 显示 lineage、review checklist、export contract、samples，并能
  触发 `Download JSONL` 前端下载流程。

## 清理

停止 compose：

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose
docker compose -f compose.dev.yml -f compose.synthetic-upload.yml down
```

runner 进程在其终端用 `Ctrl+C` 停止。
