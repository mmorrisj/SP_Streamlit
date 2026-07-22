# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development Server

**Option 1: Docker (Recommended for Development)**
```bash
# Start full stack (Streamlit, FastAPI, PostgreSQL, Redis) using the
# zero-prerequisite default compose file. Requires a populated .env
# (copy .env.example). See docs/DEMO_RUNBOOK.md for the full walkthrough.
docker compose up -d --build

# Test database connection
python -c "from shared.database.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"
```

> **Compose files:** `docker-compose.yml` is the default dev/demo stack
> (Compose-managed volume + network, no pre-steps). `docker-compose.dev.yml`
> mirrors production with external volume/network for debugging;
> `docker-compose.production.yml` is the enterprise/hardened-daemon stack
> (see `PRODUCTION_DOCKER_RUN.md`). Older `docker-compose` (v1) also works.

### Database Management
```bash
# Initialize database (creates all tables)
python -c "from shared.database.database import init_database; init_database()"

# Run Alembic migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Database health check
python -c "from shared.database.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"

# View connection pool status
python -c "from shared.database.database import get_pool_status; print(get_pool_status())"
```

### Docker Commands
```bash
# Start full stack (Streamlit, FastAPI, PostgreSQL, Redis)
docker-compose up -d

# Run migrations via Docker
docker-compose --profile migrate up

# Stop services
docker-compose down

# View logs
docker-compose logs -f [service-name]

# Connect to PostgreSQL container
docker exec -it softpower_db psql -U $POSTGRES_USER -d $POSTGRES_DB
```

### Pipeline Processing Scripts
```bash
# Document ingestion
# Raw ATOM CSV exports: salience gate + initial extraction -> results.json + Postgres
python services/pipeline/ingestion/atom_pipeline.py export.csv
python services/pipeline/ingestion/atom_pipeline.py export.csv --status     # Counts only
python services/pipeline/ingestion/atom_pipeline.py export.csv --dry-run    # No DB writes
# Pre-extracted DSR JSON exports
python services/pipeline/ingestion/dsr.py                 # Process JSON files from S3
python services/pipeline/ingestion/dsr.py --status        # Check processing status
python services/pipeline/ingestion/dsr.py --no-embed      # Process without embeddings

# AI analysis
python services/pipeline/analysis/phase0_event_analysis.py  # Event analysis

# Event Processing Pipeline

## Daily Processing (Stage 1)
# Cluster same-day events using DBSCAN + embeddings
python services/pipeline/events/batch_cluster_events.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# LLM validates clusters and creates canonical_events
python services/pipeline/events/llm_deconflict_clusters.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

## Batch Consolidation (Stage 2) - Run periodically across entire dataset
# Groups canonical events using embedding similarity
python services/pipeline/events/consolidate_all_events.py --influencers

# LLM validates consolidation, picks best names, splits incorrect groups
python services/pipeline/events/llm_deconflict_canonical_events.py --influencers

# Consolidates daily_event_mentions into multi-day events
python services/pipeline/events/merge_canonical_events.py --influencers

# Bilateral Relationship Summaries
python services/pipeline/summaries/generate_bilateral_summaries.py \
    --init-country China --recipient-country Egypt         # Generate specific pair

python services/pipeline/summaries/generate_bilateral_summaries.py \
    --init-country China --min-docs 500                    # All recipients for China (≥500 docs)

python services/pipeline/summaries/generate_bilateral_summaries.py \
    --all --min-docs 1000                                  # All major pairs (≥1000 docs)

python services/pipeline/summaries/generate_bilateral_summaries.py \
    --init-country China --recipient-country Egypt --regenerate  # Update existing summary

# Public Economic Data (World Bank WDI + IMF DOTS)
# Country-level indicators (GDP, FDI, trade share, remittances, population)
python services/pipeline/ingestion/wdi.py                 # Fetch + upsert
python services/pipeline/ingestion/wdi.py --dry-run       # Fetch/parse only
python services/pipeline/ingestion/wdi.py --status        # Coverage report
# Bilateral trade (influencer -> recipient exports/imports, IMF SDMX API)
# Optional: set IMF_API_KEY in .env for higher rate limits
python services/pipeline/ingestion/imf_dots.py            # Annual by default
python services/pipeline/ingestion/imf_dots.py --frequency M --start-year 2020
python services/pipeline/ingestion/imf_dots.py --status
# Both write to the economic_indicators table (see economic_data in
# shared/config/config.yaml for indicator lists and endpoints); re-runs
# upsert in place. Query helpers: services/dashboard/queries/economic_queries.py

# Embeddings - Generation
python services/pipeline/embeddings/embed_missing_documents.py                    # Embed documents
python services/pipeline/embeddings/embed_missing_documents.py --status           # Check status
python services/pipeline/embeddings/embed_event_summaries.py --yes                # Embed event summaries
python services/pipeline/embeddings/embed_event_summaries.py --status             # Check event embedding status

# Embeddings - Backup & Restore (FAST - recommended for database rebuilds)
# Export all embeddings (saves ~45 hours of regeneration time!)
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./embedding_backups/$(date +%Y%m%d) \
    --include-event-summaries

# Restore embeddings from backup (15-20 minutes vs 45 hours regeneration)
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./embedding_backups/20241106

# Export to S3 for long-term storage
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./embedding_backups/$(date +%Y%m%d) \
    --include-event-summaries \
    --s3-bucket your-bucket \
    --s3-prefix embeddings/backup/$(date +%Y%m%d)/

# Restore from S3
python services/pipeline/embeddings/import_embeddings.py \
    --s3-bucket your-bucket \
    --s3-prefix embeddings/backup/20241106/

# See services/pipeline/embeddings/README_BACKUP_RESTORE.md for full documentation

# FastAPI server (for S3 operations, runs on host)
uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload
```

## Architecture

### High-Level Overview
This is a **Soft Power Analytics Dashboard** that processes diplomatic documents through an AI/ML pipeline and provides interactive visualizations. The system analyzes international relations documents to identify patterns, events, and trends in soft power activities.

**Data Flow**: S3 Raw Documents → Document Ingestion → AI Analysis → Event Detection → Clustering → Vector Embeddings → Dashboard Visualization

### Technology Stack
- **Backend**: SQLAlchemy 2.0 with sophisticated connection pooling, FastAPI for API and static file serving
- **Database**: PostgreSQL with pgvector extension for embeddings
- **Frontend**:
  - **React + TypeScript + Vite** - Modern web interface (primary UI at client/)
  - **Streamlit** - Analytics and data exploration dashboard (services/dashboard/)
- **AI/ML**: OpenAI GPT models (via `CLAUDE_KEY`), sentence-transformers, HDBSCAN clustering
- **Infrastructure**: Docker Compose stack (optional), Alembic migrations, Redis (for future Celery tasks)
- **Storage**: AWS S3 for raw documents and embeddings (via boto3)

### Directory Structure

The project is organized into a **service-oriented monorepo** with clear separation of concerns:

```
SP_Streamlit/
├── client/                      # React frontend (Vite + TypeScript)
│   ├── src/                    # React source code
│   │   ├── pages/             # Page components
│   │   ├── components/        # Reusable components
│   │   ├── services/          # API client services
│   │   ├── hooks/             # React hooks
│   │   └── App.tsx            # Main app component
│   ├── dist/                  # Production build output (created by npm run build)
│   ├── package.json           # Node.js dependencies
│   ├── vite.config.ts         # Vite configuration
│   └── tsconfig.json          # TypeScript configuration
│
├── server/                      # Consolidated FastAPI server
│   ├── main.py                # FastAPI: React UI + API + Chat/RAG + S3/Batch proxy
│   ├── report_generator.py    # Report generation logic
│   └── report_exporter.py     # Word document export
│
├── services/                    # Application services
│   ├── chat/                   # Chat/RAG service
│   │   └── rag_service.py     # Semantic search + LLM response generation
│   │
│   ├── dashboard/              # Streamlit analytics dashboard
│   │   ├── app.py             # Main dashboard app
│   │   ├── pages/             # Dashboard pages
│   │   ├── queries/           # Database queries
│   │   └── charts/            # Chart components
│   │
│   └── pipeline/               # Data processing pipeline
│       ├── ingestion/         # Document ingestion (atom_pipeline.py, dsr.py)
│       ├── analysis/          # AI analysis (phase0_event_analysis.py)
│       ├── events/            # Event processing (news_event_tracker.py)
│       ├── embeddings/        # Vector embeddings (s3_to_pgvector.py)
│       ├── migrations/        # Data migrations
│       └── diagnostics/       # Diagnostic tools
│
├── shared/                     # Shared code across all services
│   ├── models/                # SQLAlchemy models
│   │   └── models.py          # Database models (was backend/models.py)
│   ├── database/              # Database connection management
│   │   └── database.py        # Connection pooling (was backend/database.py)
│   ├── config/                # Configuration
│   │   ├── config.yaml        # Main config file
│   │   └── config.py          # Config helpers
│   └── utils/                 # Shared utilities
│       ├── utils.py           # Common utilities
│       └── prompts.py         # LLM prompts
│
├── docker/                     # Docker configurations
│   ├── registry.Dockerfile    # Production consolidated app (Docker Hub)
│   ├── pgvector.Dockerfile    # Custom pgvector database image
│   ├── api.Dockerfile         # Dev API service Dockerfile
│   ├── dashboard.Dockerfile   # Dev dashboard Dockerfile
│   └── supervisord.conf       # Process manager config
│
├── scripts/                    # All installation and deployment scripts
│   ├── run_tests.sh/ps1       # Test runner scripts
│   └── docker/                # Docker-specific scripts
│       ├── production-deploy.sh # Production deployment script
│       ├── push-to-registry.sh # Registry push
│
├── alembic/                    # Database migrations
├── docker-compose.yml          # Docker orchestration
├── requirements.txt            # Unified Python dependencies
├── QUICKSTART.md               # Quick start guide
└── CLAUDE.md                   # This file
```

**Migration Notes**:
- All `backend/` code has been reorganized into `services/` and `shared/`
- Old imports like `from backend.database import` → `from shared.database.database import`
- Old imports like `from backend.scripts.utils import` → `from shared.utils.utils import`
- Docker services renamed: `backend` → `api`, `streamlit` → `dashboard`
- All services share the same `requirements.txt` at the root level

### Docker Architecture

The application runs as a multi-container Docker stack:

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Network: softpower_net             │
├─────────────────────────────────────────────────────────────┤
│  streamlit-dashboard (port 8501)                             │
│  └─> services/dashboard → Streamlit UI                       │
│                                                               │
│  api-service (port 8000)                                     │
│  └─> server/main.py → React UI + API + Chat/RAG              │
│                                                               │
│  softpower_db (port 5432)                                    │
│  └─> PostgreSQL + pgvector                                   │
│                                                               │
│  redis (internal)                                            │
│  └─> Redis cache/queue                                       │
└─────────────────────────────────────────────────────────────┘
         ↑
    Host Machine (port 5001)
    └─> server/main.py (S3/Batch/LLM proxy for Docker containers)
```

**Key Points**:
- PostgreSQL exposed on host port 5432
- Docker api-service runs `server/main.py` on port 8000
- Host runs same `server/main.py` on port 5001 for S3/Batch/LLM proxy (Docker uses `host.docker.internal:5001`)
- Shared network `softpower_net` allows inter-container communication
- Volume `postgres_data` persists database data

### Deployment

The project deploys via Docker with `DOCKER_ENV=true` environment variable:
- All services run in containers
- Database host: `softpower_db` (container name)
- API URL: `http://host.docker.internal:5001`
- Start with: `docker-compose up -d`

**Environment Variable Hierarchy**:
```
1. Docker: docker-compose.yml overrides (DB_HOST=softpower_db, DOCKER_ENV=true)
2. .env file values (fallback)
3. Code defaults: Hardcoded fallbacks in shared/database/database.py
```

### Database Architecture

**Modern SQLAlchemy 2.0 Setup**: The project uses pure SQLAlchemy 2.0 with centralized connection management in `shared/database/database.py`.

**Core Entity**: `Document` - Central table containing diplomatic documents with AI-generated analysis

**Normalized Relationships** (many-to-many):
- `categories` / `subcategories` - Document classification
- `initiating_countries` / `recipient_countries` - Geographic relationships
- `projects` - Associated initiatives
- `citations` - Source citations

**Consolidated Event Models** (`shared/models/models.py`):
- `EventSummary` - Unified event summaries with `period_type` enum (daily/weekly/monthly/yearly)
- `PeriodSummary` - Aggregated summaries across all events for a time period
- `EventSourceLink` - Traceability linking events to source documents

**Legacy Event Tables**: The system is transitioning from separate `daily_events`, `weekly_events`, etc. tables to the consolidated `event_summaries` table. Some scripts may still reference the old schema.

**LangChain Integration**:
- `langchain_pg_collection` - Vector store collections
- `langchain_pg_embedding` - Document embeddings for semantic search

### Processing Pipeline Architecture

1. **Document Ingestion** (`services/pipeline/ingestion/`): Imports raw documents from various sources
2. **AI Analysis** (`services/pipeline/analysis/`): GPT-4 extracts salience, categories, countries, projects, locations
3. **Event Processing** (`services/pipeline/events/`): Groups related documents into events and tracks news
4. **Embedding Generation** (`services/pipeline/embeddings/`): Creates vector representations and syncs with S3
5. **Dashboard** (`services/dashboard/`): Streamlit visualization of trends and patterns

### Event Processing: Two-Stage Architecture

The event processing pipeline uses a **two-stage batch consolidation approach**:

**Stage 1: Daily Event Detection**
1. `batch_cluster_events.py` - Clusters raw events per day using DBSCAN + embeddings
   - Creates `event_clusters` table with batch numbers
   - Groups similar events happening on the same day
   - Does NOT link across days (by design)

2. `llm_deconflict_clusters.py` - LLM validates and refines clusters
   - Creates `canonical_events` (one per unique event per day)
   - Creates `daily_event_mentions` (links events to source documents)
   - Generates embeddings for each canonical event

**Stage 2: Batch Consolidation (Across All Dates)**
3. `consolidate_all_events.py` - Groups canonical events across entire dataset
   - Uses embedding similarity (cosine ≥0.85)
   - Sets `master_event_id` to create event hierarchy
   - Master events: `master_event_id IS NULL`
   - Child events: `master_event_id = master.id`

4. `llm_deconflict_canonical_events.py` - LLM validates consolidation
   - Verifies grouped events represent same real-world event
   - Picks best canonical name
   - Splits incorrectly merged groups

5. `merge_canonical_events.py` - Creates multi-day events
   - Consolidates `daily_event_mentions` from child to master events
   - Deletes empty child canonical events
   - Result: Master events span multiple days

**Why Two Stages?**
- Daily clustering handles day-to-day event detection
- Batch consolidation has full dataset context for better temporal linking
- LLM validation at both stages ensures quality
- Separation of concerns: real-time processing vs. comprehensive consolidation

**Traceability**: All events can be linked back to original documents via `daily_event_mentions` → `documents`

### Configuration Management

**Primary Config**: `shared/config/config.yaml` - Central configuration for all processing parameters
- Database paths and credentials
- AI model settings (GPT models via `aws.default_model`)
- Processing thresholds and date ranges
- Country/category taxonomies
- Clustering parameters (eps, min_samples, threshold)
- S3 bucket and prefix configuration (see below)

**S3 Configuration** (in `shared/config/config.yaml`):
```yaml
s3:
  bucket: "your-bucket-name"      # S3 bucket name
  region: "us-east-1"             # AWS region
  prefixes:
    dsr_extracts: "dsr_extracts/" # Document extracts
    embeddings: "embeddings/"      # Embedding backups
    exports: "exports/"            # Data exports
    backups: "backups/"            # General backups
```

Environment variable overrides:
- `S3_BUCKET` - Overrides `s3.bucket` from config
- `S3_REGION` - Overrides `s3.region` from config

**Environment Variables**: `.env` file for sensitive data
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_HOST`, `DB_PORT`
- `CLAUDE_KEY` (for OpenAI API access)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (for S3)
- `API_URL` (FastAPI endpoint for S3 operations)
- `S3_BUCKET`, `S3_REGION` (optional S3 overrides)
- Database tuning: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`

## Development Patterns

### Database Session Management

The project uses SQLAlchemy 2.0 with a sophisticated `DatabaseManager` class in `shared/database/database.py`:

```python
# Preferred: Context manager (auto-commit/rollback)
from shared.database.database import get_session

with get_session() as session:
    documents = session.query(Document).filter(...).all()
    # Automatic commit on success, rollback on exception

# Alternative: Manual session management (not recommended)
from shared.database.database import create_session

session = create_session()
try:
    # operations
    session.commit()
except Exception:
    session.rollback()
finally:
    session.close()

# Decorator pattern for functions
from shared.database.database import with_session

@with_session
def process_documents(session, doc_ids):
    # session is automatically provided
    return session.query(Document).filter(Document.doc_id.in_(doc_ids)).all()
```

**Connection Pooling**:
- Default pool size: 10 connections
- Max overflow: 20 additional connections
- Pool recycle: 3600 seconds (1 hour)
- Pre-ping enabled for connection health checks
- Configurable via environment variables

**Important**: All models are in `shared/models/models.py` - use this for all database operations

### Script Execution Patterns

Pipeline processing scripts follow a consistent pattern:

```python
from shared.database.database import get_session
from shared.utils.utils import Config

def main():
    with get_session() as session:
        # Load config
        config = Config.from_yaml('shared/config/config.yaml')

        # Process data
        results = process_documents(session, config)

        # Auto-commit via context manager

if __name__ == "__main__":
    main()
```

### Configuration Access

```python
import yaml

with open('shared/config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Common config sections:
start_date = config['start_date']                  # Processing start date
models = config['aws']['default_model']            # AI model configuration
countries = config['influencers']                  # Initiating countries
recipients = config['recipients']                  # Recipient countries
categories = config['categories']                  # Category taxonomy
cluster_eps = config['cluster']['eps']             # Clustering threshold
```

### Model Relationships

When working with normalized data, use SQLAlchemy relationships:

```python
# Get all categories for a document
doc = session.get(Document, doc_id)
categories = [cat.category for cat in doc.categories]

# Get all documents in a category using raw SQL
from sqlalchemy import text

docs = session.execute(
    text("SELECT d.* FROM documents d JOIN categories c ON d.doc_id = c.doc_id WHERE c.category = :cat"),
    {"cat": "Economic"}
).fetchall()

# Working with consolidated event summaries
from shared.models.models import EventSummary, PeriodType

daily_events = session.query(EventSummary).filter(
    EventSummary.period_type == PeriodType.DAILY,
    EventSummary.initiating_country == "China"
).all()

# Access event metadata via JSONB properties
for event in daily_events:
    categories = event.categories_list  # Property that extracts from JSONB
    recipients = event.recipients_list
    print(f"Event: {event.event_name}, Categories: {categories}")
```

### S3 Integration Pattern

S3 operations use a two-tier architecture:

1. **FastAPI Server** (`server/main.py`): Runs on host with AWS credentials, provides S3 proxy endpoints
2. **API Client**: Used by scripts to access S3 via FastAPI
3. **S3 Config** (`services/pipeline/embeddings/s3.py`): Provides config-based bucket/prefix helpers

```python
from services.pipeline.embeddings.s3 import get_bucket_name, get_s3_prefix
from services.pipeline.embeddings.s3 import get_s3_api_client

# Get bucket from config.yaml (or S3_BUCKET env var)
bucket = get_bucket_name()
prefix = get_s3_prefix('embeddings')  # Returns 'embeddings/' from config

# Initialize client
client = get_s3_api_client()  # Auto-detects API_URL from env

# List parquet files
files = client.list_parquet_files(
    bucket=bucket,
    prefix=prefix,
    max_keys=1000
)

# Download parquet as DataFrame
df = client.download_parquet_as_dataframe(
    bucket=bucket,
    key=f'{prefix}chunk_2024-08-01.parquet'
)
```

### Alembic Migrations

Alembic is configured to work with both local and Docker environments:

```bash
# Create a new migration after modifying models
alembic revision --autogenerate -m "add salience_bool column"

# Review the generated migration in alembic/versions/

# Apply migration (local)
alembic upgrade head

# Apply migration (Docker)
docker-compose --profile migrate up

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history

# View current version
alembic current
```

**Important**: When adding new model fields:
1. Update the model in `shared/models/models.py`
2. Run `alembic revision --autogenerate -m "description"`
3. Review the generated migration file for correctness
4. Test migration with `alembic upgrade head`
5. Update any related prompts in `shared/utils/prompts.py`
6. Modify extraction/processing scripts to handle the new field

### Performance Considerations

**Database Queries**:
- Use `session.execute()` with raw SQL for complex analytical queries
- Batch operations: `session.bulk_insert_mappings()` or `session.bulk_update_mappings()`
- Avoid N+1 queries: use `joinedload()` or `selectinload()` for relationships
- Monitor pool status: `from shared.database.database import get_pool_status; print(get_pool_status())`

**S3 Operations**:
- Use binary streaming for large parquet files
- Implement pagination when listing large S3 prefixes
- Local tracker files prevent duplicate processing

**Processing Scripts**:
- Adjust batch sizes based on available memory
- Use `--dry-run` flags to test without database writes
- Process embeddings separately during off-peak hours

### Environment Setup

```bash
# Set up environment variables
cp .env.example .env  # Edit with your credentials

# Docker setup
docker-compose up -d
docker-compose --profile migrate up  # Run migrations

# Verify connection
python -c "from shared.database.database import health_check; print('Connected' if health_check() else 'Failed')"
```

### Testing Database Connection

```python
# Quick health check
from shared.database.database import health_check, get_pool_status

if health_check():
    print("✅ Database connected")
    print(f"Pool status: {get_pool_status()}")
else:
    print("❌ Database connection failed")

# Query example
from shared.database.database import get_session
from shared.models.models import Document

with get_session() as session:
    count = session.query(Document).count()
    print(f"Total documents: {count}")
```

## Common Development Tasks

### Adding New Document Fields

1. Update model in `shared/models/models.py`:
   ```python
   class Document(Base):
       __tablename__ = "documents"
       # ... existing fields ...
       new_field: Mapped[str] = mapped_column(String, nullable=True)
   ```

2. Create Alembic migration:
   ```bash
   alembic revision --autogenerate -m "add new_field to documents"
   ```

3. Review and apply migration:
   ```bash
   # Review the file in alembic/versions/
   alembic upgrade head
   ```

4. Update extraction logic in `services/pipeline/ingestion/atom_pipeline.py` (ATOM CSV) or the upstream DSR prompt

5. Update prompts if needed in `shared/utils/prompts.py`

### Adding New Dashboard Pages

1. Create page in `services/dashboard/pages/NewPage.py`:
   ```python
   import streamlit as st
   from queries.document_queries import my_new_query
   from charts.document_charts import my_new_chart

   st.title("New Page")
   data = my_new_query()
   st.altair_chart(my_new_chart(data))
   ```

2. Add query function in `services/dashboard/queries/document_queries.py`

3. Add chart function in `services/dashboard/charts/document_charts.py`

4. Page automatically appears in Streamlit sidebar navigation

### Working with Event Summaries

The consolidated event summary model supports multiple time periods:

```python
from shared.models.models import EventSummary, PeriodType, EventStatus
from shared.database.database import get_session

with get_session() as session:
    # Query daily events
    daily_events = session.query(EventSummary).filter(
        EventSummary.period_type == PeriodType.DAILY,
        EventSummary.status == EventStatus.ACTIVE
    ).all()

    # Access JSONB data via properties
    for event in daily_events:
        print(f"Event: {event.event_name}")
        print(f"Categories: {event.categories_list}")
        print(f"Top sources: {event.get_top_sources(limit=5)}")
        print(f"Category breakdown: {event.get_category_percentage_breakdown()}")

    # Update counts (should be done after modifying count_by_* fields)
    event.update_basic_counts()
    session.commit()
```

### Debugging Tips

**Database connection issues**:
```python
# Check pool status
from shared.database.database import get_pool_status
print(get_pool_status())

# Force reconnection
from shared.database.database import db_manager
db_manager.recreate_connection()
```

**View SQL queries**:
```bash
# Set environment variable
export SQL_ECHO=true
export SQL_DEBUG=true  # For connection pool debugging
```

**Docker logs**:
```bash
docker-compose logs -f api           # FastAPI logs
docker-compose logs -f streamlit    # Streamlit logs
docker-compose logs -f db           # PostgreSQL logs
```
