#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/preflight.sh
[ -f .env ] || { echo ".env missing" >&2; exit 1; }
set -a; source .env; set +a
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD missing}"
: "${APP_ENCRYPTION_KEY:?APP_ENCRYPTION_KEY missing}"
: "${ADMIN_API_KEY:?ADMIN_API_KEY missing}"
: "${PARTNER_KEY_PEPPER:?PARTNER_KEY_PEPPER missing}"

docker build -t twoid_app:local .
docker volume inspect twoid_postgres_data >/dev/null 2>&1 || docker volume create twoid_postgres_data >/dev/null
docker network inspect twoid_internal >/dev/null 2>&1 || docker network create --driver bridge --subnet 172.28.235.0/24 twoid_internal >/dev/null

docker rm -f twoid_postgres twoid_api twoid_worker twoid_bot >/dev/null 2>&1 || true

docker run -d --name twoid_postgres --restart unless-stopped --log-opt max-size=10m --log-opt max-file=5 --network twoid_internal   --network-alias postgres -e POSTGRES_DB=twoid -e POSTGRES_USER=twoid -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD"   -v twoid_postgres_data:/var/lib/postgresql/data postgres:16-alpine >/dev/null

for i in $(seq 1 60); do
  docker exec twoid_postgres pg_isready -U twoid -d twoid >/dev/null 2>&1 && break
  sleep 1
  (( i < 60 )) || { echo "postgres readiness timeout" >&2; exit 1; }
done

common=(--env-file .env --log-opt max-size=10m --log-opt max-file=5 --network twoid_internal -e "DATABASE_URL=postgresql+psycopg://twoid:${POSTGRES_PASSWORD}@postgres:5432/twoid")
docker run --rm "${common[@]}" twoid_app:local alembic upgrade head

docker run -d --name twoid_api --restart unless-stopped "${common[@]}" -e API_BIND=0.0.0.0 -e API_PORT=8000   -p 127.0.0.1:18220:8000 twoid_app:local python -m app.api_server >/dev/null

docker run -d --name twoid_worker --restart unless-stopped "${common[@]}"   twoid_app:local python -m app.worker >/dev/null

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  docker run -d --name twoid_bot --restart unless-stopped "${common[@]}"     twoid_app:local python -m app.bot >/dev/null
fi

for i in $(seq 1 40); do
  curl -fsS http://127.0.0.1:18220/health/ready >/dev/null && break
  sleep 1
  (( i < 40 )) || { echo "api readiness timeout" >&2; exit 1; }
done
echo DEPLOY_OK
