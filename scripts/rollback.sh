#!/usr/bin/env bash
set -euo pipefail
for c in twoid_bot twoid_worker twoid_api twoid_postgres; do
  docker rm -f "$c" 2>/dev/null || true
done
docker network rm twoid_internal 2>/dev/null || true
echo "2-id runtime removed; twoid_postgres_data preserved"
