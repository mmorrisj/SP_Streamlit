#!/bin/bash
# Consolidate Data & Archive Directories
# This script moves all scattered data and archives into organized locations

set -e

echo ""
echo "========================================="
echo "Data & Archive Consolidation"
echo "========================================="
echo ""
echo "This script will:"
echo "  1. Create _data/ directory for all runtime data"
echo "  2. Consolidate scattered data directories"
echo "  3. Move all archives to docs/archive/"
echo "  4. Clean up empty directories"
echo "  5. Update .gitignore"
echo ""
read -p "Proceed with consolidation? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Step 1: Create directory structure
echo ""
echo "[1/5] Creating directory structure..."
mkdir -p _data/processed/embeddings
mkdir -p _data/processed/json
mkdir -p _data/exports/database
mkdir -p _data/exports/embeddings
mkdir -p _data/exports/events
mkdir -p _data/exports/materiality
mkdir -p _data/publications
mkdir -p _data/temp
mkdir -p docs/archive/code
mkdir -p docs/archive/old_docs
mkdir -p docs/archive/backups

echo "  ✓ Created _data/ structure"
echo "  ✓ Created docs/archive/ structure"

# Step 2: Move data directories
echo ""
echo "[2/5] Consolidating data directories..."

# Move processed data
if [ -d "data" ]; then
    if [ -d "data/processed_embeddings" ]; then
        mv data/processed_embeddings/* _data/processed/embeddings/ 2>/dev/null || true
        echo "  ✓ Moved data/processed_embeddings/ → _data/processed/embeddings/"
    fi
    if [ -d "data/processed" ]; then
        mv data/processed/* _data/processed/json/ 2>/dev/null || true
        echo "  ✓ Moved data/processed/ → _data/processed/json/"
    fi
    # Move any other files in data/
    find data -maxdepth 1 -type f -exec mv {} _data/processed/ \; 2>/dev/null || true
fi

# Move publications
if [ -d "output/publications" ]; then
    mv output/publications/* _data/publications/ 2>/dev/null || true
    echo "  ✓ Moved output/publications/ → _data/publications/"
fi

# Move database exports
if [ -d "full_db_export" ]; then
    mv full_db_export/* _data/exports/database/ 2>/dev/null || true
    echo "  ✓ Moved full_db_export/ → _data/exports/database/"
fi

# Move materiality exports
if [ -d "materiality_exports" ]; then
    mv materiality_exports/* _data/exports/materiality/ 2>/dev/null || true
    echo "  ✓ Moved materiality_exports/ → _data/exports/materiality/"
fi

# Move test exports
if [ -d "test_export" ]; then
    mv test_export/* _data/temp/ 2>/dev/null || true
    echo "  ✓ Moved test_export/ → _data/temp/"
fi

# Move services/data if it exists
if [ -d "services/data" ]; then
    mkdir -p _data/services
    mv services/data/* _data/services/ 2>/dev/null || true
    echo "  ✓ Moved services/data/ → _data/services/"
fi

# Step 3: Move archive directories
echo ""
echo "[3/5] Consolidating archive directories..."

# Move root archive (old code)
if [ -d "archive" ]; then
    mv archive/* docs/archive/code/ 2>/dev/null || true
    echo "  ✓ Moved archive/ → docs/archive/code/"
fi

# Move docs/docs_archive (old docs)
if [ -d "docs/docs_archive" ]; then
    mv docs/docs_archive/* docs/archive/old_docs/ 2>/dev/null || true
    echo "  ✓ Moved docs/docs_archive/ → docs/archive/old_docs/"
fi

# Move old Streamlit backup
if [ -d "streamlit_old_backup" ]; then
    mv streamlit_old_backup docs/archive/backups/streamlit_old 2>/dev/null || true
    echo "  ✓ Moved streamlit_old_backup/ → docs/archive/backups/streamlit_old/"
fi

# Step 4: Clean up empty directories
echo ""
echo "[4/5] Cleaning up empty directories..."

# Remove empty directories
for dir in data output archive full_db_export materiality_exports test_export streamlit_old_backup docs/docs_archive services/data; do
    if [ -d "$dir" ]; then
        # Check if directory is empty
        if [ -z "$(ls -A $dir 2>/dev/null)" ]; then
            rmdir "$dir" 2>/dev/null && echo "  ✓ Removed empty directory: $dir" || true
        else
            echo "  ⚠ Directory not empty (review manually): $dir"
        fi
    fi
done

# Step 5: Update .gitignore
echo ""
echo "[5/5] Updating .gitignore..."

# Check if _data/ is already in .gitignore
if ! grep -q "^_data/" .gitignore 2>/dev/null; then
    cat >> .gitignore << 'EOF'

# Consolidated data directory (all runtime data)
_data/
!_data/.gitkeep
!_data/*/.gitkeep
EOF
    echo "  ✓ Added _data/ to .gitignore"
else
    echo "  ✓ _data/ already in .gitignore"
fi

# Create .gitkeep files to preserve structure
touch _data/.gitkeep
touch _data/processed/.gitkeep
touch _data/exports/.gitkeep
touch _data/publications/.gitkeep
touch _data/temp/.gitkeep

echo ""
echo "========================================="
echo "Consolidation Complete!"
echo "========================================="
echo ""
echo "Summary:"
echo "  ✓ All data consolidated in _data/"
echo "  ✓ All archives consolidated in docs/archive/"
echo "  ✓ Empty directories cleaned up"
echo "  ✓ .gitignore updated"
echo ""
echo "New structure:"
echo "  _data/"
echo "    ├── processed/        # Processed data"
echo "    ├── exports/          # All exports"
echo "    ├── publications/     # Generated files"
echo "    └── temp/             # Temporary files"
echo ""
echo "  docs/archive/"
echo "    ├── code/             # Old Python scripts"
echo "    ├── old_docs/         # Old documentation"
echo "    ├── deprecated/       # Deprecated proposals"
echo "    ├── migration_guides/ # Migration docs"
echo "    ├── legacy_deployment/# Old deployment"
echo "    ├── analysis_reports/ # Historical reports"
echo "    └── backups/          # Old backups"
echo ""
echo "Next steps:"
echo "  1. Review _data/ and docs/archive/ directories"
echo "  2. Update code references to use _data/ paths"
echo "  3. Test exports work correctly"
echo "  4. Delete any remaining empty directories"
echo "  5. Commit changes to git"
echo ""
