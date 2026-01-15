# Entity Extraction Pipeline - Implementation Status

## ✅ Completed

### Database Models ([shared/models/models.py](../../../shared/models/models.py))

All entity extraction database models have been added:

1. **EntityTypeEnum** - Entity type classification (person, organization, company, location, other)
2. **EntityRoleEnum** - Role classification (government_official, diplomat, business_leader, etc.)
3. **RawEntity** - Raw entity mentions from documents (many-to-many with documents)
4. **EntityCluster** - Daily clustering results (Stage 1B output)
5. **CanonicalEntity** - Canonical entity representations with master-child hierarchy
6. **DailyEntityMention** - Daily entity activity tracking
7. **EntityRelationship** - Directed relationships between entities (graph edges)

**Features**:
- Full SQLAlchemy 2.0 compliance with type hints
- PostgreSQL-specific features (ARRAY, JSONB, UUID)
- Comprehensive indexes for query performance
- Relationships configured with cascade delete
- Master-child hierarchy for entity resolution
- Check constraints for data integrity

### Pipeline Scripts

#### [services/pipeline/entities/extract_daily_entities.py](extract_daily_entities.py) ✅
**Stage 1A: Extract entities from documents**

- LLM-based entity extraction from `documents.distilled_text`
- Extracts 4 entity types: persons, organizations, companies, locations
- Contextual information capture (roles, affiliations, snippets)
- PostgreSQL UPSERT for handling duplicates
- Batch processing with configurable commit frequency
- Status reporting and force reprocessing mode

**Usage**:
```bash
python services/pipeline/entities/extract_daily_entities.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31
```

#### [services/pipeline/entities/cluster_daily_entities.py](cluster_daily_entities.py) ✅
**Stage 1B: Cluster entity mentions per day**

- DBSCAN clustering on entity name embeddings
- Processes entities separately by type
- SentenceTransformer embeddings (all-MiniLM-L6-v2)
- Tighter clustering parameters (eps=0.12 vs 0.15 for events)
- Batch organization for LLM processing
- Centroid calculation and representative name selection

**Usage**:
```bash
python services/pipeline/entities/cluster_daily_entities.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31
```

### Documentation

#### [services/pipeline/entities/README.md](README.md) ✅
Comprehensive documentation including:
- Complete architecture overview
- Database schema documentation
- Usage examples for all scripts
- Query examples (SQL)
- Design patterns and best practices
- Troubleshooting guide
- Complete processing workflow

---

## 🚧 Remaining Implementation

### Stage 1C: LLM Entity Deconfliction

**Script**: `llm_deconflict_entity_clusters.py`

**Purpose**: LLM validates entity clusters and creates canonical entities

**Key Features Needed**:
- Load entity_clusters where `llm_deconflicted = FALSE`
- LLM prompt for name variation detection
  - Handles: "Wang Yi" = "Chinese FM Wang Yi" = "FM Wang"
  - Handles: "CNOOC" = "China National Offshore Oil Corporation"
  - Disambiguates: Different people with same surname
- Atomic operations with savepoints (canonical_entity + daily_entity_mention pair)
- Checkpoint/resume functionality (commit every 10 clusters)
- Embedding generation for canonical entity names

**LLM Prompt Pattern**:
```
Clustered Entities:
1. Wang Yi
2. Chinese Foreign Minister Wang Yi
3. FM Wang

Task: Identify which names refer to the SAME real-world entity.
Return canonical_name, entity_names[], primary_role, country_affiliation
```

---

### Stage 2A: Entity Consolidation

**Script**: `consolidate_all_entities.py`

**Purpose**: Find same entity across entire dataset using embeddings

**Key Features Needed**:
- Load ALL canonical_entities for country (not date-filtered)
- Compute pairwise cosine similarity matrix (chunked for memory)
- Find connected components using threshold (0.88)
- Create master-child hierarchy:
  - Master: Most mentioned entity in group
  - Children: Point to master via `master_entity_id`
- Process separately by entity type
- Memory-efficient chunking (avoid OOM with large matrices)

**Pattern from Events**: Based on `consolidate_all_events.py`

---

### Stage 2B: LLM Validate Consolidation

**Script**: `llm_deconflict_canonical_entities.py`

**Purpose**: LLM validates entity groupings and picks best canonical name

**Key Features Needed**:
- For each master entity with children:
  - Send all entity names + metadata to LLM
  - LLM validates they're the same entity
  - LLM picks best canonical name
  - Splits groups if incorrectly merged
- Checkpoint/resume (commit every 10 groups)
- Mark `llm_validated = TRUE`

**LLM Prompt Pattern**:
```
Entities grouped as same entity:
1. Wang Yi (23 mentions, 2024-08-01 to 2024-12-31)
2. Chinese Foreign Minister Wang Yi (45 mentions, 2024-08-15 to 2024-12-30)

Verify: Are these the SAME real-world entity?
If yes: Pick best canonical name
If no: Split into separate entities and explain why
```

---

### Stage 2C: Merge Canonical Entities

**Script**: `merge_canonical_entities.py`

**Purpose**: Consolidate daily_entity_mentions into master entities

**Key Features Needed**:
- For each master entity:
  - Reassign all daily_entity_mentions from children to master
  - Handle date conflicts (merge document counts)
  - Merge metadata: categories, recipients, activities
  - Update master entity stats (total_documents, date ranges)
  - Delete empty child canonical_entities
- Dry-run mode for preview
- Process by entity type

**Pattern from Events**: Based on `merge_canonical_events.py`

---

### Relationship Extraction

**Script**: `extract_entity_relationships.py`

**Purpose**: Extract relationships between entities for graph visualization

**Key Features Needed**:
- Query documents where multiple canonical entities co-occur
- LLM extracts relationship types:
  - person-person: works_with, colleague
  - person-org: employed_by, leads, represents
  - org-org: partnered_with, subsidiary_of
  - entity-location: located_in, visited, based_in
- Create/update entity_relationships records
- Track co-occurrence counts and date ranges
- Minimum co-occurrence threshold (filter weak connections)

**LLM Prompt Pattern**:
```
Document excerpt:
"Foreign Minister Wang Yi met with CEO of China Atomic Energy Company at the Ministry of Foreign Affairs in Beijing to discuss nuclear cooperation..."

Entities mentioned:
1. Wang Yi (person)
2. China Atomic Energy Company (company)
3. Ministry of Foreign Affairs (organization)
4. Beijing (location)

Extract relationships between these entities.
Return: entity_from, entity_to, relationship_type, description
```

---

## 📋 Next Steps

### 1. Create Alembic Migration

```bash
# Create migration for entity tables
alembic revision --autogenerate -m "add entity extraction tables"

# Review generated migration in alembic/versions/
# Verify:
# - All 6 entity tables created
# - Enums created correctly
# - Indexes created
# - Foreign keys set up

# Apply migration
alembic upgrade head

# Verify tables
psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt *entit*"
```

### 2. Test Stage 1 (One Month)

```bash
# Test extraction
python services/pipeline/entities/extract_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Test clustering
python services/pipeline/entities/cluster_daily_entities.py \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Implement and test Stage 1C
# (llm_deconflict_entity_clusters.py)
```

### 3. Implement Remaining Scripts

Priority order:
1. **llm_deconflict_entity_clusters.py** (Stage 1C) - Completes Stage 1
2. **consolidate_all_entities.py** (Stage 2A) - Starts Stage 2
3. **llm_deconflict_canonical_entities.py** (Stage 2B) - Validates Stage 2
4. **merge_canonical_entities.py** (Stage 2C) - Completes Stage 2
5. **extract_entity_relationships.py** - Graph building

### 4. Build Visualizations

- Export entity graph to GraphML/JSON
- Create entity timeline visualizations
- Build influence network dashboards
- Integrate with existing event visualizations

---

## 🔗 Reference Files

### Completed
- [shared/models/models.py](../../../shared/models/models.py) - Database models
- [services/pipeline/entities/extract_daily_entities.py](extract_daily_entities.py) - Stage 1A
- [services/pipeline/entities/cluster_daily_entities.py](cluster_daily_entities.py) - Stage 1B
- [services/pipeline/entities/README.md](README.md) - Documentation

### Templates to Reference
- `services/pipeline/events/llm_deconflict_clusters.py` - Template for Stage 1C
- `services/pipeline/events/consolidate_all_events.py` - Template for Stage 2A
- `services/pipeline/events/llm_deconflict_canonical_events.py` - Template for Stage 2B
- `services/pipeline/events/merge_canonical_events.py` - Template for Stage 2C

### Key Differences from Events
- **Clustering**: Separate processing by entity_type (person, org, company, location)
- **Epsilon**: Tighter clustering (0.12 vs 0.15) - entity names less varied
- **Similarity**: Stricter consolidation (0.88 vs 0.85) - entity resolution more critical
- **LLM Focus**: Name disambiguation vs event lifecycle stages
- **Additional**: Relationship extraction for graph building

---

## 📊 Expected Outputs

### After Stage 1
- `raw_entities`: ~50,000-100,000 entity mentions (for 5 months)
- `entity_clusters`: ~20,000-40,000 clusters
- `canonical_entities`: ~10,000-20,000 unique entities
- `daily_entity_mentions`: ~30,000-50,000 daily mentions

### After Stage 2
- `canonical_entities` (masters only): ~5,000-10,000 unique entities
- Consolidation ratio: ~50% (many entities appear across multiple days/docs)

### After Relationship Extraction
- `entity_relationships`: ~20,000-50,000 relationships
- Graph density: ~2-5 connections per entity on average

---

## ⚠️ Important Notes

1. **Database Migration Required**: Run Alembic migration before processing
2. **LLM Costs**: Entity extraction is LLM-intensive - monitor API costs
3. **Memory**: Consolidation scripts may need 8-16GB RAM for large datasets
4. **Processing Time**: Full pipeline for 5 months may take 12-24 hours
5. **Checkpointing**: All scripts support resume - safe to interrupt and restart

---

## 🎯 Success Criteria

✅ **Stage 1 Complete When**:
- All documents have entities extracted
- Entity clusters created for all dates
- Canonical entities created with daily mentions
- Full traceability: canonical_entity → daily_mentions → documents

✅ **Stage 2 Complete When**:
- Entity resolution complete (master-child hierarchy)
- LLM validation at 100%
- Daily mentions consolidated to masters
- No orphaned canonical_entities

✅ **Graph Building Complete When**:
- Co-occurring entities identified
- Relationships extracted and categorized
- Graph exportable for visualization
- Entity influence scores calculable
