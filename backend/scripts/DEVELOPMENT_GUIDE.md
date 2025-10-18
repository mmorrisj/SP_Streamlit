# Backend Scripts Development Guide

**Last Updated**: 2025-10-17

## Database Interaction Standards

All new scripts MUST use the modern SQLAlchemy 2.0 patterns. Legacy Flask-SQLAlchemy scripts have been archived to `archive_legacy_flask/` for reference only.

## Required Patterns for New Scripts

### 1. Imports

```python
# Database connection
from backend.database import get_session, init_database

# Models - Use ONLY these
from backend.models import (
    Document,
    Category,
    Subcategory,
    InitiatingCountry,
    RecipientCountry,
    RawEvent
)

# Consolidated event models (recommended for new event processing)
from backend.models_consolidated import (
    EventSummary,
    PeriodSummary,
    EventSourceLink,
    PeriodType,
    EventStatus
)

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

**Use environment variables** (automatically loaded from `.env`):

```python
# ✅ CORRECT - No hardcoding needed
with get_session() as session:
    # Connection is automatically configured
    pass
```

**NEVER hardcode**:
```python
# ❌ DON'T USE - Breaks Docker compatibility
os.environ["DB_HOST"] = "localhost"
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://user:pass@localhost:5432/db"
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

        # Get raw events separately (NEW!)
        raw_events = session.query(RawEvent.event_name).filter(
            RawEvent.doc_id == doc_id
        ).all()

        return {
            'document': doc,
            'categories': [c[0] for c in categories],
            'subcategories': [s[0] for s in subcategories],
            'initiating_countries': [i[0] for i in initiating_countries],
            'recipient_countries': [r[0] for r in recipient_countries],
            'events': [e[0] for e in raw_events]
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

**Use YAML config loading**:

```python
import yaml

def load_config():
    with open('backend/config.yaml', 'r') as f:
        return yaml.safe_load(f)

config = load_config()
influencers = config['influencers']  # ['China', 'Russia', 'Iran', ...]
recipients = config['recipients']    # ['Israel', 'Palestine', 'Iran', ...]
```

### 7. Docker Compatibility

**Assume scripts will run in Docker**:

- Use relative paths from project root
- No hardcoded localhost connections
- Use environment variables for all configuration
- Test with: `docker exec ml-backend python -m backend.scripts.your_script`

### 8. Event Consolidation

**For new event processing, use EventSummary model**:

```python
from backend.models_consolidated import EventSummary, PeriodType, EventStatus
from datetime import date

def create_daily_event_summary(country: str, event_name: str, event_date: date):
    with get_session() as session:
        event = EventSummary(
            period_type=PeriodType.DAILY,
            period_start=event_date,
            period_end=event_date,
            event_name=event_name,
            initiating_country=country,
            first_observed_date=event_date,
            last_observed_date=event_date,
            status=EventStatus.ACTIVE,
            count_by_category={},
            count_by_subcategory={},
            count_by_recipient={},
            count_by_source={}
        )
        session.add(event)
        session.commit()
        return event.id
```

## Reference Examples

### Best Practice Examples

1. **[dsr.py](dsr.py)** - Document ingestion with modern patterns
   - Modern database connections
   - Relationship table flattening
   - ON CONFLICT DO NOTHING for idempotency
   - Docker-compatible configuration

2. **[s3_to_pgvector.py](s3_to_pgvector.py)** - S3 to pgvector migration
   - Modern session management
   - Idempotent processing with tracker files
   - Clean error handling

### Legacy Reference (DO NOT COPY)

See `archive_legacy_flask/` for historical approaches. These scripts:
- Use outdated Flask-SQLAlchemy patterns
- Have hardcoded database connections
- Don't work in Docker
- Should be referenced for business logic only, NOT implementation patterns

## Schema Reference

### Current Database Schema

**Documents Table**: Central table with document metadata
- Legacy fields preserved: `event_name`, `project_name`, `projects` (for backward compatibility)
- All fields are now ALSO flattened to relationship tables

**Relationship Tables** (normalized many-to-many):
- `categories`: doc_id, category
- `subcategories`: doc_id, subcategory
- `initiating_countries`: doc_id, initiating_country
- `recipient_countries`: doc_id, recipient_country
- `raw_events`: doc_id, event_name (consolidated from event-name, project-name, projects)

**Event Summary Tables** (consolidated):
- `event_summaries`: Replaces daily_events, weekly_events, monthly_events with period_type enum
- `period_summaries`: Aggregate summaries for time periods
- `event_source_links`: Traceability linking events to source documents

### RawEvents Consolidation Logic

The `raw_events` table consolidates event data from multiple legacy fields:

**Priority**: `event-name` > `project-name` > `projects`

```python
# Example: How events are consolidated
doc_data = {
    "event-name": "Summit Meeting",        # Highest priority
    "project-name": "Infrastructure Deal",  # Second priority
    "projects": "Trade Agreement"          # Lowest priority
}

# Results in raw_events:
# doc_id, event_name: "Summit Meeting"
# (event-name takes precedence)
```

## Testing

**Always test scripts in Docker environment**:

```bash
# Test database connection
docker exec ml-backend python -c "from backend.database import health_check; print('OK' if health_check() else 'FAIL')"

# Run your script
docker exec -e DB_HOST=softpower_db -e DB_PORT=5432 \
  ml-backend python -m backend.scripts.your_script
```

## Need Help?

1. Review [dsr.py](dsr.py) for complete modern implementation
2. Check [ARCHIVE_README.md](archive_legacy_flask/ARCHIVE_README.md) for migration patterns
3. See [backend/models.py](../models.py) for current schema
4. See [backend/models_consolidated.py](../models_consolidated.py) for event models

## Key Takeaway

✅ **Use**: `backend.models`, `get_session()`, environment variables, relationship tables, RawEvents

❌ **Avoid**: `backend.scripts.models`, Flask app context, hardcoded connections, Cartesian JOINs
