# Harbor Platform Architecture

## Objective

Build a distributed Harbor execution platform that can later be reused by a synthetic data platform.

The target runtime flow is:

```text
synthetic-data-platform
  -> harbor-api
  -> MySQL + RabbitMQ
  -> harbor-runner instances
  -> harbor-runtime subprocesses
  -> agent-runtime environments
```

## Runtime Terminology

Use these terms consistently:

- `harbor-runner`: the distributed worker daemon. It receives dispatched jobs, obtains job leases, starts execution, reports snapshots, heartbeats, and records artifacts.
- `harbor-runtime`: the Harbor CLI execution control code run by the runner, currently `harbor job start`. It parses `JobConfig`, schedules trials, calls agents/environments/verifiers, and writes Harbor job/trial results.
- `agent-runtime`: the actual task execution environment used by an agent, such as a Docker container, AGS sandbox, TKE Pod, E2B sandbox, or another Harbor environment backend.

Deployment relationship:

```text
harbor-runner Pod/container
  ├─ harbor-runner daemon
  └─ harbor-runtime
       └─ creates or connects to agent-runtime through the selected provider
```

`harbor-runner` and `harbor-runtime` are packaged together in the runner image. `agent-runtime` is provider-dependent and is not necessarily in the same Pod/container.

## Repository Layout

```text
harbor-platform/
  harbor/                         # Harbor fork submodule
  harbor-control-plane/            # harbor-api/control-plane submodule
  synthetic-data-platform/         # synthetic data platform submodule
  harbor-service-contracts/        # shared schemas/contracts submodule
  deploy/
    docker-compose/                # local control-plane stack and smoke jobs
    k8s/                           # TKE namespace/RBAC and service manifests
  docs/
    architecture/
    runbooks/
```

## Module Responsibilities

### Harbor Submodule

`harbor/` remains the execution framework. It contains:

- core dataset/task/agent/environment/trial/job logic
- Harbor CLI
- Tencent Cloud AGS environment
- Tencent Cloud TKE environment
- future `harbor-runner`

`harbor-runner` belongs in the Harbor submodule because it launches the `harbor-runtime`, reads Harbor `jobs/` layout, and depends on `JobConfig`, `JobResult`, and `TrialResult` semantics.

### Harbor Control Plane

`harbor-control-plane/` is a separate service submodule pinned by the
super repo.

It owns:

- `harbor-api` HTTP service
- MySQL schema and migrations
- RabbitMQ dispatch producer and optional legacy RocketMQ adapters
- runner registry, heartbeat, lease, and retry logic
- job cancellation and status APIs
- service-local configuration and migrations

`harbor-api` should not run jobs directly. It writes DB state, publishes dispatch messages, and returns DB-backed job status.

### Synthetic Data Platform

`synthetic-data-platform/` is a separate business platform submodule
above Harbor. It owns:

- synthetic task management
- data source management
- prompt/template management
- sample ingestion and quality review
- dataset versions and publishing
- cost/business reporting

It should call `harbor-api` and store `synthetic_task_id -> harbor_job_id` mappings. It should not read runner-local files or import Harbor runner internals.

Frontend information architecture and UI/UX rules are documented in
[`synthetic-data-platform-frontend-design.md`](synthetic-data-platform-frontend-design.md).
The next platformization iteration is documented in
[`synthetic-data-platform-v4-platformization-plan.md`](synthetic-data-platform-v4-platformization-plan.md).

### Harbor Platform Super Repo

The super repo owns integration assets only:

- git submodule pins for each component repository
- Docker Compose and future Kubernetes/TKE deployment manifests
- local end-to-end smoke jobs and cross-component wiring
- cross-repo architecture docs and runbooks

It should not become the owner of component implementation code or concrete
component runtime configuration. `harbor-runner` config lives in `harbor/config/`;
TKE provider config lives in `harbor/config/`; `harbor-api` config lives in
`harbor-control-plane/config/`; synthetic platform config lives in
`synthetic-data-platform/config/`.

## State and Dispatch

Use MySQL as the state source:

- jobs
- trials
- runners
- runner leases
- job events
- artifact metadata

Use RabbitMQ as the default dispatch channel:

- queue: `harbor_jobs`
- message body: `job_id`, `action`, and minimal routing metadata
- consumers: Harbor runners

The message queue does not own durable job state. If a message is redelivered, the runner must consult MySQL lease/status before executing.

`harbor-api` does not directly call a specific `harbor-runner` for job dispatch. It writes MySQL state and publishes a RabbitMQ message. `harbor-runner` instances consume messages or poll queued jobs, claim a MySQL-backed lease, then invoke the local `harbor-runtime`.

The preferred runner acquisition path is `POST /internal/jobs/claim`. Claiming
combines capability matching and lease creation in one control-plane operation.
Jobs have `queue` and `priority` scheduling fields. Claim matching orders queued
work by descending priority and FIFO creation time, can filter by runner-provided
`queues`, and can enforce per-claim `queue_quotas` so one queue cannot consume an
entire multi-job claim batch.
For dispatch wake-ups that name a specific job, callers can pass `job_id` so the
claim cannot lease unrelated work.
RabbitMQ remains a wake-up channel; MySQL-backed claim state decides what actually
runs. Dispatch `action` defaults to `run`; artifact retry wake-ups use
`artifact-retry` and still require the runner to claim an artifact retry lease.

Cancellation is also control-plane owned. `POST /jobs/{job_id}/cancel` records
cancel metadata and moves queued jobs directly to `cancelled` or running/leased
jobs to `cancelling`. Runners poll `GET /internal/jobs/{job_id}/control` while
`harbor-runtime` is running and terminate the subprocess when cancellation is
requested.

## PoC Storage Model

Detailed COS artifact storage design lives in [`cos-artifact-storage-design.md`](cos-artifact-storage-design.md).
Detailed COS input dataset materialization design lives in
[`cos-input-dataset-materialization-design.md`](cos-input-dataset-materialization-design.md).

The platform currently supports two artifact storage modes:

- `runner-local`: default local development mode. Each runner keeps its own local `jobs/` directory and `harbor-api` may serve files only from an explicitly allowed local root.
- `cos`: production-oriented mode. `harbor-runner` uploads collected artifacts to Tencent Cloud COS, records `cos://<bucket>/<key>` metadata in MySQL, and `harbor-api` serves either signed URLs or proxy streams.

In both modes:

- runner writes `artifacts/runner-execution.json` for each execution namespace
  before starting `harbor-runtime`
- runner scans every ordinary file under `jobs/<job_id>/` after execution; it does
  not follow symlinks
- artifact manifests such as `artifacts/manifest.json` are metadata overlays only:
  they can declare `kind`, `trial_id`, `schema`, `content_type`, and extra
  metadata, but they do not decide whether a file is uploaded
- runner records artifact rows through `harbor-api`
- MySQL remains the artifact index
- `synthetic-data-platform` reads results and trajectories through `harbor-api`, not runner-local paths or COS credentials

COS non-secret configuration remains TOML-based. Local development can still use
literal `secret_id` and `secret_key` fields for compatibility, while production
templates use `secret_id_env`, `secret_key_env`, and optional
`session_token_env` fields. The referenced environment variables are injected by
Kubernetes Secrets in TKE manifests. The local runner reads
`harbor/config/runner.local.toml`; the local control-plane stack mounts
`harbor-control-plane/config/control-plane.local.toml` into `harbor-api`.
Production templates also reference database and RabbitMQ connection strings via
`database_url_env` and `rabbitmq_url_env`, keeping concrete passwords out of
ConfigMaps and git-tracked TOML files.

Production service-to-service access can be protected by config-driven Bearer
token, tenant header, and coarse token scopes. `harbor-api` reads `[auth]` from
`harbor-control-plane/config/control-plane.<env>.toml`; `synthetic-data-platform`
uses `[auth]` for its own API and `[harbor_api_auth]` for outbound calls to
`harbor-api`; `harbor-runner` uses `control_plane_bearer_token(_env)` and
`control_plane_tenant_id(_env)` when calling the control plane. Control-plane
tokens can be split into `read`, `write`, and `internal` scopes so the synthetic
platform cannot call runner-only endpoints and runner tokens can be separated
from user-facing workflow calls. `synthetic-data-platform` also supports
multiple inbound `[auth.tokens]` with coarse `read` / `write` scopes so console
read traffic can be separated from dataset upload, task mutation, publish, and
review-decision writes. This is a minimum deployment gate, not a
replacement for future user login, fine-grained RBAC, or end-user permission
modeling. Control-plane API calls are persisted as `api_audit_events` with
tenant, principal, scopes, required scope, path, status, request ID, and derived
job ID; internal callers can query them through
`POST /internal/audit-events/query`. Cancel/retry/artifact-retry idempotency
records are persisted with tenant scope so replay behavior is isolated per
tenant.

Trajectory files, trial results, logs, task artifacts, and runner manifests are all treated as artifact records. `kind = "trajectory"` is reserved for agent trajectory JSON files. The artifact `kind` describes the business category, while `metadata.schema` describes the concrete file schema, such as `atif` or `openai_messages`.

Artifact identity is intentionally split:

- `platform_job_id`: the control-plane job ID used for scheduling and querying.
- `runtime_job_result_id`: Harbor runtime `JobResult.id` from root `result.json`.
- `execution_id`: the runner lease/attempt namespace used in COS keys.

The default COS object key layout is:

```text
{prefix}/jobs/{platform_job_id}/attempts/{attempt}/executions/{execution_id}/{relative_path}
```

This keeps two runner Pods from overwriting each other when the same platform job
ID is retried, re-leased, or re-uploaded.

`harbor-runtime` writes the canonical ATIF trajectory and also derives an OpenAI
messages trajectory when a valid ATIF `agent/trajectory*.json` file exists:

```text
agent/trajectory.json
agent/trajectory.openai-messages.json
```

Both files are recorded as `kind = "trajectory"` and are distinguished through
`metadata.schema`.

Input datasets are handled separately from output artifacts. `synthetic-data-platform`
can submit `input_datasets` with COS URIs to `harbor-api`; `harbor-api` stores
those declarations in MySQL; `harbor-runner` downloads and validates them under
`jobs/<job_id>/inputs/`, rewrites Harbor `JobConfig.datasets` to local paths, and
then starts `harbor-runtime`. The runner also records `inputs/manifest.json` as
`kind = "input-manifest"` so callers can inspect what was materialized.

## Concurrency Model

There are two independent concurrency controls:

```text
runner_concurrency
  Number of Harbor jobs one runner can run at once.

job_n_concurrent_trials
  Number of trials inside one Harbor job, equivalent to `harbor run -n`.
```

Total trial pressure is roughly:

```text
runner_count * runner_concurrency * job_n_concurrent_trials
```

Provider quotas, model API limits, TCR image pull speed, and AGS/TKE sandbox capacity must still be handled separately.

## Deployment Direction

Development uses Docker Compose with:

- MySQL
- RabbitMQ
- optional RabbitMQ management UI
- harbor-api
- synthetic-data-platform

Local `harbor-runner` processes run from the `harbor/` submodule on the host.
Production packages runner/runtime into runner Pods.

Production replaces these with:

- TencentDB MySQL
- TDMQ for RabbitMQ
- TKE harbor-api active/standby
- TKE harbor-runner deployment
- COS/object storage for artifacts

The Tencent Cloud deployment contract, rollout order, acceptance checks, and
rollback boundaries are documented in
[`tencent-cloud-deployment-runbook.md`](../runbooks/tencent-cloud-deployment-runbook.md).
