# Docker Workflow Reference

Quick reference for building, running, and maintaining the SoftPower Analytics Docker container.

> ## ⚠ Enterprise / kiosk hosts — read this first
>
> This document assumes a permissive Docker daemon (laptop, dev VM, generic Linux server) where `docker exec`, `docker cp`, custom bridge networks, and `--rm` all work normally.
>
> **On enterprise / kiosk hosts (Rocky 9 + hardened daemon), most patterns in this file will fail with `setns: permission denied` errors.** Specifically these are blocked: `docker exec`, `docker cp`, `docker rm` of existing containers, `docker run --rm` (teardown), and `--network` with anything other than `host`.
>
> **For enterprise deployments use [`PRODUCTION_DOCKER_RUN.md`](./PRODUCTION_DOCKER_RUN.md) instead** — it documents the host-TCP / `--network host` / non-`--rm` patterns that actually work in that environment.
>
> Quick translation table for commands in this doc:
>
> | Doc says | Enterprise host uses |
> |---|---|
> | `docker exec <container> psql ...` | `psql -h 127.0.0.1 -p 5432 ...` (host-installed psql) |
> | `docker exec <container> printenv X` | `docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}' \| grep X` |
> | `docker exec -it <container> bash` | Not available — debug via `docker logs` and host-side reproductions |
> | `docker exec <container> curl ...` | `curl ...` from the host (containers are on `--network host`) |
> | `docker run --rm ...` | `docker run` without `--rm`; ignore the stopped container afterward |
> | `docker network create ...` | Don't create networks; use `--network host` |

## Architecture

The production image is a **single container** running two services via supervisord:
- **FastAPI** (port 8000 inside container) — React UI + API + Chat/RAG
- **Streamlit** (port 8501 inside container) — Analytics dashboard

The database (PostgreSQL + pgvector) runs separately — either as its own container or on the host.

**LLM Proxy Relay:** The container does **not** call LLM APIs (OpenAI, Azure, etc.) directly — it lacks the certificate authorizations needed to reach external services. Instead, LLM requests are proxied through a **host-side FastAPI instance** running on port 7001, which has the proper certs and network access. The flow:

```
Container (port 8000)  -->  Host FastAPI (port 7001)  -->  LLM API (OpenAI/Azure/LiteLLM)
    via API_URL                has certs/auth              external service
```

This means the host-side FastAPI must be running for any LLM features (report generation, chat/RAG, validation) to work.

## 1. Get the Image

### Development (internet-connected machine) — build from source

```bash
sudo docker build -f docker/registry.Dockerfile -t softpower-analytics:latest .
```

**What happens during the build:**
- Stage 1: `node:20-slim` installs npm deps and runs `npm run build` (compiles React to static files)
- Stage 2: `python:3.13-slim` installs system packages and all pip dependencies (including ML packages)
- The built React files are copied from Stage 1 into Stage 2
- Node.js is **not** present in the final image — React runs as pre-built static files

**Build times:**
- First build: ~10-15 minutes (downloads all dependencies)
- Subsequent builds: ~1-2 minutes (Docker caches unchanged layers)

**If the build fails with TypeScript errors:**
Fix the source files in `client/src/`, then re-run the build command. Only the changed layers rebuild.

## 2. Run the Container

```bash
sudo docker run -d \
  --name softpower_analytics \
  -p 8005:8000 \
  -p 8503:8501 \
  --env-file .env \
  -e DOCKER_ENV=true \
  -e DATABASE_URL=postgresql+psycopg2://matthew50:softpower@host.docker.internal:5432/softpower-db \
  -e API_URL=http://host.docker.internal:7001 \
  --add-host=host.docker.internal:host-gateway \
  softpower-analytics:latest
```

**Port mapping format: `-p HOST:CONTAINER`**
- `-p 8005:8000` → access FastAPI/React at `http://localhost:8005`
- `-p 8503:8501` → access Streamlit at `http://localhost:8503`

**Flags explained:**
| Flag | Purpose |
|------|---------|
| `-d` | Run in background (detached) |
| `--name softpower_analytics` | Name the container for easy reference |
| `-p HOST:CONTAINER` | Map host port to container port |
| `--env-file .env` | Load environment variables from .env |
| `-e DOCKER_ENV=true` | Tell the app it's running in Docker |
| `-e DATABASE_URL=...` | Database connection string |
| `-e API_URL=...` | LLM/S3 proxy relay — base URL for host proxy on port 7001 (code appends `/proxy_query`, `/s3/*`, etc.) |
| `--add-host=host.docker.internal:host-gateway` | Linux-only: lets container reach host network |

**IMPORTANT:** The `-e API_URL` flag **overrides** the value from `.env`. Your `.env` likely has `API_URL=http://localhost:7001` — correct on the host but wrong inside the container where `localhost` means the container itself. The `-e` override rewrites it to `host.docker.internal` so the container can reach the host.

**Prerequisites:**
- Host-side LLM proxy must be running on port 7001 for LLM features.

  **Option A: Lightweight proxy (recommended — only needs `fastapi`, `uvicorn`, `openai`, `boto3`)**
  ```bash
  pip install fastapi uvicorn openai boto3 python-dotenv python-multipart
  python scripts/llm_proxy.py
  ```

  **Option B: Full server (needs full `requirements.txt`)**
  ```bash
  source venv/bin/activate
  uvicorn server.main:app --host 0.0.0.0 --port 7001
  ```

**If port 8005 is already in use**, pick another host port (e.g., `-p 9000:8000`).

## 3. Check Container Status

```bash
# Is the container running?
sudo docker ps

# Check both services (FastAPI + Streamlit)
sudo docker logs softpower_analytics 2>&1 | tail -30

# Check FastAPI specifically
sudo docker logs softpower_analytics 2>&1 | grep -E "fastapi|uvicorn|ERROR|FATAL"

# Check Streamlit specifically
sudo docker logs softpower_analytics 2>&1 | grep -i streamlit

# Follow logs in real time
sudo docker logs -f softpower_analytics

# Health check
curl http://localhost:8005/api/health

# Verify proxy env var is correct (should show host.docker.internal, NOT localhost)
sudo docker exec softpower_analytics printenv API_URL
```

## 4. Stop the Container

```bash
sudo docker stop softpower_analytics
```

## 5. Remove a Container

You must stop a container before removing it (or use `-f` to force).

```bash
# Stop then remove
sudo docker stop softpower_analytics && sudo docker rm softpower_analytics

# Force remove (even if running)
sudo docker rm -f softpower_analytics
```

## 6. Restart After Code Changes

After editing source files, rebuild and restart:

```bash
sudo docker rm -f softpower_analytics && \
sudo docker build -f docker/registry.Dockerfile -t softpower-analytics:latest . && \
sudo docker run -d \
  --name softpower_analytics \
  -p 8005:8000 \
  -p 8503:8501 \
  --env-file .env \
  -e DOCKER_ENV=true \
  -e DATABASE_URL=postgresql+psycopg2://matthew50:softpower@host.docker.internal:5432/softpower-db \
  -e API_URL=http://host.docker.internal:7001 \
  --add-host=host.docker.internal:host-gateway \
  softpower-analytics:latest
```

## 7. Common Errors and Fixes

### "port is already allocated"

Something else is using that host port.

```bash
# Find what's using port 8005
sudo lsof -i :8005

# Pick a different host port
sudo docker run -d ... -p 9000:8000 -p 9501:8501 ...
```

### "container name is already in use"

A container with that name already exists (running or stopped).

```bash
# See all containers (including stopped)
sudo docker ps -a

# Remove the old one
sudo docker rm -f softpower_analytics
```

### FastAPI crashes / port 8005 not connecting (but Streamlit works)

Check the logs for Python import or startup errors:

```bash
sudo docker logs softpower_analytics 2>&1 | grep -E "ERROR|FATAL|Traceback|NameError|ImportError" | tail -20
```

Fix the Python source, rebuild, and restart (see section 6).

### LLM calls fail / report generation returns no response

The container proxies LLM requests through the host. Check:

1. **Host-side FastAPI running on port 7001?**
   ```bash
   curl http://localhost:7001/docs
   ```
   If not running, start the lightweight proxy:
   ```bash
   pip install fastapi uvicorn openai boto3 python-dotenv python-multipart
   python scripts/llm_proxy.py
   ```

2. **API_URL set correctly?** Must be `http://host.docker.internal:7001`.
   Check from inside the container:
   ```bash
   sudo docker exec softpower_analytics printenv API_URL
   ```

3. **Container can reach host?** Test connectivity:
   ```bash
   sudo docker exec softpower_analytics curl -s http://host.docker.internal:7001/docs | head -5
   ```

### "no such container"

The container doesn't exist. Check the name:

```bash
sudo docker ps -a --format "table {{.Names}}\t{{.Status}}"
```

## 8. Useful Docker Commands

```bash
# List all images
sudo docker images

# List running containers
sudo docker ps

# List ALL containers (including stopped/failed)
sudo docker ps -a

# Shell into a running container
sudo docker exec -it softpower_analytics bash

# Check disk usage
sudo docker system df

# Clean up dangling images (safe, frees disk space)
sudo docker image prune

# Nuclear option: remove all stopped containers and unused images
sudo docker system prune
```

## 9. Registry / Production Deployment

The **registry** path is the recommended production deployment. It produces a fully self-contained ~2GB image with ML packages and HuggingFace model baked in — pull-and-run, no manual setup.

### Build and push to Docker Hub

```bash
# Build + push the registry image (default mode)
REGISTRY=docker.io/yourusername ./scripts/docker/push-to-registry.sh

# This builds docker/registry.Dockerfile with:
#   --pull --sbom=true --provenance=mode=max --push
# Produces: softpower-app (FastAPI + Streamlit + React + ML, self-contained)
# Also rebuilds: pgvector (PostgreSQL + pgvector extension)
```

### Deploy with docker-compose.production.yml

```bash
# First time — run migrations:
docker compose -f docker-compose.production.yml --profile migrate up

# Start the stack:
docker compose -f docker-compose.production.yml up -d
```

This pulls pre-built images from Docker Hub (no local builds needed). See `docs/DOCKERHUB_README.md` for the full Docker Hub README with environment variables and restore instructions.

### Security hardening (production compose)

The production compose file includes:
- `security_opt: no-new-privileges:true`
- `cap_drop: ALL`
- Health checks on database
- Non-root user (`appuser`)

## 10. Export for Production Deployment

### Option A: Registry push (if registry is accessible from both networks)

```bash
REGISTRY=docker.io/yourusername ./scripts/docker/push-to-registry.sh --production
```

### Option B: Save as tar file (for physical/S3 transfer)

```bash
# Save the app image
sudo docker save softpower-analytics:latest -o softpower-analytics.tar

# Save the database image
sudo docker save pgvector/pgvector:0.8.1-pg16 -o pgvector-pg16.tar

# Transfer to production system, then load
sudo docker load -i softpower-analytics.tar
sudo docker load -i pgvector-pg16.tar
```

## 11. File Reference

| File | Purpose |
|------|---------|
| **Dockerfiles** | |
| `docker/registry.Dockerfile` | Production image — self-contained with ML packages + HuggingFace model (~2GB) |
| `docker/api.Dockerfile` | Dev API service (multi-stage: Node build + Python FastAPI) |
| `docker/dashboard.Dockerfile` | Dev Streamlit dashboard service |
| `docker/pgvector.Dockerfile` | Custom PostgreSQL 16 + pgvector (compiled from source) |
| `docker/supervisord.conf` | Process manager config (runs FastAPI + Streamlit in consolidated images) |
| **Compose files** | |
| `docker-compose.dev.yml` | Development stack (separate containers: API, Dashboard, DB, Redis) |
| `docker-compose.production.yml` | Production stack (consolidated app image from Docker Hub) |
| **Requirements** | |
| `requirements-production.txt` | Lightweight Python deps baked into production Docker image |
| `requirements-production-heavy.txt` | Heavy ML deps installed from wheels on production target |
| **Scripts** | |
| `scripts/docker/push-to-registry.sh` | Build + push images to Docker Hub (registry or production mode) |
| `scripts/docker/production-deploy.sh` | Deployment management on production target system |
| `scripts/llm_proxy.py` | Lightweight LLM+S3 proxy (only needs fastapi+uvicorn+openai+boto3) |
| **Documentation** | |
| `docs/DOCKERHUB_README.md` | Docker Hub container registry README |
| `.dockerignore` | Build context exclusions |
| `.env` | Environment variables (DB creds, API keys, etc.) |

