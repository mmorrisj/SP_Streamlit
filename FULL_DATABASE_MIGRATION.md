# Full Database Migration Guide

Complete guide for migrating the entire database from System 1 to System 2.

---

## Overview

This creates an **exact replica** of System 1's database state on System 2, including:

- 496,783 documents
- All normalized relationships (categories, subcategories, countries, raw events)
- 153,873 event clusters
- 112,510 canonical events (with 22,235 materiality scores)
- 140,037 daily event mentions
- 12,227 event summaries
- All bilateral summaries (if present)

**Total:** ~640,000+ rows across all tables

### Data Linkages Preserved

The export/import process preserves **ALL** linkages between tables:

**1. Document → Metadata Linkages** (Many-to-Many):
- ✅ `categories` → links documents to their categories
- ✅ `subcategories` → links documents to their subcategories
- ✅ `initiating_countries` → links documents to initiating countries
- ✅ `recipient_countries` → links documents to recipient countries
- ✅ `raw_events` → links documents to extracted event names

**2. Event → Document Linkages** (Array Fields):
- ✅ `event_clusters.doc_ids[]` → array linking clusters to source documents
- ✅ `daily_event_mentions.doc_ids[]` → array linking events to source articles

**3. Event Hierarchy Linkages** (Foreign Keys):
- ✅ `daily_event_mentions.canonical_event_id` → FK to canonical_events
- ✅ `canonical_events.master_event_id` → FK for event consolidation hierarchy

**4. Materiality Scores** (Preserved):
- ✅ `canonical_events.material_score` → 22,235 materiality scores (1-10 scale)
- ✅ `canonical_events.material_justification` → AI justifications for scores

**Result**: Complete traceability from documents → events → scores is maintained

---

## Prerequisites

### System 1 (Export Machine)
- Docker running with softpower_db
- ~50-100 MB free disk space for export
- Python environment with all dependencies

### System 2 (Import Machine)
- PostgreSQL database running (empty or existing)
- Same schema as System 1 (run Alembic migrations first)
- Python environment with all dependencies
- ~50-100 MB free disk space for import files

---

## Step 1: Export from System 1

### Quick Export (Local Only)
```bash
# On System 1
cd /c/Users/mmorr/Desktop/Apps/SP_Streamlit

# Export everything to local directory
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export
```

### Export with S3 Upload (Recommended for System 2 Migration)
```bash
# Export locally AND automatically upload to S3
PYTHONPATH=/c/Users/mmorr/Desktop/Apps/SP_Streamlit python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/

# System 2 can then import directly from S3 (see Step 4)
```

### Docker Export
```bash
# If running in Docker
docker exec -it api-service python services/pipeline/migrations/export_full_database.py \
    --output-dir /app/full_db_export

# Or with S3 upload
docker exec -it api-service python services/pipeline/migrations/export_full_database.py \
    --output-dir /app/full_db_export \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/
```

### Export Options
```bash
# Skip optional tables (bilateral summaries)
python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export \
    --skip-optional

# With S3 upload and custom prefix
python services/pipeline/migrations/export_full_database.py \
    --output-dir ./full_db_export \
    --s3-bucket morris-sp-bucket \
    --s3-prefix exports/system1/$(date +%Y%m%d)/ \
    --skip-optional
```

### Expected Output
```
================================================================================
FULL DATABASE EXPORT
================================================================================

Exporting: documents
Total rows: 496,783
  Batch 1: 10,000 rows → documents_20241218_120000_batch0000.parquet (15.2 MB)
  Batch 2: 10,000 rows → documents_20241218_120001_batch0001.parquet (15.1 MB)
  ...
  ✅ Exported 496,783 rows in 50 file(s)

Exporting: categories
Total rows: 125,432
  ✅ Exported 125,432 rows in 3 file(s)

...

================================================================================
EXPORT COMPLETE
================================================================================

Total tables exported: 10
Total files created: 150
Total rows exported: 640,537
Total size: 85.4 MB

Manifest: ./full_db_export/manifest.json
```

---

## Step 2: Transfer Files to System 2

### Option A: S3 (Recommended - Automatic)
```bash
# If you used --s3-bucket during export, files are already in S3!
# System 2 can import directly - NO transfer needed (see Step 4)
```

### Option B: Direct Copy (if same network)
```bash
# Copy entire directory to System 2
scp -r ./full_db_export user@system2:/path/to/SP_Streamlit/
```

### Option C: USB Drive
```bash
# Copy to USB
cp -r ./full_db_export /media/usb/

# On System 2
cp -r /media/usb/full_db_export /path/to/SP_Streamlit/
```

### Option D: Manual S3 Upload (if not done during export)
```bash
# Upload to S3 manually using AWS CLI
aws s3 sync ./full_db_export s3://your-bucket/full_db_export/

# System 2 can then import directly from S3 (see Step 4)
```

---

## Step 3: Prepare System 2

### Verify Database is Running
```bash
# On System 2
docker-compose ps

# Should show softpower_db running
```

### Run Alembic Migrations (Critical!)
```bash
# On System 2 - Ensure schema matches System 1
docker-compose --profile migrate up

# Or locally
alembic upgrade head
```

### Verify Empty Database (Optional)
```bash
# Check if database is empty or has existing data
python -c "
from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    doc_count = session.execute(text('SELECT COUNT(*) FROM documents')).fetchone()[0]
    event_count = session.execute(text('SELECT COUNT(*) FROM canonical_events')).fetchone()[0]
    print(f'Documents: {doc_count:,}')
    print(f'Events: {event_count:,}')
"
```

---

## Step 4: Import on System 2

### Option A: Import from S3 (Recommended)

**Test Import (Dry Run - Recommended First!)**
```bash
# On System 2
cd /path/to/SP_Streamlit

# Dry run - downloads from S3 but makes no changes
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/migrations/import_full_database.py \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/ \
    --dry-run
```

**Actual Import from S3**
```bash
# Downloads from S3 and imports all data
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/migrations/import_full_database.py \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/
```

**Import from S3 with Clear (WARNING: Destroys Existing Data!)**
```bash
# Clear all existing data and import fresh from S3
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/migrations/import_full_database.py \
    --s3-bucket morris-sp-bucket \
    --s3-prefix full_db_export/ \
    --clear-existing

# Will prompt: Type 'yes' to continue:
```

### Option B: Import from Local Directory

**Test Import (Dry Run)**
```bash
# Dry run - no changes made
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/migrations/import_full_database.py \
    --input-dir ./full_db_export \
    --dry-run
```

**Actual Import**
```bash
# Import all data from local directory
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/migrations/import_full_database.py \
    --input-dir ./full_db_export
```

**Import with Clear (WARNING: Destroys Existing Data!)**
```bash
# Clear all existing data and import fresh
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/migrations/import_full_database.py \
    --input-dir ./full_db_export \
    --clear-existing

# Will prompt: Type 'yes' to continue:
```

### Expected Output
```
================================================================================
FULL DATABASE IMPORT
================================================================================

Input directory: ./full_db_export
Export timestamp: 2024-12-18T12:00:00
Total tables: 10
Total rows: 640,537
Total size: 85.40 MB

Importing documents...
  Processing documents_20241218_120000_batch0000.parquet...
    Batch 1 (10,000 rows)... [OK] 10,000 rows
  ...
  ✅ Imported 496,783 rows

Importing categories...
  ✅ Imported 125,432 rows

...

================================================================================
IMPORT COMPLETE
================================================================================

Import Results:
Table                                    Imported        Expected       Status
--------------------------------------------------------------------------------
documents                                 496,783         496,783       success
categories                                125,432         125,432       success
subcategories                              98,234          98,234       success
initiating_countries                       42,567          42,567       success
recipient_countries                        38,921          38,921       success
raw_events                                234,156         234,156       success
event_clusters                            153,873         153,873       success
canonical_events                          112,510         112,510       success
daily_event_mentions                      140,037         140,037       success
event_summaries                            12,227          12,227       success

TOTAL                                     640,537         640,537
```

---

## Step 5: Verify Import

### Run Data Integrity Check
```bash
# On System 2
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/diagnostics/verify_data_linkage.py
```

Expected:
```
✅ ALL DATA INTEGRITY CHECKS PASSED

📄 Documents: 496,783
⭐ Canonical Events: 112,510
   Materiality Scored: 22,235 (19.8%)
📰 Daily Event Mentions: 140,037
   With doc_ids: 140,029 (100.0%)
```

### Verify Relationship Table Linkages
```bash
# On System 2 - Verify all many-to-many relationships were imported
python -c "
from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    # Check relationship tables
    tables = {
        'categories': 'doc_id, category',
        'subcategories': 'doc_id, subcategory',
        'initiating_countries': 'doc_id, initiating_country',
        'recipient_countries': 'doc_id, recipient_country',
        'raw_events': 'doc_id, event_name'
    }

    print('Relationship Table Linkages:')
    print('=' * 70)
    for table, cols in tables.items():
        count = session.execute(text(f'SELECT COUNT(*) FROM {table}')).fetchone()[0]
        col1, col2 = cols.split(', ')

        # Check for orphaned references
        orphaned = session.execute(text(f'''
            SELECT COUNT(*) FROM {table} t
            WHERE NOT EXISTS (
                SELECT 1 FROM documents d WHERE d.doc_id = t.{col1}
            )
        ''')).fetchone()[0]

        status = '✅' if orphaned == 0 else '⚠️'
        print(f'{status} {table:30s}: {count:>10,} rows, {orphaned} orphaned')

    print()
    print('Event Linkages:')
    print('=' * 70)

    # Check daily_event_mentions → canonical_events FK
    orphaned_mentions = session.execute(text('''
        SELECT COUNT(*) FROM daily_event_mentions dem
        WHERE NOT EXISTS (
            SELECT 1 FROM canonical_events ce WHERE ce.id = dem.canonical_event_id
        )
    ''')).fetchone()[0]

    status = '✅' if orphaned_mentions == 0 else '⚠️'
    print(f'{status} daily_event_mentions → canonical_events: {orphaned_mentions} broken FKs')

    # Check master_event_id hierarchy
    broken_hierarchy = session.execute(text('''
        SELECT COUNT(*) FROM canonical_events ce1
        WHERE ce1.master_event_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM canonical_events ce2 WHERE ce2.id = ce1.master_event_id
        )
    ''')).fetchone()[0]

    status = '✅' if broken_hierarchy == 0 else '⚠️'
    print(f'{status} canonical_events master_event_id hierarchy: {broken_hierarchy} broken refs')
"
```

Expected output:
```
Relationship Table Linkages:
======================================================================
✅ categories                      :    125,432 rows, 0 orphaned
✅ subcategories                   :     98,234 rows, 0 orphaned
✅ initiating_countries            :     42,567 rows, 0 orphaned
✅ recipient_countries             :     38,921 rows, 0 orphaned
✅ raw_events                      :    234,156 rows, 0 orphaned

Event Linkages:
======================================================================
✅ daily_event_mentions → canonical_events: 0 broken FKs
✅ canonical_events master_event_id hierarchy: 0 broken refs
```

### Verify Counts Match
```bash
# On System 2
python -c "
from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    tables = [
        'documents',
        'categories',
        'subcategories',
        'canonical_events',
        'daily_event_mentions',
        'event_summaries'
    ]

    print('Table Counts:')
    for table in tables:
        count = session.execute(text(f'SELECT COUNT(*) FROM {table}')).fetchone()[0]
        print(f'  {table:30s}: {count:>10,}')
"
```

### Verify Materiality Scores
```bash
# On System 2
python -c "
from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) as total,
            COUNT(CASE WHEN material_score IS NOT NULL THEN 1 END) as scored
        FROM canonical_events
        GROUP BY initiating_country
        ORDER BY total DESC
    ''')).fetchall()

    print('Materiality Scoring by Country:')
    for row in result:
        print(f'  {row[0]:20s}: {row[2]:>6,} / {row[1]:>6,}')
"
```

---

## Step 6: Start Processing on System 2

### Test Azure OpenAI Connection
```bash
# On System 2
jupyter notebook test_azure_connection.ipynb
# Set CREDENTIAL_MODE = "secrets" and run all cells
```

### Start Materiality Scoring
```bash
# On System 2 - Start with Iran (highest priority)
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/score_canonical_event_materiality.py \
    --country Iran \
    --source azure
```

---

## Troubleshooting

### Export Issues

**Problem:** "Table does not exist"
```bash
# Check if table exists
docker exec -it softpower_db psql -U matthew50 -d softpower-db \
    -c "\dt public.*"
```

**Problem:** "Out of disk space"
```bash
# Check disk usage
df -h

# Clear space or use external drive
python services/pipeline/migrations/export_full_database.py \
    --output-dir /media/external/full_db_export
```

### Transfer Issues

**Problem:** Files corrupted during transfer
```bash
# Verify integrity using manifest
python -c "
import json
from pathlib import Path

with open('full_db_export/manifest.json', 'r') as f:
    manifest = json.load(f)

missing = []
for table in manifest['tables']:
    for file in table['files']:
        if not Path(f'full_db_export/{file}').exists():
            missing.append(file)

if missing:
    print(f'Missing files: {missing}')
else:
    print('All files present')
"
```

### Import Issues

**Problem:** "Foreign key constraint violation"
```bash
# Tables imported in wrong order - re-run import
# The script handles dependencies automatically
```

**Problem:** "Duplicate key value violates unique constraint"
```bash
# Data already exists - use --clear-existing to start fresh
python services/pipeline/migrations/import_full_database.py \
    --input-dir ./full_db_export \
    --clear-existing
```

**Problem:** Import is very slow
```bash
# Normal for large datasets
# Expected time: ~30-60 minutes for full import
# Monitor progress with timestamps in output
```

### Verification Issues

**Problem:** Counts don't match
```bash
# Check manifest vs actual import
python -c "
import json
with open('full_db_export/manifest.json', 'r') as f:
    manifest = json.load(f)

for table in manifest['tables']:
    print(f'{table[\"table\"]}: expected {table[\"total_rows\"]:,} rows')
"

# Compare to database
# Run verification query above
```

---

## Performance Estimates

| Task | Estimated Time |
|------|----------------|
| Export (System 1) | 10-20 minutes |
| Transfer (network) | 5-30 minutes (depends on speed) |
| Transfer (USB) | 2-5 minutes |
| Import (System 2) | 30-60 minutes |
| Verification | 2-5 minutes |
| **Total** | **1-2 hours** |

---

## Important Notes

1. **Schema Compatibility:** System 2 MUST have the same database schema as System 1
   - Run `alembic upgrade head` on System 2 before importing

2. **Data Safety:** Export creates a complete snapshot
   - Original System 1 data is untouched
   - Import uses `ON CONFLICT DO NOTHING` - safe to re-run

3. **Incremental Updates:** This is a one-time migration
   - After migration, systems are independent
   - Updates on System 1 won't automatically sync to System 2

4. **Disk Space:** Monitor disk usage
   - Export: ~100 MB compressed
   - Uncompressed in PostgreSQL: ~2-5 GB

5. **Network Bandwidth:** For remote transfer
   - 100 MB @ 10 Mbps = ~80 seconds
   - 100 MB @ 1 Mbps = ~13 minutes

---

## Next Steps After Migration

1. **Verify Data Integrity** ✓
2. **Test Azure OpenAI Connection** ✓
3. **Start Materiality Scoring on System 2**
   - Iran: 36,526 events
   - USA: 22,120 events
   - Turkey: 18,387 events

4. **Continue Processing on System 1**
   - China: 2,993 remaining
   - Russia: 10,249 remaining

5. **Monitor Both Systems**
   - System 1: OpenAI proxy
   - System 2: Azure OpenAI

---

## S3 Support Details

Both export and import scripts now support S3 for seamless cloud-based migration:

### Export S3 Features
- **Automatic Upload**: Export locally and upload to S3 in one command
- **Local Backup**: Export files remain on local disk after S3 upload
- **Progress Tracking**: Shows upload progress every 10 files
- **Custom Paths**: Support for dated or custom S3 prefixes

### Import S3 Features
- **Automatic Download**: Downloads from S3 to temporary directory
- **Auto Cleanup**: Temporary files deleted after import completes
- **Same Validation**: Full manifest validation and row count verification
- **Dry Run Support**: Test S3 import without making changes

### Requirements
- FastAPI S3 proxy running (port 8000 by default)
- `API_URL` environment variable set
- S3 bucket with appropriate permissions

See [S3_IMPORT_GUIDE.md](S3_IMPORT_GUIDE.md) for detailed documentation.

---

## Summary

This migration process ensures System 2 starts with the **exact same state** as System 1:
- ✅ All 496,783 documents
- ✅ All 112,510 canonical events
- ✅ All 22,235 materiality scores
- ✅ All 153,873 event clusters
- ✅ All 140,037 daily event mentions
- ✅ All 12,227 event summaries
- ✅ Complete data lineage and traceability

**Result:** System 2 can immediately begin processing the remaining 90,275 unscored events using Azure OpenAI, while System 1 continues its work in parallel.
