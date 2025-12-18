# Import/Export Commands Quick Reference

## System 1 → System 2 Migration Commands

### Step 1: Export on System 1 (✅ COMPLETE)

```bash
# Export materiality scores (22,235 scored events)
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_materiality_scores.py \
    --output-dir ./materiality_exports \
    --scored-only

# Export event tables (153,873 clusters + 140,037 mentions + 12,227 summaries)
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_event_tables.py \
    --output-dir ./event_exports
```

**Result:**
- `./materiality_exports` - 2.8 MB (3 files)
- `./event_exports` - 35 MB (34 files)

---

### Step 2: Transfer Files to System 2

Copy both directories to System 2:
```bash
# Example using scp (adjust for your setup)
scp -r ./materiality_exports user@system2:/path/to/SP_Streamlit/
scp -r ./event_exports user@system2:/path/to/SP_Streamlit/

# Or use USB drive, network share, cloud storage, etc.
```

---

### Step 3: Import on System 2

#### A. Test Azure Connection First

```bash
# On System 2
jupyter notebook test_azure_connection.ipynb
# Set CREDENTIAL_MODE = "secrets" and run all cells
```

#### B. Import Materiality Scores (Dry Run)

```bash
# On System 2 - Test import first
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_exports \
    --dry-run
```

Expected output:
```
Total events in files: 22,235
Updated events: 22,235
Created events: 0
Skipped events: 0
```

#### C. Import Materiality Scores (Actual)

```bash
# On System 2 - Actually import
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
    --input-dir ./materiality_exports
```

#### D. Import Event Tables (Dry Run)

```bash
# On System 2 - Test import first
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_event_tables.py \
    --input-dir ./event_exports \
    --dry-run
```

Expected output:
```
EVENT_CLUSTERS: 153,873 clusters
DAILY_EVENT_MENTIONS: 140,037 mentions
EVENT_SUMMARIES: 12,227 summaries
```

#### E. Import Event Tables (Actual)

```bash
# On System 2 - Actually import
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_event_tables.py \
    --input-dir ./event_exports
```

#### F. Verify Imports

```bash
# On System 2 - Check materiality scores
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/export_materiality_scores.py --stats-only

# On System 2 - Check event tables
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/export_event_tables.py --stats-only
```

Expected counts should match System 1.

---

### Step 4: Start Processing on System 2

#### Test Materiality Scoring with Azure

```bash
# On System 2 - Test with a small batch first
PYTHONPATH=/path/to/SP_Streamlit python -c "
from shared.utils.utils import gai

# Test Azure connection
response = gai(
    sys_prompt='You are a helpful assistant.',
    user_prompt='Say hello from Azure OpenAI',
    source='azure'
)
print(response)
"
```

#### Start Materiality Scoring (Production)

```bash
# On System 2 - Iran (highest priority - 36,526 unscored)
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/score_canonical_event_materiality.py \
    --country Iran \
    --source azure

# On System 2 - United States (22,120 unscored)
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/score_canonical_event_materiality.py \
    --country "United States" \
    --source azure

# On System 2 - Turkey (18,387 unscored)
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/score_canonical_event_materiality.py \
    --country Turkey \
    --source azure
```

**Note:** System 1 should continue processing China and Russia via the OpenAI proxy.

---

## Optional: S3-Based Transfer

### Export to S3 (System 1)

```bash
# Export materiality scores to S3
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_materiality_scores.py \
    --output-dir ./materiality_exports \
    --scored-only \
    --s3-bucket your-bucket \
    --s3-prefix materiality/backup/$(date +%Y%m%d)/

# Export event tables to S3
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/events/export_event_tables.py \
    --output-dir ./event_exports \
    --s3-bucket your-bucket \
    --s3-prefix events/backup/$(date +%Y%m%d)/
```

### Import from S3 (System 2)

```bash
# Import materiality scores from S3
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
    --s3-bucket your-bucket \
    --s3-prefix materiality/backup/20241217/

# Import event tables from S3
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_event_tables.py \
    --s3-bucket your-bucket \
    --s3-prefix events/backup/20241217/
```

---

## Import Options Reference

### Materiality Scores Import Options

```bash
# Update only existing events (don't create new)
python import_materiality_scores.py --input-dir ./materiality_exports --update-only

# Overwrite existing scores
python import_materiality_scores.py --input-dir ./materiality_exports --overwrite

# Dry run (test without changes)
python import_materiality_scores.py --input-dir ./materiality_exports --dry-run
```

### Event Tables Import Options

```bash
# Import only specific tables
python import_event_tables.py --input-dir ./event_exports --tables event_clusters

# Import multiple specific tables
python import_event_tables.py --input-dir ./event_exports --tables event_clusters daily_event_mentions

# Clear existing data before import (WARNING: destructive)
python import_event_tables.py --input-dir ./event_exports --clear-existing

# Dry run
python import_event_tables.py --input-dir ./event_exports --dry-run
```

---

## Troubleshooting

### "No parquet files found"
- Check the input directory path
- Ensure files were exported successfully
- Look for `*.parquet` files

### "Database connection failed"
- Verify PostgreSQL is running
- Check DATABASE_URL in .env
- Test connection: `python -c "from shared.database.database import health_check; print(health_check())"`

### "Azure OpenAI authentication failed"
- Verify AWS credentials are set (for boto3)
- Check config.yaml has `aws.secret_name` and `aws.region_name`
- Verify secret exists in AWS Secrets Manager
- Test: `jupyter notebook test_azure_connection.ipynb`

### Import seems stuck
- Normal for large datasets
- Check database logs for errors
- Monitor: `htop` or Task Manager
- Each batch of 500 rows takes ~5-10 seconds

### "ON CONFLICT" errors
- Expected behavior - script uses `ON CONFLICT DO NOTHING`
- Safely skips duplicate IDs
- Re-running import is safe (idempotent)

---

## Performance Notes

**Export Speed:**
- Materiality scores: ~50,000-100,000 events/minute
- Event tables: ~50,000 rows/minute

**Import Speed:**
- Materiality scores: ~10,000-20,000 events/minute
- Event tables: ~5,000-10,000 rows/minute (slower due to JSONB parsing)

**File Sizes:**
- Materiality: ~1-2 MB per 10,000 events (zstd compressed)
- Event clusters: ~1 MB per 10,000 clusters
- Event mentions: ~750 KB per 10,000 mentions
- Event summaries: ~500 KB per 10,000 summaries

**Estimated Times:**
- Export: ~5 minutes total
- Transfer: Depends on network
- Import: ~15-20 minutes total
- **Total migration: ~30 minutes** (vs. weeks to regenerate)
