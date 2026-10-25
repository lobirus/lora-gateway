#!/usr/bin/env bash
# Dump both Postgres databases (litellm + gateway) and copy .env into backups/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
chmod 700 backups
ts=$(date +%Y%m%d-%H%M%S)
DC="docker compose"
docker info >/dev/null 2>&1 || DC="sudo -n docker compose"
umask 077
$DC exec -T postgres sh -c 'pg_dumpall -U "$POSTGRES_USER" --clean --if-exists' | gzip -9 > "backups/lora-gateway-$ts.sql.gz"
cp .env "backups/env-$ts"
# keep the last 14 backups
ls -1t backups/lora-gateway-*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
ls -1t backups/env-* 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "backups/lora-gateway-$ts.sql.gz"
