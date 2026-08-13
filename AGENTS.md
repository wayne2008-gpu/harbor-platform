# AGENTS.md - Harbor Platform

## Project Goal

This monorepo coordinates a Harbor-based distributed execution platform and a future synthetic data platform.

The repository intentionally keeps these modules separate:

- `harbor/`: Harbor fork as a git submodule. This contains Harbor core, AGS/TKE environment adapters, and future `harbor-runner` work.
- `services/harbor-control-plane/`: future control-plane service project. It will contain `harbor-api`, DB migrations, RocketMQ adapters, scheduler/lease logic, and deployment code.
- `services/synthetic-data-platform/`: future business platform for synthetic data task management. It should call `harbor-api` instead of importing Harbor internals.
- `packages/harbor-service-contracts/`: future shared service contracts, such as job state enums, RocketMQ message schema, and request/response models.
- `deploy/`: local Docker Compose and future Kubernetes/TKE manifests.
- `docs/`: architecture notes and runbooks.

## Boundary Rules

- `harbor/` must not import `harbor-control-plane` or `synthetic-data-platform`.
- `harbor-control-plane` may depend on stable Harbor package APIs and shared contracts, but it must not know synthetic data business concepts.
- `synthetic-data-platform` should talk to `harbor-api` over HTTP and store its own business state.
- MySQL is the durable state source for control-plane jobs and runners.
- RocketMQ is a dispatch channel only. Do not use RocketMQ as the source of truth for job state.
- In PoC, runner-local `jobs/` can hold logs and artifacts. Production should move logs/artifacts to object storage.

## Development Commands

For Harbor submodule work:

```bash
cd harbor
uv sync --all-extras --dev
uv run pytest tests/unit/environments/test_ags_clients.py tests/unit/environments/test_ags.py tests/unit/environments/test_ags_config.py tests/unit/environments/test_ags_queue.py tests/unit/environments/test_tke_config.py tests/unit/environments/test_tke.py tests/unit/environments/test_environment_definition.py tests/unit/environments/test_provider_resource_capabilities.py -q
```

Follow the Harbor submodule workflow in `docs/runbooks/harbor-fork-submodule-workflow.md` before syncing official Harbor upstream.

## New Codex Session Handoff

At the start of a new session, read these files first:

1. `AGENTS.md`
2. `docs/architecture/harbor-platform-architecture.md`
3. `docs/runbooks/harbor-fork-submodule-workflow.md`
4. `docs/runbooks/development-roadmap.md`

Then inspect `harbor/readme-ags.md`, `harbor/readme-tke.md`, and the Harbor submodule git status before changing code.
