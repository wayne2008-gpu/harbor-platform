# Harbor Platform Architecture

## Objective

Build a distributed Harbor execution platform that can later be reused by a synthetic data platform.

The target runtime flow is:

```text
synthetic-data-platform
  -> harbor-api
  -> MySQL + RocketMQ
  -> harbor-runner instances
  -> harbor run subprocesses
  -> docker / ags / tke / e2b / other Harbor environments
```

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

`harbor-runner` belongs in the Harbor submodule because it controls `harbor run`, reads Harbor `jobs/` layout, and depends on `JobConfig`, `JobResult`, and `TrialResult` semantics.

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

## PoC Storage Model

In PoC:

- each runner keeps its own local `jobs/` directory
- runner scans `jobs/<job_id>/result.json` and trial directories
- runner writes progress into MySQL
- `harbor-api` queries MySQL for status
- for logs/artifacts, `harbor-api` can route through `job_id -> runner_id -> runner_internal_url`

In production:

- runner uploads logs/artifacts to object storage
- MySQL stores artifact keys
- `harbor-api` reads through object storage instead of runner-local files

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
