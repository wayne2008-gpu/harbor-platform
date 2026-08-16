# Docker Compose Config

This directory holds the checked-in TOML configuration used by local Docker Compose.
For the current PoC, COS credentials are literal TOML values here. Replace the
placeholder values before running COS-backed jobs.

Files:

- `control-plane.toml`: `harbor-api` COS read/signing config.
- `runner.toml`: shared runner COS upload and input materialization config.
  Compose injects each runner's identity through `HARBOR_RUNNER_ID`.
- `runner.host-paths.toml`: shared runner config for rootless Docker host-path
  smoke runs. It keeps COS artifact upload enabled but uses
  `$HARBOR_RUNNER_HOST_JOBS_DIR` so the runner container and external Docker
  daemon agree on absolute job paths.

Compose mounts them as:

```text
config/control-plane.toml  -> harbor-api:/config/control-plane.toml
config/runner.toml         -> harbor-runner-1:/config/runner.toml
config/runner.toml         -> harbor-runner-2:/config/runner.toml
```

`compose.rootless-docker-host-paths.yml` overrides the runner mount to:

```text
config/runner.host-paths.toml -> harbor-runner-1:/config/runner.toml
config/runner.host-paths.toml -> harbor-runner-2:/config/runner.toml
```

Update these fields for your COS account:

```toml
[artifact_storage.cos]
bucket = "..."
region = "..."
prefix = "..."
secret_id = "..."
secret_key = "..."

[input_materialization.cos]
bucket = "..."
region = "..."
prefix = "..."
secret_id = "..."
secret_key = "..."
```

Runner artifact uploads use this default COS key layout:

```toml
[artifact_storage]
upload_policy = "job_dir_all"
cos_key_layout = "attempt_execution"
```

The resulting object keys are scoped as:

```text
{prefix}/jobs/{platform_job_id}/attempts/{attempt}/executions/{execution_id}/{relative_path}
```
