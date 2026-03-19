# Production Installation Guide

Complete guide for deploying SoftPower Analytics on production systems using Docker (no Docker Compose required).

---

## Architecture

The deployment uses **2 Docker containers**:

| Container | Image | Ports | Purpose |
|-----------|-------|-------|---------|
| `softpower_db` | `mmorrisj/pgvector:0.8.1-pg16` | 5432 | PostgreSQL 16 + pgvector |
| `softpower_app` | `mmorrisj/softpower-analytics:1.7.2` | 8000, 8501 | FastAPI + Streamlit (via supervisord) |

```
┌────────────────────────────────────────────────┐
│              Production Host                   │
│                                                │
│  ┌─────────────┐    ┌──────────────────────┐   │
│  │ softpower_db│    │  softpower_app       │   │
│  │ PostgreSQL  │◄───│  FastAPI  (port 8000)│   │
│  │ + pgvector  │    │  Streamlit (port 8501)│  │
│  │  port 5432  │    │                      │   │
│  └─────────────┘    │  + ML model (baked in)│  │
│                      └──────────────────────┘   │
│                                                │
│  Optional: Host-side LLM proxy (port 7001)     │
│  for routing LLM/S3 requests to external APIs  │
└────────────────────────────────────────────────┘
```

---

## Registry Images (Docker Hub)

Use this path when you have loaded Docker Hub images (`mmorrisj/softpower-analytics` and `mmorrisj/pgvector`) into the enterprise environment.

### Step 1: Verify Docker Installation

```bash
# Check Docker is installed
docker --version

# If not installed, install from internal mirrors:
sudo yum install docker -y

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $(whoami)

# Log out and back in, then verify
docker ps
```

### Step 2: Load Docker Images

If images were transferred as tar files:
```bash
docker load -i softpower-analytics-1.7.2.tar
docker load -i pgvector-0.8.1-pg16.tar
```

If images were pulled from an enterprise registry mirror:
```bash
docker pull registry.enterprise.local/mmorrisj/softpower-analytics:1.7.2
docker pull registry.enterprise.local/mmorrisj/pgvector:0.8.1-pg16

# Tag to expected names
docker tag registry.enterprise.local/mmorrisj/softpower-analytics:1.7.2 mmorrisj/softpower-analytics:1.7.2
docker tag registry.enterprise.local/mmorrisj/pgvector:0.8.1-pg16 mmorrisj/pgvector:0.8.1-pg16
```

Verify both images are loaded:
```bash
docker images | grep -E "softpower|pgvector"
# Expected:
#   mmorrisj/softpower-analytics   1.7.2    ...   ~2GB
#   mmorrisj/pgvector              0.8.1-pg16  ...   ~400MB
```

### Step 3: Configure Environment

Create a `.env` file in your working directory:
```bash
cat > .env << 'EOF'
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=softpower-db

# Registry image configuration
APP_IMAGE=mmorrisj/softpower-analytics:1.7.2
DB_IMAGE=mmorrisj/pgvector:0.8.1-pg16

# LLM proxy (set to 0 to disable)
LLM_PROXY_PORT=0

# API key for LLM features (optional)
CLAUDE_KEY=your_api_key
EOF
```

### Step 4: Start Services

```bash
./production-deploy.sh start
```

The script auto-detects the registry image and skips the setup/model checks. It starts:
- `softpower_db` — PostgreSQL + pgvector on port 5432
- `softpower_app` — FastAPI (8000) + Streamlit (8501) with ML model baked in

### Step 5: Initialize Database

Choose one:

**Option A: Fresh install (empty database)**
```bash
# Run Alembic migrations to create all tables
./production-deploy.sh migrate
```

**Option B: Restore from pg_dump file**

> **Do not** run migrations when restoring — the dump already contains the full schema.

```bash
./production-deploy.sh restore /path/to/your-backup.dump
```

If the dump was created with `pg_dump -Fc` (custom format), this uses `pg_restore --clean --if-exists` to drop and recreate objects.

If the dump is a plain SQL file (`.sql`), restore it directly:
```bash
docker exec -i softpower_db psql -U matthew50 -d softpower-db < /path/to/backup.sql
```

### Step 6: Verify Deployment

```bash
# Check status
./production-deploy.sh status

# Health check
curl http://localhost:8000/api/health

# Access in browser
#   Web App:    http://<hostname>:8000
#   Streamlit:  http://<hostname>:8501
#   API Docs:   http://<hostname>:8000/docs
```

### Step 7: Verify pgvector Extension (after restore)

After restoring a dump, verify the pgvector extension is active:
```bash
docker exec softpower_db psql -U matthew50 -d softpower-db -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

If not present (unlikely — the pgvector image auto-creates it), enable it:
```bash
docker exec softpower_db psql -U matthew50 -d softpower-db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

---

## Management Commands

```bash
./production-deploy.sh load [dir]       # Load Docker images from tar files
./production-deploy.sh start            # Start all services
./production-deploy.sh stop             # Stop all services (preserves data)
./production-deploy.sh restart          # Stop then start all services
./production-deploy.sh migrate          # Run database migrations (Alembic)
./production-deploy.sh status           # Show container status
./production-deploy.sh backup [file]    # Create database backup
./production-deploy.sh restore <file>   # Restore database from backup
./production-deploy.sh logs [container] # Tail container logs (default: app)
```

---

## LLM Proxy Configuration

The container does **not** call LLM APIs directly — it lacks the certificate authorizations needed to reach external services. Instead, LLM requests are proxied through a **host-side FastAPI** on port 7001.

```
Container (port 8000) --> Host FastAPI (port 7001) --> LLM API (OpenAI/Azure)
```

**Start the proxy:**
```bash
# Lightweight proxy (recommended)
pip install fastapi uvicorn openai boto3 python-dotenv python-multipart
python scripts/llm_proxy.py

# Or full server
source venv/bin/activate
uvicorn server.main:app --host 0.0.0.0 --port 7001
```

**Disable the proxy** (container calls APIs directly):
```bash
# In .env:
LLM_PROXY_PORT=0
```

---

## Auto-Start on Boot

```bash
sudo vi /etc/systemd/system/softpower.service
```

```ini
[Unit]
Description=SoftPower Analytics
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/softpower
ExecStart=/opt/softpower/production-deploy.sh start
ExecStop=/opt/softpower/production-deploy.sh stop

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable softpower
```

---

## Troubleshooting

### Container Won't Start

```bash
docker logs softpower_app
docker logs softpower_db

# Port already in use?
sudo netstat -tlnp | grep -E "8000|8501|5432"
```

### Database Connection Errors

```bash
# Is the database running?
docker exec softpower_db pg_isready -U matthew50 -d softpower-db

# Test SQL
docker exec softpower_db psql -U matthew50 -d softpower-db -c "SELECT 1;"

# Check network
docker network inspect softpower_net
```

### ML Packages Not Working

ML packages are baked into the registry image. Verify:
```bash
docker run --rm mmorrisj/softpower-analytics:1.7.2 python -c "import torch; print(torch.__version__)"
```

### Shared Memory Errors (PostgreSQL)

The deploy script uses `--shm-size=1g`. If still failing:
```bash
sysctl kernel.shmmax
# Increase if needed:
sudo sysctl -w kernel.shmmax=2147483648
```

### Networking Issues

```bash
# Recreate network
docker network rm softpower_net
docker network create softpower_net
./production-deploy.sh restart
```

---

## Updating the Application

```bash
# 1. Load new image version
docker load -i softpower-analytics-X.Y.Z.tar

# 2. Update .env
APP_IMAGE=mmorrisj/softpower-analytics:X.Y.Z

# 3. Restart
./production-deploy.sh stop
./production-deploy.sh start
./production-deploy.sh migrate    # Apply any new migrations
```

---

## Verification Checklist

- [ ] Docker installed and running
- [ ] Both Docker images loaded (`mmorrisj/softpower-analytics:1.7.2`, `mmorrisj/pgvector:0.8.1-pg16`)
- [ ] `.env` configured with credentials and `APP_IMAGE`/`DB_IMAGE`
- [ ] Database container running (port 5432)
- [ ] App container running (ports 8000, 8501)
- [ ] Database restored from dump or migrations applied
- [ ] Health check passes: `curl http://localhost:8000/api/health`
- [ ] Web app accessible in browser
- [ ] Streamlit accessible in browser
- [ ] Firewall allows ports 8000, 8501
- [ ] (Optional) LLM proxy running on host port 7001

---

## Support Information

**Container Names**: `softpower_db`, `softpower_app`
**Network**: `softpower_net`
**Volume**: `softpower_pgdata` (database persistence)
**Ports**: 8000 (Web App + API), 8501 (Streamlit), 5432 (PostgreSQL)
