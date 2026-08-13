# Harbor Fork and Submodule Workflow

## Current Remote Model

The Harbor fork is stored at:

```text
git@github.com:wayne2008-gpu/harbor-based-data-synthesis-platform.git
```

Inside `harbor-platform/harbor`, remotes should be:

```text
origin   git@github.com:wayne2008-gpu/harbor-based-data-synthesis-platform.git
upstream git@github.com:harbor-framework/harbor.git
```

`origin` is the writable fork/mirror. `upstream` is the official open-source Harbor repository.

## Clone Monorepo

```bash
git clone --recurse-submodules <harbor-platform-url>
cd harbor-platform
```

If submodules were not cloned:

```bash
git submodule update --init --recursive
```

## Work on Harbor

```bash
cd harbor
# edit Harbor code
git status
git add <files>
git commit -m "..."
git push origin main

cd ..
git add harbor
git commit -m "Update Harbor submodule"
```

The outer monorepo records the Harbor submodule commit pointer. Harbor code changes must be committed and pushed inside `harbor/` first.

## Sync Official Harbor Upstream

```bash
cd harbor
git fetch upstream
git checkout main
git merge upstream/main
# resolve conflicts, run tests
git push origin main

cd ..
git add harbor
git commit -m "Sync Harbor submodule with upstream"
```

Use merge rather than rebasing public shared commits unless the team explicitly decides otherwise. This keeps the fork history stable for the monorepo submodule pointer.

## Current Known Harbor Additions

The fork currently contains local additions on top of official Harbor:

- Tencent Cloud AGS environment support
- Tencent Cloud TKE environment support
- AGS/TKE docs and example configs
- generated AGS-ready otel-bench dataset assets
- agent skill for converting Harbor datasets to AGS image-only datasets
- project skill initialization script

Useful docs inside the submodule:

```text
harbor/readme-ags.md
harbor/readme-tke.md
harbor/docs/agents/tke-smoke-runbook.zh.md
harbor/agent-skills/harbor-ags-dataset-converter/SKILL.md
```

## Verification After Sync

Run the targeted AGS/TKE tests:

```bash
cd harbor
uv run pytest tests/unit/environments/test_ags_clients.py tests/unit/environments/test_ags.py tests/unit/environments/test_ags_config.py tests/unit/environments/test_ags_queue.py tests/unit/environments/test_tke_config.py tests/unit/environments/test_tke.py tests/unit/environments/test_environment_definition.py tests/unit/environments/test_provider_resource_capabilities.py -q
```

A broader Harbor validation can run:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run ty check
```

Known historical note: `ty check` previously reported an optional `sky.server` import issue in `src/harbor/environments/skypilot.py`. Treat that as unrelated unless it changes.
