# Kubernetes / TKE Manifests

This directory contains production-oriented Kubernetes manifests for the Harbor
platform deployment path.

Current scope:

- `base/`: namespaces, runner RBAC, service accounts, Deployments,
  ClusterIP Services, PodDisruptionBudgets, and API/Web HPAs for `harbor-api`,
  synthetic API/Web, and `harbor-runner`.
- `overlays/production/`: production template overlay with TCR image
  replacements, a synthetic web Ingress, and ingress-only NetworkPolicies.

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
  --from-literal=HARBOR_SYNTHETIC_HARBOR_API_TOKEN='<synthetic-to-harbor-api-token>' \
  --from-literal=HARBOR_RUNNER_CONTROL_PLANE_TOKEN='<runner-to-harbor-api-token>' \
  --from-literal=HARBOR_TENANT_ID='<tenant-id>' \
  --from-literal=HARBOR_ARTIFACT_COS_SECRET_ID='<cos-secret-id>' \
  --from-literal=HARBOR_ARTIFACT_COS_SECRET_KEY='<cos-secret-key>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create secret generic synthetic-data-platform-secret \
  --from-literal=SYNTHETIC_DATA_PLATFORM_DATABASE_URL='mysql+pymysql://<user>:<password>@<mysql-host>:3306/synthetic_data_platform' \
  --from-literal=SYNTHETIC_DATA_PLATFORM_API_TOKEN='<synthetic-platform-api-token>' \
  --from-literal=HARBOR_SYNTHETIC_HARBOR_API_TOKEN='<synthetic-to-harbor-api-token>' \
  --from-literal=HARBOR_TENANT_ID='<tenant-id>' \
  --from-literal=SYNTHETIC_DATASET_COS_SECRET_ID='<cos-secret-id>' \
  --from-literal=SYNTHETIC_DATASET_COS_SECRET_KEY='<cos-secret-key>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n harbor-platform create secret generic harbor-runner-secret \
  --from-literal=HARBOR_RUNNER_RABBITMQ_URL='amqps://<user>:<password>@<tdmq-host>:5671/%2F' \
  --from-literal=HARBOR_RUNNER_CONTROL_PLANE_TOKEN='<runner-to-harbor-api-token>' \
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

Use the same `HARBOR_TENANT_ID` in `harbor-api-secret`,
`synthetic-data-platform-secret`, and `harbor-runner-secret`. The
control-plane production template uses separate inbound tokens:
`HARBOR_SYNTHETIC_HARBOR_API_TOKEN` has read/write scope for the synthetic
platform, while `HARBOR_RUNNER_CONTROL_PLANE_TOKEN` has read/write/internal
scope for runner calls. `SYNTHETIC_DATA_PLATFORM_API_TOKEN` protects inbound
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

The base includes PodDisruptionBudgets for `harbor-api`, synthetic API/Web, and
`harbor-runner`. It also includes CPU-based HPAs for the stateless API/Web
Deployments. `harbor-runner` intentionally has no HPA in the base because a
scale-down while a Pod owns active Harbor work can interrupt a run; scale
runners deliberately through Deployment replicas, queue quotas, and
`max_running_jobs`.

The production overlay is a template, not a ready-to-apply environment config.
Copy it to an environment-specific location outside git or into your deployment
repo, then replace:

- image registry and tags in `kustomization.yaml`
- `spec.ingressClassName`
- `synthetic.change-me.example.com`
- `synthetic-data-platform-tls`

The overlay exposes only `synthetic-data-platform-web`. The web service should
proxy API calls to `synthetic-data-platform` inside the cluster; `harbor-api`
stays internal and is reachable only from synthetic API and runner Pods.

Before applying the production overlay, label the namespace that runs the
Ingress controller:

```bash
kubectl label namespace <ingress-controller-namespace> \
  harbor.openai.com/ingress-access=true
```

The included NetworkPolicies restrict ingress only. They do not restrict egress,
so TencentDB, TDMQ for RabbitMQ, COS, DNS, and the Kubernetes API remain
reachable according to cluster routing and cloud security groups. Add
environment-specific egress NetworkPolicies only after the exact service
endpoints, CIDRs, and DNS requirements are known.

Apply the current base:

```bash
kubectl apply -k deploy/k8s/base
```

Render the base and run offline static validation:

```bash
HARBOR_K8S_ALLOW_PLACEHOLDER_IMAGES=1 \
  deploy/k8s/scripts/tke-preflight.sh --static-only
```

`--static-only` intentionally avoids `kubectl apply --dry-run=client` because
recent `kubectl` versions still perform API discovery for client dry-run and
therefore require a reachable cluster. The base manifests intentionally contain
`CHANGE_ME` image placeholders, so base-only validation must opt into allowing
placeholders.

You can also keep the rendered YAML for inspection:

```bash
HARBOR_K8S_RENDERED_MANIFEST=/tmp/harbor-platform-k8s-base.yaml \
  HARBOR_K8S_ALLOW_PLACEHOLDER_IMAGES=1 \
  deploy/k8s/scripts/tke-preflight.sh --static-only
```

For a production overlay, point the script at the overlay and do not allow
placeholder images:

```bash
HARBOR_K8S_KUSTOMIZE_DIR=/path/to/filled/production/overlay \
  deploy/k8s/scripts/tke-preflight.sh --static-only
```

To validate the checked-in template itself, allow placeholders explicitly:

```bash
HARBOR_K8S_KUSTOMIZE_DIR=deploy/k8s/overlays/production \
  HARBOR_K8S_ALLOW_PLACEHOLDER_IMAGES=1 \
  deploy/k8s/scripts/tke-preflight.sh --static-only
```

After ConfigMaps, Secrets, namespaces, RBAC, and image pull secrets have been
created in the cluster, run cluster checks. This command only reads cluster
state and does not apply manifests:

```bash
HARBOR_K8S_KUSTOMIZE_DIR=/path/to/filled/production/overlay \
  deploy/k8s/scripts/tke-preflight.sh --cluster
```

Set `HARBOR_K8S_CHECK_ROLLOUT=1` to also wait for the four service Deployments
to be rolled out.

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
