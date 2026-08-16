# Compose 真实 Harbor Job 后端接入

本 runbook 用于本地端到端验证：Compose 只启动控制面依赖，`harbor-runner`
在宿主机直接运行，并使用宿主机 Docker daemon 执行 Docker provider 任务。

## 原则

- 不把 RabbitMQ 当状态源，job 状态仍以 MySQL 为准。
- 本地 Compose 不启动 `harbor-runner` 容器。
- 本地 Docker smoke 使用宿主机当前 Docker context，不挂载 `/var/run/docker.sock` 到 runner 容器，也不再维护 runner 容器访问宿主机 Docker 的本地路径方案。
- 组件运行配置放在各自子项目：`harbor/config/runner.local.toml` 和 `harbor-control-plane/config/control-plane.local.toml`。
- 当前迭代 COS 凭证直接写 TOML；后续再切到 env/K8s Secret 引用。

## Docker + COS 本地验证

先把 COS 占位值替换成真实配置：

```text
harbor/config/runner.local.toml
harbor-control-plane/config/control-plane.local.toml
```

两个文件的 artifact bucket/region/prefix 需要一致；runner 额外配置
`input_materialization.cos`，用于从 COS 下载输入 dataset。

启动控制面：

```bash
cd deploy/docker-compose
docker compose -f compose.dev.yml up --build -d
```

Compose 会启动 RabbitMQ，AMQP 端口为 `5672`，管理 UI 端口为 `15672`。
本地默认队列为 `harbor_jobs`。

启动宿主机 runner：

```bash
cd ../../harbor
uv sync --all-extras --dev
uv run harbor runner start --config config/runner.local.toml --keep-alive
```

提交最小 Docker smoke job：

```bash
cd ../deploy/docker-compose
export HARBOR_PLATFORM_ROOT=$(cd ../.. && pwd)
./scripts/submit-and-wait-job.sh smoke/docker-touch-file-smoke-job.local.json
```

脚本默认断言：

- `/runners?stale_after_sec=60` 至少有 1 个 `online` runner。
- `POST /jobs` 成功返回 job id。
- job 最终进入 `succeeded`。
- terminal job response 带非空 `runner_id`。
- `GET /jobs/{job_id}/trials` 至少返回 1 条 trial。
- `GET /jobs/{job_id}/artifacts` 至少包含 `result` 和 `artifact-manifest`。
- terminal `runner_id` 能在 `/runners` 返回列表中找到。

可通过环境变量调整严格度：`HARBOR_SMOKE_EXPECT_RUNNERS`、
`HARBOR_SMOKE_REQUIRE_TRIALS`、`HARBOR_SMOKE_REQUIRE_RESULT_ARTIFACT`、
`HARBOR_SMOKE_REQUIRE_ARTIFACT_MANIFEST`、`HARBOR_SMOKE_POLL_INTERVAL_SEC`、
`HARBOR_SMOKE_RUNNER_TIMEOUT_SEC`、`HARBOR_SMOKE_METADATA_TIMEOUT_SEC`。

如果要在本机模拟多个 runner，启动多个终端并为每个进程设置不同 ID：

```bash
HARBOR_RUNNER_ID=local-runner-2 uv run harbor runner start --config config/runner.local.toml --keep-alive
```

## AGS/TKE

AGS/TKE smoke 也通过宿主机 runner 执行，不再通过 Compose override 注入 runner
容器配置。启用前需要：

- 按 `harbor/readme-ags.md` 或 `harbor/readme-tke.md` 准备云侧配置和凭证。
- 在 runner 配置的 `[capabilities] providers` 中加入 `ags` 或 `tke`。
- 按 Harbor 现有约定设置 `HARBOR_AGS_CONFIG`、`HARBOR_TKE_CONFIG`、
  `OPENAI_API_KEY`、`OPENAI_BASE_URL` 等运行时变量。

提交 AGS smoke：

```bash
cd deploy/docker-compose
export HARBOR_PLATFORM_ROOT=$(cd ../.. && pwd)
./scripts/submit-and-wait-job.sh smoke/ags-otel-bench-smoke-job.json
```

成功验收和 Docker smoke 一致：API 提交、MySQL lease、runner 执行、
terminal snapshot、trial 明细和 artifact metadata 都必须可查。

## COS Input Materialization

如果要验证输入 dataset 从 COS 下载、校验、解压并重写给 `harbor-runtime`，
使用专门 runbook：
[`cos-input-materialization-local-e2e.md`](cos-input-materialization-local-e2e.md)。

该流程会额外断言：

- job `input_state = "succeeded"`
- `materialized_inputs` 非空
- artifacts 中存在 `kind = "input-manifest"`
