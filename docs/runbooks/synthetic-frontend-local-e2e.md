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
- 查看 Task、Trial、Trajectory、OpenAI messages、Artifact download URL。
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

在另一个终端执行：

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose

HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=go-http-tracing \
HARBOR_E2E_TIMEOUT_SEC=1800 \
./scripts/synthetic-cos-tke-e2e.sh
```

脚本会：

1. 检查 `http://localhost:5173`、`http://localhost:8081/health`、online runner。
2. 打包并上传 `otel-bench-ags` 到 synthetic dataset storage COS。
3. 创建 synthetic task，并通过 `dataset_id` 让 backend 透传 `input_datasets`。
4. 等待 Harbor job 进入 `succeeded`。
5. 断言：
   - `input_state = "succeeded"`
   - 至少 1 条 trial
   - 至少 1 条 artifact
   - 至少 1 条 `kind = "trajectory"` artifact
   - 至少 1 条 `metadata.schema = "openai_messages"` trajectory artifact
   - 至少 1 条带 `storage_type = "cos"` 和 `storage_key` 的 artifact
6. 通过 synthetic API 获取 OpenAI messages trajectory。
7. 通过 synthetic API 获取 artifact download URL。
8. 调用 `POST /synthetic-tasks/{task_id}/ingest-samples`。
9. 如果 ingest 到样本，则 publish result dataset，并下载 JSONL / JSON。

### 样本 publish 说明

当前 synthetic-data-platform 的样本导入仍然依赖 Harbor artifact 中存在：

- `kind = "sample"`
- `kind = "samples"`
- 或 `kind = "trial-result"` 且 JSON 内有可抽取的 `samples`

因此，某些 Harbor benchmark 只会验证到 artifact / trajectory / download URL，
不会自动生成 result dataset。脚本默认允许这种情况，并输出 Task / Trial 前端 URL。

如果你要强制验证 result dataset publish 和下载，使用带样本源的任务，并设置：

```bash
HARBOR_E2E_REQUIRE_PUBLISH=1 ./scripts/synthetic-cos-tke-e2e.sh
```

没有 ingest 到样本时脚本会失败。

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

## 清理

停止 compose：

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose
docker compose -f compose.dev.yml -f compose.synthetic-upload.yml down
```

runner 进程在其终端用 `Ctrl+C` 停止。
