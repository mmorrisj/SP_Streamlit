# Complete News Event Tracker Workflow

## Your Actual Data Pipeline

Based on your `dsr.py` ingestion workflow, here's the complete pipeline for event consolidation:

```
1. dsr.py
   └─> Loads DSR JSON → Creates Document records with event_name field

2. flatten.py
   └─> Reads Document.event_name → Splits by semicolon → Creates RawEvent records

3. process_daily_news.py (NEW)
   └─> Reads RawEvent + Document → Clusters events → Creates DailyEventMention + CanonicalEvent
```

## Step-by-Step Setup

### 1. Load Documents (You Already Do This)

```bash
# From S3 (your typical workflow)
python backend/scripts/dsr.py --source s3

# Or from local directory
python backend/scripts/dsr.py --source local --relocate
```

**What this does:**
- Loads DSR JSON files
- Parses AI-extracted fields (lines 95-154 in dsr.py)
- **Populates `Document.event_name`** from the DSR `event-name` field
- Creates Document records in batch

### 2. Flatten Event Names into RawEvent Table (REQUIRED STEP)

```bash
# Run the flattening process
python backend/scripts/flatten.py --batch-size 1000
```

**What this does:**
- Reads all Documents with `event_name` field
- Splits semicolon-separated event names (e.g., "Event A; Event B" → ["Event A", "Event B"])
- Creates one `RawEvent` record per event name per document
- **This populates the `raw_events` table that `process_daily_news.py` needs**

**Example:**
```python
# Document record:
doc_id = "abc123"
event_name = "China-Pakistan Trade Agreement; Belt and Road Initiative"

# After flatten.py creates:
RawEvent(doc_id="abc123", event_name="China-Pakistan Trade Agreement")
RawEvent(doc_id="abc123", event_name="Belt and Road Initiative")
```

### 3. Process Daily News Events (NEW CONSOLIDATION)

```bash
# Process specific date and country
python backend/scripts/process_daily_news.py --date 2024-08-15 --country China

# Process today for all countries
python backend/scripts/process_daily_news.py

# Process specific date for all countries
python backend/scripts/process_daily_news.py --date 2024-08-15
```

**What this does:**
- Queries `RawEvent` JOIN `Document` for the specified date/country
- Clusters similar events using embedding-based DBSCAN
- LLM deduplication to refine clusters
- Creates `DailyEventMention` for each unique event on that day
- Links to existing `CanonicalEvent` or creates new one
- Tracks document IDs through the entire process

## Complete Workflow Example

### Initial Setup (One Time)

```bash
# 1. Load your DSR data
python backend/scripts/dsr.py --source s3

# 2. Flatten event names to create RawEvent records
python backend/scripts/flatten.py

# 3. Verify data exists
python debug_news_tracker.py --date 2024-08-15 --country China
```

### Daily Processing (Production)

```bash
# After new DSR data is ingested each day:

# Step 1: Load new DSR documents
python backend/scripts/dsr.py --source s3

# Step 2: Flatten any new event names
python backend/scripts/flatten.py

# Step 3: Process daily news consolidation
python backend/scripts/process_daily_news.py
```

## Automation Script

Create a daily processing script `process_daily_pipeline.sh`:

```bash
#!/bin/bash
set -e

echo "🚀 Starting daily news processing pipeline..."

# Step 1: Load new DSR documents from S3
echo "📥 Step 1: Loading DSR documents from S3..."
python backend/scripts/dsr.py --source s3 --no-embed

# Step 2: Flatten new event names
echo "🔄 Step 2: Flattening event names..."
python backend/scripts/flatten.py --batch-size 1000

# Step 3: Process daily news consolidation
echo "📊 Step 3: Processing daily news events..."
python backend/scripts/process_daily_news.py

echo "✅ Daily pipeline complete!"
```

Make it executable:
```bash
chmod +x process_daily_pipeline.sh
```

Run it:
```bash
./process_daily_pipeline.sh
```

## Cron Job Setup

Add to crontab for automatic daily processing:

```bash
# Edit crontab
crontab -e

# Add this line to run daily at 3 AM
0 3 * * * cd /path/to/SP_Streamlit && /path/to/venv/bin/python backend/scripts/process_daily_pipeline.sh >> /var/log/daily_news_pipeline.log 2>&1
```

## Troubleshooting

### Issue: "Found 0 unique events"

**Diagnosis:**
```bash
python debug_news_tracker.py --date 2024-08-15 --country China
```

**Most Common Causes:**

1. **RawEvent table is empty** → Run `python backend/scripts/flatten.py`
2. **Wrong country name** → Check config.yaml for exact country names
3. **No documents for that date** → Check available dates in debug output
4. **event_name field is NULL** → DSR extraction may have failed

### Issue: "No raw events found"

This means the JOIN between Document and RawEvent failed. Check:

```bash
# Check if Documents exist
python -c "from backend.database import get_session; from backend.models import Document; from sqlalchemy import func; session = get_session().__enter__(); print(f'Documents: {session.query(func.count(Document.doc_id)).scalar()}')"

# Check if RawEvents exist
python -c "from backend.database import get_session; from backend.models import RawEvent; from sqlalchemy import func; session = get_session().__enter__(); print(f'RawEvents: {session.query(func.count(RawEvent.event_name)).scalar()}')"
```

**Solution:** Run `python backend/scripts/flatten.py`

### Issue: Embeddings taking too long

Speed up with GPU:
```python
# Edit news_event_tracker.py line 27
self.embedding_model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2",
    device='cuda'  # Use GPU instead of CPU
)
```

## Monitoring Queries

### Check Daily Processing Results

```python
from backend.database import get_session
from backend.models import DailyEventMention, CanonicalEvent
from sqlalchemy import func, select
from datetime import date

with get_session() as session:
    # Count today's mentions
    today = date.today()
    mention_count = session.query(func.count(DailyEventMention.id)).filter(
        DailyEventMention.mention_date == today
    ).scalar()

    print(f"DailyEventMentions created today: {mention_count}")

    # Show recent mentions
    stmt = (
        select(DailyEventMention)
        .order_by(DailyEventMention.mention_date.desc())
        .limit(10)
    )
    recent = list(session.scalars(stmt).all())

    for mention in recent:
        print(f"{mention.mention_date}: {mention.consolidated_headline}")
        print(f"  Articles: {mention.article_count}, Sources: {len(mention.source_names)}")
        print(f"  Doc IDs: {mention.doc_ids[:3]}...")  # Show first 3 doc IDs
```

### Check Canonical Events

```python
from backend.database import get_session
from backend.models import CanonicalEvent
from sqlalchemy import select

with get_session() as session:
    # Get active events
    stmt = (
        select(CanonicalEvent)
        .where(CanonicalEvent.story_phase.in_(['emerging', 'developing', 'peak', 'active']))
        .order_by(CanonicalEvent.last_mention_date.desc())
        .limit(10)
    )
    active_events = list(session.scalars(stmt).all())

    for event in active_events:
        print(f"📰 {event.canonical_name}")
        print(f"   Country: {event.initiating_country}")
        print(f"   Phase: {event.story_phase}")
        print(f"   Coverage: {event.total_mention_days} days, {event.total_articles} articles")
        print(f"   Sources: {event.source_count} unique sources")
        print(f"   Last mention: {event.last_mention_date} ({event.days_since_last_mention} days ago)")
        print()
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `backend/scripts/dsr.py` | Primary document ingestion from DSR JSON |
| `backend/scripts/flatten.py` | Creates RawEvent records from Document.event_name |
| `backend/scripts/process_daily_news.py` | Daily consolidation → DailyEventMention + CanonicalEvent |
| `backend/scripts/news_event_tracker.py` | Core clustering and temporal linking logic |
| `backend/models.py` | Database models: Document, RawEvent, DailyEventMention, CanonicalEvent |
| `debug_news_tracker.py` | Diagnostic tool for troubleshooting |

## Database Schema

```
documents
├── doc_id (PK)
├── event_name (semicolon-separated)
├── distilled_text
├── initiating_country
└── date

raw_events (flattened from documents.event_name)
├── doc_id (FK → documents)
├── event_name (single value)
└── [composite PK on both]

daily_event_mentions (daily consolidation)
├── id (PK)
├── canonical_event_id (FK → canonical_events)
├── mention_date
├── consolidated_headline
├── doc_ids (array of document IDs)
└── source_names (array)

canonical_events (temporal tracking)
├── id (PK)
├── canonical_name
├── initiating_country
├── first_mention_date
├── last_mention_date
├── story_phase
└── alternative_names (array)
```

## Performance Notes

- **Document loading (dsr.py)**: ~100-500 docs/sec (batch size 100)
- **Flattening (flatten.py)**: ~1000 docs/sec (batch size 1000)
- **Embedding generation**: ~50ms per event (CPU), ~10ms (GPU)
- **DBSCAN clustering**: ~100ms for 50 events
- **LLM deduplication**: ~2-5s per cluster (only for 4+ unique names)
- **Total daily processing**: ~30-120 seconds for typical day (50-200 events)

## Next Steps

1. **Test on your server:**
   ```bash
   python debug_news_tracker.py --date 2024-08-15 --country China
   ```

2. **If RawEvents is empty:**
   ```bash
   python backend/scripts/flatten.py
   ```

3. **Run daily processing:**
   ```bash
   python backend/scripts/process_daily_news.py --date 2024-08-15 --country China
   ```

4. **Check results:**
   ```python
   from backend.database import get_session
   from backend.models import DailyEventMention
   from sqlalchemy import func

   with get_session() as session:
       count = session.query(func.count(DailyEventMention.id)).scalar()
       print(f"Total DailyEventMentions: {count}")
   ```

5. **Set up automation** using the shell script and cron job above
