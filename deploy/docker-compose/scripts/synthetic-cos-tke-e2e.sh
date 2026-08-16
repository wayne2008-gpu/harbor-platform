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
require_cos_artifacts=${HARBOR_E2E_REQUIRE_COS_ARTIFACTS:-1}
require_publish=${HARBOR_E2E_REQUIRE_PUBLISH:-0}
check_web=${HARBOR_E2E_CHECK_WEB:-1}
preflight_only=${HARBOR_E2E_PREFLIGHT_ONLY:-0}

archive_path=""
jsonl_path=""
json_path=""

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
}
trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 2
  fi
}

fetch_json() {
  curl -fsS "$1"
}

post_json() {
  local url=$1
  local payload=$2
  curl -fsS -H "content-type: application/json" --data-binary "$payload" "$url"
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
  local trial_count artifact_count trajectory_count openai_count cos_count

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
    echo \
      "$(date -Is) metadata trials=$trial_count artifacts=$artifact_count trajectories=$trajectory_count openai=$openai_count cos=$cos_count"
    if [ "$trial_count" -ge 1 ] &&
      [ "$artifact_count" -ge 1 ] &&
      [ "$trajectory_count" -ge 1 ] &&
      [ "$openai_count" -ge 1 ]; then
      if [ "$require_cos_artifacts" -eq 0 ] || [ "$cos_count" -ge 1 ]; then
        return
      fi
    fi
    sleep "$interval_sec"
  done
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
  curl -fsS "$frontend_url" >/dev/null
fi
fetch_json "$synthetic_api/health" >/dev/null
fetch_json "$harbor_api/health" >/dev/null
echo "Preflight: services reachable, dataset_dir=$dataset_dir runtime=$runtime task=$task_name"
wait_for_runners
if [ "$preflight_only" -ne 0 ]; then
  echo "Preflight passed. Set HARBOR_E2E_PREFLIGHT_ONLY=0 or unset it to run the full E2E."
  exit 0
fi

archive_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-dataset.XXXXXX.tar.gz")
tar -C "$(dirname "$dataset_dir")" -czf "$archive_path" "$(basename "$dataset_dir")"
archive_sha=$(sha256sum "$archive_path" | awk '{print $1}')
echo "Prepared dataset archive: $archive_path sha256=$archive_sha"

dataset_json=$(
  curl -fsS -X POST "$synthetic_api/datasets/upload" \
    -F "file=@${archive_path};type=application/gzip" \
    -F "name=${dataset_name}" \
    -F "version=${dataset_version}" \
    -F "format=tar.gz" \
    -F "task_names=${task_name}"
)
dataset_id=$(jq -r '.id // empty' <<<"$dataset_json")
dataset_uri=$(jq -r '.uri // empty' <<<"$dataset_json")
dataset_checksum=$(jq -r '.checksum_sha256 // empty' <<<"$dataset_json")
assert_non_empty "dataset id" "$dataset_id"
assert_non_empty "dataset uri" "$dataset_uri"
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
assert_count_at_least "trial count" "$trial_count" 1
assert_count_at_least "artifact count" "$artifact_count" 1
assert_count_at_least "trajectory artifact count" "$trajectory_count" 1
assert_count_at_least "OpenAI trajectory artifact count" "$openai_count" 1
if [ "$require_cos_artifacts" -ne 0 ]; then
  assert_count_at_least "COS artifact count" "$cos_count" 1
fi

trial_id=$(jq -r '.trials[0].id // empty' <<<"$results_json")
assert_non_empty "trial id" "$trial_id"
trajectory_json=$(
  fetch_json "$synthetic_api/synthetic-tasks/$task_id/trials/$trial_id/trajectory?schema=openai_messages"
)
message_count=$(
  jq -r \
    'if type == "array" then length elif type == "object" then ((.openai_messages // .messages // []) | if type == "array" then length else 0 end) else 0 end' \
    <<<"$trajectory_json"
)
assert_count_at_least "OpenAI message count" "$message_count" 1

artifact_id=$(
  jq -r \
    '([.artifacts[] | select(.kind == "trajectory")][0].id // .artifacts[0].id // empty)' \
    <<<"$results_json"
)
assert_non_empty "artifact id" "$artifact_id"
download_url_json=$(
  fetch_json "$synthetic_api/synthetic-tasks/$task_id/artifacts/$artifact_id/download-url"
)
jq -e '.url and (.url | length > 0)' <<<"$download_url_json" >/dev/null
echo "Verified trajectory and artifact download-url through synthetic API."

ingest_json=$(curl -fsS -X POST "$synthetic_api/synthetic-tasks/$task_id/ingest-samples")
ingested=$(jq -r '.ingested // 0' <<<"$ingest_json")
echo "Ingested samples: $ingested"
if [ "$ingested" -lt 1 ]; then
  if [ "$require_publish" -ne 0 ]; then
    echo "No samples were ingested; cannot publish result dataset." >&2
    exit 1
  fi
  echo "No sample source artifact was found; result dataset publish/download skipped."
  echo "Frontend dataset URL: $frontend_url/datasets/$dataset_id"
  echo "Frontend task URL: $frontend_url/tasks/$task_id"
  echo "Frontend trial URL: $frontend_url/tasks/$task_id/trials/$trial_id"
  exit 0
fi

publish_json=$(curl -fsS -X POST "$synthetic_api/synthetic-tasks/$task_id/publish")
result_dataset_id=$(jq -r '.result_dataset.id // empty' <<<"$publish_json")
assert_non_empty "result dataset id" "$result_dataset_id"
result_json=$(fetch_json "$synthetic_api/result-datasets/$result_dataset_id")
sample_count=$(jq -r '.sample_count // 0' <<<"$result_json")
assert_count_at_least "result dataset sample count" "$sample_count" 1

jsonl_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-result.XXXXXX.jsonl")
curl -fsS "$synthetic_api/result-datasets/$result_dataset_id/download?format=jsonl" \
  -o "$jsonl_path"
jsonl_lines=$(wc -l <"$jsonl_path" | tr -d ' ')
assert_count_at_least "JSONL line count" "$jsonl_lines" 1

json_path=$(mktemp "${TMPDIR:-/tmp}/harbor-e2e-result.XXXXXX.json")
curl -fsS "$synthetic_api/result-datasets/$result_dataset_id/download?format=json" \
  -o "$json_path"
jq -e --arg id "$result_dataset_id" \
  '.id == $id and (.samples | length >= 1)' \
  "$json_path" >/dev/null

echo "Synthetic COS/TKE E2E passed."
echo "Frontend dataset URL: $frontend_url/datasets/$dataset_id"
echo "Frontend task URL: $frontend_url/tasks/$task_id"
echo "Frontend trial URL: $frontend_url/tasks/$task_id/trials/$trial_id"
echo "Frontend result URL: $frontend_url/results/$result_dataset_id"
