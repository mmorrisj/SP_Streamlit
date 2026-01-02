# Quick Start: News Event Tracker

## Prerequisites

Your workflow uses `dsr.py` to load documents, so you need to run the flattening step first!

## Installation

```bash
# Install dependencies
pip install sentence-transformers scikit-learn numpy

# Verify database
python -c "from backend.database import health_check; print('✅ DB OK' if health_check() else '❌ DB Failed')"
```

## Complete Workflow

### 1. Load Documents (You Already Do This)

```bash
# Load DSR documents from S3
python backend/scripts/dsr.py --source s3
```

### 2. Flatten Event Names (REQUIRED - Creates RawEvent table)

```bash
# This splits Document.event_name by semicolons into RawEvent records
python backend/scripts/flatten.py
```

**Why this is needed:** `process_daily_news.py` queries the `RawEvent` table which is created by flattening the semicolon-separated `event_name` field from your Documents.

### 3. Test Your Setup

```bash
# Run the debug script to verify data exists
python debug_news_tracker.py --date 2024-08-15 --country China
```

This will:
1. Check if Documents exist for that date/country
2. **Check if RawEvents exist** (most common issue!)
3. Show sample events that will be processed
4. Tell you exactly what's wrong if no data found

### 4. Process Daily News

```bash
# Process specific date and country
python backend/scripts/process_daily_news.py --date 2024-08-15 --country China

# Process today for all countries (production mode)
python backend/scripts/process_daily_news.py
```

## Check Results

```python
from backend.database import get_session
from backend.models import DailyEventMention, CanonicalEvent
from sqlalchemy import func

with get_session() as session:
    # Count results
    mentions = session.query(func.count(DailyEventMention.id)).scalar()
    events = session.query(func.count(CanonicalEvent.id)).scalar()

    print(f"DailyEventMentions: {mentions}")
    print(f"CanonicalEvents: {events}")

    # View recent mentions
    recent = session.query(DailyEventMention).order_by(
        DailyEventMention.mention_date.desc()
    ).limit(5).all()

    for mention in recent:
        print(f"{mention.mention_date}: {mention.consolidated_headline}")
        print(f"  Articles: {mention.article_count}, Context: {mention.mention_context}")
```

## What Each Method Does

### 1. `_cluster_daily_events()`
Groups similar articles from same day using embeddings.

**Input**: List of 50 raw events
**Output**: List of 8 clusters (similar events grouped)

### 2. `_llm_deduplicate_clusters()`
Refines clusters using LLM (only for ambiguous cases).

**Input**: 8 clusters
**Output**: 9 refined clusters (one split into two)

### 3. `_semantic_similarity_news()`
Compares today's event to past events using embeddings.

**Input**: Two headlines
**Output**: Similarity score 0.0-1.0

### 4. `_call_llm()`
Handles ambiguous temporal matches with LLM reasoning.

**Input**: Prompt with event details
**Output**: Decision to link or create new

### 5. `_entity_consistency_score()`
Checks if same actors/locations mentioned.

**Input**: Two event descriptions
**Output**: Entity overlap score 0.0-1.0

## Typical Output

```
Processing news for 2024-08-15...
  Processing China...
    Fetching raw events... Found 52 events
    Generating embeddings for 52 events...
    Clustering events...
    Found 12 clusters from 52 events
    LLM deduplication for cluster with 6 unique names...
    Found 13 unique events
✅ Daily processing complete

Results:
  DailyEventMentions: 13
  CanonicalEvents: 10 (3 linked to existing, 10 new)
```

## Tuning Parameters

### Make clustering stricter (fewer, larger clusters)
Edit `news_event_tracker.py` line 106:
```python
eps=0.10,  # Lower = stricter (was 0.15)
```

### Make clustering looser (more, smaller clusters)
```python
eps=0.20,  # Higher = looser
```

### Adjust similarity thresholds
Edit `news_event_tracker.py` line 164:
```python
base_threshold = 0.70  # Lower = more linking (was 0.75)
```

## Common Issues

### "No raw events found"
Your documents need event extraction first:
```bash
python backend/scripts/atom_extraction.py
```

### "LLM call failed"
Check your OpenAI/Azure API credentials:
```bash
python -c "from backend.scripts.utils import gai; print(gai('test', 'hello'))"
```

### Slow embedding generation
Use GPU (if available):
```python
# Edit news_event_tracker.py line 27
self.embedding_model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2",
    device='cuda'
)
```

## Next Steps

1. **Run test script** to verify data exists
2. **Process one day** to see it work
3. **Check results** in database
4. **Adjust parameters** if needed
5. **Set up daily cron job** for production

## Production Cron Job

```bash
# Add to crontab: run daily at 2 AM
0 2 * * * cd /path/to/SP_Streamlit && python backend/scripts/process_daily_news.py >> /var/log/daily_news.log 2>&1
```

## Monitoring

```python
# Check for stale events
from backend.database import get_session
from backend.models import CanonicalEvent
from datetime import date, timedelta

with get_session() as session:
    stale_events = session.query(CanonicalEvent).filter(
        CanonicalEvent.days_since_last_mention > 30,
        CanonicalEvent.story_phase != 'dormant'
    ).all()

    print(f"Found {len(stale_events)} events that need attention")
```

For detailed implementation info, see `NEWS_EVENT_TRACKER_IMPLEMENTATION.md`.
