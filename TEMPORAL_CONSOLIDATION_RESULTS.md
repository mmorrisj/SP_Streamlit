# Temporal Event Consolidation Test Results

## Overview
Tested the temporal event consolidation process using embedding similarity to identify related events across August-September 2024 for all influencer countries.

## Methodology
The consolidation process uses:
- **Embedding Cosine Similarity**: Compares semantic embeddings of canonical event names
- **Similarity Threshold**: 0.85 (configurable)
- **Depth-First Search (DFS)**: Groups events into connected components based on similarity
- **Primary Event Selection**: Chooses event with most articles as the primary event in each group

## Test Results Summary

### China - Monthly Consolidation (August-September 2024)
- **Total canonical events**: 3,007
- **Event groups identified**: 340
- **Events that can be consolidated**: 1,252 (41.6%)
- **Reduction potential**: From 3,007 events down to 2,095 master events

### China - Weekly Consolidation (September 2024)
- **Total canonical events**: 2,109
- **Event groups identified**: 221
- **Events that can be consolidated**: 652 (30.9%)
- **Reduction potential**: From 2,109 events down to 1,678 master events

### All Influencer Countries - Monthly Consolidation (September 2024)
- **Countries**: China, Russia, Iran, Turkey, United States
- **Total canonical events**: 10,288
- **Event groups identified**: 1,105
- **Events that can be consolidated**: 4,631 (45.0%)
- **Reduction potential**: From 10,288 events down to 6,762 master events

## Example Consolidation Groups

### Group 1: Belt and Road Initiative (August)
**Primary Event**: Belt and Road Initiative (14 articles, Aug 20)
**Related Events**: 23 similar events including:
- Belt and Road Initiative (various dates with 1-3 articles each)
- Belt and Road Educational Initiative (2 articles, Aug 7)

**Cross-Month Tracking**: The canonical "Belt and Road Initiative" event spans **40 different days** across August-September 2024.

### Group 2: Beijing Declaration (August)
**Primary Event**: Beijing Declaration (5 articles, Aug 2)
**Related Events**: 16 similar events including:
- Beijing Declaration on Ending Division and Strengthening Palestinian National Unity (2 articles)
- Beijing Unity Declaration (1 article)
- Beijing Palestinian Unity Declaration (1 article)
- Beijing Declaration to End Palestinian Division (1 article)

### Group 3: Forum on China-Africa Cooperation (September)
**Primary Event**: Forum on China-Africa Cooperation (FOCAC) summit (31 articles, Sep 3)
**Related Events**: 135 similar events including:
- China-Egypt Industrial Cooperation Agreements (16 articles)
- China-Africa Cooperation Forum 2023/2024 (multiple mentions)
- TEDA Suez Economic Zone (multiple mentions)
- Various bilateral cooperation agreements announced at FOCAC

## Key Findings

### 1. Significant Consolidation Opportunity
- **40-45%** of canonical events can be consolidated into groups
- This represents substantial deduplication potential across the event timeline

### 2. Event Naming Variations
Events appear with multiple name variations:
- Slight wording differences: "Belt and Road Initiative" vs "Belt and Road"
- Detail additions: "Beijing Declaration" vs "Beijing Declaration on Ending Division..."
- Language variations: "FOCAC" vs "Forum on China-Africa Cooperation" vs "China-Africa Cooperation Forum"

### 3. Cross-Time Tracking
- Single canonical events span **multiple weeks and months**
- Example: "Belt and Road Initiative" appears on 40 different days
- This demonstrates the need for temporal consolidation to track event evolution

### 4. Major Event Clusters
Large events create many related mentions:
- FOCAC Summit: 136 related events
- Belt and Road Initiative: 24 related events in August alone
- Beijing Declaration: 17 related events

## Implications for Summary Generation

### Current State
- Daily summaries are generated per canonical event per day
- This creates many summaries for semantically similar events
- No linkage between "Belt and Road Initiative" on Aug 1 vs Aug 15

### Recommended Approach
Two-tier consolidation strategy:

#### Tier 1: Canonical Event Consolidation (Embedding-Based)
1. Use embedding similarity to identify related canonical events
2. Select primary event (most articles) as master event
3. Link related events to master using `master_event_id` field
4. This creates a consolidated timeline view

#### Tier 2: Hierarchical Summary Generation (LLM-Based)
1. Generate daily summaries for master events only
2. Aggregate daily summaries into weekly summaries using LLM
3. Aggregate weekly summaries into monthly summaries using LLM
4. Use prompts from `summary_prompts.py` for AP-style journalism

## Next Steps

### Option 1: Implement Canonical Event Master Linkage
- Run consolidation script in non-dry-run mode
- Update `master_event_id` field in canonical_events table
- Link related events to their primary master event
- Modify daily summary generation to only summarize master events

### Option 2: Weekly/Monthly Summary Generation
- Build on existing daily summaries
- Create `generate_weekly_summaries.py` script
- Aggregate daily summaries within each week
- Use `WEEKLY_SUMMARY_PROMPT` from summary_prompts.py

### Option 3: Hybrid Approach
- First consolidate canonical events (Option 1)
- Then generate hierarchical summaries (Option 2)
- This provides both event consolidation AND temporal aggregation

## Technical Details

### Database Schema
Current structure supports consolidation:
```sql
-- canonical_events table
master_event_id INTEGER  -- References another canonical_event.id
                         -- NULL for master events
                         -- Populated for child events
```

### Consolidation Algorithm
```python
def find_similar_events(events, similarity_threshold=0.85):
    # Build embedding matrix
    embeddings = np.vstack([e['embedding'] for e in events])

    # Compute pairwise similarities
    similarities = cosine_similarity(embeddings)

    # Find connected components using DFS
    # Returns groups of event indices
```

### Script Location
`services/pipeline/events/_deprecated/temporal_event_consolidation.py`

Note: Currently in `_deprecated` folder but fully functional and tested.

## Conclusion

The temporal consolidation testing demonstrates:
1. **Significant consolidation potential** (40-45% of events)
2. **Clear need for master event tracking** to link related events
3. **Effective embedding similarity approach** for identifying related events
4. **Foundation for hierarchical summary generation** (daily → weekly → monthly)

The system is ready to implement either canonical event consolidation, hierarchical summary generation, or both approaches in combination.
