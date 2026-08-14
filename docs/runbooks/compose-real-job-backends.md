# Compose 真实 Harbor Job 后端接入

本 runbook 用于完成 M5 的“真实 Harbor job 成功执行”验收。默认 `compose.dev.yml` 只启动 MySQL、RocketMQ、harbor-api、harbor-runner 和 synthetic-data-platform，不挂宿主 Docker socket，也不启动 privileged DinD。

## 原则

- 不把 RocketMQ 当状态源，job 状态仍以 MySQL 为准。
- 不默认挂载 `/var/run/docker.sock`。
- 不默认启用 `privileged: true` DinD。
- Docker smoke 只连接用户显式提供的外部 rootless Docker daemon。
- 默认推荐 TLS client authentication，不使用未认证 Docker TCP endpoint。
- AGS/TKE smoke 只通过环境变量和 Harbor 配置文件注入凭证，不把密钥写进 Compose 文件；不要用会输出完整环境的 `docker compose config` 展示含密钥 override。

## 方案 A：外部 rootless Docker（推荐 TLS）

前提：本机或远端已有 rootless Docker daemon，并通过 TLS TCP 暴露给 runner 容器。Linux 本机可让容器通过 `host.docker.internal` 访问 host-gateway。

生成本地私有 TLS 证书：

```bash
cd deploy/docker-compose
./scripts/create-rootless-docker-tls-certs.sh .local/rootless-docker-certs
```

启动 rootless Docker daemon。示例监听 `2376` 并强制 client cert：

```bash
dockerd-rootless.sh \
  --host=tcp://0.0.0.0:2376 \
  --host=unix://$XDG_RUNTIME_DIR/docker-rootless.sock \
  --tlsverify \
  --tlscacert=$PWD/.local/rootless-docker-certs/server/ca.pem \
  --tlscert=$PWD/.local/rootless-docker-certs/server/cert.pem \
  --tlskey=$PWD/.local/rootless-docker-certs/server/key.pem
```

启动 Compose。rootless Docker daemon 在宿主机上解析 bind mount 源路径，
所以 Docker smoke 需要额外启用 host-path override，让 runner 容器和
daemon 使用同一组宿主机绝对路径：

```bash
export HARBOR_RUNNER_DOCKER_TLS_CERTS=$PWD/.local/rootless-docker-certs
export HARBOR_PLATFORM_HOST_ROOT=$(cd ../.. && pwd)
export HARBOR_RUNNER_HOST_JOBS_DIR=$HARBOR_PLATFORM_HOST_ROOT/deploy/docker-compose/.local/runner-jobs
mkdir -p "$HARBOR_RUNNER_HOST_JOBS_DIR"
docker compose \
  -f compose.dev.yml \
  -f compose.rootless-docker-tls.yml \
  -f compose.rootless-docker-host-paths.yml \
  up --build
```

验证 runner 容器能通过 TLS 访问 Docker daemon：

```bash
docker compose \
  -f compose.dev.yml \
  -f compose.rootless-docker-tls.yml \
  -f compose.rootless-docker-host-paths.yml \
  exec harbor-runner-1 docker info
```

然后提交 Docker provider 的 Harbor JobConfig。仓库内置的最小 smoke 使用公开镜像 `ubuntu:24.04` 和 oracle agent，只验证 solution 写文件、verifier 检查文件，避免依赖私有镜像或外部测试下载：

```bash
./scripts/submit-and-wait-job.sh smoke/docker-touch-file-smoke-job.host-paths.json
```

脚本默认断言：

- `/runners?stale_after_sec=60` 至少有 2 个 `online` runner。
- `POST /jobs` 成功返回 job id。
- job 最终进入 `succeeded`。
- terminal job response 带非空 `runner_id`。
- `GET /jobs/{job_id}/trials` 至少返回 1 条 trial。
- `GET /jobs/{job_id}/artifacts` 至少包含 `result` 和 `artifact-manifest`。
- terminal `runner_id` 能在 `/runners` 返回列表中找到。

可通过环境变量调整严格度：`HARBOR_SMOKE_EXPECT_RUNNERS`、`HARBOR_SMOKE_REQUIRE_TRIALS`、`HARBOR_SMOKE_REQUIRE_RESULT_ARTIFACT`、`HARBOR_SMOKE_REQUIRE_ARTIFACT_MANIFEST`、`HARBOR_SMOKE_POLL_INTERVAL_SEC`、`HARBOR_SMOKE_RUNNER_TIMEOUT_SEC`、`HARBOR_SMOKE_METADATA_TIMEOUT_SEC`。

## 方案 A2：外部 rootless Docker（未认证 TCP，仅显式授权时）

`compose.rootless-docker.yml` 仍保留给已经由外部网络策略保护的 rootless Docker endpoint。它使用 `DOCKER_HOST=tcp://host.docker.internal:2375`，不配置 TLS。不要在未明确授权时启动未认证的 `0.0.0.0:2375` Docker API。

```bash
cd deploy/docker-compose
export HARBOR_RUNNER_DOCKER_HOST=tcp://host.docker.internal:2375
docker compose -f compose.dev.yml -f compose.rootless-docker.yml up --build
```

## 方案 B：AGS

前提：已准备 AGS 配置和镜像，参考 `harbor/readme-ags.md`。Compose 启动前在 shell 中注入：

```bash
export HARBOR_AGS_CONFIG=/home/ubuntu/.config/harbor/ags.toml
export AGS_SECRET_ID=...
export AGS_SECRET_KEY=...
export AGS_E2B_API_KEY=...
export AGS_E2B_DOMAIN=...
```

`compose.ags.yml` 会把 `HARBOR_AGS_CONFIG` 指向的文件挂载到 runner 容器内的 `/config/ags.toml`，并把 `AGS_*` 环境变量传给 runner。不要把密钥写进 toml；toml 只保存环境变量名。

启动：

```bash
cd deploy/docker-compose
docker compose -f compose.dev.yml -f compose.ags.yml up --build
```

提交仓库内置 AGS smoke job，并等待 terminal 状态：

```bash
./scripts/submit-and-wait-job.sh smoke/ags-otel-bench-smoke-job.json
```

该脚本使用同一套 M5 断言：runner 在线数量、terminal succeeded、非空 runner assignment、trial 明细和 artifact metadata。

`smoke/ags-otel-bench-smoke-job.json` 使用 runner 镜像内的 `/workspace/harbor/generated/otel-bench-ags-smoke`，只跑 `go-http-tracing`，默认 oracle agent，不需要 OpenAI agent 凭证。如果改成 Codex 等 LLM agent，应通过本地私有 override 注入 `OPENAI_API_KEY`/`OPENAI_BASE_URL`，不要提交到仓库。

验收同样要求 job 最终为 `succeeded`、`/trials` 有真实 trial row、`/artifacts` 至少包含 job result 和 trial result。

## 方案 C：TKE

前提：已准备 kubeconfig、namespace、image pull secret 和 Harbor TKE 配置，参考 `harbor/readme-tke.md`。runner 容器需要挂载 kubeconfig 和 `tke.toml`，并设置：

```bash
export HARBOR_TKE_CONFIG=/path/in/container/tke.toml
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
```

这些变量同样应通过本地私有 override 或部署系统注入，不提交到仓库。

成功验收和 Docker smoke 一致：API 提交、MySQL lease、runner 执行、terminal snapshot、trial 明细、artifact metadata 都必须可查。

## 当前验收记录

截至 2026-08-14，rootless Docker TLS + host-path override 已跑通 M5 真实 Docker provider smoke：

- 单 job smoke：`9a5e4f5364ba462bad0c51663cd9dd8a`，runner `runner-1`，最终 `succeeded`，`/trials` 有 1 条 `succeeded` trial，`/artifacts` 包含 `result` 和 `artifact-manifest`。
- 并发双 job smoke：`60707c0367a54f68a72017f5b145ff42` 由 `runner-1` 执行，`3849c6f61c5a4c56a976690c196cc7af` 由 `runner-2` 执行，二者最终均 `succeeded`，验证 MySQL lease、RocketMQ/控制面 fallback、双 runner 分担和 artifact/trial 回写。

AGS/TKE 真实 smoke 仍需要明确云资源授权和凭证；未认证 `0.0.0.0:2375` Docker API 仍只应在明确授权且有外部网络保护时使用。
