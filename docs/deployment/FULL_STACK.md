# Full Stack Docker Deployment

Complete production-ready deployment with all services in Docker.

## Overview

The full stack includes:

### Database Tier
- **PostgreSQL + pgvector** - Main database with vector search
- **pgAdmin** - Web-based database management (optional)
- **Redis** - Cache and task queue

### Processing Tier
- **Pipeline Worker** - Data processing, embeddings, event analysis
- **GPU Support** - Optional CUDA support for ML workloads

### Application Tier
- **React Web App** - Modern UI (built inside Docker)
- **FastAPI** - Backend API server
- **Streamlit Dashboard** - Analytics and data exploration

---

## Quick Start

### One-Command Deployment

```bash
# Linux/macOS
./deploy-full.sh

# Windows
.\deploy-full.ps1
```

### Manual Deployment

```bash
# 1. Build all services
docker-compose -f docker-compose.full.yml build --parallel

# 2. Start all services
docker-compose -f docker-compose.full.yml up -d

# 3. Run database migrations
docker-compose -f docker-compose.full.yml --profile migrate up

# 4. Verify deployment
curl http://localhost:8000/api/health
curl http://localhost:8501/_stcore/health
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Docker Network                    │
├─────────────────────────────────────────────────────┤
│                                                      │
│  DATABASE TIER                                       │
│  ┌─────────────────┐  ┌──────────┐  ┌───────────┐  │
│  │ PostgreSQL      │  │ pgAdmin  │  │   Redis   │  │
│  │ + pgvector      │  │ (opt)    │  │   Cache   │  │
│  │ :5432           │  │ :5050    │  │   :6379   │  │
│  └─────────────────┘  └──────────┘  └───────────┘  │
│                                                      │
│  PROCESSING TIER                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ Pipeline Worker                               │   │
│  │ - Document ingestion (dsr.py, atom.py)       │   │
│  │ - AI analysis (atom_extraction.py)           │   │
│  │ - Embeddings (embed_*.py)                    │   │
│  │ - Event processing (batch_*.py)              │   │
│  │ - GPU support (optional)                     │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  APPLICATION TIER                                    │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐   │
│  │ React UI   │  │  FastAPI   │  │  Streamlit  │   │
│  │ (built in  │  │    API     │  │  Dashboard  │   │
│  │  Docker)   │  │  :8000     │  │   :8501     │   │
│  └────────────┘  └────────────┘  └─────────────┘   │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## Access Points

After deployment:

| Service | URL | Purpose |
|---------|-----|---------|
| **React Web App** | http://localhost:8000 | Modern web interface |
| **API Docs** | http://localhost:8000/docs | Interactive API documentation |
| **Streamlit** | http://localhost:8501 | Analytics dashboard |
| **PostgreSQL** | localhost:5432 | Database (direct connection) |
| **Redis** | localhost:6379 | Cache/queue (direct connection) |
| **pgAdmin** | http://localhost:5050 | Database management (optional) |

---

## Running Pipeline Tasks

All pipeline scripts run inside the `pipeline` container:

### Document Ingestion

```bash
# Ingest from S3
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/ingestion/dsr.py

# Check status
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/ingestion/dsr.py --status

# Ingest from Atom feed
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/ingestion/atom.py
```

### AI Analysis

```bash
# Extract salience, categories, countries, projects
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/analysis/atom_extraction.py
```

### Generate Embeddings

```bash
# Embed all missing documents
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/embeddings/embed_missing_documents.py --yes

# Check embedding status
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/embeddings/embed_missing_documents.py --status

# Embed event summaries
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/embeddings/embed_event_summaries.py --yes
```

### Event Processing

**Stage 1: Daily Event Detection**

```bash
# Stage 1A: Cluster daily events
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/events/batch_cluster_events.py \
  --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 1B: LLM validate and create canonical events
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/events/llm_deconflict_clusters.py \
  --country China --start-date 2024-08-01 --end-date 2024-08-31
```

**Stage 2: Batch Consolidation**

```bash
# Stage 2A: Group events via embeddings
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/events/consolidate_all_events.py --influencers

# Stage 2B: LLM validate consolidations
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/events/llm_deconflict_canonical_events.py --influencers

# Stage 2C: Merge daily mentions
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/events/merge_canonical_events.py --influencers
```

### Backup & Restore

```bash
# Export embeddings
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/embeddings/export_embeddings.py \
  --output-dir ./_data/exports/embeddings/$(date +%Y%m%d) \
  --include-event-summaries

# Import embeddings
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/embeddings/import_embeddings.py \
  --input-dir ./_data/exports/embeddings/20241106
```

---

## Database Management

### Using pgAdmin (Optional)

Start pgAdmin:

```bash
docker-compose -f docker-compose.full.yml --profile management up -d
```

Access: http://localhost:5050
- Email: `admin@softpower.local` (or from `.env`)
- Password: `admin` (or from `.env`)

**Add Server in pgAdmin:**
1. Right-click "Servers" → "Register" → "Server"
2. **General Tab**: Name: `Soft Power DB`
3. **Connection Tab**:
   - Host: `softpower_db`
   - Port: `5432`
   - Database: `softpower-db`
   - Username: `matthew50` (or from `.env`)
   - Password: `softpower` (or from `.env`)

### Direct psql Access

```bash
# Connect to database
docker-compose -f docker-compose.full.yml exec db psql -U matthew50 -d softpower-db

# Example queries
softpower-db=# SELECT COUNT(*) FROM documents;
softpower-db=# \dt  -- List tables
softpower-db=# \d+ documents  -- Describe documents table
```

### Database Backups

```bash
# Full database dump
docker-compose -f docker-compose.full.yml exec db \
  pg_dump -U matthew50 softpower-db > backup_$(date +%Y%m%d).sql

# Restore from backup
docker-compose -f docker-compose.full.yml exec -T db \
  psql -U matthew50 -d softpower-db < backup_20241106.sql
```

---

## Monitoring & Logs

### View Logs

```bash
# All services
docker-compose -f docker-compose.full.yml logs -f

# Specific service
docker-compose -f docker-compose.full.yml logs -f api
docker-compose -f docker-compose.full.yml logs -f pipeline
docker-compose -f docker-compose.full.yml logs -f dashboard
docker-compose -f docker-compose.full.yml logs -f db

# Last 100 lines
docker-compose -f docker-compose.full.yml logs --tail=100 api
```

### Service Status

```bash
# Check all services
docker-compose -f docker-compose.full.yml ps

# Check specific service health
docker-compose -f docker-compose.full.yml exec api curl -f http://localhost:8000/api/health
```

### Resource Usage

```bash
# Docker stats (real-time)
docker stats

# Specific container
docker stats softpower_api softpower_db softpower_pipeline
```

---

## Scaling & Performance

### Adjust Resource Limits

Edit `docker-compose.full.yml`:

```yaml
api:
  deploy:
    resources:
      limits:
        memory: 4G  # Increase for large datasets
      reservations:
        memory: 2G

db:
  shm_size: "4gb"  # Increase for complex queries
```

### Scale Specific Services

```bash
# Scale pipeline workers (for parallel processing)
docker-compose -f docker-compose.full.yml up -d --scale pipeline=3
```

### Database Performance Tuning

Connect to PostgreSQL and optimize:

```sql
-- Create indexes for common queries
CREATE INDEX CONCURRENTLY idx_documents_country
  ON documents USING btree (initiating_country);

-- Vacuum and analyze
VACUUM ANALYZE documents;

-- Check query performance
EXPLAIN ANALYZE SELECT * FROM documents WHERE ...;
```

---

## GPU Support (Optional)

The pipeline container supports NVIDIA GPUs for accelerated ML workloads.

### Prerequisites

1. **NVIDIA GPU** on host machine
2. **NVIDIA Docker runtime** installed:
   ```bash
   # Install nvidia-docker2
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
     sudo tee /etc/apt/sources.list.d/nvidia-docker.list
   sudo apt-get update && sudo apt-get install -y nvidia-docker2
   sudo systemctl restart docker
   ```

### Verify GPU Access

```bash
# Check GPU is available in container
docker-compose -f docker-compose.full.yml exec pipeline nvidia-smi

# Test PyTorch CUDA
docker-compose -f docker-compose.full.yml exec pipeline \
  python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check logs for errors
docker-compose -f docker-compose.full.yml logs [service-name]

# Rebuild specific service
docker-compose -f docker-compose.full.yml build --no-cache [service-name]
docker-compose -f docker-compose.full.yml up -d [service-name]
```

### Database Connection Errors

```bash
# Verify database is healthy
docker-compose -f docker-compose.full.yml exec db pg_isready -U matthew50

# Check database logs
docker-compose -f docker-compose.full.yml logs db

# Restart database
docker-compose -f docker-compose.full.yml restart db
```

### Pipeline Task Fails

```bash
# Check pipeline container is running
docker-compose -f docker-compose.full.yml ps pipeline

# View pipeline logs
docker-compose -f docker-compose.full.yml logs -f pipeline

# Test database connection from pipeline
docker-compose -f docker-compose.full.yml exec pipeline \
  python -c "from shared.database.database import health_check; print(health_check())"
```

### Out of Memory

```bash
# Check memory usage
docker stats

# Increase limits in docker-compose.full.yml
# Then rebuild
docker-compose -f docker-compose.full.yml up -d
```

### Port Already in Use

```bash
# Check what's using port 8000
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Change port in docker-compose.full.yml
ports:
  - "8080:8000"  # Map to different host port
```

---

## Maintenance

### Update Services

```bash
# Pull latest changes
git pull origin main

# Rebuild all services
docker-compose -f docker-compose.full.yml build --parallel

# Restart with new images
docker-compose -f docker-compose.full.yml up -d
```

### Clean Up

```bash
# Stop all services
docker-compose -f docker-compose.full.yml down

# Remove volumes (WARNING: deletes all data)
docker-compose -f docker-compose.full.yml down -v

# Clean up old images
docker image prune -a

# Full cleanup
docker system prune -a --volumes
```

### Backup Strategy

**Automated backup script:**

```bash
#!/bin/bash
BACKUP_DIR=./backups/$(date +%Y%m%d)
mkdir -p $BACKUP_DIR

# Database backup
docker-compose -f docker-compose.full.yml exec -T db \
  pg_dump -U matthew50 softpower-db | gzip > $BACKUP_DIR/database.sql.gz

# Export embeddings
docker-compose -f docker-compose.full.yml exec pipeline \
  python services/pipeline/embeddings/export_embeddings.py \
  --output-dir ./_data/exports/embeddings/$(date +%Y%m%d) \
  --include-event-summaries

# Sync to S3
aws s3 sync $BACKUP_DIR s3://your-bucket/backups/$(date +%Y%m%d)/
```

---

## Production Checklist

Before deploying to production:

- [ ] Set secure passwords in `.env`
- [ ] Configure SSL/TLS for HTTPS
- [ ] Set up automated backups
- [ ] Configure log rotation
- [ ] Set resource limits appropriately
- [ ] Enable monitoring (Prometheus/Grafana)
- [ ] Test disaster recovery procedure
- [ ] Document custom configuration
- [ ] Set up alerts for errors
- [ ] Review security settings

---

## See Also

- [DEPLOYMENT_OPTIONS.md](../../DEPLOYMENT_OPTIONS.md) - All deployment options
- [DOCKER_BUILD.md](DOCKER_BUILD.md) - Multi-stage build details
- [client/README.md](../../client/README.md) - Web app documentation
- [CURRENT_PIPELINE_SCRIPTS.md](../../CURRENT_PIPELINE_SCRIPTS.md) - Pipeline reference
