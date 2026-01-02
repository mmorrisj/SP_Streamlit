# Full Docker Build Guide

This guide covers building the React web app **inside Docker** using a multi-stage build.

## Overview

The production Docker build uses a **multi-stage approach**:

1. **Stage 1 (Node.js)**: Build React frontend
2. **Stage 2 (Python)**: Copy built React + serve via FastAPI

This eliminates the need to build React on the host machine.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│ Stage 1: Frontend Builder (node:20-slim)   │
│ - npm install (all deps)                    │
│ - npm run build                              │
│ - Output: client/dist/                       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ Stage 2: Backend (python:3.11-slim)        │
│ - Copy client/dist/ from Stage 1            │
│ - Install Python deps                        │
│ - FastAPI serves React + API                │
│ - Exposes port 8000                          │
└─────────────────────────────────────────────┘
```

---

## Quick Start

### Option 1: Using Production Compose File (Recommended)

```bash
# 1. Build and start all services
docker-compose -f docker-compose.production.yml up -d --build

# 2. Run database migrations
docker-compose -f docker-compose.production.yml --profile migrate up

# 3. Access application
# Web app: http://localhost:8000
# API docs: http://localhost:8000/docs
# Streamlit: http://localhost:8501
```

### Option 2: Manual Build and Run

```bash
# 1. Build production image
docker build -f docker/api-production.Dockerfile -t softpower-production:latest .

# 2. Run with docker run
docker run -d \
  --name softpower-api \
  -p 8000:8000 \
  --env-file .env \
  -e DOCKER_ENV=true \
  softpower-production:latest

# 3. Access at http://localhost:8000
```

---

## Build Process Details

### Stage 1: React Frontend Build

**Dockerfile snippet:**
```dockerfile
FROM node:20-slim AS frontend-builder

WORKDIR /app/client

# Install all dependencies (including devDependencies)
COPY client/package*.json ./
RUN npm ci

# Copy source and build
COPY client/ ./
RUN npm run build
```

**What happens:**
- Installs all npm dependencies (including build tools like Vite, TypeScript)
- Runs `npm run build` (equivalent to `vite build`)
- Creates optimized production bundle in `client/dist/`
- **This stage is discarded** after copying dist/ to Stage 2

### Stage 2: Python Backend

**Dockerfile snippet:**
```dockerfile
FROM python:3.11-slim AS backend

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY shared/ ./shared/
COPY server/ ./server/
COPY services/ ./services/

# Copy built React from Stage 1
COPY --from=frontend-builder /app/client/dist ./client/dist

# Start FastAPI
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**What happens:**
- Installs Python dependencies
- Copies application code
- **Copies built React files from Stage 1** (no Node.js in final image)
- Final image only contains Python + built static files
- FastAPI serves both React UI and API endpoints

---

## Environment Configuration

### Required Environment Variables

Create `.env` file in project root:

```bash
# Database
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=softpower-db

# OpenAI API
CLAUDE_KEY=your_openai_api_key

# AWS S3 (optional)
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
S3_BUCKET=your-bucket-name
```

### Docker-specific Variables

These are automatically set by docker-compose.production.yml:

```yaml
environment:
  DOCKER_ENV: "true"                # Enables Docker mode
  NODE_ENV: "production"            # Production build
  DB_HOST: softpower_db_prod        # Container DB hostname
  DATABASE_URL: postgresql+psycopg2://user:pass@softpower_db_prod:5432/db
```

---

## Build Optimization

### .dockerignore File

The [.dockerignore](../../.dockerignore) file excludes:
- `client/node_modules/` (700MB+)
- `_data/` directories (processed data)
- `.git/` directory
- Python `__pycache__/`
- Documentation archives

**Result:** Build context reduced from ~2GB to ~50MB

### Layer Caching

Docker caches layers to speed up rebuilds:

1. **Python dependencies** - Only rebuilds if `requirements.txt` changes
2. **npm dependencies** - Only rebuilds if `package.json` changes
3. **Application code** - Rebuilds when source files change

**Tip:** To force rebuild without cache:
```bash
docker-compose -f docker-compose.production.yml build --no-cache
```

---

## Production Deployment

### Full Deployment Steps

```bash
# 1. Clone repository
git clone https://github.com/your-repo/SP_Streamlit.git
cd SP_Streamlit

# 2. Create .env file
cp .env.example .env
# Edit .env with production credentials

# 3. Build and start services
docker-compose -f docker-compose.production.yml up -d --build

# 4. Run database migrations
docker-compose -f docker-compose.production.yml --profile migrate up

# 5. Verify services are healthy
docker-compose -f docker-compose.production.yml ps

# 6. Check logs
docker-compose -f docker-compose.production.yml logs -f api

# 7. Test health endpoint
curl http://localhost:8000/api/health
```

### Updating Deployment

```bash
# 1. Pull latest code
git pull origin main

# 2. Rebuild only changed services
docker-compose -f docker-compose.production.yml up -d --build

# 3. Run migrations if needed
docker-compose -f docker-compose.production.yml --profile migrate up
```

---

## Troubleshooting

### Build Fails at React Stage

**Problem:** `npm run build` fails during Stage 1

**Solutions:**
```bash
# 1. Check for TypeScript errors locally first
cd client
npm install
npm run build

# 2. Increase Docker memory
# Docker Desktop → Settings → Resources → Memory: 4GB+

# 3. Check build logs
docker-compose -f docker-compose.production.yml build --no-cache api
```

### React Files Not Found

**Problem:** API starts but returns 404 for React routes

**Solutions:**
```bash
# 1. Verify client/dist exists in image
docker run --rm softpower-production:latest ls -la /app/client/dist

# 2. Check server/main.py STATIC_DIR path
docker-compose -f docker-compose.production.yml logs api | grep -i static

# 3. Rebuild from scratch
docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml build --no-cache
docker-compose -f docker-compose.production.yml up -d
```

### Database Connection Fails

**Problem:** API can't connect to PostgreSQL

**Solutions:**
```bash
# 1. Check database is healthy
docker-compose -f docker-compose.production.yml ps

# 2. Check DATABASE_URL environment variable
docker-compose -f docker-compose.production.yml exec api env | grep DATABASE

# 3. Test connection from API container
docker-compose -f docker-compose.production.yml exec api \
  python -c "from shared.database.database import health_check; print(health_check())"
```

### Build Context Too Large

**Problem:** Build takes 10+ minutes, uploads GBs of data

**Solutions:**
```bash
# 1. Verify .dockerignore is working
docker build -f docker/api-production.Dockerfile --progress=plain . 2>&1 | head -20

# 2. Check what's being included
docker build -f docker/api-production.Dockerfile --progress=plain . 2>&1 | grep "Sending build context"

# 3. Add more exclusions to .dockerignore
echo "_data/" >> .dockerignore
echo "client/node_modules/" >> .dockerignore
```

---

## Performance Benchmarks

**Build Times** (on M1 MacBook Pro):
- Initial build (no cache): ~8-12 minutes
- Rebuild (code changes only): ~30-60 seconds
- Rebuild (dependencies changed): ~3-5 minutes

**Image Sizes:**
- Stage 1 (node:20-slim + deps): ~800MB (discarded)
- Final image (python:3.11-slim + app): ~1.2GB

**Runtime Performance:**
- Cold start: ~5-10 seconds
- React bundle size: ~500KB gzipped
- API response time: ~50-200ms

---

## Comparison: Docker vs Host Build

| Aspect | Docker Build | Host Build |
|--------|-------------|------------|
| **Build Time** | 8-12 min (initial) | 2-3 min |
| **Rebuild** | 30-60 sec | 10-20 sec |
| **Dependencies** | Self-contained | Requires Node.js + Python locally |
| **Portability** | Deploy anywhere | Host-specific build |
| **CI/CD** | ✅ Perfect | ❌ Requires Node + Python on CI |
| **Development** | ❌ Slower iteration | ✅ Hot reload |
| **Production** | ✅ Recommended | ⚠️ Manual build + copy |

**Recommendation:**
- **Development**: Use host build (`npm run dev` + `uvicorn --reload`)
- **Production/CI/CD**: Use Docker build (consistent, portable)

---

## Advanced: Multi-Architecture Builds

Build for multiple platforms (AMD64, ARM64):

```bash
# 1. Create buildx builder
docker buildx create --name multiarch --use

# 2. Build for multiple platforms
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/api-production.Dockerfile \
  -t your-registry/softpower-production:latest \
  --push \
  .

# 3. Deploy on any architecture
docker run -d -p 8000:8000 your-registry/softpower-production:latest
```

---

## See Also

- [Development Guide](../../client/README.md) - Local development without Docker
- [docker-compose.production.yml](../../docker-compose.production.yml) - Production compose file
- [api-production.Dockerfile](../../docker/api-production.Dockerfile) - Multi-stage Dockerfile
- [.dockerignore](../../.dockerignore) - Build context exclusions
