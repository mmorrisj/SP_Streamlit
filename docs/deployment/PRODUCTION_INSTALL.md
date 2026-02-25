# Production Installation Guide (CentOS 7)

Complete guide for deploying SoftPower Analytics on production CentOS 7 systems using only Docker (no Docker Compose required).

---

## Architecture

The deployment uses **2 Docker containers**:

| Container | Image | Ports | Purpose |
|-----------|-------|-------|---------|
| `softpower_db` | `pgvector/pgvector:0.8.1-pg16` | 5432 | PostgreSQL 16 + pgvector |
| `softpower_app` | `softpower-app-production:latest` | 8000, 8501 | FastAPI + Streamlit (via supervisord) |

The app container is built as a **slim image** (~700 MB) with heavyweight ML packages (torch, sentence-transformers) installed on the target from pre-downloaded wheel files.

```
┌────────────────────────────────────────────────┐
│           Production CentOS 7 Host             │
│                                                │
│  ┌─────────────┐    ┌──────────────────────┐   │
│  │ softpower_db│    │  softpower_app       │   │
│  │ PostgreSQL  │◄───│  FastAPI  (port 8000)│   │
│  │ + pgvector  │    │  Streamlit (port 8501)│  │
│  │  port 5432  │    │                      │   │
│  └─────────────┘    │  + HuggingFace model │   │
│                      │    (volume mount)    │   │
│                      └──────────────────────┘   │
│                                                │
│  Optional: Host-side LLM proxy (port 7001)     │
│  for routing LLM/S3 requests to external APIs  │
└────────────────────────────────────────────────┘
```

---

## Part 1: Build Transfer Package (Internet-Connected Machine)

Everything is automated via `production-build.sh`. It produces a self-contained package containing Docker image tars, ML wheel files, a HuggingFace model, and a deployment script.

### Quick Build

```bash
cd SP_Streamlit

# Standard output: tar.gz archive
./scripts/docker/production-build.sh

# Transfer-safe output: directory of .txt files (for systems that block binaries)
./scripts/docker/production-build.sh --pack
```

### What the Build Script Does (8 steps)

1. **Build slim Docker image** — `production.Dockerfile` installs only lightweight Python packages
2. **Download ML wheels** — `pip download` inside the slim image for platform-compatible `.whl` files (torch CPU, sentence-transformers, langchain-huggingface)
3. **Download HuggingFace model** — sentence-transformers/all-MiniLM-L6-v2 for offline embedding
4. **Export Docker images** — `docker save` to tar files
5. **Database backup** — if a local `softpower_db` container is running
6. **Copy deployment files** — deploy script, .env template, requirements
7. **Create documentation** — README.txt, INSTALL_CHECKLIST.txt
8. **Package** — tar.gz (standard) or base64-encoded .txt directory (`--pack`)

### Package Contents

```
softpower-production-YYYYMMDD/
├── images/
│   ├── pgvector-pg16.tar            # ~400 MB  PostgreSQL + pgvector
│   └── softpower-app-production.tar     # ~700 MB  FastAPI + Streamlit (slim)
├── wheels/                          # ~1.5 GB  ML package wheels
│   ├── torch-2.5.1-cp311-*.whl
│   ├── sentence_transformers-3.3.1-*.whl
│   ├── langchain_huggingface-0.1.2-*.whl
│   └── ... (transitive dependencies)
├── hf_model/                        # ~90 MB   sentence-transformers model
├── requirements-production-heavy.txt    # Package list for wheel install
├── production-deploy.sh                 # Deployment management script
├── .env.example                     # Environment variable template
├── softpower-backup.dump            # Database backup (if available)
├── README.txt                       # Quick start instructions
├── INSTALL_CHECKLIST.txt            # Step-by-step checklist
└── debug/                           # Alembic migrations (troubleshooting)
```

### Transfer to Production System

```bash
# Option 1: SCP via bastion/jump host
scp softpower-production-YYYYMMDD.tar.gz user@bastion:/approved-transfer/

# Option 2: Internal file share
cp softpower-production-YYYYMMDD.tar.gz /mnt/secure-transfer/

# Option 3: Organization's secure file transfer application
# Upload via web portal or CLI tool
```

---

## Part 2: Installation on Production CentOS 7

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

### Step 2: Extract Package

```bash
cd /opt
tar xzf softpower-production-YYYYMMDD.tar.gz
cd softpower-production-YYYYMMDD
```

If using `--pack` mode (base64-encoded .txt files):
```bash
cd softpower-production-YYYYMMDD
python3 unpack-production.py --apply
```

### Step 3: Load Docker Images

```bash
./production-deploy.sh load ./images
```

Verify:
```bash
docker images | grep -E "softpower|pgvector"
# Expected:
#   pgvector/pgvector       0.8.1-pg16   ...   ~400MB
#   softpower-app-production    latest       ...   ~700MB
```

### Step 4: Install ML Packages from Wheels

This is a one-time operation that installs torch, sentence-transformers, and langchain-huggingface into the app image from the pre-downloaded wheel files.

```bash
./production-deploy.sh setup
```

What happens:
1. Runs a temporary container from the slim image
2. Mounts `wheels/` directory read-only
3. `pip install --no-index --find-links /wheels torch sentence-transformers langchain-huggingface`
4. `docker commit` saves the result as the updated image
5. Removes the temporary container

Verify the image size increased:
```bash
docker images | grep softpower-app-production
# Size should now be ~2 GB (was ~700 MB)
```

### Step 5: Configure Environment

```bash
cp .env.example .env
vi .env
```

Key settings:
```bash
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=softpower-db

# LLM proxy (set to 0 to disable)
LLM_PROXY_PORT=7001

# API key for LLM features (optional)
CLAUDE_KEY=your_api_key
```

### Step 6: Start Services

```bash
./production-deploy.sh start
```

This starts both containers:
- `softpower_db` — PostgreSQL + pgvector on port 5432
- `softpower_app` — FastAPI (8000) + Streamlit (8501) with HuggingFace model mounted

### Step 7: Initialize Database

```bash
# Run Alembic migrations
./production-deploy.sh migrate

# (Optional) Restore from backup
./production-deploy.sh restore softpower-backup.dump
```

### Step 8: Verify Deployment

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

---

## Management Commands

```bash
./production-deploy.sh load [dir]       # Load Docker images from tar files
./production-deploy.sh setup            # Install ML wheels into app image (one-time)
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
WorkingDirectory=/opt/softpower-production-YYYYMMDD
ExecStart=/opt/softpower-production-YYYYMMDD/production-deploy.sh start
ExecStop=/opt/softpower-production-YYYYMMDD/production-deploy.sh stop

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

If you see `ImportError: No module named 'torch'` or similar:
```bash
# Re-run setup
./production-deploy.sh setup

# Verify packages installed
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

When a new version is available:

```bash
# 1. On internet-connected system: rebuild package
./scripts/docker/production-build.sh

# 2. Transfer new package to production system

# 3. On production system:
./production-deploy.sh stop
./production-deploy.sh load ./images      # Load updated slim image
./production-deploy.sh setup              # Re-install ML packages
./production-deploy.sh start
./production-deploy.sh migrate            # Apply any new migrations
```

To update only the ML wheels (e.g., new torch version) without rebuilding the full image:
```bash
# Transfer only the updated .whl files to wheels/
./production-deploy.sh stop
./production-deploy.sh load ./images      # Reload the slim base image
./production-deploy.sh setup              # Install updated wheels
./production-deploy.sh start
```

---

## Verification Checklist

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
