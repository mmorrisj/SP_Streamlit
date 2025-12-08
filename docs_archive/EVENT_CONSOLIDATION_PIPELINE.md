# Canonical Event Consolidation Pipeline

## Overview

Pipeline for consolidating thousands of raw events into canonical events that provide a comprehensive picture of event coverage over time.

## Challenge

- **Input**: ~24,500 raw event-document relationships, ~thousands of unique event names
- **Variations**: Same events with different names ("Ceasefire Agreement" vs "Ceasefire Agreement in Gaza")
- **Goal**: Create canonical events that track coverage over time, by country, category, etc.
- **Constraint**: High accuracy required - diplomatic events are nuanced

## Multi-Pass Pipeline Architecture

### Phase 1: Data Extraction & Preparation
**Script**: `extract_event_features.py`

**Purpose**: Gather all raw events with rich context for clustering

**Process**:
1. Extract all unique event names from `raw_events`
2. For each event, gather:
   - All document dates (to establish time span)
   - All initiating countries
   - All recipient countries
   - All categories/subcategories
   - Document count
   - Sample document titles
3. Create embeddings for event names + context
4. Store in staging table: `event_consolidation_candidates`

**Output**:
- PostgreSQL table with event features
- Embeddings stored in pgvector
- CSV export for manual review

---

### Phase 2: Initial Clustering (String Similarity)
**Script**: `cluster_events_initial.py`

**Purpose**: Group obviously similar events using fast string methods

**Techniques**:
1. **Exact matching** (case-insensitive): "Summit Meeting" = "summit meeting"
2. **Levenshtein distance**: "Ceasefire Agreement" ≈ "Ceasefire Aggreement" (typo)
3. **Token overlap**: "Gaza Ceasefire Agreement" ≈ "Ceasefire Agreement in Gaza"
4. **Substring matching**: "Peace Summit" in "Sharm El-Sheikh Peace Summit"

**Clustering Strategy**:
- Use DBSCAN with edit distance
- eps = 0.3 (30% dissimilarity threshold)
- min_samples = 1 (keep singletons for next phase)

**Output**:
- Cluster assignments for ~60-70% of events
- Remaining events marked for semantic clustering

---

### Phase 3: Semantic Clustering (Embeddings)
**Script**: `cluster_events_semantic.py`

**Purpose**: Group semantically similar events that string methods miss

**Examples of what this catches**:
- "Diplomatic Visit" vs "Official State Visit"
- "Aid Package" vs "Humanitarian Assistance"
- "Military Exercise" vs "Joint Training Operation"

**Process**:
1. Take unclustered events from Phase 2
2. Generate embeddings using sentence-transformers
3. Apply HDBSCAN clustering on embedding space
4. Use cosine similarity threshold = 0.85

**Output**:
- Additional cluster assignments
- High-confidence clusters (>0.9 similarity)
- Low-confidence clusters (0.85-0.9) marked for LLM review

---

### Phase 4: LLM-Based Refinement (Batch Processing)
**Script**: `consolidate_events_llm.py`

**Purpose**: Human-level judgment on ambiguous clusters

**Process**:
1. Take clusters from Phase 2 & 3 (batches of 50 clusters)
2. For each batch, send to LLM with:
   - Event names in cluster
   - Document counts
   - Date ranges
   - Countries involved
   - Sample document titles
3. LLM decides:
   - Should these be merged? (YES/NO)
   - What is the canonical event name?
   - Are there sub-events that should be separate?
4. Human review interface for LLM decisions

**LLM Prompt Structure**:
```
You are consolidating diplomatic soft power events. Review this cluster:

CLUSTER #1:
Events:
1. "Ceasefire Agreement" (414 docs, 2024-01-15 to 2024-08-04, Iran→Palestine)
2. "Ceasefire Agreement in Gaza" (291 docs, 2024-01-20 to 2024-08-01, USA→Palestine)
3. "Gaza Ceasefire Talks" (89 docs, 2024-02-01 to 2024-07-30, Egypt→Palestine)

Sample Titles:
- "Egypt mediates ceasefire talks between..."
- "US pushes for Gaza ceasefire agreement..."
- "Iran calls for immediate ceasefire..."

DECISION:
Should these be consolidated? (YES/NO)
If YES, provide:
- Canonical name: <name>
- Rationale: <explanation>
- Temporal scope: <is this one event or multiple events over time?>

If NO, explain why they should remain separate.
```

**Output**:
- LLM consolidation decisions
- Canonical event names
- Merge mappings

---

### Phase 5: Canonical Event Creation
**Script**: `create_canonical_events.py`

**Purpose**: Populate the final canonical events table

**Schema** (new table: `canonical_events`):
```sql
CREATE TABLE canonical_events (
    canonical_event_id UUID PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    description TEXT,
    event_type TEXT,  -- e.g., "diplomatic_visit", "aid_package", "ceasefire"

    -- Temporal coverage
    first_observed DATE,
    last_observed DATE,
    is_ongoing BOOLEAN,

    -- Geographic coverage
    primary_initiating_countries TEXT[],
    primary_recipient_countries TEXT[],

    -- Categorization
    primary_categories TEXT[],
    primary_subcategories TEXT[],

    -- Metrics
    total_documents INT,
    total_raw_events INT,  -- How many raw event names map to this
    coverage_intensity FLOAT,  -- Documents per day

    -- Context
    sample_titles TEXT[],
    related_entities TEXT[],

    -- Metadata
    consolidation_method TEXT,  -- 'string_cluster', 'semantic_cluster', 'llm_merge', 'manual'
    consolidation_confidence FLOAT,
    created_at TIMESTAMP,
    reviewed_by TEXT
);

CREATE TABLE canonical_event_mappings (
    raw_event_name TEXT PRIMARY KEY,
    canonical_event_id UUID REFERENCES canonical_events(canonical_event_id),
    confidence FLOAT,
    method TEXT
);
```

**Process**:
1. Create canonical event records from consolidation results
2. Map all raw event names to canonical events
3. Aggregate statistics from all mapped documents
4. Generate comprehensive descriptions

**Output**:
- Populated `canonical_events` table
- Mapping table for lookups
- Analytics-ready view

---

### Phase 6: Incremental Pipeline (New Events)
**Script**: `match_new_events.py`

**Purpose**: Assign new incoming events to canonical events

**Process** (runs after `dsr.py`):
1. Detect new raw event names
2. Fast matching:
   - Check exact match in mappings table
   - Check string similarity to existing events
3. If no match, semantic matching:
   - Generate embedding
   - Find nearest canonical event (cosine similarity)
   - If similarity > 0.9, assign
   - If 0.8-0.9, flag for review
   - If < 0.8, create new canonical event candidate
4. Weekly LLM batch review of flagged events

**Output**:
- Auto-assigned events
- Review queue for ambiguous cases
- New canonical events as needed

---

## Implementation Priority

### Week 1: Analysis & Phase 1
- Run `analyze_raw_events.py` to understand data
- Implement `extract_event_features.py`
- Create staging table with embeddings

### Week 2: Phases 2-3 (Automated Clustering)
- Implement string-based clustering
- Implement semantic clustering
- Validate cluster quality (sample reviews)

### Week 3: Phase 4 (LLM Refinement)
- Implement LLM batch processing
- Build review interface
- Process all ambiguous clusters

### Week 4: Phase 5 (Canonical Creation)
- Create final schema
- Populate canonical events table
- Build analytics views

### Week 5: Phase 6 (Incremental Pipeline)
- Implement new event matching
- Integrate with dsr.py
- Set up automated review queue

---

## Quality Assurance

### Validation Metrics

1. **Cluster Purity**: What % of clusters contain truly similar events?
2. **Coverage**: What % of raw events are mapped to canonical events?
3. **Precision**: What % of consolidated events are actually the same event?
4. **Recall**: What % of same-event instances are consolidated together?

### Manual Review Checkpoints

- After Phase 2: Sample 50 clusters for quality
- After Phase 3: Review all low-confidence clusters
- After Phase 4: Human validation of 10% of LLM decisions
- After Phase 5: Spot-check 100 random canonical events

---

## Example Consolidation

**Raw Events**:
- "Ceasefire Agreement" (414 docs)
- "Ceasefire Agreement in Gaza" (291 docs)
- "Gaza Ceasefire" (127 docs)
- "Ceasefire Talks" (89 docs)
- "Humanitarian Pause Agreement" (45 docs)

**Phase 2 Output**: Cluster A (first 3 events), Cluster B (last 2 events)

**Phase 3 Output**: Cluster A unchanged, Cluster B unchanged (different semantic meaning)

**Phase 4 LLM Decision**:
- Cluster A → Canonical: "Gaza Ceasefire Negotiations (2024)"
  - Rationale: All refer to same ongoing ceasefire negotiation process
  - Type: diplomatic_negotiation
- Cluster B → Canonical: "Gaza Humanitarian Pause Agreements (2024)"
  - Rationale: Separate from broader ceasefire, focused on humanitarian access
  - Type: humanitarian_agreement

**Phase 5 Output**:
```
canonical_event_id: 123e4567-e89b-12d3-a456-426614174000
canonical_name: "Gaza Ceasefire Negotiations (2024)"
description: "Ongoing multilateral efforts to negotiate a ceasefire..."
first_observed: 2024-01-15
last_observed: 2024-08-04
is_ongoing: true
total_documents: 832
total_raw_events: 3
coverage_intensity: 4.2 docs/day
```

---

## Configuration

All parameters configurable in `backend/config.yaml`:

```yaml
event_consolidation:
  # Phase 2: String clustering
  string_similarity_threshold: 0.7
  levenshtein_max_distance: 3

  # Phase 3: Semantic clustering
  embedding_model: "all-MiniLM-L6-v2"
  semantic_threshold: 0.85
  high_confidence_threshold: 0.9

  # Phase 4: LLM processing
  llm_model: "gpt-4o-mini"
  batch_size: 50
  max_retries: 3

  # Phase 6: Incremental matching
  auto_assign_threshold: 0.9
  review_queue_threshold: 0.8
```

---

## Monitoring & Iteration

### Dashboards
- Consolidation progress (events processed, clusters created)
- Quality metrics (precision, recall, manual overrides)
- Coverage by country/category
- Review queue size

### Iteration Strategy
- Run Phase 2-3 multiple times with different parameters
- Compare results, optimize thresholds
- Use LLM feedback to improve clustering
- Maintain audit log of all consolidation decisions

---

## Benefits

1. **Comprehensive Event Tracking**: See how "Gaza Ceasefire" was covered over 12 months
2. **Cross-Country Analysis**: Compare how different countries engage with same events
3. **Temporal Patterns**: Identify when events gain/lose coverage
4. **Reduced Noise**: Eliminate duplicate events from analysis
5. **Scalable**: Incremental pipeline handles new events efficiently
6. **Auditable**: Full traceability of consolidation decisions
