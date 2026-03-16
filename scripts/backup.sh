#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Error: .env not found." >&2
  exit 1
fi

set -a
source .env
set +a

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="backups/$STAMP"
mkdir -p "$OUT_DIR"

echo "Creating PostgreSQL dump..."
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$OUT_DIR/db.sql"

echo "Archiving persisted farmOS data..."
tar -czf "$OUT_DIR/sites.tar.gz" -C data sites
if [[ -d data/keys ]]; then
  tar -czf "$OUT_DIR/keys.tar.gz" -C data keys
fi
if [[ -d data/proxy ]]; then
  tar -czf "$OUT_DIR/proxy.tar.gz" -C data proxy
fi

echo "Backup complete: $OUT_DIR"
