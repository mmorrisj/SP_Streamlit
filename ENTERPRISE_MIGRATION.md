# Enterprise CentOS Migration Guide

Full data app migration: wipe and rebuild the database from a dump file while preserving user accounts. All operations use `docker run` (ephemeral containers) — **no `docker exec` allowed**.

---

## Prerequisites

**On the enterprise CentOS system you need:**
- Docker installed and running (`sudo systemctl start docker`)
- The cloned/ported repo at a known path (e.g., `/opt/softpower/`)
- The database dump file (e.g., `softpower-full.dump`) transferred to the system
- The Docker images either pulled from registry or loaded from `.tar` files

---

## Phase 0: Verify Docker and Load Images

```bash
# Verify Docker is running
sudo docker info

# If images are in .tar files (air-gapped transfer):
sudo docker load -i softpower-analytics.tar
sudo docker load -i pgvector-pg16.tar

# If pulling from a registry:
sudo docker pull mmorrisj/softpower-analytics:1.7.2
sudo docker pull mmorrisj/pgvector:0.8.1-pg16

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

### 1.2 Edit `.env` — Key Variables to Update

Open `.env` in your editor and set these critical values:

```bash
# ==========================================
# DATABASE (required)
# ==========================================
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password
POSTGRES_DB=softpower-db
DB_HOST=0.0.0.0
DB_PORT=5432

# ==========================================
# LLM CONFIGURATION (required for AI features)
# ==========================================
# OPTION A: LiteLLM (enterprise endpoint — MOST LIKELY for enterprise)
#   Set these to point to your enterprise LiteLLM proxy
LITELLM_URL=https://your-enterprise-litellm-endpoint/v1
LITELLM_API_KEY=your-litellm-api-key
LITELLM_MODEL=gpt-4o-mini           # or whatever model your LiteLLM exposes

# OPTION B: Azure OpenAI (if your enterprise uses Azure)
# ENV=production
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_API_KEY=your-azure-key
# AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

# OPTION C: Direct OpenAI (unlikely in enterprise)
# CLAUDE_KEY=sk-...
# OPENAI_PROJ_API=sk-...

# ==========================================
# LLM PROXY RELAY (required — container cannot call LLM APIs directly)
# ==========================================
# Port for the host-side LLM proxy that the container routes through
LLM_PROXY_PORT=7001

# ==========================================
# AWS S3 (if using S3 for document ingestion)
# ==========================================
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
S3_BUCKET=your-bucket-name
S3_REGION=us-east-1

# ==========================================
# JWT / AUTH (important for user sessions)
# ==========================================
# MUST be at least 32 characters. Change this from the default!
JWT_SECRET=your-secure-random-string-at-least-32-characters-long
JWT_EXPIRATION_HOURS=24

# ==========================================
# DEPLOYMENT MODE
# ==========================================
DEPLOY_MODE=production              # Enables offline HuggingFace mode
DOCKER_ENV=true

# ==========================================
# PORTS
# ==========================================
API_PORT=8000                       # FastAPI + React UI
STREAMLIT_PORT=8501                 # Streamlit analytics dashboard

# ==========================================
# REDIS (optional — swap image for enterprise-hardened version)
# ==========================================
# REDIS_IMAGE=dhi/redis:7           # Uncomment for enterprise Redis image
```

### 1.3 Environment Variable Reference

| Variable | Purpose | Required |
|----------|---------|----------|
| `POSTGRES_USER` | Database username | Yes |
| `POSTGRES_PASSWORD` | Database password | Yes |
| `POSTGRES_DB` | Database name | Yes |
| `LITELLM_URL` | Enterprise LLM endpoint base URL | Yes (for AI) |
| `LITELLM_API_KEY` | API key for LiteLLM proxy | Yes (for AI) |
| `LITELLM_MODEL` | Model name exposed by LiteLLM | Yes (for AI) |
| `LLM_PROXY_PORT` | Host port for LLM proxy relay | Yes (default: 7001) |
| `JWT_SECRET` | Secret for signing auth tokens (min 32 chars) | Yes |
| `AWS_ACCESS_KEY_ID` | AWS credentials for S3 | If using S3 |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials for S3 | If using S3 |
| `REDIS_IMAGE` | Enterprise Redis image override | No |
| `APP_IMAGE` | Override app image name | No |
| `DB_IMAGE` | Override DB image name | No |

---

## Phase 2: Stop Existing Services (if running)

```bash
# Check what's currently running
sudo docker ps -a --filter "name=sp_prod"

# Stop and remove all existing containers
sudo docker stop sp_prod_app sp_prod_redis sp_prod_db 2>/dev/null
sudo docker rm sp_prod_app sp_prod_redis sp_prod_db 2>/dev/null
```

---

## Phase 3: Export Users from Existing Database (BEFORE wiping)

If there's an existing database with users you want to preserve, export them first.

### 3.1 Check if the old database is still accessible

```bash
# Start ONLY the database container (using the old volume)
sudo docker run -d \
    --name sp_prod_db \
    --network softpower_net \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -v softpower_production_prod_pgdata:/var/lib/postgresql/data \
    -p 5432:5432 \
    --shm-size=1g \
    mmorrisj/pgvector:0.8.1-pg16
```

(If the network doesn't exist yet, create it first: `sudo docker network create softpower_net`)

### 3.2 Wait for database to be ready

```bash
# Poll until ready (ephemeral container, no docker exec)
for i in $(seq 1 30); do
    if sudo docker run --rm --network softpower_net \
        mmorrisj/pgvector:0.8.1-pg16 \
        pg_isready -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" 2>/dev/null; then
        echo "Database is ready"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 2
done
```

### 3.3 Export the users table to a SQL file

```bash
# Export users table as plain SQL INSERT statements
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    pg_dump -h sp_prod_db \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --table=users \
    --data-only \
    --column-inserts \
    --no-owner \
    --no-privileges > users_backup.sql

# Verify the export
cat users_backup.sql | head -20
echo "---"
echo "User count: $(grep -c 'INSERT INTO' users_backup.sql)"
```

### 3.4 Stop the database

```bash
sudo docker stop sp_prod_db
sudo docker rm sp_prod_db
```

---

## Phase 4: Wipe and Rebuild the Database

### 4.1 Remove the old database volume

```bash
# THIS DESTROYS ALL DATA — make sure you have the dump file and users_backup.sql
sudo docker volume rm softpower_production_prod_pgdata 2>/dev/null

# Recreate the volume (fresh)
sudo docker volume create softpower_production_prod_pgdata
```

### 4.2 Start a fresh PostgreSQL container

```bash
# Source .env variables
export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)

sudo docker run -d \
    --name sp_prod_db \
    --network softpower_net \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --cap-add SETGID --cap-add SETUID \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -v softpower_production_prod_pgdata:/var/lib/postgresql/data \
    -p "${DB_PORT:-5432}:5432" \
    --shm-size=1g \
    mmorrisj/pgvector:0.8.1-pg16
```

### 4.3 Wait for PostgreSQL to initialize

```bash
for i in $(seq 1 30); do
    if sudo docker run --rm --network softpower_net \
        mmorrisj/pgvector:0.8.1-pg16 \
        pg_isready -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" 2>/dev/null; then
        echo "PostgreSQL is ready"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 2
done
```

### 4.4 Enable required PostgreSQL extensions

```bash
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "CREATE EXTENSION IF NOT EXISTS vector;" \
    -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
    -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');"
```

### 4.5 Restore the dump file

```bash
# Restore from the dump file (replace softpower-full.dump with your actual filename)
sudo docker run --rm -i --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    pg_restore -h sp_prod_db \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --clean --if-exists \
    --no-owner --no-privileges < softpower-full.dump

# Note: pg_restore may return non-zero on warnings — this is normal
```

### 4.6 Run Alembic migrations (apply any schema changes since the dump was created)

```bash
sudo docker run --rm \
    --network softpower_net \
    -e DOCKER_ENV=true \
    -e DB_HOST=sp_prod_db \
    -e DB_PORT=5432 \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@sp_prod_db:5432/${POSTGRES_DB}" \
    mmorrisj/softpower-analytics:1.7.2 \
    alembic upgrade head
```

### 4.7 Verify the schema

```bash
# Check table count
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT relname AS table_name, reltuples::bigint AS approx_rows
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r' AND n.nspname = 'public'
        ORDER BY reltuples DESC
        LIMIT 30;"
```

---

## Phase 5: Restore Users

### 5.1 Clear imported users (the dump may contain stale/different user records)

```bash
# Delete all users that came from the dump
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "DELETE FROM users;"
```

### 5.2 Restore the preserved users

```bash
# Re-import the users you exported in Phase 3
sudo docker run --rm -i --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" < users_backup.sql
```

### 5.3 Verify users are restored

```bash
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT username, role, display_name, is_active, created_at FROM users ORDER BY created_at;"
```

### 5.4 (If no prior users exist) Create the initial admin user

If this is a first deployment or you don't have users to restore, create one via the app:

```bash
# Start a temporary app container to create the default admin
sudo docker run --rm -it \
    --network softpower_net \
    -e DOCKER_ENV=true \
    -e DB_HOST=sp_prod_db \
    -e DB_PORT=5432 \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@sp_prod_db:5432/${POSTGRES_DB}" \
    mmorrisj/softpower-analytics:1.7.2 \
    python -c "
from shared.database.database import get_session
from shared.models.models import User, UserRole
import bcrypt, uuid

with get_session() as session:
    existing = session.query(User).filter_by(username='admin').first()
    if existing:
        print('Admin user already exists')
    else:
        pw_hash = bcrypt.hashpw('changeme'.encode(), bcrypt.gensalt()).decode()
        admin = User(
            id=uuid.uuid4(),
            username='admin',
            password_hash=pw_hash,
            role=UserRole.ADMIN,
            display_name='Administrator',
            is_active=True,
            force_password_change=True
        )
        session.add(admin)
        session.commit()
        print('Admin user created (username: admin, password: changeme)')
        print('** User will be forced to change password on first login **')
"
```

---

## Phase 6: Run ANALYZE (Optimize Query Performance)

After a full restore, update PostgreSQL statistics:

```bash
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "ANALYZE VERBOSE;" 2>&1 | tail -5
```

---

## Phase 7: Start the Full Application Stack

### 7.1 Start Redis

```bash
sudo docker run -d \
    --name sp_prod_redis \
    --network softpower_net \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add SETGID --cap-add SETUID \
    ${REDIS_IMAGE:-redis:7-alpine}

# Verify Redis is running
for i in $(seq 1 10); do
    if sudo docker run --rm --network softpower_net \
        ${REDIS_IMAGE:-redis:7-alpine} redis-cli -h sp_prod_redis ping 2>/dev/null | grep -q PONG; then
        echo "Redis is ready"
        break
    fi
    sleep 1
done
```

### 7.2 Start the Application Container

```bash
sudo docker run -d \
    --name sp_prod_app \
    --network softpower_net \
    --restart unless-stopped \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --add-host=host.docker.internal:host-gateway \
    -e DOCKER_ENV=true \
    -e NODE_ENV=production \
    -e DB_HOST=sp_prod_db \
    -e DB_PORT=5432 \
    -e POSTGRES_HOST=sp_prod_db \
    -e POSTGRES_PORT=5432 \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@sp_prod_db:5432/${POSTGRES_DB}" \
    -e DB_POOL_SIZE="${DB_POOL_SIZE:-10}" \
    -e DB_MAX_OVERFLOW="${DB_MAX_OVERFLOW:-20}" \
    -e DB_POOL_TIMEOUT="${DB_POOL_TIMEOUT:-30}" \
    -e DB_POOL_RECYCLE="${DB_POOL_RECYCLE:-3600}" \
    -e API_URL="http://host.docker.internal:${LLM_PROXY_PORT:-7001}" \
    -e S3_PROXY_URL="http://host.docker.internal:${LLM_PROXY_PORT:-7001}" \
    -e USE_S3_API_CLIENT=true \
    -e TRANSFORMERS_OFFLINE=1 \
    -e HF_HUB_OFFLINE=1 \
    -e HF_HOME="/app/.cache/huggingface" \
    -e SENTENCE_TRANSFORMERS_HOME="/app/.cache/huggingface/hub" \
    -e TIKTOKEN_CACHE_DIR="/app/.cache/tiktoken" \
    -e REDIS_URL="redis://sp_prod_redis:6379/0" \
    -e CLAUDE_KEY="${CLAUDE_KEY:-}" \
    -e OPENAI_PROJ_API="${OPENAI_PROJ_API:-}" \
    -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}" \
    -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}" \
    -e JWT_SECRET="${JWT_SECRET:-softpower-jwt-secret-change-in-production-min32chars}" \
    -e JWT_EXPIRATION_HOURS="${JWT_EXPIRATION_HOURS:-24}" \
    -p "${API_PORT:-8000}:8000" \
    -p "${STREAMLIT_PORT:-8501}:8501" \
    mmorrisj/softpower-analytics:1.7.2
```

### 7.3 Wait for the app to become healthy

```bash
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:${API_PORT:-8000}/api/health > /dev/null 2>&1; then
        echo "Application is healthy!"
        break
    fi
    echo "Waiting for API... ($i/30)"
    sleep 2
done
```

---

## Phase 8: Start the Host-Side LLM Proxy

The container **cannot** call LLM APIs directly (no certificate authorization). It routes LLM/S3 requests through a host-side proxy on port 7001.

### 8.1 Install proxy dependencies (lightweight — no full requirements.txt needed)

```bash
pip install fastapi uvicorn openai boto3 python-dotenv python-multipart
```

### 8.2 Start the proxy

```bash
cd /opt/softpower
python scripts/llm_proxy.py &

# Verify it's running
curl http://localhost:7001/api/health
# Should return: {"status":"healthy","service":"proxy"}
```

The proxy reads `.env` automatically and routes based on what's configured:
1. **LiteLLM** (if `LITELLM_URL` + `LITELLM_API_KEY` are set) — **enterprise default**
2. **Azure OpenAI** (if `ENV=production` + Azure vars are set)
3. **OpenAI** (fallback, if `OPENAI_PROJ_API` or `CLAUDE_KEY` is set)

### 8.3 (Optional) Run the proxy as a systemd service

```bash
sudo tee /etc/systemd/system/softpower-proxy.service > /dev/null << 'EOF'
[Unit]
Description=SoftPower LLM Proxy
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/softpower
ExecStart=/usr/bin/python3 scripts/llm_proxy.py
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

Expected output:
```
NAMES           STATUS                    PORTS
sp_prod_app     Up X minutes              0.0.0.0:8000->8000/tcp, 0.0.0.0:8501->8501/tcp
sp_prod_redis   Up X minutes
sp_prod_db      Up X minutes              0.0.0.0:5432->5432/tcp
```

### 9.2 Check API health

```bash
curl http://127.0.0.1:${API_PORT:-8000}/api/health
```

### 9.3 Check LLM proxy connectivity

```bash
curl http://127.0.0.1:7001/api/health
```

### 9.4 Verify document count in database

```bash
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT count(*) AS document_count FROM documents;"
```

### 9.5 Verify user login works

```bash
curl -X POST http://127.0.0.1:${API_PORT:-8000}/api/login \
    -H "Content-Type: application/json" \
    -d '{"username": "admin", "password": "changeme"}'
```

### 9.6 Access the web interfaces

- **React Web App:** `http://<server-ip>:8000`
- **API Docs:** `http://<server-ip>:8000/docs`
- **Streamlit Dashboard:** `http://<server-ip>:8501`

---

## Troubleshooting

### Container logs

```bash
# Application logs (FastAPI + Streamlit)
sudo docker logs -f sp_prod_app

# Database logs
sudo docker logs -f sp_prod_db

# Filter for errors only
sudo docker logs sp_prod_app 2>&1 | grep -E "ERROR|FATAL|Traceback"
```

### LLM calls fail

1. Check the host-side proxy is running: `curl http://localhost:7001/api/health`
2. Check `API_URL` inside the container:
   ```bash
   sudo docker run --rm --network softpower_net \
       --add-host=host.docker.internal:host-gateway \
       mmorrisj/softpower-analytics:1.7.2 \
       python -c "import os; print('API_URL =', os.getenv('API_URL', 'NOT SET'))"
   ```
3. Verify the LiteLLM endpoint is reachable from the host:
   ```bash
   curl -H "Authorization: Bearer $LITELLM_API_KEY" $LITELLM_URL/models
   ```

### Database connection issues

```bash
# Test connectivity from an ephemeral container
sudo docker run --rm --network softpower_net \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    mmorrisj/pgvector:0.8.1-pg16 \
    psql -h sp_prod_db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT 1 AS connected;"
```

### Password contains special characters

If `POSTGRES_PASSWORD` contains `@`, `/`, `#`, `%`, or spaces, the `DATABASE_URL` connection string needs URL-encoding. The app handles this automatically when using individual vars (`POSTGRES_USER`, etc.), so you can omit `DATABASE_URL` entirely and let the app build it:

```bash
# In the docker run command, remove the -e DATABASE_URL=... line
# and ensure these are set:
-e POSTGRES_USER="$POSTGRES_USER" \
-e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
-e POSTGRES_DB="$POSTGRES_DB" \
-e DB_HOST=sp_prod_db \
-e DB_PORT=5432 \
```

### pg_restore errors about existing objects

This is normal — `--clean --if-exists` tries to drop objects before creating them. Warnings about objects not existing are harmless. The restore still succeeds.

---

## Quick Reference: Using production-deploy.sh

The repo includes a script that wraps all the above `docker run` commands. If you prefer to use it:

```bash
cd /opt/softpower
export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)

# Full rebuild with dump restore + user preservation:
./scripts/docker/production-deploy.sh stop
./scripts/docker/production-deploy.sh rebuild-db softpower-full.dump
./scripts/docker/production-deploy.sh start

# Individual operations:
./scripts/docker/production-deploy.sh status
./scripts/docker/production-deploy.sh migrate
./scripts/docker/production-deploy.sh backup
./scripts/docker/production-deploy.sh restore softpower-full.dump
./scripts/docker/production-deploy.sh psql "SELECT count(*) FROM documents;"
```

Note: `rebuild-db` does NOT preserve users automatically — you still need to export/re-import them using the manual steps in Phases 3 and 5.

---

## Appendix: Complete Operation Summary

| Step | What it does | Command pattern |
|------|-------------|----------------|
| Export users | Dump users table before wipe | `docker run --rm ... pg_dump --table=users ...` |
| Remove volume | Wipe all database data | `docker volume rm softpower_production_prod_pgdata` |
| Start fresh DB | New PostgreSQL with empty data dir | `docker run -d --name sp_prod_db ...` |
| Enable extensions | pgvector + pg_trgm | `docker run --rm ... psql -c "CREATE EXTENSION..."` |
| Restore dump | Load full dataset | `docker run --rm -i ... pg_restore ... < dump.file` |
| Run migrations | Apply schema updates | `docker run --rm ... alembic upgrade head` |
| Clear stale users | Remove dump's user records | `docker run --rm ... psql -c "DELETE FROM users;"` |
| Restore users | Re-import preserved users | `docker run --rm -i ... psql < users_backup.sql` |
| ANALYZE | Update query planner stats | `docker run --rm ... psql -c "ANALYZE;"` |
| Start Redis | Cache service | `docker run -d --name sp_prod_redis ...` |
| Start app | FastAPI + Streamlit | `docker run -d --name sp_prod_app ...` |
| Start LLM proxy | Host-side API relay | `python scripts/llm_proxy.py` |
