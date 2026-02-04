# Entity Extraction Pipeline - Quick Start Guide

## TL;DR - What Should I Run?

### ✅ RECOMMENDED: Two-Stage Pipeline

This is the documented, supported approach that matches your event processing pipeline:

```bash
# Stage 1A: Extract raw entities from documents
python services/pipeline/entities/extract_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Stage 1B: Cluster entities by similarity
python services/pipeline/entities/cluster_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Stage 1C: LLM validates and creates canonical entities
# ⚠️ NOT YET IMPLEMENTED - needs to be created
python services/pipeline/entities/llm_deconflict_entity_clusters.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Stage 2: Batch consolidation across all dates
# ⚠️ NOT YET IMPLEMENTED - needs to be created
python services/pipeline/entities/consolidate_all_entities.py --country China
python services/pipeline/entities/llm_deconflict_canonical_entities.py --country China
python services/pipeline/entities/merge_canonical_entities.py --country China
```

### ❌ DEPRECATED: Single-Stage Scripts

These scripts use the old architecture and have been deprecated:

```bash
# ⚠️ DEPRECATED - Don't use these
python services/pipeline/entities/entity_extraction.py --country China --limit 100
python services/pipeline/entities/store_entities.py data/entity_extractions_*.json
python services/pipeline/entities/batch_entity_extraction.py --country China --batch-size 500
```

**Why deprecated?**
- Simple name matching (error-prone)
- No clustering or deduplication
- Conflicts with two-stage pipeline models
- Not aligned with event processing architecture

---

## What Tables Are Created?

### Two-Stage Pipeline Tables (Current)

**Stage 1A: Raw Extraction**
- `raw_entities` - Raw entity mentions from documents

**Stage 1B: Clustering**
- `entity_clusters` - Daily entity clusters (DBSCAN results)

**Stage 1C: Deconfliction** (not yet implemented)
- `canonical_entities` - Deduplicated entities with master-child hierarchy
- `daily_entity_mentions` - Daily activity tracking per entity

**Stage 2: Relationships** (not yet implemented)
- `entity_relationships` - Relationships between canonical entities (for graph)

### Old Architecture Tables (Deprecated)

- `entities` - Simple entity table (conflicts with new architecture)
- `document_entities` - Document-entity links (deprecated)
- `entity_relationships` - Different schema than two-stage pipeline

**Status**: Models disabled to prevent conflicts. Tables may still exist in database but should not be used.

---

## Current Implementation Status

### ✅ Working Now

**Stage 1A: extract_daily_entities.py**
```bash
# Extract entities for a date range
python services/pipeline/entities/extract_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Check status
python services/pipeline/entities/extract_daily_entities.py \
    --country China \
    --status

# Force reprocess documents
python services/pipeline/entities/extract_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31 \
    --force
```

**What it does**:
- Reads `documents.distilled_text`
- LLM extracts persons, organizations, companies, locations
- Captures roles, affiliations, context snippets
- Saves to `raw_entities` table

**Stage 1B: cluster_daily_entities.py**
```bash
# Cluster all entity types
python services/pipeline/entities/cluster_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Cluster specific entity type only
python services/pipeline/entities/cluster_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31 \
    --entity-type person

# Check status
python services/pipeline/entities/cluster_daily_entities.py \
    --country China \
    --status
```

**What it does**:
- Groups raw entity mentions using DBSCAN + embeddings
- Processes per (country, date, entity_type)
- Creates `entity_clusters` table
- Prepares for LLM deconfliction

### 🚧 Needs Implementation

**Stage 1C: llm_deconflict_entity_clusters.py**
- Template: `services/pipeline/events/llm_deconflict_clusters.py`
- Purpose: LLM validates clusters and creates canonical entities
- Output: `canonical_entities` + `daily_entity_mentions` tables

**Stage 2A: consolidate_all_entities.py**
- Template: `services/pipeline/events/consolidate_all_events.py`
- Purpose: Find same entity across entire dataset (embedding similarity)
- Output: Sets `master_entity_id` for entity resolution

**Stage 2B: llm_deconflict_canonical_entities.py**
- Template: `services/pipeline/events/llm_deconflict_canonical_events.py`
- Purpose: LLM validates entity groupings, picks best canonical name
- Output: Marks `llm_validated = TRUE`

**Stage 2C: merge_canonical_entities.py**
- Template: `services/pipeline/events/merge_canonical_events.py`
- Purpose: Consolidate daily mentions to master entities
- Output: Merged `daily_entity_mentions`, deleted empty children

**Relationship Extraction: extract_entity_relationships.py**
- Purpose: Extract relationships for entity graph
- Output: `entity_relationships` table (graph edges)

---

## Check Your Database

### See what tables exist

```bash
# Connect to database
psql -U $POSTGRES_USER -d $POSTGRES_DB

# List entity-related tables
\dt *entit*

# Check table contents
SELECT COUNT(*) FROM raw_entities;
SELECT COUNT(*) FROM entity_clusters;
SELECT COUNT(*) FROM canonical_entities;  -- May not exist yet
```

### Check if old tables exist

```bash
# These are deprecated tables
SELECT COUNT(*) FROM entities;           -- Old architecture
SELECT COUNT(*) FROM document_entities;  -- Old architecture
```

If these exist, they're from the old architecture and should be migrated or ignored.

---

## Migration from Old Architecture

If you've been using the old scripts and have data in `entities` / `document_entities`:

### Option 1: Start Fresh (Recommended)

```bash
# Drop old tables (backup first!)
DROP TABLE IF EXISTS entity_relationships CASCADE;
DROP TABLE IF EXISTS document_entities CASCADE;
DROP TABLE IF EXISTS entities CASCADE;
DROP TABLE IF EXISTS entity_extraction_runs CASCADE;

# Run Alembic migration to create new tables
alembic revision --autogenerate -m "create entity extraction tables"
alembic upgrade head

# Start processing with two-stage pipeline
python services/pipeline/entities/extract_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-12-31
```

### Option 2: Keep Both (Temporary)

- Old tables can coexist with new tables (different table names)
- Use new two-stage pipeline for new processing
- Old data remains queryable but won't be updated
- Eventually migrate old data to new schema

---

## Common Issues

### "Failed to get processing status"

**Cause**: Running deprecated `batch_entity_extraction.py` which queries old tables.

**Fix**: Use two-stage pipeline instead (see "RECOMMENDED" section above).

### "Table 'entity_relationships' already defined"

**Cause**: Duplicate model definition (now fixed).

**Fix**: Update your code - models in `models_entity.py` have been disabled.

### "Cannot import Entity from models_entity"

**Cause**: Old model classes disabled to prevent conflicts.

**Fix**: Use models from `shared.models.models`:
- Use `CanonicalEntity` instead of `Entity`
- Use `RawEntity` for raw extractions
- Use `DailyEntityMention` for daily tracking

---

## Next Steps

1. **Run Stage 1A & 1B** on your dataset (these work now)
2. **Implement Stage 1C** - Critical blocker, use event script as template
3. **Implement Stage 2** - Entity consolidation across dataset
4. **Build visualizations** - Entity networks, timelines, influence graphs

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for detailed implementation checklist.

---

**Last Updated**: 2026-01-28
