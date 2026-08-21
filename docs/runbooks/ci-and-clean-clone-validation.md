# CI and Clean Clone Validation

This runbook covers the release checks after the platform split:

- GitHub Actions CI for contracts, control-plane, synthetic platform, Harbor runner, Harbor AGS/TKE targeted tests, Compose config rendering, and smoke asset validation.
- A clean clone smoke test that proves the pushed repository and submodules can reproduce the Docker provider validation without relying on the original working tree.

## GitHub Actions

The workflow lives at:

```text
.github/workflows/ci.yml
```

It checks out only the submodules required by each CI job. Private submodules
require a repository secret named `HARBOR_SUBMODULE_TOKEN` with read access to
all private component repositories referenced by `.gitmodules`, currently:

- `wayne2008-gpu/harbor-based-data-synthesis-platform`
- `wayne2008-gpu/harbor-control-plane`
- `wayne2008-gpu/harbor-service-contracts`
- `wayne2008-gpu/synthetic-data-platform`

If the token is a fine-grained PAT, select all private component repositories
above and grant at least read-only `Contents` access. CI falls back to
`github.token` only for public submodule access; private cross-repository
submodules need `HARBOR_SUBMODULE_TOKEN`.

## Clean Clone Smoke

Run from a temporary directory, not from the development working tree:

```bash
rm -rf /tmp/harbor-platform-clean
git clone --recurse-submodules git@github.com:wayne2008-gpu/harbor-platform.git /tmp/harbor-platform-clean
cd /tmp/harbor-platform-clean
git submodule status
```

Create the local config files before running the smoke. These files are
deployment-local and intentionally ignored by Git because they may contain COS
credentials:

```text
harbor/config/runner.local.toml
harbor-control-plane/config/control-plane.local.toml
```

Start the control-plane stack:

```bash
cd /tmp/harbor-platform-clean/deploy/docker-compose
docker compose -f compose.dev.yml up --build -d
```

Start the runner from the Harbor submodule on the host:

```bash
cd /tmp/harbor-platform-clean/harbor
uv sync --all-extras --dev
uv run harbor runner start --config config/runner.local.toml --keep-alive
```

In another shell, submit the smoke job:

```bash
cd /tmp/harbor-platform-clean/deploy/docker-compose
export HARBOR_PLATFORM_ROOT=/tmp/harbor-platform-clean
./scripts/submit-and-wait-job.sh smoke/docker-touch-file-smoke-job.local.json http://localhost:18080 900
```

Expected result:

- one online runner
- terminal `succeeded` job
- non-empty `runner_id`
- at least one `succeeded` trial from `/jobs/{job_id}/trials`
- `result` and `artifact-manifest` entries from `/jobs/{job_id}/artifacts`

Cleanup:

```bash
cd /tmp/harbor-platform-clean/deploy/docker-compose
docker compose -f compose.dev.yml down
```
