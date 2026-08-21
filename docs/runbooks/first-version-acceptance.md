# First Version Acceptance

更新时间：2026-08-20

本文记录“后训练 Agent 轨迹数据合成平台”第一版的验收口径和当前已验证证据。

## 第一版产品范围

第一版只暴露四个主模块：

- 候选集管理：上传、查看、编辑、删除提交给 Harbor 跑数的输入数据集。
- 合成任务管理：创建、查看、编辑、删除合成任务，并查看任务实例运行状态和日志。
- 合成结果管理：查看、下载、删除任务实例产生的结果。
- 平台设置：查看 harbor-control-plane、COS、runtime capability 等配置摘要。

第一版不把 Workbench、独立 Reviews、Audit、platform sample、result dataset 作为主导航或主用户心智。
旧接口和旧页面源码可以作为 legacy/debug 能力保留，但默认入口和验收不依赖它们。

## 结果口径

任务实例日志归属合成任务管理。

合成结果管理默认只展示：

- OpenAI messages schema trajectory
- `result.json`

Harbor 原始 trajectory 只作为排障辅助入口。日志不进入结果详情页。

评审动作只做 trajectory 级别的通过/不通过。

## 本地部署验收

默认本地栈使用：

```bash
cd /home/ubuntu/project/harbor-platform
docker compose -f deploy/docker-compose/compose.dev.yml up -d --build
```

默认服务地址：

```text
synthetic-data-platform web:  http://localhost:8080
synthetic-data-platform API:  http://localhost:8081
harbor-control-plane:         http://localhost:18080
RabbitMQ management:          http://localhost:15672
```

`compose.dev.yml` 默认挂载：

```text
synthetic-data-platform/config/platform.local.toml
harbor-control-plane/config/control-plane.local.toml
```

`compose.synthetic-upload.yml` 只保留为 legacy compatibility override，不是第一版本地验收必需项。

宿主机 runner 启动命令：

```bash
cd /home/ubuntu/project/harbor-platform/harbor
HARBOR_TKE_CONFIG=/home/ubuntu/.config/harbor/tke.toml \
uv run harbor runner start --config config/runner.local.toml --keep-alive
```

当前本机 runner 常驻在 tmux：

```bash
tmux attach -t harbor-runner-local
tmux kill-session -t harbor-runner-local
```

## 端到端验收命令

真实 COS/TKE 端到端验收：

```bash
cd /home/ubuntu/project/harbor-platform
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

该命令验证：

- synthetic API 上传候选集归档到 COS。
- synthetic API 创建合成任务。
- harbor-control-plane 创建 Harbor job 并持久化状态。
- host runner claim job。
- runner 从 COS 下载并物化输入 dataset。
- harbor-runtime 执行 TKE runtime 任务。
- runner 上传 job_dir 下普通文件到 COS。
- harbor-control-plane 记录 artifact metadata。
- synthetic API 能查询并下载 artifact。
- synthetic API 能读取 OpenAI messages trajectory 和 `result.json`。
- 前端 live test 打开候选集、合成任务实例、合成结果页面。

## 最近一次通过记录

2026-08-20 已通过：

- dataset：`f5090befe9044f229852d300d67d49ec`
- synthetic task：`2ca836d50bb44641a4c4da6bdf0f8709`
- Harbor job：`282182c916494674a4255417665dd050`
- trial：`34c9fb50-f6ad-480d-843f-5514ba4f4bb4`
- COS artifacts：155 个
- trajectory artifacts：2 个
- OpenAI messages trajectory：1 个
- input manifest：1 个
- frontend live workflow：1 passed

前端复核入口：

```text
http://localhost:8080/candidate-sets/f5090befe9044f229852d300d67d49ec
http://localhost:8080/synthesis-tasks/2ca836d50bb44641a4c4da6bdf0f8709
http://localhost:8080/synthesis-results/2ca836d50bb44641a4c4da6bdf0f8709/34c9fb50-f6ad-480d-843f-5514ba4f4bb4
```

## 自动化验证

已执行并通过：

```bash
cd /home/ubuntu/project/harbor-platform/harbor
uv run pytest tests/unit/runner -q
```

结果：80 passed。

```bash
cd /home/ubuntu/project/harbor-platform/harbor-control-plane
uv run pytest tests -q
```

结果：97 passed。

```bash
cd /home/ubuntu/project/harbor-platform/synthetic-data-platform
uv run pytest tests/test_app.py tests/test_sql_repository.py -q
```

结果：134 passed。

```bash
cd /home/ubuntu/project/harbor-platform/synthetic-data-platform/web
npm run build
npm run test:ui
```

结果：build passed，V1 UI smoke 3 passed。

```bash
cd /home/ubuntu/project/harbor-platform
docker compose -f deploy/docker-compose/compose.dev.yml config
docker compose -f deploy/docker-compose/compose.dev.yml -f deploy/docker-compose/compose.synthetic-upload.yml config
```

结果：均通过。

## 手工验收清单

打开 `http://localhost:8080`，确认：

- 顶级导航只有候选集管理、合成任务管理、合成结果管理、平台设置。
- 候选集详情能看到 COS URI、checksum、task name。
- 合成任务详情能看到 Harbor job、runtime、input/artifact 状态和运行日志。
- 合成结果详情默认显示 OpenAI messages trajectory。
- 合成结果详情显示 `result.json`。
- 合成结果详情不显示运行日志。
- 合成结果详情支持通过/不通过评审。
- 平台设置显示 harbor-control-plane、COS、runtime capability 摘要，不泄露密钥。

## 剩余非阻塞项

- 旧 Workbench/Reviews/Audit 源码仍在仓库中，当前通过路由重定向隐藏。
- `harbor_api` 兼容字段和 `/settings/harbor-api` 兼容路由仍保留，用于旧客户端兼容。
- Legacy sample ingest / result dataset publish / export 能力仍可用，但不作为第一版主路径。
- 当前仓库处于 detached HEAD，正式发布前需要按子仓库拆提交、推送分支，并更新 super repo submodule 指针。
