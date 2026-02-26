# Production Installation Guide (CentOS 7)

Complete guide for deploying SoftPower Analytics on production CentOS 7 systems using only Docker (no Docker Compose required).

---

## Architecture

The deployment uses **2 Docker containers**:

| Container | Image | Ports | Purpose |
|-----------|-------|-------|---------|
| `softpower_db` | `mmorrisj/pgvector:0.8.1-pg16` | 5432 | PostgreSQL 16 + pgvector |
| `softpower_app` | `mmorrisj/softpower-analytics:1.5.5` | 8000, 8501 | FastAPI + Streamlit (via supervisord) |

```
┌────────────────────────────────────────────────┐
│           Production CentOS 7 Host             │
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

## Two Deployment Paths

| | Path A: Registry Images | Path B: Slim Images |
|---|---|---|
| **Source** | Docker Hub (`mmorrisj/softpower-analytics`) | `production-build.sh` package |
| **ML packages** | Baked into image | Installed from wheels via `setup` |
| **HuggingFace model** | Baked into image | External `hf_model/` directory (volume mount) |
| **Image size** | ~2 GB (ready to run) | ~700 MB slim + ~1.5 GB wheels |
| **Steps** | Load → configure → start → restore | Load → setup → configure → start → restore |
| **Best for** | Enterprise with pre-approved Docker Hub images | Air-gapped with no registry access |

---

## Path A: Registry Images (Recommended for Enterprise)

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
docker load -i softpower-analytics-1.5.5.tar
docker load -i pgvector-0.8.1-pg16.tar
```

If images were pulled from an enterprise registry mirror:
```bash
docker pull registry.enterprise.local/mmorrisj/softpower-analytics:1.5.5
docker pull registry.enterprise.local/mmorrisj/pgvector:0.8.1-pg16

# Tag to expected names
docker tag registry.enterprise.local/mmorrisj/softpower-analytics:1.5.5 mmorrisj/softpower-analytics:1.5.5
docker tag registry.enterprise.local/mmorrisj/pgvector:0.8.1-pg16 mmorrisj/pgvector:0.8.1-pg16
```

Verify both images are loaded:
```bash
docker images | grep -E "softpower|pgvector"
# Expected:
#   mmorrisj/softpower-analytics   1.5.5    ...   ~2GB
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
APP_IMAGE=mmorrisj/softpower-analytics:1.5.5
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

## Path B: Slim Images (Air-Gapped via production-build.sh)

Use this path when deploying from a `production-build.sh` transfer package.

### Quick Build (Internet-Connected Machine)

```bash
cd SP_Streamlit

# Standard output: tar.gz archive
./scripts/docker/production-build.sh

# Transfer-safe output: directory of .txt files (for systems that block binaries)
./scripts/docker/production-build.sh --pack
```

### Package Contents

```
softpower-production-YYYYMMDD/
├── images/
│   ├── pgvector-pg16.tar            # ~400 MB  PostgreSQL + pgvector
│   └── softpower-app-production.tar # ~700 MB  FastAPI + Streamlit (slim)
├── wheels/                          # ~1.5 GB  ML package wheels
├── hf_model/                        # ~90 MB   sentence-transformers model
├── requirements-production-heavy.txt
├── production-deploy.sh
├── .env.example
├── softpower-backup.dump            # Database backup (if available)
└── README.txt
```

### Installation Steps

```bash
# 1. Extract package
cd /opt
tar xzf softpower-production-YYYYMMDD.tar.gz
cd softpower-production-YYYYMMDD

# If using --pack mode:
python3 unpack-production.py --apply

# 2. Load Docker images
./production-deploy.sh load ./images

# 3. Install ML packages from wheels (one-time)
./production-deploy.sh setup

# 4. Configure environment
cp .env.example .env
vi .env

# 5. Start services
./production-deploy.sh start

# 6. Initialize database
./production-deploy.sh migrate
# Or restore from backup:
./production-deploy.sh restore softpower-backup.dump
```

---

## Management Commands

```bash
./production-deploy.sh load [dir]       # Load Docker images from tar files
./production-deploy.sh setup            # Install ML wheels into app image (slim only, one-time)
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

## CentOS 7 Specific Considerations

### SELinux

```bash
# Check status
getenforce

# Set to permissive if blocking Docker
sudo setenforce 0

# Or add proper SELinux contexts
sudo chcon -Rt svirt_sandbox_file_t /opt/softpower-production-*
```

### Firewall

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp    # Web app
sudo firewall-cmd --permanent --add-port=8501/tcp    # Streamlit
sudo firewall-cmd --reload
```

### Storage

CentOS 7 may have limited `/var` space:

```bash
# Check disk space
df -h

# Move Docker data directory if needed
sudo systemctl stop docker
sudo mkdir -p /opt/docker
sudo vi /etc/docker/daemon.json
# Add: {"data-root": "/opt/docker"}
sudo rsync -aP /var/lib/docker/ /opt/docker/
sudo systemctl start docker
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

For **registry images**, ML packages are baked in. Verify:
```bash
docker run --rm mmorrisj/softpower-analytics:1.5.5 python -c "import torch; print(torch.__version__)"
```

For **slim images**, re-run setup:
```bash
./production-deploy.sh setup
docker run --rm softpower-app-production:latest python -c "import torch; print(torch.__version__)"
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

### Registry images (from Docker Hub)

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

### Slim images (from production-build.sh)

```bash
# 1. Transfer new package to production system
# 2. On production system:
./production-deploy.sh stop
./production-deploy.sh load ./images      # Load updated slim image
./production-deploy.sh setup              # Re-install ML packages
./production-deploy.sh start
./production-deploy.sh migrate            # Apply any new migrations
```

---

## Verification Checklist

### Registry Images (Path A)
- [ ] Docker installed and running
- [ ] Both Docker images loaded (`mmorrisj/softpower-analytics:1.5.5`, `mmorrisj/pgvector:0.8.1-pg16`)
- [ ] `.env` configured with credentials and `APP_IMAGE`/`DB_IMAGE`
- [ ] Database container running (port 5432)
- [ ] App container running (ports 8000, 8501)
- [ ] Database restored from dump or migrations applied
- [ ] Health check passes: `curl http://localhost:8000/api/health`
- [ ] Web app accessible in browser
- [ ] Streamlit accessible in browser
- [ ] Firewall allows ports 8000, 8501
- [ ] (Optional) LLM proxy running on host port 7001

### Slim Images (Path B)
- [ ] Docker installed and running
- [ ] Both Docker images loaded (`pgvector`, `softpower-app-production`)
- [ ] ML packages installed via `setup` command
- [ ] HuggingFace model directory present (`hf_model/`)
- [ ] `.env` configured with credentials
- [ ] Database container running (port 5432)
- [ ] App container running (ports 8000, 8501)
- [ ] Database migrations applied
- [ ] Health check passes: `curl http://localhost:8000/api/health`
- [ ] Web app accessible in browser
- [ ] Streamlit accessible in browser
- [ ] Firewall allows ports 8000, 8501
- [ ] (Optional) LLM proxy running on host port 7001
- [ ] (Optional) Database backup restored

---

## Support Information

**Container Names**: `softpower_db`, `softpower_app`
**Network**: `softpower_net`
**Volume**: `softpower_pgdata` (database persistence)
**Ports**: 8000 (Web App + API), 8501 (Streamlit), 5432 (PostgreSQL)
