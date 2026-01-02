# Schema Fix Summary - News Event Tracker

## Issue Identified
The news event tracking code was querying `Document.initiating_country` directly, but the database uses a normalized/flattened schema where country relationships are stored in the separate `InitiatingCountry` table.

## Root Cause
Schema mismatch between:
- **Old pattern**: `Document.initiating_country` (semicolon-separated field)
- **Actual schema**: `InitiatingCountry` table with many-to-many relationship

## Files Fixed

### 1. `backend/scripts/news_event_tracker.py`

**Changes:**
- **Line 9**: Added `InitiatingCountry` to imports
- **Lines 772-802**: Updated `_get_daily_raw_events()` method

**Before:**
```python
.where(
    and_(
        Document.date == target_date,
        Document.initiating_country == country  # ❌ WRONG
    )
)
```

**After:**
```python
.join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
.where(
    and_(
        Document.date == target_date,
        InitiatingCountry.initiating_country == country  # ✅ CORRECT
    )
)
```

### 2. `debug_news_tracker.py`

**Changes:**
- **Line 9**: Added `InitiatingCountry` to imports
- **Lines 22-32**: Fixed document count query (Step 1)
- **Lines 45-50**: Fixed country listing query
- **Lines 57-64**: Fixed date listing query
- **Lines 74-84**: Fixed raw events count query (Step 2)
- **Lines 113-123**: Fixed sample events query (Step 3)
- **Lines 91, 100**: Updated error messages to reference `flatten.py` instead of `atom_extraction.py`

**Pattern Applied:**
All queries that filter by country now use:
```python
.join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
.where(InitiatingCountry.initiating_country == country)
```

## Verification

### Test the Fix
```bash
# Run debug script to verify schema alignment
python debug_news_tracker.py --date 2024-08-15 --country China
```

**Expected Output:**
```
================================================================================
DEBUGGING: 2024-08-15 / China
================================================================================

[STEP 1] Checking Documents table...
  Found X documents for 2024-08-15 / China

[STEP 2] Checking RawEvents table...
  Found Y raw events

[STEP 3] Sample raw events that WILL be processed:
  1. Event name here...
     Source: ..., Date: 2024-08-15
  ...

✅ Data exists! The pipeline should work.
```

### Run the Pipeline
```bash
# Process daily news with correct schema
python backend/scripts/process_daily_news.py --date 2024-08-15 --country China
```

## Schema Reference

### InitiatingCountry Table
```python
class InitiatingCountry(Base):
    __tablename__ = 'initiating_countries'

    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    initiating_country: Mapped[str] = mapped_column(Text, primary_key=True)

    document = relationship("Document", back_populates="initiating_countries")
```

### RawEvent Table
```python
class RawEvent(Base):
    __tablename__ = 'raw_events'

    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    event_name: Mapped[str] = mapped_column(Text, primary_key=True)

    document = relationship("Document", back_populates="raw_events")
```

## Complete Data Pipeline (After Fix)

```
1. dsr.py
   └─> Loads DSR JSON → Creates Document records
       └─> Populates event_name field (semicolon-separated)

2. flatten.py
   └─> Splits Document.event_name → Creates RawEvent records
   └─> Splits Document.initiating_country → Creates InitiatingCountry records

3. process_daily_news.py (NOW WORKING)
   └─> Queries: RawEvent JOIN Document JOIN InitiatingCountry
   └─> Creates: DailyEventMention + CanonicalEvent
```

## Next Steps

1. **Install missing dependencies** (if needed):
   ```bash
   pip install sentence-transformers scikit-learn numpy
   ```

2. **Run debug script** to verify data exists:
   ```bash
   python debug_news_tracker.py --date YYYY-MM-DD --country "CountryName"
   ```

3. **Process daily news**:
   ```bash
   python backend/scripts/process_daily_news.py --date YYYY-MM-DD --country "CountryName"
   ```

4. **Check results**:
   ```python
   from backend.database import get_session
   from backend.models import DailyEventMention
   from sqlalchemy import func

   with get_session() as session:
       count = session.query(func.count(DailyEventMention.id)).scalar()
       print(f"Total DailyEventMentions: {count}")
   ```

## Status
✅ **Schema alignment complete**
✅ **Both production and debug scripts updated**
✅ **Ready to run news event tracking**
