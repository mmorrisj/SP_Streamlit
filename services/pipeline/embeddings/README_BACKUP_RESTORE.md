# Embedding Backup & Restore Guide

This guide explains how to backup and restore embeddings and event summaries for fast database recovery.

## Overview

Regenerating 480,000+ document embeddings and 10,000+ event summary embeddings takes many hours. These scripts allow you to:

1. **Export** all embeddings and event summaries to compressed parquet files (~500-600 MB total)
2. **Restore** them in minutes instead of hours

## Quick Start

### Full Backup (Recommended)

Export everything to local directory:

```bash
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./embedding_backups/$(date +%Y%m%d) \
    --include-event-summaries
```

### Full Restore

Restore from local backup:

```bash
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./embedding_backups/20241106
```

## Export Options

### 1. Export All Embeddings + Event Summaries

```bash
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./my_backup \
    --include-event-summaries
```

**Exports:**
- `chunk_embeddings.parquet` - Document chunk embeddings (470,890 embeddings, ~850 MB)
- `daily_event_embeddings.parquet` - Daily event embeddings (8,317 embeddings, ~18 MB)
- `weekly_event_embeddings.parquet` - Weekly event embeddings (1,014 embeddings, ~2 MB)
- `monthly_event_embeddings.parquet` - Monthly event embeddings (776 embeddings, ~1.5 MB)
- `event_summaries.parquet` - Event summaries table (10,107 rows, ~6 MB)
- `export_manifest.json` - Metadata about the export

**Total size:** ~875 MB (compressed with zstd)

### 2. Export Specific Collections

Export only document embeddings:

```bash
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./docs_only \
    --collections chunk_embeddings
```

Export only event embeddings:

```bash
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./events_only \
    --collections daily_event_embeddings weekly_event_embeddings monthly_event_embeddings \
    --include-event-summaries
```

### 3. Export to S3

Backup directly to S3:

```bash
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./temp_export \
    --include-event-summaries \
    --s3-bucket your-bucket-name \
    --s3-prefix embeddings/backup/20241106/
```

This will:
1. Export to local `./temp_export` directory
2. Upload all files to S3
3. Keep local files for verification

### 4. Large Collection Batching

For very large collections, files are automatically split into batches:

```bash
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./batch_export \
    --batch-size 50000  # 50K embeddings per file
```

This creates multiple files like:
- `chunk_embeddings_part0000.parquet`
- `chunk_embeddings_part0001.parquet`
- etc.

## Import Options

### 1. Full Restore from Local Backup

```bash
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./embedding_backups/20241106
```

This imports:
- All embedding collections found in the directory
- Event summaries (if `event_summaries.parquet` exists)
- Handles both single files and multi-part files automatically

### 2. Restore from S3

```bash
python services/pipeline/embeddings/import_embeddings.py \
    --s3-bucket your-bucket-name \
    --s3-prefix embeddings/backup/20241106/
```

This will:
1. Download all parquet files from S3 to temp directory
2. Import them to database
3. Clean up temp files

### 3. Dry Run (Test Without Importing)

Test the import without modifying the database:

```bash
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./embedding_backups/20241106 \
    --dry-run
```

This shows what would be imported without actually inserting data.

### 4. Clear Existing Data Before Import

**⚠️ DESTRUCTIVE - Use with caution!**

```bash
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./embedding_backups/20241106 \
    --clear-existing
```

This will:
1. DELETE all existing embeddings in each collection
2. DELETE all existing event summaries
3. Import the backup data

Use this when rebuilding a database from scratch.

### 5. Skip Event Summaries

Import only embeddings, skip event_summaries table:

```bash
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./embedding_backups/20241106 \
    --skip-event-summaries
```

## Database Rebuild Workflow

Complete workflow to rebuild database from scratch:

### Step 1: Export Current Data (Before Rebuild)

```bash
# Create timestamped backup
BACKUP_DIR="./embedding_backups/$(date +%Y%m%d_%H%M%S)"

python services/pipeline/embeddings/export_embeddings.py \
    --output-dir "$BACKUP_DIR" \
    --include-event-summaries \
    --s3-bucket your-bucket \
    --s3-prefix "embeddings/backup/$(date +%Y%m%d)/"
```

### Step 2: Rebuild Database Schema

```bash
# Drop and recreate database (or run migrations)
alembic downgrade base
alembic upgrade head
```

### Step 3: Restore Embeddings

```bash
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir "$BACKUP_DIR"
```

### Step 4: Verify Restoration

```bash
python -c "
from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    # Check embeddings
    chunk_count = session.execute(text(
        'SELECT COUNT(*) FROM langchain_pg_embedding WHERE collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name = \'chunk_embeddings\')'
    )).scalar()

    daily_count = session.execute(text(
        'SELECT COUNT(*) FROM langchain_pg_embedding WHERE collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name = \'daily_event_embeddings\')'
    )).scalar()

    # Check event summaries
    summary_count = session.execute(text('SELECT COUNT(*) FROM event_summaries')).scalar()

    print(f'Chunk embeddings: {chunk_count:,}')
    print(f'Daily event embeddings: {daily_count:,}')
    print(f'Event summaries: {summary_count:,}')
"
```

Expected output:
```
Chunk embeddings: 470,890
Daily event embeddings: 8,317
Event summaries: 10,107
```

## Performance Benchmarks

Based on actual system performance:

### Export Performance
- **Document embeddings** (470K): ~2-3 minutes
- **Event embeddings** (10K): ~15-30 seconds
- **Event summaries**: ~10 seconds
- **Total export time**: ~3-5 minutes

### Import Performance
- **Document embeddings** (470K): ~10-15 minutes
- **Event embeddings** (10K): ~2-3 minutes
- **Event summaries**: ~1 minute
- **Total import time**: ~15-20 minutes

### Regeneration Time (For Comparison)
- **Document embedding generation**: ~44 hours (159,362 seconds)
- **Event summary embedding**: ~30-45 minutes
- **Total regeneration**: ~45 hours

**Time Savings**: Import is ~130x faster than regeneration!

## File Formats

### Parquet Files

All data is stored in Apache Parquet format with zstd compression:

**Advantages:**
- Columnar storage (efficient for analytics)
- Built-in compression (~70% size reduction)
- Schema preservation
- Fast read/write with pandas/pyarrow
- Cross-platform compatibility

**Embedding Vector Storage:**
- Vectors stored as PostgreSQL text representation: `[0.123, 0.456, ...]`
- Converted back to `vector` type on import
- Preserves exact floating point values

### Manifest File

`export_manifest.json` contains:

```json
{
  "export_timestamp": "2024-11-06T19:45:00",
  "total_files": 6,
  "files": [
    "chunk_embeddings.parquet",
    "daily_event_embeddings.parquet",
    "weekly_event_embeddings.parquet",
    "monthly_event_embeddings.parquet",
    "event_summaries.parquet"
  ],
  "metadata": {
    "total_embeddings": 481007,
    "collections": ["chunk_embeddings", "daily_event_embeddings", "weekly_event_embeddings", "monthly_event_embeddings"],
    "include_event_summaries": true
  }
}
```

## Automation & Scheduling

### Daily Backup Cron Job

Add to crontab for daily backups:

```bash
# Daily backup at 2 AM, keep last 7 days
0 2 * * * cd /path/to/SP_Streamlit && \
    python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./embedding_backups/$(date +\%Y\%m\%d) \
    --include-event-summaries \
    --s3-bucket your-bucket \
    --s3-prefix embeddings/backup/$(date +\%Y\%m\%d)/ && \
    find ./embedding_backups -type d -mtime +7 -exec rm -rf {} \;
```

### Weekly Full Backup Script

```bash
#!/bin/bash
# weekly_backup.sh

BACKUP_DIR="./embedding_backups/$(date +%Y%m%d_%H%M%S)"
S3_BUCKET="your-backup-bucket"
S3_PREFIX="embeddings/weekly/$(date +%Y%m%d)/"

echo "Starting weekly backup to $BACKUP_DIR"

# Export
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir "$BACKUP_DIR" \
    --include-event-summaries \
    --s3-bucket "$S3_BUCKET" \
    --s3-prefix "$S3_PREFIX"

# Verify
if [ $? -eq 0 ]; then
    echo "Backup successful!"
    echo "Local: $BACKUP_DIR"
    echo "S3: s3://$S3_BUCKET/$S3_PREFIX"
else
    echo "Backup failed!"
    exit 1
fi
```

## Troubleshooting

### Import Fails with "collection does not exist"

The import script automatically creates collections if they don't exist. If you see this error, ensure pgvector extension is installed:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Import Fails with "vector dimension mismatch"

This means the embedding dimensions changed. You'll need to:
1. Drop the existing collection
2. Recreate it with correct dimensions
3. Re-import

### Out of Memory During Export

For very large collections, reduce batch size:

```bash
python services/pipeline/embeddings/export_embeddings.py \
    --batch-size 5000  # Smaller batches
```

### Slow Import Performance

Import uses batches of 1000 embeddings. For faster import on powerful systems:

Edit `import_embeddings.py` line ~140:
```python
batch_size = 5000  # Increase from 1000
```

## Best Practices

1. **Regular Backups**: Schedule weekly full backups to S3
2. **Version Control**: Include timestamp in backup directory names
3. **Verify Exports**: Always check manifest file after export
4. **Test Restores**: Periodically test restore process to verify backups
5. **Keep Local Copies**: Maintain recent backups locally for fast recovery
6. **Monitor S3 Costs**: Use S3 lifecycle policies to archive old backups to Glacier
7. **Document Changes**: Note any schema changes in manifest metadata

## Security Considerations

**Parquet files contain:**
- Vector embeddings (derived from documents)
- Event summaries (aggregated text)
- Metadata (document IDs, dates, countries)

**Do NOT include:**
- Original source documents
- User credentials
- API keys

**S3 Security:**
- Use private buckets
- Enable encryption at rest
- Use IAM roles instead of access keys
- Enable versioning for recovery

## File Size Reference

Approximate compressed sizes:

| Collection | Embeddings | File Size | Uncompressed |
|------------|------------|-----------|--------------|
| chunk_embeddings | 470,890 | ~850 MB | ~2.1 GB |
| daily_event_embeddings | 8,317 | ~18 MB | ~42 MB |
| weekly_event_embeddings | 1,014 | ~2 MB | ~5 MB |
| monthly_event_embeddings | 776 | ~1.5 MB | ~3.5 MB |
| event_summaries | 10,107 rows | ~6 MB | ~15 MB |
| **TOTAL** | **481,007** | **~875 MB** | **~2.16 GB** |

Compression ratio: ~60% size reduction with zstd

## Support

For issues or questions:
- Check script help: `python export_embeddings.py --help`
- Review logs for error messages
- Verify PostgreSQL pgvector extension is installed
- Ensure sufficient disk space (2x file size for safe margin)
