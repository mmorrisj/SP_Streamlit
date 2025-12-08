# Archived Event Processing Files

These files describe approaches that were designed but not implemented in the final architecture, or documentation that described the current pipeline incorrectly.

## Archived Files

### news_event_tracker.py
- **Status**: Not used in current pipeline
- **Description**: Comprehensive real-time temporal linking implementation (1106 lines)
- **Reason for archiving**: The system uses a two-stage batch consolidation approach instead
- **Replacement**:
  - Stage 1: `batch_cluster_events.py` + `llm_deconflict_clusters.py`
  - Stage 2: `consolidate_all_events.py` + `llm_deconflict_canonical_events.py` + `merge_canonical_events.py`

**Design Notes**: This file contains sophisticated logic for real-time temporal linking:
- Context-aware lookback windows (3-90 days)
- Adaptive similarity thresholds
- Story arc coherence checking
- LLM temporal resolution for ambiguous cases

However, the two-stage batch consolidation approach was chosen instead because:
1. Batch consolidation has full dataset context
2. Embedding similarity works better with complete data
3. LLM validation is more reliable with full event history
4. Clearer separation of concerns (daily vs. temporal consolidation)

### ROOT_CAUSE_TEMPORAL_LINKING.md
- **Status**: Misleading documentation
- **Description**: Describes `news_event_tracker.py` temporal linking as "broken" and needing fixes
- **Reason for archiving**: Temporal linking isn't broken - it was simply never the chosen architecture
- **Key Misconception**: Suggested `merge_canonical_events.py` was a "temporary fix" when it's actually Stage 2C of the designed workflow

**What This Document Got Wrong**:
- ❌ Claimed temporal linking in `news_event_tracker.py` is broken and needs fixing
- ❌ Described batch consolidation as a workaround
- ❌ Suggested the architecture needs fundamental changes

**Reality**:
- ✅ Two-stage batch consolidation is the intended design
- ✅ Daily events are correctly created separately per day (by design)
- ✅ Batch consolidation properly links them temporally in Stage 2
- ✅ `merge_canonical_events.py` is part of the designed workflow, not a temporary fix

### FUTURE_ENHANCEMENTS.md
- **Status**: Outdated roadmap
- **Description**: Proposed enhancements with 2024 timelines
- **Reason for archiving**: References already-implemented features and outdated timelines
- **Key Issues**:
  - Says "Phase 2 (Q1 2025): Implement vector similarity search"
  - Vector similarity is already implemented in `consolidate_all_events.py`
  - Timeline references are from 2024

### consolidate_canonical_events.py
- **Status**: Replaced by newer implementation
- **Description**: Monthly consolidation script with `--period month` parameter
- **Reason for archiving**: Replaced by `consolidate_all_events.py` which processes entire dataset at once
- **Replacement**: `consolidate_all_events.py` - Processes all canonical events without time filtering

## Current Architecture

The **actual implemented pipeline** uses a two-stage approach:

### Stage 1: Daily Processing
1. **batch_cluster_events.py** - Clusters raw events per day using DBSCAN + embeddings
2. **llm_deconflict_clusters.py** - LLM validates and creates canonical_events

### Stage 2: Batch Consolidation (Across All Dates)
3. **consolidate_all_events.py** - Groups canonical events using embedding similarity
4. **llm_deconflict_canonical_events.py** - LLM validates consolidation
5. **merge_canonical_events.py** - Creates multi-day events by consolidating daily_event_mentions

## Documentation

For current architecture documentation, see:
- `../EVENT_PROCESSING_ARCHITECTURE.md` - Comprehensive architecture explanation
- `../../CLAUDE.md` - Event processing commands
- `../../PIPELINE.md` - Pipeline step-by-step guide

## Why These Files Are Preserved

These files are archived rather than deleted because:
1. They contain valuable design thinking and alternative approaches
2. Historical context for understanding design decisions
3. Reference for future architectural discussions
4. `news_event_tracker.py` contains sophisticated temporal linking logic that may inform future enhancements

---

**Last Updated**: December 2024
**Archived By**: Documentation cleanup to align with actual implementation
