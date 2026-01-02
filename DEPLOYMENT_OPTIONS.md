# Deployment Options Summary

Quick reference guide for deploying the Soft Power Analytics application.

---

## Option 1: Local Development (Fastest Iteration)

**Best for:** Active development, debugging, testing

**Requirements:**
- Node.js 18+
- Python 3.11+
- PostgreSQL 14+ (can run in Docker)

**Commands:**
```bash
# Terminal 1: React dev server (hot reload)
cd client
npm run dev
# → http://localhost:5000

# Terminal 2: FastAPI backend (hot reload)
cd server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# → http://localhost:8000/api
```

**Pros:**
- ✅ Fastest rebuild (instant hot reload)
- ✅ Best debugging experience
- ✅ Direct access to source code

**Cons:**
- ❌ Requires Node.js + Python locally
- ❌ Manual setup of dependencies

---

## Option 2: Hybrid Docker (Docker DB + Local Services)

**Best for:** Development with simplified database setup

**Requirements:**
- Docker + Docker Compose
- Node.js 18+ (for React)
- Python 3.11+ (for FastAPI)

**Commands:**
```bash
# Start PostgreSQL + Redis in Docker
docker-compose up -d db redis

# Terminal 1: React dev server
cd client
npm run dev

# Terminal 2: FastAPI backend
cd server
uvicorn main:app --reload
```

**Pros:**
- ✅ No PostgreSQL installation needed
- ✅ Fast iteration with hot reload
- ✅ Easy database backup/restore

**Cons:**
- ❌ Still requires Node.js + Python locally

---

## Option 3: Full Docker (Build React on Host)

**Best for:** Production-like local testing

**Requirements:**
- Docker + Docker Compose
- Node.js 18+ (for building React)

**Commands:**
```bash
# Build React on host
cd client
npm run build

# Start all services in Docker
cd ..
docker-compose up -d
# → http://localhost:8000
```

**Pros:**
- ✅ Production-like environment
- ✅ All services orchestrated
- ✅ Easy deployment

**Cons:**
- ❌ Manual React build step
- ❌ No hot reload

**Files:**
- [docker-compose.yml](docker-compose.yml)
- [docker/api.Dockerfile](docker/api.Dockerfile)

---

## Option 4: Full Docker Build ⭐ (Recommended for Production)

**Best for:** Production deployment, CI/CD, no local dependencies

**Requirements:**
- Docker + Docker Compose only

**Commands:**
```bash
# Build React INSIDE Docker (multi-stage build)
docker-compose -f docker-compose.build.yml up -d --build

# Run migrations
docker-compose -f docker-compose.build.yml --profile migrate up

# → http://localhost:8000
```

**Or use automated script:**
```bash
# Linux/macOS
./build-docker.sh

# Windows
.\build-docker.ps1
```

**Pros:**
- ✅ No Node.js or Python required on host
- ✅ Consistent builds across all environments
- ✅ Perfect for CI/CD pipelines
- ✅ Deploy anywhere with Docker
- ✅ Single command deployment

**Cons:**
- ❌ Slower build time (8-12 min initial)
- ❌ No hot reload (requires rebuild)

**Files:**
- [docker-compose.build.yml](docker-compose.build.yml)
- [docker/api-production.Dockerfile](docker/api-production.Dockerfile)
- [build-docker.sh](build-docker.sh) / [build-docker.ps1](build-docker.ps1)

**See:** [Full Docker Build Guide](docs/deployment/DOCKER_BUILD.md)

---

## Option 5: Docker Hub (Pre-built Images)

**Best for:** End users, quick deployment without building

**Requirements:**
- Docker + Docker Compose only

**Commands:**
```bash
# Pull and run pre-built images from Docker Hub
docker-compose -f docker-compose.production.yml up -d

# Run migrations
docker-compose -f docker-compose.production.yml run --rm migrate
```

**Pros:**
- ✅ No build time (downloads pre-built)
- ✅ Fastest deployment
- ✅ Verified production images

**Cons:**
- ❌ Requires images published to Docker Hub
- ❌ Can't modify source code

**Files:**
- [docker-compose.production.yml](docker-compose.production.yml)

---

## Comparison Table

| Option | Build Time | Hot Reload | Node.js Required | Python Required | Docker Required | Best For |
|--------|-----------|------------|------------------|-----------------|-----------------|----------|
| **Local Dev** | Instant | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No | Development |
| **Hybrid Docker** | Instant | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | Dev + Easy DB |
| **Docker (Host Build)** | 2-3 min | ❌ No | ✅ Yes | ❌ No | ✅ Yes | Testing |
| **Docker (Full Build)** ⭐ | 8-12 min | ❌ No | ❌ No | ❌ No | ✅ Yes | **Production/CI/CD** |
| **Docker Hub** | 0 min (download) | ❌ No | ❌ No | ❌ No | ✅ Yes | End Users |

---

## Which Option Should I Choose?

### For Development
→ **Option 1 (Local Dev)** if you want fastest iteration with hot reload

→ **Option 2 (Hybrid Docker)** if you want easy database setup but still want hot reload

### For Testing
→ **Option 3 (Docker - Host Build)** if you want to test in production-like environment

### For Production / CI/CD ⭐
→ **Option 4 (Full Docker Build)** - Recommended for consistent, portable deployments

### For End Users
→ **Option 5 (Docker Hub)** if just deploying pre-built images

---

## Quick Start Commands

```bash
# Development (fastest iteration)
npm run dev  # Terminal 1
uvicorn server.main:app --reload  # Terminal 2

# Production (recommended)
./build-docker.sh  # Linux/macOS
.\build-docker.ps1  # Windows
```

---

## Additional Resources

- **Development Guide**: [client/README.md](client/README.md)
- **Full Docker Build Guide**: [docs/deployment/DOCKER_BUILD.md](docs/deployment/DOCKER_BUILD.md)
- **Pipeline Scripts**: [CURRENT_PIPELINE_SCRIPTS.md](CURRENT_PIPELINE_SCRIPTS.md)
- **Main Documentation**: [README.md](README.md)
- **Setup Guide**: [CLAUDE.md](CLAUDE.md)

---

## Option 6: Deploy to Existing Database ⭐ (Your Scenario)

**Best for:** When you already have a populated PostgreSQL database running

**Requirements:**
- Docker + Docker Compose
- Existing PostgreSQL with data (container: `softpower_db`)

**Commands:**
```bash
# Automated deployment
./deploy-webapp.sh      # Linux/macOS
.\deploy-webapp.ps1     # Windows

# Or manual
docker-compose -f docker-compose.webapp.yml up -d --build
```

**What it does:**
- ✅ Builds React inside Docker (multi-stage build)
- ✅ Connects to your existing `softpower_db` container
- ✅ **NO new database created**
- ✅ **NO migrations needed** (database already populated)
- ✅ Serves web app on http://localhost:8000

**Pros:**
- ✅ Uses your existing data (496K+ documents)
- ✅ No database setup needed
- ✅ No migrations to run
- ✅ Just builds and serves the web app

**Files:**
- [docker-compose.webapp.yml](docker-compose.webapp.yml)
- [deploy-webapp.sh](deploy-webapp.sh) / [deploy-webapp.ps1](deploy-webapp.ps1)

**This is what you need!** Your database is already running with data.


---

## Option 7: Full Production Stack ⭐⭐ (Complete System)

**Best for:** Production deployment with all services, database management, and pipeline processing

**Requirements:**
- Docker + Docker Compose only
- (Optional) NVIDIA GPU for accelerated ML processing

**Commands:**
```bash
# Automated full deployment
./deploy-full.sh      # Linux/macOS
.\deploy-full.ps1     # Windows

# Or manual
docker-compose -f docker-compose.full.yml build --parallel
docker-compose -f docker-compose.full.yml up -d
docker-compose -f docker-compose.full.yml --profile migrate up
```

**What's Included:**

**Database Tier:**
- ✅ PostgreSQL + pgvector
- ✅ pgAdmin (database management UI)
- ✅ Redis (cache & task queue)

**Processing Tier:**
- ✅ Pipeline worker (all data processing scripts)
- ✅ GPU support (optional, for embeddings)

**Application Tier:**
- ✅ React web app (http://localhost:8000)
- ✅ FastAPI backend (http://localhost:8000/api)
- ✅ Streamlit dashboard (http://localhost:8501)

**Run Pipeline Tasks:**
```bash
# Document ingestion
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/ingestion/dsr.py

# AI analysis
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/analysis/atom_extraction.py

# Generate embeddings
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/embeddings/embed_missing_documents.py --yes

# Event processing
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/events/batch_cluster_events.py \
  --country China --start-date 2024-08-01 --end-date 2024-08-31
```

**Pros:**
- ✅ Complete system in Docker
- ✅ All services orchestrated
- ✅ Pipeline runs inside container
- ✅ Database management UI (pgAdmin)
- ✅ GPU acceleration available
- ✅ Production-ready

**Cons:**
- ❌ Longer build time (~15 min)
- ❌ More resource intensive
- ❌ Complex for simple use cases

**Files:**
- [docker-compose.full.yml](docker-compose.full.yml)
- [deploy-full.sh](deploy-full.sh) / [deploy-full.ps1](deploy-full.ps1)

**See:** [Full Stack Guide](docs/deployment/FULL_STACK.md)

**This is the complete production solution!**

