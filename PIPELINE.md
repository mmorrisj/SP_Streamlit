# Event Processing and Summary Generation Pipeline

This document describes the **current** pipeline for processing soft power events and generating daily summaries.

## Pipeline Overview

```
Documents (database)
    ↓
Step 1: Daily Clustering → event_clusters (RawEvent → daily clusters)
    ↓
Step 2: LLM Deconfliction → refined event_clusters
    ↓
Step 3: Temporal Consolidation → canonical_events + master_events
    ↓
Step 4: Summary Generation → AP-style narratives with source links
```

## Two-Stage Event Processing Architecture

The pipeline uses a **two-stage clustering approach** optimized for news article feeds:

### Stage 1: Daily Consolidation
**Goal:** Group same-day mentions of the same event across different news sources

**Process:**
1. Get all articles published on a specific date
2. Cluster similar event mentions using DBSCAN (eps=0.15 for strict clustering)
3. LLM deduplication within clusters to handle edge cases
4. Create daily event clusters

### Stage 2: Temporal Linking
**Goal:** Link daily clusters across time to track evolving stories

**Process:**
1. For each daily cluster, search for matching canonical events in temporal window
2. Use context-aware similarity scoring (semantic + temporal + source overlap + entity consistency)
3. Decide: link to existing canonical event OR create new canonical event
4. Track story phases (emerging → developing → peak → fading → dormant)

## Step 1: Daily Clustering

**Script:** `services/pipeline/events/batch_cluster_events.py`

**Purpose:** Clusters event names by country and date using DBSCAN + embeddings

**Input:**
- `raw_events` table (extracted from documents)
- `documents` table (metadata)

**Output:**
- `event_clusters` table entries (organized in batches for LLM processing)

**Usage:**
```bash
# Cluster events for all influencer countries
docker exec api-service python services/pipeline/events/batch_cluster_events.py \
  --influencers \
  --start-date 2024-09-01 \
  --end-date 2024-09-30

# Cluster for single country
docker exec api-service python services/pipeline/events/batch_cluster_events.py \
  --country China \
  --start-date 2024-09-01 \
  --end-date 2024-09-30

# Adjust clustering sensitivity
docker exec api-service python services/pipeline/events/batch_cluster_events.py \
  --country China \
  --date 2024-09-15 \
  --eps 0.20 \
  --batch-size 30
```

**What it does:**
1. Queries raw_events for a specific country and date
2. Filters out self-directed events (initiator = recipient)
3. Normalizes event names (lowercasing, removing punctuation, generic terms)
4. Generates embeddings using sentence-transformers
5. Clusters ALL events for the day using DBSCAN (cosine distance)
6. Organizes clusters into batches of ~50 events for later LLM processing
7. Saves to `event_clusters` table with representative names and centroids

**Key Parameters:**
- `--eps`: DBSCAN epsilon (default 0.15, range 0.10-0.30)
  - Lower = stricter clustering (fewer events per cluster)
  - Higher = looser clustering (more events grouped together)
- `--batch-size`: Events per batch for LLM processing (default 50, does NOT affect clustering)

## Step 2: LLM Deconfliction

**Script:** `services/pipeline/events/llm_deconflict_clusters.py`

**Purpose:** Uses AI to validate and refine event clusters from Step 1

**Input:** `event_clusters` table from Step 1

**Output:**
- Refined event clusters (split incorrectly merged clusters)
- Improved representative names
- `canonical_events` table entries (deduplicated events)
- `daily_event_mentions` table entries (doc_ids by date)

**Usage:**
```bash
# Process all influencer countries
docker exec api-service python services/pipeline/events/llm_deconflict_clusters.py \
  --influencers \
  --start-date 2024-09-01 \
  --end-date 2024-09-30

# Process single country
docker exec api-service python services/pipeline/events/llm_deconflict_clusters.py \
  --country China \
  --start-date 2024-09-01 \
  --end-date 2024-09-30
```

**What it does:**
1. Loads event_clusters created in Step 1
2. For each cluster, samples representative events
3. Asks LLM: "Are these events truly the same or different?"
4. Splits clusters if LLM determines they contain multiple distinct events
5. Improves event naming using LLM
6. Creates `canonical_events` records (one per unique event)
7. Creates `daily_event_mentions` records (links events to doc_ids by date)

## Step 3: Temporal Consolidation (Master Events)

**NOTE:** This step creates master events from canonical events by clustering across time.

**Implementation:** Three-script batch consolidation process

**Scripts:**
1. **consolidate_all_events.py** - Groups canonical events using embedding similarity
   - Loads all canonical_events for each country (no date filtering)
   - Clusters using cosine similarity on embeddings (threshold ≥0.85)
   - Sets `master_event_id` to link related events
   - Master events: `master_event_id IS NULL`
   - Child events: `master_event_id = master.id`

2. **llm_deconflict_canonical_events.py** - Validates groupings with LLM
   - Reviews each event group to confirm they represent same real-world event
   - Picks best canonical name from the group
   - Splits incorrectly merged groups if needed
   - Assigns new canonical names for split groups

3. **merge_canonical_events.py** - Consolidates daily mentions into multi-day events
   - Reassigns `daily_event_mentions` from child events to master events
   - Handles date conflicts by merging article counts
   - Deletes empty child canonical events
   - Creates true multi-day event tracking

**Process:**
1. Load all canonical_events for a country (no time filtering)
2. Cluster similar events using embedding cosine similarity
3. Validate clusters with LLM (confirms same event, picks best name)
4. Consolidate daily_event_mentions to create multi-day master events
5. Track story evolution across days/weeks/months

**Usage:**
```bash
python services/pipeline/events/consolidate_all_events.py --influencers
python services/pipeline/events/llm_deconflict_canonical_events.py --influencers
python services/pipeline/events/merge_canonical_events.py --influencers
```

**Output:**
- Master events (canonical_events with `master_event_id IS NULL`)
- Updated canonical_events with `master_event_id` linking to parent
- Temporal event tracking across the full date range

## Step 4: Daily Summary Generation

**Script:** `services/pipeline/summaries/generate_daily_summaries.py`

**Purpose:** Creates AP-style narrative summaries for each master event on each day

**Input:** Master events from Step 3

**Output:**
- `event_summaries` table entries (with narrative_summary JSONB)
- `event_source_links` table entries (complete source traceability)

**Usage:**
```bash
# Generate for all influencer countries
docker exec api-service python services/pipeline/summaries/generate_daily_summaries.py \
  --influencers \
  --start-date 2024-09-01 \
  --end-date 2024-09-30 \
  --limit 10

# Generate for single country
docker exec api-service python services/pipeline/summaries/generate_daily_summaries.py \
  --country China \
  --start-date 2024-09-01 \
  --end-date 2024-09-30 \
  --limit 10

# Dry run (test without DB writes)
docker exec api-service python services/pipeline/summaries/generate_daily_summaries.py \
  --dry-run \
  --country China \
  --date 2024-09-15 \
  --limit 5
```

**What it does:**
1. Queries master events active on each day
2. Selects top N events by article count
3. Samples 5 representative documents per event
4. Calls LLM to generate AP-style summary (Overview + Outcomes)
5. Creates ATOM hyperlinks to all source documents
6. Generates formatted citations (first 10 documents)
7. Stores in EventSummary with complete source tracking

**Summary Format:**
- **Overview:** 2-3 sentences (what, when, where, who, sources)
- **Outcomes:** 2-3 sentences (results, statements, actions)
- **Sources:** ATOM hyperlink + citations
- **Style:** Associated Press (factual, attributed, no analysis)

## Complete September 2024 Example

Run all steps for September 2024 (influencer countries):

```bash
# Step 1: Daily Clustering
docker exec api-service python services/pipeline/events/batch_cluster_events.py \
  --influencers --start-date 2024-09-01 --end-date 2024-09-30

# Step 2: LLM Deconfliction + Create Canonical Events
docker exec api-service python services/pipeline/events/llm_deconflict_clusters.py \
  --influencers --start-date 2024-09-01 --end-date 2024-09-30

# Step 3: Temporal Consolidation (Master Events)
# NOTE: This step may be integrated into Step 2 or requires a separate script
# Verify master_event_id field is populated in canonical_events table

# Step 4: Summary Generation
docker exec api-service python services/pipeline/summaries/generate_daily_summaries.py \
  --influencers --start-date 2024-09-01 --end-date 2024-09-30 --limit 10
```

## Single Country Example (China, September 2024)

```bash
# Step 1: Daily Clustering
docker exec api-service python services/pipeline/events/batch_cluster_events.py \
  --country China --start-date 2024-09-01 --end-date 2024-09-30

# Step 2: LLM Deconfliction
docker exec api-service python services/pipeline/events/llm_deconflict_clusters.py \
  --country China --start-date 2024-09-01 --end-date 2024-09-30

# Step 3: Verify master events exist
docker exec softpower_db psql -U matthew50 -d softpower-db -c \
  "SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NULL AND initiating_country = 'China' AND first_mention_date >= '2024-09-01';"

# Step 4: Generate summaries
docker exec api-service python services/pipeline/summaries/generate_daily_summaries.py \
  --country China --start-date 2024-09-01 --end-date 2024-09-30 --limit 10
```

## Database Schema

### event_clusters (Step 1 output)
```sql
id                      UUID PRIMARY KEY
initiating_country      TEXT
cluster_date            DATE
batch_number            INTEGER (for organizing LLM processing)
cluster_id              INTEGER (DBSCAN cluster label)
event_names             TEXT[] (all event names in cluster)
doc_ids                 TEXT[] (all document IDs)
cluster_size            INTEGER
is_noise                BOOLEAN (DBSCAN noise label = -1)
centroid_embedding      FLOAT[] (cluster centroid)
representative_name     TEXT (most representative event name)
processed               BOOLEAN (false initially)
llm_deconflicted        BOOLEAN (false initially)
created_at              TIMESTAMP
```

### canonical_events (Step 2 output)
```sql
id                      UUID PRIMARY KEY
canonical_name          TEXT (event name)
initiating_country      TEXT
master_event_id         UUID (NULL for master events, links to master for children)
first_mention_date      DATE
last_mention_date       DATE
total_mention_days      INTEGER
total_articles          INTEGER
story_phase             TEXT (emerging|developing|peak|active|fading|dormant)
days_since_last_mention INTEGER
unique_sources          TEXT[] (news sources)
source_count            INTEGER
peak_mention_date       DATE
peak_daily_article_count INTEGER
alternative_names       TEXT[]
primary_categories      JSONB
primary_recipients      JSONB
```

### daily_event_mentions (Step 2 output)
```sql
id                      UUID PRIMARY KEY
canonical_event_id      UUID (links to canonical_events)
mention_date            DATE
doc_ids                 TEXT[] (array of document IDs)
article_count           INTEGER
consolidated_headline   TEXT
source_names            TEXT[]
source_diversity_score  FLOAT (sources / articles)
news_intensity          TEXT (breaking|developing|follow-up|recap)
mention_context         TEXT (announcement|preparation|execution|continuation|aftermath|general)
```

### event_summaries (Step 4 output)
```sql
id                      UUID PRIMARY KEY
period_type             PeriodType (DAILY, WEEKLY, MONTHLY, YEARLY)
period_start            DATE
period_end              DATE
event_name              TEXT
initiating_country      TEXT
narrative_summary       JSONB (overview, outcomes, source_link, citations)
count_by_category       JSONB
count_by_recipient      JSONB
total_documents_across_sources INTEGER
first_observed_date     DATE
last_observed_date      DATE
created_at              TIMESTAMP
is_deleted              BOOLEAN
```

### event_source_links (Step 4 output)
```sql
id                      UUID PRIMARY KEY
event_summary_id        UUID (links to event_summaries)
doc_id                  TEXT (links to documents)
contribution_weight     FLOAT (1.0 for featured, 0.5 for supporting)
```

## Deprecated Scripts

The following scripts have been moved to `services/pipeline/events/_deprecated/` and should **NOT** be used:

- ❌ `process_daily_news.py` - Old single-day processing
- ❌ `process_date_range.py` - Old date range processing
- ❌ `temporal_event_consolidation.py` - Replaced by batch_cluster + llm_deconflict
- ❌ `create_master_events.py` - Replaced by batch_cluster_events.py

## Troubleshooting

**No events created in Step 1:**
- Check if documents exist for the date range
- Verify documents have `event_name` extracted
- Check initiating_country values match config.yaml

**No master events created in Step 2:**
- Verify Step 1 completed successfully
- Check that canonical_events exist for the date range
- Review clustering parameters in config.yaml

**LLM deconfliction errors in Step 3:**
- Ensure OPENAI_PROJ_API environment variable is set
- Check OpenAI API rate limits
- Review LLM response format

**No summaries generated in Step 4:**
- Verify Steps 1-3 completed
- Check that master events exist (master_event_id IS NULL)
- Ensure daily_event_mentions exist for the date range

## Performance

**Expected Processing Times (for 1 month, 5 countries):**

| Step | Time | Cost (GPT-4o-mini) |
|------|------|-------------------|
| 1. Event Tracking | 30-60 min | $0 (no LLM) |
| 2. Clustering | 10-20 min | $0 (no LLM) |
| 3. LLM Deconfliction | 60-90 min | ~$5-10 |
| 4. Summary Generation | 30-60 min | ~$5-7 |
| **Total** | **2.5-4 hours** | **~$10-17** |

**Optimization:**
- Steps can run in parallel for different countries
- Summaries (Step 4) can run in parallel for all countries
- Use `--limit` parameter to reduce number of summaries per day

## Monitoring

Check pipeline progress:

```bash
# Count canonical events
docker exec softpower_db psql -U matthew50 -d softpower-db -c \
  "SELECT COUNT(*) FROM canonical_events WHERE first_mention_date >= '2024-09-01';"

# Count master events
docker exec softpower_db psql -U matthew50 -d softpower-db -c \
  "SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NULL AND first_mention_date >= '2024-09-01';"

# Count daily summaries
docker exec softpower_db psql -U matthew50 -d softpower-db -c \
  "SELECT initiating_country, COUNT(*) FROM event_summaries WHERE period_start >= '2024-09-01' GROUP BY initiating_country;"
```
