# Current Pipeline Scripts Reference

This document identifies which scripts are **actively used** in the current production pipeline vs which are deprecated.

## ✅ Active Production Scripts

### Document Ingestion
```
services/pipeline/ingestion/
├── atom.py              # ACTIVE - Ingest documents from atom feed
└── dsr.py               # ACTIVE - Process JSON files from S3
```

### AI Analysis
```
services/pipeline/analysis/
└── atom_extraction.py   # ACTIVE - Extract salience, categories, countries, projects
```

### Event Processing (Current 2-Stage Pipeline)

**Stage 1: Daily Event Detection**
```
services/pipeline/events/
├── batch_cluster_events.py              # ACTIVE - Stage 1A: Cluster daily events
└── llm_deconflict_clusters.py           # ACTIVE - Stage 1B: Create canonical events
```

**Stage 2: Batch Consolidation**
```
services/pipeline/events/
├── consolidate_all_events.py            # ACTIVE - Stage 2A: Group events via embeddings
├── llm_deconflict_canonical_events.py   # ACTIVE - Stage 2B: Validate consolidations
└── merge_canonical_events.py            # ACTIVE - Stage 2C: Merge daily mentions
```

**Event Utilities**
```
services/pipeline/events/
├── score_canonical_event_materiality.py # ACTIVE - Score materiality
├── generate_event_summaries.py          # ACTIVE - Generate summaries
├── export_event_tables.py               # ACTIVE - Backup events
├── import_event_tables.py               # ACTIVE - Restore events
├── export_materiality_scores.py         # ACTIVE - Backup scores
└── import_materiality_scores.py         # ACTIVE - Restore scores
```

### Embeddings
```
services/pipeline/embeddings/
├── embed_missing_documents.py           # ACTIVE - Embed documents
├── embed_event_summaries.py             # ACTIVE - Embed event summaries
├── export_embeddings.py                 # ACTIVE - Backup embeddings to S3
├── import_embeddings.py                 # ACTIVE - Restore embeddings from S3
└── s3.py                                # ACTIVE - S3 utilities
```

## ❌ Deprecated Scripts (Move to _deprecated/)

### Event Processing (Old Approaches)
```
services/pipeline/events/_deprecated/
├── create_master_events.py              # DEPRECATED - Use consolidate_all_events.py
├── process_daily_news.py                # DEPRECATED - Old event detection
├── process_date_range.py                # DEPRECATED - Old batch processing
├── temporal_event_consolidation.py      # DEPRECATED - Old consolidation
├── news_event_tracker.py                # DEPRECATED - Old tracking approach
└── consolidate_canonical_events.py      # DEPRECATED - Old consolidation
```

## ⚠️ Scripts Needing Review

These scripts may be one-time utilities or deprecated - needs investigation:

```
services/pipeline/events/
├── auto_queue_materiality.py            # REVIEW - Still used? Or manual now?
├── backfill_canonical_event_recipients.py  # REVIEW - One-time migration script?
├── query_master_events.py               # REVIEW - Diagnostic tool or deprecated?
└── run_full_pipeline.py                 # REVIEW - Orchestration script - current?
```

**Action:** Review these scripts and either:
- Move to `_deprecated/` if not used
- Document in this file if they're active utilities
- Keep if they're current diagnostic/orchestration tools

## Current Pipeline Execution Order

### Initial Data Load
```bash
# 1. Ingest documents
python services/pipeline/ingestion/atom.py
# OR
python services/pipeline/ingestion/dsr.py

# 2. AI analysis
python services/pipeline/analysis/atom_extraction.py

# 3. Generate embeddings
python services/pipeline/embeddings/embed_missing_documents.py --yes
```

### Event Processing (Per Country)
```bash
# Stage 1A: Cluster daily events
python services/pipeline/events/batch_cluster_events.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 1B: LLM validate and create canonical events
python services/pipeline/events/llm_deconflict_clusters.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 2A: Consolidate across all dates (run periodically)
python services/pipeline/events/consolidate_all_events.py --influencers

# Stage 2B: LLM validate consolidations
python services/pipeline/events/llm_deconflict_canonical_events.py --influencers

# Stage 2C: Merge daily mentions into multi-day events
python services/pipeline/events/merge_canonical_events.py --influencers

# Optional: Score materiality
python services/pipeline/events/score_canonical_event_materiality.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31
```

### Backup/Restore
```bash
# Backup embeddings to S3
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./backups/$(date +%Y%m%d) \
    --include-event-summaries

# Restore embeddings from S3
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./backups/20241106

# Backup event data
python services/pipeline/events/export_event_tables.py \
    --output-dir ./backups/events/

# Restore event data
python services/pipeline/events/import_event_tables.py \
    --input-dir ./backups/events/
```

## Database Models

### Current Models (Active)
- `Document` - Core document storage
- `CanonicalEvent` - Events with master_event_id hierarchy
- `DailyEventMention` - Event mentions by date
- `EventSummary` - Consolidated summaries (with period_type enum)
- `PeriodSummary` - Aggregated period summaries
- `EventSourceLink` - Event-to-document traceability
- Normalized: `categories`, `subcategories`, `initiating_countries`, `recipient_countries`, `projects`, `citations`

### Deprecated Models (Keep for legacy data)
- `DailyEvent` → Replaced by EventSummary(period_type=DAILY)
- `WeeklyEvent` → Replaced by EventSummary(period_type=WEEKLY)
- `MonthlyEvent` → Replaced by EventSummary(period_type=MONTHLY)
- `YearlyEvent` → Replaced by EventSummary(period_type=YEARLY)

## Configuration Files

### Current
- `shared/config/config.yaml` - Main configuration
- `.env` - Environment variables (local, not committed)
- `.env.example` - Environment template (committed)
- `alembic.ini` - Database migrations config
- `docker-compose.yml` - Development deployment
- `docker-compose.production.yml` - Production deployment

## Startup Scripts

### Current
- `start_services.sh` - Non-Docker startup (Linux/macOS)
- `start_services.ps1` - Non-Docker startup (Windows)
- `deploy-docker-only.sh` - Docker-only deployment (Linux/macOS)
- `deploy-docker-only.ps1` - Docker-only deployment (Windows)
- `build-and-push.sh` - Build Docker images (Linux/macOS)
- `build-and-push.ps1` - Build Docker images (Windows)

## Next Steps

1. **Review Scripts Marked "REVIEW"**: Determine if they're active, deprecated, or one-time utilities
2. **Move Deprecated Scripts**: Ensure all deprecated scripts are in `_deprecated/` folders
3. **Update Import Paths**: If any active scripts import from deprecated scripts, update them
4. **Document run_full_pipeline.py**: If it's the current orchestration script, document its usage
5. **Test Pipeline**: Run through entire pipeline to ensure all active scripts work

## Maintenance

Update this file when:
- New pipeline scripts are added
- Scripts are deprecated
- Pipeline execution order changes
- New models are introduced
