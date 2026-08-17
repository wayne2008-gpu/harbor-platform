# Harbor Platform

Harbor Platform is the integration repository for the distributed Harbor-based
execution platform. Component code is pinned as git submodules; this repository
owns deployment manifests, local end-to-end smoke tests, and cross-repo docs.

## Layout

```text
harbor/                              # Harbor fork: runtime and runner
harbor-control-plane/                # harbor-api/control-plane
synthetic-data-platform/             # synthetic data business platform
harbor-service-contracts/            # shared service contracts
deploy/                              # Compose/Kubernetes deployment assets
docs/                                # architecture and runbooks
```

## Setup

```bash
git submodule update --init --recursive
```

Component runtime configuration lives with the component that reads it:

```text
harbor/config/runner.local.toml
harbor-control-plane/config/control-plane.local.toml
```

`deploy/docker-compose/` owns only the local control-plane stack and smoke-test
wiring. Run `harbor-runner` from the `harbor/` submodule for local end-to-end
tests.
