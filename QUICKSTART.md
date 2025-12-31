# Quick Start Guide

## Choose Your Deployment Method

### Docker (Recommended for Development)
```bash
# One-time setup
docker-compose up -d
docker-compose --profile migrate up

# Daily usage
docker-compose up -d      # Start
docker-compose down       # Stop
docker-compose logs -f    # View logs
```

### Non-Docker (Production / No Docker Available)
```bash
# One-time setup
python3 -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

# Install Node.js dependencies for React client
cd client
npm install
cd ..

# Configure PostgreSQL (see SETUP_NON_DOCKER.md)
# Create database and user, install pgvector extension

# Run migrations
alembic upgrade head

# Build React client for production
cd client
npm run build
cd ..

# Daily usage - Development mode (separate React dev server with hot reload)
./start_services.sh all   # Linux/macOS - Start all services
.\start_services.ps1 all  # Windows - Start all services

# Daily usage - Production mode (FastAPI serves built React app)
./start_services.sh prod   # Linux/macOS
.\start_services.ps1 prod  # Windows

./start_services.sh stop  # Stop services
```

## Access Points

### Docker Mode
- **React App**: http://localhost:8000 (served by FastAPI)
- **API**: http://localhost:8000/api/*
- **Streamlit Dashboard**: http://localhost:8501
- **Database**: localhost:5432

### Non-Docker Development Mode (./start_services.sh all)
- **React App**: http://localhost:5000 (Vite dev server with hot reload)
- **API**: http://localhost:5001
- **Streamlit Dashboard**: http://localhost:8501
- **Database**: localhost:5432

### Non-Docker Production Mode (./start_services.sh prod)
- **React App**: http://localhost:8000 (production build served by FastAPI)
- **API**: http://localhost:8000/api/*
- **Streamlit Dashboard**: http://localhost:8501
- **Database**: localhost:5432

## Running Pipeline Scripts

Both modes use the same commands:

```bash
# Docker mode - run inside container
docker exec -it api-service python services/pipeline/events/batch_cluster_events.py --country China

# Non-Docker mode - run from venv
source venv/bin/activate
python services/pipeline/events/batch_cluster_events.py --country China
```

## Troubleshooting

**Database connection failed?**
```bash
# Check PostgreSQL is running
docker ps                           # Docker mode
sudo systemctl status postgresql    # Non-Docker Linux
```

**Port already in use?**
```bash
# Change ports in .env file
API_PORT=5002
STREAMLIT_PORT=8502
```

**Module import errors?**
```bash
# Make sure you're in project root and venv is activated
pwd  # Should show .../SP_Streamlit
source venv/bin/activate  # Non-Docker only
```

## Full Documentation
- Docker setup: See [CLAUDE.md](CLAUDE.md) Docker sections
- Non-Docker setup: See [SETUP_NON_DOCKER.md](SETUP_NON_DOCKER.md)
- Pipeline commands: See [CLAUDE.md](CLAUDE.md) Pipeline sections
