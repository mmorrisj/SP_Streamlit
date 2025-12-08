# Event Processing Architecture

## Overview

This document describes the **actual implemented architecture** for event processing in the Soft Power Analytics system.

The system uses a **two-stage batch consolidation approach** where daily events are first clustered and deconflicted on a per-day basis, then consolidated across the entire dataset temporally.

## Design Philosophy

The architecture was designed with these principles:

1. **Separation of Concerns**: Daily clustering handles same-day deduplication; batch consolidation handles temporal linking
2. **Full Dataset Context**: Temporal consolidation benefits from seeing all events at once
3. **Multiple Validation Passes**: LLM validation at both daily and batch stages ensures quality
4. **Traceability**: All events can be linked back to original source documents

## Pipeline Stages

### Stage 1: Daily Event Detection

Daily processing creates canonical events from raw document events for each day.

#### 1A: Cluster Same-Day Events
**Script**: [`batch_cluster_events.py`](batch_cluster_events.py)

**Purpose**: Group similar raw events happening on the same day

**Process**:
1. Loads `raw_events` for a specific date and country
2. Generates embeddings using sentence-transformers (`all-MiniLM-L6-v2`)
3. Clusters events using DBSCAN (eps=0.15 for strict clustering)
4. Saves clusters to `event_clusters` table with batch numbers

**Database Tables**:
- **Input**: `raw_events` (from document analysis)
- **Output**: `event_clusters` (organized in batches for LLM processing)

**Key Parameter**: `eps=0.15` - Strict clustering to avoid merging distinct events

**Usage**:
```bash
python services/pipeline/events/batch_cluster_events.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31
```

#### 1B: LLM Deconfliction of Clusters
**Script**: [`llm_deconflict_clusters.py`](llm_deconflict_clusters.py)

**Purpose**: Validate and refine event clusters using LLM

**Process**:
1. Loads unprocessed `event_clusters` (where `llm_deconflicted = FALSE`)
2. For each cluster, asks LLM: "Are these events the same or different?"
3. LLM can:
   - Confirm cluster represents single event
   - Split cluster into multiple distinct events
   - Pick best canonical name from event descriptions
4. Creates `canonical_events` records (one per unique event)
5. Creates `daily_event_mentions` linking events to source documents by date
6. Generates embeddings for each canonical event
7. Marks `event_clusters.llm_deconflicted = TRUE`

**Database Tables**:
- **Input**: `event_clusters` (from Stage 1A)
- **Output**:
  - `canonical_events` - Unique events identified per day
  - `daily_event_mentions` - Links events to doc_ids by date

**Important**: Each daily cluster creates a NEW canonical event. Events are NOT linked across days at this stage (by design).

**Usage**:
```bash
python services/pipeline/events/llm_deconflict_clusters.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31
```

**Result**: After Stage 1, you have canonical events with daily mentions, but no temporal linking yet.

---

### Stage 2: Batch Consolidation (Temporal Linking)

Batch consolidation groups canonical events across the entire dataset to create multi-day master events.

#### 2A: Consolidate Canonical Events
**Script**: [`consolidate_all_events.py`](consolidate_all_events.py)

**Purpose**: Group canonical events across entire dataset using embedding similarity

**Process**:
1. Loads **ALL** canonical_events for a country (no date filtering)
2. Generates embeddings if not present
3. Computes pairwise cosine similarity between embeddings
4. Finds connected components using threshold (≥0.85)
5. For each group:
   - Picks event with highest article count as master
   - Sets `master_event_id = NULL` for master
   - Sets `master_event_id = master.id` for children

**Database Tables**:
- **Input**: `canonical_events` (from Stage 1B)
- **Output**: Updates `canonical_events.master_event_id`

**Key Concepts**:
- **Master Events**: `master_event_id IS NULL`
- **Child Events**: `master_event_id` points to master event ID
- **Hierarchy**: Creates parent-child relationships for temporal consolidation

**Usage**:
```bash
python services/pipeline/events/consolidate_all_events.py --influencers
python services/pipeline/events/consolidate_all_events.py --country China
```

**Typical Results**:
- Processes 70,000+ canonical events
- Creates 5,000-6,000 event groups
- Updates 14,000+ records with master_event_id

#### 2B: LLM Validation of Consolidation
**Script**: [`llm_deconflict_canonical_events.py`](llm_deconflict_canonical_events.py)

**Purpose**: Use LLM to validate that grouped events truly represent the same real-world event

**Process**:
1. Loads all event groups (events with same `master_event_id`)
2. For each group, asks LLM:
   - "Do these events represent the same real-world event?"
   - "What is the best canonical name?"
   - "Should this group be split?"
3. LLM can:
   - **Confirm**: Events are same, pick best name
   - **Rename**: Update `canonical_name` to best option
   - **Split**: Break group into subgroups with new masters

**Splitting Logic**:
When LLM identifies that a group contains multiple distinct events:
1. LLM returns subgroups with indices and canonical names
2. Script creates new master for each subgroup
3. Re-assigns `master_event_id` for each subgroup's events
4. Result: One incorrectly merged group → Multiple correct groups

**Usage**:
```bash
python services/pipeline/events/llm_deconflict_canonical_events.py --influencers
```

**Typical Results**:
- Processes 5,000-6,000 event groups
- Confirms most groups are correct
- Renames ~100-200 events to better canonical names
- Splits ~10-50 incorrectly merged groups

#### 2C: Merge Daily Mentions
**Script**: [`merge_canonical_events.py`](merge_canonical_events.py)

**Purpose**: Consolidate `daily_event_mentions` to create true multi-day events

**Why This Step is Necessary**:
After Stage 2B, you have:
- Master events with `master_event_id = NULL`
- Child events with `master_event_id = master.id`
- But each canonical event still has its own separate `daily_event_mentions`

This step **consolidates** all daily mentions from children into their master events.

**Process**:
1. For each master event:
   - Find all child events (`master_event_id = master.id`)
   - Reassign all `daily_event_mentions` from children to master
   - Handle date conflicts by merging article counts
   - Delete empty child canonical events
2. Result: Master events now have daily mentions spanning multiple days

**Conflict Handling**:
```python
if master already has mention for date X:
    new_count = master_count + child_count
    UPDATE master mention with new_count
    DELETE child mention
else:
    UPDATE child mention SET canonical_event_id = master.id
```

**Usage**:
```bash
python services/pipeline/events/merge_canonical_events.py --influencers
python services/pipeline/events/merge_canonical_events.py --country China
```

**Typical Results**:
- Processes 55,000+ master events
- Merges 42,000+ child events
- Reassigns 42,000+ daily mentions
- Creates 10,000+ multi-day events

---

## Database Schema

### Tables Created by Daily Processing (Stage 1)

**event_clusters**
- `id` - Cluster identifier
- `country` - Initiating country
- `cluster_date` - Date of events in cluster
- `batch_number` - Batch number for LLM processing
- `events` - JSONB array of raw event data
- `llm_deconflicted` - Boolean flag (FALSE → pending, TRUE → processed)

**canonical_events**
- `id` - Unique event identifier
- `canonical_name` - Standardized event name
- `initiating_country` - Country initiating the event
- `embedding_vector` - Vector embedding for similarity matching
- `alternative_names` - JSONB array of alternate names
- `master_event_id` - NULL for masters, references parent for children
- `created_at` - Timestamp

**daily_event_mentions**
- `id` - Unique mention identifier
- `canonical_event_id` - References canonical_events
- `mention_date` - Date of mention
- `article_count` - Number of articles mentioning event on this date
- `doc_ids` - JSONB array of source document IDs

### Fields Used for Batch Consolidation (Stage 2)

**canonical_events.master_event_id**
- `NULL` → This is a master event
- `<id>` → This is a child event linked to master with ID `<id>`

**canonical_events.embedding_vector**
- Used for cosine similarity matching
- Generated during Stage 1B or Stage 2A if missing

### Final Result

After all stages complete:
- **Master events** (`master_event_id IS NULL`):
  - Have multiple days of `daily_event_mentions`
  - Represent consolidated multi-day events
  - Single canonical name (best name chosen by LLM)
- **Child events**:
  - All deleted after consolidation
- **Traceability**:
  - `daily_event_mentions.doc_ids` → `documents.doc_id`
  - Full chain: master event → daily mentions → source documents

---

## Why NOT Real-Time Temporal Linking?

The codebase contains [`news_event_tracker.py`](_archived/news_event_tracker.py) (1106 lines) with sophisticated temporal linking logic:
- Context-aware lookback windows (3-90 days)
- Adaptive similarity thresholds
- Story arc coherence checking
- LLM temporal resolution for ambiguous cases

**However, this approach is NOT used** because:

1. **Daily clustering is simpler**: Focus on same-day deduplication without temporal complexity
2. **Batch consolidation has full context**: Can see all events at once for better matching
3. **Multiple validation passes**: LLM validates both daily clusters and temporal groupings
4. **Clearer separation of concerns**: Real-time vs. comprehensive consolidation

The two-stage approach is **working as designed**, not a temporary workaround.

---

## Common Misconceptions

### ❌ "Temporal linking is broken"
- **Reality**: Temporal linking was never the chosen architecture
- The two-stage batch consolidation is the intended design
- Daily events are correctly created separately per day (by design)

### ❌ "merge_canonical_events.py is a temporary fix"
- **Reality**: It's Stage 2C of the designed workflow
- Consolidating daily_event_mentions is the final step of batch consolidation
- This step creates the true multi-day event tracking capability

### ❌ "Events aren't being linked across days"
- **Reality**: They are - in Stage 2 via `master_event_id` hierarchy
- Daily processing intentionally creates separate canonical events per day
- Batch consolidation then links them temporally
- Result: Master events with mentions spanning days/weeks/months

### ❌ "The pipeline needs fundamental changes"
- **Reality**: The pipeline is working as designed
- All components serve their intended purpose
- Documentation was outdated, not the implementation

---

## Workflow Summary

```
Documents (S3)
    ↓
Document Ingestion (atom.py, dsr.py)
    ↓
AI Analysis (atom_extraction.py) → raw_events table
    ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 1: DAILY EVENT DETECTION                              │
├─────────────────────────────────────────────────────────────┤
│ batch_cluster_events.py                                     │
│   ↓ event_clusters table                                    │
│ llm_deconflict_clusters.py                                  │
│   ↓ canonical_events + daily_event_mentions                 │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 2: BATCH CONSOLIDATION (Temporal Linking)             │
├─────────────────────────────────────────────────────────────┤
│ consolidate_all_events.py                                   │
│   ↓ Sets master_event_id hierarchy                          │
│ llm_deconflict_canonical_events.py                          │
│   ↓ Validates groups, renames, splits                       │
│ merge_canonical_events.py                                   │
│   ↓ Consolidates daily_event_mentions                       │
└─────────────────────────────────────────────────────────────┘
    ↓
Master Events (multi-day, fully traceable to documents)
    ↓
Event Summaries (daily/weekly/monthly/yearly)
    ↓
Dashboard Visualization (Streamlit)
```

---

## Example: Event Lifecycle

**Day 1 (Aug 15)**: Iran announces Arbaeen border crossing opening
- `batch_cluster_events.py` creates cluster
- `llm_deconflict_clusters.py` creates canonical event: "Arbaeen Border Crossing Opening"
- `daily_event_mentions`: 1 entry for Aug 15

**Day 2 (Aug 16)**: Iran opens additional crossings
- `batch_cluster_events.py` creates NEW cluster (separate day)
- `llm_deconflict_clusters.py` creates NEW canonical event: "Arbaeen Additional Crossings"
- `daily_event_mentions`: 1 entry for Aug 16

**Day 3-56**: Coverage continues across 56 days
- Each day creates its own canonical event
- Result: 56 separate canonical events, each with 1 day of mentions

**Batch Consolidation**:
1. `consolidate_all_events.py`: Groups all 56 events (similar embeddings)
   - Picks event with most articles as master
   - Sets `master_event_id` for other 55 events
2. `llm_deconflict_canonical_events.py`: Validates grouping
   - Confirms all are same event
   - Picks "Arbaeen Pilgrimage" as best canonical name
3. `merge_canonical_events.py`: Consolidates mentions
   - Reassigns all daily_event_mentions to master
   - Deletes 55 empty child events
   - Result: 1 master event with 56 days of mentions

**Final Result**: "Arbaeen Pilgrimage" master event spanning 56 days with full traceability to source documents

---

## Stage 3: Materiality Scoring (Optional)

After batch consolidation creates multi-day master events, you can score their materiality.

#### 3: Score Canonical Event Materiality
**Script**: [`score_canonical_event_materiality.py`](score_canonical_event_materiality.py)

**Purpose**: Assign materiality scores (1-10) to canonical events measuring concrete/substantive nature versus symbolic/rhetorical gestures

**Why This Matters**: Enables tracking the materiality of specific initiatives over their entire lifecycle, distinguishing between:
- High-materiality events (7-10): Infrastructure projects, financial commitments, tangible deliverables
- Mixed materiality (4-6): Agreements with unclear implementation, capacity building
- Low-materiality events (1-3): Symbolic statements, cultural events without concrete commitments

**Process**:
1. Loads master canonical events (WHERE master_event_id IS NULL)
2. Formats event data: consolidated_description, key_facts, categories, recipients
3. LLM scores each event on 1-10 scale using specialized materiality prompt
4. Saves material_score and material_justification to canonical_events table

**Database Fields Added**:
- `canonical_events.material_score` - NUMERIC(3,1) score from 1.0 to 10.0
- `canonical_events.material_justification` - TEXT explanation of score

**Usage**:
```bash
# Score all canonical events for a country
python services/pipeline/events/score_canonical_event_materiality.py --country China

# Score all influencer countries
python services/pipeline/events/score_canonical_event_materiality.py --influencers

# Only score events with 3+ days of mentions (recommended for initial run)
python services/pipeline/events/score_canonical_event_materiality.py --influencers --min-days 3

# Rescore existing events
python services/pipeline/events/score_canonical_event_materiality.py --country China --rescore

# Test without saving to database
python services/pipeline/events/score_canonical_event_materiality.py --country China --dry-run
```

**Example Scores**:
- Al-Abdaliya Photovoltaic Project: 8.0 - "Major infrastructure project with renewable energy deliverables"
- Beijing-hosted Saudi-Iranian rapprochement: 6.5 - "Significant diplomatic engagement with economic potential"
- Arbaeen Pilgrimage Hospitality: 3.0 - "Primarily symbolic gesture of goodwill and cultural diplomacy"

**Typical Results**:
- ~71,000 master canonical events across all influencers
- Most events have 1 day of mentions (single-day events)
- Multi-day events (3+ days) are higher value candidates for scoring
- Scoring rate: ~1-2 events per second (LLM API dependent)

---

## Performance Characteristics

### Stage 1 (Daily Processing)
- **Speed**: Fast (processes one day at a time)
- **Scalability**: Linear with daily event count
- **Typical**: 100-500 events/day per country
- **Runtime**: Minutes per day

### Stage 2A (Consolidation)
- **Speed**: Moderate (O(n²) similarity computation)
- **Scalability**: Quadratic with total event count
- **Typical**: 70,000 events → 5 minutes
- **Runtime**: 5-10 minutes per country

### Stage 2B (LLM Validation)
- **Speed**: Slow (LLM API calls)
- **Scalability**: Linear with group count
- **Typical**: 6,000 groups → 2-3 hours
- **Runtime**: 2-4 hours for all influencers
- **Optimization**: Batch processing, skip single-event groups

### Stage 2C (Merge Mentions)
- **Speed**: Fast (SQL operations)
- **Scalability**: Linear with child event count
- **Typical**: 42,000 children → 2 minutes
- **Runtime**: 2-5 minutes

---

## Future Enhancements

Potential improvements while maintaining the two-stage architecture:

1. **Incremental Batch Consolidation**: Only re-consolidate new events instead of entire dataset
2. **Adaptive Similarity Thresholds**: Use different thresholds for different event types
3. **Temporal Decay**: Weight recent events more heavily in similarity matching
4. **Story Arc Tracking**: Leverage some logic from `news_event_tracker.py` for lifecycle phases
5. **Parallel LLM Validation**: Process multiple groups concurrently to speed up Stage 2B

---

## Documentation and Support

**Related Documentation**:
- [`CLAUDE.md`](../../../CLAUDE.md) - Event processing commands and architecture overview
- [`PIPELINE.md`](../../../PIPELINE.md) - Step-by-step pipeline guide
- [`_archived/README.md`](_archived/README.md) - Why files were archived

**Script Locations**:
- Daily Processing: `services/pipeline/events/batch_cluster_events.py`, `llm_deconflict_clusters.py`
- Batch Consolidation: `services/pipeline/events/consolidate_all_events.py`, `llm_deconflict_canonical_events.py`, `merge_canonical_events.py`
- Materiality Scoring: `services/pipeline/events/score_canonical_event_materiality.py`

**Database Models**:
- `shared/models/models.py` - Canonical Events, Daily Event Mentions

---

**Last Updated**: December 2024
**Architecture Status**: Production (working as designed)
