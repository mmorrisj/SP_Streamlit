# Update Data Path References
# This script updates all hardcoded paths to use the new _data/ structure

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Updating Data Path References" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "This script will update hardcoded paths in:" -ForegroundColor Cyan
Write-Host "  - Embedding scripts"
Write-Host "  - Event export/import scripts"
Write-Host "  - Publication scripts"
Write-Host "  - Migration scripts"
Write-Host ""
$response = Read-Host "Proceed with path updates? [y/N]"
if ($response -ne 'y' -and $response -ne 'Y') {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

# Function to replace text in file
function Replace-InFile {
    param($FilePath, $OldText, $NewText)
    if (Test-Path $FilePath) {
        $content = Get-Content $FilePath -Raw
        $content = $content -replace [regex]::Escape($OldText), $NewText
        Set-Content $FilePath $content -NoNewline
        return $true
    }
    return $false
}

Write-Host ""
Write-Host "[1/4] Updating embedding script paths..." -ForegroundColor Blue

# load_embeddings.py
if (Replace-InFile "services\pipeline\embeddings\load_embeddings.py" "data/processed_embeddings" "_data/processed/embeddings") {
    Write-Host "  ✓ Updated load_embeddings.py" -ForegroundColor Green
}

# load_embeddings_by_docid.py
if (Replace-InFile "services\pipeline\embeddings\load_embeddings_by_docid.py" "./data/processed_embeddings" "./_data/processed/embeddings") {
    Write-Host "  ✓ Updated load_embeddings_by_docid.py" -ForegroundColor Green
}

# s3_to_pgvector.py
if (Replace-InFile "services\pipeline\embeddings\s3_to_pgvector.py" "./data/processed_embeddings" "./_data/processed/embeddings") {
    Write-Host "  ✓ Updated s3_to_pgvector.py" -ForegroundColor Green
}

# export_embeddings.py
if (Test-Path "services\pipeline\embeddings\export_embeddings.py") {
    Replace-InFile "services\pipeline\embeddings\export_embeddings.py" "'./embedding_exports'" "'./_data/exports/embeddings'" | Out-Null
    Replace-InFile "services\pipeline\embeddings\export_embeddings.py" "./embedding_exports" "./_data/exports/embeddings" | Out-Null
    Write-Host "  ✓ Updated export_embeddings.py" -ForegroundColor Green
}

Write-Host ""
Write-Host "[2/4] Updating event script paths..." -ForegroundColor Blue

# export_event_tables.py
if (Replace-InFile "services\pipeline\events\export_event_tables.py" "default='./event_exports'" "default='./_data/exports/events'") {
    Write-Host "  ✓ Updated export_event_tables.py" -ForegroundColor Green
}

# import_event_tables.py
if (Replace-InFile "services\pipeline\events\import_event_tables.py" "./event_exports" "./_data/exports/events") {
    Write-Host "  ✓ Updated import_event_tables.py" -ForegroundColor Green
}

# export_materiality_scores.py
if (Replace-InFile "services\pipeline\events\export_materiality_scores.py" "default='./materiality_exports'" "default='./_data/exports/materiality'") {
    Write-Host "  ✓ Updated export_materiality_scores.py" -ForegroundColor Green
}

# import_materiality_scores.py
if (Replace-InFile "services\pipeline\events\import_materiality_scores.py" "./materiality_exports" "./_data/exports/materiality") {
    Write-Host "  ✓ Updated import_materiality_scores.py" -ForegroundColor Green
}

Write-Host ""
Write-Host "[3/4] Updating publication script paths..." -ForegroundColor Blue

# export_monthly_publications_docx.py
if (Test-Path "services\pipeline\summaries\export_monthly_publications_docx.py") {
    Replace-InFile "services\pipeline\summaries\export_monthly_publications_docx.py" "'output/publications'" "'_data/publications'" | Out-Null
    Replace-InFile "services\pipeline\summaries\export_monthly_publications_docx.py" "output/publications" "_data/publications" | Out-Null
    Write-Host "  ✓ Updated export_monthly_publications_docx.py" -ForegroundColor Green
}

# export_publication_template_docx.py
if (Test-Path "services\pipeline\summaries\export_publication_template_docx.py") {
    Replace-InFile "services\pipeline\summaries\export_publication_template_docx.py" "'output/publications'" "'_data/publications'" | Out-Null
    Replace-InFile "services\pipeline\summaries\export_publication_template_docx.py" "output/publications" "_data/publications" | Out-Null
    Write-Host "  ✓ Updated export_publication_template_docx.py" -ForegroundColor Green
}

# generate_monthly_summary_publications.py
if (Test-Path "services\pipeline\summaries\generate_monthly_summary_publications.py") {
    Replace-InFile "services\pipeline\summaries\generate_monthly_summary_publications.py" "'output/publications'" "'_data/publications'" | Out-Null
    Replace-InFile "services\pipeline\summaries\generate_monthly_summary_publications.py" "output/publications" "_data/publications" | Out-Null
    Write-Host "  ✓ Updated generate_monthly_summary_publications.py" -ForegroundColor Green
}

Write-Host ""
Write-Host "[4/4] Updating migration script paths..." -ForegroundColor Blue

# export_full_database.py
if (Test-Path "services\pipeline\migrations\export_full_database.py") {
    Replace-InFile "services\pipeline\migrations\export_full_database.py" "'full_db_export/'" "'exports/database/'" | Out-Null
    Replace-InFile "services\pipeline\migrations\export_full_database.py" "full_db_export/" "exports/database/" | Out-Null
    Write-Host "  ✓ Updated export_full_database.py" -ForegroundColor Green
}

# import_full_database.py
if (Test-Path "services\pipeline\migrations\import_full_database.py") {
    Replace-InFile "services\pipeline\migrations\import_full_database.py" "'full_db_export/'" "'exports/database/'" | Out-Null
    Replace-InFile "services\pipeline\migrations\import_full_database.py" "full_db_export/" "exports/database/" | Out-Null
    Write-Host "  ✓ Updated import_full_database.py" -ForegroundColor Green
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Path Updates Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  ✓ Updated embedding script paths to _data\processed\embeddings\"
Write-Host "  ✓ Updated event export paths to _data\exports\events\"
Write-Host "  ✓ Updated materiality export paths to _data\exports\materiality\"
Write-Host "  ✓ Updated publication paths to _data\publications\"
Write-Host "  ✓ Updated migration S3 paths to exports\database\"
Write-Host ""
Write-Host "Verification:" -ForegroundColor Yellow
Write-Host "  Run: Get-ChildItem -Path services\ -Recurse -Filter *.py | Select-String 'data/processed_embeddings'"
Write-Host "  (Should return nothing)"
Write-Host ""
Write-Host "Testing:" -ForegroundColor Yellow
Write-Host "  python services\pipeline\embeddings\load_embeddings.py --help"
Write-Host "  python services\pipeline\events\export_event_tables.py --help"
Write-Host "  python services\pipeline\summaries\generate_monthly_summary_publications.py --help"
Write-Host ""
