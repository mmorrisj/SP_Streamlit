# Event/Project Field Flattening

## Overview

The DSR parser now **automatically flattens** all event and project-related fields into the `RawEvent` table, creating a normalized many-to-many relationship between documents and events/projects.

## How It Works

### Fields Tracked in Document Model

The following fields are stored directly in the `documents` table for reference:

- **`event_name`**: Primary event field (from `event-name` in JSON)
- **`project_name`**: Legacy field (from `project-name` in JSON)
- **`projects`**: Projects field (from `projects` in JSON)

These fields are **kept for backward compatibility and quick reference**, but the authoritative source of all events/projects is the `RawEvent` table.

### Flattening to RawEvent Table

After documents are inserted, the `flatten_events_to_raw_events()` function:

1. **Extracts** all values from `event_name`, `project_name`, and `projects` fields
2. **Splits** semicolon-separated values (e.g., `"Event A; Event B"` → `["Event A", "Event B"]`)
3. **Deduplicates** to avoid inserting the same event multiple times for one document
4. **Inserts** into `raw_events` table as separate rows

### Example

**JSON Input:**
```json
{
  "event-name": "Moscow Format Diplomatic Meeting",
  "project-name": "Moscow Format",
  "projects": "Peace Negotiations; Regional Stability"
}
```

**Document Table** (single row):
```
doc_id: abc123
event_name: "Moscow Format Diplomatic Meeting"
project_name: "Moscow Format"
projects: "Peace Negotiations; Regional Stability"
```

**RawEvent Table** (4 rows created):
```
| doc_id  | event_name                             |
|---------|----------------------------------------|
| abc123  | Moscow Format Diplomatic Meeting       |
| abc123  | Moscow Format                          |
| abc123  | Peace Negotiations                     |
| abc123  | Regional Stability                     |
```

## Schema Migration Support

### Old Schema (August Data)
```json
{
  "project-name": "Belt and Road Initiative",
  "projects": "Infrastructure Development"
}
```

Both values are extracted and inserted into `RawEvent`.

### New Schema (October Data)
```json
{
  "event-name": "Belt and Road Forum",
  "projects": "Belt and Road Initiative"
}
```

Both values are extracted and inserted into `RawEvent`.

### Consolidation Priority

When populating the `event_name` field in the Document model, the parser uses this priority:

1. **event-name** (if present and non-empty)
2. **project-name** (if event-name is empty, legacy fallback)
3. **projects** (if both above are empty)

However, **ALL non-empty values** from all three fields are flattened into `RawEvent`, regardless of priority.

## Querying Flattened Data

### Get All Events/Projects for a Document

```python
from backend.models import Document

with get_session() as session:
    doc = session.get(Document, "abc123")

    # Access flattened events via relationship
    events = [event.event_name for event in doc.raw_events]
    print(f"Document has {len(events)} events/projects: {events}")
```

### Get All Documents for an Event

```python
from backend.models import RawEvent

with get_session() as session:
    event_docs = session.query(RawEvent).filter(
        RawEvent.event_name == "Moscow Format"
    ).all()

    doc_ids = [event.doc_id for event in event_docs]
    print(f"Event mentioned in {len(doc_ids)} documents")
```

### Count Events Across All Documents

```python
from sqlalchemy import func

with get_session() as session:
    event_counts = session.query(
        RawEvent.event_name,
        func.count(RawEvent.doc_id).label('doc_count')
    ).group_by(RawEvent.event_name).order_by(
        func.count(RawEvent.doc_id).desc()
    ).limit(10).all()

    print("Top 10 events by document count:")
    for event_name, count in event_counts:
        print(f"  {event_name}: {count} documents")
```

## Processing Workflow

### 1. Parse Document
```python
doc = parse_doc(dsr_doc)
# doc.event_name = "Moscow Format Diplomatic Meeting"
# doc.project_name = "Moscow Format"
# doc.projects = "Peace Negotiations"
```

### 2. Insert Document
```python
session.add(doc)
session.commit()
```

### 3. Flatten Events (Automatic)
```python
flatten_events_to_raw_events(session, [doc])
session.commit()
# Creates 3 rows in raw_events table
```

This happens **automatically** in batches during `process_dsr()` and `process_dsr_s3()`.

## Benefits of Flattening

1. **Normalization**: Eliminates data duplication
2. **Flexible Queries**: Easy to find all documents for an event
3. **Aggregation**: Simple counts and statistics
4. **Schema Evolution**: Handles old and new schemas seamlessly
5. **Semicolon Handling**: Automatically splits multi-value fields

## Database Schema

```sql
-- Documents table (stores original fields)
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,
    event_name TEXT,
    project_name TEXT,
    projects TEXT,  -- Note: This is actually stored as _projects internally
    -- ... other fields
);

-- RawEvent table (flattened many-to-many)
CREATE TABLE raw_events (
    doc_id TEXT REFERENCES documents(doc_id),
    event_name TEXT,
    PRIMARY KEY (doc_id, event_name)
);
```

## Migration Notes

When you first run the updated parser on existing data:

1. **Documents** table is populated with all three fields
2. **RawEvents** table is populated with flattened values
3. Old documents without flattening can be backfilled:

```python
from backend.database import get_session
from backend.models import Document
from backend.scripts.dsr import flatten_events_to_raw_events

# Backfill existing documents
with get_session() as session:
    docs = session.query(Document).all()
    flatten_events_to_raw_events(session, docs)
    session.commit()
```

## Summary

- **Document fields** (`event_name`, `project_name`, `projects`) are kept for quick reference
- **RawEvent table** is the normalized source of truth for all event/project mentions
- **Automatic flattening** happens during document processing
- **Handles all schemas** (old project-name, new event-name, projects field)
- **No code changes needed** - flattening happens automatically during `process_dsr()`
