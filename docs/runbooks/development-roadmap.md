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

- Local TOML config can still use literal `secret_id` and `secret_key` for
  compatibility. Production examples use `secret_id_env`, `secret_key_env`, and
  optional `session_token_env`, with Kubernetes Secrets injecting the referenced
  environment variables.
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

- add scheduled local retention cleanup beyond immediate `retain_local = false`
- add real-COS integration smoke gated by credentials

## Phase 7: Synthetic Data Platform

Create `synthetic-data-platform/` after Harbor API is stable.

Current first version:

```text
POST /datasets/register
POST /datasets/upload
GET /datasets
GET /datasets/summary
GET /datasets/{id}
POST /synthetic-tasks
GET /synthetic-tasks/summary
GET /synthetic-tasks/{id}
GET /synthetic-tasks/{id}/samples
GET /synthetic-tasks/{id}/samples/summary
GET /synthetic-tasks/{id}/results
GET /synthetic-tasks/{id}/events
GET /synthetic-tasks/{id}/logs
GET /synthetic-tasks/{id}/artifacts
GET /synthetic-tasks/{id}/trials
GET /synthetic-tasks/{id}/trials/{trial_id}/result
GET /synthetic-tasks/{id}/trials/{trial_id}/artifacts
GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory
GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory?schema=openai_messages
POST /synthetic-tasks/{id}/trials/{trial_id}/trajectory/messages/sync
GET /synthetic-tasks/{id}/trials/{trial_id}/trajectory/messages
GET /synthetic-tasks/{id}/trials/{trial_id}/review-decision
PUT /synthetic-tasks/{id}/trials/{trial_id}/review-decision
GET /reviews/trials
POST /reviews/trials/batch-decision
POST /synthetic-tasks/{id}/cancel
POST /synthetic-tasks/{id}/retry
POST /synthetic-tasks/{id}/artifacts/retry
POST /synthetic-tasks/{id}/publish
GET /result-datasets
GET /result-datasets/summary
GET /result-datasets/{id}
GET /result-datasets/{id}/samples/summary
GET /result-datasets/{id}/download?format=jsonl
GET /result-datasets/{id}/download?format=json
GET /settings
GET /runtime-capabilities
GET /audit-events
GET /operations/idempotency/summary
```

Synthetic API governance baseline:

- every response includes `X-Request-ID`
- error bodies include `request_id` for HTTP, validation, Harbor proxy, and auth
  failures
- the web console preserves `ApiError.requestId` and shows it in shared error
  states
- key write/download actions are persisted to `synthetic_audit_events` with
  action, resource, task/result dataset IDs, actor, metadata, and request ID

`GET /synthetic-tasks/{id}/samples` keeps the legacy full-list response when no
pagination parameters are provided. For UI-scale review it also accepts
`search`/`q`, `limit`, and `offset`, and returns `X-Total-Count`, `X-Offset`,
and `X-Limit` headers.

Flow:

1. create synthetic task
2. generate Harbor JobConfig
3. call `harbor-api POST /jobs`
4. store `synthetic_task_id -> harbor_job_id`
5. poll/query Harbor status
6. read trial results, trajectory, and artifact metadata through `harbor-api`
7. parse samples into business tables when sample artifacts exist, or derive one
   training sample from `trajectory` artifacts with `metadata.schema =
   "openai_messages"`
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
18. save and reload manual trial review decisions for trajectory audit
19. expose configured runtime/provider capabilities for task creation and
    deployment readiness checks
20. persist synthetic operation idempotency for cancel, retry, and artifact
    retry so repeated client requests return the first task result without
    duplicating synthetic retry records
21. review trials from a first-class Reviews queue with state/task/runtime/schema/
    quality flag/reviewer filters and URL-restorable pagination
22. read Workbench operational rollups from a repository summary snapshot instead
    of app-layer wide-list aggregation
23. trace Synthetic API failures with request IDs and persist business audit
    events for dataset/task/review/publish/download mutations
24. query synthetic audit events by request ID, action, resource, task/result
    dataset, status, actor, search text, and pagination from the web console
25. inspect Harbor-derived task event timelines and run log previews from the
    synthetic task detail page without giving the web console runner-local paths
    or COS credentials
26. sync OpenAI message trajectory artifacts into Synthetic-owned structured
    message rows and query them by schema, role, search text, and pagination
27. consume structured OpenAI message rows in the Trial Detail frontend with
    explicit index sync, server-side role/search pagination, and URL-restorable
    controls
28. apply one review decision to multiple current-page review queue trials from
    the Reviews console and persist the batch operation as a single audit event
29. apply one review decision to all trial reviews matching the current Reviews
    filters, with expected-count protection before persistence
30. read task/result sample quality summaries from backend endpoints so quality
    metrics are not derived from only the current browser page
31. compute task/result sample quality summaries through repository-level
    contracts and SQL sample-row aggregation, with legacy JSON fallback
32. expire stale synthetic operation idempotency reservations through a
    configurable TTL so `in_progress` records cannot block retry forever
33. query sample quality flags through structured `sample_id + flag` rows and
    indexes instead of scanning `quality_flags_text`
34. observe synthetic operation idempotency status through aggregate summary
    counts by operation, stale reservation, and expired reservation state
35. record audit events for completed operation idempotency replays so duplicate
    client requests keep their own request ID and actor trail without exposing
    idempotency keys
36. record failed Synthetic API mutation requests as audit events without
    storing request payloads or idempotency keys
37. surface operation idempotency health in the Workbench so operators can see
    failed, stale, and expired reservation aggregates without querying APIs
    manually
38. summarize Synthetic API audit events through a repository-backed endpoint
    and surface aggregate status/action/resource views in the Audit console
39. summarize result dataset inventory, sample scale, source dataset coverage,
    and latest published results from a backend endpoint instead of deriving
    list-level readiness from one paginated browser page
40. summarize synthetic task inventory, active/completed/failed state, result
    dataset readiness, runtime mix, dataset coverage, and recent updates from a
    backend endpoint instead of deriving task readiness from one paginated
    browser page
41. summarize dataset inventory, COS/uploaded/external source mix, task-name
    coverage, checksum/size coverage, and latest dataset updates from a backend
    endpoint instead of deriving dataset readiness from one paginated browser
    page
42. surface Synthetic API auth readiness in Settings through aggregate token,
    scope, tenant, and anonymous-access flags without exposing bearer tokens or
    environment variable names
43. surface Synthetic API auth readiness in Workbench summary and fallback
    readiness so production exposure risks are visible from the first screen

Current sample ingestion behavior:

- `kind = "sample"` / `kind = "samples"`: accepts either a JSON list, a JSON
  object with `samples`, or one JSON object as one sample.
- `kind = "trial-result"`: only imports the `samples` field when it is present.
- `kind = "trajectory"` with `metadata.schema = "openai_messages"`: imports one
  sample shaped as `{sample_type, messages, source_artifact}` for downstream
  post-training data review and JSONL export.

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
- Synthetic dataset upload now validates archive catalog before COS upload:
  archives must be readable tar files with safe members and at least one
  `task.toml`; explicit `task_names` must exist in that catalog.

Hardening backlog:

- add scheduled retention cleanup beyond immediate `retain_local = false`
- add real-COS integration smoke gated by credentials

## Phase 9: Control Plane Operations

Current target:

- external callers can query jobs, trials, and artifacts through cursor-based
  query endpoints instead of broad list calls
- cancellation has explicit request metadata and a `cancelling` execution state
- runners can poll job control and terminate `harbor-runtime` on cancel request
- runners can claim jobs through `POST /internal/jobs/claim`; claim owns
  capability matching and lease creation in one control-plane operation
- jobs carry `queue` and `priority`; claim matching orders higher-priority jobs
  first and supports runner-provided `queues` plus per-queue `queue_quotas`
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
- `harbor-runtime` writes fallback ATIF `agent/trajectory.json` files from
  trial results when an agent does not emit native ATIF, then derives OpenAI
  messages sidecars from `agent/trajectory*.json`
- `harbor-runner` collects every ordinary file under `job_dir` for artifact
  storage; unclassified files are recorded as `kind = "artifact"`
- artifact manifests act as metadata overlays for `kind`, `trial_id`, `schema`,
  `content_type`, and custom metadata; they do not limit upload scope
- artifact query supports schema, content type, and relative path prefix filters
- runner execution metadata separates platform job ID, Harbor runtime
  `JobResult.id`, and runner `execution_id`
- COS artifact keys default to the attempt/execution namespace layout, with
  explicit `legacy` layout retained only for migration
- control-plane startup reconciles additive legacy schema gaps for
  `jobs.priority`, `jobs.queue`, and their claim scheduling indexes
- runner control-plane polling treats transient claim/queue lookup failures as
  retryable, so a brief `harbor-api` restart does not terminate keep-alive
  runners
- control-plane startup runs Alembic migrations to head for versioned databases;
  existing unversioned local schemas are reconciled and stamped to head
- control-plane API calls are persisted as service-to-service audit events with
  tenant, principal, token scopes, required scope, path, status code, request ID,
  client metadata, and derived job ID

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
POST /internal/audit-events/query
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

- add full user/session auth, fine-grained RBAC, and end-user audit correlation
  before exposing query endpoints to end users directly
- define production migration rollout rules for TencentDB, including backup,
  rollback, and multi-version service compatibility checks

## Phase 10: Cloud Deployment

Replace local services with Tencent Cloud services:

- Docker MySQL -> TencentDB MySQL
- Docker RabbitMQ -> TDMQ for RabbitMQ
- local host runner processes -> TKE runner Pods
- local artifact files -> COS/object storage
- provider runtimes remain selectable: Docker, AGS, TKE, E2B, etc.

Deployment contract and rollout checklist:

- [`tencent-cloud-deployment-runbook.md`](tencent-cloud-deployment-runbook.md)

Implementation milestones:

1. M33: add production `.example.toml` templates in the component repos without
   real secrets. Current status: implemented in
   `harbor-control-plane/config/control-plane.production.example.toml`,
   `synthetic-data-platform/config/platform.production.example.toml`,
   `harbor/config/runner.production.example.toml`, and
   `harbor/config/tke.production.example.toml`.
2. M34: add TKE namespace/RBAC manifests for runner-managed agent-runtime Pods.
   Current status: implemented in `deploy/k8s/base`.
3. M35: add TKE Deployment/Service manifests for `harbor-api`, synthetic API/Web,
   and `harbor-runner`. Current status: implemented in `deploy/k8s/base`, with
   PodDisruptionBudgets for all service Deployments and CPU-based HPAs for the
   stateless API/Web Deployments. Runner horizontal scale remains deliberate via
   Deployment replicas, queue quotas, and `max_running_jobs` rather than an HPA
   that might scale down active work. `deploy/k8s/overlays/production` adds a
   production template for TCR image replacements, synthetic Web Ingress, and
   ingress-only NetworkPolicies. Environment-specific host, TLS, ingress class,
   image tags, and egress allowlists remain deployment-time overlay inputs.
4. M36: add TencentDB migration readiness gate and startup failure behavior.
   Current status: implemented with startup migration, `/ready` head-version
   check, and K8s readinessProbe on `harbor-api`.
5. M37: validate TDMQ for RabbitMQ publish/consume plus MySQL claim. Current
   status: `deploy/docker-compose/scripts/rabbitmq-claim-smoke.sh` implemented;
   local RabbitMQ-compatible smoke passed on August 17, 2026 with polling
   disabled on the runner. Run the same script against TDMQ once production
   endpoints and credentials are configured.
6. M38: validate COS dataset input and artifact output in cloud. Current status:
   local real COS/TKE smoke passed on August 17, 2026 with dataset `cos://`
   upload, materialized inputs, `input-manifest`, COS artifacts, artifact
   download, sample ingest, result dataset publish, and JSONL/JSON download.
7. M39: parameterize production E2E smoke for URLs, auth, runtime, dataset, and
   timeout. Current status: `synthetic-cos-tke-e2e.sh` supports production
   synthetic API, harbor API, Web base URLs, runtime, dataset path, timeout,
   unified auth header/bearer token, tenant header, and per-service auth/tenant
   overrides. Frontend live smoke can assert that Web `/api/` requests carry the
   configured auth and tenant headers.
8. M40: replace TOML secrets with env/K8s Secret references and add tenant/auth
   scope before broad exposure. Current status: COS credential env references
   are implemented for runner artifact upload, runner input materialization,
   harbor-api artifact reads, and synthetic dataset upload. Production TOML
   examples now reference env var names for COS credentials, database URLs,
   RabbitMQ URLs, API tokens, and tenant IDs. `harbor-api` and
   `synthetic-data-platform` can enforce Bearer token plus `X-Tenant-ID`;
   `harbor-api` can bind tokens to `read`, `write`, and `internal` scopes, and
   `synthetic-data-platform` can bind inbound tokens to coarse `read` / `write`
   scopes.
   `harbor-runner` and the synthetic platform harbor-api client attach matching
   outbound headers with separate production token env names. K8s manifests
   inject component Secrets. Cancel/retry/artifact retry idempotency persistence
   is tenant-scoped. Control-plane API calls are persisted in
   `api_audit_events` and queryable through `POST /internal/audit-events/query`.
   Remaining security scope: full user/session auth, fine-grained RBAC, and
   end-user audit correlation.
9. M41: expose safe control-plane settings summary for production readiness.
   Current status: implemented in `harbor-control-plane`; authenticated
   `GET /settings` returns database migration readiness, RabbitMQ/RocketMQ
   dispatch configuration status, artifact storage/COS configured flags, and
   control-plane auth scope coverage without exposing database URLs, RabbitMQ
   URLs, COS secrets, bearer tokens, tenant values, or env var names.
10. M42: surface Harbor control-plane readiness in the synthetic console.
    Current status: implemented in `synthetic-data-platform`; synthetic exposes
    `GET /settings/harbor-api` as a safe proxy to harbor-api `GET /settings`,
    and Settings renders database migration, dispatch backend, artifact
    storage/COS, and control-plane auth readiness without exposing database
    URLs, RabbitMQ URLs, COS secrets, bearer tokens, tenant values, or env var
    names.
11. M43: surface remote Harbor control-plane readiness on the synthetic
    Workbench first screen. Current status: implemented in
    `synthetic-data-platform`; Workbench queries `GET /settings/harbor-api`
    when Harbor API is configured and adds a `Harbor control-plane` run
    readiness gate for database migration, dispatch, artifact storage/COS, and
    control-plane auth.

## Phase 11: Synthetic Platform V4 Productization

Detailed plan:

- [`synthetic-data-platform-v4-platformization-plan.md`](../architecture/synthetic-data-platform-v4-platformization-plan.md)

Current target:

- move from an end-to-end demo-grade synthetic console to a production-oriented
  post-training agent trajectory data platform
- keep the browser workflow centered on Dataset -> Synthetic task -> Trial
  trajectory -> Samples -> Result dataset -> Download / lineage audit
- promote global trial review into a first-class production queue
- move sample querying from row-level `samples_json` list slicing toward SQL-backed
  sample records, search, pagination, and quality flags
- harden synthetic cancel/retry/artifact-retry idempotency with an atomic
  reservation state so concurrent same-key retries cannot create duplicate
  synthetic retry tasks
- add synthetic-platform audit records and request IDs for dataset mutations,
  task control, review decisions, sample ingest, publish, and downloads
- keep settings and frontend diagnostics secret-safe; show configured flags and
  readiness only
- use local COS + TKE and production-parameterized E2E smoke as release gates

Planned milestones:

1. V4-0: freeze the platformization plan and split issues/PRs. Current status:
   completed with
   [`synthetic-data-platform-v4-platformization-plan.md`](../architecture/synthetic-data-platform-v4-platformization-plan.md).
2. V4-1: add SQL-backed `synthetic_samples` and source lineage rows; keep current
   samples API response contract and pagination headers. Current status:
   implemented in `synthetic-data-platform`; task/result sample queries read
   SQL sample rows when present, keep `samples_json` fallback, and support
   `quality_flag` filtering.
3. V4-2: freeze result dataset sample snapshots for reproducible JSONL/JSON
   downloads. Current status: implemented; published result samples remain stable
   when the source task ingests additional samples later.
4. V4-3: add operation idempotency reservation states for concurrent same-key
   cancel/retry/artifact-retry requests. The first compatible implementation can
   store reservation status in existing operation metadata before a later schema
   migration promotes it to columns. Current status: implemented in
   `synthetic-data-platform`; same-key in-progress operations return 409 before
   Harbor side effects, completed operations replay the first result, and failed
   operations require a new idempotency key.
5. V4-4: promote Reviews to a first-class frontend workflow with query filters,
   URL deep links, and quick decision recovery. Current status: implemented in
   `synthetic-data-platform`; `GET /reviews/trials` supports
   state/task/runtime/schema/quality flag/reviewer/search/pagination, queue
   items expose `runtime` and `quality_flags`, and the frontend has a primary
   Reviews nav entry plus URL-backed filters.
6. V4-5: make Workbench summary use dedicated backend aggregation with frontend
   fallback. Current status: implemented in `synthetic-data-platform`;
   `/workbench/summary` now reads a repository summary snapshot, and the SQL
   repository uses count/group_by/limit queries for rollups and top lists while
   preserving the existing response contract.
7. V4-6: add synthetic API audit baseline and surface request IDs in recoverable
   frontend errors. Current status: implemented in `synthetic-data-platform`;
   `X-Request-ID` is returned on API responses, error bodies expose
   `request_id`, frontend `ApiError` preserves request IDs, and
   `synthetic_audit_events` is queryable from the Audit console.
8. V4-7: connect the Trial OpenAI Messages UI to structured trajectory message
   rows. Current status: implemented in `synthetic-data-platform`; the Trial
   Detail Messages tab queries `GET /trajectory/messages`, exposes `Sync index`,
   and supports server-side role/search pagination with URL-restorable controls.
9. V4-8: run backend tests, frontend verify, and COS + TKE E2E smoke as the
   release gate. Current status: passed locally on August 18, 2026
   (Asia/Shanghai). Verification covered `harbor-control-plane` tests/ruff,
   compose rebuild, `harbor-api` MySQL migration readiness at
   `0008_api_audit_events`, real COS dataset upload from
   `/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags`, TKE runtime
   execution, COS artifact upload/download, sample ingest, result dataset
   publish/download, OpenAI trajectory message sync/query, and synthetic Web
   live Playwright rendering. Evidence IDs: dataset
   `e1eee484389249aaa1f5078a363efe69`, synthetic task
   `73063b12c15941f8b6de73307af1d4ee`, harbor job
   `6032457cd1744c89a770c7b9e397d8eb`, trial
   `f1e09428-3524-4bc5-8e06-9a3174f1af71`, result dataset
   `240e0e8d1f9147b5b353ab37419ec637`. Release-gate hardening found and fixed
   the control-plane MySQL audit-event path index migration issue in
   `harbor-control-plane` PR #4.
10. V4-9: add a production-oriented Reviews summary endpoint and dashboard
    strip. Current status: implemented in `synthetic-data-platform`; PR #41
    added `GET /reviews/summary` with total/open/reviewed/unreviewed counts,
    OpenAI-message readiness, flagged trial count, state/runtime/schema/quality
    flag buckets, and priority review items. The Reviews page now renders
    global queue metrics from this endpoint while retaining URL-backed filters
    and server-side pagination for `/reviews/trials`. Verification:
    `uv run ruff check .`, `uv run pytest -q`, and
    `npm --prefix web run verify`.
11. V4-10: add current-page batch review decisions. Current status: implemented
    in `synthetic-data-platform`; PR #42 added
    `POST /reviews/trials/batch-decision`, duplicate item protection, one
    audit event per batch, checkbox selection on the Reviews queue, and a batch
    decision panel with validation, pending, success, and refresh states. The
    first increment intentionally batches only the visible page and avoids
    cross-page selection until review queue bulk operations have a stronger
    selection model. Verification: `uv run ruff check .`, `uv run pytest -q`,
    and `npm --prefix web run verify`.
12. V4-11: add filter-based batch review decisions. Current status:
    implemented in `synthetic-data-platform`; PR #43 lets
    `POST /reviews/trials/batch-decision` accept either explicit `items` or
    `filters + expected_total`, reuses `/reviews/trials` filtering semantics,
    requires at least one non-state filter for filter-based batches, and writes
    selection metadata into the batch audit event. The Reviews page now exposes
    `Batch matching filters` when the current query is narrowed and no more
    than 500 trials match, then saves through the shared batch decision panel.
    Verification: `uv run ruff check .`, `uv run pytest -q`, and
    `npm --prefix web run verify`.
13. V4-12: add sample quality summary endpoints. Current status: implemented
    in `synthetic-data-platform`; PR #44 added
    `GET /synthetic-tasks/{id}/samples/summary` and
    `GET /result-datasets/{id}/samples/summary` with `search/q` and
    `quality_flag` support. The endpoints return total/matching counts,
    flagged rows, reward coverage, low reward count, and quality flag buckets
    using the same quality flag rules as sample queries. Result Dataset Detail
    now uses the result summary endpoint for dataset-wide quality cards instead
    of deriving those cards only from the current paginated sample page.
    Verification: `uv run ruff check .`, `uv run pytest -q`, and
    `npm --prefix web run verify`.
14. V4-13: move sample quality summaries into the repository contract. Current
    status: implemented in `synthetic-data-platform`; PR #45 added
    `SampleSummaryResult`, `summarize_task_samples`, and
    `summarize_result_dataset_samples` so API endpoints delegate summary
    computation to repository implementations. SQL repositories now summarize
    from `synthetic_samples` quality flag columns when structured sample rows
    exist, while preserving the legacy JSON snapshot fallback for older task
    and result dataset records. Verification: `uv run ruff check .`,
    `uv run pytest -q`, and `npm --prefix web run verify`.
15. V4-14: expire stale operation idempotency reservations. Current status:
    implemented in `synthetic-data-platform`; PR #46 added
    `operation_idempotency_reservation_ttl_seconds` with a 3600-second default,
    repository-level stale reservation expiry for InMemory and SQL stores, and
    cancel/retry/artifact-retry claim-time cleanup. Expired `in_progress`
    records become `failed`, so clients must use a new idempotency key instead
    of reusing a key with an unknown side-effect outcome. Verification:
    `uv run ruff check .`, `uv run pytest -q`, and
    `npm --prefix web run verify`.
16. V4-15: add structured sample quality flag indexes. Current status:
    implemented in `synthetic-data-platform`; PR #47 added
    `synthetic_sample_quality_flags`, writes `sample_id + flag` rows during
    sample ingestion, changes SQL `quality_flag` filtering to indexed `EXISTS`
    conditions, and lazily backfills matching legacy sample rows on first
    scoped flag query. SQL regression tests cover flag row persistence, legacy
    backfill, index creation, and SQLite query-plan use of the `flag + sample_id`
    covering index. Verification: `uv run ruff check .`, `uv run pytest -q`,
    and `npm --prefix web run verify`.
17. V4-16: expose operation idempotency observability summary. Current status:
    implemented in `synthetic-data-platform`; PR #48 added
    `GET /operations/idempotency/summary`, repository-level aggregate snapshots,
    operation/status buckets, TTL-derived `stale_in_progress` counts, and
    expired reservation counts. The response is aggregate-only and does not
    expose idempotency keys, request payloads, or Harbor execution parameters.
    Verification: `uv run ruff check .`, targeted API/SQL repository tests,
    `uv run pytest -q`, and `npm --prefix web run verify`.
18. V4-17: audit completed operation idempotency replays. Current status:
    implemented in `synthetic-data-platform`; PR #49 records audit events when
    cancel, retry, or artifact retry reuses an idempotency key whose first
    execution already completed. Replay audit events keep the current request ID
    and actor, point at the returned task, include operation/source-task
    metadata, and avoid writing idempotency keys or request payloads. Verification:
    `uv run ruff check .`, targeted API tests, `uv run pytest -q`, and
    `git diff --check`.
19. V4-18: audit failed mutation requests. Current status: implemented in
    `synthetic-data-platform`; PR #50 records `synthetic_api.request_failed`
    audit events for failed `POST`, `PUT`, `PATCH`, and `DELETE` requests,
    covering HTTPException, HarborApiError, RequestValidationError, and auth
    401/403 failures. Events preserve request ID, actor, resource IDs, status
    code, and error type, but do not store request payloads or idempotency keys.
    Verification: `uv run ruff check .`, targeted auth/API/validation/Harbor
    tests, `uv run pytest -q`, and `git diff --check`.
20. V4-19: surface operation idempotency observability in the Workbench. Current
    status: implemented in `synthetic-data-platform`; PR #51 adds the frontend
    wrapper for `GET /operations/idempotency/summary`, renders aggregate
    total/in-progress/completed/failed/stale/expired reservation counts, and
    shows an operation-level status table for cancel, retry, and artifact retry
    health. The UI keeps the backend aggregate-only contract and does not
    expose idempotency keys, request payloads, or Harbor operation parameters.
    Verification: `npm --prefix web run verify`.
21. V4-20: summarize audit events in the Audit console. Current status:
    implemented in `synthetic-data-platform`; PR #52 adds
    `GET /audit-events/summary`, repository-level aggregate snapshots,
    total/succeeded/failed counts, status/action/resource-type buckets, recent
    failed events, and a URL-backed Audit summary panel with resource type
    filtering. The endpoint reuses audit list filters and avoids deriving
    aggregate state from one paginated browser page. Verification:
    `uv run ruff check .`, `uv run pytest -q`, and
    `npm --prefix web run verify`.
22. V4-21: summarize result dataset inventory in the Results console. Current
    status: implemented in `synthetic-data-platform`; PR #53 adds
    `GET /result-datasets/summary`, repository-level aggregate snapshots,
    result count, sample count, empty/single-sample result counts, source
    task/dataset counts, sample-scale buckets, source dataset buckets, recent
    result datasets, and a URL-backed Results summary panel. Verification:
    `uv run ruff check .`, `uv run pytest -q`, and
    `npm --prefix web run verify`.
23. V4-22: surface Synthetic API auth readiness in Settings. Current status:
    implemented in `synthetic-data-platform`; `GET /settings` now returns a
    safe `auth` summary with enabled/anonymous mode, configured and missing
    token counts, read/write/internal scope coverage, tenant-scoped/global
    token counts, tenant header, and required method groups. The Settings page
    renders those aggregates without exposing bearer token values, token env
    names, or tenant env names.
24. V4-23: surface Synthetic API auth readiness in Workbench. Current status:
    implemented in `synthetic-data-platform`; `/workbench/summary` now includes
    a `Synthetic API auth` readiness gate and the Workbench frontend fallback
    derives the same gate from `/settings.auth`. Anonymous local mode is marked
    as production review rather than an E2E blocker, while enabled auth with
    incomplete token or read/write scope coverage is marked missing.
25. V4-24: verify live frontend auth headers. Current status: implemented in
    `synthetic-data-platform`; the Playwright live workflow can inject explicit
    auth headers or bearer tokens plus tenant headers, observe browser `/api/`
    requests, and assert the configured headers are present without printing
    secrets.
26. V4-25: expose production auth smoke gates in Settings. Current status:
    implemented in `synthetic-data-platform`; the Settings Local E2E validation
    panel now shows token source, tenant header, Web `/api` header assertion,
    and split-entrance readiness, plus a copyable production auth smoke command
    with gateway URLs, bearer token, tenant header, publish requirement, and
    live Playwright header assertion.
27. V4-26: expose Harbor API outbound auth readiness. Current status:
    implemented in `synthetic-data-platform`; `/settings.harbor_api.auth` now
    returns safe configured flags for outbound bearer token, tenant ID, and tenant
    header, while Settings and Workbench show whether synthetic-data-platform
    calls to `harbor-api` are anonymous, bearer-authenticated, or tenant-scoped
    without exposing token values, tenant values, or env var names.
28. V4-27: expose Harbor control-plane readiness in Settings. Current status:
    implemented in `synthetic-data-platform`; `GET /settings/harbor-api`
    proxies the harbor-api safe settings summary, and Settings shows remote
    database migration, RabbitMQ/RocketMQ dispatch, artifact storage/COS, and
    control-plane auth gates without duplicating or leaking low-level secrets.
29. V4-28: expose Harbor control-plane readiness in Workbench. Current status:
    implemented in `synthetic-data-platform`; Workbench now queries
    `GET /settings/harbor-api` and adds a first-screen `Harbor control-plane`
    run readiness gate, marking request failures or missing remote DB/dispatch/
    artifact storage/auth gates as actionable blockers.
