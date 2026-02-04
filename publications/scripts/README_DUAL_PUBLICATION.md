# Dual Publication Pipeline

## Overview

Generates two publication formats from consolidated canonical events:

1. **Summary Version** - Executive briefing with flowing narrative prose
2. **Review Version** - Same narrative, but with source citations for analyst validation

## Key Difference: Summary vs. Review

| Aspect | Summary Version | Review Version |
|--------|----------------|----------------|
| **Narrative** | Strategic overview prose | **Same narrative** as Summary |
| **Sources** | None (clean read) | Full source citations with doc_ids |
| **Purpose** | Executive consumption | Analyst validation |
| **Top Events** | Not shown | Listed with metrics |
| **Document Links** | None | Hyperlinks to source documents |

**Example**:

**Summary Version**:
```json
{
  "overall_summary": "China's soft power strategy in the region focused on cultural diplomacy...",
  "category_summaries": {
    "Diplomacy": "Key diplomatic initiatives included high-level bilateral meetings..."
  }
}
```

**Review Version**:
```json
{
  "overall_summary": "China's soft power strategy in the region focused on cultural diplomacy...",
  "category_summaries": {
    "Diplomacy": "Key diplomatic initiatives included high-level bilateral meetings..."
  },
  "categories": [
    {
      "category": "Diplomacy",
      "narrative": "Key diplomatic initiatives included high-level bilateral meetings...",
      "top_events": [
        {
          "event_name": "China-Egypt Strategic Partnership Summit",
          "article_count": 127,
          "materiality_score": 8.5
        }
      ],
      "sources": [
        {
          "citation_number": 1,
          "doc_id": "abc123",
          "headline": "Xi Jinping meets with Egyptian President...",
          "source_url": "https://...",
          "event_name": "China-Egypt Strategic Partnership Summit"
        }
      ]
    }
  ]
}
```

Analysts can verify claims in the narrative by checking the source documents listed below.

## Prerequisites

You must run the event consolidation pipeline first:

```bash
# Step 1: Consolidate events
python services/pipeline/events/consolidate_all_events.py --country China --similarity-threshold 0.82

# Step 2: LLM deconfliction (validates consolidation)
python services/pipeline/events/llm_deconflict_canonical_events_parallel.py --country China --batch-size 5

# Step 3: Merge daily mentions (creates multi-day events)
python services/pipeline/events/merge_canonical_events.py --country China
```

This creates the `canonical_events` table with `master_event_id` hierarchy needed for publication generation.

## Usage

### Generate Both Versions (Recommended)

```bash
python publications/scripts/generate_dual_publication.py --country China --start-date 2025-06-01 --end-date 2025-12-31 --output-dir publications --top-events 20
```

**Output**:
- `publications/China/summary_2025-06-01_2025-12-31.json` - Executive version
- `publications/China/review_2025-06-01_2025-12-31.json` - Analyst version with sources

### Generate Only Summary Version

```bash
python publications/scripts/generate_dual_publication.py --country China --start-date 2025-06-01 --end-date 2025-12-31 --summary-only
```

### Generate Only Review Version

```bash
python publications/scripts/generate_dual_publication.py --country China --start-date 2025-06-01 --end-date 2025-12-31 --review-only
```

### Adjust Number of Top Events

```bash
python publications/scripts/generate_dual_publication.py --country China --start-date 2025-06-01 --end-date 2025-12-31 --top-events 30
```

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--country` | Yes | - | Country to analyze (e.g., China, Iran) |
| `--start-date` | Yes | - | Start date (YYYY-MM-DD) |
| `--end-date` | Yes | - | End date (YYYY-MM-DD) |
| `--output-dir` | No | `publications` | Output directory |
| `--top-events` | No | `20` | Top N events per category to include |
| `--summary-only` | No | `False` | Only generate summary version |
| `--review-only` | No | `False` | Only generate review version |

## How It Works

### Step 1: Load Top Events by Category

Queries `canonical_events` table for master events (consolidated multi-day events):

```sql
SELECT canonical_name, total_articles, materiality_score, ...
FROM canonical_events
WHERE master_event_id IS NULL  -- Only masters
ORDER BY total_articles DESC, materiality_score DESC
LIMIT 20
```

### Step 2: Get Source Documents

For each event, retrieves all linked documents via `daily_event_mentions`:

```sql
SELECT doc_id FROM daily_event_mentions
WHERE canonical_event_id = <event_id>
```

Then fetches document details (headline, source, URL, date) for citations.

### Step 3: Generate Category Narratives

For each category (Diplomacy, Economic, Social, Military):

1. Pass top 10 events to LLM
2. LLM generates strategic narrative (4-6 sentences)
3. Focuses on patterns, trends, and geopolitical implications

**LLM Prompt**:
```
Category: Diplomacy
Top Events:
- China-Egypt Strategic Partnership (127 articles, materiality: 8.5/10)
- Iran-China Nuclear Cooperation Talks (94 articles, materiality: 7.2/10)
...

Generate a strategic narrative paragraph for this category.
```

### Step 4: Generate Overall Synthesis

Combines all category narratives into cohesive executive summary:

1. Opening: Strategic context and themes
2. Body: Major developments by category
3. Closing: Implications and outlook

### Step 5: Create Review Version

Takes the **same narrative** from Summary version and adds:

- Top events list with metrics (article count, materiality, date range)
- Source citations for each category
- Links to original documents for validation

## Output Structure

### Summary Version JSON

```json
{
  "version": "summary",
  "country": "China",
  "period_start": "2025-06-01",
  "period_end": "2025-12-31",
  "generated_at": "2026-02-02T...",
  "overall_summary": "Strategic synthesis across all categories...",
  "category_summaries": {
    "Diplomacy": "Narrative paragraph about diplomatic activities...",
    "Economic": "Narrative paragraph about economic initiatives...",
    "Social": "Narrative paragraph about cultural/social programs...",
    "Military": "Narrative paragraph about security cooperation..."
  }
}
```

### Review Version JSON

```json
{
  "version": "review",
  "country": "China",
  "period_start": "2025-06-01",
  "period_end": "2025-12-31",
  "generated_at": "2026-02-02T...",
  "overall_summary": "Strategic synthesis across all categories...",
  "categories": [
    {
      "category": "Diplomacy",
      "narrative": "Same narrative as summary version...",
      "top_events": [
        {
          "event_name": "China-Egypt Strategic Partnership Summit",
          "date_range": "2025-06-15 to 2025-06-28",
          "article_count": 127,
          "materiality_score": 8.5,
          "mention_days": 14
        }
      ],
      "sources": [
        {
          "citation_number": 1,
          "doc_id": "abc123",
          "headline": "Xi Jinping meets with Egyptian President...",
          "source_name": "Xinhua",
          "source_url": "https://...",
          "published_date": "2025-06-15",
          "categories": ["Diplomacy"],
          "recipients": ["Egypt"],
          "event_name": "China-Egypt Strategic Partnership Summit",
          "event_metrics": {
            "article_count": 127,
            "materiality_score": 8.5
          }
        }
      ]
    }
  ],
  "all_sources": [
    /* Complete list of all sources across categories */
  ]
}
```

## Converting to Word Documents

After generating JSON files, convert to Word:

```bash
# Summary version (clean executive brief)
python publications/scripts/json_to_word_summary.py --input publications/China/summary_2025-06-01_2025-12-31.json --output publications/China/Summary_Jun_Dec_2025.docx

# Review version (with sources and citations)
python publications/scripts/json_to_word_review.py --input publications/China/review_2025-06-01_2025-12-31.json --output publications/China/Review_Jun_Dec_2025.docx
```

*(Note: These converters need to be created if you want Word output)*

## Complete Pipeline

```bash
# 1. Consolidate events (if not already done)
python services/pipeline/events/consolidate_all_events.py --country China --similarity-threshold 0.82
python services/pipeline/events/llm_deconflict_canonical_events_parallel.py --country China --batch-size 5
python services/pipeline/events/merge_canonical_events.py --country China

# 2. Generate publications
python publications/scripts/generate_dual_publication.py --country China --start-date 2025-06-01 --end-date 2025-12-31 --top-events 20

# 3. Review outputs
cat publications/China/summary_2025-06-01_2025-12-31.json
cat publications/China/review_2025-06-01_2025-12-31.json

# 4. (Optional) Convert to Word
python publications/scripts/json_to_word_summary.py --input publications/China/summary_2025-06-01_2025-12-31.json --output publications/China/Executive_Brief.docx
python publications/scripts/json_to_word_review.py --input publications/China/review_2025-06-01_2025-12-31.json --output publications/China/Analyst_Review.docx
```

## Workflow: Summary vs. Review

**Use Summary Version**:
- Executive briefings
- Strategic overviews
- Clean narrative read
- High-level decision making

**Use Review Version**:
- Analyst validation
- Fact-checking claims
- Source verification
- Quality assurance
- Identifying gaps in coverage

## Troubleshooting

### Error: "No events found for category X"

**Cause**: Event consolidation didn't run or no events in that category

**Fix**:
```bash
# Check canonical_events table
python -c "from shared.database.database import get_session; from sqlalchemy import text;
with get_session() as s:
    result = s.execute(text('SELECT COUNT(*) FROM canonical_events WHERE initiating_country = :c AND master_event_id IS NULL'), {'c': 'China'}).scalar();
    print(f'Master events: {result}')"

# If 0, run consolidation pipeline first
```

### Error: "No source documents found"

**Cause**: `daily_event_mentions` table not populated

**Fix**:
```bash
# Run merge_canonical_events to link events to documents
python services/pipeline/events/merge_canonical_events.py --country China
```

### Review version has no sources

**Cause**: doc_ids array is empty in canonical_events

**Fix**: Check `daily_event_mentions` table has entries linking to doc_ids

```sql
SELECT COUNT(*) FROM daily_event_mentions WHERE canonical_event_id IN (
  SELECT id FROM canonical_events WHERE initiating_country = 'China' AND master_event_id IS NULL
);
```

## Next Steps

After generating publications:

1. **Review Summary Version**: Read the executive brief for coherence and strategic insight
2. **Validate with Review Version**: Check sources to verify key claims
3. **Adjust top_events**: If narrative is too broad/narrow, change `--top-events` parameter
4. **Refine Event Consolidation**: If seeing duplicate events, adjust consolidation threshold
5. **Generate Word Documents**: Convert JSON to formatted Word documents for distribution
