# ROOT CAUSE: Temporal Linking Not Working in news_event_tracker.py

## Problem Summary

The `news_event_tracker.py` script creates a **NEW canonical event for EACH DAY** instead of linking events across time. This results in events like "Arbaeen Pilgrimage" being stored as 41 separate canonical events (one per day) instead of a single multi-day event.

## Evidence

Query results show events mentioned across many days but stored as separate canonical events:

```
"Arbaeen Pilgrimage":
  - Mentioned across 41 days (2024-08-23 to 2025-11-09)
  - But stored as 41 SEPARATE canonical_events
  - Each canonical event has only 1 day of daily_event_mentions

"Iran Hamdel Campaign":
  - Mentioned across 61 days
  - But stored as 61 SEPARATE canonical_events
```

## Code Location

**File**: `services/pipeline/events/news_event_tracker.py`
**Method**: `_create_or_link_daily_mention()` (lines 227-299)

### What Should Happen

```python
def _create_or_link_daily_mention(
    self,
    cluster: List[Dict],
    target_date: date,
    country: str
) -> DailyEventMention:
    """
    Core temporal linking logic.
    Determine if this daily cluster matches an existing canonical event.
    """

    # Step 1: Create daily mention object first
    daily_mention = self._create_daily_mention_record(cluster, target_date, country)

    # Step 2: Find candidate canonical events based on lookback window
    candidates = self._get_candidate_canonical_events(
        country,
        target_date,
        lookback_days  # e.g., 3-90 days based on context
    )

    if not candidates:
        # No previous events - create new canonical event
        canonical_event = self._create_new_canonical_event(daily_mention, country)
        daily_mention.canonical_event_id = canonical_event.id
        return daily_mention

    # Step 3: Find best match using similarity
    best_match, best_score = self._find_best_canonical_match(
        daily_mention,
        candidates,
        target_date
    )

    if best_score >= threshold:
        # LINK to existing canonical event
        canonical_event = best_match
        daily_mention.canonical_event_id = best_match.id
        # Update canonical event's last_mention_date, etc.
    else:
        # Create new canonical event
        canonical_event = self._create_new_canonical_event(daily_mention, country)
```

### What's Actually Happening

The temporal linking logic (Step 3) is **not working** and **always creates a new canonical event**.

This means:
- `_get_candidate_canonical_events()` returns empty or doesn't find matches
- OR `_find_best_canonical_match()` never scores high enough
- OR the code path isn't even reaching the matching logic

## Current Workaround

**Temporary Fix**: `merge_canonical_events.py`
- Post-processes the database after `consolidate_all_events.py`
- Merges child events into their master events
- Consolidates daily_event_mentions into single multi-day events

**Flow**:
1. `news_event_tracker.py` creates fragmented events (1 per day)
2. `consolidate_all_events.py` groups them via `master_event_id`
3. `merge_canonical_events.py` merges them into true multi-day events

## Permanent Fix Needed

### Option 1: Fix news_event_tracker.py Temporal Linking

**Investigate**:
1. Why doesn't `_get_candidate_canonical_events()` find matches?
   - Is the lookback window too short?
   - Is the country filter too strict?
   - Are there no canonical events being created at all?

2. Why doesn't `_find_best_canonical_match()` match events?
   - Is the similarity threshold too high?
   - Are embeddings not being compared correctly?
   - Is the temporal gap penalty too severe?

3. Is the code path even executing?
   - Add logging to each decision point
   - Verify candidates are being retrieved
   - Check if LLM temporal resolution is being called

**Fix**:
- Debug the temporal linking logic
- Lower similarity thresholds if needed
- Increase lookback windows
- Add better logging/diagnostics

### Option 2: Redesign Event Detection Architecture

Instead of trying to link events across days in real-time:

1. **Daily Phase**: Create events per day without linking
2. **Consolidation Phase**: Run batch consolidation across all dates
   - Use embedding similarity to find related events
   - Use LLM to validate groupings
   - Merge daily_event_mentions into master events

This is essentially what we're doing now with the workaround, but would be formalized as the intended architecture.

**Advantages**:
- Simpler real-time processing
- Better batch consolidation with full dataset context
- LLM validation of groupings
- Cleaner separation of concerns

**Disadvantages**:
- Events aren't linked in real-time
- Requires batch processing step

## Recommended Approach

**Short-term** (DONE):
- Use `merge_canonical_events.py` to fix existing data
- Run after `consolidate_all_events.py` in the pipeline

**Long-term** (TODO):
- Investigate why temporal linking in `news_event_tracker.py` isn't working
- Add comprehensive logging to debug the issue
- Consider redesigning to embrace batch consolidation as the primary approach
- Update documentation to reflect the actual architecture

## Impact

**Before Fix**:
- 55,835 master events, all with only 1 day of mentions
- "Arbaeen Pilgrimage" = 41 separate events
- No ability to track event duration or evolution over time

**After Fix**:
- Multi-day events with mentions spanning days/weeks/months
- "Arbaeen Pilgrimage" = 1 event with 41 days of mentions
- Proper long-term activity tracking

## Files Involved

1. **news_event_tracker.py** - Root cause (temporal linking broken)
2. **consolidate_all_events.py** - Groups events via embedding similarity
3. **llm_deconflict_canonical_events.py** - LLM validation of groupings
4. **merge_canonical_events.py** - Temporary fix to create multi-day events
