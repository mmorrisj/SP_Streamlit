# Path Updates Required After Data Consolidation

## Summary

After consolidating data into `_data/`, the following files contain hardcoded paths that need updating.

## Path Mapping

| Old Path | New Path | Purpose |
|----------|----------|---------|
| `data/processed_embeddings/` | `_data/processed/embeddings/` | Processed embedding parquet files |
| `./materiality_exports/` | `./_data/exports/materiality/` | Materiality score exports |
| `./event_exports/` | `./_data/exports/events/` | Event table exports |
| `output/publications/` | `_data/publications/` | Generated publications |
| `full_db_export/` (S3) | `_data/exports/database/` (local) | Full database exports |
| `embedding_backups/` | `_data/exports/embeddings/` | Embedding backups |

## Files Requiring Updates

### High Priority (Actively Used)

#### 1. services/pipeline/embeddings/load_embeddings.py
**Lines to update:**
- Line 38: `LOCAL_TRACKER_FILE = "data/processed_embeddings/.processed_tracker.json"`
- Line 80: `def process_local_embeddings(directory: str = "data/processed_embeddings",`
- Line 203: `def show_local_status(directory: str = "data/processed_embeddings"):`
- Line 222: `def reprocess_local_files(filenames: List[str], directory: str = "data/processed_embeddings"):`
- Line 269: `parser.add_argument("--directory", type=str, default="data/processed_embeddings",`
- Line 270: Help text

**Update to:**
```python
LOCAL_TRACKER_FILE = "_data/processed/embeddings/.processed_tracker.json"
def process_local_embeddings(directory: str = "_data/processed/embeddings",
def show_local_status(directory: str = "_data/processed/embeddings"):
def reprocess_local_files(filenames: List[str], directory: str = "_data/processed/embeddings"):
parser.add_argument("--directory", type=str, default="_data/processed/embeddings",
```

#### 2. services/pipeline/embeddings/load_embeddings_by_docid.py
**Lines to update:**
- Line 63: `local_dir: str = './data/processed_embeddings',`
- Line 388: `default='./data/processed_embeddings',`
- Line 389: Help text

**Update to:**
```python
local_dir: str = './_data/processed/embeddings',
default='./_data/processed/embeddings',
```

#### 3. services/pipeline/embeddings/s3_to_pgvector.py
**Lines to update:**
- Line ~50: `tracker_dir: str = './data/processed_embeddings',`
- Line ~190: `def view_tracker(collection_name: str, tracker_dir: str = './data/processed_embeddings'):`
- Line ~210: `def reset_tracker(collection_name: str, tracker_dir: str = './data/processed_embeddings', confirm: bool = False):`
- Multiple argparse defaults

**Update to:**
```python
tracker_dir: str = './_data/processed/embeddings',
```

#### 4. services/pipeline/events/export_event_tables.py
**Line to update:**
- `parser.add_argument('--output-dir', type=str, default='./event_exports',`

**Update to:**
```python
parser.add_argument('--output-dir', type=str, default='./_data/exports/events',
```

#### 5. services/pipeline/events/import_event_tables.py
**Documentation to update:**
- Line ~10-15: Example commands showing `./event_exports`

**Update to:**
```python
python services/pipeline/events/import_event_tables.py --input-dir ./_data/exports/events
```

#### 6. services/pipeline/events/export_materiality_scores.py
**Line to update:**
- `parser.add_argument('--output-dir', type=str, default='./materiality_exports',`

**Update to:**
```python
parser.add_argument('--output-dir', type=str, default='./_data/exports/materiality',
```

#### 7. services/pipeline/events/import_materiality_scores.py
**Documentation to update:**
- Lines ~10-20: Example commands showing `./materiality_exports`

**Update to:**
```python
python services/pipeline/events/import_materiality_scores.py --input-dir ./_data/exports/materiality
```

#### 8. services/pipeline/summaries/export_monthly_publications_docx.py
**Line to update:**
- `parser.add_argument('--output-dir', type=str, default='output/publications',`

**Update to:**
```python
parser.add_argument('--output-dir', type=str, default='_data/publications',
```

#### 9. services/pipeline/summaries/export_publication_template_docx.py
**Line to update:**
- `parser.add_argument('--output-dir', type=str, default='output/publications',`

**Update to:**
```python
parser.add_argument('--output-dir', type=str, default='_data/publications',
```

#### 10. services/pipeline/summaries/generate_monthly_summary_publications.py
**Lines to update:**
- `def save_publication(publication: Dict, output_dir: str = 'output/publications'):`
- `parser.add_argument('--output-dir', type=str, default='output/publications', help='Output directory for publications')`

**Update to:**
```python
def save_publication(publication: Dict, output_dir: str = '_data/publications'):
parser.add_argument('--output-dir', type=str, default='_data/publications', help='Output directory for publications')
```

### Medium Priority (Migration Scripts - Less Frequently Used)

#### 11. services/pipeline/migrations/export_full_database.py
**Lines to update:**
- Documentation example showing `./full_export`
- `parser.add_argument('--s3-prefix', type=str, default='full_db_export/',`

**Update to:**
```python
# Documentation example
python %(prog)s --output-dir ./_data/exports/database --s3-bucket morris-sp-bucket --s3-prefix exports/database/

# S3 prefix (or keep as is if S3 structure is different)
parser.add_argument('--s3-prefix', type=str, default='exports/database/',
```

#### 12. services/pipeline/migrations/import_full_database.py
**Lines to update:**
- Documentation example
- `parser.add_argument('--s3-prefix', type=str, default='full_db_export/',`

**Update to:**
```python
python services/pipeline/migrations/import_full_database.py --s3-bucket my-bucket --s3-prefix exports/database/
parser.add_argument('--s3-prefix', type=str, default='exports/database/',
```

### Low Priority (Embedding Export - Already Uses Relative Defaults)

#### 13. services/pipeline/embeddings/export_embeddings.py
**Current state:**
- Uses `./embedding_exports` as default (doesn't exist in old structure either)
- S3 prefix: `embeddings/backup/` (this is fine, it's S3 not local)

**Recommendation:**
Update default output dir:
```python
parser.add_argument('--output-dir', type=str, default='./_data/exports/embeddings',
                   help='Directory to store exported parquet files (default: ./_data/exports/embeddings)')
```

#### 14. services/pipeline/embeddings/import_embeddings.py
**Current state:**
- Only uses S3 prefix `embeddings/backup/` which is fine
- No local path defaults

**Recommendation:**
No changes needed unless local input dir is added.

## Update Script

Here's a script to make all the changes automatically:

```bash
# services/pipeline/embeddings/load_embeddings.py
sed -i 's|data/processed_embeddings|_data/processed/embeddings|g' services/pipeline/embeddings/load_embeddings.py

# services/pipeline/embeddings/load_embeddings_by_docid.py
sed -i 's|./data/processed_embeddings|./_data/processed/embeddings|g' services/pipeline/embeddings/load_embeddings_by_docid.py

# services/pipeline/embeddings/s3_to_pgvector.py
sed -i 's|./data/processed_embeddings|./_data/processed/embeddings|g' services/pipeline/embeddings/s3_to_pgvector.py

# services/pipeline/events/export_event_tables.py
sed -i "s|default='./event_exports'|default='./_data/exports/events'|g" services/pipeline/events/export_event_tables.py

# services/pipeline/events/import_event_tables.py
sed -i 's|./event_exports|./_data/exports/events|g' services/pipeline/events/import_event_tables.py

# services/pipeline/events/export_materiality_scores.py
sed -i "s|default='./materiality_exports'|default='./_data/exports/materiality'|g" services/pipeline/events/export_materiality_scores.py

# services/pipeline/events/import_materiality_scores.py
sed -i 's|./materiality_exports|./_data/exports/materiality|g' services/pipeline/events/import_materiality_scores.py

# services/pipeline/summaries/*
sed -i "s|output/publications|_data/publications|g" services/pipeline/summaries/export_monthly_publications_docx.py
sed -i "s|output/publications|_data/publications|g" services/pipeline/summaries/export_publication_template_docx.py
sed -i "s|output/publications|_data/publications|g" services/pipeline/summaries/generate_monthly_summary_publications.py

# services/pipeline/embeddings/export_embeddings.py
sed -i "s|./embedding_exports|./_data/exports/embeddings|g" services/pipeline/embeddings/export_embeddings.py

# services/pipeline/migrations/*
sed -i "s|full_db_export|exports/database|g" services/pipeline/migrations/export_full_database.py
sed -i "s|full_db_export|exports/database|g" services/pipeline/migrations/import_full_database.py
```

## Testing After Updates

### Test Embeddings
```bash
# Test load embeddings
python services/pipeline/embeddings/load_embeddings.py --source local --status

# Verify path
grep "_data/processed/embeddings" services/pipeline/embeddings/load_embeddings.py
```

### Test Event Exports
```bash
# Test export (dry run)
python services/pipeline/events/export_event_tables.py --dry-run

# Check default path used
python services/pipeline/events/export_event_tables.py --help | grep output-dir
```

### Test Publications
```bash
# Test publication export
python services/pipeline/summaries/generate_monthly_summary_publications.py --help | grep output-dir
```

## Verification Checklist

After making changes:

- [ ] All references to `data/processed_embeddings` updated to `_data/processed/embeddings`
- [ ] All references to `./event_exports` updated to `./_data/exports/events`
- [ ] All references to `./materiality_exports` updated to `./_data/exports/materiality`
- [ ] All references to `output/publications` updated to `_data/publications`
- [ ] All references to `full_db_export` updated to `exports/database` (S3) or `_data/exports/database` (local)
- [ ] Test each export script to verify new paths work
- [ ] Update documentation (README.md, CLAUDE.md) if needed

## Files That Don't Need Updates

These files are okay as-is:
- `services/pipeline/embeddings/export_embeddings.py` - S3 prefixes are fine, just update local default
- `services/pipeline/embeddings/import_embeddings.py` - Only uses S3 paths
- Most scripts that already use command-line arguments (users can specify new paths)

## Post-Update Actions

1. Create `_data/processed/embeddings/.processed_tracker.json` if it doesn't exist
2. Test all export scripts with new defaults
3. Update any documentation referencing old paths
4. Consider adding symbolic links for backward compatibility (optional):
   ```bash
   ln -s _data/processed/embeddings data/processed_embeddings
   ln -s _data/exports/events event_exports
   ```
