# Quick Start Guide

## Choose Your Deployment Method

### Docker Compose (Recommended for Development)
```bash
# One-time setup
docker-compose up -d
docker-compose --profile migrate up

# Daily usage
docker-compose up -d      # Start
docker-compose down       # Stop
docker-compose logs -f    # View logs
```

### Production Docker (No Compose)
```bash
# First-time deploy
./scripts/docker/production-deploy.sh start
./scripts/docker/production-deploy.sh migrate

# Or restore from backup
./scripts/docker/production-deploy.sh start
./scripts/docker/production-deploy.sh restore backup.dump
```

## Access Points

### Docker Compose Mode
- **React App**: http://localhost:8000 (served by FastAPI)
- **API**: http://localhost:8000/api/*
- **Streamlit Dashboard**: http://localhost:8501
- **Database**: localhost:5432

### Production Docker Mode
- **React App**: http://localhost:8000 (served by FastAPI)
- **API**: http://localhost:8000/api/*
- **Streamlit Dashboard**: http://localhost:8501
- **Database**: localhost:5432

## Running Pipeline Scripts

```bash
# Docker Compose mode - run inside container
docker-compose exec api python services/pipeline/events/batch_cluster_events.py --country China

# Production Docker mode - run inside container
docker exec softpower_app python services/pipeline/events/batch_cluster_events.py --country China
```

## Troubleshooting

**Database connection failed?**
```bash
# Check PostgreSQL is running
docker ps
```

**Port already in use?**
```bash
# Change ports in .env file
API_PORT=5002
STREAMLIT_PORT=8502
```

**Module import errors?**
```bash
# Make sure you're in project root
pwd  # Should show .../SP_Streamlit
```

## Full Documentation
- **Docker Compose setup**: See [../CLAUDE.md](../CLAUDE.md) Docker sections
- **Docker workflow**: See [../DOCKER_WORKFLOW.md](../DOCKER_WORKFLOW.md)
- **Production install**: See [deployment/PRODUCTION_INSTALL.md](deployment/PRODUCTION_INSTALL.md)
- **Docker Hub deployment**: See [DOCKERHUB_README.md](DOCKERHUB_README.md)
- **Pipeline commands**: See [../CLAUDE.md](../CLAUDE.md) Pipeline sections
