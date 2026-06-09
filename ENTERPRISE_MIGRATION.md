# Enterprise CentOS / Rocky 9 Migration Guide

Full data app migration: wipe and rebuild the database from a dump file while preserving user accounts. All operations work against the hardened Docker daemon found on enterprise / kiosk hosts.

> ## ⚠ Enterprise Docker daemon constraints
>
> The daemon on these hosts enforces strict namespace policies. The following are **blocked** with `setns: permission denied` errors:
>
> - `docker exec` — entering a running container's namespace
> - `docker cp host:path container:path` — same reason
> - `docker rm <existing-container>` — cleanup setns fails
> - `docker run --rm <...>` — the teardown setns at container exit fails
> - `docker run --network <custom-bridge>` — requires `/proc/<pid>/ns/net` bind mount that the daemon denies
>
> Everything in this guide is written to avoid those operations. We use:
>
> - `--network host` everywhere — no bridge networks, no netns bind mounts. Containers share the host's network stack and reach each other at `127.0.0.1:<port>`.
> - **Native host binaries** (`psql`, `pg_dump`, `pg_restore`, `pg_isready`) for every DB admin operation. The Postgres container is host-networked, so the host can connect to it over TCP without entering its namespace.
> - **No `--rm`** on any container. Short-lived admin containers exit and stay in `Exited` state. Ignore them; they don't consume resources and can't be cleanly removed on this daemon.
> - **`docker start || docker run`** as the idempotent pattern for starting services. `docker start` on an existing stopped container does not trigger setns.
> - **New container names** (`sp_prod_app_v2`, `sp_prod_app_v3`, …) when you need to relaunch with different env vars, since `docker rm` of the previous one is blocked.
>
> See [`PRODUCTION_DOCKER_RUN.md`](./PRODUCTION_DOCKER_RUN.md) for the full operator's reference.

---

## Prerequisites

On the enterprise host:

- Docker installed and running (`sudo systemctl start docker`).
- The cloned/ported repo at a known path (e.g., `/opt/softpower/`).
- The database dump file (e.g., `softpower-full.dump`) transferred to the system.
- The Docker images either pulled from a registry or loaded from `.tar` files.
- **Postgres client tools installed natively on the host** — `psql`, `pg_dump`, `pg_restore`, `pg_isready`. Required because `docker exec` is unavailable. Install via:
  ```bash
  # Rocky 9 / RHEL via PGDG repo
  sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
  sudo dnf install -y postgresql17

  # Or via conda (if internet/pre-staged channel is available)
  conda install -y -c conda-forge postgresql=17

  # Verify
  which psql pg_dump pg_restore pg_isready
  ```
  The client major version should match (or exceed) the server major you'll deploy. We use pg17 throughout.

---

## Phase 0: Verify Docker and Load Images

```bash
# Verify Docker is running
sudo docker info

# If images are in .tar files (air-gapped transfer):
sudo docker load -i softpower-analytics.tar
sudo docker load -i pgvector-pg17.tar

# If pulling from a registry:
sudo docker pull mmorrisj/softpower-analytics:latest
sudo docker pull mmorrisj/pgvector:0.8.1-pg17

# Verify images are available
sudo docker images | grep -E "softpower|pgvector"
```

---

## Phase 1: Configure Environment Variables

### 1.1 Create/Update the `.env` file

```bash
cd /opt/softpower    # or wherever the repo lives
cp .env.example .env
```

### 1.2 Edit `.env` — key variables

Open `.env` in your editor and set these. **No inline comments** — `--env-file` loaders treat everything after `=` as the value (including `# comment` text). Put comments on their own lines.

```bash
# ==========================================
# DATABASE (required)
# ==========================================
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password
POSTGRES_DB=softpower_db
DB_HOST=127.0.0.1
DB_PORT=5432

# ==========================================
# LLM CONFIGURATION (required for AI features)
# ==========================================
# OPTION A: LiteLLM (enterprise endpoint — MOST LIKELY for enterprise)
LITELLM_URL=https://your-enterprise-litellm-endpoint/v1
LITELLM_MODEL=gpt-4o-mini
# Authentication: the enterprise LiteLLM endpoint authenticates by the gateway
# JWT (x-kiosk-gateway-jwt), which the app forwards automatically — no API key
# is needed in production. LITELLM_API_KEY is an OPTIONAL fallback for
# non-enterprise/dev setups where the endpoint expects a static key instead.
# LITELLM_API_KEY=your-litellm-api-key

# OPTION B: Azure OpenAI
# ENV=production
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_API_KEY=your-azure-key
# AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

# ==========================================
# LLM PROXY RELAY (optional — keeps LLM creds off the container)
# ==========================================
# If you run the host-side proxy on this port, set API_URL=http://127.0.0.1:7001
# below and blank the LITELLM_* vars on the container (see Phase 7.2).
# If you don't run the host proxy, the container's own /proxy_query_stream
# handles LLM calls and you should set API_URL=http://127.0.0.1:8000 instead.
LLM_PROXY_PORT=7001

# ==========================================
# AWS S3 (if using S3 for document ingestion)
# ==========================================
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
S3_BUCKET=your-bucket-name
S3_REGION=us-east-1

# ==========================================
# JWT / AUTH
# ==========================================
JWT_SECRET=your-secure-random-string-at-least-32-characters-long
JWT_EXPIRATION_HOURS=24
# Set DEV_AUTH_BYPASS=true only for pre-gateway testing; production should be false.
DEV_AUTH_BYPASS=false
DEV_AUTH_ROLE=admin

# ==========================================
# DEPLOYMENT MODE
# ==========================================
DEPLOY_MODE=production
DOCKER_ENV=true

# ==========================================
# PORTS
# ==========================================
API_PORT=8000
STREAMLIT_PORT=8501

# ==========================================
# REDIS (optional — swap image for enterprise-hardened version)
# ==========================================
# REDIS_IMAGE=dhi/redis:7
```

### 1.3 Environment Variable Reference

| Variable | Purpose | Required |
|----------|---------|----------|
| `POSTGRES_USER` | Database username | Yes |
| `POSTGRES_PASSWORD` | Database password | Yes |
| `POSTGRES_DB` | Target database name | Yes |
| `DB_HOST` | Always `127.0.0.1` under `--network host` | Yes |
| `DB_PORT` | DB port (default 5432) | Yes |
| `LITELLM_URL` / `LITELLM_API_KEY` | LiteLLM enterprise endpoint | If using LiteLLM |
| `LLM_PROXY_PORT` | Host LLM proxy port (default 7001) | Only if using host proxy |
| `API_URL` | Where `gai()` and the chat stream POST proxy requests | Yes |
| `DEV_AUTH_BYPASS` | Skip gateway JWT validation; `true` only for pre-gateway testing | No |
| `JWT_SECRET` | Min 32 char random string for any local JWT signing | Yes |
| `AWS_ACCESS_KEY_ID` | S3 access | Only if using S3 |
| `REDIS_IMAGE` | Enterprise Redis image override | No |
| `APP_IMAGE` | Override app image name | No |
| `DB_IMAGE` | Override DB image name | No |

---

## Phase 2: Stop Existing Services (if running)

```bash
# Check what's currently running
sudo docker ps -a --filter "name=sp_prod"

# Stop existing containers — do NOT try to remove them; docker rm is blocked.
# The stopped containers will be reused by `docker start` in later phases, or
# ignored if we relaunch under different names.
sudo docker stop sp_prod_app sp_prod_redis sp_prod_db 2>/dev/null || true
```

If a container is wedged in `Restarting` or `Created` state and you really need it gone, the only reliable cleanup is a daemon-level operation outside this guide's scope. In practice, ignore the dead container — it doesn't hold resources.

---

## Phase 3: Export Users from Existing Database (BEFORE wiping)

If there's an existing database with users you want to preserve, export them first.

### 3.1 Start ONLY the database container

```bash
sudo docker start sp_prod_db 2>/dev/null || sudo docker run -d \
    --name sp_prod_db \
    --network host \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --cap-add SETGID --cap-add SETUID \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -e PGPORT="${DB_PORT:-5432}" \
    -v softpower_production_prod_pgdata:/var/lib/postgresql/data \
    --shm-size=1g \
    mmorrisj/pgvector:0.8.1-pg17
```

### 3.2 Wait for the database to be ready

Native `pg_isready` from the host — no sidecar container:

```bash
until PGPASSWORD="$POSTGRES_PASSWORD" pg_isready \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    echo "Waiting for database..."
    sleep 2
done
echo "Database is ready"
```

### 3.3 Export the users table

```bash
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --table=users --data-only --column-inserts \
    --no-owner --no-privileges \
    -f users_backup.sql

# Verify the export
head -20 users_backup.sql
echo "---"
echo "User count: $(grep -c 'INSERT INTO' users_backup.sql)"
```

### 3.4 Stop the database (don't remove it)

```bash
sudo docker stop sp_prod_db
# Do NOT docker rm — blocked by setns. The stopped container is reused below.
```

---

## Phase 4: Wipe and Rebuild the Database

### 4.1 Remove the old database volume

The volume isn't a container, so `docker volume rm` works. Make sure no container has it mounted first.

```bash
# THIS DESTROYS ALL DATA — make sure you have softpower-full.dump and users_backup.sql.
# Stop the DB container (Phase 3.4) so the volume is not in use.
sudo docker volume rm softpower_production_prod_pgdata 2>/dev/null
sudo docker volume create softpower_production_prod_pgdata
```

### 4.2 Start a fresh PostgreSQL container

Because the volume was wiped, we can't reuse the existing `sp_prod_db` stopped container (it's tied to the old volume's internal state). Launch under a new name:

```bash
set -a; source .env; set +a

sudo docker run -d \
    --name sp_prod_db_fresh \
    --network host \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --cap-add SETGID --cap-add SETUID \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -e PGPORT="${DB_PORT:-5432}" \
    -v softpower_production_prod_pgdata:/var/lib/postgresql/data \
    --shm-size=1g \
    mmorrisj/pgvector:0.8.1-pg17
```

(`sp_prod_db` from before is stopped and ignored. From this point on, use `sp_prod_db_fresh` as the canonical DB container.)

### 4.3 Wait for PostgreSQL to initialize

```bash
until PGPASSWORD="$POSTGRES_PASSWORD" pg_isready \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    echo "Waiting..."
    sleep 2
done
echo "PostgreSQL is ready"
```

### 4.4 Enable required PostgreSQL extensions

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "CREATE EXTENSION IF NOT EXISTS vector;" \
    -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
    -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');"
```

### 4.5 Restore the dump file

Single-file dump (custom format from `pg_dump -F c`):

```bash
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
    --verbose --no-owner --no-privileges --jobs=4 \
    --clean --if-exists \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    softpower-full.dump 2>&1 | tee restore.log

# pg_restore may return non-zero on warnings — that is normal.
# Real errors look like "could not connect" or "out of memory".
```

If your export is **chunked** (manifest.json + chunk files from `scripts/db_export.py`):

```bash
# Verify checksums and manifest
python scripts/db_import.py --input-dir ./chunks_dir --dry-run

# Reassemble in manifest order
python -c "
import json, pathlib
d = pathlib.Path('./chunks_dir')
m = json.loads((d/'manifest.json').read_text())
out = d/'reassembled.dump'
with open(out, 'wb') as fo:
    for c in m['chunks']:
        fo.write((d/c['file']).read_bytes())
print('wrote', out, 'size', out.stat().st_size)
"

# Restore
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
    --verbose --no-owner --no-privileges --jobs=4 \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    ./chunks_dir/reassembled.dump 2>&1 | tee restore.log
```

**Do not** run `scripts/db_import.py` with `--docker-container` — it launches an ephemeral `pg_restore` container with `--rm` and a custom network, both of which trigger setns failures.

### 4.6 Run Alembic migrations

Two options. Pick whichever your enclave supports.

**Option A — run alembic natively on the host** (cleanest if Python env is available):

```bash
cd /opt/softpower
set -a; source .env; set +a
DB_HOST=127.0.0.1 alembic upgrade head
```

**Option B — short-lived migration container, no `--rm`**, timestamped name so it doesn't clash:

```bash
sudo docker run --name sp_migrate_$(date +%s) \
    --network host \
    -e DOCKER_ENV=true \
    -e DB_HOST=127.0.0.1 -e POSTGRES_HOST=127.0.0.1 \
    -e DB_PORT="${DB_PORT:-5432}" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    mmorrisj/softpower-analytics:latest \
    alembic upgrade head
```

The container exits when migrations complete. The stopped container record is harmless; leave it. (Do not try `docker rm` — blocked by setns.)

### 4.7 Verify the schema

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT relname AS table_name, reltuples::bigint AS approx_rows
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r' AND n.nspname = 'public'
        ORDER BY reltuples DESC
        LIMIT 30;"
```

---

## Phase 5: Restore Users

### 5.1 Clear imported users

The dump may contain stale or different user records from the source environment.

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "DELETE FROM users;"
```

### 5.2 Restore the preserved users

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -f users_backup.sql
```

### 5.3 Verify users are restored

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT username, role, display_name, is_active, last_login
        FROM users ORDER BY last_login DESC NULLS LAST;"
```

### 5.4 (First deployment only) Promote your gateway user to admin

Under the enterprise JWT model, users are auto-provisioned as `viewer` the first time they hit the app via the gateway. To pre-create an admin, or to promote your own gateway identity once it's been auto-provisioned:

```bash
# After hitting the app once via the gateway URL, find your gateway username:
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT username, role FROM users ORDER BY last_login DESC LIMIT 5;"

# Promote:
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "UPDATE users SET role='admin' WHERE username='your-gateway-username';"
```

---

## Phase 6: Run ANALYZE (Optimize Query Performance)

After a full restore, update PostgreSQL statistics:

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "ANALYZE VERBOSE;" 2>&1 | tail -10
```

---

## Phase 7: Start the Full Application Stack

### 7.1 Start Redis

```bash
sudo docker start sp_prod_redis 2>/dev/null || sudo docker run -d \
    --name sp_prod_redis \
    --network host \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add SETGID --cap-add SETUID \
    ${REDIS_IMAGE:-redis:7-alpine} \
    redis-server --bind 127.0.0.1 --port 6379

# Verify Redis is running (native redis-cli, no sidecar)
until redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; do
    echo "Waiting for Redis..."
    sleep 1
done
echo "Redis is ready"
```

If `redis-cli` isn't installed on the host, `nc -z 127.0.0.1 6379 && echo OK` works as a basic reachability test.

### 7.2 Start the application container

```bash
sudo docker start sp_prod_app 2>/dev/null || sudo docker run -d \
    --name sp_prod_app \
    --network host \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --env-file .env \
    -e DOCKER_ENV=true \
    -e NODE_ENV=production \
    -e DB_HOST=127.0.0.1 \
    -e POSTGRES_HOST=127.0.0.1 \
    -e DB_PORT="${DB_PORT:-5432}" \
    -e POSTGRES_PORT="${DB_PORT:-5432}" \
    -e API_PORT="${API_PORT:-8000}" \
    -e STREAMLIT_PORT="${STREAMLIT_PORT:-8501}" \
    -e DB_POOL_SIZE="${DB_POOL_SIZE:-10}" \
    -e DB_MAX_OVERFLOW="${DB_MAX_OVERFLOW:-20}" \
    -e DB_POOL_TIMEOUT="${DB_POOL_TIMEOUT:-30}" \
    -e DB_POOL_RECYCLE="${DB_POOL_RECYCLE:-3600}" \
    -e API_URL="http://127.0.0.1:${LLM_PROXY_PORT:-7001}" \
    -e S3_PROXY_URL="http://127.0.0.1:${LLM_PROXY_PORT:-7001}" \
    -e USE_S3_API_CLIENT=true \
    -e TRANSFORMERS_OFFLINE=1 \
    -e HF_HUB_OFFLINE=1 \
    -e HF_HOME="/app/.cache/huggingface" \
    -e SENTENCE_TRANSFORMERS_HOME="/app/.cache/huggingface/hub" \
    -e TIKTOKEN_CACHE_DIR="/app/.cache/tiktoken" \
    -e REDIS_URL="redis://127.0.0.1:6379/0" \
    -e DEV_AUTH_BYPASS=false \
    -e LITELLM_URL= -e LITELLM_API_KEY= -e LITELLM_MODEL= \
    -e OPENAI_PROJ_API= -e OPENAI_API_KEY= \
    -e AZURE_OPENAI_ENDPOINT= -e AZURE_OPENAI_API_KEY= \
    mmorrisj/softpower-analytics:latest
```

The trailing `-e LITELLM_URL= -e LITELLM_API_KEY= ...` blocks blank out LLM credentials inside the container even if they're in `.env`. This is the **proxy mode** setup: the container has no way to call LLM APIs directly; all `gai()` calls go via `API_URL` to the host-side proxy.

**Alternative if you don't run the host proxy:** drop those blank `-e LITELLM_*` lines, leave `.env`'s `LITELLM_*` values intact, and set `-e API_URL=http://127.0.0.1:${API_PORT:-8000}`. Then the container's own `/proxy_query_stream` endpoint handles LLM calls using its env vars. Simpler, less isolated.

### 7.3 Wait for the app to become healthy

```bash
until curl -sf "http://127.0.0.1:${API_PORT:-8000}/api/health" >/dev/null 2>&1; do
    echo "Waiting for API..."
    sleep 2
done
echo "Application is healthy"
```

---

## Phase 8: Start the Host-Side LLM Proxy (if using proxy mode)

Skip this phase if you set `API_URL` to the container itself in Phase 7.2.

The container has no LLM credentials in proxy mode. It POSTs to `http://127.0.0.1:7001/proxy_query_stream` and lets the host process do the actual LLM call. The host has certs / DNS / outbound network egress that the container lacks.

### 8.1 Install proxy dependencies

Lightweight — only needs FastAPI / uvicorn / openai / boto3 / dotenv:

```bash
pip install fastapi uvicorn openai boto3 python-dotenv python-multipart
```

(Or use a conda env with the project's full `requirements.txt` if simpler.)

### 8.2 Start the proxy

```bash
cd /opt/softpower
set -a; source .env; set +a
nohup uvicorn server.main:app --host 127.0.0.1 --port "${LLM_PROXY_PORT:-7001}" \
    > /var/log/softpower/proxy.log 2>&1 &
echo $! > /var/run/softpower-proxy.pid

# Verify
curl http://127.0.0.1:${LLM_PROXY_PORT:-7001}/api/health
```

Bind to `127.0.0.1` not `0.0.0.0` — the proxy should only be reachable from the host's loopback, which the container shares via `--network host`.

The proxy's `/proxy_query_stream` endpoint routes based on what's in its env:
1. **LiteLLM** if `LITELLM_URL` + `LITELLM_API_KEY` are set (enterprise default).
2. **Azure OpenAI** if `ENV=production` and Azure vars set.
3. **OpenAI** if `OPENAI_PROJ_API` set (unlikely in enclave).

### 8.3 (Optional) Run the proxy as a systemd service

```bash
sudo tee /etc/systemd/system/softpower-proxy.service > /dev/null << 'EOF'
[Unit]
Description=SoftPower LLM Proxy
After=network.target

[Service]
Type=simple
User=softpower
WorkingDirectory=/opt/softpower
ExecStart=/opt/softpower/.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 7001
Restart=always
RestartSec=5
EnvironmentFile=/opt/softpower/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable softpower-proxy
sudo systemctl start softpower-proxy
sudo systemctl status softpower-proxy
```

---

## Phase 9: Verify Everything Works

### 9.1 Check all containers

```bash
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

You should see `sp_prod_db_fresh`, `sp_prod_redis`, `sp_prod_app` all `Up`. The old `sp_prod_db` (pre-rebuild) may still show `Exited` — leave it.

### 9.2 Check API health

```bash
curl http://127.0.0.1:${API_PORT:-8000}/api/health
```

### 9.3 Check LLM proxy connectivity (proxy mode only)

```bash
curl http://127.0.0.1:${LLM_PROXY_PORT:-7001}/api/health

# End-to-end LLM smoke test
curl -s -X POST http://127.0.0.1:${LLM_PROXY_PORT:-7001}/proxy_query_stream \
    -H "Content-Type: application/json" \
    -d '{"sys_prompt":"You are a test.","prompt":"Say hello","model":"gpt-4o-mini","temperature":0.0,"max_tokens":20}' \
    | head -3
```

### 9.4 Verify document count in database

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT count(*) AS document_count FROM documents;"
```

### 9.5 Verify gateway auth flow

```bash
# Forge a test JWT (signature is not verified — gateway is the security boundary)
TEST_JWT=$(python3 -c "import jwt; print(jwt.encode({'sub':'test','preferred_username':'tester','name':'Tester'}, 'x', algorithm='HS256'))")

curl -i http://127.0.0.1:${API_PORT:-8000}/api/auth/me \
    -H "x-kiosk-gateway-jwt: $TEST_JWT"
# Want: 200 with user JSON. A row for 'tester' should now exist in users.
```

### 9.6 Access the web interfaces

- **React Web App:** `http://<server-ip>:8000` (via gateway URL in production)
- **API Docs:** `http://<server-ip>:8000/docs`
- **Streamlit Dashboard:** `http://<server-ip>:8501`

---

## Troubleshooting

### Container logs

```bash
sudo docker logs -f sp_prod_app
sudo docker logs -f sp_prod_db_fresh
sudo docker logs sp_prod_app 2>&1 | grep -E "ERROR|FATAL|Traceback"
```

`docker logs` reads from the daemon's log files — no setns, always works.

### "setns: permission denied" on `docker exec` / `docker cp` / `docker rm` / `--rm`

You're on the enterprise daemon. Replace the operation with a host-TCP equivalent:

| What you wanted | Use instead |
|---|---|
| `docker exec sp_prod_db psql -U postgres -c "..."` | `psql -h 127.0.0.1 -U "$POSTGRES_USER" -c "..."` |
| `docker exec sp_prod_db pg_dump ...` | `pg_dump -h 127.0.0.1 ...` |
| `docker cp local.sql sp_prod_db:/tmp/` | Use `psql -f local.sql` from the host |
| `docker rm sp_prod_app` | Leave the stopped container; rename future ones |
| `docker run --rm pgvector ... pg_restore` | Native `pg_restore` on the host, or `docker run` without `--rm` |

### LLM calls fail

1. **Check the proxy is reachable** (proxy mode):
   ```bash
   curl http://127.0.0.1:${LLM_PROXY_PORT:-7001}/api/health
   ```
2. **Check `API_URL` inside the container**:
   ```bash
   sudo docker inspect sp_prod_app --format '{{range .Config.Env}}{{println .}}{{end}}' | grep API_URL
   ```
   Should be `http://127.0.0.1:7001` in proxy mode, or `http://127.0.0.1:8000` in container-LLM mode. Must NOT contain `#comment` text — that's the inline-comment-in-`.env` bug.
3. **Verify the LiteLLM endpoint is reachable from the host**:
   ```bash
   curl -H "Authorization: Bearer $LITELLM_API_KEY" "$LITELLM_URL/models"
   ```
4. **Check 500 errors** by tailing the proxy log and triggering a Research query — the SSE response body contains the actual error from the LLM SDK.

### Database connection issues

```bash
# Test from the host
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "${DB_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT 1 AS connected;"
```

### "role appuser does not exist"

`POSTGRES_USER` is empty in the application container's environment, so libpq fell back to the container's OS user (`appuser`). Pass `--env-file .env` plus `-e POSTGRES_USER=...` explicitly, or check:

```bash
docker inspect sp_prod_app --format '{{range .Config.Env}}{{println .}}{{end}}' | grep POSTGRES
```

### "Failed to parse: http://0.0.0.0:8000 #should match API_PORT above/proxy_query_stream"

`.env` has an inline comment on `API_URL=`. Move it to its own line:

```env
# Should match API_PORT above
API_URL=http://127.0.0.1:7001
```

### Password contains special characters

If `POSTGRES_PASSWORD` contains `@`, `/`, `#`, `%`, or spaces, `DATABASE_URL` needs URL-encoding. The app builds it correctly from individual vars (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_HOST`, `DB_PORT`), so just omit `DATABASE_URL` from the `docker run` and let the app construct it.

### pg_restore errors about existing objects

Normal when using `--clean --if-exists` against a fresh DB. Warnings like "object does not exist, skipping" are harmless. Real errors say "could not connect" or "out of memory".

### RAG responses cite dates outside the data window

The LLM is fabricating citations because retrieval returned thin context. Check `docker logs sp_prod_app | grep "Context packing"` — if it consistently shows `0–3 docs`, retrieval is broken (embeddings missing, vector index unbuilt). The prompt hardening in `services/chat/rag_service.py` (system prompt + early-exit on empty context) catches most cases but only after retrieval is functional.

---

## Quick Reference: Using production-deploy.sh

The `scripts/docker/production-deploy.sh` script wraps the manual `docker run` commands above with auto env loading, image detection, and health-check loops. It is being progressively updated to use only the setns-safe patterns (no `--rm`, no `docker exec`, no `docker rm`, no custom networks, host-TCP for DB ops).

```bash
cd /opt/softpower
set -a; source .env; set +a

# Full deployment
./scripts/docker/production-deploy.sh start       # Start DB + App
./scripts/docker/production-deploy.sh stop        # Stop all
./scripts/docker/production-deploy.sh restart     # docker stop && docker start (no rm)
./scripts/docker/production-deploy.sh migrate     # Run Alembic migrations
./scripts/docker/production-deploy.sh backup      # pg_dump over TCP
./scripts/docker/production-deploy.sh restore F   # pg_restore over TCP
./scripts/docker/production-deploy.sh status      # docker ps + curl /api/health
./scripts/docker/production-deploy.sh logs        # docker logs -f
./scripts/docker/production-deploy.sh psql "SQL"  # Native psql via TCP
```

If a `production-deploy.sh` subcommand hits an old `docker run --rm` or `docker exec` path that has not yet been ported, the fallback is the manual commands in this guide — they are the source of truth for what works.

---

## Appendix: Complete Operation Summary

| Step | What it does | Command pattern |
|------|-------------|-----------------|
| Export users | Dump users table before wipe | `pg_dump --table=users` over TCP from host |
| Remove volume | Wipe all database data | `docker volume rm softpower_production_prod_pgdata` |
| Start fresh DB | New PostgreSQL with empty data dir | `docker start sp_prod_db \|\| docker run -d --name sp_prod_db_fresh ...` |
| Enable extensions | pgvector + pg_trgm | `psql -c "CREATE EXTENSION..."` over TCP from host |
| Restore dump | Load full dataset | `pg_restore -h 127.0.0.1 ...` natively on host |
| Run migrations | Apply schema updates | Native `alembic upgrade head` or `docker run` (no `--rm`) |
| Clear stale users | Remove dump's user records | `psql -c "DELETE FROM users;"` from host |
| Restore users | Re-import preserved users | `psql -f users_backup.sql` from host |
| ANALYZE | Update query planner stats | `psql -c "ANALYZE;"` from host |
| Start Redis | Cache service | `docker start sp_prod_redis \|\| docker run -d ...` |
| Start app | FastAPI + React UI | `docker start sp_prod_app \|\| docker run -d ...` |
| Start LLM proxy | Host-side API relay | `uvicorn server.main:app --host 127.0.0.1 --port 7001` natively |
