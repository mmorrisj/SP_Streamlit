# Event Consolidation: Existing Pipeline vs. Layered Approach

## Executive Summary

**Question**: Should we use the existing `consolidate_all_events.py` or the new `layered_consolidate_events.py`?

**Answer**: **Try existing pipeline first with tuned threshold, use layered approach only if it fails.**

The existing pipeline already handles computational feasibility through chunked computation. The new layered approach adds **time-windowing** which may help with false positives but isn't strictly necessary.

---

## Existing Pipeline Architecture

### Overview

The event processing pipeline uses a **two-stage batch consolidation approach**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Daily Event Detection                                      │
│ (Per-day processing)                                                 │
├─────────────────────────────────────────────────────────────────────┤
│ 1. batch_cluster_events.py                                          │
│    - Clusters raw_events for each (country, date) using DBSCAN      │
│    - Creates event_clusters table with batch numbers                │
│    - Does NOT link events across days (by design)                   │
│                                                                       │
│ 2. llm_deconflict_clusters.py                                       │
│    - LLM validates daily clusters                                    │
│    - Creates canonical_events (one per unique event per day)        │
│    - Creates daily_event_mentions (links events to docs)            │
│    - Generates embedding_vector for each canonical_event            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Batch Consolidation                                        │
│ (Across entire dataset)                                              │
├─────────────────────────────────────────────────────────────────────┤
│ 2A. consolidate_all_events.py (EXISTING)                            │
│     - Loads ALL canonical_events for country                        │
│     - Computes cosine similarity between all event pairs            │
│     - Uses chunked computation (1000 rows at a time) for memory     │
│     - Groups similar events using DFS (connected components)        │
│     - Sets master_event_id to create event hierarchy                │
│                                                                       │
│ 2B. llm_deconflict_canonical_events.py                              │
│     - LLM validates consolidation                                    │
│     - Picks best canonical_name                                      │
│     - Splits incorrectly merged groups                               │
│     - EXPENSIVE - User has already run this!                        │
│                                                                       │
│ 2C. merge_canonical_events.py                                       │
│     - Consolidates daily_event_mentions from child to master        │
│     - Deletes empty child canonical_events                           │
│     - Result: Master events span multiple days                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Algorithm: consolidate_all_events.py

```python
# Existing approach (Stage 2A)
1. Load ALL canonical_events for country (WHERE master_event_id IS NULL)
   - 12,329 events for China June-Dec 2025

2. Build embedding matrix (12,329 × embedding_dim)

3. Compute similarity matrix in chunks to avoid memory issues:
   - Process 1000 rows at a time
   - Results in 12,329 × 12,329 similarity matrix
   - Total comparisons: ~152 million (12,329² ÷ 2)

4. Find connected components using DFS:
   - If event A ~ B (similarity ≥ threshold)
   - And event B ~ C (similarity ≥ threshold)
   - Then all three merge into one group {A, B, C}

5. For each group:
   - Pick master: highest article_count + days_mentioned
   - Set master_event_id for all children → master
```

**Memory Management**: Uses chunked computation (1000-row chunks) to avoid memory corruption on large datasets.

**Threshold**: Default 0.85 (strict), user tried 0.75 (too loose → over-consolidation)

---

## Proposed Layered Approach

### Overview: layered_consolidate_events.py

```
┌─────────────────────────────────────────────────────────────────────┐
│ TIME-WINDOWED CONSOLIDATION                                          │
├─────────────────────────────────────────────────────────────────────┤
│ Level 1: Within-Month Consolidation                                 │
│   - Split date range into monthly windows (June, July, Aug, ...)   │
│   - Cluster events within each month separately                      │
│   - Reduces problem size: ~500-2000 events/month vs 12,329 total   │
│                                                                       │
│ Level 2: Cross-Boundary Consolidation                               │
│   - Identify events spanning month boundaries                        │
│   - Cluster events within ±N days of transitions                    │
│   - Catches multi-month events split across windows                 │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Algorithm

```python
# Proposed layered approach
1. Split date range into monthly windows:
   - June 2025: 1,823 events
   - July 2025: 1,945 events
   - August 2025: 1,712 events
   - ... (7 windows total for June-Dec)

2. For each window:
   - Load events (first_mention <= window_end AND last_mention >= window_start)
   - Compute similarity matrix (1,823 × 1,823 for June)
   - Find groups using same DFS algorithm
   - Set master_event_id for children

3. Cross-boundary pass:
   - Load events near month boundaries (±7 days)
   - Cluster events that span boundaries
   - Handles multi-month events

Total comparisons: ~22 million (7 windows × ~1,800² ÷ 2)
```

**Memory Management**: Smaller matrices per window (1,800 × 1,800 vs 12,329 × 12,329)

**LLM Preservation**: Prioritizes events with `llm_validated = true` as masters

---

## Comparison Table

| Aspect | Existing `consolidate_all_events.py` | Proposed `layered_consolidate_events.py` |
|--------|--------------------------------------|------------------------------------------|
| **Processing Scope** | All events at once (12,329) | Monthly batches (~1,800 each) + cross-boundary |
| **Similarity Comparisons** | ~152M (12,329² ÷ 2) | ~22M (7 × 1,800² ÷ 2) = **7× fewer** |
| **Memory Management** | Chunked computation (1000 rows) | Smaller matrices per window |
| **Time Filtering** | None - processes all events together | Time-windowed - events grouped by month |
| **Threshold Sensitivity** | High (0.75 → mega-groups, 0.85 → 0 groups) | Potentially lower (time-windowing reduces false matches) |
| **LLM Validation Preservation** | Picks highest article_count | **Prioritizes llm_validated = true events** |
| **False Positive Risk** | Higher (events separated by 6 months can match) | Lower (events only match if in same/adjacent months) |
| **Implementation Status** | ✅ Battle-tested, documented | ⚠️ New code, needs validation |
| **Dry-run Support** | ✅ Yes | ✅ Yes |
| **Force Reset** | ✅ Yes | ❌ No (resets manually) |

---

## Key Differences

### 1. Time-Windowing (Main Innovation)

**Existing**: All events for China June-Dec 2025 processed together
- "Belt and Road Forum" event in June can be grouped with "Belt and Road Forum" in December
- High risk of merging unrelated events with similar names

**Layered**: Events processed within monthly windows first
- June's "Belt and Road Forum" only compared with June events initially
- Cross-boundary pass catches legitimate multi-month events
- Reduces false positives from semantically similar but temporally distinct events

**Example Problem**:
- Event A: "China-Egypt Strategic Partnership" (June 15, 5 articles)
- Event B: "China-Egypt Strategic Partnership" (October 3, 8 articles)
- These might be two DIFFERENT diplomatic meetings 4 months apart
- Existing approach: Would merge them (high similarity)
- Layered approach: Would keep separate unless they span the June-October gap

### 2. LLM Validation Preservation

**Existing**: Master selection only considers `article_count` and `days_mentioned`
```python
group_events.sort(key=lambda e: (e['total_articles'], e['days_mentioned']), reverse=True)
master_event = group_events[0]  # Highest article count
```

**Layered**: Prioritizes events already validated by LLM
```python
llm_validated_events = [e for e in cluster_events if e['llm_validated']]
if llm_validated_events:
    master_event = max(llm_validated_events, key=lambda e: e['article_count'])
else:
    master_event = max(cluster_events, key=lambda e: e['article_count'])
```

**Impact**: Protects the expensive LLM deconfliction work the user has already paid for.

### 3. Computational Cost

**Existing**:
- Similarity matrix: 12,329 × 12,329 = ~152M comparisons
- Memory: ~1.2 GB (12,329 × 12,329 × 8 bytes) with chunking
- Processing time: ~8-10 minutes for China

**Layered**:
- 7 windows × (1,800 × 1,800) ≈ 22M comparisons = **7× fewer**
- Memory: ~26 MB per window (1,800 × 1,800 × 8 bytes)
- Processing time: ~8-10 minutes total (similar due to overhead)

**NOTE**: Both approaches handle memory - existing uses chunking, layered uses smaller matrices.

---

## When to Use Which Approach

### Use Existing `consolidate_all_events.py` IF:

1. ✅ You trust the similarity threshold (after tuning)
2. ✅ Events are truly global (not temporally clustered)
3. ✅ You're okay with potential false positives (can fix in LLM deconfliction)
4. ✅ You want the battle-tested, documented approach
5. ✅ You need `--force` reset functionality

**Recommended first approach**: Try existing with threshold 0.82-0.83 (between 0.75 and 0.85)

```bash
# Conservative threshold
python services/pipeline/events/consolidate_all_events.py \
    --country China \
    --similarity-threshold 0.83 \
    --dry-run

# If that's too strict, lower incrementally
python services/pipeline/events/consolidate_all_events.py \
    --country China \
    --similarity-threshold 0.80 \
    --dry-run
```

### Use Layered `layered_consolidate_events.py` IF:

1. ✅ You're getting massive over-consolidation with existing approach
2. ✅ Events are temporally distinct (e.g., annual forums, recurring meetings)
3. ✅ You want to preserve LLM validation work more strictly
4. ✅ You want to experiment with time-based filtering
5. ✅ You're willing to validate a new approach

**Use case**: After existing approach fails even with tuned threshold

```bash
python services/pipeline/events/layered_consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --similarity-threshold 0.80 \
    --dry-run
```

---

## Issues with Current Results

### Problem 1: Duplicate Events (22 variants of "March 10 Agreement")

**Root Cause**: Not a consolidation problem - it's a **Stage 1 problem**
- `batch_cluster_events.py` (daily clustering) isn't catching duplicates within the same day
- LLM deconfliction (`llm_deconflict_clusters.py`) is creating 22 separate canonical_events

**Fix**: Adjust Stage 1 clustering parameters (eps threshold in batch_cluster_events.py)
```bash
# Try stricter clustering
python services/pipeline/events/batch_cluster_events.py \
    --country China \
    --start-date 2025-03-10 \
    --end-date 2025-03-10 \
    --eps 0.10  # Default is 0.15, try stricter
```

**OR**: Fix in Stage 2 with consolidation (either approach should catch these)

### Problem 2: No Multi-Day Events in Metrics

**Root Cause**: Consolidation (Stage 2A) hasn't been run successfully
- User ran with threshold 0.85: Found 0 groups
- User ran with threshold 0.75: Over-consolidated (1,022 children in one group)
- Need to find optimal threshold between 0.75 and 0.85

**Fix**: Run consolidation with intermediate threshold
```bash
# Try 0.80 (midpoint)
python services/pipeline/events/consolidate_all_events.py \
    --country China \
    --similarity-threshold 0.80 \
    --dry-run

# Then apply and run subsequent steps
python services/pipeline/events/consolidate_all_events.py \
    --country China \
    --similarity-threshold 0.80

python services/pipeline/events/merge_canonical_events.py --country China
```

### Problem 3: Lost LLM Work

**Root Cause**: Running consolidation after LLM deconfliction overwrites decisions
- User ran `llm_deconflict_canonical_events.py` (expensive)
- Then ran `consolidate_all_events.py` with 0.75 threshold
- The consolidation grouped events differently than LLM decided

**Fix**:
1. **Correct order**: Run consolidation BEFORE LLM deconfliction
2. **OR** Use layered approach which prioritizes LLM-validated events
3. **OR** Don't re-run consolidation if LLM work is already done

**Recommended Pipeline Order**:
```bash
# Stage 2A: Consolidation (embedding-based grouping)
python services/pipeline/events/consolidate_all_events.py --country China --similarity-threshold 0.80

# Stage 2B: LLM validation (expensive - only run once!)
python services/pipeline/events/llm_deconflict_canonical_events.py --country China

# Stage 2C: Merge daily mentions
python services/pipeline/events/merge_canonical_events.py --country China
```

---

## Recommendation

### Step 1: Try Existing Pipeline with Tuned Threshold

```bash
# Reset consolidation (preserve LLM validation column)
psql -d softpower-db -c "UPDATE canonical_events SET master_event_id = NULL WHERE initiating_country = 'China' AND master_event_id IS NOT NULL;"

# Try threshold 0.82 (between 0.75 and 0.85)
python services/pipeline/events/consolidate_all_events.py \
    --country China \
    --similarity-threshold 0.82 \
    --dry-run

# Check results:
# - Are there mega-groups (100+ events)?
# - Are duplicates being caught (March 10 Agreement variants)?
# - Do event names look semantically related?

# If results look good, apply it
python services/pipeline/events/consolidate_all_events.py \
    --country China \
    --similarity-threshold 0.82

# Then merge and generate metrics
python services/pipeline/events/merge_canonical_events.py --country China

python publications/scripts/generate_metrics_snapshot.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31
```

### Step 2: If Existing Approach Fails, Try Layered

```bash
# Reset again
psql -d softpower-db -c "UPDATE canonical_events SET master_event_id = NULL WHERE initiating_country = 'China' AND master_event_id IS NOT NULL;"

# Try layered approach
python services/pipeline/events/layered_consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --similarity-threshold 0.80 \
    --dry-run

# If results look better, apply it
python services/pipeline/events/layered_consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --similarity-threshold 0.80

# Then merge and generate metrics
python services/pipeline/events/merge_canonical_events.py --country China

python publications/scripts/generate_metrics_snapshot.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31
```

### Step 3: Add doc_ids to Metrics (Regardless of Approach)

Both consolidation approaches should work with the updated metrics snapshot that includes doc_ids for traceability.

---

## Summary

**Key Insight**: The existing pipeline already handles computational feasibility through chunked computation. The new layered approach's main benefit is **time-windowing** to reduce false positives from temporally distinct events.

**Recommendation**:
1. Try existing `consolidate_all_events.py` with threshold 0.80-0.83
2. Only use `layered_consolidate_events.py` if you get unacceptable over-consolidation
3. Update metrics snapshot to include doc_ids for traceability (applies to both approaches)

**User's Expensive LLM Work**: The layered approach's LLM preservation feature would have prevented the lost work, but the better solution is to **not re-run consolidation after LLM deconfliction**. If you've already run LLM deconfliction, don't run consolidation again - just use the existing master_event_id links.
