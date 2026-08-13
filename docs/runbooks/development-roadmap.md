# Development Roadmap

## Phase 0: Spec

Write the first formal spec before implementation.

Spec should define:

- project boundaries
- `harbor-runner` interface
- `harbor-api` interface
- MySQL tables
- RocketMQ topic/message schema
- job/trial/runner state machines
- cancellation and retry semantics
- local Docker Compose topology
- cloud replacement path for TencentDB, TDMQ RocketMQ, TKE, and COS

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

No MySQL or RocketMQ in this phase.

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

Create `services/harbor-control-plane/`.

Minimum modules:

- FastAPI app
- config loader
- MySQL repository
- RocketMQ producer
- job schema validation

Initial endpoints:

```text
POST /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/trials
POST /jobs/{job_id}/cancel
GET /runners
```

`POST /jobs` writes MySQL and publishes a RocketMQ message. It does not run Harbor directly.

## Phase 4: Runner MySQL + RocketMQ Integration

Connect `harbor-runner` to the control plane contracts.

Flow:

1. runner registers in MySQL
2. runner heartbeats
3. runner consumes RocketMQ messages in `harbor-runners` consumer group
4. runner obtains job lease from MySQL
5. runner starts `harbor run`
6. runner scans `result.json`
7. runner writes progress to MySQL
8. runner completes/fails/cancels job and acks message

Validate with two runner instances.

## Phase 5: Docker Compose Distributed Dev

Create `deploy/docker-compose/compose.dev.yml` with:

- MySQL
- RocketMQ nameserver
- RocketMQ broker
- optional RocketMQ dashboard
- harbor-api
- harbor-runner-1
- harbor-runner-2

Run real jobs:

- Harbor hello-world
- one otel-bench task
- several otel-bench tasks
- concurrent jobs

## Phase 6: Logs and Artifacts

PoC:

- runner-local `jobs/`
- MySQL has `job_id -> runner_id -> runner_internal_url`
- API proxies logs/artifacts to the runner

Production:

- runner uploads logs/artifacts to object storage
- DB stores artifact keys
- API reads artifacts from object storage

## Phase 7: Synthetic Data Platform

Create `services/synthetic-data-platform/` after Harbor API is stable.

First version:

```text
POST /synthetic-tasks
GET /synthetic-tasks/{id}
GET /synthetic-tasks/{id}/samples
POST /synthetic-tasks/{id}/publish
```

Flow:

1. create synthetic task
2. generate Harbor JobConfig
3. call `harbor-api POST /jobs`
4. store `synthetic_task_id -> harbor_job_id`
5. poll/query Harbor status
6. read artifacts
7. parse samples into business tables
8. review and publish dataset version

## Phase 8: Cloud Deployment

Replace local services with Tencent Cloud services:

- Docker MySQL -> TencentDB MySQL
- Docker RocketMQ -> TDMQ RocketMQ
- local runner containers -> TKE runner Pods
- local artifact files -> COS/object storage
- provider runtimes remain selectable: Docker, AGS, TKE, E2B, etc.
