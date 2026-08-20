# Harbor Platform 研发计划

## 目标

以 `harbor/` 现有执行能力为基础，交付一个可分布式运行 Harbor job 的平台：

```text
harbor-control-plane -> MySQL -> RabbitMQ -> harbor-runner -> harbor run -> Docker/AGS/TKE
```

第一阶段目标不是完整合成数据平台，而是先让 Harbor job 能被 API 提交、被 runner 消费、被 MySQL 查询状态，并能用本地 Compose 控制面加宿主机 runner 跑通。

## 排期假设

- 计划起点：2026-08-14。
- 人力假设：1 到 2 名平台后端研发，必要时 1 名同学协助云资源和测试数据集验证。
- 优先级：先打通 runner 边界，再接 MySQL/RabbitMQ，最后做合成数据平台。
- Harbor 子模块改动必须遵守 `docs/runbooks/harbor-fork-submodule-workflow.md`：先在 `harbor/` 内提交并推送，再更新外层 submodule pointer。

## MVP 定义

MVP 完成时必须满足：

- 可以通过 `POST /jobs` 提交一个 Harbor `JobConfig`。
- `harbor-control-plane` 将 job 写入 MySQL 并发布 RabbitMQ 消息。
- 两个 `harbor-runner` 实例订阅同一 RabbitMQ queue，只有一个 runner 成功拿到 job lease。
- runner 使用现有 `harbor run` 能力运行 Docker/AGS/TKE job。
- runner 周期性把 job/trial progress 写入 MySQL。
- `GET /jobs/{job_id}` 能查询 queued/running/succeeded/failed/cancelled 状态。
- `POST /jobs/{job_id}/cancel` 能取消 queued 或 running job。
- Docker Compose 能一键启动 MySQL、RabbitMQ、harbor-control-plane；runner 从 `harbor/` 子项目在宿主机启动。

## 不在 MVP 范围

- 合成数据平台的业务 UI 和样本审核流。
- COS/object storage 正式产物归档。
- 多租户、权限、配额和计费。
- Harbor trial 调度器重写。
- RabbitMQ 作为状态源。状态只以 MySQL 为准。

## 里程碑总览

| 里程碑 | 时间盒 | 目标 | 主要产物 |
| --- | --- | --- | --- |
| M0 | 2 天 | 规格冻结 | 架构方案、研发计划、contracts 草案 |
| M1 | 1 周 | runner run-once | `harbor runner run-once`、进程监管、result 扫描 |
| M2 | 1 周 | runner daemon | 本地并发、快照、取消、优雅退出 |
| M3 | 1 到 1.5 周 | harbor-control-plane MVP | FastAPI、MySQL migration、jobs/runners API |
| M4 | 1.5 到 2 周 | MySQL/RabbitMQ 集成 | lease、heartbeat、consumer、状态写回 |
| M5 | 1 周 | Compose 联调 | 本地分布式环境、双 runner 验证 |
| M6 | 1 周 | 日志和产物 PoC | runner-local artifact proxy、artifact manifest |
| M7 | 2 周 | synthetic platform PoC | 合成任务到 Harbor job 的最小闭环 |
| M8 | 2 周以上 | 云部署加固 | TencentDB、TDMQ for RabbitMQ、TKE runner、COS |

M0 到 M5 是第一批必须交付内容。M6 到 M8 可以在 MVP 稳定后排入下一轮。

## M0: 规格冻结

时间盒：2026-08-14 起 2 天。

任务：

- 评审 `docs/architecture/harbor-platform-development-plan.md`。
- 确认 job/trial/runner 状态枚举。
- 确认 `JobConfig` 是 API 和 runner 的执行契约。
- 确认 MySQL schema 初稿。
- 确认 RabbitMQ queue、routing key、message body。
- 确认取消和 lease 语义。

交付物：

- `harbor-service-contracts/` 的最小 package skeleton。
- 状态枚举和消息 schema。
- 状态转换单测。
- JSON round-trip 单测。

验收：

- contracts 不依赖 synthetic data 平台。
- 状态枚举能覆盖 queued、leased、running、succeeded、failed、cancelled、timed_out。
- RabbitMQ message 只包含 job_id、action 和最小 routing metadata；action
  默认 `run`，artifact retry 唤醒使用 `artifact-retry`。

## M1: Harbor Runner Run-Once

时间盒：1 周。

目标：

```bash
uv run harbor runner run-once --job-config /path/job.json
```

任务：

- 在 `harbor/src/harbor/runner/` 新增 runner 内核模块。
- 在 `harbor/src/harbor/cli/runner.py` 新增 Typer 子命令。
- 支持加载 Harbor `JobConfig` JSON/TOML。
- 强制设置 `job_name = job_id`。
- 支持设置 runner-local `jobs_dir`。
- 用 subprocess 启动 `harbor job start --config <resolved-config>`。
- 记录 pid、command、started_at、exit_code。
- 轮询 `jobs/<job_id>/result.json` 并生成 runner snapshot。
- 支持本地取消，终止 subprocess group。

建议模块：

```text
harbor/src/harbor/runner/config.py
harbor/src/harbor/runner/process.py
harbor/src/harbor/runner/snapshot.py
harbor/src/harbor/runner/cancel.py
```

测试：

```bash
cd harbor
uv run pytest tests/unit/runner -q
uv run harbor job start --config <fixture> --print-config
uv run harbor runner run-once --job-config <fixture>
```

验收：

- fake subprocess 测试能覆盖 running、exit 0、exit nonzero、cancel。
- result.json 缺失时状态保持 running 或 failed，不崩溃。
- Harbor 现有 AGS/TKE 单测仍通过。

## M2: Harbor Runner Daemon

时间盒：1 周。

目标：

```bash
uv run harbor runner start --config runner.toml
```

任务：

- 新增 runner daemon 配置：
  - `runner_id`
  - `jobs_dir`
  - `max_running_jobs`
  - `poll_interval_sec`
  - `runner_internal_url`
- 实现本地 job queue。
- 并发运行多个 Harbor job，受 `max_running_jobs` 控制。
- 周期性生成所有 active job snapshots。
- 支持 graceful shutdown：
  - 停止接收新 job。
  - 等待 running job 完成或按配置取消。
- 支持 draining。

测试：

- 两个 fake job 同时运行，第三个等待。
- 取消一个 job 不影响其他 job。
- runner 重启后能读取已有 job 目录并生成 terminal snapshot。

验收：

- runner 进程不因单个 job 失败退出。
- `runner_concurrency` 和 Harbor `n_concurrent_trials` 明确分离。
- 本阶段仍不引入 MySQL/RabbitMQ。

## M3: Harbor control-plane MVP

时间盒：1 到 1.5 周。

目标：

创建 `harbor-control-plane/` 的最小 FastAPI 服务。

任务：

- 初始化 Python project。
- 新增配置加载。
- 新增 MySQL repository。
- 新增 Alembic migrations。
- 新增 RabbitMQ producer port 和 in-memory fake。
- 实现 endpoints：
  - `POST /jobs`
  - `GET /jobs/{job_id}`
  - `GET /jobs/{job_id}/trials`
  - `POST /jobs/{job_id}/cancel`
  - `GET /runners`
- `POST /jobs` 校验并保存 resolved `JobConfig`。
- `POST /jobs` 写入 DB 后再 publish RabbitMQ。
- API 不直接执行 Harbor job。

测试：

- repository 单测。
- API route 单测。
- invalid JobConfig 不写 DB、不发消息。
- DB 写入成功但 publish 失败时状态可恢复或有明确错误事件。

验收：

- OpenAPI 能描述初始接口。
- MySQL 是 job status 唯一读取来源。
- API 不导入 runner 内部模块。

## M4: Runner MySQL 和 RabbitMQ 集成

时间盒：1.5 到 2 周。

目标：

runner 从 RabbitMQ 收消息，通过 MySQL lease 抢占 job，运行 Harbor，并写回状态。

任务：

- runner 注册到 MySQL。
- runner heartbeat。
- RabbitMQ consumer 接入 `harbor_jobs` queue。
- 实现原子 lease：

```sql
UPDATE jobs
SET state = 'leased',
    runner_id = :runner_id,
    lease_id = :lease_id,
    lease_expires_at = :lease_expires_at,
    updated_at = NOW()
WHERE id = :job_id
  AND state = 'queued'
  AND cancel_requested_at IS NULL;
```

- leased 后启动 local subprocess。
- claim 匹配支持 `queue`、`priority`、指定 `job_id` 和 per-queue quota；
  高优先级先被 claim，同队列同优先级保持 FIFO。
- running 时续租。
- 周期性解析 `result.json` 和 trial results，写入 `jobs`、`trials`、`job_events`。
- runner 观察 `cancel_requested_at` 并取消 subprocess。
- terminal 后 ack RabbitMQ message。

测试：

- 同一 job 被两个 runner 消费时只有一个 lease winner。
- 已完成 job 的 redelivery 会 ack 并忽略。
- runner crash before start 后 lease 过期，job 回到 queued。
- running job cancellation 能落到 cancelled。

验收：

- RabbitMQ redelivery 不导致重复执行。
- MySQL 中能看到完整 job lifecycle events。
- runner offline heartbeat 能被 API 识别。

## M5: Docker Compose 分布式联调

时间盒：1 周。

目标：

本地一键启动完整 MVP。

任务：

- 新增 `deploy/docker-compose/compose.dev.yml`。
- 服务包含：
  - MySQL
  - RabbitMQ
  - optional RabbitMQ management UI
  - optional RabbitMQ dashboard
  - harbor-control-plane
  - synthetic-data-platform
- 准备本地 smoke JobConfig。
- 准备 AGS/TKE 可选 smoke JobConfig。
- 编写 runbook。

验收：

- `docker compose up` 后 API healthcheck 通过。
- `POST /jobs` 后 job 能被一个 runner 执行。
- 宿主机 runner 在线；需要验证分布式 lease 时，可用不同 `HARBOR_RUNNER_ID` 启动多个 runner 进程。
- 并发提交多个 job 时能分散到不同 runner。
- `GET /jobs/{job_id}` 能看到最终 succeeded/failed。
- cancel endpoint 对 queued/running job 生效。

## M6: 日志和产物 PoC

时间盒：1 周。

任务：

- runner 生成 job-level artifact collection manifest：`artifacts/runner-manifest.json`。
- MySQL 写入 artifact metadata。
- API 增加 artifact list endpoint。
- API 支持通过 `runner_internal_url` 代理读取 runner-local 文件。

验收：

- API 能读取：
  - job-level `artifacts/runner-manifest.json`
  - job `config.json`
  - job `result.json`
  - trial `result.json`
  - `exception.txt`
  - agent logs
  - verifier logs

## M7: Synthetic Data Platform PoC

时间盒：2 周。

任务：

- 创建 `synthetic-data-platform/` 最小服务。
- 实现 synthetic task CRUD。
- 生成 Harbor `JobConfig`。
- 调用 `harbor-control-plane POST /jobs`。
- 保存 `synthetic_task_id -> harbor_job_id`。
- 查询 Harbor job status。
- 从 Harbor artifacts 读取样本结果。

验收：

- synthetic 平台不导入 Harbor runner 内部模块。
- synthetic 平台不读取 runner-local `jobs/`。
- 所有 Harbor 交互走 HTTP API。

## M8: 腾讯云部署加固

时间盒：2 周以上。

任务：

- MySQL 替换为 TencentDB。
- RabbitMQ 替换为 TDMQ for RabbitMQ。
- harbor-control-plane 部署到 TKE。
- harbor-runner 以 TKE Deployment 运行。
- 配置 AGS/TKE provider secrets。
- artifact storage 从 runner-local 切到 COS。
- 增加监控、日志、告警。

验收：

- 云上至少两个 runner pod 同时在线。
- API active/standby 可用。
- AGS/TKE provider job 能从云上 runner 执行。
- runner pod 重启不造成重复执行已完成 job。

## 当前实现状态（2026-08-14）

已落地：

- M1/M2 runner 基础能力：`harbor runner run-once`、`harbor runner start`、并发控制、snapshot、取消和 artifact metadata 回写。
- M3/M4 控制面和调度链路：FastAPI、SQL repository、MySQL schema、RabbitMQ producer/consumer、heartbeat、lease、expired lease recovery、runner offline marking、snapshot 回写和 trial 明细同步。
- M5 本地 Compose 栈已调整为 MySQL、RabbitMQ、harbor-control-plane、synthetic-data-platform；runner 在宿主机从 `harbor/config/runner.local.toml` 启动。
- M6 artifact PoC：artifact list endpoint、受限 runner-local content proxy、runner 生成 `artifacts/runner-manifest.json`、job `config.json`/`result.json`、trial `result.json`、`exception.txt`、agent/verifier logs、Harbor artifact `manifest.json` 和 `samples*.json` 索引。
- M7 synthetic PoC：`POST /synthetic-tasks` 可直传 Harbor JobConfig，也可从 dataset/tasks/environment/agent/model 等业务字段生成 Harbor JobConfig；创建 Harbor job 后保存 `synthetic_task_id -> harbor_job_id`，支持查询 Harbor job、同步状态、通过 harbor-control-plane artifacts endpoint ingest samples。

已验证：

- `POST /synthetic-tasks` 能通过 Compose 内部 HTTP 调用 `harbor-control-plane POST /jobs`。
- `GET /synthetic-tasks/{id}/harbor-job` 能通过 harbor-control-plane 查询 Harbor job 状态。
- `POST /synthetic-tasks/{id}/sync` 能把 Harbor `failed/running/succeeded/...` 状态同步成本地 synthetic task 状态。
- 过期 `leased` job 会被重新排队，`acquire_lease` 在处理 RabbitMQ redelivery 时也会先回收过期 lease。
- 带 `trial_results` 的 runner snapshot 会同步写入 `trials` 表，`GET /jobs/{job_id}/trials` 能返回 task、agent、model、reward、exception 和 trial result JSON。
- `GET /runners` 可按 `stale_after_sec` 将超时 heartbeat 的 runner 标记为 `offline`。
- runner terminal 后会生成并回写 job-level `artifacts/runner-manifest.json`，同时把 Harbor trial artifact `manifest.json` 记为 `artifact-manifest`、把 `samples*.json` 记为 `samples`，供 synthetic 平台通过 harbor-control-plane artifacts endpoint ingest。
- `POST /synthetic-tasks/{id}/ingest-samples` 只通过 harbor-control-plane artifacts endpoint 读取样本，不读取 runner-local `jobs/`；只从 `sample`/`samples` artifact 和带 `samples` 字段的 `trial-result` 解析样本，避免把 job-level `result.json` 误入库。
- `POST /synthetic-tasks` 支持从 `dataset_path`/`dataset_name`、`tasks`、`environment`、`agent_name`、`model_name`、`n_concurrent_trials`、`artifacts` 生成 Harbor JobConfig，并保留 `harbor_job_config` 直传兼容路径。
- `docker compose -f compose.dev.yml config` 可正常渲染本地控制面栈。
- `smoke/ags-otel-bench-smoke-job.json` 已通过 JSON 和 Harbor `JobConfig` 静态校验，`harbor/generated/otel-bench-ags-smoke/go-http-tracing` 已通过 `Task.is_valid_dir` 和 `DatasetConfig.get_task_configs` 静态校验。
- `smoke/docker-touch-file-smoke-job.local.json` 已通过 JSON 和 Harbor `JobConfig` 静态校验；`harbor/generated/harbor-platform-docker-smoke/touch-file` 已通过 `Task.is_valid_dir` 和 `DatasetConfig.get_task_configs` 静态校验。
- `scripts/submit-and-wait-job.sh` 已通过 `bash -n` 和本地 fake harbor-control-plane 成功路径验证，可复用提交 Docker/AGS smoke，并断言 runner 在线数量、terminal succeeded、非空 runner assignment、trial 明细、`result` 和 `artifact-manifest` metadata；terminal 后会等待 metadata 回写，避免 artifact/trial 写入竞态。
- 旧的 runner 容器访问宿主机 Docker 验证路径已下线，当前使用宿主机 runner + 宿主机 Docker。
- 并发双 job smoke 已验证双 runner 分担：`60707c0367a54f68a72017f5b145ff42` 由 `runner-1` 执行，`3849c6f61c5a4c56a976690c196cc7af` 由 `runner-2` 执行，二者均 `succeeded` 且 trial/artifact metadata 完整。
- runner 在 RabbitMQ 本轮无消息且启用 `poll_control_plane_jobs` 时会 fallback 到控制面 queued-job polling，再由 MySQL lease 保证不会重复执行；该行为补齐了 Compose 双 runner 分担验证所需的空闲抢占能力。
- `cd harbor && uv run pytest tests/unit/runner -q` 已通过 23 个 runner 单测；`uv run ruff check src/harbor/runner tests/unit/runner` 已通过。
- `cd harbor-control-plane && uv run pytest tests -q` 已通过 32 个控制面单测；`uv run ruff check src tests` 已通过。
- 本轮复跑 `cd harbor-control-plane && uv run pytest tests -q`、`cd harbor && uv run pytest tests/unit/runner -q`、`cd synthetic-data-platform && uv run pytest tests -q` 均通过，覆盖控制面、runner、synthetic 三段当前回归。
- `cd synthetic-data-platform && uv run pytest tests -q` 已通过 8 个 synthetic 平台单测；`uv run ruff check src tests` 已通过，其中覆盖 succeeded Harbor job 通过 harbor-control-plane artifacts endpoint ingest samples 的成功路径。

仍未满足：

- AGS/TKE 真实执行仍需要明确云资源授权和凭证；M5 Docker provider 当前应通过宿主机 runner + 宿主机 Docker 重新验收。
- M6 生产化对象存储/COS 不在当前 PoC 内，后续 M8 再切换。
- Harbor 子模块改动仍需按 submodule workflow 先在 `harbor/` 内提交并推送，再更新外层 pointer。

## 关键路径

1. `harbor runner run-once`
2. runner daemon
3. MySQL schema 和 job lease
4. RabbitMQ consumer
5. Compose 双 runner 联调

其中 `run-once` 是最高风险边界。它决定 Harbor 现有 job 结果、进程生命周期、取消语义能否被稳定封装。不要在 `run-once` 稳定前同时推进完整 API 和 RabbitMQ 集成。

## 每周节奏

- 周初确定本周 milestone 和验收命令。
- 每个 milestone 拆成小 PR 或小 commit。
- Harbor 子模块 PR 和外层 submodule pointer 更新分开处理。
- 每次改 runner/provider 相关代码后运行 AGS/TKE targeted tests。
- 每周末保留一份手工联调记录，写入 `docs/runbooks/`。

## 验证命令基线

Harbor 子模块 targeted tests：

```bash
cd harbor
uv run pytest tests/unit/environments/test_ags_clients.py tests/unit/environments/test_ags.py tests/unit/environments/test_ags_config.py tests/unit/environments/test_ags_queue.py tests/unit/environments/test_tke_config.py tests/unit/environments/test_tke.py tests/unit/environments/test_environment_definition.py tests/unit/environments/test_provider_resource_capabilities.py -q
```

Runner 新增测试：

```bash
cd harbor
uv run pytest tests/unit/runner -q
```

后续 API 测试：

```bash
cd harbor-control-plane
uv run pytest -q
uv run ruff check src tests
```

Synthetic 平台测试：

```bash
cd synthetic-data-platform
uv run pytest tests -q
uv run ruff check src tests
```

## 风险和应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Harbor CLI 参数面过宽 | runner 调用复杂、复现困难 | runner 接受 resolved JobConfig，API 保存完整 JobConfig |
| result.json 写入时机不稳定 | 状态扫描误判 | snapshot parser 容忍缺失和部分字段 |
| RabbitMQ redelivery | job 重复执行 | 所有执行前必须先拿 MySQL lease |
| runner crash | job 卡在 running | lease 过期和 heartbeat offline 恢复 |
| AGS/TKE 凭据差异 | Compose smoke 不稳定 | 本地 Docker smoke 必选，AGS/TKE smoke 可选 |
| 产物仍在 runner local | API 读取受 runner 存活影响 | MVP 先 proxy，后续 M8 切 COS |
| submodule 工作流遗漏 | 外层指针和内层提交不一致 | 每个 Harbor 改动都按 runbook 双层提交 |

## 下一步执行清单

1. 按 submodule workflow 整理 Harbor 内层提交并推送，再更新外层 submodule pointer。
2. 若要扩大真实后端覆盖面，使用宿主机 runner 和 `deploy/docker-compose/smoke/ags-otel-bench-smoke-job.json`，在明确授权云资源调用后跑 AGS succeeded smoke。
3. 后续 M8 将 runner-local artifact proxy 切换到 COS/object storage，并把 MySQL/RabbitMQ 替换为云上托管服务。
