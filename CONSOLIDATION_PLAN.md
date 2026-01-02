# Data & Archive Consolidation Plan

## Current Problems

**Scattered Data Directories:**
- `./data/` - Processed embeddings and JSON files
- `./output/` - Publications output
- `./full_db_export/` - Database exports
- `./materiality_exports/` - Materiality score exports
- `./test_export/` - Test exports
- `./services/data/` - Service-specific data

**Multiple Archive Directories:**
- `./archive/` - Old Python scripts (code archive)
- `./docs/archive/` - Deprecated markdown docs
- `./docs/docs_archive/` - More deprecated docs
- `./streamlit_old_backup/` - Old Streamlit backup

**Issues:**
- Hard to find data
- Unclear what's production vs test
- Archives scattered across project
- No clear data organization

## Proposed Structure

### Single Data Directory: `_data/`

Use underscore prefix to:
- Keep it at top of directory listings
- Clearly separate from source code
- Signal "not source code"

```
_data/                                  # All runtime data here
├── processed/                          # Processed data
│   ├── embeddings/                     # Document embeddings
│   └── json/                           # Processed JSON files
│
├── exports/                            # All exports
│   ├── database/                       # Full database exports
│   │   ├── 2024-12-19/
│   │   └── latest/
│   ├── embeddings/                     # Embedding backups
│   ├── events/                         # Event table exports
│   └── materiality/                    # Materiality score exports
│
├── publications/                       # Generated publications
│
└── temp/                               # Temporary/test exports
    └── test_exports/
```

### Single Archive: `docs/archive/`

Consolidate all archives under `docs/`:

```
docs/
├── archive/                            # All historical content
│   ├── code/                           # OLD Python scripts (from ./archive/)
│   │   ├── atom.py
│   │   ├── models.py
│   │   └── ...
│   │
│   ├── deprecated/                     # Deprecated proposals (already here)
│   ├── migration_guides/               # Migration docs (already here)
│   ├── legacy_deployment/              # Old deployment (already here)
│   ├── analysis_reports/               # Historical reports (already here)
│   │
│   └── old_docs/                       # From docs/docs_archive/
│       ├── CONSOLIDATED_PIPELINE_PRODUCTION.md
│       └── ...
│
├── deployment/                         # Current deployment guides
├── INDEX.md                            # Documentation index
└── QUICKSTART.md                       # Quick start guide
```

**No archives in project root.**

## Migration Script

### What Gets Moved

**To `_data/`:**
```bash
./data/                     → _data/processed/
./output/publications/      → _data/publications/
./full_db_export/           → _data/exports/database/
./materiality_exports/      → _data/exports/materiality/
./test_export/              → _data/temp/test_exports/
./services/data/            → _data/services/  (if needed, or consolidate)
```

**To `docs/archive/`:**
```bash
./archive/                  → docs/archive/code/
./docs/docs_archive/        → docs/archive/old_docs/
./streamlit_old_backup/     → docs/archive/backups/streamlit_old/
```

### What Gets Updated

**`.gitignore`:**
```gitignore
# Data directory (all runtime data)
_data/
!_data/.gitkeep

# Keep structure but ignore contents
_data/processed/
_data/exports/
_data/publications/
_data/temp/

# Legacy paths (for backward compatibility during transition)
data/processed_embeddings/
material_exports/
event_exports/
full_db_export/
embedding_backups/
```

**Code references:**
- Update scripts that reference `./data/` to `_data/processed/`
- Update export scripts to use `_data/exports/`

## Directory Standards

### Data Directory Rules

1. **`_data/processed/`** - Processed data ready for use
2. **`_data/exports/`** - Database/table exports (backup/restore)
3. **`_data/publications/`** - Generated output files
4. **`_data/temp/`** - Temporary files, can be deleted
5. **Never commit `_data/` contents** (add to .gitignore)

### Archive Directory Rules

1. **All archives under `docs/archive/`** only
2. **Categorize by type**: code, docs, backups
3. **Include date/reason** in subdirectory names
4. **No archives in project root**

## Benefits

| Before | After |
|--------|-------|
| 8 data directories scattered | 1 `_data/` directory |
| 4 archive locations | 1 `docs/archive/` |
| Unclear organization | Clear structure |
| Hard to find exports | All in `_data/exports/` |
| Archives in root | No root clutter |

## Implementation

### Automated Script

Run:
```bash
./consolidate_data.sh      # Linux/macOS
.\consolidate_data.ps1     # Windows
```

### Manual Steps

If you prefer manual control:

**Step 1: Create structure**
```bash
mkdir -p _data/{processed/{embeddings,json},exports/{database,embeddings,events,materiality},publications,temp}
mkdir -p docs/archive/{code,old_docs,backups}
```

**Step 2: Move data**
```bash
mv data/* _data/processed/ 2>/dev/null || true
mv output/publications/* _data/publications/ 2>/dev/null || true
mv full_db_export/* _data/exports/database/ 2>/dev/null || true
mv materiality_exports/* _data/exports/materiality/ 2>/dev/null || true
mv test_export/* _data/temp/ 2>/dev/null || true
```

**Step 3: Move archives**
```bash
mv archive/* docs/archive/code/ 2>/dev/null || true
mv docs/docs_archive/* docs/archive/old_docs/ 2>/dev/null || true
mv streamlit_old_backup docs/archive/backups/ 2>/dev/null || true
```

**Step 4: Clean up empty directories**
```bash
rmdir data output archive docs/docs_archive full_db_export materiality_exports test_export streamlit_old_backup 2>/dev/null || true
```

**Step 5: Update .gitignore**
```bash
# Add _data/ to .gitignore
echo "" >> .gitignore
echo "# Consolidated data directory" >> .gitignore
echo "_data/" >> .gitignore
echo "!_data/.gitkeep" >> .gitignore
```

## Code Updates Needed

### Scripts That Reference Data Paths

**Before:**
```python
data_dir = "./data/processed_embeddings"
export_dir = "./full_db_export"
output_dir = "./output/publications"
```

**After:**
```python
data_dir = "./_data/processed/embeddings"
export_dir = "./_data/exports/database"
output_dir = "./_data/publications"
```

**Files to check:**
- `services/pipeline/embeddings/load_embeddings.py`
- `services/pipeline/embeddings/export_embeddings.py`
- `services/pipeline/events/export_event_tables.py`
- `services/pipeline/events/export_materiality_scores.py`
- Any scripts with hardcoded paths

## Validation

After consolidation:

**Check structure:**
```bash
tree _data -L 2
tree docs/archive -L 2
```

**Verify no root archives:**
```bash
ls -la | grep -i archive
# Should return nothing
```

**Test exports:**
```bash
python services/pipeline/events/export_event_tables.py --output-dir _data/exports/events
```

## Rollback

All original directories preserved until you manually delete them:

```bash
# If something breaks, originals are still there
ls -la data/
ls -la archive/

# Revert
rm -rf _data
rm -rf docs/archive/code docs/archive/old_docs
```

## Next Steps

1. Review this plan
2. Run consolidation script
3. Update code references
4. Test exports work
5. Delete old empty directories
6. Commit changes
