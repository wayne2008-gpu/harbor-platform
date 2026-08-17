# Tencent Cloud Deployment Runbook

本 runbook 定义 Phase 10 的线上部署目标。它面向真实环境：
TKE + TencentDB MySQL + TDMQ for RabbitMQ + COS + TCR。

当前仓库已经提供第一版生产导向 K8s base manifests。本文件固定部署契约、
配置归属、上线顺序、验收项和回滚边界；环境专属 overlay、Ingress、HPA、
PDB 和 NetworkPolicy 仍按这里的分层继续补齐。

## 目标拓扑

```text
synthetic-data-platform Web
  -> synthetic-data-platform API
  -> harbor-api
  -> TencentDB MySQL
  -> TDMQ for RabbitMQ
  -> harbor-runner Pods
  -> harbor-runtime
  -> TKE agent-runtime Pods
  -> COS datasets / artifacts / result datasets
```

部署关系：

- `synthetic-data-platform` 是业务平台，负责 dataset、task、result dataset。
- `harbor-api` 是控制面，负责 job、trial、artifact、runner、lease、retry、cancel。
- `harbor-runner` 和 `harbor-runtime` 在同一个 runner 镜像/Pod 内。
- `agent-runtime` 由 Harbor provider 创建，TKE 场景下是目标 namespace 内的 Pod。

## 配置归属

组件运行配置放在读取它的子项目内，不放在 super repo 的 `deploy/` 目录中：

```text
harbor-control-plane/config/control-plane.<env>.toml
harbor/config/runner.<env>.toml
synthetic-data-platform/config/platform.<env>.toml
harbor/config/tke.<env>.toml
```

生产模板已放在对应子项目：

```text
harbor-control-plane/config/control-plane.production.example.toml
synthetic-data-platform/config/platform.production.example.toml
harbor/config/runner.production.example.toml
harbor/config/tke.production.example.toml
```

推荐线上挂载路径：

```text
harbor-api Pod:
  /config/control-plane.toml

synthetic-data-platform API Pod:
  /config/platform.toml

harbor-runner Pod:
  /config/runner.toml
  /config/tke.toml
```

对应环境变量：

```text
HARBOR_CONTROL_PLANE_CONFIG=/config/control-plane.toml
SYNTHETIC_DATA_PLATFORM_CONFIG=/config/platform.toml
HARBOR_TKE_CONFIG=/config/tke.toml
```

`runner.toml` 仍通过 CLI 参数传入：

```bash
uv run harbor runner start --config /config/runner.toml --keep-alive
```

当前生产模板把 COS bucket、region、prefix、endpoint 等非敏感配置保留在 TOML。
COS `secret_id`、`secret_key`、可选 `session_token`、MySQL `database_url`
、RabbitMQ `rabbitmq_url`、API token 和 tenant ID 都通过 `*_env` 字段引用
环境变量，并由 K8s Secret 注入。不要把任何真实凭证提交到 git。

## 云资源准备

### TencentDB MySQL

准备一个 MySQL 实例和独立数据库，例如：

```text
database: harbor_control_plane
user: harbor_api
```

要求：

- `harbor-api` Pod 可以访问 TencentDB 内网地址。
- 用户具备建表、建索引、写入 `alembic_version` 的权限。
- 上线前创建快照或备份。
- `harbor-api` 启动时会执行 Alembic migration 到 head。
- `harbor-api /ready` 会检查数据库可访问且 `alembic_version` 等于当前 head。
- `harbor-api /health` 只作为进程 liveness，不代表数据库 readiness。

验收：

```sql
select version_num from alembic_version;
```

当前 head 是：

```text
0007_idempotency_tenant_scope
```

### TDMQ for RabbitMQ

准备 RabbitMQ 兼容实例：

```text
queue: harbor_jobs
```

要求：

- `harbor-api` 可以 publish。
- `harbor-runner` 可以 consume。
- RabbitMQ 只作为唤醒/派发通道，MySQL lease 仍是唯一执行判定。
- 消息重复投递或 runner 重启时，runner 必须重新通过 `POST /internal/jobs/claim`
  获取 lease。
- 普通 `run` dispatch 和 `artifact-retry` dispatch 都走 specific claim，不再绕过
  capability、queue 和 quota 匹配。

本地/TDMQ 兼容 smoke 脚本：

```bash
cd /home/ubuntu/project/harbor-platform
./deploy/docker-compose/scripts/rabbitmq-claim-smoke.sh
```

默认连接本地 Compose RabbitMQ：

```text
amqp://guest:guest@localhost:5672/%2F
```

指向 TDMQ for RabbitMQ 时，先确保 `harbor-api` 的
`control-plane.toml [dispatch]` 和 runner 使用同一 TDMQ queue/exchange，然后设置：

```bash
HARBOR_RABBITMQ_SMOKE_API_BASE=https://<harbor-api-base-url> \
HARBOR_RABBITMQ_SMOKE_RABBITMQ_URL='amqps://<user>:<password>@<tdmq-host>:5671/%2F' \
HARBOR_RABBITMQ_SMOKE_RABBITMQ_QUEUE=harbor_jobs \
HARBOR_RABBITMQ_SMOKE_PURGE_QUEUE=0 \
./deploy/docker-compose/scripts/rabbitmq-claim-smoke.sh
```

脚本会启动一个临时 RabbitMQ-only runner，`poll_control_plane_jobs = false`，
提交一个 Docker smoke job，并断言 job 成功、`runner_id` 匹配、trial/artifact
metadata 写回。因为 runner 不启用 polling，成功结果证明链路是
`harbor-api publish -> RabbitMQ/TDMQ consume -> MySQL specific claim -> runner execute`。
如果 `HARBOR_RABBITMQ_SMOKE_RABBITMQ_URL` 带凭证，临时 runner config 会写到
已 git-ignore 的 `deploy/docker-compose/.local/rabbitmq-claim-smoke/`。

### COS

至少准备两个逻辑前缀，bucket 可以相同也可以分开：

```text
datasets prefix:  <env>/datasets/
artifacts prefix: <env>/artifacts/
```

用途：

- `synthetic-data-platform` 上传输入 dataset archive 到 datasets prefix。
- `harbor-runner` 下载输入 dataset archive。
- `harbor-runner` 上传所有 job_dir 普通文件到 artifacts prefix。
- `harbor-api` 读取 artifacts prefix，返回 signed URL 或 proxy stream。

推荐权限拆分：

- synthetic API：datasets prefix 的 `PutObject`、`HeadObject`、`GetObject`。
- runner：datasets prefix 的 `GetObject`、`HeadObject`，artifacts prefix 的
  `PutObject`、`HeadObject`。
- harbor-api：artifacts prefix 的 `GetObject`、`HeadObject` 和签名 URL 所需权限。

当前 artifact key 默认布局：

```text
{prefix}/jobs/{platform_job_id}/attempts/{attempt}/executions/{execution_id}/{relative_path}
```

这个布局避免多个 runner Pod 在同一个 `platform_job_id` 下重试、抢占或补传时
覆盖彼此的文件。

### TCR

准备服务镜像仓库：

```text
harbor-api
synthetic-data-platform-api
synthetic-data-platform-web
harbor-runner
```

如果 TKE agent-runtime 使用 image-only dataset，也需要把 task 镜像推送到 TCR，
并在 task `task.toml` 的 `[environment].docker_image` 中写完整镜像地址。

### TKE

建议拆分两个 namespace：

```text
harbor-platform     # harbor-api, synthetic API/Web, harbor-runner
harbor-agent-runtime # agent-runtime Pods
```

runner 使用的 kubeconfig 或 ServiceAccount 需要能在 agent-runtime namespace 中：

- create/delete/get/list/watch pods
- create pods/exec
- get/list/watch pods/log
- 使用 image pull secret 拉取 TCR 镜像

基础 namespace 和 RBAC manifests 已放在：

```text
deploy/k8s/base/
```

该 base 同时包含第一版服务 Deployment/Service manifests：

```text
harbor-api
synthetic-data-platform
synthetic-data-platform-web
harbor-runner
```

应用：

```bash
kubectl apply -k deploy/k8s/base
```

验证：

```bash
kubectl auth can-i create pods \
  --as system:serviceaccount:harbor-platform:harbor-runner \
  -n harbor-agent-runtime
kubectl auth can-i create pods/exec \
  --as system:serviceaccount:harbor-platform:harbor-runner \
  -n harbor-agent-runtime
kubectl auth can-i get pods/log \
  --as system:serviceaccount:harbor-platform:harbor-runner \
  -n harbor-agent-runtime
```

TKE provider 当前通过 Kubernetes API 工作。线上第一版可以继续把 kubeconfig
挂载为 `/config/kubeconfig` 并在 `tke.toml` 中引用。后续可优化为 in-cluster
ServiceAccount 默认发现。

## 组件配置要点

### control-plane.toml

必须包含：

- MySQL DSN，指向 TencentDB。
- RabbitMQ dispatch 配置，指向 TDMQ for RabbitMQ。
- `[artifact_storage] backend = "cos"`。
- `[artifact_storage.cos]` 指向 artifact bucket、region、prefix。

`harbor-api` 只读 artifact，不上传运行结果。

### platform.toml

必须包含：

- synthetic 平台自己的数据库 DSN。
- harbor API base URL。
- `[dataset_storage] backend = "cos"`。
- `[dataset_storage.cos]` 指向 dataset bucket、region、prefix。

如果 synthetic 平台数据库和 control-plane 数据库复用同一个 TencentDB 实例，
也应使用独立 database/schema，避免业务表和控制面表混在一起。

### runner.toml

必须包含：

- `control_plane_url` 指向线上 `harbor-api`。
- RabbitMQ consumer 配置，指向 TDMQ for RabbitMQ。
- `[artifact_storage] backend = "cos"`。
- `[artifact_storage] upload_policy = "job_dir_all"`。
- `[artifact_storage.cos]` 指向 artifact bucket、region、prefix。
- `[input_materialization] backend = "cos"`。
- `[input_materialization.cos]` 指向 dataset bucket、region、prefix。
- `[capabilities] providers` 包含线上允许的 provider，例如 `tke`。
- `[capabilities] features` 包含 `cos-input`。

当前策略是默认上传 `job_dir` 下所有普通文件。manifest 只补元数据，不限制上传范围。

### tke.toml

必须包含：

- kubeconfig 路径或后续 ServiceAccount 发现配置。
- TKE context。
- agent-runtime namespace。
- 默认 service account。
- image pull secret。
- 可选 node selector、tolerations、pod override。

模型 API key 不写入 `tke.toml`。它们仍通过 Harbor agent env 传入。

## 部署顺序

1. 构建并推送镜像到 TCR。
2. 准备 TencentDB、TDMQ for RabbitMQ、COS、TKE namespace、RBAC、image pull secret。
   TKE namespace/RBAC 可先执行 `kubectl apply -k deploy/k8s/base`。
3. 准备各子项目线上 TOML，并以 ConfigMap/Secret 或只读文件方式挂载到 Pod。
   当前 manifests 引用这些集群内资源：
   - `harbor-control-plane-config` -> `/config/control-plane.toml`
   - `synthetic-data-platform-config` -> `/config/platform.toml`
   - `harbor-runner-config` -> `/config/runner.toml`
   - `harbor-tke-config` -> `/config/tke.toml`
   - `harbor-runner-kubeconfig` -> `/config/kubeconfig`
   - `harbor-runner-agent-env` -> optional model env secret
4. 用 production overlay 跑静态 preflight：
   `HARBOR_K8S_KUSTOMIZE_DIR=/path/to/production/overlay deploy/k8s/scripts/tke-preflight.sh --static-only`。
5. 创建 ConfigMaps、Secrets、TKE namespace、RBAC、image pull secret 后，跑集群
   preflight：
   `HARBOR_K8S_KUSTOMIZE_DIR=/path/to/production/overlay deploy/k8s/scripts/tke-preflight.sh --cluster`。
6. 部署 `harbor-api`。
7. 检查 `harbor-api /ready`，并确认 MySQL `alembic_version` 到 head。
8. 部署 `synthetic-data-platform` API 和 Web。
9. 检查 synthetic API `/health` 和 Web 首屏。
10. 部署 `harbor-runner` Pods。
11. 检查 `GET /runners?stale_after_sec=60`，确认 runner online，capabilities
   包含 `tke` 和 `cos-input`。
12. 上传一个小 Harbor dataset 到 COS。
13. 创建 synthetic task，runtime 选择 `tke`。
14. 等待 job 成功，验证 input materialization、artifact 上传、trajectory、
    OpenAI messages trajectory、sample ingest、result dataset publish/download。

## 冒烟验收

线上冒烟至少通过以下检查：

```text
harbor-api health: succeeded
harbor-api readiness: succeeded
synthetic API health: succeeded
frontend reachable: succeeded
MySQL alembic head: 0007_idempotency_tenant_scope
runner online: >= 1
runner providers: contains tke
runner features: contains cos-input
dataset upload to COS: succeeded
input_state: succeeded
job state: succeeded
trial count: >= 1
artifact count: >= 1
artifact storage_type: cos
trajectory artifact: exists
openai_messages trajectory artifact: exists
artifact download: non-empty
sample ingest: >= 1
result dataset publish: succeeded
JSONL / JSON download: non-empty
```

本地脚本 `deploy/docker-compose/scripts/synthetic-cos-tke-e2e.sh` 已覆盖同一条
逻辑链路。线上可以复用它的请求顺序，但地址、认证、网络入口和密钥加载方式
要替换为生产环境配置。

## 回滚策略

服务回滚：

1. 先把 `harbor-runner` 副本数降到 0，避免继续 claim 新任务。
2. 回滚 `synthetic-data-platform` Web/API 镜像。
3. 回滚 `harbor-api` 镜像。
4. 恢复 `harbor-runner` 副本数。

任务处理：

- 已经 running 的 agent-runtime Pod 可能继续运行或被 runner 终止，取决于 runner
  是否仍在心跳和轮询 cancel/control。
- queued job 不会被 RabbitMQ 状态单独决定；恢复后 runner 会重新通过 MySQL claim。
- artifact retry 不会重跑 harbor-runtime，只补传/登记已有本地 artifact。

数据库回滚：

- 当前 migration 以向前升级为主，不承诺自动 downgrade。
- TencentDB 上线前必须有备份或快照。
- 如果 migration 后需要回滚版本，优先恢复数据库备份，再回滚服务镜像。

COS 回滚：

- 不删除已上传对象。
- MySQL artifact rows 是索引源；如需废弃异常结果，应通过业务状态或后续清理任务处理。

## 当前限制

- 当前提供基础 Deployment/Service manifests；Ingress、HPA、PDB、NetworkPolicy
  仍待补充。
- COS credential、RabbitMQ URL、MySQL URL、API token 和 tenant ID 的 env/K8s
  Secret 引用已补齐。
- 已有最小服务间 Bearer token + tenant header + token scope gate。
  `harbor-api` 可将 synthetic 平台 token 限制为 `read/write`，将 runner token
  配成 `read/write/internal`；cancel/retry/artifact retry 的 idempotency
  persistence 已按 tenant 隔离。对终端用户开放前仍需补完整登录、细粒度 RBAC
  和审计。
- TKE provider 当前主要使用 kubeconfig 配置，in-cluster ServiceAccount 默认发现是后续优化。
- Compose 脚本是本地验证工具；线上可以复用流程，不应直接依赖本地端口假设。

## Phase 10 开发拆分

| 里程碑 | 内容 | 验收 |
| --- | --- | --- |
| M33 | 生产配置模板 | 已完成：三个子项目各有不含真实 secret 的 `.example.toml` |
| M34 | TKE namespace/RBAC manifests | 已完成：`deploy/k8s/base` 渲染通过，runner ServiceAccount 具备最小 Pod/exec/log 权限 |
| M35 | 服务 Deployment/Service manifests | 已完成：harbor-api、synthetic API/Web、runner manifests 通过 kustomize 和 client dry-run |
| M36 | TencentDB migration gate | 已完成：启动自动 migration，`/ready` 校验 head version，失败会阻止服务就绪 |
| M37 | TDMQ RabbitMQ smoke | 已完成本地 RabbitMQ 兼容 smoke：`rabbitmq-claim-smoke.sh` 通过；真实 TDMQ 复用同脚本和线上配置 |
| M38 | COS dataset/artifact smoke | 已完成本地真实 COS/TKE smoke：dataset `cos://`、materialized inputs、input-manifest、COS artifacts、artifact download、publish/download 全部通过；生产复用同脚本和线上配置 |
| M39 | 生产 E2E 脚本 | 已完成：`synthetic-cos-tke-e2e.sh` 支持生产 base URL、runtime、dataset、timeout、统一或分服务 auth header/bearer token |
| M40 | 安全加固 | 已完成：COS credential、RabbitMQ URL、MySQL URL、API token、tenant ID 的 env/K8s Secret 引用；harbor-api/synthetic API 支持 Bearer token + tenant header；harbor-api 支持 `read/write/internal` token scopes；runner 和 synthetic 出站 harbor-api client 会携带对应 header；cancel/retry/artifact retry 的 idempotency persistence 已按 tenant 隔离。剩余：完整用户登录、细粒度 RBAC、审计 |
