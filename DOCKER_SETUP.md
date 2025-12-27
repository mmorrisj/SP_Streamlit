# 🐳 Docker Setup for Dual Frontend Architecture

## Overview

Your Docker setup now supports **both frontends** (Streamlit + React) with a single backend.

## Architecture

```
Docker Compose Stack:
├── db (PostgreSQL + pgvector)           Port 5432
├── api (FastAPI - serves React UI)      Port 8000  ← React UI here
├── dashboard (Streamlit)                Port 8501  ← Streamlit UI here
└── redis (for caching)                  Internal
```

## Quick Start

### Option 1: Run Everything (Both UIs + Database)

```bash
# Build and start all services
docker-compose up -d

# Access:
# - React UI:     http://localhost:8000
# - Streamlit UI: http://localhost:8501
# - API Docs:     http://localhost:8000/docs
```

### Option 2: React Only (Recommended for Production)

```bash
# Start database only
docker-compose up -d db

# Build React frontend
cd client
npm run build
cd ..

# Start API server (serves React + API)
cd server
python main.py

# Access: http://localhost:8000
```

### Option 3: Streamlit Only (Legacy)

```bash
# Start database + API + Streamlit
docker-compose up -d db api dashboard

# Access: http://localhost:8501
```

---

## Before First Docker Build

**Important:** Build your React frontend first!

```bash
cd client
npm install
npm run build
```

This creates `client/dist/` which Docker will copy into the API container.

---

## Docker Commands

### Build & Start
```bash
# Build and start all services
docker-compose up -d

# Build with fresh images (no cache)
docker-compose build --no-cache
docker-compose up -d

# Start only specific services
docker-compose up -d db api          # React UI
docker-compose up -d db dashboard    # Streamlit UI
```

### Stop & Clean
```bash
# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ deletes database data!)
docker-compose down -v

# Remove all containers and images
docker-compose down --rmi all
```

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f db
docker-compose logs -f dashboard
```

### Check Status
```bash
# List running containers
docker-compose ps

# Check API health
curl http://localhost:8000/api/health
```

---

## Development Workflow

### Developing React UI

**Option A: Hot Reload (Development)**
```bash
# Terminal 1: Database
docker-compose up -d db

# Terminal 2: React dev server (hot reload)
cd client
npm run dev
# Access: http://localhost:5000

# Terminal 3: API server (if needed)
cd server
python main.py
```

**Option B: Production Build (Testing)**
```bash
# Build React
cd client
npm run build

# Rebuild Docker image
docker-compose build api
docker-compose up -d

# Access: http://localhost:8000
```

### Developing Streamlit UI

```bash
# Start database
docker-compose up -d db

# Run Streamlit locally (hot reload)
streamlit run services/dashboard/app.py

# Access: http://localhost:8501
```

---

## Updating the React UI

When you make changes to the React code:

### Local Development (No Docker)
```bash
cd client
npm run dev  # Hot reload at http://localhost:5000
```

### Docker Production Build
```bash
# 1. Build React
cd client
npm run build

# 2. Rebuild and restart API container
cd ..
docker-compose build api
docker-compose up -d api

# React changes now live at http://localhost:8000
```

---

## Database Migrations

```bash
# Run migrations in Docker
docker-compose --profile migrate up

# Or manually
docker exec -it api-service alembic upgrade head

# Create new migration
docker exec -it api-service alembic revision --autogenerate -m "description"
```

---

## Environment Variables

The `.env` file is used by Docker Compose:

```bash
# Database
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=softpower
POSTGRES_DB=softpower-db

# API Keys
CLAUDE_KEY=your_key_here
OPENAI_PROJ_API=your_key_here

# Ports (can customize)
# API_PORT=8000
# STREAMLIT_PORT=8501
```

---

## Troubleshooting

### React UI shows 404
**Problem:** `client/dist` doesn't exist
**Solution:**
```bash
cd client
npm run build
docker-compose build api
docker-compose up -d api
```

### API can't connect to database
**Problem:** Database not running
**Solution:**
```bash
docker-compose up -d db
# Wait 10 seconds for PostgreSQL to initialize
```

### Changes not showing up
**Problem:** Docker cached old build
**Solution:**
```bash
docker-compose build --no-cache api
docker-compose up -d api
```

### Port already in use
**Problem:** Port 8000 or 5432 already used
**Solution:**
```bash
# Check what's using the port
netstat -ano | findstr :8000
netstat -ano | findstr :5432

# Kill the process or change port in docker-compose.yml
```

---

## Volume Management

### Database Data
```bash
# Backup database
docker exec softpower_db pg_dump -U matthew50 softpower-db > backup.sql

# Restore database
cat backup.sql | docker exec -i softpower_db psql -U matthew50 -d softpower-db

# View volume
docker volume ls | grep softpower
docker volume inspect softpower_streamlit_postgres_data
```

---

## Production Deployment

For production, use this workflow:

```bash
# 1. Build React for production
cd client
npm run build

# 2. Build Docker images
docker-compose build

# 3. Push to registry (if using Docker Hub/ECR)
docker tag softpower_streamlit-api:latest your-registry/softpower-api:latest
docker push your-registry/softpower-api:latest

# 4. On production server
docker-compose pull
docker-compose up -d
```

---

## Summary

✅ **Docker handles**: Database, API server, Streamlit (optional)
✅ **React build**: Must be done before Docker build
✅ **Hot reload**: Use `npm run dev` for development
✅ **Production**: Use Docker Compose for full stack

**Recommended for daily work:**
- Use `npm run dev` for React development
- Use Docker only for database
- Deploy with Docker for production
