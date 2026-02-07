# Hasty Publication Event Pipeline

Complete event extraction and consolidation pipeline for rapid intelligence analysis.

## Overview

This pipeline extracts and consolidates key events from daily publication summaries, providing hierarchical intelligence products from daily to strategic overview levels.

**Pipeline Flow**:
```
Daily Publications → Daily Events → Weekly Events → Monthly Events → Overall Summary
```

All processing stays within the `publications/` directory, completely separate from the main document processing pipeline.

## Quick Start

### Complete Pipeline (Daily → Weekly → Monthly → Overall)

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

**Result**: Daily, weekly, monthly, and overall event summaries with full source tracking and ATOM search URLs.

## Directory Structure

```
publications/
├── scripts/                          # Processing scripts
│   ├── extract_daily_events.py       # Daily event extraction
│   ├── consolidate_events.py         # Hierarchical consolidation
│   └── generate_document_based_summaries.py  # Original publication generator
│
├── China/                            # Publication outputs (input for events)
│   ├── daily/
│   │   ├── 2025-06-01.json          # Daily publication summaries
│   │   └── ...
│   └── bilateral/
│       └── ...
│
├── events/                           # Event extraction outputs
│   └── China/
│       ├── daily/
│       │   ├── 2025-06-01_events.json         # Unique daily events
│       │   └── ...
│       ├── weekly/
│       │   ├── 2025-W22_events.json           # Consolidated weekly events
│       │   └── ...
│       ├── monthly/
│       │   ├── 2025-06_events.json            # Consolidated monthly events
│       │   └── ...
│       └── overall_2025-06-01_2026-01-01_events.json  # Strategic summary
│
├── README.md                         # This file
├── README_DAILY_EVENTS.md            # Daily extraction documentation
└── README_CONSOLIDATION.md           # Consolidation pipeline documentation
```

## Pipeline Components

### 1. Daily Event Extraction ([README_DAILY_EVENTS.md](README_DAILY_EVENTS.md))

**Input**: Daily publication JSON files
**Output**: Daily event extractions
**Script**: `publications/scripts/extract_daily_events.py`

Extracts unique events from each day with:
- Materiality scores (0-10 scale)
- Event summaries
- Entity extraction (persons, organizations, companies, locations)
- Source doc_ids with ATOM search URLs

**Example**:
```bash
python publications/scripts/extract_daily_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-06-30
```

### 2. Event Consolidation ([README_CONSOLIDATION.md](README_CONSOLIDATION.md))

**Input**: Daily event extractions
**Output**: Weekly, monthly, and overall summaries
**Script**: `publications/scripts/consolidate_events.py`

Consolidates events across time periods:
- **Weekly**: Groups daily events by ISO week, identifies multi-day events
- **Monthly**: Groups weekly events, identifies multi-week initiatives
- **Overall**: Creates strategic summary of highest-impact events

**Example**:
```bash
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01
```

### 3. Document-Based Summaries (Original Pipeline)

**Input**: Raw documents from database
**Output**: Daily publication JSON files
**Script**: `publications/scripts/generate_document_based_summaries.py`

Generates daily summaries with full citation chains. See script documentation for details.

## Key Features

### ✅ Hierarchical Intelligence
- **Daily**: Tactical-level event tracking
- **Weekly**: Operational-level trend identification
- **Monthly**: Strategic pattern recognition
- **Overall**: Executive-level decision support

### ✅ Multi-day Event Detection
LLM identifies when events on different days represent the same real-world occurrence and consolidates them automatically.

### ✅ Materiality Scoring
All events rated 0-10 on concrete vs symbolic nature:
- **9-10**: Highly material (signed agreements, construction, deployments)
- **7-8**: Substantial (MoUs with plans, trade deals with figures)
- **5-6**: Moderate (visits with deliverables, working groups)
- **3-4**: Limited (statements of intent, dialogue mechanisms)
- **0-2**: Symbolic (rhetoric, expressions of friendship)

### ✅ Entity Tracking
Comprehensive entity extraction and consolidation:
- **Persons**: Names, roles, countries
- **Organizations**: Types (govt agencies, international orgs, NGOs)
- **Companies**: Sectors (tech, manufacturing, energy)
- **Locations**: Cities, facilities, infrastructure

### ✅ Complete Source Traceability
- Full doc_id chains maintained through all consolidation levels
- ATOM search URLs for instant document access
- Citation tracking from overall summary → monthly → weekly → daily → documents

### ✅ Isolated from Main Pipeline
Everything stays in `publications/` directory, preventing interference with main document processing pipeline.

## Use Cases

### 1. Daily Intelligence Briefings
```bash
# Extract today's events
python publications/scripts/extract_daily_events.py \
    --country China \
    --start-date 2026-01-07 \
    --end-date 2026-01-07
```

### 2. Weekly Situation Reports
```bash
# Consolidate this week's events
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2026-01-01 \
    --end-date 2026-01-07 \
    --weekly-only
```

### 3. Monthly Trend Analysis
```bash
# Generate monthly summary
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-12-01 \
    --end-date 2025-12-31 \
    --monthly-only
```

### 4. Strategic Overview (6+ months)
```bash
# Create executive summary
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01
```

## Output Examples

### Daily Event
```json
{
  "event_name": "China-Iraq Hospital Construction Project",
  "event_summary": "China signed a contract to build 16 hospitals...",
  "materiality": {
    "score": 9.0,
    "justification": "Signed contract, specific infrastructure..."
  },
  "source_doc_ids": ["doc1", "doc2"],
  "atom_search_url": "https://atom.opensource.gov/searches?..."
}
```

### Weekly Event (Multi-day Consolidation)
```json
{
  "event_name": "China-Iraq Hospital Construction Project",
  "event_summary": "China announced, confirmed, and began construction...",
  "date_range": {
    "first_mention": "2025-06-25",
    "last_mention": "2025-06-30"
  },
  "daily_sources": ["2025-06-25", "2025-06-27", "2025-06-30"],
  "source_doc_ids": ["doc1", "doc2", "doc3", "doc4", "doc5"]
}
```

### Overall Event (Multi-month Consolidation)
```json
{
  "event_name": "Belt and Road Infrastructure Expansion in Iraq",
  "event_summary": "Six-month initiative spanning hospital construction, rail development...",
  "date_range": {
    "first_mention": "2025-06-01",
    "last_mention": "2025-11-30"
  },
  "source_doc_ids": [/* 50+ documents */]
}
```

## Performance

### Daily Extraction
- **Per file**: ~3-5 seconds
- **30 days**: ~2-4 minutes
- **180 days**: ~15-20 minutes

### Hierarchical Consolidation
- **Weekly** (30 weeks): ~5 minutes
- **Monthly** (7 months): ~2 minutes
- **Overall**: ~20 seconds
- **Total for 7 months**: ~8 minutes

## Configuration

All scripts use `shared/config/config.yaml` for:
- LLM model selection (`aws.default_model`)
- API endpoints (FastAPI proxy with Azure/OpenAI fallback)

Environment variables:
- `FASTAPI_URL` or `API_URL`: LLM proxy endpoint
- `ENV`: Set to `production` for Azure OpenAI, defaults to OpenAI API

## Troubleshooting

### Daily Extraction Issues
See [README_DAILY_EVENTS.md](README_DAILY_EVENTS.md#troubleshooting)

### Consolidation Issues
See [README_CONSOLIDATION.md](README_CONSOLIDATION.md#troubleshooting)

### General Tips
1. Always run daily extraction before consolidation
2. Verify input files exist before processing
3. Check LLM proxy is running (FastAPI service)
4. Monitor API rate limits for large date ranges

## Best Practices

### 1. Incremental Processing
Process new data incrementally rather than reprocessing everything:

```bash
# Daily: Add new day
python publications/scripts/extract_daily_events.py \
    --country China \
    --start-date 2026-01-08 \
    --end-date 2026-01-08

# Weekly: Update current week
python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2026-01-01 \
    --end-date 2026-01-08 \
    --weekly-only
```

### 2. Quality Control
Regularly review high-materiality events for accuracy:

```python
import json

events = json.load(open("publications/events/China/daily/2025-06-30_events.json"))
high_mat = [e for e in events['events'] if e['materiality']['score'] >= 8.0]

for event in high_mat:
    print(f"{event['event_name']}: {event['materiality']['score']}")
    print(f"  ATOM: {event['atom_search_url']}\n")
```

### 3. Archive Old Summaries
Move completed overall summaries to archive:

```bash
mkdir -p publications/archive/2025
mv publications/events/China/overall_2025-*.json publications/archive/2025/
```

## Integration with Main System

```
┌─────────────────────────────────────────────────────────────────┐
│                     Main Document Pipeline                       │
│  Documents → Ingestion → AI Analysis → Database                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│              Document-Based Publication Pipeline                 │
│  Database → Daily Summaries → publications/{Country}/daily/     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│              Event Extraction Pipeline (THIS)                    │
│  Daily Summaries → Daily Events → Weekly → Monthly → Overall    │
│  publications/events/{Country}/*_events.json                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
              Intelligence Reports & Analysis
```

## Documentation

- **[README.md](README.md)**: This overview (you are here)
- **[README_DAILY_EVENTS.md](README_DAILY_EVENTS.md)**: Daily extraction details
- **[README_CONSOLIDATION.md](README_CONSOLIDATION.md)**: Consolidation pipeline details

## Support

For questions or issues:
1. Check relevant README file
2. Review script inline documentation: `python script.py --help`
3. Verify input files and configuration
4. Check LLM proxy service status

---

**Ready to start?** Run the complete pipeline:

```bash
# Full pipeline for 7 months of data
python publications/scripts/extract_daily_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01

python publications/scripts/consolidate_events.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2026-01-01
```
