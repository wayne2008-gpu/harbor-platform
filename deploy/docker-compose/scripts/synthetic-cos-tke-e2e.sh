#!/usr/bin/env bash
set -euo pipefail

synthetic_api=${SYNTHETIC_API_BASE:-http://localhost:8081}
harbor_api=${HARBOR_API_BASE:-http://localhost:8080}
frontend_url=${SYNTHETIC_WEB_BASE:-http://localhost:5173}
dataset_dir=${HARBOR_E2E_DATASET_DIR:-/home/ubuntu/project/harbor/benchmark_verify/otel-bench-ags}
dataset_name=${HARBOR_E2E_DATASET_NAME:-$(basename "$dataset_dir")}
dataset_version=${HARBOR_E2E_DATASET_VERSION:-local-e2e-$(date -u +%Y%m%dT%H%M%SZ)}
task_name=${HARBOR_E2E_TASK_NAME:-go-http-tracing}
runtime=${HARBOR_E2E_RUNTIME:-tke}
agent_name=${HARBOR_E2E_AGENT_NAME:-oracle}
model_name=${HARBOR_E2E_MODEL_NAME:-}
concurrency=${HARBOR_E2E_CONCURRENCY:-1}
timeout_sec=${HARBOR_E2E_TIMEOUT_SEC:-1800}
metadata_timeout_sec=${HARBOR_E2E_METADATA_TIMEOUT_SEC:-180}
interval_sec=${HARBOR_E2E_POLL_INTERVAL_SEC:-5}
expect_runners=${HARBOR_E2E_EXPECT_RUNNERS:-1}
runner_timeout_sec=${HARBOR_E2E_RUNNER_TIMEOUT_SEC:-120}
stale_after_sec=${HARBOR_E2E_STALE_AFTER_SEC:-60}
require_input_state=${HARBOR_E2E_REQUIRE_INPUT_STATE:-succeeded}
require_dataset_cos_uri=${HARBOR_E2E_REQUIRE_DATASET_COS_URI:-1}
require_materialized_inputs=${HARBOR_E2E_REQUIRE_MATERIALIZED_INPUTS:-1}
require_input_manifest=${HARBOR_E2E_REQUIRE_INPUT_MANIFEST:-1}
require_cos_artifacts=${HARBOR_E2E_REQUIRE_COS_ARTIFACTS:-1}
require_trajectory=${HARBOR_E2E_REQUIRE_TRAJECTORY:-0}
require_openai_trajectory=${HARBOR_E2E_REQUIRE_OPENAI_TRAJECTORY:-$require_trajectory}
require_publish=${HARBOR_E2E_REQUIRE_PUBLISH:-0}
require_result_export_cos=${HARBOR_E2E_REQUIRE_RESULT_EXPORT_COS:-$require_publish}
check_web=${HARBOR_E2E_CHECK_WEB:-1}
frontend_live_check=${HARBOR_E2E_FRONTEND_LIVE_CHECK:-0}
preflight_only=${HARBOR_E2E_PREFLIGHT_ONLY:-0}
auth_header=${HARBOR_E2E_AUTH_HEADER:-}
bearer_token=${HARBOR_E2E_BEARER_TOKEN:-}
tenant_header_name=${HARBOR_E2E_TENANT_HEADER_NAME:-X-Tenant-ID}
tenant_id=${HARBOR_E2E_TENANT_ID:-}
synthetic_auth_header=${HARBOR_E2E_SYNTHETIC_AUTH_HEADER:-$auth_header}
synthetic_bearer_token=${HARBOR_E2E_SYNTHETIC_BEARER_TOKEN:-$bearer_token}
synthetic_tenant_header_name=${HARBOR_E2E_SYNTHETIC_TENANT_HEADER_NAME:-$tenant_header_name}
synthetic_tenant_id=${HARBOR_E2E_SYNTHETIC_TENANT_ID:-$tenant_id}
harbor_auth_header=${HARBOR_E2E_HARBOR_AUTH_HEADER:-$auth_header}
harbor_bearer_token=${HARBOR_E2E_HARBOR_BEARER_TOKEN:-$bearer_token}
harbor_tenant_header_name=${HARBOR_E2E_HARBOR_TENANT_HEADER_NAME:-$tenant_header_name}
harbor_tenant_id=${HARBOR_E2E_HARBOR_TENANT_ID:-$tenant_id}
web_auth_header=${HARBOR_E2E_WEB_AUTH_HEADER:-$auth_header}
web_bearer_token=${HARBOR_E2E_WEB_BEARER_TOKEN:-$bearer_token}
web_tenant_header_name=${HARBOR_E2E_WEB_TENANT_HEADER_NAME:-$tenant_header_name}
web_tenant_id=${HARBOR_E2E_WEB_TENANT_ID:-$tenant_id}
expect_web_auth_headers=${HARBOR_E2E_EXPECT_WEB_AUTH_HEADERS:-}
if [ -z "$expect_web_auth_headers" ]; then
  if [ -n "$web_auth_header" ] || [ -n "$web_bearer_token" ] || [ -n "$web_tenant_id" ]; then
    expect_web_auth_headers=1
  else
    expect_web_auth_headers=0
  fi
fi
synthetic_curl_args=()
harbor_curl_args=()
web_curl_args=()

append_request_headers() {
  local target_array=$1
  local auth_header_value=$2
  local bearer_token_value=$3
  local tenant_header_name_value=$4
  local tenant_id_value=$5
  local -n args_ref="$target_array"

  if [ -n "$auth_header_value" ]; then
    args_ref+=(-H "$auth_header_value")
  elif [ -n "$bearer_token_value" ]; then
    args_ref+=(-H "Authorization: Bearer $bearer_token_value")
  fi
  if [ -n "$tenant_id_value" ]; then
    if [ -z "$tenant_header_name_value" ]; then
      echo "Tenant header name cannot be empty when tenant id is configured." >&2
      exit 2
    fi
    args_ref+=(-H "$tenant_header_name_value: $tenant_id_value")
  fi
}

append_request_headers \
  synthetic_curl_args \
  "$synthetic_auth_header" \
  "$synthetic_bearer_token" \
  "$synthetic_tenant_header_name" \
  "$synthetic_tenant_id"
append_request_headers \
  harbor_curl_args \
  "$harbor_auth_header" \
  "$harbor_bearer_token" \
  "$harbor_tenant_header_name" \
  "$harbor_tenant_id"
append_request_headers \
  web_curl_args \
  "$web_auth_header" \
  "$web_bearer_token" \
  "$web_tenant_header_name" \
  "$web_tenant_id"

archive_path=""
jsonl_path=""
json_path=""
export_download_path=""
artifact_download_path=""

cleanup() {
  if [ -n "$archive_path" ]; then
    rm -f "$archive_path"
  fi
  if [ -n "$jsonl_path" ]; then
    rm -f "$jsonl_path"
  fi
  if [ -n "$json_path" ]; then
    rm -f "$json_path"
  fi
  if [ -n "$export_download_path" ]; then
    rm -f "$export_download_path"
  fi
  if [ -n "$artifact_download_path" ]; then
    rm -f "$artifact_download_path"
  fi
}
trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 2
  fi
}

fetch_json() {
  curl_url "$1"
}

post_json() {
  local url=$1
  local payload=$2
  curl_url "$url" -H "content-type: application/json" --data-binary "$payload"
}

curl_url() {
  local url=$1
  shift
  if [[ "$url" == "$harbor_api"* ]]; then
    curl -fsS "${harbor_curl_args[@]}" "$@" "$url"
    return
  fi
  if [[ "$url" == "$frontend_url"* ]]; then
    curl -fsS "${web_curl_args[@]}" "$@" "$url"
    return
  fi
  curl -fsS "${synthetic_curl_args[@]}" "$@" "$url"
}

synthetic_api_url_from_download_url() {
  local value=$1
  if [[ "$value" == http://* ]] || [[ "$value" == https://* ]]; then
    printf '%s\n' "$value"
    return
  fi
  if [[ "$value" == /api/* ]]; then
    printf '%s/%s\n' "$synthetic_api" "${value#/api/}"
    return
  fi
  printf '%s%s\n' "$synthetic_api" "$value"
}

assert_non_empty() {
  local label=$1
  local value=$2
  if [ -z "$value" ] || [ "$value" = "null" ]; then
    echo "Expected non-empty $label" >&2
    exit 1
  fi
}

assert_count_at_least() {
  local label=$1
  local count=$2
  local minimum=$3
  if [ "$count" -lt "$minimum" ]; then
    echo "Expected $label >= $minimum, got $count" >&2
    exit 1
  fi
}

wait_for_runners() {
  if [ "$expect_runners" -le 0 ]; then
    return
  fi

  local deadline=$((SECONDS + runner_timeout_sec))
  local runners_json online_count
  while [ "$SECONDS" -lt "$deadline" ]; do
    runners_json=$(fetch_json "$harbor_api/runners?stale_after_sec=$stale_after_sec")
    online_count=$(
      jq -r '[.[] | select(.state == "online")] | length' <<<"$runners_json"
    )
    echo "$(date -Is) online_runners=$online_count expected=$expect_runners"
    if [ "$online_count" -ge "$expect_runners" ]; then
      return
    fi
    sleep "$interval_sec"
  done

  case "$runtime" in
    tke)
      if [ -z "${HARBOR_TKE_CONFIG:-}" ]; then
        echo "Hint: HARBOR_TKE_CONFIG is not set in this shell." >&2
      fi
      ;;
    ags)
      if [ -z "${HARBOR_AGS_CONFIG:-}" ]; then
        echo "Hint: HARBOR_AGS_CONFIG is not set in this shell." >&2
      fi
      ;;
  esac
  echo "Start a host-side runner with provider '$runtime' before running E2E." >&2
  echo "Timed out waiting for $expect_runners online runner(s)" >&2
  exit 1
}

wait_for_terminal_results() {
  local task_id=$1
  local deadline=$((SECONDS + timeout_sec))
  local state input_state artifact_state trial_count artifact_count

  while [ "$SECONDS" -lt "$deadline" ]; do
    results_json=$(fetch_json "$synthetic_api/synthetic-tasks/$task_id/results")
    state=$(jq -r '.harbor_job.state // empty' <<<"$results_json")
    input_state=$(jq -r '.harbor_job.input_state // empty' <<<"$results_json")
    artifact_state=$(jq -r '.harbor_job.artifact_state // empty' <<<"$results_json")
    trial_count=$(jq -r '.trials | length' <<<"$results_json")
    artifact_count=$(jq -r '.artifacts | length' <<<"$results_json")
    echo \
      "$(date -Is) state=$state input_state=$input_state artifact_state=$artifact_state trials=$trial_count artifacts=$artifact_count"
    case "$state" in
      succeeded|failed|cancelled|timed_out)
        return
        ;;
    esac
    sleep "$interval_sec"
  done

  echo "Timed out waiting for synthetic task $task_id" >&2
  exit 1
}

wait_for_metadata() {
  local task_id=$1
  local deadline=$((SECONDS + metadata_timeout_sec))
  local trial_count artifact_count trajectory_count openai_count cos_count input_manifest_count metadata_ready

  while [ "$SECONDS" -lt "$deadline" ]; do
    results_json=$(fetch_json "$synthetic_api/synthetic-tasks/$task_id/results")
    trial_count=$(jq -r '.trials | length' <<<"$results_json")
    artifact_count=$(jq -r '.artifacts | length' <<<"$results_json")
    trajectory_count=$(
      jq -r '[.artifacts[] | select(.kind == "trajectory")] | length' \
        <<<"$results_json"
    )
    openai_count=$(
      jq -r \
        '[.artifacts[] | select(.kind == "trajectory" and ((.metadata.schema // "") == "openai_messages"))] | length' \
        <<<"$results_json"
    )
    cos_count=$(
      jq -r \
        '[.artifacts[] | select(.storage_type == "cos" and ((.storage_key // "") != ""))] | length' \
        <<<"$results_json"
    )
    input_manifest_count=$(
      jq -r '[.artifacts[] | select(.kind == "input-manifest")] | length' \
        <<<"$results_json"
    )
    echo \
      "$(date -Is) metadata trials=$trial_count artifacts=$artifact_count trajectories=$trajectory_count openai=$openai_count cos=$cos_count input_manifest=$input_manifest_count"
    metadata_ready=1
    if [ "$trial_count" -lt 1 ] || [ "$artifact_count" -lt 1 ]; then
      metadata_ready=0
    fi
    if [ "$require_trajectory" -ne 0 ] && [ "$trajectory_count" -lt 1 ]; then
      metadata_ready=0
    fi
    if [ "$require_openai_trajectory" -ne 0 ] && [ "$openai_count" -lt 1 ]; then
      metadata_ready=0
    fi
    if [ "$require_cos_artifacts" -ne 0 ] && [ "$cos_count" -lt 1 ]; then
      metadata_ready=0
    fi
    if [ "$require_input_manifest" -ne 0 ] && [ "$input_manifest_count" -lt 1 ]; then
      metadata_ready=0
    fi
    if [ "$metadata_ready" -eq 1 ]; then
      return
    fi
    sleep "$interval_sec"
  done

  echo "Timed out waiting for required metadata for synthetic task $task_id" >&2
  exit 1
}

run_frontend_live_check() {
  local checked_dataset_id=$1
  local checked_task_id=$2
  local checked_trial_id=$3
  local checked_result_dataset_id=${4:-}

  if [ "$frontend_live_check" -eq 0 ]; then
    return
  fi

  require_command npm
  local script_dir web_dir
  script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  web_dir=$(cd "$script_dir/../../../synthetic-data-platform/web" && pwd)

  echo "Running frontend live workflow check through Playwright."
  SYNTHETIC_LIVE_BASE_URL="$frontend_url" \
    SYNTHETIC_LIVE_AUTH_HEADER="$web_auth_header" \
    SYNTHETIC_LIVE_BEARER_TOKEN="$web_bearer_token" \
    SYNTHETIC_LIVE_TENANT_HEADER_NAME="$web_tenant_header_name" \
    SYNTHETIC_LIVE_TENANT_ID="$web_tenant_id" \
    SYNTHETIC_LIVE_EXPECT_AUTH_HEADERS="$expect_web_auth_headers" \
    SYNTHETIC_LIVE_DATASET_ID="$checked_dataset_id" \
    SYNTHETIC_LIVE_DATASET_NAME="$dataset_name" \
    SYNTHETIC_LIVE_TASK_ID="$checked_task_id" \
    SYNTHETIC_LIVE_TASK_NAME="$task_name" \
    SYNTHETIC_LIVE_TRIAL_ID="$checked_trial_id" \
    SYNTHETIC_LIVE_RESULT_DATASET_ID="$checked_result_dataset_id" \
    SYNTHETIC_LIVE_RUNTIME="$runtime" \
    npm --prefix "$web_dir" run test:live
}

require_command curl
require_command jq
require_command tar
require_command sha256sum
require_command awk

if ! [[ "$concurrency" =~ ^[1-9][0-9]*$ ]]; then
  echo "HARBOR_E2E_CONCURRENCY must be a positive integer" >&2
  exit 2
fi

if [ ! -d "$dataset_dir" ]; then
  echo "Dataset directory not found: $dataset_dir" >&2
  exit 2
fi

if [ "$check_web" -ne 0 ]; then
  curl_url "$frontend_url" >/dev/null
fi
fetch_json "$synthetic_api/health" >/dev/null
fetch_json "$harbor_api/ready" >/dev/null
echo "Preflight: services reachable, dataset_dir=$dataset_dir runtime=$runtime task=$task_name"
wait_for_runners
if [ "$preflight_only" -ne 0 ]; then
  echo "Preflight passed. Set HARBOR_E2E_PREFLIGHT_ONLY=0 or unset it to run the full E2E."
  exit 0
fi

archive_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-dataset.XXXXXX.tar.gz")
if [ -f "$dataset_dir/task.toml" ]; then
  tar -C "$(dirname "$dataset_dir")" -czf "$archive_path" "$(basename "$dataset_dir")"
else
  tar -C "$dataset_dir" -czf "$archive_path" .
fi
archive_sha=$(sha256sum "$archive_path" | awk '{print $1}')
echo "Prepared dataset archive: $archive_path sha256=$archive_sha"

dataset_json=$(
  curl_url "$synthetic_api/datasets/upload" \
    -X POST \
    -F "file=@${archive_path};type=application/gzip" \
    -F "name=${dataset_name}" \
    -F "version=${dataset_version}" \
    -F "format=tar.gz" \
    -F "task_names=${task_name}"
)
dataset_id=$(jq -r '.id // empty' <<<"$dataset_json")
dataset_uri=$(jq -r '.uri // empty' <<<"$dataset_json")
dataset_storage_key=$(jq -r '.metadata.storage_key // empty' <<<"$dataset_json")
dataset_checksum=$(jq -r '.checksum_sha256 // empty' <<<"$dataset_json")
assert_non_empty "dataset id" "$dataset_id"
assert_non_empty "dataset uri" "$dataset_uri"
if [ "$require_dataset_cos_uri" -ne 0 ]; then
  if [[ "$dataset_uri" != cos://* ]]; then
    echo "Expected dataset uri to start with cos://, got $dataset_uri" >&2
    exit 1
  fi
  assert_non_empty "dataset storage key" "$dataset_storage_key"
fi
echo "Uploaded dataset: id=$dataset_id uri=$dataset_uri"

if [ "$dataset_checksum" != "$archive_sha" ]; then
  echo "Uploaded dataset checksum mismatch: expected $archive_sha got $dataset_checksum" >&2
  exit 1
fi

task_run_name="${dataset_name}-${runtime}-${task_name}-${dataset_version}"
task_payload=$(
  jq -n \
    --arg name "$task_run_name" \
    --arg dataset_id "$dataset_id" \
    --arg task_name "$task_name" \
    --arg runtime "$runtime" \
    --arg agent_name "$agent_name" \
    --arg model_name "$model_name" \
    --argjson concurrency "$concurrency" \
    '{
      name: $name,
      dataset_id: $dataset_id,
      task_names: [$task_name],
      environment: {type: $runtime},
      agent_name: $agent_name,
      n_concurrent_trials: $concurrency
    } + (if $model_name == "" then {} else {model_name: $model_name} end)'
)
task_json=$(post_json "$synthetic_api/synthetic-tasks" "$task_payload")
task_id=$(jq -r '.id // empty' <<<"$task_json")
harbor_job_id=$(jq -r '.harbor_job_id // empty' <<<"$task_json")
assert_non_empty "synthetic task id" "$task_id"
assert_non_empty "harbor job id" "$harbor_job_id"
echo "Submitted synthetic task: id=$task_id harbor_job_id=$harbor_job_id"

wait_for_terminal_results "$task_id"
state=$(jq -r '.harbor_job.state // empty' <<<"$results_json")
if [ "$state" != "succeeded" ]; then
  jq . <<<"$results_json"
  echo "Harbor job $harbor_job_id finished with state=$state" >&2
  exit 1
fi

if [ -n "$require_input_state" ]; then
  input_state=$(jq -r '.harbor_job.input_state // empty' <<<"$results_json")
  if [ "$input_state" != "$require_input_state" ]; then
    echo "Expected input_state=$require_input_state, got ${input_state:-empty}" >&2
    exit 1
  fi
fi
if [ "$require_materialized_inputs" -ne 0 ]; then
  materialized_input_count=$(jq -r '.harbor_job.materialized_inputs | length' <<<"$results_json")
  assert_count_at_least "materialized input count" "$materialized_input_count" 1
fi

wait_for_metadata "$task_id"
trial_count=$(jq -r '.trials | length' <<<"$results_json")
artifact_count=$(jq -r '.artifacts | length' <<<"$results_json")
trajectory_count=$(
  jq -r '[.artifacts[] | select(.kind == "trajectory")] | length' <<<"$results_json"
)
openai_count=$(
  jq -r \
    '[.artifacts[] | select(.kind == "trajectory" and ((.metadata.schema // "") == "openai_messages"))] | length' \
    <<<"$results_json"
)
cos_count=$(
  jq -r \
    '[.artifacts[] | select(.storage_type == "cos" and ((.storage_key // "") != ""))] | length' \
    <<<"$results_json"
)
input_manifest_count=$(
  jq -r '[.artifacts[] | select(.kind == "input-manifest")] | length' \
    <<<"$results_json"
)
assert_count_at_least "trial count" "$trial_count" 1
assert_count_at_least "artifact count" "$artifact_count" 1
if [ "$require_trajectory" -ne 0 ]; then
  assert_count_at_least "trajectory artifact count" "$trajectory_count" 1
fi
if [ "$require_openai_trajectory" -ne 0 ]; then
  assert_count_at_least "OpenAI trajectory artifact count" "$openai_count" 1
fi
if [ "$require_cos_artifacts" -ne 0 ]; then
  assert_count_at_least "COS artifact count" "$cos_count" 1
fi
if [ "$require_input_manifest" -ne 0 ]; then
  assert_count_at_least "input-manifest artifact count" "$input_manifest_count" 1
fi

trial_id=$(jq -r '.trials[0].id // empty' <<<"$results_json")
assert_non_empty "trial id" "$trial_id"
if [ "$openai_count" -ge 1 ]; then
  trajectory_json=$(
    fetch_json "$synthetic_api/synthetic-tasks/$task_id/trials/$trial_id/trajectory?schema=openai_messages"
  )
  message_count=$(
    jq -r \
      'if type == "array" then length elif type == "object" then ((.openai_messages // .messages // []) | if type == "array" then length else 0 end) else 0 end' \
      <<<"$trajectory_json"
  )
  assert_count_at_least "OpenAI message count" "$message_count" 1
else
  echo "No OpenAI messages trajectory artifact found; trajectory API check skipped."
fi

artifact_id=$(
  jq -r \
    '([.artifacts[] | select(.kind == "trajectory")][0].id // [.artifacts[] | select(.kind == "result")][0].id // .artifacts[0].id // empty)' \
    <<<"$results_json"
)
assert_non_empty "artifact id" "$artifact_id"
download_url_json=$(
  fetch_json "$synthetic_api/synthetic-tasks/$task_id/artifacts/$artifact_id/download-url"
)
jq -e '.url and (.url | length > 0)' <<<"$download_url_json" >/dev/null
artifact_download_url=$(jq -r '.url' <<<"$download_url_json")
artifact_download_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-artifact.XXXXXX")
curl -fsSL "$artifact_download_url" -o "$artifact_download_path"
artifact_download_size=$(wc -c <"$artifact_download_path" | tr -d ' ')
assert_count_at_least "artifact download byte count" "$artifact_download_size" 1
echo "Verified artifact download through synthetic API."

ingest_json=$(curl_url "$synthetic_api/synthetic-tasks/$task_id/ingest-samples" -X POST)
ingested=$(jq -r '.ingested // 0' <<<"$ingest_json")
echo "Ingested samples: $ingested"
if [ "$ingested" -lt 1 ]; then
  if [ "$require_publish" -ne 0 ]; then
    echo "No samples were ingested; cannot publish result dataset." >&2
    exit 1
  fi
  echo "No sample source artifact was found; result dataset publish/download skipped."
  run_frontend_live_check "$dataset_id" "$task_id" "$trial_id"
  echo "Frontend dataset URL: $frontend_url/datasets/$dataset_id"
  echo "Frontend task URL: $frontend_url/tasks/$task_id"
  echo "Frontend trial URL: $frontend_url/tasks/$task_id/trials/$trial_id"
  exit 0
fi

publish_json=$(curl_url "$synthetic_api/synthetic-tasks/$task_id/publish" -X POST)
result_dataset_id=$(jq -r '.result_dataset.id // empty' <<<"$publish_json")
assert_non_empty "result dataset id" "$result_dataset_id"
result_json=$(fetch_json "$synthetic_api/result-datasets/$result_dataset_id")
sample_count=$(jq -r '.sample_count // 0' <<<"$result_json")
assert_count_at_least "result dataset sample count" "$sample_count" 1

jsonl_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-result.XXXXXX.jsonl")
curl_url "$synthetic_api/result-datasets/$result_dataset_id/download?format=jsonl" \
  -o "$jsonl_path"
jsonl_lines=$(wc -l <"$jsonl_path" | tr -d ' ')
assert_count_at_least "JSONL line count" "$jsonl_lines" 1

json_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-result.XXXXXX.json")
curl_url "$synthetic_api/result-datasets/$result_dataset_id/download?format=json" \
  -o "$json_path"
jq -e --arg id "$result_dataset_id" \
  '.id == $id and (.samples | length >= 1)' \
  "$json_path" >/dev/null

export_json=$(
  post_json \
    "$synthetic_api/result-datasets/$result_dataset_id/exports" \
    '{"format":"jsonl","mode":"background","metadata":{"source":"synthetic-cos-tke-e2e"}}'
)
export_id=$(jq -r '.id // empty' <<<"$export_json")
assert_non_empty "result export id" "$export_id"
export_deadline=$((SECONDS + metadata_timeout_sec))
while [ "$SECONDS" -lt "$export_deadline" ]; do
  export_status=$(jq -r '.status // empty' <<<"$export_json")
  echo "$(date -Is) result_export_id=$export_id status=$export_status"
  if [ "$export_status" = "completed" ] || [ "$export_status" = "failed" ]; then
    break
  fi
  sleep "$interval_sec"
  export_json=$(fetch_json "$synthetic_api/result-datasets/$result_dataset_id/exports/$export_id")
done
export_status=$(jq -r '.status // empty' <<<"$export_json")
if [ "$export_status" != "completed" ]; then
  echo "Expected result export $export_id to complete, got $export_status" >&2
  exit 1
fi
export_storage_type=$(jq -r '.storage_type // empty' <<<"$export_json")
export_download_url=$(jq -r '.download_url // empty' <<<"$export_json")
assert_non_empty "result export download_url" "$export_download_url"
if [ "$require_result_export_cos" -ne 0 ] && [ "$export_storage_type" != "cos" ]; then
  echo "Expected COS result export storage, got $export_storage_type" >&2
  exit 1
fi
export_download_endpoint=$(synthetic_api_url_from_download_url "$export_download_url")
export_download_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-result-export.XXXXXX.jsonl")
curl_url "$export_download_endpoint" -o "$export_download_path"
export_jsonl_lines=$(wc -l <"$export_download_path" | tr -d ' ')
assert_count_at_least "result export JSONL line count" "$export_jsonl_lines" 1
echo "Verified result export record download: $export_id ($export_storage_type)."

run_frontend_live_check "$dataset_id" "$task_id" "$trial_id" "$result_dataset_id"

echo "Synthetic COS/TKE E2E passed."
echo "Frontend dataset URL: $frontend_url/datasets/$dataset_id"
echo "Frontend task URL: $frontend_url/tasks/$task_id"
echo "Frontend trial URL: $frontend_url/tasks/$task_id/trials/$trial_id"
echo "Frontend result URL: $frontend_url/results/$result_dataset_id"
