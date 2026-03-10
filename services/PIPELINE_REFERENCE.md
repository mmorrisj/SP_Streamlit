# Pipeline Reference Guide

Complete workflow for processing documents, events, entities, and summaries into the database.

## Table of Contents

- [Quick Start: New Data Ingestion](#quick-start-new-data-ingestion)
- [Pipeline Overview](#pipeline-overview)
- [Database Models](#database-models)
- [Step 1: Document Ingestion](#step-1-document-ingestion)
- [Step 2: Document Embeddings](#step-2-document-embeddings)
- [Step 3: Event Pipeline - Stage 1 (Daily Clustering)](#step-3-event-pipeline---stage-1-daily-clustering)
- [Step 4: Event Pipeline - Stage 2 (Cross-Day Consolidation)](#step-4-event-pipeline---stage-2-cross-day-consolidation)
- [Step 5: Entity Pipeline - Stage 1 (Daily Extraction)](#step-5-entity-pipeline---stage-1-daily-extraction)
- [Step 6: Entity Pipeline - Stage 2 (Cross-Day Consolidation)](#step-6-entity-pipeline---stage-2-cross-day-consolidation)
- [Step 7: Entity Pipeline - Stage 3 (Relationships)](#step-7-entity-pipeline---stage-3-relationships)
- [Step 8: Summaries](#step-8-summaries)
- [Step 9: Event Summary Embeddings](#step-9-event-summary-embeddings)
- [Batch API Pipeline](#batch-api-pipeline)
- [Incremental vs Full Reprocessing](#incremental-vs-full-reprocessing)
- [Docker Commands](#docker-commands)

---

## Quick Start: New Data Ingestion

After receiving new DSR JSON files in `./data/`:

```bash
# Alias for convenience (add to ~/.bashrc)
alias sp-pipeline='docker compose -f docker-compose.preprocessing.yml run --rm preprocessing'

# 1. Ingest documents
sp-pipeline python services/pipeline/ingestion/dsr.py --source local

# 2. Embed new documents
sp-pipeline python services/pipeline/embeddings/embed_missing_documents.py --yes

# 3. Cluster events (new date range only)
sp-pipeline python services/pipeline/events/batch_cluster_events.py \
    --influencers --start-date 2026-02-01 --end-date 2026-02-28

# 4. Deconflict clusters (iterative)
sp-pipeline python services/pipeline/events/llm_deconflict_clusters.py \
    --influencers --start-date 2026-02-01 --end-date 2026-02-28

# 4. Deconflict clusters (batch - 50% cheaper)
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type cluster_deconflict --influencers --start-date 2026-02-01 --end-date 2026-02-28
sp-pipeline python services/pipeline/batch/batch_queue_runner.py --job-type cluster_deconflict
sp-pipeline python services/pipeline/batch/batch_process_all_results.py --job-type cluster_deconflict

# 5. Consolidate across all dates (must process full dataset)
sp-pipeline python services/pipeline/events/consolidate_all_events.py --influencers --force

# 6. Validate consolidation (iterative)
sp-pipeline python services/pipeline/events/llm_deconflict_canonical_events.py --influencers --resume

# 6. Validate consolidation (batch)
sp-pipeline python services/pipeline/batch/batch_prepare.py --job-type canonical_deconflict --influencers
sp-pipeline python services/pipeline/batch/batch_queue_runner.py --job-type canonical_deconflict
sp-pipeline python services/pipeline/batch/batch_process_all_results.py --job-type canonical_deconflict

# 7. Merge into multi-day events
sp-pipeline python services/pipeline/events/merge_canonical_events.py --influencers
```

---

## Pipeline Overview

```
                         ┌──────────────┐
                         │  DSR JSON    │
                         │  (S3/local)  │
                         └──────┬───────┘
                                │
                    ┌───────────▼───────────┐
                    │  Step 1: INGESTION    │
                    │  dsr.py               │
                    │  ─────────────────    │
                    │  → documents          │
                    │  → categories         │
                    │  → initiating_countries│
                    │  → recipient_countries │
                    │  → raw_events         │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Step 2: EMBEDDINGS   │
                    │  embed_missing_docs   │
                    │  ─────────────────    │
                    │  → langchain_pg_*     │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┴─────────────────┐
              │                                     │
  ┌───────────▼───────────┐           ┌─────────────▼─────────────┐
  │  Step 3: EVENTS S1    │           │  Step 5: ENTITIES S1      │
  │  Cluster + Deconflict │           │  Extract + Cluster +      │
  │  ─────────────────    │           │  Deconflict               │
  │  → event_clusters     │           │  ─────────────────────    │
  │  → canonical_events   │           │  → raw_entities           │
  │  → daily_event_mentions│          │  → entity_clusters        │
  └───────────┬───────────┘           │  → canonical_entities     │
              │                        │  → daily_entity_mentions  │
  ┌───────────▼───────────┐           └─────────────┬─────────────┘
  │  Step 4: EVENTS S2    │                         │
  │  Consolidate + Merge  │           ┌─────────────▼─────────────┐
  │  ─────────────────    │           │  Step 6: ENTITIES S2      │
  │  → master_event_id    │           │  Consolidate + Merge      │
  │  → llm_validated      │           │  ─────────────────────    │
  │  → multi-day events   │           │  → master_entity_id       │
  └───────────┬───────────┘           │  → multi-day entities     │
              │                        └─────────────┬─────────────┘
              │                                      │
              │                        ┌─────────────▼─────────────┐
              │                        │  Step 7: ENTITY RELS      │
              │                        │  Links + Co-occurrence     │
              │                        │  ─────────────────────    │
              │                        │  → entity_relationships   │
              │                        └─────────────┬─────────────┘
              │                                      │
              └─────────────────┬────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Step 8: SUMMARIES    │
                    │  Bilateral + Category │
                    │  ─────────────────    │
                    │  → bilateral_*        │
                    │  → event_summaries    │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Step 9: EMBED SUMM   │
                    │  embed_event_summaries│
                    └───────────────────────┘
```

---

## Database Models

All models defined in `shared/models/models.py`.

### Core Document Tables

| Table | PK | Purpose | Key Columns |
|-------|-----|---------|-------------|
| `documents` | `doc_id` (Text) | Central document store | `title`, `date`, `salience`, `salience_bool`, `category`, `initiating_country`, `recipient_country`, `distilled_text`, `event_name` |
| `categories` | (`doc_id`, `category`) | Normalized categories | FK → documents |
| `subcategories` | (`doc_id`, `subcategory`) | Normalized subcategories | FK → documents |
| `initiating_countries` | (`doc_id`, `initiating_country`) | Normalized initiating countries | FK → documents |
| `recipient_countries` | (`doc_id`, `recipient_country`) | Normalized recipient countries | FK → documents |
| `raw_events` | (`doc_id`, `event_name`) | Flattened event/project mentions | FK → documents |

### Event Tables

| Table | PK | Purpose | Key Status Flags |
|-------|-----|---------|-----------------|
| `event_clusters` | `id` (UUID) | DBSCAN cluster output per (country, date) | `llm_deconflicted` (False→True), `is_noise`, `processed` |
| `canonical_events` | `id` (UUID) | Resolved event entities | `master_event_id` (NULL=master), `llm_validated` (False→True) |
| `daily_event_mentions` | `id` (UUID) | Per-day event activity | `canonical_event_id` FK, `doc_ids` array |
| `event_summaries` | `id` (UUID) | Period-based aggregated summaries | `period_type` (daily/weekly/monthly/yearly), `status`, `canonical_event_id` FK |
| `period_summaries` | `id` (UUID) | Cross-event period aggregation | `period_type`, `initiating_country` |
| `event_source_links` | `id` (UUID) | Links event_summaries → documents | `event_summary_id`, `doc_id` |

**Event hierarchy:**
- Master event: `master_event_id IS NULL` — the canonical version spanning multiple days
- Child event: `master_event_id = <master_id>` — duplicate that gets merged into master

### Entity Tables

| Table | PK | Purpose | Key Status Flags |
|-------|-----|---------|-----------------|
| `raw_entities` | (`doc_id`, `entity_name`, `entity_type`) | Raw LLM-extracted entities | `role`, `country_affiliation` |
| `entity_clusters` | `id` (UUID) | DBSCAN cluster output per (country, date, type) | `llm_deconflicted` (False→True), `is_noise` |
| `canonical_entities` | `id` (UUID) | Resolved entity profiles | `master_entity_id` (NULL=master), `llm_validated`, `entity_type`, `primary_role` |
| `daily_entity_mentions` | `id` (UUID) | Per-day entity activity | `canonical_entity_id` FK, `doc_ids` array, `associated_event_ids` |
| `entity_relationships` | `id` (UUID) | Directed entity-to-entity edges | `relationship_type`, `co_occurrence_count` |

**Entity types** (EntityTypeEnum): PERSON, ORGANIZATION, COMPANY, LOCATION, OTHER
**Entity roles** (EntityRoleEnum): GOVERNMENT_OFFICIAL, DIPLOMAT, BUSINESS_LEADER, CULTURAL_FIGURE, MILITARY_OFFICIAL, ACADEMIC, MEDIA_FIGURE, CIVIL_SOCIETY, IMPLEMENTING_ORGANIZATION, FUNDING_ORGANIZATION, RECIPIENT_INSTITUTION, INFRASTRUCTURE_PROJECT, VENUE, OTHER

### Summary Tables

| Table | PK | Purpose |
|-------|-----|---------|
| `bilateral_relationship_summaries` | `id` (UUID) | One per country pair, AI-generated relationship analysis |
| `country_category_summaries` | `id` (UUID) | Category-level analysis per initiating country |
| `bilateral_category_summaries` | `id` (UUID) | Category-specific bilateral pair analysis |

### Infrastructure Tables

| Table | PK | Purpose |
|-------|-----|---------|
| `batch_jobs` | `id` (UUID) | OpenAI Batch API job tracking |
| `langchain_pg_collection` | `uuid` | Vector store collections |
| `langchain_pg_embedding` | `id` | Document/summary embeddings |

**Batch job lifecycle:** `preparing` → `submitted` → `in_progress` → `completed` → (process results) → `processed_at` set

---

## Step 1: Document Ingestion

**Script:** `services/pipeline/ingestion/dsr.py`
**Writes to:** `documents`, `categories`, `subcategories`, `initiating_countries`, `recipient_countries`, `raw_events`

```bash
# From local JSON files in ./data/
sp-pipeline python services/pipeline/ingestion/dsr.py --source local

# From S3
sp-pipeline python services/pipeline/ingestion/dsr.py --source s3

# Check processing status
sp-pipeline python services/pipeline/ingestion/dsr.py --status

# Without embeddings (faster, embed separately later)
sp-pipeline python services/pipeline/ingestion/dsr.py --source local --no-embed
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--source` | required | `local` or `s3` |
| `--no-embed` | False | Skip embedding step |
| `--relocate` | False | Move processed files to `./data/processed/` |
| `--reprocess` | False | Reprocess already-ingested files |
| `--doc-batch-size` | 100 | Documents per DB commit |
| `--embed-batch-size` | 50 | Documents per embedding batch |

**Incremental:** Yes. Checks `doc_id` existence before insert. Uses `ON CONFLICT DO NOTHING` for relationship tables. S3 mode tracks processed files via local tracker.

---

## Step 2: Document Embeddings

**Script:** `services/pipeline/embeddings/embed_missing_documents.py`
**Writes to:** `langchain_pg_embedding`, `langchain_pg_collection`

```bash
# Embed all missing documents
sp-pipeline python services/pipeline/embeddings/embed_missing_documents.py --yes

# Check status
sp-pipeline python services/pipeline/embeddings/embed_missing_documents.py --status

# Dry run
sp-pipeline python services/pipeline/embeddings/embed_missing_documents.py --dry-run
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--collection` | chunk_embeddings | LangChain collection name |
| `--batch-size` | 50 | Documents per batch |
| `--limit` | None | Max documents to process |
| `--yes` | False | Skip confirmation prompt |

**Incremental:** Yes. Only embeds documents not already in `langchain_pg_embedding`.

---

## Step 3: Event Pipeline - Stage 1 (Daily Clustering)

Creates canonical events from raw event mentions, one day at a time.

### Step 3A: DBSCAN Clustering

**Script:** `services/pipeline/events/batch_cluster_events.py`
**Reads:** `raw_events`, `documents` → **Writes:** `event_clusters`

```bash
sp-pipeline python services/pipeline/events/batch_cluster_events.py \
    --influencers --start-date 2026-02-01 --end-date 2026-02-28
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--country` | None | Single country |
| `--influencers` | False | All influencer countries from config |
| `--all-countries` | False | All countries in database |
| `--start-date` | None | Start of date range |
| `--end-date` | None | End of date range |
| `--date` | None | Single date |
| `--eps` | 0.15 | DBSCAN distance threshold |
| `--batch-size` | 150 | LLM batch organization size |
| `--force` | False | Reprocess dates that already have clusters |
| `--dry-run` | False | Preview without saving |

**Incremental:** Yes. Skips (country, date) pairs that already have clusters unless `--force`.
**Creates:** `event_clusters` with `processed=False`, `llm_deconflicted=False`.

### Step 3B: LLM Cluster Deconfliction

LLM validates each cluster, splits/merges as needed, creates canonical events.

**Script:** `services/pipeline/events/llm_deconflict_clusters.py`
**Reads:** `event_clusters` (where `llm_deconflicted=False`) → **Writes:** `canonical_events`, `daily_event_mentions`

#### Iterative (synchronous, full price)

```bash
sp-pipeline python services/pipeline/events/llm_deconflict_clusters.py \
    --influencers --start-date 2026-02-01 --end-date 2026-02-28
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--checkpoint-frequency` | 10 | Commit every N clusters (safe to interrupt) |
| `--dry-run` | False | Preview without saving |

#### Batch (asynchronous, 50% cheaper)

```bash
# 1. Prepare JSONL + queue batch jobs
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type cluster_deconflict --influencers \
    --start-date 2026-02-01 --end-date 2026-02-28

# 2. Submit to OpenAI + poll until complete
sp-pipeline python services/pipeline/batch/batch_queue_runner.py \
    --job-type cluster_deconflict

# 3. Apply results to database
sp-pipeline python services/pipeline/batch/batch_process_all_results.py \
    --job-type cluster_deconflict
```

**Incremental:** Yes. Only processes clusters where `llm_deconflicted=False`. Checkpointed.
**Sets:** `event_clusters.llm_deconflicted=True`, `event_clusters.refined_clusters` (JSONB).

---

## Step 4: Event Pipeline - Stage 2 (Cross-Day Consolidation)

Links canonical events across days into multi-day event threads.

### Step 4A: Embedding-Based Consolidation

**Script:** `services/pipeline/events/consolidate_all_events.py`
**Reads:** `canonical_events` → **Writes:** `canonical_events.master_event_id`

```bash
sp-pipeline python services/pipeline/events/consolidate_all_events.py --influencers --force
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--similarity-threshold` | 0.85 | Cosine similarity for grouping |
| `--force` | False | Reset all `master_event_id` to NULL before re-running |
| `--dry-run` | False | Preview without saving |

**WARNING:** Without `--force`, only processes events where `master_event_id IS NULL`. This can create fragmented groups if new events were added. Use `--force` after adding new data.

**Sets:** `master_event_id` on child events. Masters have `master_event_id IS NULL`.

### Step 4B: LLM Validation of Consolidation

**Script:** `services/pipeline/events/llm_deconflict_canonical_events.py`
**Reads:** `canonical_events` groups → **Writes:** `canonical_events.llm_validated`, may rename/swap/split

#### Iterative

```bash
sp-pipeline python services/pipeline/events/llm_deconflict_canonical_events.py \
    --influencers --resume
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--resume` | False | Skip already-validated groups |
| `--force` | False | Reprocess all groups |
| `--batch-size` | 10 | Commit every N groups |

#### Batch

```bash
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type canonical_deconflict --influencers
sp-pipeline python services/pipeline/batch/batch_queue_runner.py \
    --job-type canonical_deconflict
sp-pipeline python services/pipeline/batch/batch_process_all_results.py \
    --job-type canonical_deconflict
```

**Incremental:** Yes with `--resume`. Checks `llm_validated` on master events.
**Sets:** `llm_validated=True`, `llm_validated_at=NOW()`.

### Step 4C: Merge into Multi-Day Events

**Script:** `services/pipeline/events/merge_canonical_events.py`
**Reads:** validated masters with children → **Writes:** reassigns `daily_event_mentions`, deletes child `canonical_events`

```bash
sp-pipeline python services/pipeline/events/merge_canonical_events.py --influencers
```

**Requires:** `llm_validated=True` on master events (Step 4B must complete first).
**Incremental:** Safe to re-run. After merge, children are deleted so re-run is a no-op.

---

## Step 5: Entity Pipeline - Stage 1 (Daily Extraction)

Mirrors the event pipeline architecture for persons, organizations, companies, locations.

### Step 5A: Entity Extraction

**Script:** `services/pipeline/entities/extract_daily_entities.py`
**Reads:** `documents.distilled_text` → **Writes:** `raw_entities`

```bash
sp-pipeline python services/pipeline/entities/extract_daily_entities.py \
    --country China --start-date 2026-02-01 --end-date 2026-02-28

# Batch alternative
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type daily_entity_extract --country China \
    --start-date 2026-02-01 --end-date 2026-02-28
```

### Step 5B: Entity Clustering

**Script:** `services/pipeline/entities/cluster_daily_entities.py`
**Reads:** `raw_entities` → **Writes:** `entity_clusters`

```bash
sp-pipeline python services/pipeline/entities/cluster_daily_entities.py \
    --country China --start-date 2026-02-01 --end-date 2026-02-28
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--entity-type` | None | Filter by PERSON/ORGANIZATION/etc. |
| `--eps` | varies | DBSCAN threshold |
| `--min-samples` | varies | DBSCAN min cluster size |

### Step 5C: LLM Entity Deconfliction

**Script:** `services/pipeline/entities/llm_deconflict_entity_clusters.py`
**Reads:** `entity_clusters` (llm_deconflicted=False) → **Writes:** `canonical_entities`, `daily_entity_mentions`

```bash
# Iterative
sp-pipeline python services/pipeline/entities/llm_deconflict_entity_clusters.py \
    --country China --start-date 2026-02-01 --end-date 2026-02-28

# Batch
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type entity_deconflict --country China
sp-pipeline python services/pipeline/batch/batch_queue_runner.py --job-type entity_deconflict
sp-pipeline python services/pipeline/batch/batch_process_all_results.py --job-type entity_deconflict
```

---

## Step 6: Entity Pipeline - Stage 2 (Cross-Day Consolidation)

### Step 6A: Entity Embeddings

**Script:** `services/pipeline/entities/embed_canonical_entities.py`
**Writes:** `canonical_entities.embedding_vector`

```bash
sp-pipeline python services/pipeline/entities/embed_canonical_entities.py --influencers
```

### Step 6B: Embedding-Based Consolidation

**Script:** `services/pipeline/entities/consolidate_all_entities.py`
**Sets:** `canonical_entities.master_entity_id`

```bash
sp-pipeline python services/pipeline/entities/consolidate_all_entities.py --influencers --force
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--similarity-threshold` | 0.88 | Cosine similarity threshold |
| `--force` | False | Reset master_entity_id before re-running |

### Step 6C: LLM Validation

**Script:** `services/pipeline/entities/llm_deconflict_canonical_entities.py`

```bash
# Iterative
sp-pipeline python services/pipeline/entities/llm_deconflict_canonical_entities.py \
    --influencers --resume

# Batch
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type canonical_entity_deconflict --influencers
sp-pipeline python services/pipeline/batch/batch_queue_runner.py --job-type canonical_entity_deconflict
sp-pipeline python services/pipeline/batch/batch_process_all_results.py --job-type canonical_entity_deconflict
```

### Step 6D: Merge Entities

**Script:** `services/pipeline/entities/merge_canonical_entities.py`

```bash
sp-pipeline python services/pipeline/entities/merge_canonical_entities.py --influencers
```

---

## Step 7: Entity Pipeline - Stage 3 (Relationships)

### Step 7A: Link Entities to Events

**Script:** `services/pipeline/entities/link_entities_to_events.py`
**Writes:** `daily_entity_mentions.associated_event_ids`, `canonical_entities.associated_events`

```bash
sp-pipeline python services/pipeline/entities/link_entities_to_events.py --influencers
```

### Step 7B: Build Co-occurrence Network

**Script:** `services/pipeline/entities/build_entity_cooccurrence.py`
**Writes:** `entity_relationships` (type=co_occurrence)

```bash
sp-pipeline python services/pipeline/entities/build_entity_cooccurrence.py --influencers
```

### Step 7C: Generate Entity Descriptions

**Script:** `services/pipeline/entities/generate_entity_descriptions.py`
**Writes:** `canonical_entities.entity_description`, `.key_activities`

```bash
# Iterative
sp-pipeline python services/pipeline/entities/generate_entity_descriptions.py --influencers

# Batch
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type generate_entity_descriptions --influencers
```

### Step 7D: Classify Relationships

**Script:** `services/pipeline/entities/classify_entity_relationships.py`
**Writes:** `entity_relationships.relationship_type`, `.relationship_description`

```bash
# Iterative
sp-pipeline python services/pipeline/entities/classify_entity_relationships.py --influencers

# Batch
sp-pipeline python services/pipeline/batch/batch_prepare.py \
    --job-type classify_entity_relationships --influencers
```

**Relationship types:** works_with, employed_by, leads, partnered_with, located_in, visited, represents, signed_agreement_with, co_occurrence

---

## Step 8: Summaries

### Bilateral Relationship Summaries

**Script:** `services/pipeline/summaries/generate_bilateral_summaries.py`
**Writes:** `bilateral_relationship_summaries`

```bash
# Specific pair
sp-pipeline python services/pipeline/summaries/generate_bilateral_summaries.py \
    --init-country China --recipient-country Egypt

# All pairs for a country (min 500 docs)
sp-pipeline python services/pipeline/summaries/generate_bilateral_summaries.py \
    --init-country China --min-docs 500

# All major pairs
sp-pipeline python services/pipeline/summaries/generate_bilateral_summaries.py \
    --all --min-docs 1000

# Regenerate existing
sp-pipeline python services/pipeline/summaries/generate_bilateral_summaries.py \
    --init-country China --recipient-country Egypt --regenerate
```

**Incremental:** Yes. Skips existing summaries unless `--regenerate`.

---

## Step 9: Event Summary Embeddings

**Script:** `services/pipeline/embeddings/embed_event_summaries.py`
**Writes:** `langchain_pg_embedding`

```bash
sp-pipeline python services/pipeline/embeddings/embed_event_summaries.py --yes

# Check status
sp-pipeline python services/pipeline/embeddings/embed_event_summaries.py --status
```

---

## Batch API Pipeline

The Batch API provides an alternative to synchronous LLM calls using OpenAI's Batch API at **50% cost reduction**. Every iterative LLM step has a batch equivalent.

### Three-Step Process

```
batch_prepare.py          →  batch_queue_runner.py       →  batch_process_all_results.py
Creates JSONL + queue        Uploads to OpenAI + polls       Parses output + applies to DB
(status: preparing)          (status: submitted→completed)   (sets processed_at)
```

### Supported Job Types

| Job Type | Equivalent Iterative Script | Purpose |
|----------|---------------------------|---------|
| `cluster_deconflict` | `llm_deconflict_clusters.py` | Event Stage 1B |
| `canonical_deconflict` | `llm_deconflict_canonical_events.py` | Event Stage 2B |
| `entity_extract` | — | Extract entities from canonical events |
| `daily_entity_extract` | `extract_daily_entities.py` | Entity Stage 1A |
| `entity_deconflict` | `llm_deconflict_entity_clusters.py` | Entity Stage 1C |
| `canonical_entity_deconflict` | `llm_deconflict_canonical_entities.py` | Entity Stage 2C |
| `score_materiality` | — | Score canonical event materiality |
| `generate_daily_summary` | — | Generate daily event summaries |
| `generate_weekly_summary` | — | Generate weekly event summaries |
| `generate_monthly_summary` | — | Generate monthly event summaries |
| `score_summary_materiality` | — | Score event summary materiality |
| `generate_entity_descriptions` | `generate_entity_descriptions.py` | Entity Stage 3C |
| `generate_bilateral_summaries` | `generate_bilateral_summaries.py` | Bilateral summaries |
| `classify_entity_relationships` | `classify_entity_relationships.py` | Entity Stage 3D |

### Common Batch Flags

**batch_prepare.py:**

| Flag | Purpose |
|------|---------|
| `--job-type` | Required. One of the job types above |
| `--country` | Filter by country |
| `--influencers` | All influencer countries |
| `--start-date` / `--end-date` | Date range filter |
| `--min-articles` | Min articles for canonical_deconflict (default: 3) |
| `--force` | Recreate even if batch job exists |
| `--dry-run` | Preview without creating |

**batch_queue_runner.py:**

| Flag | Purpose |
|------|---------|
| `--job-type` | Filter by job type |
| `--country` | Filter by country |
| `--max-concurrent` | Max simultaneous OpenAI batches (default: 5) |
| `--poll-interval` | Seconds between status checks (default: 300) |
| `--retry-failed` | Reset failed jobs to preparing and resubmit |

**batch_process_all_results.py:**

| Flag | Purpose |
|------|---------|
| `--job-type` | Filter by job type |
| `--country` | Filter by country |
| `--include-processed` | Re-process already-processed batches |
| `--dry-run` | Preview without applying |

### Troubleshooting Batch Jobs

```bash
# Check batch job status in database
docker exec api-service python -c "
from shared.database.database import get_session
from shared.models.models import BatchJob
with get_session() as s:
    for j in s.query(BatchJob).order_by(BatchJob.created_at.desc()).limit(10).all():
        print(f'{j.job_type} | {j.initiating_country} | {j.status} | {j.created_at}')
"

# Retry failed batch jobs
sp-pipeline python services/pipeline/batch/batch_queue_runner.py \
    --job-type cluster_deconflict --retry-failed
```

**Common issues:**
- `0 pending batches` → Run `batch_prepare.py` first, or use `--retry-failed` if jobs exist but failed
- `Connection refused` → FastAPI proxy not running on host. Start with `uvicorn server.main:app --host 0.0.0.0 --port 7001`
- `completed` but results not applied → Run `batch_process_all_results.py`

---

## Incremental vs Full Reprocessing

| Script | Safe for Incremental? | Skips Existing? | Key Flag |
|--------|----------------------|-----------------|----------|
| `dsr.py` | Yes | By doc_id | `--reprocess` to force |
| `embed_missing_documents.py` | Yes | By embedding existence | — |
| `batch_cluster_events.py` | Yes | By (country, date) | `--force` to reprocess |
| `llm_deconflict_clusters.py` | Yes | By `llm_deconflicted=False` | Checkpointed |
| `consolidate_all_events.py` | Use `--force` | Only `master_event_id IS NULL` | `--force` resets all |
| `llm_deconflict_canonical_events.py` | Yes with `--resume` | By `llm_validated` | `--resume` / `--force` |
| `merge_canonical_events.py` | Yes | Validated masters only | — |
| `generate_bilateral_summaries.py` | Yes | By existing summary | `--regenerate` to force |

### When to Use `--force`

- **`consolidate_all_events.py --force`**: After adding new canonical events. Resets `master_event_id` on all events for the country and re-groups. Does NOT delete events.
- **`batch_cluster_events.py --force`**: After reprocessing documents for a date that was already clustered.
- **`consolidate_all_entities.py --force`**: After adding new canonical entities.

---

## Docker Commands

### Using docker-compose.preprocessing.yml

```bash
# Build the image
docker compose -f docker-compose.preprocessing.yml build

# Run any pipeline command
docker compose -f docker-compose.preprocessing.yml run --rm preprocessing python <script> <args>

# Recommended alias
alias sp-pipeline='docker compose -f docker-compose.preprocessing.yml run --rm preprocessing'
```

### Environment

The preprocessing container connects to:
- **Database:** `sp_prod_db` on `softpower_net` (external network)
- **FastAPI proxy:** `host.docker.internal:${API_PORT}` (default 7001)
- **Volumes:** `./data`, `./services/pipeline`, `./shared`, `./alembic`

### Configuration

- **Pipeline config:** `shared/config/config.yaml`
  - `influencers`: [China, Russia, Iran, Turkey, United States]
  - `recipients`: [Bahrain, Cyprus, Egypt, Iran, Iraq, Israel, Jordan, Kuwait, Lebanon, Libya, Oman, Palestine, Qatar, Saudi Arabia, Syria, Turkey, United Arab Emirates, UAE, Yemen]
  - `categories`: [Economic, Social, Military, Diplomacy]
  - `cluster.eps`: 0.55, `cluster.min_samples`: 2
  - `aws.default_model`: gpt-4o-mini
- **Credentials:** `.env` file (POSTGRES_*, CLAUDE_KEY, AWS_*, API_PORT)
