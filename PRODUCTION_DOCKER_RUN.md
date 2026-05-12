# Production Deployment with `docker run` on Enterprise / Kiosk Hosts

This guide deploys SoftPower Analytics using only `docker run` / `docker start` / `docker stop`. It targets enterprise / kiosk hosts where the Docker daemon enforces strict namespace policies and several common operations are blocked.

---

## Enterprise daemon constraints (read first)

On Rocky 9 / RHEL enterprise hosts that run Docker inside a sandboxed container themselves (DinD or DooD with a hardened daemon), several Docker operations fail with `setns` / `permission denied` errors because they require entering an existing container's namespace. The table below maps which operations work on this kind of host:

| Operation | Triggers `setns`? | Works |
|---|---|---|
| `docker run --network host` (create) | No | ✅ |
| `docker start <existing>` | No | ✅ |
| Running container serving traffic | No | ✅ |
| `docker logs` / `docker inspect` / `docker ps` | No | ✅ |
| TCP connection from host to host-networked container | No | ✅ |
| `docker exec <container> ...` | Yes | ❌ |
| `docker cp host:path <container>:path` | Yes | ❌ |
| `docker rm <existing-container>` | Yes | ❌ |
| `docker run --rm` (teardown phase) | Yes | ❌ |
| `docker run --network <custom-bridge>` (bind-mount of `/proc/<pid>/ns/net`) | Yes | ❌ |

**Operating rules that follow from this:**

1. **Always use `--network host`.** Never create a custom bridge network. Containers share the host's network stack and reach each other at `127.0.0.1:<port>`.
2. **Never use `--rm`.** The teardown setns will fail and may leave the container in a half-dead state. Long-lived containers are fine; short-lived ones must be allowed to exit and then ignored or `docker stop`'d later.
3. **Never rely on `docker exec` or `docker cp`.** For database admin (psql, pg_dump, pg_restore, migrations) install the client tools on the host and connect to the host-networked container at `127.0.0.1:<port>` over TCP.
4. **Use `docker start || docker run` for idempotent launches.** `docker start` reuses an existing stopped container (no setns). The `docker run` fallback only fires when the container truly doesn't exist yet — and on first creation, setns isn't involved.
5. **If you need to "rebuild" a container, give it a new name** (`sp_app_v2`, `sp_app_v3`, ...). The old one sits stopped. You cannot remove it cleanly until/unless the daemon's policy ever changes.

---

## Prerequisites

On the enterprise host:

- Docker Engine installed and running.
- The `pgvector` and `softpower-analytics` images either pulled from a registry or `docker load`'d from `.tar` files.
- The repo cloned to a known path (e.g., `/opt/softpower/`).
- `.env` file configured (copy from `.env.example`, fill in real values).
- Postgres client tools (`psql`, `pg_dump`, `pg_restore`) installed on the host directly, **not** inside a container. Use conda, dnf, or pre-staged RPMs. Required because `docker exec` is unavailable.

Verify:

```bash
docker info >/dev/null && echo "docker OK"
docker images | grep -E "softpower|pgvector"
which psql pg_dump pg_restore
```

---

## Quick start

Once `.env` is filled in and images are loaded:

```bash
set -a; source .env; set +a
./scripts/docker/production-deploy.sh start
```

The script wraps all the `docker run` commands below. The rest of this guide documents the manual commands for when you need to run them individually (debugging, manual ordering, partial rebuilds).

---

## 1. Volume only (no network create)

```bash
docker volume create sp_db_data
```

Do **not** create a Docker bridge network. We use `--network host` everywhere.

---

## 2. Start the database container (`sp_db`)

Idempotent one-liner — starts an existing container if present, otherwise creates fresh:

```bash
docker start sp_db 2>/dev/null || docker run -d \
    --name sp_db \
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
    -e PGPORT=5432 \
    -v sp_db_data:/var/lib/postgresql/data \
    --shm-size=1g \
    mmorrisj/pgvector:0.8.1-pg17
```

Notes on the flags:

- `--network host` — port 5432 is exposed on the enclave host's loopback. Reach it as `127.0.0.1:5432` from anywhere on the host or from sibling containers also on `--network host`.
- `--cap-drop ALL` plus the specific caps Postgres needs for initdb (CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID). Defense in depth.
- **No `--rm`.** This is a long-lived service; let it run.
- Volume `sp_db_data` persists data. If you want to start from scratch, `docker volume rm sp_db_data` first (only when no container is using it).

### Wait for the database to be ready

`pg_isready` over TCP from the host — no sidecar container, no `docker exec`:

```bash
until PGPASSWORD="$POSTGRES_PASSWORD" pg_isready \
    -h 127.0.0.1 -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    sleep 2
done
echo "Database ready"
```

### Verify pgvector is loaded

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
    -c "\dx"
```

You should see `vector` and `pg_trgm` listed.

---

## 3. Start the application container (`sp_app`)

Same idempotent pattern. Drops privileges, loads everything from `.env`, points DB connections at host loopback (since the DB container is also on `--network host`):

```bash
docker start sp_app 2>/dev/null || docker run -d \
    --name sp_app \
    --network host \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --env-file .env \
    -e DOCKER_ENV=true \
    -e NODE_ENV=production \
    -e DB_HOST=127.0.0.1 \
    -e POSTGRES_HOST=127.0.0.1 \
    -e DB_PORT=5432 \
    -e POSTGRES_PORT=5432 \
    -e API_PORT=8000 \
    -e STREAMLIT_PORT=8501 \
    -e API_URL=http://127.0.0.1:7001 \
    -e DEV_AUTH_BYPASS=false \
    -e HF_HOME=/app/.cache/huggingface \
    -e SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/hub \
    -e TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken \
    -e TRANSFORMERS_OFFLINE=true \
    -e HF_HUB_OFFLINE=true \
    mmorrisj/softpower-analytics:latest
```

Important details:

- **`--env-file .env`** pulls every line in `.env` into the container. Avoid inline comments in `.env` — most loaders treat `KEY=value # comment` as `KEY=value # comment` (literal). Put comments on their own lines.
- **`-e API_URL=http://127.0.0.1:7001`** — only matters if you run the optional host-side LLM/S3 proxy on port 7001 (see §6). Otherwise the container's own `/proxy_query_stream` endpoint handles LLM calls. If you keep LLM creds inside the container and don't run the host proxy, point `API_URL` at `http://127.0.0.1:8000` instead (so HyDe and other `gai()` calls hit the container's own proxy endpoint).
- **`-e DEV_AUTH_BYPASS=false`** — real per-user enterprise gateway auth. Set to `true` only for early testing before the gateway integration is verified.
- **`-e DB_HOST=127.0.0.1`** — overrides any `DB_HOST=sp_db` left over from a prior bridge-network deployment. Host networking means the DB is on loopback.
- **No `--rm`.** Same reason as the database container.

### Wait for the API to be ready

```bash
until curl -sf http://127.0.0.1:8000/api/health >/dev/null; do sleep 2; done
echo "API ready"
```

### Verify auth and DB pool

```bash
docker logs --tail=50 sp_app | grep -iE 'pool|enterprise|started|listening'
# Should show: "Uvicorn running on http://0.0.0.0:8000"
# Should NOT show: "DEV_AUTH_BYPASS is ON" (that warning only prints when bypass is true)
```

---

## 4. Run Alembic migrations

The application container has the migrations code baked in. You can either:

**Option A — Migrations happen at app startup** (if your entrypoint runs them). Check logs:

```bash
docker logs sp_app 2>&1 | grep -iE 'alembic|migration|upgrade'
```

**Option B — Run migrations from the host using a `psql`-equivalent approach.** Since `docker exec` is blocked, you can't easily run `alembic upgrade head` inside the running container. Two workarounds:

```bash
# B1. Run migrations from the host using a host Python env that has the project deps installed:
cd /opt/softpower
set -a; source .env; set +a
DB_HOST=127.0.0.1 alembic upgrade head

# B2. Launch a SECOND, short-lived migration container with a different name (no --rm):
docker run --name sp_migrate_$(date +%s) --network host \
    --env-file .env \
    -e DB_HOST=127.0.0.1 -e POSTGRES_HOST=127.0.0.1 -e DB_PORT=5432 \
    mmorrisj/softpower-analytics:latest \
    alembic upgrade head
# The container exits when migrations complete. You can ignore the stopped container
# or `docker stop` it later. (Don't try docker rm — it'll fail with setns.)
```

---

## 5. Common operations — all over TCP from the host

### View logs

```bash
docker logs -f sp_app
docker logs -f sp_db
```

`docker logs` reads from the daemon's container log files, no setns involved.

### Connect with psql

```bash
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -p 5432 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

Hits the host-networked DB container directly. No sidecar.

### Backup the database

```bash
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h 127.0.0.1 -p 5432 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -F c \
    -f softpower-backup-$(date +%Y%m%d).dump
```

The dump file lands on the host filesystem. No `docker cp`, no sidecar.

### Restore the database

If the dump is one file:

```bash
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
    --verbose --no-owner --no-privileges --jobs=4 \
    -h 127.0.0.1 -p 5432 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    softpower-backup-20260101.dump 2>&1 | tee restore.log
```

If the dump is a chunked export (manifest + chunk files from `scripts/db_export.py`):

```bash
# 1. Verify chunk checksums
python scripts/db_import.py --input-dir ./chunks_dir --dry-run

# 2. Reassemble per manifest.json
python -c "
import json, pathlib
d = pathlib.Path('./chunks_dir')
m = json.loads((d/'manifest.json').read_text())
out = d/'reassembled.dump'
with open(out,'wb') as fo:
    for c in m['chunks']:
        fo.write((d/c['file']).read_bytes())
print('wrote', out, 'size', out.stat().st_size)
"

# 3. Create the target DB if needed
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres \
    -c "CREATE DATABASE \"$POSTGRES_DB\";"
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 4. Restore over TCP
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
    --verbose --no-owner --no-privileges --jobs=4 \
    -h 127.0.0.1 -p 5432 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    ./chunks_dir/reassembled.dump 2>&1 | tee restore.log
```

`--no-owner --no-privileges` strips role / grant statements from the dump and avoids "role X does not exist" errors on a fresh DB. `--jobs=4` parallelizes; adjust based on host cores.

**Do not use** `scripts/db_import.py`'s `--docker-container` mode on this daemon — it launches an ephemeral `pg_restore` container with `--rm` and `--network softpower_net`, both of which trigger the setns failures.

### Health check from Python

```bash
cd /opt/softpower
set -a; source .env; set +a
DB_HOST=127.0.0.1 python -c "
from shared.database.database import health_check, get_pool_status
print('DB:', 'OK' if health_check() else 'FAIL')
print('Pool:', get_pool_status())
"
```

### Stop and restart services

```bash
# Stop (keeps the container, data persists in the volume)
docker stop sp_app
docker stop sp_db

# Start again (no setns — reuses existing containers)
docker start sp_db
docker start sp_app

# Restart in one shot (same as stop + start)
docker restart sp_app
docker restart sp_db
```

### Update env vars on a running container

Docker doesn't let you mutate env vars on a running container — they're set at `docker run` time. To update:

```bash
# 1. Stop the current container (don't try to docker rm; setns blocks it)
docker stop sp_app

# 2. Edit .env on the host
nano .env

# 3. Launch a NEW container with a different name and the new env
docker run -d --name sp_app_v2 --network host --restart unless-stopped \
    --security-opt no-new-privileges:true --cap-drop ALL \
    --env-file .env \
    -e DOCKER_ENV=true -e DB_HOST=127.0.0.1 -e POSTGRES_HOST=127.0.0.1 \
    -e DB_PORT=5432 -e API_PORT=8000 \
    -e DEV_AUTH_BYPASS=false \
    -e API_URL=http://127.0.0.1:7001 \
    -e HF_HOME=/app/.cache/huggingface \
    -e SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/hub \
    -e TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken \
    -e TRANSFORMERS_OFFLINE=true -e HF_HUB_OFFLINE=true \
    mmorrisj/softpower-analytics:latest

# 4. Old sp_app sits stopped. Ignore it (it can't be cleanly removed; setns blocks docker rm).
docker ps -a --filter name=sp_app
```

The next time you bring the stack up, `docker start sp_app_v2` is your new entry point.

### Bind-mount a patched file without rebuilding the image

When you have a small code fix to deploy and don't want to rebuild and reship a multi-GB image, bind-mount the patched file at container start:

```bash
docker stop sp_app
docker run -d --name sp_app_v3 --network host --restart unless-stopped \
    --security-opt no-new-privileges:true --cap-drop ALL \
    --env-file .env \
    -e DOCKER_ENV=true -e DB_HOST=127.0.0.1 -e POSTGRES_HOST=127.0.0.1 \
    -e DB_PORT=5432 -e API_PORT=8000 \
    -e DEV_AUTH_BYPASS=false \
    -e API_URL=http://127.0.0.1:7001 \
    -v /opt/softpower/server/auth.py:/app/server/auth.py:ro \
    -v /opt/softpower/services/chat/rag_service.py:/app/services/chat/rag_service.py:ro \
    mmorrisj/softpower-analytics:latest
```

Use **absolute paths** for the host side of bind mounts. The mount overlays a single file; Python imports the patched version at startup.

---

## 6. Optional: host-side LLM/S3 proxy on port 7001

If your security model requires LLM credentials (`LITELLM_*`, `OPENAI_*`, `AZURE_OPENAI_*`, `AWS_*`) to stay outside the application container, run a second native uvicorn on the host serving the same FastAPI app on port 7001. The application container calls back to it via `API_URL=http://127.0.0.1:7001`.

```bash
cd /opt/softpower
conda activate softpower    # or whatever Python env has the deps installed
set -a; source .env; set +a

nohup uvicorn server.main:app --host 127.0.0.1 --port 7001 \
    > /var/log/softpower/proxy.log 2>&1 &
echo $! > /var/run/softpower-proxy.pid
```

Bind to `127.0.0.1` not `0.0.0.0` — the proxy should only be reachable from the host's loopback (which the container shares via `--network host`).

When you choose this setup, **blank the LITELLM/OPENAI env vars on the application container** so it doesn't have any way to call out directly:

```bash
docker run -d --name sp_app_v4 ... \
    -e LITELLM_URL= -e LITELLM_API_KEY= -e LITELLM_MODEL= \
    -e OPENAI_PROJ_API= -e OPENAI_API_KEY= \
    -e AZURE_OPENAI_ENDPOINT= -e AZURE_OPENAI_API_KEY= \
    mmorrisj/softpower-analytics:latest
```

---

## 7. Script reference

The `scripts/docker/production-deploy.sh` script wraps the above with automatic env loading, image detection, and health-check loops:

```bash
./scripts/docker/production-deploy.sh start       # Start DB + App
./scripts/docker/production-deploy.sh stop        # Stop all
./scripts/docker/production-deploy.sh restart     # Stop + Start (uses docker stop + start, no rm)
./scripts/docker/production-deploy.sh migrate     # Run Alembic migrations via a transient container
./scripts/docker/production-deploy.sh backup      # pg_dump over TCP from host
./scripts/docker/production-deploy.sh restore F   # pg_restore over TCP from host
./scripts/docker/production-deploy.sh status      # docker ps + curl /api/health
./scripts/docker/production-deploy.sh logs        # docker logs -f
```

The script never calls `docker exec` or `docker cp`. All DB admin operations go through the host's `psql`/`pg_dump`/`pg_restore` binaries connecting to `127.0.0.1:5432`.

---

## 8. Environment variables

Set these in `.env`, no inline comments:

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_USER` | — | DB owner — must match initdb-time value or the credential drift guard will fire |
| `POSTGRES_PASSWORD` | — | DB password |
| `POSTGRES_DB` | — | Target DB name |
| `DB_HOST` | `127.0.0.1` | Always loopback under `--network host` |
| `DB_PORT` | `5432` | |
| `API_PORT` | `8000` | FastAPI bind port |
| `STREAMLIT_PORT` | `8501` | Streamlit bind port |
| `API_URL` | `http://127.0.0.1:7001` if running host proxy, else `http://127.0.0.1:8000` | Used by `gai()` and the chat stream for the proxy endpoint |
| `DEV_AUTH_BYPASS` | `false` | `true` only for pre-gateway testing; bypass treats every request as a single hardcoded user |
| `LITELLM_URL` / `LITELLM_API_KEY` / `LITELLM_MODEL` | — | If LLM access is via an on-prem LiteLLM proxy. Set in `.env` so it propagates via `--env-file` |
| `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME` / `TIKTOKEN_CACHE_DIR` | paths under `/app/.cache` | Where the offline embedding model caches live inside the container |
| `TRANSFORMERS_OFFLINE` / `HF_HUB_OFFLINE` | `true` | Force HuggingFace to use cached models only, no network egress |

---

## 9. Network topology (host-networked)

```
┌─────────────────────────────────────────────────────────────┐
│  Enclave host network namespace                             │
│                                                             │
│  Containers using --network host (share the host's stack):  │
│    sp_db       → 127.0.0.1:5432   PostgreSQL + pgvector     │
│    sp_app      → 127.0.0.1:8000   FastAPI + React UI        │
│                  127.0.0.1:8501   Streamlit dashboard       │
│                                                             │
│  Native processes on the host (optional):                   │
│    uvicorn     → 127.0.0.1:7001   LLM/S3 proxy              │
│    psql/pg_*   → 127.0.0.1:5432   admin ops over TCP        │
│                                                             │
│  Inter-container reachability: every container sees every   │
│  other container as 127.0.0.1:<port> — no Docker DNS, no    │
│  bridge network, no /var/run/docker/netns/ bind mounts.     │
└─────────────────────────────────────────────────────────────┘
                 ↑
        Enterprise gateway URL → kiosk:8000 → enclave 127.0.0.1:8000
```

---

## 10. Troubleshooting

### `bind mount /proc/<pid>/ns/net -> /var/run/docker/netns/...: permission denied`

You're using a custom Docker network (or anything other than `host` / `none`). The daemon can't bind-mount netns paths. Use `--network host` only.

### `setns: permission denied` from `docker exec` / `docker cp` / `docker rm` / `docker run --rm`

The daemon blocks entering existing container namespaces. You can't fix this — replace the operation with a TCP-based equivalent (psql/pg_dump/pg_restore from the host), avoid `--rm` on ephemeral containers, and don't try to delete containers (start new ones under different names instead).

### Postgres "role appuser does not exist"

`POSTGRES_USER` is empty in the application container's environment, so libpq fell back to the container's OS user (`appuser`). Either pass `--env-file .env` plus `-e POSTGRES_USER=...` explicitly, or check `docker inspect sp_app --format '{{range .Config.Env}}{{println .}}{{end}}' | grep POSTGRES`.

### `Failed to parse: http://0.0.0.0:8000 #should match API_PORT above/proxy_query_stream`

`.env` has an inline comment on the `API_URL=` line. Move comments to their own line:

```env
# Should match API_PORT above
API_URL=http://127.0.0.1:8000
```

### RAG responses cite documents from outside the data window

The LLM is fabricating citations because retrieval returned thin context. Fix order:
1. Confirm retrieval works: trigger a Research query and grep the app logs for `Context packing: N/M docs` — if `N` is consistently `0–3`, retrieval is the bug.
2. Make sure embeddings are loaded for `langchain_pg_embedding`.
3. The current `services/chat/rag_service.py` system prompt explicitly forbids out-of-context citations; if you still see them, the prompt hardening may have been reverted.

### Container env doesn't include vars I set in `.env`

You started the container *before* the `.env` edit. Container env is frozen at `docker run` time. Either use the bind-mount workaround for files, or launch a new container with a new name (`sp_app_v2`, etc.).

### "Authentication required — please ensure you are accessing through the enterprise gateway"

Either (a) you're hitting the URL directly without going through the gateway, and the gateway-injected `x-kiosk-gateway-jwt` header isn't on the request, or (b) `DEV_AUTH_BYPASS` is false but the JWT decode in `server/auth.py` is failing. Check `docker logs sp_app | grep -i jwt` for the actual failure mode.

---

## Why every other Docker deployment guide for this project may steer you wrong

Other documentation files in this repo (`DOCKER_WORKFLOW.md`, `docker-compose.dev.yml`, the original `production-deploy.sh` before mid-2026 changes) were written for a permissive Docker daemon that supports `docker exec`, `docker cp`, custom bridge networks, and `--rm`. On the enterprise / kiosk hosts this guide targets, those patterns fail. This document supersedes them for enterprise deployments. If a step elsewhere mentions any of: `docker exec`, `docker cp`, `docker network create`, or `--rm`, **don't follow it on the enterprise host**.
