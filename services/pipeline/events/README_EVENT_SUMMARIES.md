# Event Summary Pipeline

This pipeline generates **EventSummary** records needed for publication generation.

## Overview

The event summary pipeline:
1. Clusters documents by event name, date range, and country
2. Generates AI-powered narratives (overview and outcome) for each event
3. Creates EventSourceLink relationships for traceability
4. Populates aggregated statistics (categories, recipients, sources)

## Quick Start

### Generate Event Summaries

```bash
# For a specific country
python services/pipeline/events/generate_event_summaries.py \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --country China

# For all countries in config
python services/pipeline/events/generate_event_summaries.py \
  --start 2024-10-01 \
  --end 2024-10-31
```

### Run Full Pipeline (Summaries + Publications)

```bash
# Complete pipeline for one country
python services/pipeline/events/run_full_pipeline.py \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --country China

# Complete pipeline for all countries
python services/pipeline/events/run_full_pipeline.py \
  --start 2024-10-01 \
  --end 2024-10-31
```

## Scripts

### 1. generate_event_summaries.py

Creates EventSummary records from documents in the database.

**Options:**
- `--start`: Start date (YYYY-MM-DD) [required]
- `--end`: End date (YYYY-MM-DD) [required]
- `--country`: Specific country to process [optional]
- `--period-type`: Period type (daily/weekly/monthly/yearly) [default: monthly]
- `--min-docs`: Minimum documents per event [default: 2]

**Example:**
```bash
python services/pipeline/events/generate_event_summaries.py \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --country China \
  --period-type monthly \
  --min-docs 3
```

**What it does:**
1. Queries documents with event names from RawEvent table
2. Clusters documents by event name
3. Filters events with minimum document threshold
4. For each event:
   - Calculates aggregated statistics
   - Generates AI narrative (overview and outcome)
   - Creates EventSummary record
   - Creates EventSourceLink records

### 2. run_full_pipeline.py

Orchestrates the complete workflow from event summaries to publications.

**Options:**
- `--start`: Start date (YYYY-MM-DD) [required]
- `--end`: End date (YYYY-MM-DD) [required]
- `--country`: Specific country [optional]
- `--categories`: Categories for publication [default: Economic,Diplomacy,Social,Military]
- `--recipients`: Recipient countries filter [optional]
- `--period-type`: Period type [default: monthly]
- `--min-docs`: Minimum documents per event [default: 2]
- `--model`: GPT model [default: gpt-4]
- `--max-sources`: Max sources per section [default: 10]
- `--skip-summary`: Skip EventSummary generation
- `--skip-publication`: Skip publication generation

**Example:**
```bash
python services/pipeline/events/run_full_pipeline.py \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --country China \
  --categories "Economic,Diplomacy" \
  --recipients "United States,Japan" \
  --model gpt-4 \
  --max-sources 15
```

**Workflow:**
1. Generate EventSummary records for specified countries
2. Generate publication documents (Reviewer + Summary versions)
3. Save outputs to services/publication/output/

## Database Models

### EventSummary

Core model for event aggregation:

```python
- id (UUID)
- period_type (PeriodType enum: daily/weekly/monthly/yearly)
- period_start, period_end (dates)
- event_name (string)
- initiating_country (string)
- first_observed_date, last_observed_date (dates)
- status (EventStatus enum)
- narrative_summary (JSONB: overview, outcome)
- count_by_category (JSONB)
- count_by_subcategory (JSONB)
- count_by_recipient (JSONB)
- count_by_source (JSONB)
```

### EventSourceLink

Links events to source documents:

```python
- id (UUID)
- event_summary_id (foreign key to EventSummary)
- doc_id (foreign key to Document)
- contribution_weight (optional float)
- linked_at (timestamp)
```

## Prerequisites

### Database Requirements

1. **Documents table populated** with processed documents
2. **RawEvent table populated** with event names extracted from documents
3. **Related tables populated**:
   - Category (document categories)
   - InitiatingCountry (document initiators)
   - RecipientCountry (document recipients)
   - Subcategory (optional)

### Check Prerequisites

```bash
# Check if documents exist
python -c "from shared.database.database import get_session; from shared.models.models import Document; session = next(get_session()); print(f'Documents: {session.query(Document).count()}')"

# Check if events exist
python -c "from shared.database.database import get_session; from shared.models.models import RawEvent; session = next(get_session()); print(f'Raw Events: {session.query(RawEvent).count()}')"
```

### Environment Variables

Required:
- `CLAUDE_KEY`: OpenAI API key (for GPT models)
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`: Database credentials

## Workflow Example

Complete workflow for generating a publication:

```bash
# Step 1: Ensure documents are ingested
python services/pipeline/ingestion/dsr.py --status

# Step 2: Generate event summaries
python services/pipeline/events/generate_event_summaries.py \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --country China

# Step 3: Generate publications
python services/publication/generate_publication.py \
  --country China \
  --start 2024-10-01 \
  --end 2024-10-31

# OR: Run steps 2-3 together
python services/pipeline/events/run_full_pipeline.py \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --country China
```

## Output

### EventSummary Records

Created in the `event_summaries` table with:
- AI-generated narratives
- Aggregated statistics
- Source document links

### Publication Documents

Created in `services/publication/output/`:
- `{country}_{start}_{end}_Reviewer.docx` - With inline citations
- `{country}_{start}_{end}_Summary.docx` - With end notes

## Troubleshooting

### No events found

**Problem:** "No events found with sufficient documents"

**Solution:**
- Check if RawEvent table has data for the date range
- Lower `--min-docs` threshold
- Verify documents exist with event_name populated

```bash
# Check event coverage
python -c "from shared.database.database import get_session; from shared.models.models import RawEvent, Document; from sqlalchemy import func; session = next(get_session()); result = session.query(func.min(Document.date), func.max(Document.date)).join(RawEvent, Document.doc_id == RawEvent.doc_id).first(); print(f'Event date range: {result}')"
```

### AI generation errors

**Problem:** "AI generation failed"

**Solution:**
- Check `CLAUDE_KEY` environment variable is set
- Verify OpenAI API is accessible
- Try using a different model: `--model gpt-3.5-turbo`
- Check token limits if documents are very large

### Duplicate EventSummary

**Problem:** "EventSummary already exists"

**Solution:**
- This is expected behavior - the pipeline skips existing summaries
- To regenerate, delete existing records:

```python
from shared.database.database import get_session
from shared.models.models import EventSummary
from datetime import date

with get_session() as session:
    # Delete summaries for specific period
    session.query(EventSummary).filter(
        EventSummary.initiating_country == "China",
        EventSummary.period_start == date(2024, 10, 1)
    ).delete()
    session.commit()
```

## Performance

### Timing Estimates

For a typical month of data (China, ~100 documents):
- EventSummary generation: 5-10 minutes
- Publication generation: 3-5 minutes
- **Total: 8-15 minutes per country**

### Optimization Tips

1. **Parallel Processing**: Run multiple countries simultaneously in separate terminals
2. **Batch Size**: Adjust `--min-docs` to control event granularity
3. **Model Selection**: Use `gpt-3.5-turbo` for faster (but less accurate) results
4. **Caching**: Re-use existing EventSummary records with `--skip-summary`

## Advanced Usage

### Custom Filtering

Generate summaries for specific categories:

```bash
# Generate event summaries (all categories)
python services/pipeline/events/generate_event_summaries.py \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --country China

# Generate publication (specific categories only)
python services/publication/generate_publication.py \
  --country China \
  --start 2024-10-01 \
  --end 2024-10-31 \
  --categories "Economic,Diplomacy"
```

### Multi-Country Batch Processing

```bash
# Process all countries
for country in China Russia India; do
  python services/pipeline/events/run_full_pipeline.py \
    --start 2024-10-01 \
    --end 2024-10-31 \
    --country $country
done
```

### Update Existing Summaries

To refresh narratives without recreating EventSummary:

```python
from shared.database.database import get_session
from shared.models.models import EventSummary
from services.publication.summary_generator import SummaryGenerator

with get_session() as session:
    generator = SummaryGenerator()

    # Get existing summaries
    summaries = session.query(EventSummary).filter(
        EventSummary.initiating_country == "China"
    ).all()

    # Regenerate narratives
    for summary in summaries:
        # Fetch documents and regenerate
        documents = [link.document for link in summary.source_links]
        narrative = generator.generate_event_narrative(
            summary.event_name,
            documents,
            list(summary.count_by_category.keys())[0]
        )
        summary.narrative_summary = narrative

    session.commit()
```

## See Also

- [Publication Service README](../../publication/README.md) - Publication generation details
- [CLAUDE.md](../../../CLAUDE.md) - Project architecture and commands
- [Database Models](../../../shared/models/models.py) - SQLAlchemy model definitions
