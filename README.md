# Soft Power Analytics Platform

Soft Power Analytics is a platform that ingests open source documents, runs AI/ML pipelines for event detection, entity resolution, and materiality scoring, then serves interactive analytics through FastAPI, React, and Streamlit.

## Architecture

```
client/            React + TypeScript frontend (Vite, served by FastAPI)
server/            FastAPI server (API + React UI + Chat/RAG + S3/Batch proxy)
services/
  dashboard/       Streamlit analytics dashboard
  chat/            RAG service (semantic search + LLM response generation)
  pipeline/        Data processing pipeline
    ingestion/       Document ingestion (atom.py, dsr.py)
    analysis/        AI analysis (atom_extraction.py)
    events/          Event clustering and consolidation
    entities/        Entity resolution
    embeddings/      Vector embeddings (pgvector)
    summaries/       Bilateral relationship summaries
shared/            SQLAlchemy models, DB/session management, config, utilities
docker/            Dockerfiles (registry, production, pgvector, dev)
scripts/           Deployment, testing, and utility scripts
alembic/           Database migrations
```

## Quick Start

### Docker Compose (Development)

```bash
cp .env.example .env                        # Configure credentials
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml --profile migrate up migrate
```

- React UI + API: http://localhost:8000
- Streamlit Dashboard: http://localhost:8501

### Production Deployment (Docker, No Compose)

Uses `scripts/docker/production-deploy.sh` — raw Docker commands, no compose required.
Supports both Docker Hub registry images and locally-built slim images.

```bash
# Fresh deploy from Docker Hub
./scripts/docker/production-deploy.sh start
./scripts/docker/production-deploy.sh migrate

# Or restore from a database backup
./scripts/docker/production-deploy.sh start
./scripts/docker/production-deploy.sh restore backup.dump
```

### Non-Docker (Bare Metal)

```bash
pip install -r requirements.txt
cd client && npm install && npm run build && cd ..
alembic upgrade head

# Start all services
./scripts/start_services.sh all          # Linux/macOS
.\scripts\start_services.ps1 -Service all  # Windows
```

See [SETUP_NON_DOCKER.md](docs/deployment/SETUP_NON_DOCKER.md) for full installation guide.

---

## Production Deploy Commands

All production Docker operations go through a single script:

```bash
./scripts/docker/production-deploy.sh <command>
```

| Command | Description |
|---|---|
| `start` | Start all services (DB + Redis + App) |
| `stop` | Stop all services (preserves data) |
| `restart` | Stop then start |
| `migrate` | Run Alembic migrations |
| `status` | Show container and image status |
| `backup [file]` | Create pg_dump backup |
| `restore <file>` | Restore from backup (replaces data) |
| `import <files\|dir>` | Import dump files additively (no drops) |
| `rebuild-db [file]` | Drop database, recreate schema, optionally restore |
| `psql [sql]` | Interactive psql or execute SQL |
| `logs [container]` | Tail container logs |
| `load [dir]` | Load images from tar files (airgap) |
| `setup` | Install ML wheels into slim image (one-time) |

### First-Time Deploy (Registry Images)

```bash
./scripts/docker/production-deploy.sh start
./scripts/docker/production-deploy.sh migrate
```

### First-Time Deploy (Airgap / Slim Images)

```bash
./scripts/docker/production-deploy.sh load ./images
./scripts/docker/production-deploy.sh setup
./scripts/docker/production-deploy.sh start
./scripts/docker/production-deploy.sh migrate
```

---

## Wipe and Rebuild (Enterprise)

For enterprise deployments where wiping and rebuilding is easier than maintaining migrations:

```bash
# Wipe everything, preserve user accounts (default)
./scripts/docker/production-wipe.sh

# Wipe everything including users
./scripts/docker/production-wipe.sh --wipe-users

# Skip confirmation prompt (scripting)
./scripts/docker/production-wipe.sh --yes
```

The wipe script:
1. Creates a safety backup before destroying anything
2. Exports users table (unless `--wipe-users`)
3. Stops and removes all containers
4. Destroys the database volume
5. Starts a fresh DB, runs migrations, restores users
6. Stops DB so `production-deploy.sh start` manages the full stack

After wipe, deploy normally:

```bash
./scripts/docker/production-deploy.sh start
# Schema + users already in place; import data:
./scripts/docker/production-deploy.sh restore backup.dump
```

---

## Database Export and Import

### Option 1: pg_dump (Binary, Includes Embeddings)

```bash
# Export — single file
python scripts/db_export.py --output-dir ./db_export --single-file

# Export — chunked (default 750MB chunks, good for large DBs / transfer)
python scripts/db_export.py --output-dir ./db_export

# Export from Docker container
python scripts/db_export.py --output-dir ./db_export --docker-container

# Import via production-deploy.sh
./scripts/docker/production-deploy.sh restore ./db_export/chunk_001.dump
# Or for chunked exports:
./scripts/docker/production-deploy.sh import ./db_export/

# Import directly
python scripts/db_import.py --input-dir ./db_export
```

### Option 2: CSV (Human-Readable, Embeddings Separate)

```bash
# Export all tables to CSV (skips embedding tables by default)
python scripts/db_export_csv.py --output-dir ./db_csv_export

# Include embeddings (large!)
python scripts/db_export_csv.py --output-dir ./db_csv_export --include-embeddings

# Export from Docker container
python scripts/db_export_csv.py --output-dir ./db_csv_export --docker-container

# Import
python scripts/db_import_csv.py --input-dir ./db_csv_export --docker-container
```

### Embeddings (Parquet Backup — Fast Restore)

CSV export skips embedding tables by default. Use the dedicated Parquet system instead:

```bash
# Export (~45 hours of embeddings saved as Parquet files)
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./embedding_backups --include-event-summaries

# Restore (15-20 min vs 45 hours regeneration)
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./embedding_backups
```

---

## Ingestion Pipeline

Primary orchestrator: `services/run_ingestion_pipeline.py`

```bash
# Full pipeline
python services/run_ingestion_pipeline.py \
    --start-date 2026-02-18 --end-date 2026-02-24 --source local

# Run specific profiles
python services/run_ingestion_pipeline.py \
    --start-date 2026-02-18 --end-date 2026-02-24 --profile events

python services/run_ingestion_pipeline.py \
    --start-date 2026-02-18 --end-date 2026-02-24 --profile summaries

python services/run_ingestion_pipeline.py \
    --start-date 2026-02-18 --end-date 2026-02-24 --profile entities

# Dry run
python services/run_ingestion_pipeline.py \
    --start-date 2026-02-18 --end-date 2026-02-24 --dry-run
```

### Individual Pipeline Steps

```bash
# Document ingestion
python services/pipeline/ingestion/dsr.py --source local

# Embeddings
python services/pipeline/embeddings/embed_missing_documents.py --yes

# Event clustering
python services/pipeline/events/batch_cluster_events.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# LLM event deconfliction
python services/pipeline/events/llm_deconflict_clusters.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# Cross-date consolidation
python services/pipeline/events/consolidate_all_events.py --influencers
python services/pipeline/events/llm_deconflict_canonical_events.py --influencers
python services/pipeline/events/merge_canonical_events.py --influencers

# Bilateral summaries
python services/pipeline/summaries/generate_bilateral_summaries.py \
    --init-country China --recipient-country Egypt
```

---

## Preprocessing Container

For running pipeline scripts in an isolated container without the full web stack:

```bash
# Build
docker build -f docker/preprocessing.Dockerfile -t softpower-preprocessing:latest .

# Run as persistent worker
docker run -d --name sp-preprocess \
    --restart unless-stopped \
    --env-file .env.docker \
    -v "${PWD}/data:/app/data" \
    -v "${PWD}/_data:/app/_data" \
    softpower-preprocessing:latest \
    sleep infinity

# Execute pipeline commands
docker exec -it sp-preprocess python services/pipeline/ingestion/dsr.py --source local
docker exec -it sp-preprocess python services/pipeline/embeddings/embed_missing_documents.py --yes
docker exec -it sp-preprocess python services/pipeline/events/batch_cluster_events.py \
    --country Iran --start-date 2026-02-18 --end-date 2026-02-24
```

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `POSTGRES_USER` | Database username |
| `POSTGRES_PASSWORD` | Database password |
| `POSTGRES_DB` | Database name |
| `DB_HOST` | Database host (`localhost` or container name) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `DB_PORT` | `5432` | Database port |
| `API_PORT` | `8000` | FastAPI port |
| `STREAMLIT_PORT` | `8501` | Streamlit port |
| `JWT_SECRET` | built-in default | JWT signing key (min 32 chars, change for production) |
| `JWT_EXPIRATION_HOURS` | `24` | Token lifetime |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `CLAUDE_KEY` | — | API key for LLM chat/RAG |
| `AWS_ACCESS_KEY_ID` | — | AWS credentials for S3 |
| `AWS_SECRET_ACCESS_KEY` | — | AWS credentials for S3 |
| `LLM_PROXY_PORT` | `7001` | Host-side LLM/S3 proxy port (0 to disable) |
| `DOCKER_ENV` | — | Set `true` inside containers |

Docker containers detect their environment automatically via `DOCKER_ENV=true`. When running outside Docker, values come from `.env`.

---

## Database

### Connection

```bash
# Docker production
./scripts/docker/production-deploy.sh psql

# Docker compose dev
docker exec -it softpower_db psql -U $POSTGRES_USER -d $POSTGRES_DB

# Local
psql -h localhost -U $POSTGRES_USER -d $POSTGRES_DB
```

### Migrations

```bash
# Apply migrations
alembic upgrade head

# Create new migration after model changes
alembic revision --autogenerate -m "description"

# Docker production
./scripts/docker/production-deploy.sh migrate
```

### Health Check

```python
from shared.database.database import health_check, get_pool_status
print("Connected" if health_check() else "Failed")
print(get_pool_status())
```

---

## Troubleshooting

**Container cannot reach DB** (`localhost` connection refused):
- Inside a container, `localhost` means the container itself
- Use `host.docker.internal` (host DB) or the container name (compose DB)

**Port already in use:**
- Change ports in `.env`: `API_PORT=5002`, `STREAMLIT_PORT=8502`

**Module import errors:**
- Ensure you're in the project root with venv activated
- All imports use `shared.` prefix (e.g., `from shared.database.database import get_session`)

---

## Documentation

| Document | Description |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Complete architecture and development guide |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Quick deployment guide |
| [docs/DOCKERHUB_README.md](docs/DOCKERHUB_README.md) | Docker Hub image documentation |
| [DOCKER_WORKFLOW.md](DOCKER_WORKFLOW.md) | Docker workflow and build guide |
| [docs/deployment/SETUP_NON_DOCKER.md](docs/deployment/SETUP_NON_DOCKER.md) | Non-Docker installation |
