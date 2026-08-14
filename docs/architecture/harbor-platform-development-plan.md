# Harbor Platform Development Plan

## Purpose

This document turns the current architecture notes and roadmap into an executable
development plan for the distributed Harbor platform.

The first target is a distributed execution platform:

```text
harbor-api -> MySQL -> RocketMQ -> harbor-runner -> harbor run -> Docker/AGS/TKE
```

The synthetic data platform comes later and must treat `harbor-api` as the only
Harbor integration boundary.

## Current Baseline

- `harbor/` is the active Harbor fork submodule.
- Tencent Cloud AGS and TKE providers already exist inside Harbor.
- AGS and TKE both support image-only datasets where each task declares
  `[environment].docker_image`.
- Harbor already has `JobConfig`, `JobResult`, and `TrialResult` models.
- `harbor run` is an alias for `harbor job start`.
- `harbor job start --config <path> --print-config` can resolve and validate a
  `JobConfig` without running.
- `Job.run()` writes `jobs/<job_name>/config.json`,
  `jobs/<job_name>/result.json`, and trial result directories.
- `services/harbor-control-plane/`, `services/synthetic-data-platform/`, and
  `packages/harbor-service-contracts/` are currently empty project shells.

The runner and API should reuse these Harbor contracts instead of redefining job
and trial result formats.

## Architecture Decisions

### AD-1: Harbor Runner Belongs In The Harbor Submodule

`harbor-runner` must live under `harbor/` because it controls `harbor run`, reads
the local `jobs/` layout, and depends on Harbor's `JobConfig`/`JobResult`
semantics.

The runner should be a thin process supervisor, not a second job scheduler.
Harbor's existing trial scheduler remains responsible for `n_concurrent_trials`.

### AD-2: Control Plane Owns Durable State

`harbor-api` owns MySQL state and RocketMQ publication. It does not run jobs
directly.

MySQL is the source of truth for:

- jobs
- trials
- runners
- leases
- events
- artifact metadata

RocketMQ only dispatches job IDs. Redelivery is expected and must be resolved
through MySQL leases and job state.

### AD-3: Use Full JobConfig As The Execution Contract

The API stores the resolved Harbor `JobConfig` JSON for each job. Runner phase 1
accepts a path to that JSON/TOML config and sets deterministic `job_name` and
`jobs_dir`.

This keeps Docker, AGS, and TKE provider selection inside:

```json
{
  "environment": {
    "type": "ags"
  }
}
```

or:

```json
{
  "environment": {
    "type": "tke"
  }
}
```

### AD-4: Service Contracts Are Shared But Business-Free

`packages/harbor-service-contracts/` may contain job states, runner states,
RocketMQ message schemas, and HTTP request/response models.

It must not contain synthetic data business concepts.

## Component Plan

### Harbor Runner

Location:

```text
harbor/src/harbor/runner/
harbor/src/harbor/cli/runner.py
```

CLI shape:

```bash
uv run harbor runner run-once --job-config /path/job.json
uv run harbor runner start --config runner.toml
```

Phase 1 `run-once` behavior:

- Load and validate `JobConfig`.
- Override `job_name` with the control-plane `job_id`.
- Override `jobs_dir` with runner-local configured storage.
- Start `harbor job start --config <resolved-config>` as a subprocess.
- Record PID, command, start time, and local job directory.
- Poll `jobs/<job_id>/result.json`.
- Return a final snapshot with status, counts, exit code, and result path.
- Support local cancellation by terminating the subprocess group.

Phase 2 daemon behavior:

- Load `runner.toml`.
- Maintain `runner_id`, `jobs_dir`, `max_running_jobs`, and optional
  `runner_internal_url`.
- Run multiple Harbor jobs concurrently up to `max_running_jobs`.
- Periodically scan active job directories.
- Emit progress snapshots through a local interface that Phase 4 can wire to
  MySQL.

Suggested internal modules:

```text
harbor/src/harbor/runner/config.py
harbor/src/harbor/runner/process.py
harbor/src/harbor/runner/snapshot.py
harbor/src/harbor/runner/daemon.py
harbor/src/harbor/runner/cancel.py
```

Runner snapshot contract:

```json
{
  "job_id": "01J...",
  "runner_id": "runner-1",
  "pid": 12345,
  "status": "running",
  "started_at": "2026-08-14T00:00:00Z",
  "updated_at": "2026-08-14T00:01:00Z",
  "finished_at": null,
  "exit_code": null,
  "n_total_trials": 26,
  "n_pending_trials": 10,
  "n_running_trials": 4,
  "n_completed_trials": 11,
  "n_errored_trials": 1,
  "n_cancelled_trials": 0,
  "result_path": "jobs/01J.../result.json"
}
```

### Harbor Control Plane

Location:

```text
services/harbor-control-plane/
```

Recommended stack:

- FastAPI
- Pydantic
- SQLAlchemy 2.x async or SQLModel
- Alembic migrations
- MySQL 8
- RocketMQ adapter behind a small port interface

Initial modules:

```text
src/harbor_control_plane/api/
src/harbor_control_plane/config.py
src/harbor_control_plane/db/
src/harbor_control_plane/repositories/
src/harbor_control_plane/rocketmq/
src/harbor_control_plane/scheduler/
src/harbor_control_plane/contracts/
```

Initial HTTP endpoints:

```text
POST /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/trials
POST /jobs/{job_id}/cancel
GET /runners
```

`POST /jobs` flow:

1. Accept a Harbor `JobConfig` JSON payload or a thin request that can be
   resolved into `JobConfig`.
2. Validate with Harbor's `JobConfig` schema.
3. Generate `job_id`.
4. Store the resolved config in MySQL.
5. Insert a `queued` job event.
6. Publish `{job_id}` to RocketMQ.
7. Return `202 Accepted`.

`POST /jobs/{job_id}/cancel` flow:

1. Set `cancel_requested_at`.
2. Move `queued` jobs to `cancelled` immediately.
3. For `leased`/`running` jobs, let the current runner observe cancellation and
   terminate the local subprocess.
4. Return the updated DB-backed job status.

### Service Contracts

Location:

```text
packages/harbor-service-contracts/
```

Initial contracts:

```text
JobState
TrialState
RunnerState
LeaseState
JobDispatchMessage
JobCreateRequest
JobStatusResponse
TrialStatusResponse
RunnerHeartbeatRequest
RunnerHeartbeatResponse
```

These contracts should be pure Pydantic/Python types until another language
consumer exists. Publish OpenAPI from `harbor-api` for external clients.

### Synthetic Data Platform

Location:

```text
services/synthetic-data-platform/
```

This is deferred until the Harbor API is stable.

Its only Harbor integration should be:

```text
synthetic_task_id -> harbor_job_id
```

It must not import Harbor runner internals or read runner-local `jobs/`.

## MySQL Schema Draft

### `jobs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | varchar(32) pk | Control-plane job ID; also Harbor `job_name` |
| `state` | varchar(32) | See job state machine |
| `job_config_json` | json | Resolved Harbor `JobConfig` |
| `provider` | varchar(32) | `docker`, `ags`, `tke`, etc. derived from config |
| `runner_id` | varchar(128) null | Current owner |
| `lease_id` | varchar(64) null | Current lease |
| `lease_expires_at` | datetime null | Lease timeout |
| `cancel_requested_at` | datetime null | Cancellation marker |
| `started_at` | datetime null | Runner start time |
| `updated_at` | datetime | Last state/progress update |
| `finished_at` | datetime null | Terminal time |
| `error_type` | varchar(128) null | Terminal error class |
| `error_message` | text null | Terminal error detail |
| `result_json` | json null | Latest job summary snapshot |
| `created_at` | datetime | Insert time |

Indexes:

- `(state, created_at)`
- `(runner_id, state)`
- `(lease_expires_at)`
- `(updated_at)`

### `trials`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | varchar(128) pk | Stable trial ID/name |
| `job_id` | varchar(32) fk | Parent job |
| `task_name` | varchar(255) | Harbor task |
| `agent_name` | varchar(128) | Agent |
| `model_name` | varchar(255) null | Model |
| `state` | varchar(32) | See trial state machine |
| `attempt` | int | Attempt number when known |
| `reward` | double null | Primary reward when available |
| `exception_type` | varchar(128) null | Exception class |
| `result_json` | json null | Latest `TrialResult` |
| `started_at` | datetime null | Start time |
| `updated_at` | datetime | Last update |
| `finished_at` | datetime null | Terminal time |

Indexes:

- `(job_id, state)`
- `(job_id, task_name)`

### `runners`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | varchar(128) pk | Runner ID |
| `state` | varchar(32) | `online`, `draining`, `offline` |
| `hostname` | varchar(255) | Host/container identity |
| `version` | varchar(64) | Harbor runner version |
| `jobs_dir` | varchar(1024) | Local jobs dir |
| `max_running_jobs` | int | Runner concurrency |
| `running_jobs` | int | Last heartbeat count |
| `internal_url` | varchar(1024) null | PoC log/artifact proxy |
| `capabilities_json` | json | Providers or tags |
| `last_heartbeat_at` | datetime | Heartbeat timestamp |
| `created_at` | datetime | First registration |
| `updated_at` | datetime | Last update |

Indexes:

- `(state, last_heartbeat_at)`

### `job_events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint pk auto increment | Event ID |
| `job_id` | varchar(32) fk | Job |
| `runner_id` | varchar(128) null | Runner |
| `event_type` | varchar(64) | `queued`, `leased`, `snapshot`, etc. |
| `payload_json` | json null | Event detail |
| `created_at` | datetime | Event time |

Index:

- `(job_id, created_at)`

### `artifacts`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint pk auto increment | Artifact row |
| `job_id` | varchar(32) fk | Job |
| `trial_id` | varchar(128) null | Trial artifact when applicable |
| `kind` | varchar(64) | `log`, `trajectory`, `result`, `verifier` |
| `storage_type` | varchar(32) | `runner-local` for PoC, `cos` later |
| `storage_key` | varchar(2048) | Path or object key |
| `size_bytes` | bigint null | Size when known |
| `created_at` | datetime | Insert time |

## State Machines

### Job States

```text
queued
  -> leased
  -> running
  -> succeeded
  -> failed
  -> cancelled
  -> timed_out
```

Allowed transitions:

- `queued -> cancelled` when cancellation happens before lease.
- `queued -> leased` when a runner obtains a lease.
- `leased -> running` when subprocess starts.
- `leased -> queued` when lease expires before start.
- `running -> succeeded` when Harbor exits 0 and all required results exist.
- `running -> failed` when subprocess exits nonzero or result parsing fails.
- `running -> cancelled` when runner completes cancellation.
- `running -> timed_out` when runner or API timeout policy fires.
- Terminal states are immutable except for adding artifact metadata.

### Trial States

```text
pending -> running -> succeeded | failed | cancelled
```

Trial state is derived from Harbor result snapshots. The control plane should not
invent trial state that is not observable from runner snapshots.

### Runner States

```text
online -> draining -> offline
online -> offline
```

Rules:

- Missing heartbeat beyond threshold marks runner `offline`.
- `draining` runners keep existing jobs but do not acquire new leases.
- A runner restart may reuse the same `runner_id` only if it can reconcile its
  local `jobs_dir`.

## RocketMQ Contract

Topic:

```text
harbor.jobs
```

Consumer group:

```text
harbor-runners
```

Message body:

```json
{
  "schema_version": 1,
  "message_id": "01J...",
  "job_id": "01J...",
  "created_at": "2026-08-14T00:00:00Z",
  "routing": {
    "provider": "ags",
    "tags": []
  }
}
```

Runner behavior:

1. Receive message.
2. Read job from MySQL.
3. If job is not `queued`, ack and ignore.
4. Try to atomically lease the job.
5. If lease fails, ack and ignore.
6. Start local Harbor subprocess.
7. Write progress snapshots to MySQL.
8. Mark terminal state.
9. Ack message only after terminal state or deliberate non-ownership decision.

## Lease Rules

Lease acquisition should be a single conditional update:

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

The update succeeds only when exactly one row is affected.

Running jobs should renew lease while the subprocess is alive. If the lease
expires, another runner may reclaim only after it confirms the old runner is
offline and the job is not still running locally.

## Cancellation And Retry

Cancellation:

- API records cancellation intent in MySQL.
- Runner polling loop observes `cancel_requested_at`.
- Runner terminates the subprocess group.
- Runner writes final cancelled state and preserves partial result artifacts.

Retry:

- Harbor's existing `retry` config handles trial-level retry.
- Control-plane job retry should be explicit and create either:
  - a new job with `source_job_id`, or
  - a new lease attempt only when the previous runner died before starting.
- Do not silently rerun a completed failed Harbor job under the same `job_id`.

## Logs And Artifacts

PoC:

- Runner keeps local `jobs/<job_id>/`.
- MySQL stores `job_id -> runner_id -> runner_internal_url`.
- API can proxy files from the runner for debugging.

Production:

- Runner uploads artifacts to COS/object storage.
- MySQL stores artifact keys and metadata.
- API reads from object storage.

Artifact collection should start with:

- `config.json`
- `result.json`
- trial `result.json`
- `exception.txt`
- agent logs requested by JobConfig
- verifier logs requested by JobConfig

## Security And Configuration

Do not store provider secrets in MySQL job configs.

Allowed secret flow:

- AGS/TKE/Codex credentials live in runner environment, mounted config, or
  secret manager.
- `JobConfig` may reference environment variable names.
- `harbor-api` should redact sensitive agent/verifier env values before logging.

Runner containers need:

- Docker access for Docker provider when enabled.
- AGS config and CAM/E2B-compatible environment variables for AGS.
- kubeconfig and image pull secret access for TKE.
- OpenAI-compatible agent credentials when running Codex or other API agents.

## Implementation Phases

### Phase 0: Formal Spec And Contracts

Deliverables:

- This document reviewed and accepted as the baseline.
- Create shared contract package skeleton.
- Define enum names and serialized values.
- Draft Alembic migration for the schema above.
- Add API OpenAPI sketch or Pydantic request/response models.

Validation:

- Contract unit tests for state transitions.
- JSON round-trip tests for RocketMQ messages and API payloads.

### Phase 1: Harbor Runner Run-Once

Deliverables:

- `uv run harbor runner run-once --job-config /path/job.json`.
- Process supervisor with PID tracking.
- Deterministic `job_name = job_id`.
- Polling parser for `result.json`.
- Cancellation primitive.
- Unit tests with a fake subprocess and fake result files.

Validation:

```bash
cd harbor
uv run pytest tests/unit/runner -q
uv run harbor job start --config <fixture> --print-config
uv run harbor runner run-once --job-config <fixture>
```

### Phase 2: Harbor Runner Daemon

Deliverables:

- `uv run harbor runner start --config runner.toml`.
- In-memory queue for local jobs.
- `max_running_jobs`.
- Periodic snapshots.
- Graceful shutdown and draining.

Validation:

- Two local jobs run concurrently up to configured limit.
- Cancelling one job does not kill the runner or other jobs.
- Restart can read existing job directories and report terminal snapshots.

### Phase 3: Harbor API

Deliverables:

- FastAPI app.
- Config loader.
- MySQL repository.
- Alembic migrations.
- In-memory RocketMQ fake for tests.
- Initial endpoints:
  - `POST /jobs`
  - `GET /jobs/{job_id}`
  - `GET /jobs/{job_id}/trials`
  - `POST /jobs/{job_id}/cancel`
  - `GET /runners`

Validation:

- API unit tests against transactional MySQL test DB or testcontainers.
- `POST /jobs` inserts DB rows and publishes one dispatch message.
- Duplicate/invalid job configs fail before publication.

### Phase 4: Runner MySQL And RocketMQ Integration

Deliverables:

- Runner registration and heartbeat.
- RocketMQ consumer.
- MySQL lease acquisition and renewal.
- Snapshot writer.
- Cancellation polling.
- Terminal status writer.

Validation:

- Redelivered message for completed job is acked and ignored.
- Two runners receiving the same job produce one lease winner.
- Runner crash before start returns job to `queued` after lease expiry.
- Running job cancellation terminates local subprocess and updates DB.

### Phase 5: Docker Compose Distributed Dev

Deliverables:

```text
deploy/docker-compose/compose.dev.yml
```

Services:

- MySQL
- RocketMQ nameserver
- RocketMQ broker
- optional RocketMQ dashboard
- harbor-api
- harbor-runner-1
- harbor-runner-2

Validation jobs:

- Harbor hello-world on Docker.
- One otel-bench task on AGS or TKE when credentials are available.
- Several otel-bench tasks.
- Concurrent jobs across two runners.

### Phase 6: Logs And Artifacts

Deliverables:

- Runner-local artifact manifest.
- API artifact list endpoint.
- PoC artifact proxy.
- COS upload interface behind storage port.

Validation:

- API can fetch job `result.json`, trial `result.json`, agent logs, and verifier
  logs after job completion.

### Phase 7: Synthetic Data Platform

Deliverables:

- Synthetic task CRUD.
- Harbor job creation adapter.
- `synthetic_task_id -> harbor_job_id` mapping.
- Sample ingestion from Harbor artifacts.
- Review and publish flow.

Validation:

- Synthetic platform never imports `harbor.runner` or reads runner-local files.

### Phase 8: Tencent Cloud Deployment

Deliverables:

- TencentDB MySQL config.
- TDMQ RocketMQ config.
- TKE deployment manifests for API and runners.
- COS artifact storage.

Validation:

- One API active/standby deployment.
- Multiple TKE runner pods.
- AGS/TKE provider jobs run from cloud runners.

## Immediate Next Work

1. Implement the shared contracts package skeleton.
2. Add `harbor runner run-once` in the Harbor submodule.
3. Add runner unit tests around subprocess lifecycle and result scanning.
4. Add a minimal control-plane FastAPI skeleton only after run-once is stable.

This order keeps the highest-risk part, the boundary between Harbor's existing
job execution and a distributed runner, small and testable before adding MySQL
and RocketMQ.
