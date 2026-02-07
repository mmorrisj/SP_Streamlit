# Event Consolidation Pipeline

Hierarchical consolidation of daily event extractions into weekly, monthly, and overall summaries.

## Overview

This pipeline takes daily event extractions and consolidates them across multiple time periods:

```
Daily Events (publications/events/China/daily/)
    ↓ LLM consolidation
Weekly Events (publications/events/China/weekly/)
    ↓ LLM consolidation
Monthly Events (publications/events/China/monthly/)
    ↓ LLM consolidation
Overall Summary (publications/events/China/overall_{start}_{end}_events.json)
```

**Key Features**:
- **Multi-day event detection**: LLM identifies when events on different days are the same occurrence
- **Entity consolidation**: Merges persons, organizations, companies, locations
- **Materiality tracking**: Retains highest materiality score across instances
- **Source tracking**: All consolidations maintain full doc_id chains
- **ATOM search URLs**: Every consolidated event includes searchable links

## Directory Structure

```
publications/events/
├── China/
│   ├── daily/                    # Input: Daily extractions
│   │   ├── 2025-06-01_events.json
│   │   ├── 2025-06-02_events.json
│   │   └── ...
│   │
│   ├── weekly/                   # Output: Weekly consolidations
│   │   ├── 2025-W22_events.json
│   │   ├── 2025-W23_events.json
│   │   └── ...
│   │
│   ├── monthly/                  # Output: Monthly consolidations
│   │   ├── 2025-06_events.json
│   │   ├── 2025-07_events.json
│   │   └── ...
│   │
│   └── overall_2025-06-01_2026-01-01_events.json  # Final summary
```

## Quick Start

### Process All Levels (Daily → Weekly → Monthly → Overall)

```bash
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01
```

This runs the complete pipeline and produces:
- Weekly files for ~30 weeks
- Monthly files for 7 months
- Overall summary file

### Process Individual Levels

```bash
# Weekly only (from daily files)
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01 \
    --weekly-only

# Monthly only (from weekly files - must run weekly first!)
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01 \
    --monthly-only

# Overall only (from monthly files - must run monthly first!)
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01 \
    --overall-only
```

## Consolidation Logic

### Weekly Consolidation

**Input**: Daily event files for one ISO week

**Process**:
1. LLM analyzes all events from Monday-Sunday
2. Identifies multi-day events (e.g., ongoing construction, multi-day summits)
3. Merges duplicate events, keeping highest materiality score
4. Consolidates all entities (removes duplicates)
5. Tracks date range (first_mention → last_mention)

**Example**:
```json
// Day 1: "China signs hospital construction deal with Iraq"
// Day 3: "Iraqi Health Minister confirms 16-hospital project"
// Day 7: "Construction begins on China-Iraq hospitals"

// Weekly Output:
{
  "event_name": "China-Iraq Hospital Construction Project",
  "event_summary": "China announced, confirmed, and began construction of 16 hospitals across Baghdad and Iraqi provinces...",
  "materiality": {
    "score": 9.0,
    "justification": "Concrete infrastructure project with signed agreement and construction start"
  },
  "date_range": {
    "first_mention": "2025-06-01",
    "last_mention": "2025-06-07"
  },
  "source_doc_ids": ["doc1", "doc2", "doc3", "doc4", "doc5"],
  "daily_sources": ["2025-06-01", "2025-06-03", "2025-06-07"],
  "atom_search_url": "https://atom.opensource.gov/searches?ss=id%3A(%22doc1%22+OR+%22doc2%22+OR+%22doc3%22+OR+%22doc4%22+OR+%22doc5%22)&go=1"
}
```

### Monthly Consolidation

**Input**: Weekly event files for one month

**Process**:
1. LLM analyzes all weekly events
2. Identifies events spanning multiple weeks
3. Merges long-running events (e.g., multi-phase projects)
4. Updates summaries to reflect full month's developments

**Example**:
```json
// Week 1: "Belt and Road infrastructure planning in Egypt"
// Week 2: "Egypt-China sign rail project MoU"
// Week 3: "Chinese contractors arrive for rail assessment"
// Week 4: "Egypt-China rail project construction phase announced"

// Monthly Output:
{
  "event_name": "Egypt-China Belt and Road Rail Project",
  "event_summary": "China and Egypt progressed a major Belt and Road rail infrastructure project from planning through MoU signing to construction phase announcement, with Chinese contractors conducting site assessments...",
  "date_range": {
    "first_mention": "2025-06-02",
    "last_mention": "2025-06-28"
  }
}
```

### Overall Consolidation

**Input**: All monthly event files in date range

**Process**:
1. LLM analyzes all monthly events
2. Focuses on **highest materiality events** (≥7.0 preferred)
3. Consolidates major multi-month initiatives
4. Produces strategic summary (10-20 major events)

**Goal**: Final intelligence summary of most significant developments

## Output Format

All levels use consistent format:

```json
{
  "week/month/period": "2025-W22" | "2025-06" | "2025-06-01 to 2026-01-01",
  "country": "China",
  "events": [
    {
      "event_name": "Event Name",
      "event_summary": "Comprehensive summary...",
      "materiality": {
        "score": 8.5,
        "justification": "..."
      },
      "category": "Economic",
      "recipients": ["Egypt"],
      "date_range": {
        "first_mention": "2025-06-01",
        "last_mention": "2025-06-30"
      },
      "entities": {
        "persons": [...],
        "organizations": [...],
        "companies": [...],
        "locations": [...]
      },
      "source_doc_ids": ["doc1", "doc2", ...],
      "daily_sources": ["2025-06-01", "2025-06-05", ...],  // Weekly only
      "atom_search_url": "https://atom.opensource.gov/..."
    }
  ],
  "days_included": [...],      // Weekly only
  "weeks_included": [...],     // Monthly only
  "months_included": [...],    // Overall only
  "consolidated_at": "2026-01-08T..."
}
```

## Use Cases

### 1. Weekly Intelligence Briefings

Generate weekly summaries for stakeholder reports:

```bash
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-06-30 \
    --weekly-only
```

Review `publications/events/China/weekly/` for weekly digests.

### 2. Monthly Trend Analysis

Identify month-over-month patterns:

```python
import json
from pathlib import Path

monthly_dir = Path("publications/events/China/monthly")

for monthly_file in sorted(monthly_dir.glob("*.json")):
    data = json.load(open(monthly_file))

    # Analyze by category
    categories = {}
    for event in data['events']:
        cat = event['category']
        categories[cat] = categories.get(cat, 0) + 1

    print(f"{data['month']}: {categories}")
```

### 3. Strategic Overview

Generate executive summary of 6-month period:

```bash
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01
```

The overall summary focuses on highest-impact events for strategic decision-making.

### 4. Multi-day Event Tracking

Find events that evolved over multiple days/weeks:

```python
# Load weekly events
weekly_data = json.load(open("publications/events/China/weekly/2025-W26_events.json"))

# Find multi-day events
for event in weekly_data['events']:
    date_range = event.get('date_range', {})
    first = date_range.get('first_mention', '')
    last = date_range.get('last_mention', '')

    if first != last:
        print(f"Multi-day event: {event['event_name']}")
        print(f"  Span: {first} → {last}")
        print(f"  Days mentioned: {event.get('daily_sources', [])}")
        print(f"  ATOM: {event['atom_search_url']}\n")
```

## Performance

- **Weekly consolidation**: ~5-10 seconds per week (LLM call)
- **Monthly consolidation**: ~10-15 seconds per month
- **Overall consolidation**: ~15-20 seconds

**For 7 months of data (2025-06 to 2025-12)**:
- ~30 weeks → ~5 minutes
- 7 months → ~2 minutes
- 1 overall → ~20 seconds
- **Total**: ~8 minutes for full pipeline

## Best Practices

### 1. Run Daily Extraction First

Always ensure daily events are extracted before consolidation:

```bash
# Step 1: Extract daily events
python publications/scripts/extract_daily_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01

# Step 2: Consolidate hierarchically
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01
```

### 2. Incremental Updates

For new data, run only the needed levels:

```bash
# New week of daily data available
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-07-01 \
    --end-date 2025-07-07 \
    --weekly-only

# Then update monthly (if week completes a month)
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-07-01 \
    --end-date 2025-07-31 \
    --monthly-only
```

### 3. Quality Control

Spot-check high materiality events for accuracy:

```python
# Load overall summary
overall = json.load(open("publications/events/China/overall_2025-06-01_2026-01-01_events.json"))

# Check high materiality events
high_mat = [e for e in overall['events'] if e['materiality']['score'] >= 8.0]

for event in high_mat:
    print(f"{event['event_name']} (score: {event['materiality']['score']})")
    print(f"  {event['materiality']['justification']}")
    print(f"  Sources: {len(event['source_doc_ids'])} docs")
    print(f"  ATOM: {event['atom_search_url']}\n")
```

## Troubleshooting

### No weekly files generated

```
⊘ No daily event files found
```

**Solution**: Run `extract_daily_events.py` first to create daily extractions.

### Monthly consolidation fails

```
⊘ No weekly event files found. Run weekly consolidation first.
```

**Solution**: Run with `--weekly-only` first, then `--monthly-only`.

### LLM errors

```
✗ Error consolidating 2025-W26: ...
```

**Possible causes**:
- API rate limits
- Network issues
- Malformed daily event files

**Solution**: Check daily event JSON files are valid. Retry specific week/month.

### Date range issues

Ensure ISO week numbers align correctly. Weeks can span month boundaries:
- Week 2025-W22 might include days from May and June
- This is expected behavior (ISO 8601 week dates)

## Integration with Main Pipeline

```
1. Document Ingestion & AI Analysis
   ↓
2. Daily Publication Pipeline
   → publications/{Country}/daily/{Date}.json
   ↓
3. Daily Event Extraction
   → publications/events/{Country}/daily/{Date}_events.json
   ↓
4. Hierarchical Event Consolidation (THIS PIPELINE)
   → publications/events/{Country}/weekly/
   → publications/events/{Country}/monthly/
   → publications/events/{Country}/overall_*_events.json
   ↓
5. Intelligence Reports & Analysis
```

---

**Questions?** Check the script's inline documentation:
```bash
python publications/scripts/consolidate_events.py --help
```
