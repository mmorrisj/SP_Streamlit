# Non-Docker Setup Guide

This guide explains how to run the SoftPower Analytics project **without Docker**, while keeping Docker support intact.

## Prerequisites

1. **Python 3.11+** installed
2. **Node.js 18+** and **npm** installed (for React frontend)
3. **PostgreSQL 15+** with pgvector extension
4. **Redis** (optional, for future Celery tasks)
5. **Git** for version control

## Step-by-Step Setup

### 1. Install PostgreSQL with pgvector

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib postgresql-server-dev-all
sudo apt install build-essential

# Install pgvector extension
git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
cd ..
rm -rf pgvector
```

**macOS:**
```bash
brew install postgresql@15
brew services start postgresql@15
brew install pgvector
```

**Windows:**
- Download and install PostgreSQL from https://www.postgresql.org/download/windows/
- Install pgvector from https://github.com/pgvector/pgvector/releases

### 2. Create Database and User

```bash
# Connect to PostgreSQL
sudo -u postgres psql

# Create user and database
CREATE USER matthew50 WITH PASSWORD 'softpower';
CREATE DATABASE "softpower-db" OWNER matthew50;
\c softpower-db
CREATE EXTENSION vector;
GRANT ALL PRIVILEGES ON DATABASE "softpower-db" TO matthew50;
\q
```

### 3. Install Node.js and React Dependencies

**Ubuntu/Debian:**
```bash
# Install Node.js 20.x LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify installation
node --version  # Should be v20.x
npm --version   # Should be 10.x
```

**macOS:**
```bash
brew install node@20
brew link node@20
```

**Windows:**
- Download and install from https://nodejs.org/ (LTS version)

**Install React app dependencies:**
```bash
cd client
npm install
cd ..
```

### 4. Install Python Dependencies

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configure Environment Variables

The `.env` file is already configured for non-Docker setup with localhost defaults:

```bash
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=softpower
POSTGRES_DB=softpower-db

# API Configuration
API_URL=http://localhost:5001
FASTAPI_URL=http://localhost:5001/material_query

# OpenAI/Claude Keys
CLAUDE_KEY=your-claude-key-here
OPENAI_PROJ_API=your-openai-key-here
```

**Important:** Make sure `.env` is in the project root directory.

### 6. Initialize Database

```bash
# Run Alembic migrations
alembic upgrade head

# Or initialize from Python
python -c "from shared.database.database import init_database; init_database()"

# Verify connection
python -c "from shared.database.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"
```

### 7. Build React Client (Production) or Start Dev Server (Development)

**Option A: Production Build** (FastAPI serves static files)
```bash
cd client
npm run build
cd ..
```

This creates optimized production files in `client/dist/` that will be served by the FastAPI server at http://localhost:8000

**Option B: Development Mode** (Vite dev server with hot reload)
```bash
cd client
npm run dev
```

This starts the Vite dev server at http://localhost:5000 with hot module replacement for faster development.

### 8. Start Services

You can run services individually or use the startup script:

#### Option A: Manual Service Start

**For Production (FastAPI serves React build):**

**Terminal 1 - FastAPI Service (serves API + React static files):**
```bash
source venv/bin/activate  # or .\venv\Scripts\activate on Windows
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
# Access React app at: http://localhost:8000
# Access API at: http://localhost:8000/api/*
```

**Terminal 2 - Streamlit Dashboard (optional analytics):**
```bash
source venv/bin/activate
cd services/dashboard
streamlit run app.py --server.port 8501
# Access at: http://localhost:8501
```

**For Development (separate React dev server):**

**Terminal 1 - FastAPI API Service:**
```bash
source venv/bin/activate
cd services/api
uvicorn main:app --host 0.0.0.0 --port 5001 --reload
# API at: http://localhost:5001
```

**Terminal 2 - React Vite Dev Server:**
```bash
cd client
npm run dev
# React app at: http://localhost:5000 (with hot reload)
# Proxies /api requests to localhost:8000
```

**Terminal 3 - Streamlit Dashboard (optional):**
```bash
source venv/bin/activate
cd services/dashboard
streamlit run app.py --server.port 8501
```

**Terminal 4 - Pipeline Scripts (as needed):**
```bash
source venv/bin/activate
python services/pipeline/ingestion/atom.py
python services/pipeline/analysis/atom_extraction.py
# etc.
```

#### Option B: Use Startup Script

See `start_services.sh` or `start_services.ps1` for automated startup.

## Running Pipeline Scripts

All pipeline scripts work identically with or without Docker:

```bash
# Activate virtual environment first
source venv/bin/activate  # or .\venv\Scripts\activate on Windows

# Document ingestion
python services/pipeline/ingestion/atom.py
python services/pipeline/ingestion/dsr.py --status

# AI analysis
python services/pipeline/analysis/atom_extraction.py

# Event processing
python services/pipeline/events/batch_cluster_events.py --country China --start-date 2024-08-01 --end-date 2024-08-31
python services/pipeline/events/llm_deconflict_clusters.py --country China --start-date 2024-08-01 --end-date 2024-08-31
python services/pipeline/events/consolidate_all_events.py --country China
python services/pipeline/events/llm_deconflict_canonical_events.py --country China
python services/pipeline/events/merge_canonical_events.py --country China
```

## Key Differences: Docker vs Non-Docker

| Aspect | Docker | Non-Docker |
|--------|--------|------------|
| Database Host | `softpower_db` (service name) | `localhost` |
| API URL | `http://host.docker.internal:5001` | `http://localhost:5001` |
| Service Startup | `docker-compose up` | Individual `uvicorn`/`streamlit` commands |
| Dependencies | Managed by containers | Managed by venv |
| PostgreSQL | In container | System-installed |

## Environment Variable Detection

The project automatically detects whether it's running in Docker via the `DOCKER_ENV` environment variable:

- **Docker**: `DOCKER_ENV=true` (set by docker-compose.yml)
- **Non-Docker**: `DOCKER_ENV` not set, uses `.env` file

## Troubleshooting

### Database Connection Issues

```bash
# Check PostgreSQL is running
sudo systemctl status postgresql  # Linux
brew services list  # macOS
# Services app on Windows

# Test direct connection
psql -U matthew50 -d softpower-db -h localhost

# Check environment variables are loaded
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('DB_HOST'))"
```

### Port Conflicts

If ports 5001 or 8501 are in use:

```bash
# Find what's using the port (Linux/macOS)
lsof -i :5001
lsof -i :8501

# Find what's using the port (Windows)
netstat -ano | findstr :5001
netstat -ano | findstr :8501

# Update .env with different ports
API_PORT=5002
STREAMLIT_PORT=8502
```

### Module Import Errors

Make sure you're running from the project root and have activated the venv:

```bash
# Check current directory
pwd  # Should be .../SP_Streamlit

# Activate venv
source venv/bin/activate  # or .\venv\Scripts\activate

# Add project to PYTHONPATH (if needed)
export PYTHONPATH="${PYTHONPATH}:$(pwd)"  # Linux/macOS
set PYTHONPATH=%PYTHONPATH%;%CD%  # Windows
```

## Switching Between Docker and Non-Docker

You can easily switch between modes:

**To use Docker:**
```bash
docker-compose up -d
# Docker overrides DB_HOST to 'softpower_db' in docker-compose.yml
```

**To use non-Docker:**
```bash
docker-compose down
source venv/bin/activate
# Start services manually or with startup script
# Uses localhost from .env
```

## Production Deployment (Non-Docker)

For production on a bare server:

1. Use systemd services (Linux) or Windows Services for auto-restart
2. Set up nginx reverse proxy for API and Streamlit
3. Use PostgreSQL on a managed service (AWS RDS, etc.)
4. Set production environment variables in `/etc/environment` or systemd service files
5. Use gunicorn instead of uvicorn for better performance:
   ```bash
   gunicorn services.api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:5001
   ```

## Benefits of This Dual Setup

✅ **Flexibility**: Use Docker for development, bare metal for production
✅ **No Lock-in**: Not dependent on Docker infrastructure
✅ **Easier Debugging**: Direct Python debugging without Docker layers
✅ **Lower Resource Usage**: No Docker overhead on resource-constrained systems
✅ **Cloud-Friendly**: Works on any VPS, EC2, or managed hosting
