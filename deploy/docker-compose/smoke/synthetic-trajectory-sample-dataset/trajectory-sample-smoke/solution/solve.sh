#!/usr/bin/env bash
set -euo pipefail

mkdir -p /logs/agent /logs/artifacts /workdir
printf 'synthetic-trajectory-sample-ok\n' > /workdir/synthetic-smoke-output.txt

cat >/logs/agent/trajectory.json <<'JSON'
{
  "schema_version": "ATIF-v1.7",
  "session_id": "synthetic-smoke-session",
  "trajectory_id": "synthetic-smoke-trajectory",
  "agent": {
    "name": "oracle",
    "version": "1.0"
  },
  "steps": [
    {
      "step_id": 1,
      "source": "user",
      "message": "Generate one synthetic data sample for the smoke test."
    },
    {
      "step_id": 2,
      "source": "agent",
      "message": "I created the sample artifact and verification file.",
      "tool_calls": [
        {
          "tool_call_id": "call-write-sample",
          "function_name": "write_file",
          "arguments": {
            "path": "/logs/artifacts/samples.json"
          }
        }
      ],
      "observation": {
        "results": [
          {
            "source_call_id": "call-write-sample",
            "content": "Wrote /logs/artifacts/samples.json"
          }
        ]
      }
    }
  ]
}
JSON

cat >/logs/artifacts/samples.json <<'JSON'
{
  "samples": [
    {
      "id": "synthetic-smoke-sample-1",
      "task": "trajectory-sample-smoke",
      "prompt": "Generate one synthetic data sample for the smoke test.",
      "response": "synthetic-trajectory-sample-ok",
      "trajectory_schema": "ATIF-v1.7"
    }
  ]
}
JSON
