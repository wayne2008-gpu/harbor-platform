# HANDOFF

更新时间：2026-08-20

## 当前任务

当前项目目标是把 Harbor 从单机 CLI/本地执行框架，扩展成面向“后训练 agent 轨迹数据合成平台”的集群化运行底座，并在 `synthetic-data-platform` 上提供数据集管理、任务创建、运行状态、结果/轨迹查询、审核与发布入口。

最近一轮重点在确认和打通：

- `synthetic-data-platform` 前端创建数据集、创建任务。
- 数据集上传到 COS，任务运行前由 `harbor-runner` 下载到本地。
- `harbor-runner` 将输入数据集物化成本地路径后交给 `harbor-runtime` 执行。
- 结果产物上传 COS，并通过 control-plane / synthetic-data-platform 查询。
- 前端页面中文化，访问端口调整为 `8080`。

2026-08-20 新的第一版产品收敛目标：

- 顶级模块只保留四个：候选集管理、合成任务管理、合成结果管理、平台设置。
- 去掉顶级“工作台”“独立评审中心”“审计入口”“平台样本”“结果数据集”等第一版非核心概念。
- 日志归属任务实例，用于排障。
- 合成结果只保留 `trajectory` 和 `result.json`。
- `trajectory` 默认展示 OpenAI messages schema；Harbor 原始 trajectory 仅作为辅助排障入口。
- 评审简化为对单条 trajectory 做“通过/不通过”标记。

2026-08-20 最新验证结论：

- `docker compose -f deploy/docker-compose/compose.dev.yml up -d --build` 已能启动默认本地栈：
  - MySQL `3306`
  - RabbitMQ `5672/15672`
  - harbor-control-plane `18080`
  - synthetic-data-platform API `8081`
  - synthetic-data-platform web `8080`
  - synthetic-result-export-worker
- `compose.dev.yml` 已直接挂载 `synthetic-data-platform/config/platform.local.toml`，默认本地栈不再依赖额外 synthetic upload override 才能上传 COS dataset。
- `synthetic-data-platform/config/platform.local.toml` 已使用 `harbor_control_plane_base_url`，不再使用旧 `harbor_api_base_url` 命名。
- 宿主机 runner 已用 `harbor/config/runner.local.toml` 启动，`/runners?stale_after_sec=60` 返回 `local-runner-1` online，capabilities 包含 `docker`、`tke`、`ags`。
- 当前 runner 常驻在 `tmux` session `harbor-runner-local`：
  - 查看：`tmux attach -t harbor-runner-local`
  - 停止：`tmux kill-session -t harbor-runner-local`
  - 重启：`cd /home/ubuntu/project/harbor-platform/harbor && HARBOR_TKE_CONFIG=/home/ubuntu/.config/harbor/tke.toml uv run harbor runner start --config config/runner.local.toml --keep-alive`
- 完整 COS/TKE E2E 已通过：
  - dataset archive：`/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags`
  - task：`go-http-tracing`
  - runtime：`tke`
  - uploaded dataset id：`f5090befe9044f229852d300d67d49ec`
  - synthetic task id：`2ca836d50bb44641a4c4da6bdf0f8709`
  - harbor job id：`282182c916494674a4255417665dd050`
  - artifacts：155 个 COS artifact
  - trajectory artifacts：2 个，其中 OpenAI messages schema 1 个
  - input manifest：1 个
  - result export：COS 导出和下载校验通过
  - frontend live workflow：新版四模块页面通过
- 可直接打开：
  - `http://localhost:8080/candidate-sets/f5090befe9044f229852d300d67d49ec`
  - `http://localhost:8080/synthesis-tasks/2ca836d50bb44641a4c4da6bdf0f8709`
  - `http://localhost:8080/synthesis-results/2ca836d50bb44641a4c4da6bdf0f8709/34c9fb50-f6ad-480d-843f-5514ba4f4bb4`
- 本轮继续收口：
  - `docs/runbooks/synthetic-frontend-local-e2e.md` 已改成默认使用 `compose.dev.yml`，不再要求 `compose.synthetic-upload.yml`。
  - `compose.synthetic-upload.yml` 已标注为 legacy compatibility override。
  - runbook 的第一版手工验收改为候选集管理、合成任务管理、合成结果管理、平台设置四模块。
  - `synthetic-data-platform/web/src/main.tsx` 中旧 Local E2E 辅助文案已改成 trajectory/result.json 主路径，publish/result dataset 只保留 legacy 语义。
  - 复跑 `npm run build && npm run test:ui` 通过。
  - 复跑 `docker compose -f deploy/docker-compose/compose.dev.yml config` 和叠加 legacy override 的 compose config 均通过。
  - 复跑 `cd harbor && uv run pytest tests/unit/runner -q`，80 passed。
  - 复跑 `cd harbor-control-plane && uv run pytest tests -q`，97 passed。
  - 复跑 `cd synthetic-data-platform && uv run pytest tests/test_app.py tests/test_sql_repository.py -q`，134 passed。
  - `docs/runbooks/cos-input-materialization-local-e2e.md` 已同步为默认 `compose.dev.yml` 启动，并说明 `compose.synthetic-upload.yml` 只是兼容旧命令。
  - `docs/runbooks/compose-real-job-backends.md` 的 synthetic 前端验证入口已改成候选集、任务实例日志、trajectory/result.json 和 COS artifact 下载口径。
  - 新增 `docs/runbooks/first-version-acceptance.md`，固化第一版验收范围、真实 E2E 证据、自动化验证命令和剩余非阻塞项。
  - 新增 `docs/runbooks/first-version-publish-plan.md`，记录四个仓库的提交顺序、建议提交信息、验证命令和提交前需要用户确认的范围。

## 当前仓库边界

当前 super repo 是 `/home/ubuntu/project/harbor-platform`，下面按组件拆分为子仓库/子模块：

- `harbor/`：Harbor fork。包含 Harbor core、`harbor-runtime`、`harbor-runner`、AGS/TKE/Docker 等运行适配能力。
- `harbor-control-plane/`：控制面。包含对外任务 API、DB migration、lease/claim、RabbitMQ dispatch、artifact 查询、输入数据集状态记录。
- `synthetic-data-platform/`：业务平台。包含数据集管理、任务管理、结果数据集、前端控制台。应通过 HTTP 调用 control-plane，不直接 import Harbor 内部实现。
- `harbor-service-contracts/`：共享契约。包含 job state、input dataset、materialized input、artifact、dispatch message 等模型。
- `deploy/`：super repo 持有本地 compose / K8s/TKE 部署编排，只引用或挂载各组件自己的配置。
- `docs/`：super repo 持有架构设计、runbook、研发计划。

原则：组件代码和组件默认配置放在各自子仓库；super repo 不承载具体业务配置能力，只负责组合部署。

## 已完成内容

### 架构与命名

- 明确 `harbor-runtime` 指 Harbor CLI/执行控制代码。
- 明确 `agent-runtime` 指真正执行 agent 任务的环境容器/沙箱，可以是 Docker、AGS、TKE 等。
- 明确 `control-plane` 是把 Harbor 从本地运行变为集群服务的控制层，负责任务状态、lease、调度、输入物化状态、artifact 元数据。
- 方向上已确认 `harbor-api` 不再作为独立概念，应收敛为 `harbor-control-plane`。

### 消息队列

- 已从 RocketMQ 方案转向 RabbitMQ 作为默认 dispatch channel。
- RabbitMQ 只做任务唤醒/分发，不作为任务状态 source of truth。
- MySQL 仍然是 control-plane job/runner/artifact 的持久化状态源。
- 保留 lease/claim 机制，避免分布式 runner 重复执行同一个 job。

### COS 结果产物

- 目标策略已调整为默认上传全部符合收集规则的生成物。
- durable artifact 应存 COS，DB 中记录 `storage_type`、`storage_key`、`relative_path`、`kind`、`schema`、`content_type`、`size_bytes` 等元数据。
- runner-local `jobs/` 只作为 staging/cache，不是生产持久化来源。

### COS 输入数据集

- `synthetic-data-platform` 支持注册或上传数据集。
- 上传数据集时，平台会把 tar.gz archive 上传到 COS，并保存 dataset record：
  - `id`
  - `name`
  - `version`
  - `uri`
  - `format`
  - `checksum_sha256`
  - `size_bytes`
  - `task_names`
  - `metadata`
- 创建任务时，前端传的是 `dataset_id`。
- 后端用 `dataset_id` 查出 dataset record，并转换成 control-plane 的 `input_datasets`。
- control-plane 创建 job 时保存 `job_config` 和 `input_datasets`。
- runner claim job 后，从 job status 读取 `input_datasets`，下载 COS archive，解压到：
  - `jobs/<job_id>/inputs/archives/<target>.tar.gz`
  - `jobs/<job_id>/inputs/datasets/<target>`
- runner 再把 Harbor job config 重写为 Harbor runtime 能直接读取的本地路径：

```json
{
  "datasets": [
    {
      "path": "/abs/path/jobs/<job_id>/inputs/datasets/<target>",
      "task_names": ["..."],
      "n_tasks": 1
    }
  ]
}
```

结论：Harbor runtime 不直接认识 synthetic-data-platform 的 `dataset_id`，它最终看到的是 runner 物化后的本地 `datasets[].path`。

### 任务创建参数

当前 `synthetic-data-platform` 前端创建任务页支持常用 Harbor runtime 参数：

- runtime：映射到 `job_config.environment.type`，例如 `tke`、`ags`、`docker`。
- agent：映射到 `job_config.agents[0].name`。
- model：映射到 `job_config.agents[0].model_name`。
- concurrency：映射到 `job_config.n_concurrent_trials`。
- task names / n_tasks：用于筛选数据集中的任务。

后端 API 还支持 `harbor_job_config` 直通字段。如果传了 `harbor_job_config`，后端会直接提交该 dict，不走简化字段组装。

当前前端还没有产品化高级 JSON 配置编辑器，所以更复杂的 Harbor 参数暂时要通过 API 调用传。

### 结果、轨迹和样本

- control-plane 支持 job、trial、artifact 查询。
- synthetic-data-platform 支持从 control-plane 查询任务、trial、artifact、trajectory。
- 已支持 trajectory 的 `openai_messages` schema 查询/同步入口。
- 样本 ingestion 当前会从这些 artifact 中抽取：
  - `kind=sample`
  - `kind=samples`
  - `kind=trial-result`
  - `kind=trajectory && schema=openai_messages`
- 这里的 sample 是“进入结果数据集/训练数据集的业务记录”，不是 Harbor 原始轨迹本身。

### 前端

- `synthetic-data-platform/web` 已完成中文化处理。
- 前端访问端口调整为 `8080`。
- API 兼容字段已从旧的 `harbor_api` 兼容到 `control_plane`。
- 已执行过：
  - `npm run build`
  - `npm run test:ui`
- 历史 UI smoke 曾覆盖 workbench / datasets / tasks / reviews / audit / settings；第一版默认 UI gate 已收敛到新版四模块 smoke。

2026-08-20 本轮前端第一版收敛进展：

- 新增 `synthetic-data-platform/web/src/pages/platformV1.tsx`。
- `main.tsx` 顶级导航已改为：
  - 候选集管理：`/candidate-sets`
  - 合成任务管理：`/synthesis-tasks`
  - 合成结果管理：`/synthesis-results`
  - 平台设置：`/settings`
- 旧路径已做兼容跳转：
  - `/workbench` -> `/candidate-sets`
  - `/datasets` -> `/candidate-sets`
  - `/tasks` -> `/synthesis-tasks`
  - `/tasks/:taskId/trials/:trialId` -> `/synthesis-results/:taskId/:trialId`
  - `/reviews/trials` -> `/synthesis-results`
  - `/audit` -> `/settings`
- 新合成结果详情页默认读取 OpenAI messages trajectory，并单独读取 `result.json`。
- 新合成结果详情页支持“通过/不通过”评审动作。
- 新任务实例页把日志放在任务实例详情里，不进入结果管理。
- 新候选集上传页不再要求用户显式选择文件格式；同名候选集版本由前端按 `vN+1` 自动计算后传给现有后端。
- 新平台设置页是安全摘要视图，展示 Harbor Control Plane、COS、runtime capabilities。
- 新增前端 API helper：`getTrialResult(taskId, trialId)`。
- 已执行并通过：
  - `cd synthetic-data-platform/web && npm run build`
- 浏览器冒烟状态：
  - `http://127.0.0.1:8080/` 已重建为新版四模块页面。
  - `npm run test:ui` 通过，当前默认运行 `v1-platform-smoke.spec.ts`。
  - `npm run test:live` 已用真实 COS/TKE E2E 产生的 dataset/task/trial 通过。

## 当前代码状态

super repo 当前有较多未提交改动，主要集中在：

- `deploy/`
- `docs/`
- `harbor-control-plane/`
- `synthetic-data-platform/`

子仓库状态：

- `harbor/`：有未提交改动，涉及 runner input materializer 和对应单测。
- `harbor-service-contracts/`：当前 `git status --short` 为空。
- `harbor-control-plane/`：有未提交改动，涉及 config、migration、publisher、tests。
- `synthetic-data-platform/`：有未提交改动，涉及 config、DB、control-plane client、auth/RBAC、API、前端、Playwright 测试等。

注意：不要用 `git reset --hard` 或 `git checkout --` 清理这些改动，里面包含用户和前序 session 的工作。

## 卡住或未完全收口的问题

0. 五阶段目标尚未完全收口，但第一版主链路已经通过真实 E2E。
   - 阶段 1 信息架构收敛已完成主路径。
   - 阶段 2 后端 CRUD/API 主路径已补齐 dataset/task/result 的 update/delete。
   - 阶段 4 端到端交互验收已完成一次 COS/TKE 真实链路。
   - 阶段 5 文档/测试/验收清理仍需要系统整理和提交 PR。

1. `harbor-api` 到 `harbor-control-plane` 的命名迁移尚未彻底收口。
   - 代码里已经有兼容层，但文档、部署文件、变量名可能仍有历史名称。
   - 需要系统性检查 `harbor_api`、`harbor-api`、`HarborApi` 残留。

2. 高级运行参数还没有前端产品化。
   - 当前前端只暴露 runtime、agent、model、并发、任务筛选。
   - 镜像、资源规格、namespace、timeout、temperature、max_tokens、env、verifier 参数等没有结构化表单。
   - 后端可以通过 `harbor_job_config` 直通，但前端还不能编辑。

3. 本地端到端 TKE + COS 验证依赖真实外部配置。
   - COS bucket/region/prefix/secret 已由用户配置过，但下次 session 仍应先确认配置文件实际值是否存在。
   - TKE runner 需要 kubeconfig、namespace、镜像、模型密钥等运行前置条件。
   - agent-runtime 选择 TKE 时，真正任务会在 TKE 里跑；host 上的 runner 负责 claim、物化输入、提交运行、收集/上传产物。

4. 数据集格式限制。
   - 当前 runner input materializer 主要支持 `source_type=cos` 和 `format=tar.gz`。
   - 上传时会扫描 archive catalog 并校验 Harbor dataset archive 格式。

5. RabbitMQ 本地/线上配置还需要稳定验证。
   - 之前 RocketMQ 的 host 运行依赖 `librocketmq`，本地不方便。
   - RabbitMQ 更适合本地 docker compose 和腾讯云托管 RabbitMQ 统一。
   - 但需要继续跑 RabbitMQ claim/dispatch smoke，确认 compose 和 host runner 都走新链路。

6. 第一版 CRUD 主路径已补齐，但还需要回归旧兼容路径。
   - 已有候选集上传/查询/编辑/删除。
   - 已有任务创建/查询/编辑/删除。
   - 已有结果查询/评审/下载/删除平台记录。
   - 删除语义是清理平台侧索引/记录，不删除 Harbor job 或 COS 原始产物。
   - 仍需决定旧 Workbench/Reviews/Audit 源码是删除、归档，还是保留为 legacy/debug。

7. 旧前端页面仍在源码中保留。
   - 新入口不再挂旧 Workbench/Reviews/Audit。
   - 旧文件仍存在，便于回滚和复用逻辑。
   - 后续需要决定是删除旧页面，还是移动到 legacy/debug 路由。

## 下一步计划

### P0：收口当前改动并保证可运行

1. 检查并整理未提交改动。
2. 分仓库提交：
   - `harbor-control-plane`
   - `synthetic-data-platform`
   - super repo
3. 确认是否需要为每个子仓库分别 push / PR。
4. 跑最小验证：
   - control-plane tests
   - synthetic-data-platform backend tests
   - synthetic-data-platform web build
   - synthetic-data-platform web UI smoke
   - compose config validation

### P0.5：第一版平台收敛剩余开发

1. 补后端 CRUD：
   - 已完成：dataset update/delete。
   - 已完成：task update/delete。
   - 已完成：trial result delete。语义是隐藏平台结果并清平台侧索引，不删除 Harbor/COS 原始产物。
2. 补前端对应操作：
   - 已完成：候选集编辑/删除。
   - 已完成：任务编辑/删除。
   - 已完成：合成结果删除。
3. 调整 UI smoke：
   - 已新增：`synthetic-data-platform/web/tests/ui/v1-platform-smoke.spec.ts`。
   - 已覆盖：四个顶级导航、日志和结果分离、trajectory/result.json、评审通过、平台设置摘要。
   - 未完成：历史大 smoke `console-smoke.spec.ts` 仍包含 Workbench/Reviews/Audit 旧断言，尚未迁移或拆分。
4. 重启或重建 compose web：
   - 已完成：`http://localhost:8080/` 是新版四模块页面。
5. 带真实 E2E 数据跑浏览器冒烟：
   - 已完成：`npm run test:live` 针对真实 COS/TKE dataset/task/trial 通过。

2026-08-20 本轮验证命令：

```bash
cd /home/ubuntu/project/harbor-platform/synthetic-data-platform
uv run pytest tests/test_app.py -q
uv run pytest tests/test_sql_repository.py -q
cd web
npm run build
SYNTHETIC_V1_SMOKE_BASE_URL=http://127.0.0.1:8090 npx playwright test tests/ui/v1-platform-smoke.spec.ts --project=chromium
npm run test:ui
SYNTHETIC_LIVE_BASE_URL=http://localhost:8080 \
SYNTHETIC_LIVE_DATASET_ID=f5090befe9044f229852d300d67d49ec \
SYNTHETIC_LIVE_DATASET_NAME=otel-bench-ags \
SYNTHETIC_LIVE_TASK_ID=2ca836d50bb44641a4c4da6bdf0f8709 \
SYNTHETIC_LIVE_TASK_NAME=go-http-tracing \
SYNTHETIC_LIVE_TRIAL_ID=34c9fb50-f6ad-480d-843f-5514ba4f4bb4 \
SYNTHETIC_LIVE_RUNTIME=tke \
npm run test:live

cd /home/ubuntu/project/harbor-platform
docker compose -f deploy/docker-compose/compose.dev.yml config
docker compose -f deploy/docker-compose/compose.dev.yml up -d --build
HARBOR_E2E_DATASET_DIR=/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags \
HARBOR_E2E_RUNTIME=tke \
HARBOR_E2E_TASK_NAME=go-http-tracing \
HARBOR_E2E_TIMEOUT_SEC=1800 \
HARBOR_E2E_REQUIRE_TRAJECTORY=1 \
HARBOR_E2E_REQUIRE_OPENAI_TRAJECTORY=1 \
HARBOR_E2E_REQUIRE_COS_ARTIFACTS=1 \
HARBOR_E2E_FRONTEND_LIVE_CHECK=1 \
./deploy/docker-compose/scripts/synthetic-cos-tke-e2e.sh
```

验证结果：

- `tests/test_app.py`：109 passed。
- `tests/test_sql_repository.py`：25 passed。
- `npm run build`：通过。
- `v1-platform-smoke.spec.ts`：3 passed。
- `npm run test:ui`：3 passed。
- `npm run test:live`：1 passed。
- `synthetic-cos-tke-e2e.sh`：通过，包含 COS dataset 上传、TKE 运行、COS artifacts、OpenAI trajectory、结果导出下载和新版前端 live workflow。

### P1：本地人工端到端测试

自动化目标链路已通过。后续人工复测可按这个路径确认 UI：

1. 启动本地 compose：
   - MySQL
   - RabbitMQ
   - harbor-control-plane
   - synthetic-data-platform API
   - synthetic-data-platform web on `8080`
2. 在 host 上启动 `harbor-runner`，不要用 `runner.host-paths.toml` / Docker-in-Docker。
3. runner 使用 provider `tke`，并开启 `cos-input`、COS artifact upload。
4. 前端候选集管理上传 `/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags` 数据集 archive。
5. 前端合成任务管理创建任务，选择：
   - dataset
   - runtime=`tke`
   - agent
   - model
   - concurrency
6. 观察任务：
   - queued
   - leased
   - input materializing
   - input succeeded
   - running
   - succeeded / failed
   - artifact succeeded / partial_failed
7. 在合成结果管理查询并下载：
   - OpenAI messages trajectory
   - result.json
   - 必要时加载 Harbor 原始 trajectory
8. 在任务实例详情查看运行日志，不在结果详情里看日志。

### P2：前端高级任务配置

建议补一个高级配置区域：

- 展示最终 payload preview。
- 支持编辑 `harbor_job_config` JSON。
- 明确提示：填写高级配置后，会绕过简化字段的自动组装。
- 后续再把常用高级参数做成结构化字段。

### P3：命名和部署清理

1. 全局清理 `harbor-api` 历史命名。
2. K8s manifest 统一为 `harbor-control-plane`。
3. compose service、环境变量、文档、runbook 统一 terminology。
4. 确认配置文件只放组件子仓库，super repo deploy 只 mount/reference。

## 踩过的坑

- 不要把 `dataset_id` 理解成 Harbor runtime 的输入。它只是 synthetic-data-platform 的业务主键。
- 不要把 COS 数据集直接塞进 Harbor runtime 的 `datasets[].path`。runner 需要先下载/解压，再重写为本地 path。
- `job_config` 和 `input_datasets` 是两条不同链路：
  - `job_config` 决定怎么跑。
  - `input_datasets` 决定跑哪个输入数据集。
- 如果 job 有 COS input dataset，control-plane 会要求 runner 具备 `cos-input` feature；runner capabilities 不匹配时不会 claim。
- RabbitMQ / RocketMQ 都只是 dispatch wake-up，不是状态源；状态必须看 MySQL/control-plane。
- 本地不建议再用 `runner.host-paths.toml`。这个主要是 runner 跑在容器里、需要连接宿主机 Docker daemon 的历史方案；当前希望 host 直接跑 runner。
- Docker-in-Docker 和宿主机 Docker 是两套不同模型：
  - 宿主机 Docker：runner 进程在 host 上调用 host docker。
  - Docker-in-Docker：runner 容器内部再跑 docker daemon。
  当前本地测试优先 host runner；线上 TKE/AGS 不依赖 host Docker。
- 前端访问 `http://localhost:8080/api/...` 可能返回 JSON 或 `Not Found`；浏览器打开平台页面应访问 `http://localhost:8080/`。
- 端口 `8080` 是 synthetic-data-platform web 的访问端口，不等同于 backend API 端口。
- COS prefix 只是对象 key 的前缀，不是本地目录；不同 runner/job 要靠 job id、attempt、execution namespace 等避免对象冲突。
- 当前很多改动跨 super repo 和子仓库，提交/PR 时不能只 push super repo，否则子仓库改动不会进入对应远端。

## 重要文件索引

- `AGENTS.md`
- `docs/architecture/harbor-platform-architecture.md`
- `docs/runbooks/harbor-fork-submodule-workflow.md`
- `docs/runbooks/development-roadmap.md`
- `docs/architecture/cos-artifact-storage-design.md`
- `docs/architecture/cos-input-dataset-materialization-design.md`
- `docs/architecture/synthetic-data-platform-frontend-design.md`
- `docs/runbooks/cos-input-materialization-local-e2e.md`
- `docs/runbooks/synthetic-frontend-local-e2e.md`
- `docs/runbooks/first-version-acceptance.md`
- `docs/runbooks/first-version-publish-plan.md`
- `synthetic-data-platform/src/synthetic_data_platform/app.py`
- `synthetic-data-platform/src/synthetic_data_platform/control_plane.py`
- `synthetic-data-platform/src/synthetic_data_platform/repository.py`
- `synthetic-data-platform/web/src/pages/tasks.tsx`
- `synthetic-data-platform/web/src/api.ts`
- `harbor-control-plane/src/harbor_control_plane/app.py`
- `harbor-service-contracts/src/harbor_service_contracts/api.py`
- `harbor/src/harbor/runner/daemon.py`
- `harbor/src/harbor/runner/input_materializer.py`
