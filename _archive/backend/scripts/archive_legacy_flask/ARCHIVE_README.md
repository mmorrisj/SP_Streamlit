# Archive: Legacy Flask-SQLAlchemy Scripts

**Archive Date**: 2025-10-17

## Purpose

This directory contains scripts that were moved from `backend/scripts/` because they use **legacy Flask-SQLAlchemy** database connections and are incompatible with the modern **SQLAlchemy 2.0** architecture.

## Why These Scripts Were Archived

The codebase has migrated from:
- **Old**: Flask-SQLAlchemy with `db.session` and `backend.scripts.models`
- **New**: Modern SQLAlchemy 2.0 with `get_session()` context manager and `backend.models`

### Critical Issues in Archived Scripts

1. **Flask-SQLAlchemy Dependencies**: Import from `backend.scripts.models` and `backend.extensions`
2. **Hardcoded Database Connections**: Localhost connections that don't work in Docker
3. **Outdated Session Management**: Use Flask app context instead of modern connection pooling
4. **Not Docker-Compatible**: Cannot run in production Docker environment
5. **Schema Mismatches**: Don't use the new normalized relationship tables (Categories, Subcategories, InitiatingCountries, RecipientCountries, RawEvents)

## Archived Files

### Daily Event Processing
- **daily.py**: Legacy daily event consolidation using Flask-SQLAlchemy
  - Issues: Flask imports, hardcoded localhost, doesn't use RawEvents table, Cartesian product queries
  - Modern Alternative: Needs to be rewritten using `backend.models` and `get_session()`

- **daily_event_consolidation.py**: Legacy daily event consolidation
  - Issues: Flask imports, outdated models
  - Modern Alternative: Should be consolidated with modern daily.py rewrite

- **recipient_daily.py**: Recipient-specific daily summaries
  - Issues: Flask imports, hardcoded localhost, uses sqlite3
  - Modern Alternative: Functionality should be incorporated into EventSummary model

### Event Processing
- **event_summary.py**: Legacy event summarization
  - Issues: Flask imports, hardcoded localhost
  - Modern Alternative: Use EventSummary model from `backend.models_consolidated`

- **dedupe_events.py**: Event deduplication script
  - Issues: Flask imports, hardcoded localhost
  - Modern Alternative: Deduplication should be handled during ingestion with ON CONFLICT DO NOTHING

- **cluster_events.py**: Event clustering using embeddings
  - Issues: Flask imports, hardcoded localhost
  - Modern Alternative: Needs rewrite with modern database connections

- **backfill_counts.py**: Backfill count fields
  - Issues: Flask imports
  - Modern Alternative: EventSummary model has built-in count management

### Embedding Scripts
- **embeddings.py**: Document embedding generation
  - Issues: Flask imports, hardcoded localhost
  - Modern Alternative: `embedding_vectorstore.py` uses modern connections

- **embed_daily_summaries.py**: Daily summary embeddings
  - Issues: Flask imports
  - Modern Alternative: Needs rewrite for EventSummary model

- **embed_events.py**: Event embeddings
  - Issues: Flask imports
  - Modern Alternative: Needs rewrite with modern connections

- **embed_weekly_dispatch.py**: Weekly summary embedding dispatch
  - Issues: Flask imports
  - Modern Alternative: Needs rewrite for EventSummary model

- **embed_weekly_summaries_monitor.py**: Weekly summary monitoring
  - Issues: Flask imports
  - Modern Alternative: Needs rewrite for EventSummary model

### Monthly Summaries
- **monthly_summary.py**: Monthly event summaries
  - Issues: Flask imports
  - Modern Alternative: Use EventSummary with period_type=MONTHLY

### Helper Scripts
- **sp_tokenize.py**: Token counting utilities
  - Issues: Flask imports
  - Modern Alternative: Can be rewritten without database dependencies

- **summary.py**: Generic summary utilities
  - Issues: Uses sqlite3
  - Modern Alternative: Rewrite for PostgreSQL with modern connections

### Data Migration
- **flatten.py**: Legacy data flattening
  - Issues: Outdated, functionality now in dsr.py
  - Modern Alternative: `dsr.py` with `flatten_all_relationships()`

- **flatten_events.py**: Legacy event flattening
  - Issues: Outdated, functionality now in dsr.py
  - Modern Alternative: `dsr.py` with `flatten_all_relationships()`

- **insert_events.py**: Legacy event insertion
  - Issues: Outdated approach
  - Modern Alternative: `dsr.py` handles event insertion with ON CONFLICT

### Models
- **Old_models.py**: Explicitly deprecated model definitions
  - Issues: Duplicate of outdated models
  - Modern Alternative: `backend.models` and `backend.models_consolidated`

## Current Active Scripts (Still in backend/scripts/)

These scripts use modern SQLAlchemy 2.0 patterns:

- **dsr.py**: Document ingestion with modern connections (ACTIVE)
- **atom.py**: Atom document processing
- **atom_extraction.py**: AI-based document extraction
- **atom_salience.py**: Salience scoring
- **s3.py**: S3 utilities
- **s3_to_pgvector.py**: S3 to pgvector migration (ACTIVE)
- **embedding_vectorstore.py**: Modern embedding management
- **embedding_dispatcher.py**: Celery-based embedding dispatch
- **embed_weekly_summaries.py**: Weekly summaries (needs verification)
- **prompts.py**: LLM prompt templates
- **utils.py**: General utilities
- **migration_config.py**: Database migration configuration
- **postgres_migration.py**: PostgreSQL migration utilities
- **process_daily_news.py**: Daily news processing (needs verification)
- **process_date_range.py**: Date range processing (needs verification)
- **news_event_tracker.py**: Event tracking (needs verification)

## Migration Path

To modernize any archived script:

1. **Update imports**:
   ```python
   # OLD
   from backend.scripts.models import Document, ...
   from backend.extensions import db
   from backend.app import app

   # NEW
   from backend.database import get_session
   from backend.models import Document, Category, Subcategory, RawEvent, ...
   from backend.models_consolidated import EventSummary, PeriodType, ...
   ```

2. **Update session management**:
   ```python
   # OLD
   with app.app_context():
       documents = db.session.query(Document).all()

   # NEW
   with get_session() as session:
       documents = session.query(Document).all()
   ```

3. **Remove hardcoded connections**:
   ```python
   # OLD
   os.environ["DB_HOST"] = "localhost"
   app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://matthew50:softpower@localhost:5432/softpower-db"

   # NEW
   # Use environment variables from .env file (handled by backend.database)
   ```

4. **Use relationship tables**:
   ```python
   # Query normalized relationship tables instead of storing in Document table
   categories = session.query(Category).filter(Category.doc_id == doc_id).all()
   events = session.query(RawEvent).filter(RawEvent.doc_id == doc_id).all()
   ```

5. **Use consolidated models**:
   ```python
   # Use EventSummary instead of separate DailyEvent, WeeklyEvent tables
   from backend.models_consolidated import EventSummary, PeriodType

   daily_events = session.query(EventSummary).filter(
       EventSummary.period_type == PeriodType.DAILY,
       EventSummary.initiating_country == "China"
   ).all()
   ```

## Reference

See [backend/scripts/dsr.py](../dsr.py) for a complete example of modern SQLAlchemy 2.0 patterns with:
- Modern database connections
- Relationship table flattening
- ON CONFLICT DO NOTHING for idempotency
- Docker-compatible configuration
