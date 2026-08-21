# Harbor Platform

Harbor Platform 是一个基于 Harbor 的后训练 Agent 轨迹数据合成平台总仓库。它不是把所有代码合并成一个单体，而是通过 git submodule 固定各组件版本，并在总仓库里维护跨组件部署、文档和端到端验证。

当前目标链路是：

```text
synthetic-data-platform
  -> harbor-control-plane
  -> MySQL + RabbitMQ
  -> harbor-runner
  -> harbor-runtime
  -> agent-runtime: Docker / TKE / AGS
  -> COS artifacts and results
```

## 组件边界

```text
harbor-platform/
  harbor/                    # Harbor fork；包含 Harbor CLI、harbor-runtime、harbor-runner、Docker/TKE/AGS runtime 适配
  harbor-control-plane/       # Harbor Control Plane；HTTP API、MySQL 状态、RabbitMQ 调度、lease、artifact 查询
  synthetic-data-platform/    # 业务平台；候选集、合成任务、任务实例、合成结果、平台设置
  harbor-service-contracts/   # 共享契约；job 状态、dispatch message、请求/响应模型
  deploy/                     # 总仓维护的本地 Docker Compose 和未来 K8s/TKE 部署编排
  docs/                       # 架构说明和 runbook
```

边界规则：

- `harbor/` 不依赖 `harbor-control-plane` 或 `synthetic-data-platform`。
- `harbor-control-plane` 不理解业务概念，只管理 Harbor job、runner、lease、artifact。
- `synthetic-data-platform` 通过 HTTP 调用 `harbor-control-plane`，不直接读 runner 本地目录，也不导入 Harbor 内部实现。
- 具体运行配置放在读取它的组件里；`deploy/` 只负责挂载和编排。
- MySQL 是 job/runner 的事实状态源；RabbitMQ 只是调度通道。
- runner 本地 `jobs/` 是缓存/暂存；生产结果应落 COS。

## 核心概念

- 候选集：提交给 Harbor 跑数的输入数据集，一般来自本地上传后落 COS。
- 合成任务定义：可重复运行的默认配置，包括候选集、runtime、agent、model、并发和默认任务选择。
- 任务实例：一次真实运行，对应一个 Harbor job。每次点击“运行实例”都会创建新实例。
- 合成结果：任务实例中审核通过的 trial 结果，主要关注 trajectory 和 `result.json`。
- harbor-runner：本机或集群内的 worker daemon，负责抢 lease、拉取输入、启动 Harbor runtime、收集 artifacts、上传 COS、上报状态。
- harbor-runtime：Harbor CLI 执行控制代码，等价于一次 `harbor run`。
- agent-runtime：真正执行任务的沙箱环境，可以是本机 Docker、TKE Pod 或 AGS sandbox。

## 本地端口

默认本地 compose 暴露：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| Synthetic Web | `http://127.0.0.1:8080` | 中文前端控制台 |
| Synthetic API | `http://127.0.0.1:8081` | 业务平台 API |
| Harbor Control Plane | `http://127.0.0.1:18080` | Harbor job/runner/artifact API |
| MySQL | `127.0.0.1:3306` | durable state |
| RabbitMQ | `127.0.0.1:5672` | dispatch channel |
| RabbitMQ Management | `http://127.0.0.1:15672` | 队列管理页 |

公网访问时把 `127.0.0.1` 替换成机器公网 IP。

## 首次准备

```bash
git submodule update --init --recursive
```

安装 Harbor 依赖：

```bash
cd harbor
uv sync --all-extras --dev
```

如果要跑 AGS/TKE，需要额外确认：

- `~/.config/harbor/ags.toml` 或 `HARBOR_AGS_CONFIG` 指向 AGS 配置。
- `~/.config/harbor/tke.toml` 或 `HARBOR_TKE_CONFIG` 指向 TKE 配置。
- AGS/TKE/OpenAI/TCR 等凭据已在启动 runner 的 shell 环境里生效。
- 如果 runner 通过 tmux 启动，要在对应 tmux pane 里 `source ~/.bashrc` 后再启动 runner，或把变量同步到 tmux server。

## 配置文件

当前本地配置入口：

```text
harbor/config/runner.local.toml
harbor-control-plane/config/control-plane.local.toml
synthetic-data-platform/config/platform.local.toml
```

职责划分：

- `harbor/config/runner.local.toml`：runner id、并发、control-plane 地址、RabbitMQ、本地 jobs 目录、输入下载、artifact 上传、runner 能力声明。
- `harbor-control-plane/config/control-plane.local.toml`：dispatch backend、RabbitMQ、artifact 查询/签名 URL、COS artifact 访问配置。
- `synthetic-data-platform/config/platform.local.toml`：业务平台 API、候选集上传 COS、结果导出 COS、export worker。

当前开发环境可以直接在 TOML 里配置 COS 字段；不要把真实密钥提交到公共仓库。后续生产化应切换到 env/K8s Secret 引用。

## 本地部署

启动或重建控制面和平台服务：

```bash
docker compose -f deploy/docker-compose/compose.dev.yml up -d --build
```

查看状态：

```bash
docker compose -f deploy/docker-compose/compose.dev.yml ps
curl -fsS http://127.0.0.1:18080/health
curl -fsS http://127.0.0.1:8081/health
curl -fsSI http://127.0.0.1:8080
```

停止服务但保留数据：

```bash
docker compose -f deploy/docker-compose/compose.dev.yml down
```

不要随手加 `-v`，否则会删除 MySQL/RabbitMQ volume。

## 启动本机 Runner

本机作为 runner/runtime host 时，runner 建议从 `harbor/` 子模块启动：

```bash
cd /home/ubuntu/project/harbor-platform/harbor
source ~/.bashrc
uv run harbor runner start --config config/runner.local.toml --keep-alive
```

后台 tmux 启动：

```bash
tmux new-session -d -s harbor-runner-local \
  "bash -lc 'source ~/.bashrc; cd /home/ubuntu/project/harbor-platform/harbor; exec uv run harbor runner start --config config/runner.local.toml --keep-alive >> /home/ubuntu/project/harbor-platform/.local/harbor-runner.local.log 2>&1'"
```

查看 runner 状态：

```bash
curl -fsS 'http://127.0.0.1:18080/runners?stale_after_sec=60'
```

正常情况下应该看到类似：

```json
[
  {
    "id": "local-runner-1",
    "state": "online",
    "running_jobs": 0,
    "capabilities": {
      "features": ["cos-input"],
      "providers": ["docker", "tke", "ags"]
    }
  }
]
```

## 本机 Runtime 与并发

本机 runner 会同时启动多个 Harbor runtime 子进程。每个 job 等价于一次独立的 `harbor run`。

```text
local harbor-runner
  ├─ harbor run job-A -> Docker/TKE/AGS
  ├─ harbor run job-B -> Docker/TKE/AGS
  └─ harbor run job-C -> Docker/TKE/AGS
```

并发由两层控制：

- job 级并发：`harbor/config/runner.local.toml` 的 `max_running_jobs`。
- trial 级并发：任务定义或运行实例里的 `n_concurrent_trials`。

如果本机跑 Docker runtime，实际瓶颈是本机 CPU、内存、磁盘、Docker daemon 和镜像拉取速度。建议先用 2 到 4 个并发验证稳定，再提高到更大并发。

## 端到端人工测试流程

1. 打开前端：`http://127.0.0.1:8080`。
2. 进入“候选集管理”，上传候选集压缩包。
3. 进入“合成任务管理”，创建任务定义：
   - 选择候选集版本。
   - 选择 Agent Runtime：`docker`、`tke` 或 `ags`。
   - 填写合法 Agent 名，例如 `codex`。
   - 填写模型名。
   - 选择数据集中的具体任务，默认全选。
4. 进入任务定义详情，点击“运行实例”。
5. 在运行实例页观察：
   - 任务状态
   - Harbor 状态
   - 失败类型
   - runtime
   - 自动刷新
   - logs
   - trials
6. 实例完成后在 trial 区域查看 `trajectory` 和 `result.json`。
7. 对有价值的 trial 点击“通过”。
8. 进入“合成结果管理”查询已通过结果。

## 常用 API 检查

Control Plane：

```bash
curl -fsS http://127.0.0.1:18080/health
curl -fsS 'http://127.0.0.1:18080/runners?stale_after_sec=60'
curl -fsS http://127.0.0.1:18080/jobs/<job_id>
```

Synthetic API：

```bash
curl -fsS http://127.0.0.1:8081/health
curl -fsS http://127.0.0.1:8081/datasets
curl -fsS http://127.0.0.1:8081/task-definitions
curl -fsS http://127.0.0.1:8081/synthetic-tasks
```

## 状态含义

任务实例有两类状态需要同时看：

- 平台任务状态：synthetic-data-platform 对业务实例的状态归纳。
- Harbor 状态：control-plane 中 Harbor job 的真实执行状态。

常见值：

| 状态 | 含义 |
| --- | --- |
| `submitted` / `queued` | 已提交，等待 runner 领取 |
| `running` | runner 已领取并正在执行 |
| `succeeded` | Harbor job 正常结束 |
| `failed` | Harbor job 执行失败 |
| `cancelled` | 已取消 |
| `timed_out` | 超时 |
| `published` | 业务侧已发布为结果数据 |

失败类型示例：

| 失败类型 | 含义 |
| --- | --- |
| `runner_lost` | runner 心跳丢失且 job lease 过期，通常是 runner 停止或假死 |
| `input_materialization_failed` | COS 输入下载或解压失败 |
| `dispatch_failed` | 调度消息发布失败 |
| 空 | Harbor runtime 自身失败，需看 runner log、trial log 或 `result.json` |

注意区分：

- 运行失败：agent/runtime 抛异常、环境配置错误、runner 丢失、没有生成结果文件。
- 验证未通过：trial 正常跑完，但 reward 为 0 或 verifier 判定失败。

## 常见问题

### runner 在线但 AGS 任务失败

检查启动 runner 的进程环境，不只看 `.bashrc` 是否写了变量：

```bash
printenv AGS_SECRET_ID
printenv AGS_SECRET_KEY
printenv AGS_E2B_API_KEY
printenv AGS_E2B_DOMAIN
```

如果 runner 在 tmux 里启动，需要在那个 tmux pane 里执行：

```bash
source ~/.bashrc
```

再启动 runner。

### 任务一直排队

检查 runner 是否在线：

```bash
curl -fsS 'http://127.0.0.1:18080/runners?stale_after_sec=60'
```

如果没有 online runner，启动本机 runner。还要确认 runner capabilities 包含任务需要的 provider 和 feature。

### agent 名写错导致失败

Harbor 不会接受不存在的 agent。比如 `coedx` 是错的，应该是 `codex`。创建任务定义或运行实例时应使用 Harbor 支持的 agent 名。

### 结果为空

“合成结果管理”只展示在任务实例中审核通过的 trial。刚跑完的 trial 需要先到任务实例详情里查看 trajectory/result，并点击“通过”，才会出现在合成结果管理里。

### `result.json` 缺失

如果 job 显示 `Missing Harbor result file .../result.json`，说明 runner 领到了任务，但 Harbor runtime 没产出最终结果。常见原因包括 runtime 初始化失败、agent 名非法、环境变量缺失、沙箱创建失败等。看 runner log 和任务实例日志定位。

## 自动化验证

后端：

```bash
cd synthetic-data-platform
uv run pytest tests/test_app.py -q
```

前端：

```bash
cd synthetic-data-platform/web
npm run build
npm run test:ui
```

Harbor AGS/TKE targeted tests：

```bash
cd harbor
uv run pytest \
  tests/unit/environments/test_ags_clients.py \
  tests/unit/environments/test_ags.py \
  tests/unit/environments/test_ags_config.py \
  tests/unit/environments/test_ags_queue.py \
  tests/unit/environments/test_tke_config.py \
  tests/unit/environments/test_tke.py \
  tests/unit/environments/test_environment_definition.py \
  tests/unit/environments/test_provider_resource_capabilities.py \
  -q
```

## 参考文档

- `AGENTS.md`：仓库协作和边界规则。
- `docs/architecture/harbor-platform-architecture.md`：完整架构说明。
- `docs/runbooks/harbor-fork-submodule-workflow.md`：Harbor fork/submodule 工作流。
- `docs/runbooks/development-roadmap.md`：阶段路线图和当前能力。
- `harbor/readme-ags.md`：AGS runtime 接入说明。
- `harbor/readme-tke.md`：TKE runtime 接入说明。
