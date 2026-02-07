# Pipeline Scripts Development Guide

**Last Updated**: 2025-10-22

⚠️ **NOTE**: The project has been refactored to a service-oriented architecture. This guide references `backend/` paths for historical compatibility, but new scripts should be placed in `services/pipeline/` and use `shared/` imports.

## Database Interaction Standards

All scripts MUST use modern SQLAlchemy 2.0 patterns with centralized database management. Legacy Flask-SQLAlchemy scripts have been archived.

## Required Patterns for New Scripts

### 1. Imports

```python
# Database connection (NEW LOCATION)
from shared.database.database import get_session, get_engine

# Models - Use shared models (NEW LOCATION)
from shared.models.models import (
    Document,
    Category,
    Subcategory,
    InitiatingCountry,
    RecipientCountry,
    CanonicalEvent,
    DailyEventMention,
    EventCluster
)

# Configuration
from shared.utils.utils import Config

# SQLAlchemy utilities
from sqlalchemy import text, select, func
from sqlalchemy.dialects.postgresql import insert
```

### 2. Session Management

**ALWAYS use the context manager pattern**:

```python
def process_data():
    with get_session() as session:
        # Query data
        documents = session.query(Document).filter(
            Document.date == target_date
        ).all()

        # Process data
        for doc in documents:
            # ... processing logic ...
            pass

        # Commit is automatic on success
        # Rollback is automatic on exception
```

**NEVER use**:
```python
# ❌ DON'T USE - Legacy Flask pattern
from backend.app import app
from backend.extensions import db

with app.app_context():
    docs = db.session.query(Document).all()
```

### 3. Database Configuration

**Use environment variables** (automatically loaded from `.env` by `shared/database/database.py`):

```python
# ✅ CORRECT - No hardcoding needed
with get_session() as session:
    # Connection is automatically configured from environment
    # Supports both Docker and local development
    pass
```

**Connection is managed centrally with**:
- Pool size: 10 connections
- Max overflow: 20 connections
- Pool recycle: 3600 seconds
- Pre-ping enabled for connection health

**NEVER hardcode**:
```python
# ❌ DON'T USE - Breaks portability
os.environ["DB_HOST"] = "localhost"
DATABASE_URL = "postgresql://user:pass@localhost:5432/db"
```

### 4. Querying Relationship Tables

**Use normalized tables to avoid Cartesian products**:

```python
def get_document_with_relationships(doc_id: str):
    with get_session() as session:
        # Get the document
        doc = session.query(Document).filter(
            Document.doc_id == doc_id
        ).first()

        # Get categories separately
        categories = session.query(Category.category).filter(
            Category.doc_id == doc_id
        ).all()

        # Get subcategories separately
        subcategories = session.query(Subcategory.subcategory).filter(
            Subcategory.doc_id == doc_id
        ).all()

        # Get initiating countries separately
        initiating_countries = session.query(InitiatingCountry.initiating_country).filter(
            InitiatingCountry.doc_id == doc_id
        ).all()

        # Get recipient countries separately
        recipient_countries = session.query(RecipientCountry.recipient_country).filter(
            RecipientCountry.doc_id == doc_id
        ).all()

        return {
            'document': doc,
            'categories': [c[0] for c in categories],
            'subcategories': [s[0] for s in subcategories],
            'initiating_countries': [i[0] for i in initiating_countries],
            'recipient_countries': [r[0] for r in recipient_countries]
        }
```

**NEVER do this**:
```python
# ❌ DON'T USE - Creates Cartesian products
docs = session.query(Document)\
    .join(Category)\
    .join(Subcategory)\
    .join(InitiatingCountry)\
    .join(RecipientCountry)\
    .all()
# This creates doc × category × subcategory × country × recipient rows!
```

### 5. Idempotent Inserts

**Use ON CONFLICT DO NOTHING for relationship tables**:

```python
from sqlalchemy import text

def insert_categories(session, doc_id: str, categories: list[str]):
    """Insert categories with idempotent ON CONFLICT handling"""
    for category in categories:
        session.execute(
            text("""
                INSERT INTO categories (doc_id, category)
                VALUES (:doc_id, :category)
                ON CONFLICT (doc_id, category) DO NOTHING
            """),
            {"doc_id": doc_id, "category": category}
        )
```

### 6. Configuration Files

**Use Config utility class**:

```python
from shared.utils.utils import Config

# Load config from shared/config/config.yaml
config = Config.from_yaml()

# Access configuration
influencers = config.influencers    # ['China', 'Russia', 'Iran', 'Turkey', 'United States']
recipients = config.recipients      # ['Israel', 'Palestine', 'Iran', ...]
start_date = config.start_date      # '2024-08-01'
```

### 7. Docker Compatibility

**Scripts run inside api-service container**:

```bash
# Execute scripts in Docker
docker exec api-service python services/pipeline/ingestion/dsr.py --source s3

# Database connection is automatic via environment variables
# DB_HOST=softpower_db is set in docker-compose.yml
```

**Best practices**:
- Use relative paths from project root
- No hardcoded localhost connections
- Use environment variables for all configuration
- All pipeline scripts are in `services/pipeline/`

### 8. Event Tracking System

**Current Architecture**:

```
Documents → Daily Event Mentions → Canonical Events → Master Events
```

**Models**:
- `EventCluster`: Daily event clusters from DBSCAN
- `CanonicalEvent`: Deduplicated events (via LLM)
- `DailyEventMention`: Daily mentions of canonical events
- Master events: Canonical events with `master_event_id=NULL` that aggregate child events

**Example - Creating canonical events**:

```python
from shared.models.models import CanonicalEvent
from datetime import date

def create_canonical_event(session, event_data):
    event = CanonicalEvent(
        canonical_name=event_data['name'],
        initiating_country=event_data['country'],
        first_mention_date=event_data['date'],
        last_mention_date=event_data['date'],
        total_articles=event_data['article_count'],
        total_mention_days=1,
        primary_categories={},
        primary_recipients={},
        master_event_id=None  # NULL for master events, UUID for child events
    )
    session.add(event)
    return event
```

## New Directory Structure

```
services/
├── api/                    # FastAPI service
│   ├── main.py            # API endpoints
│   └── routes.py          # Route definitions
├── dashboard/              # Streamlit dashboard
│   ├── app.py             # Main dashboard
│   ├── pages/             # Dashboard pages
│   ├── queries/           # Database queries
│   └── charts/            # Chart components
└── pipeline/               # Data processing pipeline (YOUR SCRIPTS GO HERE)
    ├── ingestion/         # Document ingestion (dsr.py, atom.py)
    ├── analysis/          # AI analysis (atom_extraction.py)
    ├── events/            # Event processing (clustering, tracking)
    ├── embeddings/        # Vector embeddings
    └── diagnostics/       # Diagnostic tools

shared/                     # Shared code across all services
├── models/                # SQLAlchemy models
│   └── models.py         # All database models
├── database/              # Database connection management
│   └── database.py       # Centralized connection manager
├── config/                # Configuration
│   ├── config.yaml       # Main config file
│   └── config.py         # Config utilities
└── utils/                 # Shared utilities
    ├── utils.py          # Common utilities
    └── prompts.py        # LLM prompts
```

## Reference Examples

### Best Practice Examples

1. **services/pipeline/ingestion/dsr.py** - Document ingestion
   - Modern database connections
   - Relationship table flattening
   - ON CONFLICT DO NOTHING for idempotency
   - Docker-compatible configuration

2. **services/pipeline/events/batch_cluster_events.py** - Event clustering
   - DBSCAN clustering with embeddings
   - Modern session management
   - Batch processing patterns

3. **services/pipeline/events/llm_deconflict_clusters.py** - LLM deduplication
   - GPT-based event deduplication
   - Canonical event creation
   - Progress tracking

4. **services/pipeline/events/create_master_events.py** - Master event consolidation
   - Temporal event linking
   - Embedding similarity
   - Hierarchical event structure

### Legacy Reference (DO NOT COPY)

Archived documentation in `docs_archive/` contains historical approaches. These:
- Use outdated Flask-SQLAlchemy patterns
- Have hardcoded database connections
- Don't work in Docker
- Should be referenced for business logic only, NOT implementation patterns

## Current Database Schema

### Core Tables

**documents**: Central table with document metadata
- Fields: doc_id, title, body, date, source_name, etc.

**Relationship Tables** (normalized many-to-many):
- `categories`: doc_id, category
- `subcategories`: doc_id, subcategory
- `initiating_countries`: doc_id, initiating_country
- `recipient_countries`: doc_id, recipient_country

### Event Tables

**event_clusters**: DBSCAN clustering results
- Daily event clusters before LLM deduplication
- Fields: initiating_country, cluster_date, batch_number, cluster_id, event_names

**canonical_events**: Deduplicated events
- Master events (master_event_id=NULL) and child events
- Fields: canonical_name, initiating_country, first_mention_date, last_mention_date, total_articles, master_event_id

**daily_event_mentions**: Daily mentions of canonical events
- Links canonical events to daily occurrences
- Fields: canonical_event_id, mention_date, article_count, doc_ids[]

## Testing

**Test scripts in Docker environment**:

```bash
# Test database connection
docker exec api-service python -c "from shared.database.database import health_check; print('✅ OK' if health_check() else '❌ FAIL')"

# Run a pipeline script
docker exec api-service python services/pipeline/ingestion/dsr.py --source s3

# View logs
docker logs api-service --tail 50
```

## Migration from Old Structure

**Old imports** → **New imports**:

```python
# OLD (deprecated)
from backend.database import get_session
from backend.models import Document
from backend.scripts.utils import Config

# NEW (current)
from shared.database.database import get_session
from shared.models.models import Document
from shared.utils.utils import Config
```

**Old paths** → **New paths**:
- `backend/scripts/` → `services/pipeline/`
- `backend/database.py` → `shared/database/database.py`
- `backend/models.py` → `shared/models/models.py`
- `backend/config.yaml` → `shared/config/config.yaml`

## Key Takeaways

✅ **Use**:
- `shared/models/models.py` for all models
- `get_session()` context manager
- Environment variables for configuration
- `services/pipeline/` for new scripts
- Relationship tables for normalized data

❌ **Avoid**:
- Flask app context patterns
- Hardcoded database connections
- Cartesian JOIN queries
- Legacy `backend.scripts.models` imports
- Module-level database engine variables

## Need Help?

1. Review `services/pipeline/ingestion/dsr.py` for complete modern implementation
2. Check `shared/database/database.py` for connection management
3. See `shared/models/models.py` for current schema
4. Review `CLAUDE.md` for architecture overview
