# COS Input Materialization Local E2E

This runbook validates the Phase 8 flow where a job references an input dataset
by COS URI and `harbor-runner` downloads it before starting `harbor-runtime`.

The intended local topology is:

```text
synthetic-data-platform API :8081
  -> harbor-api :8080
  -> MySQL + RabbitMQ in Compose
  -> host-side harbor-runner
  -> harbor-runtime
  -> TKE agent-runtime
```

## Configuration Files

Runtime config stays in the component repositories:

- `harbor/config/runner.local.toml`
- `harbor-control-plane/config/control-plane.local.toml`
- `synthetic-data-platform/config/platform.local.toml`

Required settings:

- `harbor/config/runner.local.toml`
  - `[artifact_storage] backend = "cos"`
  - `[artifact_storage.cos]` points at the result artifact COS bucket/prefix.
  - `[input_materialization] backend = "cos"`
  - `[input_materialization.cos]` points at the input dataset COS bucket/prefix.
  - `[capabilities] providers` includes the runtime provider used by the job,
    for example `tke`.
- `harbor-control-plane/config/control-plane.local.toml`
  - `[artifact_storage] backend = "cos"`
  - `[artifact_storage.cos]` matches the result artifact COS location.
- `synthetic-data-platform/config/platform.local.toml`
  - `[dataset_storage] backend = "cos"`
  - `[dataset_storage.cos]` points at the input dataset COS location used by
    dataset upload.

Do not write real credentials in this runbook or in committed example files.
The current local iteration may use literal TOML credentials in ignored local
files; later hardening will move secrets to env or K8s Secret references.

## Start Services

From the super repo:

```bash
cd deploy/docker-compose
docker compose -f compose.dev.yml -f compose.synthetic-upload.yml up --build -d
```

The overlay mounts `synthetic-data-platform/config/platform.local.toml` so
`POST /datasets/upload` can write archives to COS.

Start the host-side runner from the Harbor submodule:

```bash
cd ../../harbor
uv sync --all-extras --dev

# Set provider credentials required by the chosen agent-runtime, for example TKE.
# Follow harbor/readme-tke.md for HARBOR_TKE_CONFIG and model credentials.
uv run harbor runner start --config config/runner.local.toml --keep-alive
```

## Prepare And Upload A Dataset

Use a Harbor benchmark archive. For the local otel bench fixture on this host:

```bash
tar -C /home/ubuntu/project/harbor/benchmark_verify \
  -czf /tmp/otel-bench-ags.tar.gz \
  otel-bench-ags

sha256sum /tmp/otel-bench-ags.tar.gz
```

Upload it through `synthetic-data-platform`:

```bash
curl -fsS -X POST http://localhost:8081/datasets/upload \
  -F "file=@/tmp/otel-bench-ags.tar.gz;type=application/gzip" \
  -F "name=otel-bench-ags" \
  -F "version=local-e2e" \
  -F "format=tar.gz" \
  -F "task_names=go-http-tracing" \
  | tee /tmp/harbor-input-dataset.json
```

Capture the durable input values:

```bash
export HARBOR_SMOKE_INPUT_DATASET_URI=$(
  jq -r .uri /tmp/harbor-input-dataset.json
)
export HARBOR_SMOKE_INPUT_DATASET_VERSION=$(
  jq -r .version /tmp/harbor-input-dataset.json
)
export HARBOR_SMOKE_INPUT_DATASET_SHA256=$(
  jq -r .checksum_sha256 /tmp/harbor-input-dataset.json
)
```

## Run The Harbor API Smoke

The smoke payload intentionally omits `job_config.datasets`. Runner materializes
`input_datasets`, rewrites the runtime config to local paths, and then starts
`harbor-runtime`.

```bash
cd /home/ubuntu/project/harbor-platform/deploy/docker-compose

HARBOR_SMOKE_REQUIRE_INPUT_STATE=succeeded \
HARBOR_SMOKE_REQUIRE_MATERIALIZED_INPUTS=1 \
HARBOR_SMOKE_REQUIRE_INPUT_MANIFEST=1 \
HARBOR_SMOKE_REQUIRE_ARTIFACT_MANIFEST=1 \
HARBOR_SMOKE_METADATA_TIMEOUT_SEC=120 \
./scripts/submit-and-wait-job.sh \
  smoke/cos-input-materialization-smoke-job.json \
  http://localhost:8080 \
  1800
```

Successful output must show:

- job `state = "succeeded"`
- job `input_state = "succeeded"`
- non-empty `materialized_inputs`
- at least one `input-manifest` artifact
- normal result artifacts recorded in MySQL

## Synthetic Task Pass-Through Smoke

To validate `synthetic-data-platform -> harbor-api` pass-through without the
frontend, submit:

```bash
curl -fsS -X POST http://localhost:8081/synthetic-tasks \
  -H 'content-type: application/json' \
  --data-binary @- <<JSON | jq .
{
  "name": "synthetic-cos-input-tke-smoke",
  "harbor_job_name": "synthetic-cos-input-tke-smoke",
  "input_datasets": [
    {
      "name": "otel-bench-ags",
      "source_type": "cos",
      "uri": "${HARBOR_SMOKE_INPUT_DATASET_URI}",
      "version": "${HARBOR_SMOKE_INPUT_DATASET_VERSION}",
      "format": "tar.gz",
      "checksum_sha256": "${HARBOR_SMOKE_INPUT_DATASET_SHA256}",
      "task_names": ["go-http-tracing"],
      "n_tasks": 1
    }
  ],
  "environment": {"type": "tke"},
  "agent_name": "oracle",
  "n_concurrent_trials": 1
}
JSON
```

Then inspect the returned `harbor_job_id` through `harbor-api`:

```bash
curl -fsS "http://localhost:8080/jobs/<harbor_job_id>" | jq .
curl -fsS "http://localhost:8080/jobs/<harbor_job_id>/artifacts" | jq .
```

## Troubleshooting

- `input_state = failed`: check runner logs first. Common causes are invalid COS
  credentials, missing object, checksum mismatch, unsupported archive format, or
  an archive that does not contain valid Harbor task directories.
- Job stays queued: confirm the runner is online through
  `curl -fsS http://localhost:8080/runners?stale_after_sec=60 | jq .`.
- No `input-manifest` artifact: confirm runner `[artifact_storage]` uses
  `upload_policy = "job_dir_all"` and `upload_manifest = true`.
- Synthetic upload returns 503: confirm `compose.synthetic-upload.yml` was used
  and `synthetic-data-platform/config/platform.local.toml` has COS dataset
  storage configured.
