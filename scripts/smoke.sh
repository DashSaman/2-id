#!/usr/bin/env bash
set -euo pipefail
base=${BASE_URL:-http://127.0.0.1:18220}
curl -fsS "$base/health/live" | grep -q 'ok'
curl -fsS "$base/health/ready" | grep -q 'ready'
echo SMOKE_OK
