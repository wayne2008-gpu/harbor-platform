#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
compose_dir=$(cd "$script_dir/.." && pwd)
platform_root=$(cd "$compose_dir/../.." && pwd)
harbor_dir="$platform_root/harbor"

api_base=${HARBOR_RABBITMQ_SMOKE_API_BASE:-http://localhost:8080}
rabbitmq_url=${HARBOR_RABBITMQ_SMOKE_RABBITMQ_URL:-amqp://guest:guest@localhost:5672/%2F}
rabbitmq_exchange=${HARBOR_RABBITMQ_SMOKE_RABBITMQ_EXCHANGE:-}
rabbitmq_queue=${HARBOR_RABBITMQ_SMOKE_RABBITMQ_QUEUE:-harbor_jobs}
rabbitmq_routing_key=${HARBOR_RABBITMQ_SMOKE_RABBITMQ_ROUTING_KEY:-$rabbitmq_queue}
job_queue=${HARBOR_RABBITMQ_SMOKE_JOB_QUEUE:-rabbitmq-smoke}
job_file=${HARBOR_RABBITMQ_SMOKE_JOB_FILE:-$compose_dir/smoke/docker-touch-file-smoke-job.local.json}
timeout_sec=${HARBOR_RABBITMQ_SMOKE_TIMEOUT_SEC:-900}
runner_timeout_sec=${HARBOR_RABBITMQ_SMOKE_RUNNER_TIMEOUT_SEC:-120}
metadata_timeout_sec=${HARBOR_RABBITMQ_SMOKE_METADATA_TIMEOUT_SEC:-120}
poll_interval_sec=${HARBOR_RABBITMQ_SMOKE_POLL_INTERVAL_SEC:-2}
purge_queue=${HARBOR_RABBITMQ_SMOKE_PURGE_QUEUE:-0}
runner_id=${HARBOR_RABBITMQ_SMOKE_RUNNER_ID:-rabbitmq-smoke-$(date +%s)}
work_dir=${HARBOR_RABBITMQ_SMOKE_WORK_DIR:-$compose_dir/.local/rabbitmq-claim-smoke}
runner_config="$work_dir/runner-$runner_id.toml"
runner_log="$work_dir/runner-$runner_id.log"
jobs_dir="$work_dir/jobs-$runner_id"

runner_pid=""

cleanup() {
  if [ -n "$runner_pid" ] && kill -0 "$runner_pid" >/dev/null 2>&1; then
    kill "$runner_pid" >/dev/null 2>&1 || true
    wait "$runner_pid" >/dev/null 2>&1 || true
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

print_runner_log_tail() {
  if [ -f "$runner_log" ]; then
    echo "Runner log tail:"
    tail -n 200 "$runner_log"
  fi
}

ensure_runner_alive() {
  if [ -n "$runner_pid" ] && ! kill -0 "$runner_pid" >/dev/null 2>&1; then
    echo "Runner process exited unexpectedly" >&2
    print_runner_log_tail >&2
    exit 1
  fi
}

wait_for_runner() {
  local deadline=$((SECONDS + runner_timeout_sec))
  local runners_json online_count
  while [ "$SECONDS" -lt "$deadline" ]; do
    ensure_runner_alive
    runners_json=$(fetch_json "$api_base/runners?stale_after_sec=30")
    online_count=$(
      jq -r --arg runner_id "$runner_id" \
        '[.[] | select(.id == $runner_id and .state == "online")] | length' \
        <<<"$runners_json"
    )
    echo "$(date -Is) rabbitmq_smoke_runner_online=$online_count"
    if [ "$online_count" -ge 1 ]; then
      return
    fi
    sleep "$poll_interval_sec"
  done

  echo "Timed out waiting for runner $runner_id to register" >&2
  fetch_json "$api_base/runners?stale_after_sec=30" | jq . >&2 || true
  print_runner_log_tail >&2
  exit 1
}

purge_dispatch_queue_if_requested() {
  if [ "$purge_queue" != "1" ]; then
    return
  fi
  echo "Purging RabbitMQ dispatch queue $rabbitmq_queue"
  (
    cd "$harbor_dir"
    HARBOR_RABBITMQ_SMOKE_RABBITMQ_URL="$rabbitmq_url" \
    HARBOR_RABBITMQ_SMOKE_RABBITMQ_QUEUE="$rabbitmq_queue" \
    HARBOR_RABBITMQ_SMOKE_RABBITMQ_EXCHANGE="$rabbitmq_exchange" \
    HARBOR_RABBITMQ_SMOKE_RABBITMQ_ROUTING_KEY="$rabbitmq_routing_key" \
      uv run python - <<'PY'
import os

import pika

url = os.environ["HARBOR_RABBITMQ_SMOKE_RABBITMQ_URL"]
queue = os.environ["HARBOR_RABBITMQ_SMOKE_RABBITMQ_QUEUE"]
exchange = os.environ["HARBOR_RABBITMQ_SMOKE_RABBITMQ_EXCHANGE"]
routing_key = os.environ["HARBOR_RABBITMQ_SMOKE_RABBITMQ_ROUTING_KEY"]

connection = pika.BlockingConnection(pika.URLParameters(url))
try:
    channel = connection.channel()
    channel.queue_declare(queue=queue, durable=True)
    if exchange:
        channel.exchange_declare(exchange=exchange, exchange_type="direct", durable=True)
        channel.queue_bind(queue=queue, exchange=exchange, routing_key=routing_key)
    channel.queue_purge(queue=queue)
finally:
    connection.close()
PY
  )
}

write_runner_config() {
  mkdir -p "$work_dir" "$jobs_dir"
  cat >"$runner_config" <<EOF
runner_id = "$runner_id"
jobs_dir = "$jobs_dir"
max_running_jobs = 1
poll_interval_sec = 1
control_plane_url = "$api_base"
poll_control_plane_jobs = false
control_plane_queue_limit = 1
dispatch_max_messages = 1
dispatch_wait_sec = 1
rabbitmq_url = "$rabbitmq_url"
rabbitmq_exchange = "$rabbitmq_exchange"
rabbitmq_queue = "$rabbitmq_queue"
rabbitmq_routing_key = "$rabbitmq_routing_key"
rabbitmq_prefetch_count = 1
queues = ["$job_queue"]

[queue_quotas]
$job_queue = 1

[artifact_storage]
backend = "runner-local"
retain_local = true
upload_manifest = true
upload_policy = "job_dir_all"

[input_materialization]
backend = "none"

[capabilities]
providers = ["docker"]
features = []

[capabilities.labels]
smoke = "rabbitmq-claim"
EOF
}

start_runner() {
  echo "Starting RabbitMQ-only runner $runner_id"
  (
    cd "$harbor_dir"
    HARBOR_RUNNER_ID="$runner_id" \
      uv run harbor runner start --config "$runner_config" --keep-alive
  ) >"$runner_log" 2>&1 &
  runner_pid=$!
}

build_job_payload() {
  HARBOR_PLATFORM_ROOT="$platform_root" \
  HARBOR_RABBITMQ_SMOKE_JOB_QUEUE="$job_queue" \
  HARBOR_RABBITMQ_SMOKE_RUNNER_ID="$runner_id" \
    python3 - "$job_file" <<'PY'
import json
import os
import sys
from pathlib import Path

payload = json.loads(os.path.expandvars(Path(sys.argv[1]).read_text()))
payload["queue"] = os.environ["HARBOR_RABBITMQ_SMOKE_JOB_QUEUE"]
payload["priority"] = int(os.environ.get("HARBOR_RABBITMQ_SMOKE_PRIORITY", "10"))
requirements = payload.setdefault("requirements", {})
requirements["provider"] = "docker"
requirements.setdefault("labels", {})
job_config = payload.setdefault("job_config", {})
base_name = job_config.get("job_name") or "rabbitmq-claim-smoke"
suffix = os.environ["HARBOR_RABBITMQ_SMOKE_RUNNER_ID"]
job_config["job_name"] = f"{base_name}-{suffix}"
print(json.dumps(payload))
PY
}

submit_job() {
  local payload=$1
  curl -fsS \
    -H 'content-type: application/json' \
    --data-binary "$payload" \
    "$api_base/jobs" | jq -r .id
}

wait_for_job_terminal() {
  local job_id=$1
  local deadline=$((SECONDS + timeout_sec))
  local state
  while [ "$SECONDS" -lt "$deadline" ]; do
    ensure_runner_alive
    state=$(fetch_json "$api_base/jobs/$job_id" | jq -r .state)
    echo "$(date -Is) job=$job_id state=$state"
    case "$state" in
      succeeded|failed|cancelled|timed_out)
        return
        ;;
    esac
    sleep "$poll_interval_sec"
  done
  echo "Timed out waiting for job $job_id" >&2
  print_runner_log_tail >&2
  exit 1
}

wait_for_metadata() {
  local job_id=$1
  local deadline=$((SECONDS + metadata_timeout_sec))
  local trials_json artifacts_json trial_count artifact_count
  while [ "$SECONDS" -lt "$deadline" ]; do
    trials_json=$(fetch_json "$api_base/jobs/$job_id/trials")
    artifacts_json=$(fetch_json "$api_base/jobs/$job_id/artifacts")
    trial_count=$(jq -r 'length' <<<"$trials_json")
    artifact_count=$(jq -r 'length' <<<"$artifacts_json")
    echo "$(date -Is) trial_count=$trial_count artifact_count=$artifact_count"
    if [ "$trial_count" -ge 1 ] && [ "$artifact_count" -ge 1 ]; then
      return
    fi
    sleep "$poll_interval_sec"
  done
  echo "Timed out waiting for job metadata" >&2
  exit 1
}

require_command curl
require_command jq
require_command python3
require_command uv
require_command docker

curl -fsS "$api_base/ready" >/dev/null
docker version >/dev/null

purge_dispatch_queue_if_requested
write_runner_config
start_runner
wait_for_runner

payload=$(build_job_payload)
job_id=$(submit_job "$payload")
if [ -z "$job_id" ] || [ "$job_id" = "null" ]; then
  echo "Failed to submit RabbitMQ claim smoke job" >&2
  exit 1
fi

echo "Submitted RabbitMQ claim smoke job: $job_id"
wait_for_job_terminal "$job_id"
job_json=$(fetch_json "$api_base/jobs/$job_id")
state=$(jq -r .state <<<"$job_json")
assigned_runner=$(jq -r '.runner_id // empty' <<<"$job_json")
actual_queue=$(jq -r .queue <<<"$job_json")

if [ "$state" != "succeeded" ]; then
  echo "Expected job state succeeded, got $state" >&2
  jq . <<<"$job_json" >&2
  print_runner_log_tail >&2
  exit 1
fi
if [ "$assigned_runner" != "$runner_id" ]; then
  echo "Expected runner_id=$runner_id, got ${assigned_runner:-empty}" >&2
  jq . <<<"$job_json" >&2
  exit 1
fi
if [ "$actual_queue" != "$job_queue" ]; then
  echo "Expected job queue=$job_queue, got $actual_queue" >&2
  jq . <<<"$job_json" >&2
  exit 1
fi

wait_for_metadata "$job_id"

echo "Job:"
jq . <<<"$job_json"
echo "RabbitMQ claim smoke passed for job $job_id on runner $runner_id"
