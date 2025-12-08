# Production-Scale Canonical Event Consolidation Pipeline
## For 400K+ Documents

## Scale Considerations

- **Documents**: 400,000+
- **Estimated Raw Events**: 100,000-200,000 unique event names
- **Event-Document Relationships**: Potentially millions
- **Challenge**: Cannot process everything through LLM (cost + time)
- **Solution**: Aggressive automated consolidation with strategic LLM usage

---

## Revised Multi-Pass Strategy

### Phase 0: Statistical Pre-Analysis (Critical at Scale)
**Script**: `event_stats_analysis.py`

**Purpose**: Understand distribution before expensive operations

```python
# Key questions:
# - What % of events appear only once? (can auto-group later)
# - What % of events are  >100 docs? (high-value targets for LLM)
# - Are there obvious naming patterns? ("Visit to X", "X Summit")
```

**Optimization Decision Tree**:
```
Event Frequency:
├─ 1 doc (singletons): ~40-50% → Low priority, batch process
├─ 2-10 docs: ~30-35% → String clustering only
├─ 11-100 docs: ~15-20% → String + semantic clustering
└─ 100+ docs: ~5-10% → Full pipeline with LLM review
```

**Output**: Prioritized batches for processing

---

### Phase 1: Aggressive String-Based Consolidation
**Script**: `consolidate_events_string.py`

**Purpose**: Reduce event count by 60-70% before expensive operations

**Optimizations for Scale**:

1. **Exact Match (Case-Insensitive)**:
   ```python
   # Fast SQL-based grouping
   SELECT LOWER(TRIM(event_name)), array_agg(DISTINCT event_name)
   FROM raw_events
   GROUP BY LOWER(TRIM(event_name))
   HAVING COUNT(DISTINCT event_name) > 1
   ```
   **Expected reduction**: 10-15%

2. **Normalize Punctuation & Spacing**:
   ```python
   # Remove quotes, extra spaces, trailing periods
   "Summit Meeting" = "'Summit Meeting'" = "Summit Meeting."
   ```
   **Expected reduction**: 5-10%

3. **Common Prefix/Suffix Patterns**:
   ```python
   # Pattern detection
   "Visit to Egypt" → base: "Egypt", pattern: "Visit to X"
   "Summit in Cairo" → base: "Cairo", pattern: "Summit in X"
   ```
   **Expected reduction**: 15-20%

4. **Year/Date Normalization**:
   ```python
   "Peace Summit 2024" = "Peace Summit (2024)" = "2024 Peace Summit"
   ```
   **Expected reduction**: 10-15%

**Total Phase 1 Reduction**: 40-60% of event names
**Performance**: Can process 200K events in ~30 minutes using batch SQL

**Output**:
- Reduced event set (80K-120K unique events)
- Consolidation mappings table
- High-confidence merges

---

### Phase 2: Embedding-Based Clustering (Reduced Set)
**Script**: `cluster_events_embeddings.py`

**Purpose**: Group semantically similar events from Phase 1 output

**Scale Optimizations**:

1. **Stratified Sampling for Embedding**:
   ```python
   # Don't embed everything - stratify by:
   # - High frequency events (100+ docs): MUST embed (5-10K events)
   # - Medium frequency (11-100 docs): Sample 50% (15-20K events)
   # - Low frequency (2-10 docs): Sample 10% (10K events)
   # - Singletons: Sample 1% (1K events)
   ```

2. **Batch Embedding Generation**:
   ```python
   # Use sentence-transformers with GPU
   # Batch size: 1000 events
   # Expected time: ~2-3 hours for 50K events
   ```

3. **Hierarchical Clustering**:
   ```python
   # Instead of flat DBSCAN:
   # 1. Cluster at high level (threshold=0.7)
   # 2. Sub-cluster within each group (threshold=0.85)
   # 3. Only send borderline cases to LLM
   ```

**Output**:
- ~10-20K clusters from 80-120K events
- Confidence scores for each cluster
- Borderline cases flagged for LLM

---

### Phase 3: LLM Strategic Review (High-Value Only)
**Script**: `llm_consolidate_priority.py`

**Purpose**: Focus LLM budget on highest-impact events

**Priority Tiers**:

**Tier 1 - Must Review** (~1,000 clusters):
- Events with 100+ documents each
- Ambiguous clusters (similarity 0.75-0.85)
- Multi-country events
- **LLM Cost**: $50-100

**Tier 2 - Should Review** (~5,000 clusters):
- Events with 25-100 documents
- Medium confidence clusters (similarity 0.85-0.90)
- **LLM Cost**: $200-300

**Tier 3 - Optional Review** (~10,000 clusters):
- Events with 10-25 documents
- **LLM Cost**: $500-800 (if budget allows)

**Tier 4 - Auto-Accept** (remaining):
- High confidence clusters (similarity >0.90)
- Low document count events
- **No LLM cost**

**Batch Processing Strategy**:
```python
# Send 50 clusters per LLM call
# Parallel processing: 10 concurrent API calls
# With rate limiting: ~1000 clusters/hour
# Tier 1: ~1 hour, Tier 2: ~5 hours
```

**LLM Prompt (Optimized for Batch)**:
```
Consolidate these 50 event clusters. For each cluster, decide:

CLUSTER #1:
Events: ["Ceasefire Agreement", "Ceasefire Agreement in Gaza"]
Docs: [414, 291]
Countries: [USA, Egypt, Qatar]
Period: 2024-01-15 to 2024-08-04

Decision: MERGE | SEPARATE | SPLIT
If MERGE: canonical_name = "Gaza Ceasefire Negotiations (2024)"
If SPLIT: sub_events = ["Early Ceasefire Talks (Jan-Mar)", "Resumed Negotiations (Jun-Aug)"]

[... repeat for clusters 2-50 ...]

Output JSON format for programmatic processing.
```

**Output**:
- LLM decisions for high-value events
- Canonical names
- Split/merge instructions

---

### Phase 4: Canonical Event Creation (Hierarchical)
**Script**: `create_canonical_events_v2.py`

**Purpose**: Build canonical events with confidence tiers

**Schema Enhancement**:
```sql
CREATE TABLE canonical_events (
    canonical_event_id UUID PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    confidence_tier INT NOT NULL,  -- 1=LLM verified, 2=High confidence cluster, 3=Auto-merged

    -- Add consolidation metadata
    consolidation_stats JSONB,  -- {string_merges: 5, semantic_merges: 2, llm_verified: true}

    ...
);

-- Add confidence-based index
CREATE INDEX idx_canon_confidence ON canonical_events(confidence_tier, total_documents DESC);
```

**Tiered Creation**:
1. **Tier 1 (LLM-verified)**: Create canonical events from LLM review results
2. **Tier 2 (High-confidence)**: Create from clusters with similarity >0.90
3. **Tier 3 (Auto-merged)**: Create from string consolidation

**Output**: ~20-40K canonical events from 100-200K raw events

---

### Phase 5: Incremental Pipeline (Optimized)
**Script**: `match_events_incremental.py`

**Purpose**: Efficiently match new events daily

**Fast Path Optimization**:
```python
def assign_new_event(event_name, doc_date, countries):
    # 1. Check exact match cache (Redis) - 1ms
    if event_name in cache:
        return cache[event_name]

    # 2. Check string similarity to Tier 1 events only - 10ms
    match = fuzzy_match(event_name, tier1_events)
    if match.score > 0.95:
        return match.canonical_id

    # 3. Generate embedding, check vector similarity - 100ms
    embedding = embed(event_name)
    nearest = vector_search(embedding, top_k=10)
    if nearest[0].score > 0.92:
        return nearest[0].canonical_id

    # 4. Add to review queue for weekly batch LLM review
    if nearest[0].score > 0.80:
        add_to_review_queue(event_name, nearest)

    # 5. Create new canonical event candidate
    return create_candidate(event_name)
```

**Performance Target**: <200ms per new event

---

## Implementation Timeline (Production Scale)

### Week 1-2: Infrastructure & Phase 0-1
- Set up embedding infrastructure (GPU instance)
- Implement statistical analysis
- Build string consolidation pipeline
- **Deliverable**: 40-60% reduction in event count

### Week 3: Phase 2 (Embedding Clustering)
- Generate embeddings for stratified sample
- Run hierarchical clustering
- Validate cluster quality on samples
- **Deliverable**: ~20K clusters from 80-120K events

### Week 4-5: Phase 3 (LLM Processing)
- Process Tier 1 events (high priority)
- Process Tier 2 events (medium priority)
- Budget review for Tier 3
- **Deliverable**: Consolidation decisions for 5-10K clusters

### Week 6: Phase 4 (Canonical Creation)
- Create canonical events table
- Populate with tiered confidence
- Build analytics views
- **Deliverable**: Production canonical events database

### Week 7: Phase 5 (Incremental Pipeline)
- Implement fast matching
- Set up Redis cache
- Integrate with dsr.py
- **Deliverable**: <200ms incremental matching

### Week 8: Validation & Iteration
- Manual quality review (1000 random samples)
- Measure precision/recall
- Re-run low-confidence clusters
- **Deliverable**: Production-ready system

---

## Cost Estimates (400K Documents)

### Compute Costs
- **Embedding generation**: $20-50 (GPU hours)
- **Clustering**: $10-20 (CPU hours)
- **Storage**: $5/month (embeddings in pgvector)

### LLM Costs (GPT-4o-mini)
- **Tier 1**: $50-100 (1K clusters × $0.05)
- **Tier 2**: $200-300 (5K clusters × $0.05)
- **Tier 3**: $500-800 (10K clusters × $0.05)
- **Total**: $750-1,200 for complete consolidation
- **Incremental**: $10-20/month (new events)

### Time Estimates
- **Phase 0-1**: 2-4 hours (string operations)
- **Phase 2**: 3-5 hours (embedding + clustering)
- **Phase 3**: 6-10 hours (LLM processing with parallel calls)
- **Total**: ~12-20 hours for complete pipeline

---

## Performance Optimizations

### Database Indexes
```sql
-- Speed up event lookups
CREATE INDEX idx_raw_event_name ON raw_events(event_name);
CREATE INDEX idx_raw_event_name_lower ON raw_events(LOWER(event_name));

-- Speed up document joins
CREATE INDEX idx_raw_event_doc ON raw_events(doc_id);

-- Speed up date range queries
CREATE INDEX idx_doc_date ON documents(date);

-- Vector similarity search
CREATE INDEX idx_event_embedding ON event_embeddings USING ivfflat (embedding vector_cosine_ops);
```

### Caching Strategy
```python
# Redis cache for incremental matching
{
    "event_name": {
        "canonical_id": "uuid",
        "confidence": 0.95,
        "cached_at": "timestamp"
    }
}

# TTL: 7 days, auto-refresh on access
# Hit rate target: >90% for incremental processing
```

### Parallel Processing
```python
# Phase 2: Parallel embedding generation
# - Split events into 10 batches
# - Process on separate GPU workers
# - Aggregate results

# Phase 3: Parallel LLM calls
# - 10 concurrent API calls
# - Rate limiting: 500 RPM per API key
# - Use multiple API keys if needed
```

---

## Quality Metrics & Monitoring

### Dashboard Metrics
1. **Processing Progress**: Events processed / Total events
2. **Reduction Rate**: Canonical events / Raw events (target: 20-40%)
3. **Confidence Distribution**: % in each tier
4. **LLM Agreement Rate**: Manual validation vs LLM decisions
5. **Incremental Match Rate**: Cache hits vs new assignments

### Alerts
- Cluster quality drops below 85%
- LLM error rate >5%
- Incremental matching latency >500ms
- Review queue size >1000 events

---

## Rollback & Iteration Strategy

### Versioning
```sql
CREATE TABLE consolidation_runs (
    run_id UUID PRIMARY KEY,
    run_date TIMESTAMP,
    config JSONB,  -- Thresholds, model versions
    stats JSONB,   -- Reduction rate, confidence distribution
    active BOOLEAN
);

-- Enable A/B testing of consolidation strategies
```

### Safe Deployment
1. Run Phase 0-2 on copy of production data
2. Validate quality on sample (1000 events)
3. If quality >90%, proceed to Phase 3
4. Keep old mappings table until validation complete
5. Gradual rollout: Use new canonical events for 10% of queries, compare results

---

## Next Steps

1. **Run analysis script** on full 400K dataset to validate assumptions
2. **Choose Phase 1 strategy** based on actual event distribution
3. **Set up embedding infrastructure** (GPU instance for Phase 2)
4. **Define budget** for LLM processing (which tiers to process)
5. **Build monitoring dashboard** before starting consolidation

Would you like me to implement Phase 0 (statistical analysis) first to see the actual distribution of your 400K documents?
