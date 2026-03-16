# farmOS Docker Deployment (farmOS + PostgreSQL + Caddy)

This repository now contains a production-style, self-contained farmOS stack using Docker Compose:

- `www`: official `farmos/farmos` application container
- `db`: PostgreSQL database container
- `proxy`: Caddy reverse proxy terminating HTTP/HTTPS

Only the reverse proxy publishes host ports (`80` and `443` by default). The app and database stay internal to Docker networking.

## Why Caddy for this stack?

Caddy is used because it gives a simple, reliable first-run HTTPS path without host-installed tooling. This stack uses `tls internal` for bootstrap certificates so HTTPS works immediately on clean machines (with expected browser trust warnings until you install/trust a cert or switch to public ACME TLS).

---

## Architecture summary

### Services

- **proxy** (`caddy:2.8.4`): ingress on `:80/:443`, forwards requests to `www:80`, forwards standard proxy headers.
- **www** (`farmos/farmos:3.5.1`): farmOS/Drupal application.
- **db** (`postgres:16.6`): PostgreSQL backend for farmOS.

### Exposed ports

- Host `80 -> proxy:80`
- Host `443 -> proxy:443`

(`HTTP_PORT`/`HTTPS_PORT` are configurable in `.env`.)

### Persistence

Persistent data lives under `./data/`:

- `data/sites/` → mounted to `/opt/drupal/web/sites` (farmOS site config/files)
- `data/postgres/` → PostgreSQL data directory
- `data/keys/` → optional extra key storage for future integrations
- `data/proxy/` → Caddy runtime state/cert cache/config

Only farmOS `sites` data is persisted from the app container (not the whole codebase), matching production best practices.

---

## Prerequisites

- Docker Engine
- Docker Compose plugin (`docker compose` command)

---

## First-time setup

1. Copy and edit environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit at minimum:
   - `SITE_HOSTNAME` (`localhost` for local-first)
   - `POSTGRES_PASSWORD` (strong random secret)
   - Optionally `SITE_EMAIL`, `TZ`, upload/port values.

3. Run setup helper:

   ```bash
   ./scripts/setup.sh
   ```

4. Start stack:

   ```bash
   docker compose up -d
   ```

5. Open:
   - `http://localhost` (or your `SITE_HOSTNAME`)
   - `https://localhost` (self-signed/internal CA warning expected initially)

---

## farmOS web installer values (exact)

When the installer asks for database settings, use:

- **Database type:** `PostgreSQL`
- **Database host:** `db`
- **Database port:** `5432`
- **Database name:** value of `POSTGRES_DB` in `.env`
- **Database username:** value of `POSTGRES_USER` in `.env`
- **Database password:** value of `POSTGRES_PASSWORD` in `.env`
- **Table prefix:** leave blank unless you specifically need one

---

## Post-install required step

After the installer creates `settings.php`, run:

```bash
./scripts/post-install.sh
```

This script is idempotent and will:

- ensure private files dir exists: `data/sites/default/private/files`
- update `settings.php` with:
  - `$settings['file_private_path'] = '/opt/drupal/web/sites/default/private/files';`
  - reverse proxy trust settings for Docker-private CIDRs (`TRUSTED_PROXY_CIDRS`)
  - trusted host patterns including `SITE_HOSTNAME` and localhost defaults
- attempt `drush cr` cache clear

If `settings.php` is missing, the script exits with a helpful message (installer not finished yet).

---

## Start / stop / restart

```bash
# Start (or update running services)
docker compose up -d

# Stop services
docker compose down

# Restart services
docker compose restart

# Pull updated images and recreate
docker compose pull
docker compose up -d
```

---

## Logs and troubleshooting

```bash
# All service logs
docker compose logs -f

# Single service logs
docker compose logs -f proxy
docker compose logs -f www
docker compose logs -f db

# Service status + health
docker compose ps
```

Compose healthchecks:
- `db`: `pg_isready`
- `www`: `apache2ctl -t`
- `proxy`: `caddy version`

---

## Persistence model

Survives container recreation:

- farmOS site config/files (`data/sites`)
- database contents (`data/postgres`)
- proxy state/certs (`data/proxy`)
- optional keys (`data/keys`)

Does **not** persist app code itself; app code comes from the pinned `farmos/farmos` image, which keeps upgrades cleaner and avoids accidental drift.

---

## Backup and restore

### Create backup

```bash
./scripts/backup.sh
```

Creates `backups/<timestamp>/` with:

- `db.sql` (PostgreSQL dump)
- `sites.tar.gz`
- optionally `keys.tar.gz`
- optionally `proxy.tar.gz`

### Restore backup

```bash
./scripts/restore.sh backups/<timestamp>
```

Restore script safety notes:

- prompts for confirmation before destructive overwrite
- restores site files archives
- drops/recreates `public` schema then imports SQL
- requires running DB service (`docker compose up -d db` if needed)

---

## Upgrade guidance

1. **Back up first** (`./scripts/backup.sh`).
2. Review farmOS release/update notes before changing versions.
3. Update pinned image tags in `.env` (especially `FARMOS_IMAGE_TAG`).
4. Pull and recreate containers:

   ```bash
   docker compose pull
   docker compose up -d
   ```

5. Run any required farmOS/Drupal database updates (eg `drush updb -y`) and cache clear.
6. Avoid blind major-version jumps; stage/test upgrades first.

---

## Cron guidance

Run cron manually:

```bash
docker compose exec -T www drush cron
```

Optional host cron example (every 15 min):

```cron
*/15 * * * * cd /path/to/repo && docker compose exec -T www drush cron >/dev/null 2>&1
```

---

## Reverse proxy + Drupal trust notes

Because TLS terminates at proxy, Drupal/farmOS must trust proxy headers.

`./scripts/post-install.sh` writes `settings.php` entries for:

- reverse proxy enabled
- trusted forwarded headers
- trusted proxy CIDRs from `TRUSTED_PROXY_CIDRS`
- trusted host patterns including `SITE_HOSTNAME`

For public deployments, narrow trusted host/proxy values as tightly as possible.

---

## Extensibility

- Add companion services on the same Compose network and reference `www`, `db`, or `proxy` by service name.
- You can later evolve to custom farmOS modules/themes via bind mounts or a custom derivative image while keeping this baseline as stable infrastructure.

---

## Repository layout

```text
.
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── data/
│   ├── sites/
│   ├── postgres/
│   ├── keys/
│   └── proxy/
│       ├── data/
│       └── config/
├── proxy/
│   └── Caddyfile
└── scripts/
    ├── setup.sh
    ├── post-install.sh
    ├── backup.sh
    └── restore.sh
```
