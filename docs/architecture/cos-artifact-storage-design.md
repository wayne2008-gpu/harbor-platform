# COS Artifact Storage Design

## Goal

Production artifact storage should use Tencent Cloud COS as the durable source of truth.

`harbor-runtime` still writes job output to the runner-local `jobs_dir` first. After a job finishes, `harbor-runner` uploads selected files to COS and records durable COS locations in MySQL through `harbor-api`.

```text
harbor-runtime
  -> runner-local jobs_dir
  -> harbor-runner artifact collector
  -> COS artifact store
  -> harbor-api / MySQL artifact rows
```

Runner-local files are staging/cache. COS objects are the production artifact source.

## Ownership

`harbor-runner` owns artifact persistence:

- scans `jobs/<job_id>/`
- classifies artifacts
- uploads files to COS
- records artifact metadata through `harbor-api`
- optionally deletes local files after successful upload

`harbor-api` owns artifact indexing and access:

- stores artifact metadata in MySQL
- returns artifact lists
- resolves COS artifacts for download through proxy streaming or signed URLs
- does not know Harbor local directory layout beyond stored metadata

`synthetic-data-platform` consumes artifacts through `harbor-api`. It should not read runner-local paths or COS directly.

## Storage Interface

Add a runner-side artifact storage module with a small interface:

```python
class ArtifactStore(Protocol):
    def persist_artifacts(
        self,
        *,
        job_id: str,
        job_dir: Path,
        artifacts: list[CollectedArtifact],
    ) -> list[StoredArtifact]: ...
```

Adapters:

- `RunnerLocalArtifactStore`: current PoC behavior; records local paths as `storage_type = "runner-local"`.
- `CosArtifactStore`: uploads files to COS; records durable COS locations as `storage_type = "cos"`.

The runner daemon should only depend on `ArtifactStore`, not COS SDK details.

## COS Key Layout

Use deterministic object keys so uploads are idempotent:

```text
{prefix}/jobs/{job_id}/{relative_path}
```

Example:

```text
cos://harbor-artifacts-1250000000/prod/jobs/5d4.../result.json
cos://harbor-artifacts-1250000000/prod/jobs/5d4.../trial-a/result.json
cos://harbor-artifacts-1250000000/prod/jobs/5d4.../trial-a/agent/trajectory.json
cos://harbor-artifacts-1250000000/prod/jobs/5d4.../trial-a/verifier/output.log
```

Store relative paths, not runner absolute paths, in object metadata and MySQL. Absolute runner paths are not portable.

## TOML Configuration

Use TOML as the configuration source for artifact storage in the current iteration. COS credentials are literal TOML values for this PoC so runner and control-plane share one simple config model. A later hardening iteration should replace literal credentials with env or K8s Secret references.

Runner upload config:

```toml
[artifact_storage]
backend = "cos"
retain_local = true
local_retention_hours = 72
upload_manifest = true
fail_job_on_upload_error = false
upload_retry_attempts = 2
upload_retry_wait_sec = 1.0

[artifact_storage.cos]
bucket = "harbor-artifacts-1250000000"
region = "ap-guangzhou"
prefix = "prod"
endpoint = "" # optional; default from region
secret_id = "example-runner-secret-id"
secret_key = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
session_token = "" # optional
```

Control-plane read config:

```toml
[artifact_storage]
backend = "cos"
download_mode = "signed-url" # signed-url or proxy
signed_url_ttl_sec = 600

[artifact_storage.cos]
bucket = "harbor-artifacts-1250000000"
region = "ap-guangzhou"
prefix = "prod"
secret_id = "example-api-secret-id"
secret_key = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
session_token = "" # optional
```

Recommended production permission split:

- runner credentials: `PutObject`, `HeadObject`, optional `DeleteObject` under the configured prefix
- harbor-api credentials: `GetObject`, `HeadObject`, signed URL permission under the configured prefix

Do not store temporary signed URLs in MySQL. They expire and are access tokens, not durable object addresses.

Compose examples live at:

- `deploy/docker-compose/runner-cos.example.toml`
- `deploy/docker-compose/control-plane-cos.example.toml`

Default compose runner configs still use `backend = "runner-local"`. To enable COS locally, mount a COS runner config as `/config/runner.toml` for runner containers and set `HARBOR_CONTROL_PLANE_CONFIG` to the mounted control-plane config path for `harbor-api`.

Security hardening backlog:

- replace `secret_id`, `secret_key`, and `session_token` literal TOML fields with env/K8s Secret references
- keep TOML as the non-secret config source for bucket, region, prefix, retention, and download mode
- update compose/K8s manifests so only runner and harbor-api pods receive the minimum COS credentials they need

## Artifact Metadata

Keep the existing `storage_type` and `storage_key` contract, but define COS semantics:

```text
storage_type = "cos"
storage_key  = "cos://<bucket>/<key>"
```

Extend artifact metadata over time:

```text
relative_path
content_type
checksum_sha256
etag
metadata_json
uploaded_at
```

Minimal first migration:

- keep `storage_type`
- keep `storage_key`
- add `relative_path`
- add `checksum_sha256`
- add `etag`
- add `uploaded_at`

The `artifacts` table remains the durable index. COS contains file bytes.

## Runtime Flow

1. `harbor-runtime` executes the job and writes files under runner `jobs_dir`.
2. `harbor-runner` builds a collected artifact list from `jobs/<job_id>/`.
3. `CosArtifactStore` uploads each file to deterministic COS keys.
4. Upload result returns `storage_type = "cos"` and `storage_key = cos://...`.
5. `harbor-runner` records each artifact through `POST /internal/jobs/{job_id}/artifacts`.
6. `harbor-api` persists artifact rows in MySQL.
7. Clients list artifacts through `GET /jobs/{job_id}/artifacts`.
8. Clients fetch content through `GET /jobs/{job_id}/artifacts/{artifact_id}/content`.
9. `harbor-api` either redirects to a signed COS URL or proxies the object stream.

## Failure Semantics

Artifact persistence is separate from Harbor execution.

Add a job-level artifact state:

```text
artifact_state = pending | uploading | succeeded | partial_failed | failed
```

Recommended behavior:

- If `harbor-runtime` fails, upload whatever diagnostic artifacts exist.
- If execution succeeds but COS upload partially fails, keep job execution state as `succeeded`, set `artifact_state = partial_failed`, and record an event.
- If all uploads fail, set `artifact_state = failed` and retain runner-local files for retry.

Do not mark the execution itself as failed just because COS upload failed.

## Access Model

Public clients should never receive COS credentials.

Preferred access path:

```text
client -> harbor-api -> signed URL or proxy stream -> COS
```

`harbor-api` should enforce platform auth before returning a signed URL or streaming content. The signed URL TTL should be short, defaulting to 10 minutes.

## Migration Plan

1. Add shared artifact storage config models and tests.
2. Add `ArtifactStore` with `runner-local` and fake in-memory adapters.
3. Add `CosArtifactStore` behind the same interface.
4. Extend runner config TOML to load `[artifact_storage]`.
5. Extend artifacts table and service contracts with `relative_path`, `checksum_sha256`, `etag`, and `uploaded_at`.
6. Add control-plane artifact resolver for `runner-local` and `cos`.
7. Add compose config examples for COS without enabling it by default.
8. Add synthetic-data-platform result and trajectory query endpoints that proxy through `harbor-api`.
9. Add an integration smoke that uses a fake store or a real COS bucket when credentials are present.

## Open Decisions

- Whether `harbor-api` should proxy COS content by default or return signed URLs.
- Whether env/K8s Secret credential references should use env names, mounted file paths, or both.
- Whether COS upload retries are runner-local only or also triggered by a control-plane retry endpoint.
