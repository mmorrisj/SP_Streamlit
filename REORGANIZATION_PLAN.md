# Project Reorganization Plan

This document outlines a comprehensive cleanup to remove clutter and keep only current, production-ready files.

## Current State Analysis

**Issues:**
- 31+ markdown documentation files at root level
- Multiple deprecated/archived scripts mixed with current ones
- Overlapping documentation with inconsistent information
- Old config loading patterns in multiple files
- Deprecated event models and tables still referenced

## Reorganization Strategy

### Phase 1: Documentation Consolidation

#### Keep (Core Documentation)
```
docs/
├── README.md                          # Project overview (simplified)
├── QUICKSTART.md                      # Quick deployment guide
├── ARCHITECTURE.md                    # System architecture (from CLAUDE.md)
└── deployment/
    ├── DOCKER_COMPOSE.md              # Docker Compose deployment
    ├── DOCKER_ONLY.md                 # Pure Docker deployment
    ├── NON_DOCKER.md                  # Bare metal deployment
    └── DOCKER_HUB.md                  # Publishing to Docker Hub
```

#### Archive (Historical/Reference Documentation)
```
docs/archive/
├── deprecated/
│   ├── EVENT_CONSOLIDATION_DIAGRAM_REVIEW.md    # Superseded by current pipeline
│   ├── HIERARCHICAL_SUMMARY_PIPELINE_PROPOSAL.md
│   ├── SUMMARY_PIPELINE_ARCHITECTURE.md
│   ├── SUMMARY_PIPELINE_FINAL_RECOMMENDATION.md
│   ├── SOURCE_TRACEABLE_SUMMARY_PIPELINE.md
│   ├── AP_STYLE_SUMMARY_PIPELINE.md
│   ├── PIPELINE.md                              # Old pipeline docs
│   ├── PIPELINE_STATUS.md
│   ├── setup_local_db.md
│   └── replit.md
│
├── migration_guides/
│   ├── FULL_DATABASE_MIGRATION.md
│   ├── MATERIALITY_EXPORT_IMPORT_GUIDE.md
│   ├── IMPORT_EXPORT_COMMANDS.md
│   └── S3_IMPORT_GUIDE.md
│
├── legacy_deployment/
│   ├── DEPLOYMENT_GUIDE.md                      # Superseded by new guides
│   ├── DOCKER_SETUP.md                          # Superseded
│   └── AZURE_SETUP_SYSTEM2.md
│
└── analysis_reports/
    ├── RAG_VALIDATION_REPORT.md
    ├── LINKAGE_VERIFICATION.md
    ├── API_FILTERING_SUMMARY.md
    ├── DASHBOARD_FILTERING_SUMMARY.md
    ├── INFLUENCER_PAGES_SUMMARY.md
    └── REACT_INTEGRATION_SUMMARY.md
```

### Phase 2: Pipeline Script Organization

#### Current Production Pipeline (Keep)
```
services/pipeline/
├── ingestion/
│   ├── atom.py                        # Document ingestion
│   └── dsr.py                         # S3 JSON processing
│
├── analysis/
│   └── atom_extraction.py             # AI analysis
│
├── events/
│   ├── batch_cluster_events.py        # Stage 1A: Daily clustering
│   ├── llm_deconflict_clusters.py     # Stage 1B: Create canonical events
│   ├── consolidate_all_events.py      # Stage 2A: Group events
│   ├── llm_deconflict_canonical_events.py  # Stage 2B: Validate groups
│   ├── merge_canonical_events.py      # Stage 2C: Merge mentions
│   ├── score_canonical_event_materiality.py  # Materiality scoring
│   ├── generate_event_summaries.py    # Summary generation
│   ├── export_event_tables.py         # Backup/export
│   ├── import_event_tables.py         # Restore
│   ├── export_materiality_scores.py   # Materiality backup
│   ├── import_materiality_scores.py   # Materiality restore
│   └── run_full_pipeline.py           # Orchestration (if current)
│
├── embeddings/
│   ├── embed_missing_documents.py     # Document embeddings
│   ├── embed_event_summaries.py       # Event embeddings
│   ├── export_embeddings.py           # Backup embeddings
│   ├── import_embeddings.py           # Restore embeddings
│   └── s3.py                          # S3 utilities
│
└── diagnostics/
    └── (current diagnostic tools)
```

#### Archive Deprecated Scripts
```
services/pipeline/events/_deprecated/
├── create_master_events.py            # Superseded by consolidate_all_events.py
├── process_daily_news.py              # Old approach
├── process_date_range.py              # Old approach
├── temporal_event_consolidation.py    # Old approach
├── news_event_tracker.py              # Old approach (from _archived/)
└── consolidate_canonical_events.py    # Old approach (from _archived/)
```

**Scripts to Review/Archive:**
- `auto_queue_materiality.py` - Still used? Or manual now?
- `backfill_canonical_event_recipients.py` - One-time script? Archive after use?
- `query_master_events.py` - Diagnostic tool or deprecated?

### Phase 3: Configuration Cleanup

#### Fix Config Loading Pattern

**Current Issue:** Multiple files load config independently:
```python
# BAD (causes import errors in Docker)
cfg = Config.from_yaml()
```

**Fix Required In:**
- ✅ `services/pipeline/embeddings/s3.py` - FIXED
- ❌ `services/pipeline/embeddings/load_embeddings.py`
- ❌ `services/pipeline/embeddings/load_embeddings_by_docid.py`
- ❌ `services/pipeline/entities/entity_extraction.py`
- ❌ `services/pipeline/ingestion/atom.py`
- ❌ `services/pipeline/ingestion/dsr.py`

**Solution:** All should import from `shared.utils.utils`:
```python
from shared.utils.utils import cfg  # Import singleton config
```

### Phase 4: Database Model Cleanup

#### Current Models (Keep)
- `Document` - Core document model
- `EventSummary` - Consolidated event model (with period_type enum)
- `PeriodSummary` - Aggregated summaries
- `EventSourceLink` - Event-to-document traceability
- `CanonicalEvent` - Current event processing
- `DailyEventMention` - Event mentions by date
- Normalized tables: `categories`, `subcategories`, `initiating_countries`, etc.

#### Deprecated Models (Mark in comments, keep for data migration)
- `DailyEvent` - Superseded by EventSummary(period_type=DAILY)
- `WeeklyEvent` - Superseded by EventSummary(period_type=WEEKLY)
- `MonthlyEvent` - Superseded by EventSummary(period_type=MONTHLY)
- `YearlyEvent` - Superseded by EventSummary(period_type=YEARLY)

**Action:** Add deprecation warnings in `shared/models/models.py`:
```python
# DEPRECATED: Use EventSummary with period_type=PeriodType.DAILY instead
class DailyEvent(Base):
    __tablename__ = "daily_events"
    # ... (keep for legacy data migration only)
```

### Phase 5: Startup Scripts Cleanup

#### Keep
```
./
├── start_services.sh                  # Non-Docker startup (Linux/Mac)
├── start_services.ps1                 # Non-Docker startup (Windows)
├── deploy-docker-only.sh              # Docker-only deployment (Linux/Mac)
├── deploy-docker-only.ps1             # Docker-only deployment (Windows)
├── build-and-push.sh                  # Build Docker images (Linux/Mac)
├── build-and-push.ps1                 # Build Docker images (Windows)
├── docker-compose.yml                 # Development deployment
└── docker-compose.production.yml      # Production deployment
```

#### Archive (if they exist)
- Any old deployment scripts
- Legacy database setup scripts
- Old migration scripts (keep only Alembic)

## Implementation Steps

### Step 1: Create Archive Structure
```bash
mkdir -p docs/archive/{deprecated,migration_guides,legacy_deployment,analysis_reports}
mkdir -p services/pipeline/events/_deprecated
mkdir -p services/pipeline/analysis/_deprecated
mkdir -p services/pipeline/embeddings/_deprecated
```

### Step 2: Move Documentation Files
```bash
# Core documentation
mkdir -p docs/deployment
mv QUICKSTART.md docs/
mv DOCKER_NO_COMPOSE.md docs/deployment/
mv DOCKER_HUB_DEPLOYMENT.md docs/deployment/
mv DOCKER_COMMAND_REFERENCE.md docs/deployment/
mv SETUP_NON_DOCKER.md docs/deployment/
mv REGISTER_IMAGES.md docs/deployment/

# Archive deprecated/reference docs
mv EVENT_CONSOLIDATION_DIAGRAM_REVIEW.md docs/archive/deprecated/
mv HIERARCHICAL_SUMMARY_PIPELINE_PROPOSAL.md docs/archive/deprecated/
mv SUMMARY_PIPELINE_ARCHITECTURE.md docs/archive/deprecated/
mv SUMMARY_PIPELINE_FINAL_RECOMMENDATION.md docs/archive/deprecated/
mv SOURCE_TRACEABLE_SUMMARY_PIPELINE.md docs/archive/deprecated/
mv AP_STYLE_SUMMARY_PIPELINE.md docs/archive/deprecated/
mv PIPELINE.md docs/archive/deprecated/
mv PIPELINE_STATUS.md docs/archive/deprecated/

# Migration guides
mv FULL_DATABASE_MIGRATION.md docs/archive/migration_guides/
mv MATERIALITY_EXPORT_IMPORT_GUIDE.md docs/archive/migration_guides/
mv IMPORT_EXPORT_COMMANDS.md docs/archive/migration_guides/
mv S3_IMPORT_GUIDE.md docs/archive/migration_guides/

# Analysis reports
mv RAG_VALIDATION_REPORT.md docs/archive/analysis_reports/
mv LINKAGE_VERIFICATION.md docs/archive/analysis_reports/
mv API_FILTERING_SUMMARY.md docs/archive/analysis_reports/
mv DASHBOARD_FILTERING_SUMMARY.md docs/archive/analysis_reports/
mv INFLUENCER_PAGES_SUMMARY.md docs/archive/analysis_reports/
mv REACT_INTEGRATION_SUMMARY.md docs/archive/analysis_reports/

# Legacy deployment
mv DEPLOYMENT_GUIDE.md docs/archive/legacy_deployment/
mv DOCKER_SETUP.md docs/archive/legacy_deployment/
mv AZURE_SETUP_SYSTEM2.md docs/archive/legacy_deployment/
mv setup_local_db.md docs/archive/legacy_deployment/
mv replit.md docs/archive/legacy_deployment/
```

### Step 3: Consolidate CLAUDE.md → ARCHITECTURE.md
```bash
# Extract architecture sections from CLAUDE.md
# Create new streamlined ARCHITECTURE.md
# Keep CLAUDE.md for Claude Code compatibility (it looks for this file)
```

### Step 4: Create New Simplified README.md
```bash
# Replace current README.md with:
# - Quick project overview
# - Links to docs/ for detailed guides
# - Current status/production deployment info
```

### Step 5: Fix Config Loading in All Scripts
```bash
# Update all scripts to use:
from shared.utils.utils import cfg

# Instead of:
cfg = Config.from_yaml()
```

### Step 6: Create INDEX.md for Navigation
```bash
# docs/INDEX.md - Table of contents for all documentation
```

## Final Directory Structure

```
SP_Streamlit/
├── README.md                          # Simple overview + links
├── .env.example                       # Environment template
├── requirements.txt
├── alembic.ini
│
├── docs/                              # All documentation here
│   ├── INDEX.md                       # Documentation index
│   ├── QUICKSTART.md                  # Start here!
│   ├── ARCHITECTURE.md                # System design
│   ├── PIPELINE.md                    # Pipeline overview
│   ├── deployment/
│   │   ├── DOCKER_COMPOSE.md
│   │   ├── DOCKER_ONLY.md
│   │   ├── NON_DOCKER.md
│   │   └── DOCKER_HUB.md
│   └── archive/                       # Historical reference
│       ├── deprecated/
│       ├── migration_guides/
│       ├── legacy_deployment/
│       └── analysis_reports/
│
├── client/                            # React frontend
├── server/                            # Production FastAPI
├── services/                          # Application services
│   ├── api/                           # Dev FastAPI
│   ├── dashboard/                     # Streamlit
│   └── pipeline/                      # Processing pipeline
│       ├── ingestion/
│       ├── analysis/
│       ├── events/
│       │   ├── (current scripts)
│       │   └── _deprecated/           # Old approaches
│       ├── embeddings/
│       └── diagnostics/
│
├── shared/                            # Shared code
│   ├── config/
│   ├── database/
│   ├── models/
│   └── utils/
│
├── docker/                            # Dockerfiles
├── alembic/                           # Migrations
│
├── start_services.sh                  # Non-Docker (Linux/Mac)
├── start_services.ps1                 # Non-Docker (Windows)
├── deploy-docker-only.sh              # Docker-only (Linux/Mac)
├── deploy-docker-only.ps1             # Docker-only (Windows)
├── build-and-push.sh                  # Build images (Linux/Mac)
├── build-and-push.ps1                 # Build images (Windows)
├── docker-compose.yml                 # Development
└── docker-compose.production.yml      # Production
```

## Benefits

### Before
- 31+ markdown files at root level
- Unclear which scripts are current
- Multiple overlapping docs with conflicting info
- Hard to onboard new developers
- Cluttered root directory

### After
- 2 files at root: README.md + .env.example
- All docs organized in `docs/`
- Clear separation: current vs archived
- Single source of truth per topic
- Easy navigation via docs/INDEX.md

## Validation Checklist

After reorganization:

- [ ] All deployment methods documented in `docs/deployment/`
- [ ] Current pipeline scripts clearly identified
- [ ] Deprecated scripts moved to `_deprecated/` folders
- [ ] Config loading pattern fixed in all scripts
- [ ] README.md is concise and points to detailed docs
- [ ] docs/INDEX.md provides clear navigation
- [ ] All archived docs preserved for reference
- [ ] Docker builds still work
- [ ] Non-Docker startup still works
- [ ] Pipeline scripts still run

## Rollback Plan

If reorganization causes issues:
1. All original files preserved in `docs/archive/`
2. Git history maintains original locations
3. Can revert with: `git checkout HEAD~1 -- <file>`

## Timeline

- Phase 1-2: 30 minutes (file moving)
- Phase 3: 15 minutes (config fixes)
- Phase 4: 10 minutes (model deprecation warnings)
- Phase 5: 15 minutes (documentation consolidation)
- Testing: 30 minutes

**Total: ~2 hours**

## Next Steps

1. Review this plan
2. Approve structure
3. Execute reorganization
4. Test all deployment modes
5. Update CLAUDE.md to reference new structure
