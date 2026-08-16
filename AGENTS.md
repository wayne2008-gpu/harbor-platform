# AGENTS.md - Harbor Platform

## Project Goal

This repository is the Harbor Platform super repo. It pins the component
repositories as git submodules and owns cross-repo deployment, documentation,
and end-to-end validation.

The repository intentionally keeps these modules separate:

- `harbor/`: Harbor fork submodule. This contains Harbor core, AGS/TKE environment adapters, `harbor-runtime`, and `harbor-runner`.
- `services/harbor-control-plane/`: control-plane submodule. This contains `harbor-api`, DB migrations, RocketMQ adapters, scheduler/lease logic, and artifact access code.
- `services/synthetic-data-platform/`: synthetic data business platform submodule. It should call `harbor-api` instead of importing Harbor internals.
- `packages/harbor-service-contracts/`: shared contracts submodule, such as job state enums, RocketMQ message schema, and request/response models.
- `deploy/`: super-repo owned local Docker Compose and future Kubernetes/TKE manifests.
- `docs/`: super-repo owned architecture notes and runbooks.

## Boundary Rules

- `harbor/` must not import `harbor-control-plane` or `synthetic-data-platform`.
- `harbor-control-plane` may depend on stable Harbor package APIs and shared contracts, but it must not know synthetic data business concepts.
- `synthetic-data-platform` should talk to `harbor-api` over HTTP and store its own business state.
- Component code changes belong in the owning submodule, not in super-repo-only directories.
- Deployment config belongs under `deploy/`, not at the repository root or inside component source trees.
- MySQL is the durable state source for control-plane jobs and runners.
- RocketMQ is a dispatch channel only. Do not use RocketMQ as the source of truth for job state.
- Runner-local `jobs/` is staging/cache. Durable production artifacts should be stored in object storage.

## Development Commands

For Harbor submodule work:

```bash
cd harbor
uv sync --all-extras --dev
uv run pytest tests/unit/environments/test_ags_clients.py tests/unit/environments/test_ags.py tests/unit/environments/test_ags_config.py tests/unit/environments/test_ags_queue.py tests/unit/environments/test_tke_config.py tests/unit/environments/test_tke.py tests/unit/environments/test_environment_definition.py tests/unit/environments/test_provider_resource_capabilities.py -q
```

Follow the Harbor submodule workflow in `docs/runbooks/harbor-fork-submodule-workflow.md` before syncing official Harbor upstream.

For super repo end-to-end work:

```bash
git submodule update --init --recursive
docker compose -f deploy/docker-compose/compose.dev.yml config
```

## New Codex Session Handoff

At the start of a new session, read these files first:

1. `AGENTS.md`
2. `docs/architecture/harbor-platform-architecture.md`
3. `docs/runbooks/harbor-fork-submodule-workflow.md`
4. `docs/runbooks/development-roadmap.md`

Then inspect `harbor/readme-ags.md`, `harbor/readme-tke.md`, and the Harbor submodule git status before changing code.
