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

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup-directory>" >&2
  echo "Example: $0 backups/20260101-120000" >&2
  exit 1
fi

BACKUP_DIR="$1"
SQL_FILE="$BACKUP_DIR/db.sql"
SITES_ARCHIVE="$BACKUP_DIR/sites.tar.gz"

if [[ ! -d "$BACKUP_DIR" || ! -f "$SQL_FILE" || ! -f "$SITES_ARCHIVE" ]]; then
  echo "Error: backup directory must include db.sql and sites.tar.gz" >&2
  exit 1
fi

read -r -p "This will overwrite live DB and site files. Continue? [y/N] " REPLY
if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
  echo "Restore cancelled."
  exit 0
fi

echo "Restoring site files..."
rm -rf data/sites
mkdir -p data

tar -xzf "$SITES_ARCHIVE" -C data

if [[ -f "$BACKUP_DIR/keys.tar.gz" ]]; then
  rm -rf data/keys
  tar -xzf "$BACKUP_DIR/keys.tar.gz" -C data
fi

if [[ -f "$BACKUP_DIR/proxy.tar.gz" ]]; then
  rm -rf data/proxy
  tar -xzf "$BACKUP_DIR/proxy.tar.gz" -C data
fi

echo "Restoring PostgreSQL database..."
if [[ "$(docker compose ps -q db)" == "" ]]; then
  echo "Error: db service is not running. Start it with: docker compose up -d db" >&2
  exit 1
fi

docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SQL_FILE"

echo "Restore complete from $BACKUP_DIR"
