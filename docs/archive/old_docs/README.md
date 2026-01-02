# Archived Documentation

**Archive Date**: 2025-10-22

This directory contains historical documentation from the project's refactoring process. These documents reference deprecated Flask-SQLAlchemy patterns and outdated directory structures.

## Why These Docs Were Archived

The SoftPower Analytics project underwent a major refactoring from:
- **Old**: Flask-SQLAlchemy with monolithic `backend/` and `streamlit/` directories
- **New**: Service-oriented architecture with `services/` and `shared/` directories
- **Old**: Flask app context and `db.session` patterns
- **New**: Modern SQLAlchemy 2.0 with `get_session()` context managers

## Archived Files

### Root-Level Documentation

- **DOCKER_DATABASE_MIGRATION.md** - Docker setup with old Flask patterns
- **EVENT_FLATTENING_EXPLAINED.md** - RawEvents flattening (now done via dsr.py)
- **MANUAL_WORKFLOW.md** - Manual workflow using old backend/scripts/ paths
- **NEWS_EVENT_TRACKER_IMPLEMENTATION.md** - Implementation with old paths
- **NEWS_EVENT_TRACKER_WORKFLOW.md** - Workflow with old database patterns
- **QUICK_START_NEWS_TRACKER.md** - Quick start with outdated imports
- **REFACTORING_SUMMARY.md** - Initial refactoring notes (now superseded)
- **SCHEMA_FIX_SUMMARY.md** - Historical schema fixes

### Backend Documentation

- **CONSOLIDATED_PIPELINE_PRODUCTION.md** - Event consolidation (old approach)
- **EVENT_CONSOLIDATION_PIPELINE.md** - Pipeline with old script references
- **FASTAPI_S3_SETUP.md** - S3 setup (still relevant but paths outdated)
- **S3_PGVECTOR_MIGRATION.md** - pgvector migration (still relevant but paths outdated)

## Current Documentation

For up-to-date documentation, refer to:

1. **CLAUDE.md** (root) - Comprehensive project documentation with current architecture
2. **backend/scripts/DEVELOPMENT_GUIDE.md** - Development guide with updated patterns
3. **README.md** (root) - Project overview
4. **DEPLOYMENT_GUIDE.md** (root) - Deployment instructions

## Key Changes Since Archival

### Directory Structure
- `backend/scripts/` → `services/pipeline/`
- `streamlit/` → `services/dashboard/`
- New `shared/` directory for common code

### Import Patterns
```python
# OLD (archived docs)
from backend.database import get_session
from backend.models import Document
from backend.scripts.models import DailySummary

# NEW (current)
from shared.database.database import get_session
from shared.models.models import Document, CanonicalEvent
```

### Database Patterns
```python
# OLD (archived docs)
from backend.app import create_app
from backend.extensions import db
with app.app_context():
    results = db.session.query(Document).all()

# NEW (current)
from shared.database.database import get_session
with get_session() as session:
    results = session.query(Document).all()
```

### Event Models
- **OLD**: Separate `DailyEvent`, `WeeklyEvent`, `MonthlyEvent` tables
- **NEW**: Unified `CanonicalEvent` + `DailyEventMention` with `master_event_id` hierarchy

## Using Archived Documentation

These documents are useful for:
- Understanding historical decisions
- Business logic reference
- Migration context

**DO NOT** copy:
- Import statements
- Database connection code
- File paths
- Session management patterns

## Reference

For migration guidance, see:
- **CLAUDE.md** section "Development Patterns"
- **backend/scripts/DEVELOPMENT_GUIDE.md** section "Migration from Old Structure"
