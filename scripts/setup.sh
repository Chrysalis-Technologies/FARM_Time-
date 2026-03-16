#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is required but not found in PATH." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Error: docker compose plugin is required (docker compose)." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Error: .env not found. Copy .env.example to .env and edit values first:" >&2
  echo "  cp .env.example .env" >&2
  exit 1
fi

mkdir -p \
  data/sites/default/private/files \
  data/postgres \
  data/keys \
  data/proxy/data \
  data/proxy/config \
  backups

chmod +x scripts/*.sh

echo "Validating Docker Compose configuration..."
docker compose config >/dev/null

echo "Setup complete. Start the stack with:"
echo "  docker compose up -d"
SITE_HOSTNAME_VALUE="localhost"
if grep -qE "^SITE_HOSTNAME=" .env; then
  SITE_HOSTNAME_VALUE="$(grep -E "^SITE_HOSTNAME=" .env | tail -n1 | cut -d= -f2-)"
fi
echo "Then open: http://${SITE_HOSTNAME_VALUE} and complete the farmOS installer."
