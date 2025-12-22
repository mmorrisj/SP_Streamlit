# S3 Migration Guide

## Full Database Export & Import with S3 Support

Both `export_full_database.py` and `import_full_database.py` scripts now support S3, enabling seamless database migration between System 1 and System 2.

---

## Export Options

### Option 1: Export to Local Directory Only

```bash
# Standard export
python services/pipeline/migrations/export_full_database.py --output-dir ./full_db_export

# Skip optional tables (bilateral summaries, etc.)
python services/pipeline/migrations/export_full_database.py --output-dir ./full_db_export --skip-optional
```

---

### Option 2: Export to Local + Upload to S3 (NEW!)

```bash
# Export locally and upload to S3
python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export \
    --s3-bucket your-bucket-name \
    --s3-prefix full_db_export/

# Export with custom S3 prefix
python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export \
    --s3-bucket morris-sp-bucket \
    --s3-prefix exports/system1/$(date +%Y%m%d)/
```

---

## Import Options

### Option 1: Import from Local Directory (Original)

```bash
# Standard import
python services/pipeline/migrations/import_full_database.py --input-dir ./full_db_export

# Dry run (test without importing)
python services/pipeline/migrations/import_full_database.py --input-dir ./full_db_export --dry-run

# Clear existing data and import (⚠️ DESTRUCTIVE!)
python services/pipeline/migrations/import_full_database.py --input-dir ./full_db_export --clear-existing
```

---

### Option 2: Import from S3 (NEW!)

```bash
# Import from S3 bucket
python services/pipeline/migrations/import_full_database.py \
    --s3-bucket your-bucket-name \
    --s3-prefix full_db_export/

# Dry run from S3
python services/pipeline/migrations/import_full_database.py \
    --s3-bucket your-bucket-name \
    --s3-prefix full_db_export/ \
    --dry-run

# Clear and import from S3
python services/pipeline/migrations/import_full_database.py \
    --s3-bucket your-bucket-name \
    --s3-prefix full_db_export/ \
    --clear-existing
```

---

## How S3 Export Works

1. **Exports to Local Directory First**
   - Creates all parquet files in the specified --output-dir
   - Generates manifest.json with metadata
   - Validates export completed successfully

2. **Uploads to S3 (if --s3-bucket provided)**
   - Uploads all .parquet files and manifest.json
   - Shows progress every 10 files
   - Uses FastAPI S3 proxy for upload

3. **Local Files Remain**
   - Export directory is NOT deleted after upload
   - Allows local backup and verification
   - Can be manually deleted after confirming S3 upload

---

## How S3 Import Works

1. **Downloads to Temporary Directory**
   - Creates a temp directory (e.g., `/tmp/full_db_import_abc123/`)
   - Downloads all parquet files and manifest.json from S3
   - Shows progress every 10 files

2. **Imports from Local Temp**
   - Runs the standard import process from the temp directory
   - Same validation and error handling as local import

3. **Automatic Cleanup**
   - Deletes temporary directory after import completes
   - Cleanup happens even if import fails

---

## Requirements

**S3 import requires:**
- FastAPI S3 proxy running (port 8000 by default)
- API_URL environment variable set
- OR direct boto3 access with AWS credentials

**Check if S3 is available:**
```python
python -c "from services.pipeline.embeddings.s3 import _get_api_client; print('S3 Available' if _get_api_client() else 'S3 Not Available')"
```

---

## Arguments Reference

### Export Script Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--output-dir` | Yes | Local directory for exported parquet files |
| `--skip-optional` | No | Skip optional tables (bilateral summaries, etc.) |
| `--s3-bucket` | No | S3 bucket to upload export files |
| `--s3-prefix` | No | S3 prefix/path (default: `full_db_export/`) |

### Import Script Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--input-dir` | Yes* | Local directory with parquet files |
| `--s3-bucket` | Yes* | S3 bucket name |
| `--s3-prefix` | No | S3 prefix/path (default: `full_db_export/`) |
| `--dry-run` | No | Test import without changes |
| `--clear-existing` | No | Clear tables before import (⚠️ destructive!) |

*Either `--input-dir` OR `--s3-bucket` is required (mutually exclusive)

---

## Examples

### Export Examples

#### Example 1: Local Export Only
```bash
python services/pipeline/migrations/export_full_database.py --output-dir ./full_db_export
```

#### Example 2: Export with S3 Upload
```bash
python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/
```

#### Example 3: Export to Dated S3 Path
```bash
python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export \
    --s3-bucket morris-sp-bucket \
    --s3-prefix exports/system1/$(date +%Y%m%d)/
```

---

### Import Examples

#### Example 4: Quick Local Import
```bash
python services/pipeline/migrations/import_full_database.py --input-dir ./full_db_export
```

#### Example 5: S3 Import from Specific Bucket
```bash
python services/pipeline/migrations/import_full_database.py \
    --s3-bucket morris-sp-bucket \
    --s3-prefix exports/system1/full_db_export/
```

#### Example 6: Test S3 Import (Dry Run)
```bash
python services/pipeline/migrations/import_full_database.py \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/ \
    --dry-run
```

#### Example 7: Fresh Import from S3 (Clear Existing)
```bash
# ⚠️ WARNING: This will delete all existing data!
python services/pipeline/migrations/import_full_database.py \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/ \
    --clear-existing
```

---

## Comparison: Export vs Import

| Feature | Export Script | Import Script |
|---------|--------------|---------------|
| Local support | ✅ | ✅ |
| S3 upload | ✅ (NEW!) | N/A |
| S3 download | N/A | ✅ |
| Manifest | Creates | Reads |
| Temp directory | No | Yes (for S3 import) |
| Auto cleanup | No | Yes (import only) |

---

## Troubleshooting

### Error: "S3 support not available"
- Check that `services/pipeline/embeddings/s3.py` exists
- Ensure FastAPI proxy is running or boto3 is installed
- Set `API_URL` environment variable

### Error: "No files found at s3://..."
- Verify bucket name and prefix are correct
- Check S3 permissions
- Ensure manifest.json exists in the S3 prefix

### Error: "Failed to download from S3"
- Check network connectivity
- Verify FastAPI proxy is running (port 8000)
- Check AWS credentials if using direct boto3

---

## Migration Workflow

**System 1 → System 2 via S3 (Recommended):**

1. **On System 1 - Export and Upload:**
   ```bash
   # Export locally and automatically upload to S3
   python services/pipeline/migrations/export_full_database.py \
       --output-dir ./full_db_export \
       --s3-bucket your-bucket \
       --s3-prefix full_db_export/
   ```

2. **On System 2 - Download and Import:**
   ```bash
   # Download from S3 and import automatically
   python services/pipeline/migrations/import_full_database.py \
       --s3-bucket your-bucket \
       --s3-prefix full_db_export/
   ```

**Alternative: Manual Upload (Legacy Method):**

1. **On System 1 - Export only:**
   ```bash
   python services/pipeline/migrations/export_full_database.py --output-dir ./full_db_export
   ```

2. **Upload to S3 manually:**
   ```bash
   aws s3 sync ./full_db_export/ s3://your-bucket/full_db_export/
   ```

3. **On System 2 - Import:**
   ```bash
   python services/pipeline/migrations/import_full_database.py \
       --s3-bucket your-bucket \
       --s3-prefix full_db_export/
   ```

---

## Notes

- **Temporary Directory**: Located in system temp (e.g., `/tmp/` on Linux, `C:\Users\...\AppData\Local\Temp\` on Windows)
- **Disk Space**: Ensure temp directory has 2-3 GB free for typical exports
- **Download Time**: ~5-10 minutes for 175 files (2.3 GB) depending on network speed
- **Cleanup**: Always happens automatically, even if import fails
