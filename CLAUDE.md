# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development Server
```bash
# Run Streamlit dashboard (local development)
cd streamlit
streamlit run app.py

# Run via Docker (full stack)
docker-compose up -d

# Test database connection
python test_db.py
```

### Database Management
```bash
# Initialize database (creates all tables)
python -c "from backend.database import init_database; init_database()"

# Run Alembic migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Database health check
python -c "from backend.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"

# View connection pool status
python -c "from backend.database import get_pool_status; print(get_pool_status())"
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

### Backend Processing Scripts
```bash
# Run individual processing scripts
python backend/scripts/atom.py                # Document ingestion
python backend/scripts/atom_extraction.py     # AI analysis
python backend/scripts/daily.py               # Daily summaries
python backend/scripts/cluster_events.py      # Event clustering
python backend/scripts/embeddings.py          # Generate embeddings

# S3 document processing (JSON files)
python backend/scripts/dsr.py                 # Process JSON files from S3
python backend/scripts/dsr.py --status        # Check processing status
python backend/scripts/dsr.py --no-embed      # Process without embeddings

# FastAPI server (for S3 operations, runs on host)
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload

# S3 to pgvector migration (automatically skips processed files)
python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/ --collection chunk_embeddings
python backend/scripts/s3_to_pgvector.py --dry-run     # Test without writing
python backend/scripts/s3_to_pgvector.py --force       # Reprocess all files
python backend/scripts/s3_to_pgvector.py view chunk_embeddings      # View processed files
python backend/scripts/s3_to_pgvector.py reset chunk_embeddings --confirm  # Reset tracker
```

## Architecture

### High-Level Overview
This is a **Soft Power Analytics Dashboard** that processes diplomatic documents through an AI/ML pipeline and provides interactive visualizations. The system analyzes international relations documents to identify patterns, events, and trends in soft power activities.

**Data Flow**: S3 Raw Documents → Document Ingestion → AI Analysis → Event Detection → Clustering → Vector Embeddings → Dashboard Visualization

### Technology Stack
- **Backend**: SQLAlchemy 2.0 with sophisticated connection pooling, FastAPI for S3 operations
- **Database**: PostgreSQL with pgvector extension for embeddings
- **Frontend**: Streamlit for interactive dashboards
- **AI/ML**: OpenAI GPT models (via `CLAUDE_KEY`), sentence-transformers, HDBSCAN clustering
- **Infrastructure**: Docker Compose stack, Alembic migrations, Redis (for future Celery tasks)
- **Storage**: AWS S3 for raw documents and embeddings (via boto3)

### Docker Architecture

The application runs as a multi-container Docker stack:

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Network: softpower_net             │
├─────────────────────────────────────────────────────────────┤
│  streamlit-app (port 8501)                                   │
│  └─> Streamlit dashboard                                     │
│                                                               │
│  ml-backend (port 8000)                                      │
│  └─> FastAPI + processing scripts                            │
│                                                               │
│  softpower_db (port 5433→5432)                              │
│  └─> PostgreSQL + pgvector                                   │
│                                                               │
│  redis (internal)                                            │
│  └─> Redis cache/queue                                       │
└─────────────────────────────────────────────────────────────┘
         ↑                                    ↑
    Host Machine                      Host: FastAPI Server
  (port 5001, optional)              (for local S3 access)
```

**Key Points**:
- PostgreSQL exposed on host port 5433 (to avoid conflicts with local PostgreSQL on 5432)
- Backend uses `host.docker.internal` to access host-based FastAPI S3 proxy (port 5001)
- Shared network `softpower_net` allows inter-container communication
- Volume `postgres_data` persists database data

### Database Architecture

**Modern SQLAlchemy 2.0 Setup**: The project recently migrated from Flask-SQLAlchemy to pure SQLAlchemy 2.0 with centralized connection management in `backend/database.py`.

**Core Entity**: `Document` - Central table containing diplomatic documents with AI-generated analysis

**Normalized Relationships** (many-to-many):
- `categories` / `subcategories` - Document classification
- `initiating_countries` / `recipient_countries` - Geographic relationships
- `projects` - Associated initiatives
- `citations` - Source citations

**Consolidated Event Models** (`backend/models_consolidated.py`):
- `EventSummary` - Unified event summaries with `period_type` enum (daily/weekly/monthly/yearly)
- `PeriodSummary` - Aggregated summaries across all events for a time period
- `EventSourceLink` - Traceability linking events to source documents

**Legacy Event Tables**: The system is transitioning from separate `daily_events`, `weekly_events`, etc. tables to the consolidated `event_summaries` table. Some scripts may still reference the old schema.

**LangChain Integration**:
- `langchain_pg_collection` - Vector store collections
- `langchain_pg_embedding` - Document embeddings for semantic search

### Processing Pipeline Architecture

1. **Document Ingestion** (`atom.py`): Imports raw documents from various sources
2. **AI Analysis** (`atom_extraction.py`): GPT-4 extracts salience, categories, countries, projects, locations
3. **Event Detection** (`daily.py`): Groups related documents into daily events
4. **Clustering** (`cluster_events.py`): Uses embeddings + HDBSCAN to identify event clusters across time
5. **Summarization** (`event_summary.py`): Generates human-readable event descriptions
6. **Embedding Generation** (`embeddings.py`, `embed_daily_summaries.py`): Creates vector representations
7. **S3 Migration** (`s3_to_pgvector.py`): Populates pgvector from S3 parquet files
8. **Dashboard** (`streamlit/app.py`): Streamlit visualization of trends and patterns

### Configuration Management

**Primary Config**: `backend/config.yaml` - Central configuration for all processing parameters
- Database paths and credentials
- AI model settings (GPT models via `aws.default_model`)
- Processing thresholds and date ranges
- Country/category taxonomies
- Clustering parameters (eps, min_samples, threshold)

**Environment Variables**: `.env` file for sensitive data
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_HOST`, `DB_PORT`
- `CLAUDE_KEY` (for OpenAI API access)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (for S3)
- `API_URL` (FastAPI endpoint for S3 operations)
- Database tuning: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`

## Development Patterns

### Database Session Management

The project uses SQLAlchemy 2.0 with a sophisticated `DatabaseManager` class in `backend/database.py`:

```python
# Preferred: Context manager (auto-commit/rollback)
from backend.database import get_session

with get_session() as session:
    documents = session.query(Document).filter(...).all()
    # Automatic commit on success, rollback on exception

# Alternative: Manual session management (not recommended)
from backend.database import create_session

session = create_session()
try:
    # operations
    session.commit()
except Exception:
    session.rollback()
finally:
    session.close()

# Decorator pattern for functions
from backend.database import with_session

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

**Important**: The codebase is mid-migration from Flask-SQLAlchemy to pure SQLAlchemy 2.0:
- **Old pattern**: `backend/scripts/models.py` (Flask-SQLAlchemy models, being phased out)
- **New pattern**: `backend/models.py` and `backend/models_consolidated.py` (Modern SQLAlchemy 2.0)
- When writing new code, always use `backend/models.py` or `backend/models_consolidated.py`

### Script Execution Patterns

Backend processing scripts follow a consistent pattern:

```python
def main():
    with get_session() as session:
        # Load config
        config = load_yaml_config('backend/config.yaml')

        # Process data
        results = process_documents(session, config)

        # Auto-commit via context manager

if __name__ == "__main__":
    main()
```

### Configuration Access

```python
import yaml

with open('backend/config.yaml', 'r') as f:
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
from backend.models_consolidated import EventSummary, PeriodType

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

1. **FastAPI Server** (`backend/api.py`): Runs on host with AWS credentials, provides S3 proxy endpoints
2. **API Client** (`backend/api_client.py`): Used by scripts to access S3 via FastAPI

```python
from backend.api_client import get_s3_api_client

# Initialize client
client = get_s3_api_client()  # Auto-detects API_URL from env

# List parquet files
files = client.list_parquet_files(
    bucket='morris-sp-bucket',
    prefix='embeddings/',
    max_keys=1000
)

# Download parquet as DataFrame
df = client.download_parquet_as_dataframe(
    bucket='morris-sp-bucket',
    key='embeddings/chunk_2024-08-01.parquet'
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
1. Update the model in `backend/models.py` or `backend/models_consolidated.py`
2. Run `alembic revision --autogenerate -m "description"`
3. Review the generated migration file for correctness
4. Test migration with `alembic upgrade head`
5. Update any related prompts in `backend/scripts/prompts.py`
6. Modify extraction/processing scripts to handle the new field

### Performance Considerations

**Database Queries**:
- Use `session.execute()` with raw SQL for complex analytical queries
- Batch operations: `session.bulk_insert_mappings()` or `session.bulk_update_mappings()`
- Avoid N+1 queries: use `joinedload()` or `selectinload()` for relationships
- Monitor pool status: `from backend.database import get_pool_status; print(get_pool_status())`

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
# Install Python dependencies
pip install -r requirements.txt
pip install -r backend/requirements.txt

# Set up environment variables
cp .env.example .env  # Edit with your credentials

# Option 1: Docker setup (recommended)
docker-compose up -d
docker-compose --profile migrate up  # Run migrations

# Option 2: Local setup
# Start PostgreSQL with pgvector (via Docker)
docker-compose up -d db

# Initialize database
python -c "from backend.database import init_database; init_database()"
alembic upgrade head

# Verify connection
python -c "from backend.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"

# Run Streamlit locally
cd streamlit
streamlit run app.py
```

### Testing Database Connection

```python
# Quick health check
from backend.database import health_check, get_pool_status

if health_check():
    print("✅ Database connected")
    print(f"Pool status: {get_pool_status()}")
else:
    print("❌ Database connection failed")

# Query example
from backend.database import get_session
from backend.models import Document

with get_session() as session:
    count = session.query(Document).count()
    print(f"Total documents: {count}")
```

## Common Development Tasks

### Adding New Document Fields

1. Update model in `backend/models.py`:
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

4. Update extraction logic in `backend/scripts/atom_extraction.py`

5. Update prompts if needed in `backend/scripts/prompts.py`

### Adding New Dashboard Pages

1. Create page in `streamlit/pages/NewPage.py`:
   ```python
   import streamlit as st
   from queries.document_queries import my_new_query
   from charts.document_charts import my_new_chart

   st.title("New Page")
   data = my_new_query()
   st.altair_chart(my_new_chart(data))
   ```

2. Add query function in `streamlit/queries/document_queries.py`

3. Add chart function in `streamlit/charts/document_charts.py`

4. Page automatically appears in Streamlit sidebar navigation

### Working with Event Summaries

The consolidated event summary model supports multiple time periods:

```python
from backend.models_consolidated import EventSummary, PeriodType, EventStatus
from backend.database import get_session

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
from backend.database import get_pool_status
print(get_pool_status())

# Force reconnection
from backend.database import db_manager
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
docker-compose logs -f backend      # FastAPI logs
docker-compose logs -f streamlit    # Streamlit logs
docker-compose logs -f db           # PostgreSQL logs
```
