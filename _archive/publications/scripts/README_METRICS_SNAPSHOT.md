# Metrics Snapshot Generator

Generate metrics-based snapshots from the database to feed as context into summary publications.

## Overview

This script queries the database and generates comprehensive metrics for a given country and date range:

- **Overall Statistics**: Total articles, recipient countries, categories, average materiality
- **Top Events by Article Count**: Most-mentioned events (Top 20)
- **Top Events by Materiality**: Highest-impact events (Top 20)
- **Top Bilateral Discussions**: Most active country relationships (Top 20)
- **Top Categories by Article Count**: Most common activity types (Top 20)
- **Top Categories by Materiality**: Highest-impact activity types (Top 20)

## Features

- ✅ Respects country filters from `config.yaml` (only valid recipients included)
- ✅ Respects category filters from `config.yaml` (only valid categories included)
- ✅ Pulls data from `documents`, `canonical_events`, and `daily_event_mentions` tables
- ✅ Outputs structured JSON for easy integration into publication workflows

## Usage

### Basic Usage

```bash
python publications/scripts/generate_metrics_snapshot.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31
```

### Custom Output Directory

```bash
python publications/scripts/generate_metrics_snapshot.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir publications/metrics/2025
```

### Custom Config File

```bash
python publications/scripts/generate_metrics_snapshot.py \
    --country Russia \
    --start-date 2025-01-01 \
    --end-date 2025-12-31 \
    --config /path/to/custom/config.yaml
```

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--country` | Yes | - | Initiating country (e.g., China, Russia, Iran) |
| `--start-date` | Yes | - | Start date in YYYY-MM-DD format |
| `--end-date` | Yes | - | End date in YYYY-MM-DD format |
| `--output-dir` | No | `publications/metrics` | Output directory for JSON files |
| `--config` | No | `shared/config/config.yaml` | Path to config file |

## Output Format

The script generates a JSON file named:
```
{country}_metrics_{start_date}_{end_date}.json
```

Example: `China_metrics_2025-06-01_2025-12-31.json`

### JSON Structure

```json
{
  "metadata": {
    "country": "China",
    "start_date": "2025-06-01",
    "end_date": "2025-12-31",
    "generated_at": "2026-01-26T10:30:00",
    "config_filters": {
      "valid_recipients_count": 19,
      "valid_categories_count": 4
    }
  },
  "overall_statistics": {
    "total_articles": 1523,
    "total_recipient_countries": 18,
    "total_categories": 4,
    "avg_materiality": 3.45
  },
  "top_events_by_article_count": [
    {
      "event_name": "Belt and Road Forum 2025",
      "description": "Annual BRI conference in Beijing...",
      "start_date": "2025-10-15",
      "end_date": "2025-10-17",
      "article_count": 47
    }
  ],
  "top_events_by_materiality": [
    {
      "event_name": "China-Egypt Nuclear Deal",
      "description": "Agreement for nuclear power plant...",
      "start_date": "2025-08-22",
      "end_date": "2025-08-22",
      "avg_materiality": 4.8,
      "article_count": 23
    }
  ],
  "top_bilateral_discussions_by_article_count": [
    {
      "recipient_country": "Egypt",
      "article_count": 234
    },
    {
      "recipient_country": "Saudi Arabia",
      "article_count": 189
    }
  ],
  "top_categories_by_article_count": [
    {
      "category": "Economic",
      "article_count": 678
    },
    {
      "category": "Diplomacy",
      "article_count": 512
    }
  ],
  "top_categories_by_materiality": [
    {
      "category": "Military",
      "avg_materiality": 4.2,
      "article_count": 89
    },
    {
      "category": "Economic",
      "avg_materiality": 3.8,
      "article_count": 678
    }
  ]
}
```

## Database Requirements

The script requires access to the following database tables:
- `documents` - Main document table
- `canonical_events` - Event definitions
- `daily_event_mentions` - Links events to documents
- `initiating_countries` - Country relationships
- `categories` - Document categories

Make sure your database is running before executing the script.

## Integration with Summary Publications

This metrics snapshot is designed to be fed into overall summary publications as context:

1. **Generate metrics snapshot**:
   ```bash
   python publications/scripts/generate_metrics_snapshot.py \
       --country China \
       --start-date 2025-06-01 \
       --end-date 2025-12-31
   ```

2. **Load JSON in summary generation script**:
   ```python
   import json

   with open('publications/metrics/China_metrics_2025-06-01_2025-12-31.json') as f:
       metrics = json.load(f)

   # Use metrics as context for LLM prompts
   context = f"""
   Overall Activity ({metrics['metadata']['start_date']} to {metrics['metadata']['end_date']}):
   - Total Articles: {metrics['overall_statistics']['total_articles']}
   - Top Event: {metrics['top_events_by_article_count'][0]['event_name']}
   - Top Bilateral: {metrics['top_bilateral_discussions_by_article_count'][0]['recipient_country']}
   - Most Active Category: {metrics['top_categories_by_article_count'][0]['category']}
   """
   ```

## Examples

### Generate China metrics for H2 2025
```bash
python publications/scripts/generate_metrics_snapshot.py \
    --country China \
    --start-date 2025-07-01 \
    --end-date 2025-12-31
```

### Generate Iran metrics for Q3 2025
```bash
python publications/scripts/generate_metrics_snapshot.py \
    --country Iran \
    --start-date 2025-07-01 \
    --end-date 2025-09-30
```

### Generate Russia metrics for full year 2025
```bash
python publications/scripts/generate_metrics_snapshot.py \
    --country Russia \
    --start-date 2025-01-01 \
    --end-date 2025-12-31
```

## Troubleshooting

### Database Connection Failed
```
ConnectionError: Failed to connect to database after 3 attempts
```
**Solution**: Make sure your PostgreSQL database is running. See [CLAUDE.md](../../CLAUDE.md) for database startup instructions.

### No Valid Recipients/Categories
```
Valid recipients: 0 countries
Valid categories: 0 categories
```
**Solution**: Check that `shared/config/config.yaml` contains `recipients` and `categories` lists.

### Empty Results
If metrics return empty arrays:
- Verify the date range has data in the database
- Check that the country name matches exactly (case-sensitive)
- Ensure events exist in `canonical_events` table for that country/date range

## Performance Notes

- Query execution time: ~5-10 seconds for 6-month date ranges
- Memory usage: ~50-100 MB
- Output file size: ~50-200 KB depending on activity level

## Related Scripts

- [extract_daily_events.py](extract_daily_events.py) - Extracts daily events from publications
- [consolidate_events.py](consolidate_events.py) - Creates weekly/monthly/overall event summaries
- [generate_summary_publication.py](generate_summary_publication.py) - (Future) Uses metrics as context for summary generation
