# First Version Publish Plan

更新时间：2026-08-20

当前四个仓库都已切到本地分支：

```text
agent/first-version-acceptance
```

这些分支只在本地创建，尚未提交、push 或创建 PR。

## 发布顺序

建议按子仓库先提交，再提交 super repo 指针和部署文档：

1. `harbor/`
2. `harbor-control-plane/`
3. `synthetic-data-platform/`
4. super repo `harbor-platform/`

原因：super repo 需要记录三个子模块的新 commit 指针，必须等子仓库 commit 先生成。

## harbor

目标远端：

```text
origin git@github.com:wayne2008-gpu/harbor-based-data-synthesis-platform.git
base: main 或 feature/agent-platform-mvp，按 PR 策略确认
```

当前改动：

```text
src/harbor/runner/input_materializer.py
tests/unit/runner/test_input_materializer.py
```

建议提交信息：

```text
Materialize COS input datasets for runner jobs
```

已验证：

```bash
cd harbor
uv run pytest tests/unit/runner -q
```

结果：80 passed。

## harbor-control-plane

目标远端：

```text
origin git@github.com:wayne2008-gpu/harbor-control-plane.git
base: main 或 feature/agent-platform-mvp，按 PR 策略确认
```

当前改动：

```text
config/control-plane.production.example.toml
migrations/versions/0004_query_cancel_claim_retry.py
src/harbor_control_plane/config.py
src/harbor_control_plane/publisher.py
tests/test_app.py
tests/test_config.py
```

建议提交信息：

```text
Align control plane dispatch and storage config
```

已验证：

```bash
cd harbor-control-plane
uv run pytest tests -q
```

结果：97 passed。

## synthetic-data-platform

目标远端：

```text
origin git@github.com:wayne2008-gpu/synthetic-data-platform.git
base: main
```

当前改动覆盖：

- control-plane client/config 迁移与兼容。
- COS dataset upload/result export 配置。
- auth/RBAC/access control。
- dataset/task/result CRUD。
- 第一版四模块中文前端。
- live/ui Playwright 测试。

建议提交信息：

```text
Ship first-version trajectory synthesis platform
```

已验证：

```bash
cd synthetic-data-platform
uv run pytest tests/test_app.py tests/test_sql_repository.py -q
cd web
npm run build
npm run test:ui
```

结果：134 passed；build passed；V1 UI smoke 3 passed。

## harbor-platform super repo

目标远端：

```text
origin git@github.com:wayne2008-gpu/harbor-platform.git
base: main
```

当前改动覆盖：

- `deploy/docker-compose/compose.dev.yml` 默认启动 control-plane、synthetic API/Web、result export worker。
- `compose.synthetic-upload.yml` 标记为 legacy compatibility override。
- E2E 脚本默认使用 `8080` web 和 `18080` control-plane，并输出新版四模块 URL。
- K8s/部署文档中的 `harbor-api` 命名迁移到 `harbor-control-plane`。
- 本地 runbook 改为候选集、合成任务、合成结果、平台设置的一版验收口径。
- 新增 `docs/runbooks/first-version-acceptance.md`。
- 新增本发布计划。
- `.gitignore` 忽略本地 `tmp/`。

建议提交信息：

```text
Document first-version acceptance and compose deployment
```

已验证：

```bash
cd harbor-platform
docker compose -f deploy/docker-compose/compose.dev.yml config
docker compose -f deploy/docker-compose/compose.dev.yml -f deploy/docker-compose/compose.synthetic-upload.yml config
./deploy/docker-compose/scripts/synthetic-cos-tke-e2e.sh
```

最近完整 E2E：通过，记录见 `docs/runbooks/first-version-acceptance.md`。

## 敏感信息检查

已对当前 diff 做关键词扫描，未发现真实 COS/OpenAI 密钥进入 diff。

本地明文配置仍存在于工作机器的 component config 中，但不应提交：

```text
harbor/config/runner.local.toml
harbor-control-plane/config/control-plane.local.toml
synthetic-data-platform/config/platform.local.toml
```

`tmp/` 已加入 super repo `.gitignore`，避免 E2E 临时 dataset archive 入库。

## 需要用户确认

提交前需要确认：

1. 是否将当前四个仓库的全部 dirty 文件都纳入第一版提交范围。
2. `harbor/` 和 `harbor-control-plane/` 的 PR base 是 `main` 还是 `feature/agent-platform-mvp`。
3. 是否创建 draft PR，还是只 push 分支。
