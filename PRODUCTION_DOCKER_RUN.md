# Production Deployment with `docker run` (No `docker exec`)

This guide covers deploying SoftPower Analytics using only `docker run` / `docker stop` / `docker rm` commands. It does not require `docker-compose` or `docker exec`, which may be restricted in enterprise environments.

All database admin operations (migrations, backup, restore) use ephemeral sidecar containers that connect over the Docker network instead of exec-ing into running containers.

---

## Prerequisites

- Docker Engine installed and running
- Images available (either pulled from registry or loaded from tar files)
- `.env` file configured (copy from `.env.example`)

## Quick Start (Registry Image)

```bash
# Pull images
docker pull mmorrisj/pgvector:0.8.1-pg16
docker pull mmorrisj/softpower-analytics:latest

# Run the automated script (no docker exec used)
./scripts/docker/production-deploy.sh start
./scripts/docker/production-deploy.sh migrate
```

The script handles everything below automatically. The rest of this guide documents the manual `docker run` commands if you need to run them individually.

---

## 1. Create Network and Volume

```bash
docker network create softpower_net
docker volume create softpower_pgdata
```

## 2. Start PostgreSQL + pgvector

```bash
docker run -d \
    --name softpower_db \
    --network softpower_net \
    --restart unless-stopped \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -v softpower_pgdata:/var/lib/postgresql/data \
    -p 5432:5432 \
    --shm-size=1g \
    mmorrisj/pgvector:0.8.1-pg16
```

### Wait for database readiness

Instead of `docker exec ... pg_isready`, spin up an ephemeral container on the same network:

```bash
docker run --rm --network softpower_net \
    mmorrisj/pgvector:0.8.1-pg16 \
    pg_isready -h softpower_db -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

Repeat until exit code 0 (or wrap in a loop with `sleep 2`).

## 3. Start Application (FastAPI + Streamlit)

```bash
docker run -d \
    --name softpower_app \
    --network softpower_net \
    --restart unless-stopped \
    --add-host=host.docker.internal:host-gateway \
    -e DOCKER_ENV=true \
    -e NODE_ENV=production \
    -e DB_HOST=softpower_db \
    -e DB_PORT=5432 \
    -e POSTGRES_HOST=softpower_db \
    -e POSTGRES_PORT=5432 \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB}" \
    -e DB_POOL_SIZE=10 \
    -e DB_MAX_OVERFLOW=20 \
    -e DB_POOL_TIMEOUT=30 \
    -e DB_POOL_RECYCLE=3600 \
    -e API_URL="http://host.docker.internal:7001" \
    -e TRANSFORMERS_OFFLINE=1 \
    -e HF_HUB_OFFLINE=1 \
    -e HF_HOME="/app/.cache/huggingface" \
    -e SENTENCE_TRANSFORMERS_HOME="/app/.cache/huggingface/hub" \
    -e CLAUDE_KEY="$CLAUDE_KEY" \
    -p 8000:8000 \
    -p 8501:8501 \
    mmorrisj/softpower-analytics:latest
```

### Wait for API readiness

```bash
curl -sf http://localhost:8000/api/health
```

Repeat until HTTP 200.

## 4. Run Database Migrations

Ephemeral container running `alembic upgrade head`:

```bash
docker run --rm \
    --network softpower_net \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db \
    -e DB_PORT=5432 \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB}" \
    mmorrisj/softpower-analytics:latest \
    alembic upgrade head
```

---

## Common Operations (All exec-free)

### Backup Database

```bash
docker run --rm --network softpower_net \
    mmorrisj/pgvector:0.8.1-pg16 \
    pg_dump -h softpower_db \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -F c > softpower-backup-$(date +%Y%m%d).dump
```

### Restore Database

```bash
docker run --rm -i --network softpower_net \
    mmorrisj/pgvector:0.8.1-pg16 \
    pg_restore -h softpower_db \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --clean --if-exists < softpower-backup-20250101.dump
```

### Run a One-Off Python Command

```bash
docker run --rm \
    --network softpower_net \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db \
    -e DB_PORT=5432 \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    mmorrisj/softpower-analytics:latest \
    python -c "from shared.database.database import health_check; print('OK' if health_check() else 'FAIL')"
```

### View Logs

```bash
docker logs -f softpower_app     # Application (FastAPI + Streamlit)
docker logs -f softpower_db      # PostgreSQL
```

### Stop Services

```bash
docker stop softpower_app && docker rm softpower_app
docker stop softpower_db  && docker rm softpower_db
```

Data is preserved in the `softpower_pgdata` volume.

### Restart Services

```bash
docker stop softpower_app && docker rm softpower_app
docker stop softpower_db  && docker rm softpower_db
sleep 3
# Re-run steps 2 and 3 above
```

---

## Script Reference

The `production-deploy.sh` script wraps all of the above with automatic env loading, image detection, and health-check loops. **It no longer uses `docker exec` anywhere.**

```bash
./scripts/docker/production-deploy.sh start       # Start DB + App
./scripts/docker/production-deploy.sh stop        # Stop all
./scripts/docker/production-deploy.sh restart     # Stop + Start
./scripts/docker/production-deploy.sh migrate     # Run Alembic migrations
./scripts/docker/production-deploy.sh backup      # Dump database
./scripts/docker/production-deploy.sh restore F   # Restore from dump file F
./scripts/docker/production-deploy.sh status      # Show container status
./scripts/docker/production-deploy.sh logs        # Tail app logs
```

---

## Environment Variables

Set these in `.env` or export them before running commands:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `matthew50` | Database user |
| `POSTGRES_PASSWORD` | `softpower` | Database password |
| `POSTGRES_DB` | `softpower-db` | Database name |
| `DB_PORT` | `5432` | Host port for PostgreSQL |
| `API_PORT` | `8000` | Host port for FastAPI |
| `STREAMLIT_PORT` | `8501` | Host port for Streamlit |
| `LLM_PROXY_PORT` | `7001` | Host-side LLM/S3 proxy port (0 to disable) |
| `DEPLOY_MODE` | `production` | `production` = HF offline, `standard` = HF online |
| `CLAUDE_KEY` | — | OpenAI API key for LLM features |

---

## Network Topology

```
┌─────────────────────────────────────────────────┐
│              Docker Network: softpower_net        │
│                                                   │
│  softpower_db (:5432)    ← PostgreSQL + pgvector  │
│       ↑                                           │
│  softpower_app (:8000, :8501)                     │
│       │  FastAPI (React UI + API)                 │
│       │  Streamlit (Analytics Dashboard)          │
│       │                                           │
│  Ephemeral containers (docker run --rm)           │
│       │  migrations, backup, restore, health      │
│       │  Connect via --network softpower_net      │
└───────┼───────────────────────────────────────────┘
        │
   host.docker.internal:7001
        └── Host-side LLM/S3 proxy (optional)
```

All sidecar containers use `--rm` so they clean up after themselves. No `docker exec` is ever needed.
