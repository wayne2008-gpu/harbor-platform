# Harbor Platform

Harbor Platform is the integration repository for the distributed Harbor-based
execution platform. Component code is pinned as git submodules; this repository
owns deployment manifests, local end-to-end smoke tests, and cross-repo docs.

## Layout

```text
harbor/                              # Harbor fork: runtime and runner
services/harbor-control-plane/       # harbor-api/control-plane
services/synthetic-data-platform/    # synthetic data business platform
packages/harbor-service-contracts/   # shared service contracts
deploy/                              # Compose/Kubernetes deployment assets
docs/                                # architecture and runbooks
```

## Setup

```bash
git submodule update --init --recursive
```

Local Docker Compose configuration lives under:

```text
deploy/docker-compose/config/
```
