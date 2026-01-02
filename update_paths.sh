#!/bin/bash
# Update Data Path References
# This script updates all hardcoded paths to use the new _data/ structure

set -e

echo ""
echo "========================================="
echo "Updating Data Path References"
echo "========================================="
echo ""
echo "This script will update hardcoded paths in:"
echo "  - Embedding scripts"
echo "  - Event export/import scripts"
echo "  - Publication scripts"
echo "  - Migration scripts"
echo ""
read -p "Proceed with path updates? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "[1/4] Updating embedding script paths..."

# load_embeddings.py
if [ -f "services/pipeline/embeddings/load_embeddings.py" ]; then
    sed -i 's|data/processed_embeddings|_data/processed/embeddings|g' services/pipeline/embeddings/load_embeddings.py
    echo "  ✓ Updated load_embeddings.py"
fi

# load_embeddings_by_docid.py
if [ -f "services/pipeline/embeddings/load_embeddings_by_docid.py" ]; then
    sed -i 's|./data/processed_embeddings|./_data/processed/embeddings|g' services/pipeline/embeddings/load_embeddings_by_docid.py
    echo "  ✓ Updated load_embeddings_by_docid.py"
fi

# s3_to_pgvector.py
if [ -f "services/pipeline/embeddings/s3_to_pgvector.py" ]; then
    sed -i 's|./data/processed_embeddings|./_data/processed/embeddings|g' services/pipeline/embeddings/s3_to_pgvector.py
    echo "  ✓ Updated s3_to_pgvector.py"
fi

# export_embeddings.py
if [ -f "services/pipeline/embeddings/export_embeddings.py" ]; then
    sed -i "s|'./embedding_exports'|'./_data/exports/embeddings'|g" services/pipeline/embeddings/export_embeddings.py
    sed -i 's|./embedding_exports|./_data/exports/embeddings|g' services/pipeline/embeddings/export_embeddings.py
    echo "  ✓ Updated export_embeddings.py"
fi

echo ""
echo "[2/4] Updating event script paths..."

# export_event_tables.py
if [ -f "services/pipeline/events/export_event_tables.py" ]; then
    sed -i "s|default='./event_exports'|default='./_data/exports/events'|g" services/pipeline/events/export_event_tables.py
    echo "  ✓ Updated export_event_tables.py"
fi

# import_event_tables.py
if [ -f "services/pipeline/events/import_event_tables.py" ]; then
    sed -i 's|./event_exports|./_data/exports/events|g' services/pipeline/events/import_event_tables.py
    echo "  ✓ Updated import_event_tables.py"
fi

# export_materiality_scores.py
if [ -f "services/pipeline/events/export_materiality_scores.py" ]; then
    sed -i "s|default='./materiality_exports'|default='./_data/exports/materiality'|g" services/pipeline/events/export_materiality_scores.py
    echo "  ✓ Updated export_materiality_scores.py"
fi

# import_materiality_scores.py
if [ -f "services/pipeline/events/import_materiality_scores.py" ]; then
    sed -i 's|./materiality_exports|./_data/exports/materiality|g' services/pipeline/events/import_materiality_scores.py
    echo "  ✓ Updated import_materiality_scores.py"
fi

echo ""
echo "[3/4] Updating publication script paths..."

# export_monthly_publications_docx.py
if [ -f "services/pipeline/summaries/export_monthly_publications_docx.py" ]; then
    sed -i "s|'output/publications'|'_data/publications'|g" services/pipeline/summaries/export_monthly_publications_docx.py
    sed -i 's|output/publications|_data/publications|g' services/pipeline/summaries/export_monthly_publications_docx.py
    echo "  ✓ Updated export_monthly_publications_docx.py"
fi

# export_publication_template_docx.py
if [ -f "services/pipeline/summaries/export_publication_template_docx.py" ]; then
    sed -i "s|'output/publications'|'_data/publications'|g" services/pipeline/summaries/export_publication_template_docx.py
    sed -i 's|output/publications|_data/publications|g' services/pipeline/summaries/export_publication_template_docx.py
    echo "  ✓ Updated export_publication_template_docx.py"
fi

# generate_monthly_summary_publications.py
if [ -f "services/pipeline/summaries/generate_monthly_summary_publications.py" ]; then
    sed -i "s|'output/publications'|'_data/publications'|g" services/pipeline/summaries/generate_monthly_summary_publications.py
    sed -i 's|output/publications|_data/publications|g' services/pipeline/summaries/generate_monthly_summary_publications.py
    echo "  ✓ Updated generate_monthly_summary_publications.py"
fi

echo ""
echo "[4/4] Updating migration script paths..."

# export_full_database.py
if [ -f "services/pipeline/migrations/export_full_database.py" ]; then
    sed -i "s|'full_db_export/'|'exports/database/'|g" services/pipeline/migrations/export_full_database.py
    sed -i 's|full_db_export/|exports/database/|g' services/pipeline/migrations/export_full_database.py
    echo "  ✓ Updated export_full_database.py"
fi

# import_full_database.py
if [ -f "services/pipeline/migrations/import_full_database.py" ]; then
    sed -i "s|'full_db_export/'|'exports/database/'|g" services/pipeline/migrations/import_full_database.py
    sed -i 's|full_db_export/|exports/database/|g' services/pipeline/migrations/import_full_database.py
    echo "  ✓ Updated import_full_database.py"
fi

echo ""
echo "========================================="
echo "Path Updates Complete!"
echo "========================================="
echo ""
echo "Summary:"
echo "  ✓ Updated embedding script paths to _data/processed/embeddings/"
echo "  ✓ Updated event export paths to _data/exports/events/"
echo "  ✓ Updated materiality export paths to _data/exports/materiality/"
echo "  ✓ Updated publication paths to _data/publications/"
echo "  ✓ Updated migration S3 paths to exports/database/"
echo ""
echo "Verification:"
echo "  Run: grep -r 'data/processed_embeddings' services/ --include='*.py'"
echo "  (Should return nothing)"
echo ""
echo "Testing:"
echo "  python services/pipeline/embeddings/load_embeddings.py --help"
echo "  python services/pipeline/events/export_event_tables.py --help"
echo "  python services/pipeline/summaries/generate_monthly_summary_publications.py --help"
echo ""
