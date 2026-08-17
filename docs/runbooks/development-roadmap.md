# Development Roadmap

## Phase 0: Spec

Write the first formal spec before implementation.

Spec should define:

- project boundaries
- `harbor-runner` interface
- `harbor-api` interface
- MySQL tables
- dispatch message schema
- job/trial/runner state machines
- cancellation and retry semantics
- local Docker Compose topology
- cloud replacement path for TencentDB, TDMQ for RabbitMQ, TKE, and COS

## Phase 1: Harbor Runner Run-Once

Implement in the Harbor submodule.

Goal:

```text
uv run harbor runner run-once --job-config /path/job.json
```

Minimum behavior:

- start a `harbor run` subprocess
- record process id
- set deterministic job name/jobs dir
- read `jobs/<job_id>/result.json`
- report completed/running/pending/error counts
- support local cancellation

No MySQL or message queue in this phase.

## Phase 2: Harbor Runner Daemon

Still in the Harbor submodule.

Goal:

```text
uv run harbor runner start --config runner.toml
```

Minimum behavior:

- long-running process
- configurable `runner_id`, `jobs_dir`, `max_running_jobs`
- run multiple Harbor jobs concurrently
- isolate subprocess state per job
- scan local `jobs/` and emit progress snapshots

## Phase 3: Harbor Control Plane / Harbor API

Create `harbor-control-plane/`.

Minimum modules:

- FastAPI app
- config loader
- MySQL repository
- RabbitMQ producer
- job schema validation

Initial endpoints:

```text
POST /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/trials
POST /jobs/{job_id}/cancel
GET /runners
```

`POST /jobs` writes MySQL and publishes a RabbitMQ message. It does not run Harbor directly.

## Phase 4: Runner MySQL + RabbitMQ Integration

Connect `harbor-runner` to the control plane contracts.

Flow:

1. runner registers in MySQL
2. runner heartbeats
3. runner consumes RabbitMQ messages from `harbor_jobs`
4. runner obtains job lease from MySQL
5. runner starts `harbor run`
6. runner scans `result.json`
7. runner writes progress to MySQL
8. runner completes/fails/cancels job and acks message

Validate with two runner processes. In local development those processes run from
the `harbor/` submodule; Compose only starts the control-plane dependencies.

## Phase 5: Docker Compose Distributed Dev

Create `deploy/docker-compose/compose.dev.yml` with:

- MySQL
- RabbitMQ
- optional RabbitMQ management UI
- harbor-api
- synthetic-data-platform

Run `harbor-runner` from the `harbor/` submodule with
`harbor/config/runner.local.toml`. Start additional local runner processes with
different `HARBOR_RUNNER_ID` values when validating distributed lease behavior.

Run real jobs:

- Harbor hello-world
- one otel-bench task
- several otel-bench tasks
- concurrent jobs

## Phase 6: Logs and Artifacts

Implemented storage modes:

- `runner-local`: default local mode. Runner records local artifact paths; API can serve only from an explicitly allowed root.
- `cos`: runner uploads artifacts to Tencent Cloud COS and records durable `cos://<bucket>/<key>` addresses in MySQL.

Current COS behavior:

- TOML config uses literal `secret_id` and `secret_key` in this iteration.
- Runner stores attempt/execution-scoped keys:
  `{prefix}/jobs/{platform_job_id}/attempts/{attempt}/executions/{execution_id}/{relative_path}`.
- Runner writes `artifacts/runner-execution.json` before starting
  `harbor-runtime`; artifact retry reuses this file when it already exists.
- Runner records `relative_path`, `checksum_sha256`, `etag`, `content_type`, `metadata`, and `uploaded_at`.
- Artifact metadata includes `platform_job_id`, `runtime_job_result_id`,
  `attempt`, `runner_id`, `lease_id`, `execution_id`, and `cos_key_layout`.
- Job execution state and artifact persistence state are separated through `artifact_state`.
- API can return COS signed URLs or proxy object bytes.

Hardening backlog:

- replace literal COS credentials with env/K8s Secret references
- add scheduled local retention cleanup beyond immediate `retain_local = false`
- add real-COS integration smoke gated by credentials

## Phase 7: Synthetic Data Platform

Create `synthetic-data-platform/` after Harbor API is stable.

Current first version:

```text
POST /synthetic-tasks
GET /synthetic-tasks/{id}
GET /synthetic-tasks/{id}/samples
GET /synthetic-tasks/{id}/results
GET /synthetic-tasks/{id}/artifacts
GET /synthetic-tasks/{id}/trials
GET /synthetic-tasks/{id}/trials/{trial_id}/result
GET /synthetic-tasks/{id}/trials/{trial_id}/artifacts
GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory
GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory?schema=openai_messages
POST /synthetic-tasks/{id}/cancel
POST /synthetic-tasks/{id}/retry
POST /synthetic-tasks/{id}/artifacts/retry
POST /synthetic-tasks/{id}/publish
GET /result-datasets
GET /result-datasets/{id}
GET /result-datasets/{id}/download?format=jsonl
GET /result-datasets/{id}/download?format=json
GET /settings
```

Flow:

1. create synthetic task
2. generate Harbor JobConfig
3. call `harbor-api POST /jobs`
4. store `synthetic_task_id -> harbor_job_id`
5. poll/query Harbor status
6. read trial results, trajectory, and artifact metadata through `harbor-api`
7. parse samples into business tables when sample artifacts exist
8. cancel active Harbor jobs from the synthetic task detail view
9. retry terminal Harbor jobs as new synthetic task records
10. request artifact retry for terminal jobs
11. ingest samples from Harbor sample/trial-result artifacts
12. publish those samples as an idempotent result dataset version
13. query published result datasets from the Results console
14. inspect result dataset samples, metadata, source trials, and source artifacts
    from a detail page
15. download result datasets as JSONL samples or full JSON metadata
16. jump from a result dataset back to source trajectories and source artifact
    downloads
17. inspect safe runtime settings without exposing database credentials or COS
    secrets

## Phase 8: Input Dataset Materialization

Current target:

- `synthetic-data-platform` can submit `input_datasets` with COS URIs.
- `harbor-api` stores original input declarations and materialization state in
  MySQL.
- `harbor-runner` fetches full job status, downloads COS archives, verifies
  checksum, safely extracts task datasets, rewrites Harbor `JobConfig.datasets`
  to runner-local paths, and starts `harbor-runtime`.
- `harbor-runtime` remains unaware of COS and receives normal local dataset
  paths.
- runner records `inputs/manifest.json` as `kind = "input-manifest"`.

Implementation checkpoints:

1. M17: shared contract models and state enum.
2. M18: harbor-api persistence, migration, and input-state endpoint.
3. M19: runner input materializer interface and TOML config.
4. M20: COS download, checksum verification, safe tar extraction, and task
   validation.
5. M21: runner JobConfig rewrite and input-state reporting.
6. M22: input manifest artifact collection and local retention behavior.
7. M23: synthetic-data-platform `input_datasets` pass-through.
8. M24: docs, compose examples, tests, and local validation.

Current status:

- M17-M23 are implemented across contracts, harbor-api, harbor-runner, and
  synthetic-data-platform.
- M24 adds the local COS input materialization smoke payload, optional smoke
  assertions for `input_state` and `input-manifest`, and the local E2E runbook:
  [`cos-input-materialization-local-e2e.md`](cos-input-materialization-local-e2e.md).

Hardening backlog:

- replace literal TOML COS credentials with env/K8s Secret references
- add scheduled retention cleanup beyond immediate `retain_local = false`
- add real-COS integration smoke gated by credentials
- add synthetic business dataset catalog validation

## Phase 9: Control Plane Operations

Current target:

- external callers can query jobs, trials, and artifacts through cursor-based
  query endpoints instead of broad list calls
- cancellation has explicit request metadata and a `cancelling` execution state
- runners can poll job control and terminate `harbor-runtime` on cancel request
- runners can claim jobs through `POST /internal/jobs/claim`; claim owns
  capability matching and lease creation in one control-plane operation
- claim requests can target a specific `job_id`, which lets artifact retry
  wake-up messages claim the exact job they were emitted for
- job retry creates a new job attempt with `parent_job_id`, `root_job_id`, and
  `attempt`
- cancel, retry, and artifact retry persist `idempotency_key` records; repeated
  requests with the same job, operation, and key return the first operation's
  result without repeating side effects
- artifact retry records a retry request by resetting `artifact_state`; the
  original runner later claims an `artifact-retry` action and re-uploads/registers
  existing local artifacts without re-running `harbor-runtime`
- artifact retry publishes a best-effort dispatch wake-up signal with
  `action = "artifact-retry"`; runner still claims through control-plane leases,
  so MySQL remains the source of truth
- input materialization downloads have runner-local retry settings
- `harbor-runtime` derives OpenAI messages trajectory files from valid ATIF
  `agent/trajectory*.json` files
- `harbor-runner` collects every ordinary file under `job_dir` for artifact
  storage; unclassified files are recorded as `kind = "artifact"`
- artifact manifests act as metadata overlays for `kind`, `trial_id`, `schema`,
  `content_type`, and custom metadata; they do not limit upload scope
- artifact query supports schema, content type, and relative path prefix filters
- runner execution metadata separates platform job ID, Harbor runtime
  `JobResult.id`, and runner `execution_id`
- COS artifact keys default to the attempt/execution namespace layout, with
  explicit `legacy` layout retained only for migration

Implemented interface groups:

```text
POST /jobs/query
POST /jobs/batch-get
POST /trials/query
POST /artifacts/query
POST /jobs/{job_id}/cancel
GET  /internal/jobs/{job_id}/control
POST /internal/jobs/claim
POST /jobs/{job_id}/retry
POST /jobs/{job_id}/artifacts/retry
```

Trajectory schema lookup:

```text
GET /jobs/{job_id}/trials/{trial_id}/trajectory?schema=atif
GET /jobs/{job_id}/trials/{trial_id}/trajectory?schema=openai_messages
```

Runner artifact storage policy:

```toml
[artifact_storage]
upload_policy = "job_dir_all"
upload_manifest = true
```

`job_dir_all` means all ordinary files inside the runner-local job directory are
collected and uploaded/registered. Symlink files are skipped so collection cannot
escape the job directory through a link target.

Hardening backlog:

- add priority, quota, and fairness rules to claim matching
- extend idempotency records with tenant/auth scope once auth lands
- add auth and tenant scoping before exposing query endpoints broadly

## Phase 10: Cloud Deployment

Replace local services with Tencent Cloud services:

- Docker MySQL -> TencentDB MySQL
- Docker RabbitMQ -> TDMQ for RabbitMQ
- local host runner processes -> TKE runner Pods
- local artifact files -> COS/object storage
- provider runtimes remain selectable: Docker, AGS, TKE, E2B, etc.
