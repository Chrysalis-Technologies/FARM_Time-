#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SETTINGS_FILE="data/sites/default/settings.php"
PRIVATE_DIR="data/sites/default/private/files"

if [[ ! -f "$SETTINGS_FILE" ]]; then
  echo "Error: $SETTINGS_FILE not found." >&2
  echo "Complete the farmOS web installer first, then re-run this script." >&2
  exit 1
fi

mkdir -p "$PRIVATE_DIR"

# Keep ownership permissive for containerized www-data usage.
chmod -R u+rwX,go-rwx data/sites/default/private || true

readarray -t ENV_VALUES < <(python - <<'PY'
import os
from pathlib import Path

vals={
  'SITE_HOSTNAME':'localhost',
  'TRUSTED_PROXY_CIDRS':'172.16.0.0/12,10.0.0.0/8,192.168.0.0/16,127.0.0.1',
}
if Path('.env').exists():
  for line in Path('.env').read_text().splitlines():
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line:
      continue
    k,v=line.split('=',1)
    vals[k.strip()]=v.strip()
print(vals['SITE_HOSTNAME'])
print(vals['TRUSTED_PROXY_CIDRS'])
PY
)

SITE_HOSTNAME="${ENV_VALUES[0]}"
TRUSTED_PROXY_CIDRS="${ENV_VALUES[1]}"

BLOCK_START="# >>> farmos-docker post-install settings >>>"
BLOCK_END="# <<< farmos-docker post-install settings <<<"

python - "$SETTINGS_FILE" "$BLOCK_START" "$BLOCK_END" "$SITE_HOSTNAME" "$TRUSTED_PROXY_CIDRS" <<'PY'
import re
from pathlib import Path
import sys

settings_path=Path(sys.argv[1])
block_start=sys.argv[2]
block_end=sys.argv[3]
hostname=sys.argv[4]
proxy_cidrs=[x.strip() for x in sys.argv[5].split(',') if x.strip()]

content=settings_path.read_text()
pattern=re.compile(re.escape(block_start)+r".*?"+re.escape(block_end)+r"\n?", re.S)
content=pattern.sub('', content)

host_patterns=[r'^localhost$', r'^127\\.0\\.0\\.1$', r'^\[::1\]$']
if hostname not in ('localhost','127.0.0.1','[::1]'):
    escaped=re.escape(hostname)
    host_patterns.insert(0, rf'^{escaped}$')

proxy_list=', '.join([f"'{cidr}'" for cidr in proxy_cidrs])
host_list=', '.join([f"'{h}'" for h in host_patterns])
block=f"""\n{block_start}
$settings['file_private_path'] = '/opt/drupal/web/sites/default/private/files';
$settings['reverse_proxy'] = TRUE;
$settings['reverse_proxy_addresses'] = [{proxy_list}];
$settings['reverse_proxy_trusted_headers'] = \\Symfony\\Component\\HttpFoundation\\Request::HEADER_X_FORWARDED_FOR
  | \\Symfony\\Component\\HttpFoundation\\Request::HEADER_X_FORWARDED_HOST
  | \\Symfony\\Component\\HttpFoundation\\Request::HEADER_X_FORWARDED_PORT
  | \\Symfony\\Component\\HttpFoundation\\Request::HEADER_X_FORWARDED_PROTO;
$settings['trusted_host_patterns'] = [{host_list}];
{block_end}
"""
settings_path.write_text(content.rstrip()+"\n"+block)
PY

echo "Post-install settings updated in $SETTINGS_FILE"

echo "Attempting to clear Drupal caches via Drush..."
if docker compose exec -T www drush cr >/dev/null 2>&1; then
  echo "Cache clear succeeded (drush cr)."
else
  echo "Warning: drush cache clear failed. You can re-run once the stack is fully healthy:" >&2
  echo "  docker compose exec -T www drush cr" >&2
fi
