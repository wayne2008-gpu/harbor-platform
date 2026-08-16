# Harbor Platform Architecture

## Objective

Build a distributed Harbor execution platform that can later be reused by a synthetic data platform.

The target runtime flow is:

```text
synthetic-data-platform
  -> harbor-api
  -> MySQL + RocketMQ
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
  services/
    harbor-control-plane/          # future harbor-api and scheduler project
    synthetic-data-platform/       # future synthetic data business platform
  packages/
    harbor-service-contracts/      # future shared schemas/contracts
  deploy/
    docker-compose/                # local distributed dev environment
    k8s/                           # future TKE manifests
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

`services/harbor-control-plane/` will be a separate service project inside this monorepo.

It owns:

- `harbor-api` HTTP service
- MySQL schema and migrations
- RocketMQ producer/consumer adapters
- runner registry, heartbeat, lease, and retry logic
- job cancellation and status APIs
- deployment configuration

`harbor-api` should not run jobs directly. It writes DB state, publishes RocketMQ messages, and returns DB-backed job status.

### Synthetic Data Platform

`services/synthetic-data-platform/` is a business platform above Harbor. It owns:

- synthetic task management
- data source management
- prompt/template management
- sample ingestion and quality review
- dataset versions and publishing
- cost/business reporting

It should call `harbor-api` and store `synthetic_task_id -> harbor_job_id` mappings. It should not read runner-local files or import Harbor runner internals.

## State and Dispatch

Use MySQL as the state source:

- jobs
- trials
- runners
- runner leases
- job events
- artifact metadata

Use RocketMQ as the dispatch channel:

- topic: Harbor jobs
- message body: `job_id` plus minimal routing metadata
- consumer group: Harbor runners

RocketMQ does not own durable job state. If a message is redelivered, the runner must consult MySQL lease/status before executing.

`harbor-api` does not directly call a specific `harbor-runner` for job dispatch. It writes MySQL state and publishes a RocketMQ message. `harbor-runner` instances consume messages or poll queued jobs, obtain a MySQL-backed lease, then invoke the local `harbor-runtime`.

## PoC Storage Model

Detailed COS artifact storage design lives in [`cos-artifact-storage-design.md`](cos-artifact-storage-design.md).
Detailed COS input dataset materialization design lives in
[`cos-input-dataset-materialization-design.md`](cos-input-dataset-materialization-design.md).

The platform currently supports two artifact storage modes:

- `runner-local`: default local development mode. Each runner keeps its own local `jobs/` directory and `harbor-api` may serve files only from an explicitly allowed local root.
- `cos`: production-oriented mode. `harbor-runner` uploads collected artifacts to Tencent Cloud COS, records `cos://<bucket>/<key>` metadata in MySQL, and `harbor-api` serves either signed URLs or proxy streams.

In both modes:

- runner scans `jobs/<job_id>/result.json` and trial directories after execution
- runner records artifact rows through `harbor-api`
- MySQL remains the artifact index
- `synthetic-data-platform` reads results and trajectories through `harbor-api`, not runner-local paths or COS credentials

COS configuration is TOML-based in the current iteration, including literal COS credentials. Replacing credential fields with env/K8s Secret references is a later hardening step.

Trajectory files, trial results, logs, task artifacts, and runner manifests are all treated as artifact records. `kind = "trajectory"` is reserved for agent trajectory JSON files.

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
- RocketMQ nameserver
- RocketMQ broker
- optional RocketMQ dashboard
- harbor-api
- multiple harbor-runner containers

Production replaces these with:

- TencentDB MySQL
- TDMQ RocketMQ
- TKE harbor-api active/standby
- TKE harbor-runner deployment
- COS/object storage for artifacts
