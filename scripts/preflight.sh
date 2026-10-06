#!/usr/bin/env bash
set -euo pipefail
fail(){ echo "PRECHECK_FAIL: $*" >&2; exit 1; }
free_kb=$(df --output=avail / | tail -1 | tr -d ' ')
(( free_kb >= 5*1024*1024 )) || fail "root filesystem has less than 5 GiB free"

if ss -lntH '( sport = :18220 )' | grep -q .; then
  if docker ps --format '{{.Names}}' | grep -Fxq twoid_api && docker port twoid_api 8000/tcp 2>/dev/null | grep -Fq '127.0.0.1:18220'; then
    :
  else
    fail "127.0.0.1:18220 is occupied by a foreign process"
  fi
fi

if ip route show table all | grep -Fq '172.28.235.0/24'; then
  if ! docker network inspect twoid_internal >/dev/null 2>&1; then
    fail "172.28.235.0/24 overlaps an existing foreign route"
  fi
fi

if docker network inspect twoid_internal >/dev/null 2>&1; then
  subnet=$(docker network inspect twoid_internal --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
  [[ "$subnet" == "172.28.235.0/24" ]] || fail "existing twoid_internal has unexpected subnet"
fi

for n in pv-growth-app akhbot-app pv-reseller-dashboard nine-router; do
  docker ps --format '{{.Names}}' | grep -Fxq "$n" || fail "protected container $n is not running"
done
echo PRECHECK_OK
