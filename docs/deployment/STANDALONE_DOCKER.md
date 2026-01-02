# Standalone Docker Deployment (No Docker Compose)

Complete guide for deploying with pure Docker commands (no Docker Compose required).

---

## Overview

This deployment method is for systems that have **Docker installed but not Docker Compose**. Each service runs as a separate container managed by individual shell scripts.

### Why Use Standalone Docker?

- ✅ Works on systems without Docker Compose
- ✅ Older Docker versions
- ✅ Corporate environments with Docker-only access
- ✅ Learning tool (see exact `docker run` commands)
- ✅ Fine-grained control over each service

---

## Quick Start

### One-Command Deployment

```bash
# Linux/macOS
./docker/run-all.sh

# Windows
.\docker\run-all.ps1
```

This will:
1. Build all Docker images
2. Create network and volumes
3. Start PostgreSQL + Redis
4. Run database migrations
5. Start web app (React + FastAPI)
6. Start Streamlit dashboard
7. Start pipeline worker

---

## Step-by-Step Deployment

### Step 1: Build All Images

```bash
# Linux/macOS
./docker/build-all.sh

# Windows
.\docker\build-all.ps1
```

**What it does:**
- Creates Docker network: `softpower_net`
- Creates volumes: `postgres_data`, `redis_data`, `pgadmin_data`
- Builds 3 images:
  - `softpower-api:latest` (React + FastAPI)
  - `softpower-dashboard:latest` (Streamlit)
  - `softpower-pipeline:latest` (Data processing)

### Step 2: Start Database Services

```bash
# Linux/macOS
./docker/run-database.sh

# Windows (create PowerShell version)
.\docker\run-database.ps1
```

**What it does:**
- Starts PostgreSQL with pgvector extension
- Starts Redis cache
- Exposes ports: 5432 (PostgreSQL), 6379 (Redis)

### Step 3: Run Migrations

```bash
# Run migrations (one-time)
docker run --rm \
    --network softpower_net \
    -e DB_HOST=softpower_db \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=softpower \
    -e POSTGRES_DB=softpower-db \
    -e DATABASE_URL=postgresql+psycopg2://matthew50:softpower@softpower_db:5432/softpower-db \
    -v "$(pwd)/shared:/app/shared" \
    -v "$(pwd)/alembic:/app/alembic" \
    -v "$(pwd)/alembic.ini:/app/alembic.ini" \
    softpower-api:latest \
    alembic upgrade head
```

### Step 4: Start Web Application

```bash
# Linux/macOS
./docker/run-webapp.sh

# Windows (included in run-all.ps1)
```

**What it does:**
- Starts React + FastAPI container
- Connects to database
- Exposes port 8000
- Serves web app at http://localhost:8000

### Step 5: Start Streamlit Dashboard

```bash
# Linux/macOS
./docker/run-streamlit.sh
```

**What it does:**
- Starts Streamlit container
- Connects to database and API
- Exposes port 8501
- Dashboard at http://localhost:8501

### Step 6: Start Pipeline Worker

```bash
# Linux/macOS
./docker/run-pipeline.sh
```

**What it does:**
- Starts pipeline processing container
- Keeps running for exec commands
- Supports GPU (optional)

---

## Individual Service Scripts

### Database Only

```bash
./docker/run-database.sh
```

Use this if you only need the database.

### Web App Only

```bash
./docker/run-webapp.sh
```

Requires database to be running first.

### Streamlit Only

```bash
./docker/run-streamlit.sh
```

Requires database and web app running.

### Pipeline Only

```bash
./docker/run-pipeline.sh
```

Requires database running.

---

## Managing Services

### View Running Containers

```bash
docker ps
```

Expected output:
```
CONTAINER ID   IMAGE                     STATUS    PORTS                    NAMES
xxx            softpower-pipeline        Up        -                        softpower_pipeline
xxx            softpower-dashboard       Up        0.0.0.0:8501->8501/tcp   softpower_dashboard
xxx            softpower-api             Up        0.0.0.0:8000->8000/tcp   softpower_api
xxx            redis:7-alpine            Up        0.0.0.0:6379->6379/tcp   softpower_redis
xxx            ankane/pgvector           Up        0.0.0.0:5432->5432/tcp   softpower_db
```

### View Logs

```bash
# All logs for a service
docker logs softpower_api
docker logs softpower_db
docker logs softpower_pipeline

# Follow logs (real-time)
docker logs -f softpower_api

# Last 100 lines
docker logs --tail=100 softpower_api
```

### Restart a Service

```bash
docker restart softpower_api
docker restart softpower_db
```

### Stop a Service

```bash
docker stop softpower_api
docker stop softpower_pipeline
```

### Remove a Service

```bash
# Stop and remove
docker stop softpower_api
docker rm softpower_api

# Force remove (if stuck)
docker rm -f softpower_api
```

### Stop All Services

```bash
# Linux/macOS
./docker/stop-all.sh

# Windows
.\docker\stop-all.ps1
```

---

## Running Pipeline Tasks

All pipeline scripts run inside the `softpower_pipeline` container:

### Document Ingestion

```bash
# Ingest from S3
docker exec softpower_pipeline \
  python services/pipeline/ingestion/dsr.py

# Check status
docker exec softpower_pipeline \
  python services/pipeline/ingestion/dsr.py --status
```

### AI Analysis

```bash
docker exec softpower_pipeline \
  python services/pipeline/analysis/atom_extraction.py
```

### Generate Embeddings

```bash
# Embed all missing documents
docker exec softpower_pipeline \
  python services/pipeline/embeddings/embed_missing_documents.py --yes

# Check status
docker exec softpower_pipeline \
  python services/pipeline/embeddings/embed_missing_documents.py --status
```

### Event Processing

```bash
# Stage 1A: Cluster daily events
docker exec softpower_pipeline \
  python services/pipeline/events/batch_cluster_events.py \
  --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 1B: LLM validate
docker exec softpower_pipeline \
  python services/pipeline/events/llm_deconflict_clusters.py \
  --country China --start-date 2024-08-01 --end-date 2024-08-31
```

### Interactive Shell

```bash
# Bash shell inside pipeline container
docker exec -it softpower_pipeline bash

# Then run commands directly
python services/pipeline/ingestion/dsr.py
```

---

## Manual Docker Commands

If you want to start services manually without scripts:

### Network

```bash
docker network create softpower_net
```

### Volumes

```bash
docker volume create postgres_data
docker volume create redis_data
```

### PostgreSQL

```bash
docker run -d \
    --name softpower_db \
    --network softpower_net \
    --restart unless-stopped \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=softpower \
    -e POSTGRES_DB=softpower-db \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -v postgres_data:/var/lib/postgresql/data \
    -p 5432:5432 \
    --shm-size=2gb \
    ankane/pgvector:latest
```

### Redis

```bash
docker run -d \
    --name softpower_redis \
    --network softpower_net \
    --restart unless-stopped \
    -v redis_data:/data \
    -p 6379:6379 \
    redis:7-alpine \
    redis-server --appendonly yes --maxmemory 1gb
```

### Web App (React + FastAPI)

```bash
docker run -d \
    --name softpower_api \
    --network softpower_net \
    --restart unless-stopped \
    -e DOCKER_ENV=true \
    -e NODE_ENV=production \
    -e DB_HOST=softpower_db \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=softpower \
    -e POSTGRES_DB=softpower-db \
    -e DATABASE_URL=postgresql+psycopg2://matthew50:softpower@softpower_db:5432/softpower-db \
    -e REDIS_URL=redis://softpower_redis:6379 \
    -v "$(pwd)/shared/config/config.yaml:/app/shared/config/config.yaml:ro" \
    -v "$(pwd)/_data:/app/_data" \
    -p 8000:8000 \
    softpower-api:latest
```

### Streamlit Dashboard

```bash
docker run -d \
    --name softpower_dashboard \
    --network softpower_net \
    --restart unless-stopped \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db \
    -e DATABASE_URL=postgresql+psycopg2://matthew50:softpower@softpower_db:5432/softpower-db \
    -v "$(pwd)/services/dashboard:/app/services/dashboard:ro" \
    -v "$(pwd)/shared:/app/shared:ro" \
    -p 8501:8501 \
    softpower-dashboard:latest
```

### Pipeline Worker

```bash
docker run -d \
    --name softpower_pipeline \
    --network softpower_net \
    --restart unless-stopped \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db \
    -e DATABASE_URL=postgresql+psycopg2://matthew50:softpower@softpower_db:5432/softpower-db \
    -v "$(pwd)/services/pipeline:/app/services/pipeline" \
    -v "$(pwd)/shared:/app/shared" \
    -v "$(pwd)/_data:/app/_data" \
    softpower-pipeline:latest \
    tail -f /dev/null
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs softpower_api

# Inspect container
docker inspect softpower_api

# Try starting in foreground (see errors immediately)
docker run --rm -it --network softpower_net softpower-api:latest
```

### Database Connection Errors

```bash
# Verify database is running
docker ps | grep softpower_db

# Check database logs
docker logs softpower_db

# Test connection from another container
docker run --rm --network softpower_net postgres:15 \
  psql -h softpower_db -U matthew50 -d softpower-db -c "SELECT 1"
```

### Network Issues

```bash
# List networks
docker network ls

# Inspect network
docker network inspect softpower_net

# Recreate network
docker network rm softpower_net
docker network create softpower_net
```

### Port Already in Use

```bash
# Find what's using the port
# Linux/macOS
lsof -i :8000

# Windows
netstat -ano | findstr :8000

# Use different port
docker run -p 8080:8000 ...  # Map host 8080 to container 8000
```

### Remove Everything and Start Fresh

```bash
# Stop and remove all containers
./docker/stop-all.sh

# Remove volumes (WARNING: deletes all data)
docker volume rm postgres_data redis_data pgadmin_data

# Remove network
docker network rm softpower_net

# Remove images
docker rmi softpower-api softpower-dashboard softpower-pipeline

# Start fresh
./docker/run-all.sh
```

---

## Comparison: Standalone Docker vs Docker Compose

| Feature | Standalone Docker | Docker Compose |
|---------|-------------------|----------------|
| **Setup** | Manual scripts | Single YAML file |
| **Commands** | Individual `docker run` | `docker-compose up` |
| **Dependencies** | Docker only | Docker + Compose plugin |
| **Flexibility** | High (full control) | Medium (YAML limits) |
| **Complexity** | Higher | Lower |
| **Debugging** | Easier (see all flags) | Harder (abstracted) |
| **Production** | ✅ Works | ✅ Works |

---

## See Also

- [docker-compose.full.yml](../../docker-compose.full.yml) - Docker Compose equivalent
- [FULL_STACK.md](FULL_STACK.md) - Full stack Docker Compose guide
- [DEPLOYMENT_OPTIONS.md](../../DEPLOYMENT_OPTIONS.md) - All deployment options
