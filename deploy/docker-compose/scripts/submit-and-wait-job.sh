#!/usr/bin/env bash
set -euo pipefail

job_file=${1:?usage: submit-and-wait-job.sh JOB_JSON [API_BASE_URL] [TIMEOUT_SEC]}
api_base=${2:-http://localhost:8080}
timeout_sec=${3:-600}
interval_sec=${HARBOR_SMOKE_POLL_INTERVAL_SEC:-2}
runner_timeout_sec=${HARBOR_SMOKE_RUNNER_TIMEOUT_SEC:-120}
stale_after_sec=${HARBOR_SMOKE_STALE_AFTER_SEC:-60}
expect_runners=${HARBOR_SMOKE_EXPECT_RUNNERS:-2}
require_trials=${HARBOR_SMOKE_REQUIRE_TRIALS:-1}
require_result_artifact=${HARBOR_SMOKE_REQUIRE_RESULT_ARTIFACT:-1}
require_artifact_manifest=${HARBOR_SMOKE_REQUIRE_ARTIFACT_MANIFEST:-1}
metadata_timeout_sec=${HARBOR_SMOKE_METADATA_TIMEOUT_SEC:-60}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 2
  fi
}

fetch_json() {
  curl -fsS "$1"
}

assert_json_count_at_least() {
  local label=$1
  local json=$2
  local jq_filter=$3
  local min_count=$4
  local count
  count=$(jq -r "$jq_filter" <<<"$json")
  if [ "$count" -lt "$min_count" ]; then
    echo "Expected $label >= $min_count, got $count" >&2
    exit 1
  fi
}

metadata_ready() {
  local trial_count result_artifact_count artifact_manifest_count
  if [ "$require_trials" -ne 0 ]; then
    trial_count=$(jq -r 'length' <<<"$trials_json")
    if [ "$trial_count" -lt 1 ]; then
      return 1
    fi
  fi

  if [ "$require_result_artifact" -ne 0 ]; then
    result_artifact_count=$(
      jq -r '[.[] | select(.kind == "result")] | length' <<<"$artifacts_json"
    )
    if [ "$result_artifact_count" -lt 1 ]; then
      return 1
    fi
  fi

  if [ "$require_artifact_manifest" -ne 0 ]; then
    artifact_manifest_count=$(
      jq -r '[.[] | select(.kind == "artifact-manifest")] | length' \
        <<<"$artifacts_json"
    )
    if [ "$artifact_manifest_count" -lt 1 ]; then
      return 1
    fi
  fi

  return 0
}

wait_for_metadata() {
  local deadline=$((SECONDS + metadata_timeout_sec))
  while true; do
    trials_json=$(fetch_json "$api_base/jobs/$job_id/trials")
    artifacts_json=$(fetch_json "$api_base/jobs/$job_id/artifacts")
    if metadata_ready; then
      return
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      return
    fi
    echo "$(date -Is) waiting for trial/artifact metadata"
    sleep "$interval_sec"
  done
}

wait_for_runners() {
  if [ "$expect_runners" -le 0 ]; then
    return
  fi

  local deadline=$((SECONDS + runner_timeout_sec))
  local runners_json online_count
  while [ "$SECONDS" -lt "$deadline" ]; do
    runners_json=$(fetch_json "$api_base/runners?stale_after_sec=$stale_after_sec")
    online_count=$(jq -r '[.[] | select(.state == "online")] | length' <<<"$runners_json")
    echo "$(date -Is) online_runners=$online_count expected=$expect_runners"
    if [ "$online_count" -ge "$expect_runners" ]; then
      jq . <<<"$runners_json"
      return
    fi
    sleep "$interval_sec"
  done

  runners_json=$(fetch_json "$api_base/runners?stale_after_sec=$stale_after_sec")
  jq . <<<"$runners_json"
  echo "Timed out waiting for $expect_runners online runners" >&2
  exit 1
}

require_command curl
require_command jq
require_command python3
wait_for_runners

job_payload=$(
  python3 - "$job_file" <<'PY'
import os
import sys
from pathlib import Path

print(os.path.expandvars(Path(sys.argv[1]).read_text()), end="")
PY
)

job_id=$(curl -fsS \
  -H 'content-type: application/json' \
  --data-binary "$job_payload" \
  "$api_base/jobs" | jq -r .id)

if [ -z "$job_id" ] || [ "$job_id" = "null" ]; then
  echo "Failed to submit job from $job_file" >&2
  exit 1
fi

echo "Submitted job: $job_id"
deadline=$((SECONDS + timeout_sec))
state=""
while [ "$SECONDS" -lt "$deadline" ]; do
  state=$(fetch_json "$api_base/jobs/$job_id" | jq -r .state)
  echo "$(date -Is) state=$state"
  case "$state" in
    succeeded|failed|cancelled|timed_out)
      break
      ;;
  esac
  sleep "$interval_sec"
done

job_json=$(fetch_json "$api_base/jobs/$job_id")
state=$(jq -r .state <<<"$job_json")
runner_id=$(jq -r '.runner_id // empty' <<<"$job_json")

if [ "$state" = "succeeded" ]; then
  wait_for_metadata
else
  trials_json=$(fetch_json "$api_base/jobs/$job_id/trials")
  artifacts_json=$(fetch_json "$api_base/jobs/$job_id/artifacts")
fi

echo "Job:"
jq . <<<"$job_json"
echo "Trials:"
jq . <<<"$trials_json"
echo "Artifacts:"
jq . <<<"$artifacts_json"

if [ "$state" != "succeeded" ]; then
  echo "Job $job_id finished with state=$state" >&2
  exit 1
fi

if [ -z "$runner_id" ]; then
  echo "Job $job_id succeeded without a runner_id assignment" >&2
  exit 1
fi

if [ "$require_trials" -ne 0 ]; then
  assert_json_count_at_least "trial count" "$trials_json" 'length' 1
fi

if [ "$require_result_artifact" -ne 0 ]; then
  assert_json_count_at_least \
    "result artifact count" \
    "$artifacts_json" \
    '[.[] | select(.kind == "result")] | length' \
    1
fi

if [ "$require_artifact_manifest" -ne 0 ]; then
  assert_json_count_at_least \
    "artifact-manifest count" \
    "$artifacts_json" \
    '[.[] | select(.kind == "artifact-manifest")] | length' \
    1
fi

final_runners_json=$(fetch_json "$api_base/runners?stale_after_sec=$stale_after_sec")
if [ "$expect_runners" -gt 0 ]; then
  assert_json_count_at_least \
    "online runner count" \
    "$final_runners_json" \
    '[.[] | select(.state == "online")] | length' \
    "$expect_runners"
fi

if ! jq -e --arg runner_id "$runner_id" '.[] | select(.id == $runner_id)' \
  <<<"$final_runners_json" >/dev/null; then
  echo "Assigned runner $runner_id was not returned by /runners" >&2
  exit 1
fi

echo "Smoke verification passed for job $job_id on runner $runner_id"
