#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: deploy/k8s/scripts/tke-preflight.sh [--static-only|--cluster]

Static checks:
  - render the Kustomize base or overlay
  - verify the rendered manifest is non-empty
  - verify required workload, availability, and config manifest references
  - fail on template placeholders unless explicitly allowed

Cluster checks with --cluster:
  - run kubectl server-side dry-run against the rendered manifest
  - verify required namespaces, ConfigMaps, and Secrets exist
  - verify required Secret/ConfigMap keys exist without printing values
  - verify harbor-runner ServiceAccount can manage agent-runtime Pods
  - optionally check rollout status when HARBOR_K8S_CHECK_ROLLOUT=1

Environment:
  HARBOR_K8S_KUSTOMIZE_DIR              default: deploy/k8s/base
  HARBOR_K8S_PLATFORM_NAMESPACE         default: harbor-platform
  HARBOR_K8S_AGENT_NAMESPACE            default: harbor-agent-runtime
  HARBOR_K8S_ALLOW_PLACEHOLDER_IMAGES   set 1 to allow image/template placeholders
  HARBOR_K8S_RENDERED_MANIFEST          optional output path for rendered YAML
  HARBOR_K8S_CHECK_ROLLOUT              set 1 to run kubectl rollout status
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

MODE="static"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --static-only)
      MODE="static"
      shift
      ;;
    --cluster)
      MODE="cluster"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

KUSTOMIZE_DIR="${HARBOR_K8S_KUSTOMIZE_DIR:-$ROOT_DIR/deploy/k8s/base}"
PLATFORM_NS="${HARBOR_K8S_PLATFORM_NAMESPACE:-harbor-platform}"
AGENT_NS="${HARBOR_K8S_AGENT_NAMESPACE:-harbor-agent-runtime}"
ALLOW_PLACEHOLDERS="${HARBOR_K8S_ALLOW_PLACEHOLDER_IMAGES:-0}"
CHECK_ROLLOUT="${HARBOR_K8S_CHECK_ROLLOUT:-0}"

TEMP_RENDERED=""
if [[ -n "${HARBOR_K8S_RENDERED_MANIFEST:-}" ]]; then
  RENDERED_MANIFEST="$HARBOR_K8S_RENDERED_MANIFEST"
else
  TEMP_RENDERED="$(mktemp)"
  RENDERED_MANIFEST="$TEMP_RENDERED"
fi

TEMP_VALUE="$(mktemp)"
TEMP_PLACEHOLDERS="$(mktemp)"
cleanup() {
  [[ -n "$TEMP_RENDERED" ]] && rm -f "$TEMP_RENDERED"
  rm -f "$TEMP_VALUE"
  rm -f "$TEMP_PLACEHOLDERS"
}
trap cleanup EXIT

log() {
  printf '==> %s\n' "$*"
}

ok() {
  printf 'ok: %s\n' "$*"
}

warn() {
  printf 'warn: %s\n' "$*" >&2
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

jsonpath_key() {
  local key="$1"
  printf '%s' "${key//./\\.}"
}

require_configmap_key() {
  local namespace="$1"
  local name="$2"
  local key="$3"
  local escaped
  escaped="$(jsonpath_key "$key")"
  : >"$TEMP_VALUE"
  kubectl -n "$namespace" get configmap "$name" \
    -o "jsonpath={.data.$escaped}" >"$TEMP_VALUE" 2>/dev/null \
    || fail "missing ConfigMap $namespace/$name"
  [[ -s "$TEMP_VALUE" ]] || fail "ConfigMap $namespace/$name missing key $key"
  ok "ConfigMap $namespace/$name contains $key"
}

require_secret_key() {
  local namespace="$1"
  local name="$2"
  local key="$3"
  local escaped
  escaped="$(jsonpath_key "$key")"
  : >"$TEMP_VALUE"
  kubectl -n "$namespace" get secret "$name" \
    -o "jsonpath={.data.$escaped}" >"$TEMP_VALUE" 2>/dev/null \
    || fail "missing Secret $namespace/$name"
  [[ -s "$TEMP_VALUE" ]] || fail "Secret $namespace/$name missing key $key"
  ok "Secret $namespace/$name contains $key"
}

require_rendered_text() {
  local text="$1"
  grep -q "$text" "$RENDERED_MANIFEST" || fail "rendered manifest missing: $text"
  ok "rendered manifest references $text"
}

check_can_i() {
  local verb="$1"
  local resource="$2"
  if kubectl auth can-i "$verb" "$resource" \
    --as "system:serviceaccount:$PLATFORM_NS:harbor-runner" \
    -n "$AGENT_NS" | grep -qx "yes"; then
    ok "harbor-runner can $verb $resource in $AGENT_NS"
  else
    fail "harbor-runner cannot $verb $resource in $AGENT_NS"
  fi
}

require_cmd kubectl

log "Rendering Kustomize directory: $KUSTOMIZE_DIR"
kubectl kustomize "$KUSTOMIZE_DIR" >"$RENDERED_MANIFEST"
[[ -s "$RENDERED_MANIFEST" ]] || fail "rendered manifest is empty"
ok "rendered manifests to $RENDERED_MANIFEST"

log "Checking rendered manifest references"
require_rendered_text "name: harbor-api"
require_rendered_text "name: harbor-runner"
require_rendered_text "name: synthetic-data-platform"
require_rendered_text "name: synthetic-data-platform-web"
require_rendered_text "name: harbor-api-pdb"
require_rendered_text "name: harbor-runner-pdb"
require_rendered_text "name: synthetic-data-platform-pdb"
require_rendered_text "name: synthetic-data-platform-web-pdb"
require_rendered_text "name: harbor-api-hpa"
require_rendered_text "name: synthetic-data-platform-hpa"
require_rendered_text "name: synthetic-data-platform-web-hpa"
require_rendered_text "name: harbor-control-plane-config"
require_rendered_text "name: synthetic-data-platform-config"
require_rendered_text "name: harbor-runner-config"
require_rendered_text "name: harbor-tke-config"
require_rendered_text "name: harbor-api-secret"
require_rendered_text "name: synthetic-data-platform-secret"
require_rendered_text "name: harbor-runner-secret"
require_rendered_text "harbor-runner-kubeconfig"

if grep -nE 'CHANGE_ME|change-me|replace-me' "$RENDERED_MANIFEST" >"$TEMP_PLACEHOLDERS"; then
  if [[ "$ALLOW_PLACEHOLDERS" == "1" ]]; then
    warn "template placeholders are present but allowed"
  else
    cat "$TEMP_PLACEHOLDERS" >&2
    fail "replace template placeholders or set HARBOR_K8S_ALLOW_PLACEHOLDER_IMAGES=1 for template validation"
  fi
fi

if grep -q '^kind: Ingress$' "$RENDERED_MANIFEST"; then
  require_rendered_text "name: synthetic-data-platform-web-ingress"
fi

if grep -q '^kind: NetworkPolicy$' "$RENDERED_MANIFEST"; then
  require_rendered_text "name: harbor-platform-default-deny-ingress"
  require_rendered_text "name: synthetic-data-platform-web-network-ingress"
  require_rendered_text "name: synthetic-data-platform-api-ingress"
  require_rendered_text "name: harbor-api-ingress"
fi

if [[ "$MODE" == "static" ]]; then
  log "Static preflight passed"
  exit 0
fi

log "Running kubectl server-side dry-run"
kubectl apply --dry-run=server --validate=strict -f "$RENDERED_MANIFEST" >/dev/null
ok "server-side dry-run passed"

log "Running cluster preflight checks"
kubectl get namespace "$PLATFORM_NS" >/dev/null
ok "namespace exists: $PLATFORM_NS"
kubectl get namespace "$AGENT_NS" >/dev/null
ok "namespace exists: $AGENT_NS"

require_configmap_key "$PLATFORM_NS" "harbor-control-plane-config" "control-plane.toml"
require_configmap_key "$PLATFORM_NS" "synthetic-data-platform-config" "platform.toml"
require_configmap_key "$PLATFORM_NS" "harbor-runner-config" "runner.toml"
require_configmap_key "$PLATFORM_NS" "harbor-tke-config" "tke.toml"

for key in \
  HARBOR_CONTROL_PLANE_DATABASE_URL \
  HARBOR_CONTROL_PLANE_RABBITMQ_URL \
  HARBOR_SYNTHETIC_HARBOR_API_TOKEN \
  HARBOR_RUNNER_CONTROL_PLANE_TOKEN \
  HARBOR_TENANT_ID \
  HARBOR_ARTIFACT_COS_SECRET_ID \
  HARBOR_ARTIFACT_COS_SECRET_KEY; do
  require_secret_key "$PLATFORM_NS" "harbor-api-secret" "$key"
done

for key in \
  SYNTHETIC_DATA_PLATFORM_DATABASE_URL \
  SYNTHETIC_DATA_PLATFORM_READ_TOKEN \
  SYNTHETIC_DATA_PLATFORM_WRITE_TOKEN \
  HARBOR_SYNTHETIC_HARBOR_API_TOKEN \
  HARBOR_TENANT_ID \
  SYNTHETIC_DATASET_COS_SECRET_ID \
  SYNTHETIC_DATASET_COS_SECRET_KEY; do
  require_secret_key "$PLATFORM_NS" "synthetic-data-platform-secret" "$key"
done

for key in \
  HARBOR_RUNNER_RABBITMQ_URL \
  HARBOR_RUNNER_CONTROL_PLANE_TOKEN \
  HARBOR_TENANT_ID \
  HARBOR_ARTIFACT_COS_SECRET_ID \
  HARBOR_ARTIFACT_COS_SECRET_KEY \
  HARBOR_DATASET_COS_SECRET_ID \
  HARBOR_DATASET_COS_SECRET_KEY; do
  require_secret_key "$PLATFORM_NS" "harbor-runner-secret" "$key"
done

require_secret_key "$PLATFORM_NS" "harbor-runner-kubeconfig" "kubeconfig"
require_secret_key "$AGENT_NS" "tcr-pull-secret" ".dockerconfigjson"

if kubectl -n "$PLATFORM_NS" get secret harbor-runner-agent-env >/dev/null 2>&1; then
  ok "optional Secret $PLATFORM_NS/harbor-runner-agent-env exists"
else
  warn "optional Secret $PLATFORM_NS/harbor-runner-agent-env is missing"
fi

check_can_i create pods
check_can_i delete pods
check_can_i get pods
check_can_i list pods
check_can_i watch pods
check_can_i create pods/exec
check_can_i get pods/log
check_can_i list pods/log
check_can_i watch pods/log

if [[ "$CHECK_ROLLOUT" == "1" ]]; then
  log "Checking Deployment rollouts"
  kubectl -n "$PLATFORM_NS" rollout status deployment/harbor-api
  kubectl -n "$PLATFORM_NS" rollout status deployment/synthetic-data-platform
  kubectl -n "$PLATFORM_NS" rollout status deployment/synthetic-data-platform-web
  kubectl -n "$PLATFORM_NS" rollout status deployment/harbor-runner
fi

log "Cluster preflight passed"
