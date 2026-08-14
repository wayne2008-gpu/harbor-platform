# CI and Clean Clone Validation

This runbook covers the two release checks after M1-M7 implementation:

- GitHub Actions CI for contracts, control-plane, synthetic platform, Harbor runner, Harbor AGS/TKE targeted tests, and Compose config rendering.
- A clean clone smoke test that proves the pushed repository and Harbor submodule can reproduce the M5 Docker provider validation without relying on the original working tree.

## GitHub Actions

The workflow lives at:

```text
.github/workflows/ci.yml
```

It intentionally checks out the Harbor submodule explicitly instead of relying on the default `actions/checkout` submodule handling. The repository records the Harbor submodule with an SSH URL. CI rewrites `git@github.com:` to HTTPS using:

```text
secrets.HARBOR_SUBMODULE_TOKEN || github.token
```

If `harbor-based-data-synthesis-platform` is private and the default `GITHUB_TOKEN` cannot read it, add a repository secret named `HARBOR_SUBMODULE_TOKEN` with read access to the Harbor fork.

## Clean Clone Smoke

Run from a temporary directory, not from the development working tree:

```bash
rm -rf /tmp/harbor-platform-clean
git clone --recurse-submodules git@github.com:wayne2008-gpu/harbor-platform.git /tmp/harbor-platform-clean
cd /tmp/harbor-platform-clean
git submodule status
```

Install rootless Docker prerequisites if the host does not already have them:

```bash
sudo apt-get update
sudo apt-get install -y uidmap slirp4netns
```

Start a temporary rootless Docker daemon with TLS:

```bash
cd /tmp/harbor-platform-clean/deploy/docker-compose
./scripts/create-rootless-docker-tls-certs.sh .local/rootless-docker-certs

dockerd-rootless.sh \
  --host=tcp://0.0.0.0:2376 \
  --host=unix://$XDG_RUNTIME_DIR/docker-rootless.sock \
  --tlsverify \
  --tlscacert=$PWD/.local/rootless-docker-certs/server/ca.pem \
  --tlscert=$PWD/.local/rootless-docker-certs/server/cert.pem \
  --tlskey=$PWD/.local/rootless-docker-certs/server/key.pem
```

In another shell, start the Compose stack and run the smoke:

```bash
cd /tmp/harbor-platform-clean/deploy/docker-compose
export HARBOR_PLATFORM_HOST_ROOT=/tmp/harbor-platform-clean
export HARBOR_RUNNER_HOST_JOBS_DIR=$HARBOR_PLATFORM_HOST_ROOT/deploy/docker-compose/.local/runner-jobs
export HARBOR_RUNNER_DOCKER_TLS_CERTS=$PWD/.local/rootless-docker-certs
mkdir -p "$HARBOR_RUNNER_HOST_JOBS_DIR"

docker compose \
  -f compose.dev.yml \
  -f compose.rootless-docker-tls.yml \
  -f compose.rootless-docker-host-paths.yml \
  up --build -d

./scripts/submit-and-wait-job.sh smoke/docker-touch-file-smoke-job.host-paths.json http://localhost:8080 900
```

Expected result:

- two online runners
- terminal `succeeded` job
- non-empty `runner_id`
- at least one `succeeded` trial from `/jobs/{job_id}/trials`
- `result` and `artifact-manifest` entries from `/jobs/{job_id}/artifacts`

Cleanup:

```bash
docker compose \
  -f compose.dev.yml \
  -f compose.rootless-docker-tls.yml \
  -f compose.rootless-docker-host-paths.yml \
  down
```

Then stop the temporary `dockerd-rootless.sh` process with `Ctrl-C`.
