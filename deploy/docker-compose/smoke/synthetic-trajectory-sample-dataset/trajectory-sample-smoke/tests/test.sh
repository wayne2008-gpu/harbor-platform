#!/usr/bin/env bash
set -euo pipefail

mkdir -p /logs/verifier
if [ -f /workdir/synthetic-smoke-output.txt ] &&
  grep -qx 'synthetic-trajectory-sample-ok' /workdir/synthetic-smoke-output.txt &&
  [ -s /logs/agent/trajectory.json ] &&
  [ -s /logs/artifacts/samples.json ]; then
  echo 1 > /logs/verifier/reward.txt
  echo 'Synthetic trajectory/sample smoke verifier passed'
  exit 0
fi

echo 0 > /logs/verifier/reward.txt
echo 'Synthetic trajectory/sample smoke verifier failed'
exit 1
