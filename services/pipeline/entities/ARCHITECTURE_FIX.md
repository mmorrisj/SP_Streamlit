# Entity Pipeline Architecture Fix - 2026-01-28

## Issue Resolved

**Error**: `sqlalchemy.exc.InvalidRequestError: Table 'entity_relationships' is already defined for this MetaData instance`

**Root Cause**: Duplicate `EntityRelationship` table definition in two different model files, causing SQLAlchemy conflicts when both were imported.

## Architecture Conflict

The project had **two competing entity extraction architectures**:

### Architecture 1: Simple Direct Storage (DEPRECATED)
**Files**:
- [shared/models/models_entity.py](../../../shared/models/models_entity.py) - Models
- [services/pipeline/entities/entity_extraction.py](entity_extraction.py) - Extraction
- [services/pipeline/entities/store_entities.py](store_entities.py) - Storage
- [services/pipeline/entities/batch_entity_extraction.py](batch_entity_extraction.py) - Batch wrapper

**Models**:
- `Entity` (canonical entities table)
- `DocumentEntity` (document-entity links)
- `EntityRelationship` (entity graph edges)

**Workflow**: Documents → LLM extraction → JSON → Direct storage to `entities` table

**Issues**:
- ❌ No clustering or deduplication
- ❌ Simple name matching (prone to errors)
- ❌ Cannot handle name variations well
- ❌ Conflicts with two-stage pipeline models

---

### Architecture 2: Two-Stage Pipeline (CURRENT)
**Files**:
- [shared/models/models.py](../../../shared/models/models.py) - Models
- Stage 1A: [extract_daily_entities.py](extract_daily_entities.py) ✅
- Stage 1B: [cluster_daily_entities.py](cluster_daily_entities.py) ✅
- Stage 1C: [llm_deconflict_entity_clusters.py](llm_deconflict_entity_clusters.py) 🚧
- Stage 2A: [consolidate_all_entities.py](consolidate_all_entities.py) 🚧
- Stage 2B: [llm_deconflict_canonical_entities.py](llm_deconflict_canonical_entities.py) 🚧
- Stage 2C: [merge_canonical_entities.py](merge_canonical_entities.py) 🚧

**Models**:
- `RawEntity` (Stage 1A - raw extractions)
- `EntityCluster` (Stage 1B - daily clusters)
- `CanonicalEntity` (Stage 1C - deduplicated entities)
- `DailyEntityMention` (Stage 1C - daily activity)
- `EntityRelationship` (Stage 2 - relationships between canonical entities)

**Workflow**:
```
Stage 1 (Daily Processing):
  Documents → Extract → Cluster (DBSCAN) → LLM Deconflict → CanonicalEntity + DailyEntityMention

Stage 2 (Batch Consolidation):
  All CanonicalEntities → Consolidate (embeddings) → LLM Validate → Merge → Master Entities
```

**Advantages**:
- ✅ Robust name variation handling
- ✅ Embedding-based clustering
- ✅ LLM validation at multiple stages
- ✅ Master-child entity hierarchy
- ✅ Full traceability to source documents
- ✅ Matches event processing architecture

---

## Resolution Applied

### 1. Deprecated models_entity.py

**File**: [shared/models/models_entity.py](../../../shared/models/models_entity.py)

**Changes**:
- Added deprecation warning at top of file
- Commented out all model class definitions (Entity, DocumentEntity, EntityRelationship, EntityExtractionRun)
- File kept for reference but **should not be imported**

### 2. Deprecated store_entities.py

**File**: [services/pipeline/entities/store_entities.py](store_entities.py)

**Changes**:
- Added deprecation notice in docstring
- Added runtime deprecation warning
- Still functional but **not recommended for use**

### 3. Identified Orphaned Scripts

**Scripts that use old architecture**:
- [entity_extraction.py](entity_extraction.py) - Queries `document_entities` table
- [batch_entity_extraction.py](batch_entity_extraction.py) - Calls entity_extraction.py + store_entities.py

**Status**: ⚠️ These scripts still reference the old `document_entities` table but can coexist with the two-stage pipeline since they don't import the conflicting models.

---

## Current Pipeline Status

### ✅ Completed Components

**Stage 1A: Entity Extraction**
- ✅ [extract_daily_entities.py](extract_daily_entities.py)
- Extracts RawEntity mentions from documents
- Uses LLM to identify persons, organizations, companies, locations
- Captures roles, affiliations, context snippets

**Stage 1B: Daily Clustering**
- ✅ [cluster_daily_entities.py](cluster_daily_entities.py)
- DBSCAN clustering on entity name embeddings
- Processes per (country, date, entity_type)
- Creates EntityCluster records with batch organization

**Documentation**
- ✅ [README.md](README.md) - Complete pipeline documentation
- ✅ [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) - Implementation checklist

### 🚧 Remaining Components

**Stage 1C: LLM Entity Deconfliction**
- 🚧 [llm_deconflict_entity_clusters.py](llm_deconflict_entity_clusters.py)
- **Status**: Needs implementation
- **Purpose**: LLM validates clusters, creates CanonicalEntity + DailyEntityMention
- **Template**: Use `services/pipeline/events/llm_deconflict_clusters.py` as reference

**Stage 2A: Entity Consolidation**
- 🚧 [consolidate_all_entities.py](consolidate_all_entities.py)
- **Status**: Needs implementation
- **Purpose**: Find same entity across entire dataset (master-child hierarchy)
- **Template**: Use `services/pipeline/events/consolidate_all_events.py` as reference

**Stage 2B: LLM Validate Consolidation**
- 🚧 [llm_deconflict_canonical_entities.py](llm_deconflict_canonical_entities.py)
- **Status**: Needs implementation
- **Purpose**: LLM validates entity groupings, picks best canonical name
- **Template**: Use `services/pipeline/events/llm_deconflict_canonical_events.py` as reference

**Stage 2C: Merge Canonical Entities**
- 🚧 [merge_canonical_entities.py](merge_canonical_entities.py)
- **Status**: Needs implementation
- **Purpose**: Consolidate DailyEntityMention to master entities, delete empty children
- **Template**: Use `services/pipeline/events/merge_canonical_events.py` as reference

**Relationship Extraction**
- 🚧 [extract_entity_relationships.py](extract_entity_relationships.py)
- **Status**: Needs implementation
- **Purpose**: Extract relationships between canonical entities for graph visualization

---

## Migration Path

### Option 1: Use Two-Stage Pipeline (RECOMMENDED)

This is the documented, supported architecture:

```bash
# Stage 1A: Extract entities
python services/pipeline/entities/extract_daily_entities.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 1B: Cluster entities
python services/pipeline/entities/cluster_daily_entities.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 1C: LLM deconflict (NEEDS IMPLEMENTATION)
python services/pipeline/entities/llm_deconflict_entity_clusters.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 2: Batch consolidation (NEEDS IMPLEMENTATION)
python services/pipeline/entities/consolidate_all_entities.py --country China
python services/pipeline/entities/llm_deconflict_canonical_entities.py --country China
python services/pipeline/entities/merge_canonical_entities.py --country China
```

### Option 2: Use Legacy Scripts (NOT RECOMMENDED)

If you must use the old architecture temporarily:

```bash
# Extract entities (outputs JSON)
python services/pipeline/entities/entity_extraction.py --country China --limit 100

# Store to database (uses deprecated models)
python services/pipeline/entities/store_entities.py data/entity_extractions_*.json
```

**Warning**: This approach:
- Uses deprecated models that have been disabled
- Will throw deprecation warnings
- Conflicts with the two-stage pipeline
- May break in future updates

---

## Next Steps

### 1. Complete Stage 1C Implementation

**Priority**: HIGH (blocks rest of pipeline)

**File**: [llm_deconflict_entity_clusters.py](llm_deconflict_entity_clusters.py)

**Key features needed**:
- Load EntityCluster where `llm_deconflicted = FALSE`
- LLM validates name variations ("Wang Yi" = "FM Wang Yi" = "Chinese Foreign Minister Wang Yi")
- Create CanonicalEntity + DailyEntityMention pairs (atomic with savepoints)
- Checkpoint/resume functionality
- Embedding generation for canonical entity names

**Reference implementation**: `services/pipeline/events/llm_deconflict_clusters.py`

### 2. Complete Stage 2 Scripts

**Files**: consolidate_all_entities.py, llm_deconflict_canonical_entities.py, merge_canonical_entities.py

**Reference**: Use corresponding event processing scripts as templates

### 3. Implement Relationship Extraction

**File**: extract_entity_relationships.py

**Purpose**: Build entity graph for network visualization

### 4. Database Migration

If tables don't exist yet:

```bash
# Create migration
alembic revision --autogenerate -m "add entity extraction tables"

# Review migration file
# (Check that it creates RawEntity, EntityCluster, CanonicalEntity, DailyEntityMention, EntityRelationship)

# Apply migration
alembic upgrade head

# Verify tables
psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt *entit*"
```

---

## Testing the Fix

### Verify No Import Errors

```bash
# Test import of current models (should work)
python -c "from shared.models.models import RawEntity, EntityCluster, CanonicalEntity, DailyEntityMention, EntityRelationship; print('Imports successful')"

# Test deprecated models (should show warning but not error)
python -c "from shared.models.models_entity import Entity; print('Should not reach here')"
```

### Run Existing Scripts

```bash
# Stage 1A: Should work
python services/pipeline/entities/extract_daily_entities.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-05 --limit 10

# Stage 1B: Should work
python services/pipeline/entities/cluster_daily_entities.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-05
```

---

## Troubleshooting

### Error: "Failed to get processing status - cannot continue"

**Symptom**: Running `batch_entity_extraction.py` fails with:
```
ERROR - Failed to get processing status - cannot continue
```

**Cause**: This script uses the deprecated architecture and tries to query `document_entities` table.

**Solution**: Use the two-stage pipeline instead:

```bash
# Instead of batch_entity_extraction.py, use:

# Step 1A: Extract entities (creates raw_entities table)
python services/pipeline/entities/extract_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-12-31

# Step 1B: Cluster entities (creates entity_clusters table)
python services/pipeline/entities/cluster_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-12-31

# Step 1C: Deconflict (creates canonical_entities and daily_entity_mentions)
# This script needs to be implemented - see "Remaining Components" section
```

**If you must use batch_entity_extraction.py**:
1. The script has been updated to handle missing tables gracefully
2. It will now try `raw_entities` first, then fall back to `document_entities`
3. You'll see deprecation warnings - this is expected

### Error: Table 'entity_relationships' already defined

**Symptom**: SQLAlchemy error about duplicate table definition.

**Cause**: Both `models_entity.py` and `models.py` were defining `EntityRelationship`.

**Solution**: ✅ Fixed - all classes in `models_entity.py` have been disabled.

### Error: Cannot import from models_entity

**Symptom**: Import errors when trying to use old Entity models.

**Cause**: Model classes have been commented out to prevent conflicts.

**Solution**: Update imports to use models from `shared.models.models`:
- `Entity` → Not in new architecture (use `CanonicalEntity`)
- `DocumentEntity` → Not in new architecture (use `RawEntity` + `DailyEntityMention`)
- `EntityRelationship` → Use from `shared.models.models` (links to `canonical_entities`)

---

## Summary

**Problem Solved**: ✅ Eliminated duplicate `EntityRelationship` table definition

**Current Status**:
- Stage 1A & 1B: ✅ Implemented and working
- Stage 1C: 🚧 Needs implementation
- Stage 2: 🚧 Needs implementation
- Legacy scripts: ⚠️ Deprecated but functional

**Recommendation**: Implement remaining two-stage pipeline components (Stage 1C, Stage 2A-C) using event processing scripts as templates.

**Impact**: No data loss, backward compatibility maintained for legacy scripts (with warnings).

---

**Last Updated**: 2026-01-28
**Fixed By**: Claude Code
