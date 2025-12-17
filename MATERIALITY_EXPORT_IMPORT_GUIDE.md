# Materiality Scores Export/Import Guide

## Overview

Use these commands to export materiality scores from System 1 and import them into System 2, avoiding re-scoring events that are already complete.

---

## Step 1: Export Scores from System 1

### Check Current Status First

```bash
# On System 1: View statistics before export
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_materiality_scores.py --stats-only
```

This shows:
- Total events by country
- How many are scored vs. unscored
- Average materiality scores

### Export All Scored Events

```bash
# On System 1: Export all events with materiality scores
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_materiality_scores.py \
    --output-dir ./materiality_exports \
    --scored-only
```

This exports:
- Only events with non-null, non-zero `material_score`
- Creates compressed parquet files in `./materiality_exports/`
- ~10,000 events per file (adjustable with `--batch-size`)

### Export Specific Countries

```bash
# On System 1: Export only China and Russia scores (already mostly complete)
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_materiality_scores.py \
    --output-dir ./materiality_exports \
    --countries China Russia \
    --scored-only
```

### Export to S3 (Optional)

```bash
# On System 1: Export and upload to S3
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_materiality_scores.py \
    --output-dir ./materiality_exports \
    --scored-only \
    --s3-bucket your-bucket \
    --s3-prefix materiality/backup/$(date +%Y%m%d)/
```

---

## Step 2: Transfer Files to System 2

### Option A: Local File Transfer

Copy the exported files to System 2:

```bash
# Example: Using scp (adjust paths/hosts as needed)
scp -r ./materiality_exports/ user@system2:/path/to/SP_Streamlit/materiality_exports/
```

### Option B: Via S3

If you exported to S3, the files are already available for System 2 to download.

---

## Step 3: Import Scores into System 2

### Dry Run First (Recommended)

```bash
# On System 2: Test import without making changes
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_exports \
    --dry-run
```

This shows:
- How many events would be imported
- How many would be updated vs. created vs. skipped
- No changes are made to the database

### Import from Local Files

```bash
# On System 2: Import materiality scores
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_exports
```

**Default behavior**:
- Updates existing events that don't have scores
- Skips events that already have scores
- Creates new events if they don't exist (use `--update-only` to prevent this)

### Import from S3

```bash
# On System 2: Download from S3 and import
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
    --s3-bucket your-bucket \
    --s3-prefix materiality/backup/20241216/
```

### Import Options

```bash
# Update only existing events (don't create new ones)
python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_exports \
    --update-only

# Overwrite existing scores (replace all scores, even if already set)
python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_exports \
    --overwrite
```

---

## Step 4: Verify Import on System 2

Check that scores were imported correctly:

```bash
# On System 2: Check materiality score statistics
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python -c "
from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) as total,
            COUNT(material_score) FILTER (WHERE material_score > 0) as scored,
            ROUND(AVG(material_score)::numeric, 2) as avg_score
        FROM canonical_events
        GROUP BY initiating_country
        ORDER BY total DESC
    '''))

    print(f\"{'Country':<20} {'Total':<10} {'Scored':<10} {'Avg Score':<10}\")
    print('-' * 60)
    for row in result:
        avg = float(row[3]) if row[3] else 0.0
        print(f\"{row[0]:<20} {row[1]:<10,} {row[2]:<10,} {avg:<10.2f}\")
"
```

---

## Recommended Workflow

### Scenario: Transfer China & Russia scores to System 2, score remaining on System 2

**On System 1:**
```bash
# Export China and Russia (already 69% and 2% complete)
python services/pipeline/events/export_materiality_scores.py \
    --countries China Russia \
    --scored-only \
    --output-dir ./materiality_china_russia
```

**Transfer to System 2** (copy files or use S3)

**On System 2:**
```bash
# 1. Dry run to verify
python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_china_russia \
    --dry-run

# 2. Import scores
python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_china_russia

# 3. Verify import
python services/pipeline/events/export_materiality_scores.py --stats-only

# 4. Now score the remaining unscored events using Azure OpenAI
python services/pipeline/events/score_canonical_event_materiality.py \
    --country Iran --source azure

python services/pipeline/events/score_canonical_event_materiality.py \
    --country Turkey --source azure

python services/pipeline/events/score_canonical_event_materiality.py \
    --country "United States" --source azure
```

---

## File Format

The exported parquet files contain these columns:

- `id` - Canonical event ID
- `event_name` - Name of the event
- `initiating_country` - Initiating country
- `event_date` - Date of the event
- `material_score` - Materiality score (1.0-10.0)
- `material_justification` - LLM justification for the score
- `primary_recipients` - JSON array of recipient countries
- `category_breakdown` - JSON object with category counts
- `created_at` - Timestamp when event was created
- `updated_at` - Timestamp when event was last updated

---

## Performance Notes

- **Export**: ~50,000-100,000 events/minute
- **Import**: ~10,000-20,000 events/minute
- **File size**: ~1-5 MB per 10,000 events (with zstd compression)

For a dataset with ~100,000 scored events:
- Export: ~2-3 minutes
- Transfer: Depends on network
- Import: ~5-10 minutes

Total time: **~10-15 minutes** vs. **~40+ hours** to re-score everything.

---

## Troubleshooting

### "No parquet files found"
- Check the `--input-dir` path
- Ensure files were exported successfully
- Look for `*.parquet` files in the directory

### "Event ID conflicts"
- Use `--update-only` to only update existing events
- Use `--overwrite` to replace existing scores

### "S3 download failed"
- Check AWS credentials are set (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
- Verify bucket name and prefix are correct
- Ensure boto3 is installed: `pip install boto3`

### Import seems slow
- Normal for large datasets (10k-20k events/minute)
- Runs in batches of 1,000 events
- Check database connection pool status if very slow
