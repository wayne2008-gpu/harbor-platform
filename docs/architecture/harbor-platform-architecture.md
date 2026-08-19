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
- generation usage, cost, and business reporting
- user-facing API request tracing and business audit events

It should call `harbor-api` and store `synthetic_task_id -> harbor_job_id` mappings. It should not read runner-local files or import Harbor runner internals.

Task detail diagnostics are also Harbor-backed. The synthetic platform exposes
task event timelines and run log previews by querying Harbor job/trial/artifact
metadata through `harbor-api`; log bytes are fetched through the artifact content
proxy and returned as bounded previews plus download URLs. The web console never
needs runner-local paths or COS credentials.

OpenAI message trajectory review has a Synthetic-owned structured index.
`POST /synthetic-tasks/{id}/trials/{trial_id}/trajectory/messages/sync` reads the
Harbor `schema=openai_messages` trajectory artifact, normalizes messages into
`synthetic_trajectory_messages`, and replaces the task/trial/schema rows
idempotently. `GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory/messages`
queries those rows by schema, role, search text, limit, and offset. `GET
/synthetic-tasks/{id}/trials/{trial_id}/trajectory/messages/summary` returns
aggregate-only counts for the same schema/role/search surface, including role
buckets, tool-call volume, tool-response volume, missing tool IDs, empty content,
unknown roles, and error-signal rows without returning message content.
`GET /reviews/trials` and `GET /reviews/summary` surface the indexed OpenAI
message summary as trial-level review evidence, so Workbench triage can show
message issue counts without opening every trial detail page. The task detail
trajectory review queue also prefers the task-scoped `/reviews/trials` service
view and falls back to local trial/artifact derivation while service evidence is
unavailable. Result dataset detail reuses task-scoped `/reviews/summary` to show
source-trial review coverage, guidance, trajectory/OpenAI-message evidence, and
priority review links before a published dataset is handed off for training.
`GET/PUT /result-datasets/{id}/review-decision` stores the human acceptance
decision for a published result dataset separately from automatic quality
signals, with audit records tied to the source task and result dataset.
The Results inventory also loads saved acceptance decisions for visible result
datasets and shows the decision state next to export readiness, so operators can
triage handoff state before opening detail pages.
`GET /result-datasets` and `GET /result-datasets/summary` accept an
`acceptance_state` filter for approved, needs-review, rejected, blocked, and
unreviewed result datasets, and the summary response includes acceptance state
counts over the same filtered inventory.
`POST /result-datasets/review-decisions/batch` applies one acceptance decision
to explicit result dataset IDs or to a bounded Results filter selection guarded
by `expected_total`, then records a batch audit event with the selected result
dataset IDs, source task IDs, sample counts, reviewer, labels, and request ID.
Result dataset detail shows a post-training handoff summary that combines human
acceptance, export/download readiness, automatic delivery checks, and source
trial quality into one operator-facing decision before downstream training use.
The Results inventory can batch-query source-trial quality for visible result
datasets and materialize the computed snapshot into
`synthetic_result_dataset_source_trial_quality`. `GET /result-datasets` and
`GET /result-datasets/summary` accept a `source_trial_quality` filter for ready,
needs-review, blocked, and unavailable result datasets, with summary buckets over
the same filtered inventory. Source-trial quality snapshots are refreshed by the
batch query path and by source review/message/publish write paths; result
datasets without a materialized snapshot are treated as `unavailable`.

Dataset inventory observability is Synthetic-owned. `GET /datasets/summary`
summarizes dataset count, task-name coverage, COS/uploaded/registered/external
source mix, checksum/size coverage, format buckets, task-name buckets, and recent
dataset updates over the same filters as `GET /datasets`, so the Datasets
console does not derive launch readiness from one paginated page.

Result dataset inventory observability is Synthetic-owned. `GET
/result-datasets/summary` summarizes result dataset count, sample scale, source
task/dataset coverage, sample-count buckets, source dataset buckets, and recent
published results over the same filters as `GET /result-datasets`, so the
Results console does not derive list-level readiness from a single paginated
page. The same result inventory APIs also expose `handoff_readiness`, combining
sample presence, export/download readiness, and saved acceptance decisions into
Ready / Needs review / Blocked / Checking queues for batch result triage.
Source-trial quality is a separate materialized inventory dimension available
through `source_trial_quality` filters once snapshots exist.
Result sample field-profile observability is Synthetic-owned. `GET
/result-datasets/{id}/samples/field-profile` and `GET
/synthetic-tasks/{id}/samples/field-profile` summarize field coverage, missing
counts, type buckets, and example values over the same server-side sample
search, quality-flag, and review-decision filters as the sample list and summary
APIs, so Result Detail
does not derive full dataset field coverage from one paginated browser page.
Sample review decisions are Synthetic-owned. `POST
/synthetic-tasks/{id}/samples/review-decisions/batch` and `POST
/result-datasets/{id}/samples/review-decisions/batch` apply one human decision
to a bounded server-side sample filter selection guarded by `expected_total`.
Sample list, summary, field-profile, and batch-review APIs accept
`review_decision=approved|needs_review|rejected|blocked|unreviewed`, which can
be combined with `quality_flag` and search filters. Decisions are stored in
sample `_review` metadata, negative decisions contribute `review_needs_review`,
`review_rejected`, or `review_blocked` quality flags, and automatic quality
signals remain intact so approval does not silently override missing content,
missing reward, or low reward checks.
Task and Result sample tables render saved sample review decisions separately
from automatic anomaly badges, so operators can see the human decision, reviewer,
and update time without letting `_review` metadata pollute dynamic sample field
profiles or training payload columns.
Result dataset downloads and export records are sample-scope aware. Direct
downloads and export creation can use the same sample filters as review,
including approved-only selection for training handoff. Export records persist a
reserved `sample_selection` metadata block with filters, source sample count,
and matching sample count so API stream downloads and COS/background exports can
reproduce the requested scope and detect selection drift before upload.
Generation usage observability is Synthetic-owned. `/workbench/summary` embeds a
`generation_metrics` snapshot, and `GET /generation-metrics/summary` exposes the
same rollup directly. The snapshot summarizes task/result counts, generated
sample yield, observed terminal-task runtime, runtime/model/provider buckets, and
reported token usage from durable result metadata. Result publish stores a
`generation_metrics` metadata snapshot from the source task job config and Harbor
trial-result usage fields when they are present. Synthetic can also compute an
estimated `cost_estimate` from configured `generation_cost` model prices. No
provider prices are built into the platform; deployments must provide prices from
their own billing contract, and unmatched model tokens remain visible instead of
being silently treated as real zero-cost usage. Task detail result reads also
return a live task-level `generation_metrics` object with the same cost estimate
contract, derived from the task job config plus current Harbor job/trial evidence.
Generation cost config can optionally define summary/task budget thresholds in
the same micro-unit as `estimated_cost_micros`, and can carry an operator-defined
`price_table_version`; cost estimate responses expose the version and a derived
`budget_status` for operator visibility in Workbench and Task Detail. The web
console surfaces the current price table version alongside live Workbench and
Task Detail cost estimates.
When a result dataset is published, Synthetic also stores a
`generation_cost_snapshot` in result metadata, freezing the publish-time
task-scope estimate, price table version, and budget status with a safe config
summary. Dynamic Workbench estimates can change with current configuration;
published result metadata remains a handoff audit snapshot. Result Detail
surfaces that frozen snapshot as the handoff cost view, so already-published
result datasets are not recalculated against later price-table or
budget-threshold changes.
This is still an estimate layer: final account-level billing reconciliation,
full price-rule history, and invoice-grade attribution remain later Synthetic
business-reporting work.
Result dataset export delivery is also Synthetic-owned. The synthetic platform
can create JSONL/JSON export records for published result datasets, either as
`api_stream` records pointing at the existing download endpoint or as COS-backed
objects with `storage_uri`, size, checksum, and safe storage metadata persisted
in its own export history table. COS-backed exports can be created in background
mode, moving records through `pending` / `running` / `completed` or `failed`
without blocking the request that created the export. Failed or stale
non-completed export records can be retried through the record-level retry API,
which reuses the same export ID and requeues COS materialization. Production
deployments can run `synthetic-result-export-worker` as a separate process:
the API creates pending rows, worker instances atomically claim pending or stale
running COS exports from MySQL, materialize JSONL/JSON from paged sample reads,
upload the object, and update the same export record. This is separate from
Harbor artifact storage: the web console reads export metadata and record-level
download entry points through the Synthetic API, and COS-backed export downloads
are proxied by Synthetic API using server-side storage configuration. The
browser never needs runner-local paths or COS credentials.

Synthetic task inventory observability is also Synthetic-owned. `GET
/synthetic-tasks/summary` summarizes task count, active/completed/failed state,
result dataset readiness, publish candidates, missing dataset links,
state/runtime/dataset buckets, and recent updates over the same filters as
`GET /synthetic-tasks`, so the Tasks console does not derive run readiness from
one paginated page.

The Synthetic API returns `X-Request-ID` on all responses and includes
`request_id` in error bodies for HTTP, validation, Harbor proxy, and auth errors.
Critical business operations are persisted as `synthetic_audit_events`, including
dataset create/register/upload, synthetic task create/cancel/retry/artifact retry,
sample ingest, result dataset publish/download/export, trial review decision
updates, result dataset acceptance decision updates, and artifact download
access. These audit rows are owned by the synthetic platform and complement,
rather than replace, control-plane `api_audit_events`.
The synthetic platform exposes `GET /audit-events` and a first-class Audit
console page so operators can troubleshoot by request ID, action, resource, task,
result dataset, status, actor, and search filters.
It also exposes `GET /audit-events/summary` for aggregate-only audit
observability over the same filters, returning total/succeeded/failed counts,
status/action/resource-type buckets, and recent failed events without requiring
the console to derive those values from one paginated page.
The Workbench reads recent `result_dataset_review_decision.batch_upsert` audit
events and links back to filtered Audit views, so batch acceptance activity is
visible from the operational landing page.
The Workbench also reads `GET /result-datasets/summary` to show result
acceptance backlog counts, prioritize unreviewed/needs-review/blocked result
datasets in next actions, and deep-link operators back to the matching Results
filters before downstream training handoff.
The Workbench also queries `GET /operations/idempotency/summary` and `GET
/operations/idempotency` to show cancel/retry/artifact-retry reservation health,
operation-level status, and recent reservation records. The record list returns
short reservation references, task/operation/status, response task links, error
summaries, and timestamps without exposing idempotency keys, request payloads, or
Harbor operation parameters.
The Audit console exposes the same reservation records behind
`/audit?view=operations` with deep-linkable operation, status, task, search, and
pagination controls. Its summary panel calls `GET
/operations/idempotency/summary` with the same operation/status/task/search
filters as the record list, so filtered triage counts and paginated rows describe
the same reservation set while keeping idempotency debugging under the governance
section instead of adding Harbor runner internals to primary navigation.

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
- `synthetic-data-platform` reads results, trajectories, and run log previews
  through `harbor-api`, not runner-local paths or COS credentials
- `synthetic-data-platform` may persist derived, business-facing indexes such as
  OpenAI message trajectory rows, but the original artifact bytes remain owned
  by Harbor artifact storage

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
review-decision writes. A separate `[end_user_permissions]` gate can treat
`X-End-User` as the authenticated upstream identity and enforce coarse
end-user `read` / `write` permissions; `write` also satisfies read-only routes.
This remains a minimum deployment gate, not a replacement for future user
login and fine-grained RBAC.
Synthetic API requests propagate `X-Request-ID` and `X-End-User` to harbor-api
calls. Control-plane API calls are persisted as `api_audit_events` with tenant,
service principal, optional end user, scopes, required scope, path, status,
request ID, and derived job ID; internal callers can query them through
`POST /internal/audit-events/query`. Cancel/retry/artifact-retry idempotency
records are persisted with tenant scope so replay behavior is isolated per
tenant.
The production E2E smoke can send bearer/custom auth and tenant headers to
synthetic API, harbor API, and Web independently. When the frontend live check is
enabled, it can also assert that browser `/api/` requests include the configured
Web auth and tenant headers without printing token values.

The Synthetic Settings API may expose aggregate auth readiness, such as whether
auth is enabled, whether anonymous access is active, configured/missing token
counts, scope coverage, tenant-scoped/global token counts, tenant header name,
and end-user permission gate counts. It must not expose bearer token values,
token environment variable names, tenant IDs, tenant environment variable
names, configured end-user names, or signed URLs.
Workbench readiness should surface the same Synthetic API auth posture so the
first screen shows whether the deployment is anonymous, scoped, or missing
read/write token coverage before operators start new synthesis runs.

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
