# COS Input Dataset Materialization Design

## Goal

Synthetic data jobs should be able to reference source datasets by durable COS
URI instead of requiring the dataset to already exist on the runner machine.

The production flow is:

```text
synthetic-data-platform
  -> harbor-api POST /jobs with input_datasets
  -> MySQL job row stores the input dataset declarations
  -> harbor-runner leases the job and fetches full job status
  -> harbor-runner downloads COS archives into jobs/<job_id>/inputs/
  -> harbor-runner rewrites Harbor JobConfig datasets to local paths
  -> harbor-runtime executes the local materialized dataset
```

`harbor-runtime` still receives a normal Harbor `JobConfig` with local dataset
paths. It does not need COS credentials and does not know the business dataset
catalog.

## Ownership

`synthetic-data-platform` owns business dataset selection:

- accepts dataset references from product workflows
- validates business-level dataset availability in later iterations
- calls `harbor-api` with `input_datasets`

`harbor-api` owns durable job state:

- stores the original `input_datasets`
- exposes them through `GET /jobs/{job_id}`
- records `input_state` and `materialized_inputs`
- marks the job failed if input materialization fails before execution

`harbor-runner` owns runner-local materialization:

- downloads COS archives using runner TOML credentials
- verifies checksum when configured
- safely extracts archives under `jobs/<job_id>/inputs/datasets/`
- validates that extracted directories contain Harbor tasks
- rewrites the runtime `datasets` paths before starting `harbor-runtime`
- records an `inputs/manifest.json` artifact after execution

## Contracts

`POST /jobs` accepts:

```json
{
  "job_config": {
    "job_name": "synthetic-job"
  },
  "input_datasets": [
    {
      "name": "dataset-a",
      "source_type": "cos",
      "uri": "cos://harbor-datasets/prod/datasets/a.tar.gz",
      "version": "v1",
      "format": "tar.gz",
      "checksum_sha256": "..."
    }
  ]
}
```

`GET /jobs/{job_id}` returns the original declarations plus runner-reported
materialization output:

```json
{
  "input_state": "succeeded",
  "input_datasets": [],
  "materialized_inputs": [
    {
      "name": "dataset-a",
      "source_type": "cos",
      "uri": "cos://harbor-datasets/prod/datasets/a.tar.gz",
      "format": "tar.gz",
      "target": "dataset-a",
      "local_path": "inputs/datasets/dataset-a",
      "state": "succeeded"
    }
  ]
}
```

Runner updates state through:

```text
POST /internal/jobs/{job_id}/input-state
```

Allowed `input_state` values:

```text
pending | materializing | succeeded | failed
```

## Runner TOML

Input materialization is configured on `harbor-runner`, because the runner is
the component that downloads objects and owns the local `jobs_dir` staging area.

```toml
[input_materialization]
backend = "cos"
retain_local = true
local_retention_hours = 72
verify_checksum = true
max_archive_bytes = 10737418240
max_extracted_bytes = 53687091200
max_file_count = 200000

[input_materialization.cos]
bucket = "harbor-datasets-1250000000"
region = "ap-guangzhou"
prefix = "prod/datasets"
secret_id = "example-runner-secret-id"
secret_key = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

Current iteration uses literal TOML credentials. A later hardening iteration
will keep non-secret settings in TOML and read credentials from env/K8s Secret
references.

## Archive Rules

First supported format:

```text
tar.gz
```

Safety rules:

- reject absolute paths and `..` path traversal
- reject symlinks and hardlinks
- reject unsupported tar member types
- enforce max archive size, extracted byte size, and file count
- optionally require SHA-256 checksum
- validate extracted content contains at least one Harbor task directory

## Failure Semantics

Input materialization happens after lease acquisition and before
`harbor-runtime` starts.

- materialization starts: `input_state = materializing`
- all inputs succeed: `input_state = succeeded`
- any input fails: `input_state = failed`, job `state = failed`,
  `error_type = input_materialization_failed`

Execution state and input state are intentionally separate. A job can fail
before runtime starts because its input could not be materialized.

## Development Flow

1. Extend shared contracts with `InputDataset`, `MaterializedInputDataset`, and
   `InputState`.
2. Persist input declarations and materialization state in `harbor-api`.
3. Add `/internal/jobs/{job_id}/input-state`.
4. Change runner job lookup from config-only to full job status lookup.
5. Add runner input materializer interface with `none` and `cos` adapters.
6. Download, verify, safely extract, and validate COS `tar.gz` datasets.
7. Rewrite `JobConfig.datasets` to local materialized paths before starting
   `harbor-runtime`.
8. Emit `inputs/manifest.json` and collect it as `kind = "input-manifest"`.
9. Let `synthetic-data-platform` pass `input_datasets` through to `harbor-api`.
10. Add unit coverage for contracts, API persistence, runner success/failure,
    artifact collection, and synthetic pass-through.

## Backlog

- add scheduled retention cleanup for materialized input directories
- support dataset manifests beyond single `tar.gz` archives
- add real-COS smoke tests gated by credentials
- move business dataset validation/catalog ownership into
  `synthetic-data-platform`
