# Manual Step-by-Step Workflow for News Event Consolidation

## Current Status: Testing Phase

Run these commands **one at a time** to debug and validate each step.

---

## Step 1: Load Documents (You Already Do This)

```bash
# Load DSR documents from S3
python backend/scripts/dsr.py --source s3 --no-embed
```

**What this does:**
- Loads DSR JSON files from S3
- Parses the AI-extracted fields
- Populates `Document.event_name` field (semicolon-separated)
- Creates Document records in the database

**Verify it worked:**
```bash
python -c "from backend.database import get_session; from backend.models import Document; from sqlalchemy import func; session = get_session().__enter__(); count = session.query(func.count(Document.doc_id)).scalar(); print(f'✅ Documents in database: {count}')"
```

---

## Step 2: Flatten Event Names (Creates RawEvent Table)

```bash
# Split semicolon-separated event names into individual RawEvent records
python backend/scripts/flatten.py --batch-size 1000
```

**What this does:**
- Reads `Document.event_name` field
- Splits by semicolon (e.g., "Event A; Event B" → 2 records)
- Creates `RawEvent(doc_id, event_name)` records
- **This is what `process_daily_news.py` needs to work!**

**Verify it worked:**
```bash
python -c "from backend.database import get_session; from backend.models import RawEvent; from sqlalchemy import func; session = get_session().__enter__(); count = session.query(func.count(RawEvent.event_name)).scalar(); print(f'✅ RawEvents in database: {count}')"
```

---

## Step 3: Debug/Verify Data Exists for Your Date

```bash
# Check what data is available for a specific date/country
python debug_news_tracker.py --date 2024-08-15 --country China
```

**This will tell you:**
- ✅ Do Documents exist for this date/country?
- ✅ Do RawEvents exist?
- ✅ Sample events that will be processed
- ❌ If something is missing, it tells you exactly what

**If you see "❌ NO RAW EVENTS FOUND"** → Go back to Step 2!

---

## Step 4: Process Daily News Consolidation (ONE DATE AT A TIME)

```bash
# Process a single date and country to test
python backend/scripts/process_daily_news.py --date 2024-08-15 --country China
```

**What this does:**
- Queries `RawEvent` JOIN `Document` for that date/country
- Generates embeddings for event names
- Clusters similar events using DBSCAN
- LLM deduplication (only for complex clusters)
- Creates `DailyEventMention` records
- Links to `CanonicalEvent` (creates new or links to existing)
- Tracks all source `doc_ids`

**Expected output:**
```
Processing news for 2024-08-15...
  Processing China...
    Fetching raw events...
    Found 52 raw events
    Generating embeddings for 52 events...
    Clustering events...
    Found 12 clusters from 52 events
    Processing 12 deduplicated clusters...
    Found 12 unique events
✅ Daily processing complete
```

---

## Step 5: Verify Results

```bash
# Check if DailyEventMentions were created
python -c "from backend.database import get_session; from backend.models import DailyEventMention; from sqlalchemy import func; session = get_session().__enter__(); count = session.query(func.count(DailyEventMention.id)).scalar(); print(f'✅ Total DailyEventMentions: {count}')"
```

**View the created mentions:**
```python
from backend.database import get_session
from backend.models import DailyEventMention, CanonicalEvent
from sqlalchemy import select

with get_session() as session:
    # Get mentions for your processed date
    stmt = (
        select(DailyEventMention)
        .where(DailyEventMention.mention_date == '2024-08-15')
        .limit(10)
    )
    mentions = list(session.scalars(stmt).all())

    for i, mention in enumerate(mentions, 1):
        print(f"\n{i}. {mention.consolidated_headline}")
        print(f"   Date: {mention.mention_date}")
        print(f"   Articles: {mention.article_count}")
        print(f"   Sources: {', '.join(mention.source_names)}")
        print(f"   Doc IDs: {mention.doc_ids[:3]}...")
        print(f"   Context: {mention.mention_context}")
        print(f"   Intensity: {mention.news_intensity}")

        # Show linked canonical event
        canonical = session.get(CanonicalEvent, mention.canonical_event_id)
        print(f"   → Linked to: {canonical.canonical_name}")
        print(f"   → Story Phase: {canonical.story_phase}")
```

---

## Troubleshooting Decision Tree

### Issue: "Found 0 unique events"

**Run diagnostic:**
```bash
python debug_news_tracker.py --date 2024-08-15 --country China
```

**Possible causes:**

1. **"❌ NO DOCUMENTS FOUND"**
   - Check if date is correct (use debug script to see available dates)
   - Check if country name matches config.yaml exactly

2. **"❌ NO RAW EVENTS FOUND"**
   - RawEvent table is empty
   - **Solution:** Run `python backend/scripts/flatten.py`

3. **"⚠️ Clustering produced 0 clusters"**
   - Rare issue with embedding model
   - Check logs for errors

4. **"⚠️ Deduplication produced 0 clusters"**
   - LLM error
   - Check your OpenAI/Azure API credentials

---

## Quick Diagnostic Commands

### Check Documents
```bash
python -c "from backend.database import get_session; from backend.models import Document; from sqlalchemy import select, func; session = get_session().__enter__(); dates = session.execute(select(func.min(Document.date), func.max(Document.date))).first(); print(f'Date range: {dates[0]} to {dates[1]}')"
```

### Check RawEvents
```bash
python -c "from backend.database import get_session; from backend.models import RawEvent; from sqlalchemy import func; session = get_session().__enter__(); count = session.query(func.count(RawEvent.event_name)).scalar(); print(f'RawEvents: {count}')"
```

### Check Countries Available
```bash
python -c "from backend.database import get_session; from backend.models import Document; from sqlalchemy import select; session = get_session().__enter__(); countries = list(session.scalars(select(Document.initiating_country).distinct()).all()); print(f'Countries: {countries[:20]}')"
```

### Check Dates with Data for a Specific Country
```bash
python -c "from backend.database import get_session; from backend.models import Document; from sqlalchemy import select, func; session = get_session().__enter__(); dates = list(session.execute(select(Document.date, func.count(Document.doc_id)).where(Document.initiating_country == 'China').group_by(Document.date).order_by(Document.date.desc()).limit(10)).all()); print('Recent dates for China:'); [print(f'  {d[0]}: {d[1]} docs') for d in dates]"
```

---

## Once You Confirm It Works

After successfully processing one date, you can:

1. **Process more dates:**
   ```bash
   python backend/scripts/process_daily_news.py --date 2024-08-16 --country China
   python backend/scripts/process_daily_news.py --date 2024-08-17 --country China
   ```

2. **Process all countries for one date:**
   ```bash
   python backend/scripts/process_daily_news.py --date 2024-08-15
   ```

3. **Process today for all countries:**
   ```bash
   python backend/scripts/process_daily_news.py
   ```

---

## Your Next Steps

Run these commands **in order** on your server:

```bash
# 1. Check if you have Documents
python -c "from backend.database import get_session; from backend.models import Document; from sqlalchemy import func; session = get_session().__enter__(); print(f'Documents: {session.query(func.count(Document.doc_id)).scalar()}')"

# 2. Check if you have RawEvents (probably 0!)
python -c "from backend.database import get_session; from backend.models import RawEvent; from sqlalchemy import func; session = get_session().__enter__(); print(f'RawEvents: {session.query(func.count(RawEvent.event_name)).scalar()}')"

# 3. If RawEvents is 0, run flatten
python backend/scripts/flatten.py

# 4. Run debug to find a good date/country
python debug_news_tracker.py --date 2024-08-15 --country China

# 5. Process that date
python backend/scripts/process_daily_news.py --date 2024-08-15 --country China

# 6. Check results
python -c "from backend.database import get_session; from backend.models import DailyEventMention; from sqlalchemy import func; session = get_session().__enter__(); print(f'DailyEventMentions: {session.query(func.count(DailyEventMention.id)).scalar()}')"
```

---

## Common Workflow After Initial Setup

Once everything is working, your typical workflow becomes:

```bash
# When you load new DSR data:
python backend/scripts/dsr.py --source s3 --no-embed

# Flatten the new event names:
python backend/scripts/flatten.py

# Process the new day's events:
python backend/scripts/process_daily_news.py --date 2024-MM-DD --country CountryName
```

That's it! Three steps, run manually, debug as needed.
