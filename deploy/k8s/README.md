# Kubernetes / TKE Manifests

This directory contains production-oriented Kubernetes manifests for the Harbor
platform deployment path.

Current scope:

- `base/`: namespaces, runner RBAC, service accounts, Deployments, and
  ClusterIP Services for `harbor-api`, synthetic API/Web, and `harbor-runner`.

The manifests reference ConfigMaps and Secrets, but do not define real runtime
config. Component config stays in the component repositories and should be
copied to environment-specific files outside git before being loaded into the
cluster.

Production example templates:

```text
harbor-control-plane/config/control-plane.production.example.toml
synthetic-data-platform/config/platform.production.example.toml
harbor/config/runner.production.example.toml
harbor/config/tke.production.example.toml
```

Create required ConfigMaps after filling environment-specific TOML files:

```bash
kubectl -n harbor-platform create configmap harbor-control-plane-config \
  --from-file=control-plane.toml=/path/to/control-plane.production.toml \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create configmap synthetic-data-platform-config \
  --from-file=platform.toml=/path/to/platform.production.toml \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create configmap harbor-runner-config \
  --from-file=runner.toml=/path/to/runner.production.toml \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create configmap harbor-tke-config \
  --from-file=tke.toml=/path/to/tke.production.toml \
  --dry-run=client -o yaml | kubectl apply -f -
```

The production TOML templates keep non-sensitive settings in ConfigMaps. COS
credentials, MySQL URLs, RabbitMQ URLs, API tokens, and tenant IDs are
referenced by environment variable name in TOML and must be provided through
Kubernetes Secrets.

Create required Secrets outside git:

```bash
kubectl -n harbor-platform create secret generic harbor-api-secret \
  --from-literal=HARBOR_CONTROL_PLANE_DATABASE_URL='mysql+pymysql://<user>:<password>@<mysql-host>:3306/harbor_control_plane' \
  --from-literal=HARBOR_CONTROL_PLANE_RABBITMQ_URL='amqps://<user>:<password>@<tdmq-host>:5671/%2F' \
  --from-literal=HARBOR_CONTROL_PLANE_API_TOKEN='<control-plane-api-token>' \
  --from-literal=HARBOR_TENANT_ID='<tenant-id>' \
  --from-literal=HARBOR_ARTIFACT_COS_SECRET_ID='<cos-secret-id>' \
  --from-literal=HARBOR_ARTIFACT_COS_SECRET_KEY='<cos-secret-key>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create secret generic synthetic-data-platform-secret \
  --from-literal=SYNTHETIC_DATA_PLATFORM_DATABASE_URL='mysql+pymysql://<user>:<password>@<mysql-host>:3306/synthetic_data_platform' \
  --from-literal=SYNTHETIC_DATA_PLATFORM_API_TOKEN='<synthetic-platform-api-token>' \
  --from-literal=HARBOR_CONTROL_PLANE_API_TOKEN='<control-plane-api-token>' \
  --from-literal=HARBOR_TENANT_ID='<tenant-id>' \
  --from-literal=SYNTHETIC_DATASET_COS_SECRET_ID='<cos-secret-id>' \
  --from-literal=SYNTHETIC_DATASET_COS_SECRET_KEY='<cos-secret-key>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create secret generic harbor-runner-secret \
  --from-literal=HARBOR_RUNNER_RABBITMQ_URL='amqps://<user>:<password>@<tdmq-host>:5671/%2F' \
  --from-literal=HARBOR_CONTROL_PLANE_API_TOKEN='<control-plane-api-token>' \
  --from-literal=HARBOR_TENANT_ID='<tenant-id>' \
  --from-literal=HARBOR_ARTIFACT_COS_SECRET_ID='<cos-secret-id>' \
  --from-literal=HARBOR_ARTIFACT_COS_SECRET_KEY='<cos-secret-key>' \
  --from-literal=HARBOR_DATASET_COS_SECRET_ID='<cos-secret-id>' \
  --from-literal=HARBOR_DATASET_COS_SECRET_KEY='<cos-secret-key>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create secret generic harbor-runner-kubeconfig \
  --from-file=kubeconfig=/path/to/tke-kubeconfig \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create secret generic harbor-runner-agent-env \
  --from-literal=OPENAI_API_KEY='<api-key>' \
  --from-literal=OPENAI_BASE_URL='<base-url>' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Use the same `HARBOR_CONTROL_PLANE_API_TOKEN` and `HARBOR_TENANT_ID` in
`harbor-api-secret`, `synthetic-data-platform-secret`, and
`harbor-runner-secret` so synthetic API and runner calls can pass the
control-plane gate. `SYNTHETIC_DATA_PLATFORM_API_TOKEN` protects inbound
synthetic platform API requests and can be a separate value.

If COS uses temporary credentials, add the matching optional session token
variables to the component Secret:

```text
HARBOR_ARTIFACT_COS_SESSION_TOKEN
HARBOR_DATASET_COS_SESSION_TOKEN
SYNTHETIC_DATASET_COS_SESSION_TOKEN
```

`harbor-runner-agent-env` is optional. Use it only when the selected Harbor
agents require model credentials from the runner environment.

`harbor-api` uses `/health` for liveness and `/ready` for readiness. `/ready`
checks the database connection and verifies that `alembic_version` is at the
current migration head.

Apply the current base:

```bash
kubectl apply -k deploy/k8s/base
```

Validate manifests without applying:

```bash
kubectl kustomize deploy/k8s/base > /tmp/harbor-platform-k8s-base.yaml
kubectl apply --dry-run=client -f /tmp/harbor-platform-k8s-base.yaml
```

Validate runner permissions:

```bash
kubectl auth can-i create pods \
  --as system:serviceaccount:harbor-platform:harbor-runner \
  -n harbor-agent-runtime

kubectl auth can-i create pods/exec \
  --as system:serviceaccount:harbor-platform:harbor-runner \
  -n harbor-agent-runtime

kubectl auth can-i get pods/log \
  --as system:serviceaccount:harbor-platform:harbor-runner \
  -n harbor-agent-runtime
```

Create the private TCR pull secret in the agent-runtime namespace outside git:

```bash
kubectl create secret docker-registry tcr-pull-secret \
  --namespace harbor-agent-runtime \
  --docker-server='<registry-host>' \
  --docker-username='<username>' \
  --docker-password='<password>'
```
