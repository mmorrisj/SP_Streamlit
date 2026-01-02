# Consolidate Data & Archive Directories
# This script moves all scattered data and archives into organized locations

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Data & Archive Consolidation" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "This script will:" -ForegroundColor Cyan
Write-Host "  1. Create _data/ directory for all runtime data"
Write-Host "  2. Consolidate scattered data directories"
Write-Host "  3. Move all archives to docs/archive/"
Write-Host "  4. Clean up empty directories"
Write-Host "  5. Update .gitignore"
Write-Host ""
$response = Read-Host "Proceed with consolidation? [y/N]"
if ($response -ne 'y' -and $response -ne 'Y') {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

# Step 1: Create directory structure
Write-Host ""
Write-Host "[1/5] Creating directory structure..." -ForegroundColor Blue
New-Item -ItemType Directory -Force -Path "_data\processed\embeddings" | Out-Null
New-Item -ItemType Directory -Force -Path "_data\processed\json" | Out-Null
New-Item -ItemType Directory -Force -Path "_data\exports\database" | Out-Null
New-Item -ItemType Directory -Force -Path "_data\exports\embeddings" | Out-Null
New-Item -ItemType Directory -Force -Path "_data\exports\events" | Out-Null
New-Item -ItemType Directory -Force -Path "_data\exports\materiality" | Out-Null
New-Item -ItemType Directory -Force -Path "_data\publications" | Out-Null
New-Item -ItemType Directory -Force -Path "_data\temp" | Out-Null
New-Item -ItemType Directory -Force -Path "docs\archive\code" | Out-Null
New-Item -ItemType Directory -Force -Path "docs\archive\old_docs" | Out-Null
New-Item -ItemType Directory -Force -Path "docs\archive\backups" | Out-Null

Write-Host "  ✓ Created _data\ structure" -ForegroundColor Green
Write-Host "  ✓ Created docs\archive\ structure" -ForegroundColor Green

# Function to move files if source exists
function Move-FilesIfExists {
    param($Source, $Destination, $Description)
    if (Test-Path $Source) {
        $items = Get-ChildItem -Path $Source -ErrorAction SilentlyContinue
        if ($items) {
            $items | Move-Item -Destination $Destination -Force -ErrorAction SilentlyContinue
            Write-Host "  ✓ $Description" -ForegroundColor Green
        }
    }
}

# Step 2: Move data directories
Write-Host ""
Write-Host "[2/5] Consolidating data directories..." -ForegroundColor Blue

# Move processed data
Move-FilesIfExists "data\processed_embeddings\*" "_data\processed\embeddings\" "Moved data\processed_embeddings\ → _data\processed\embeddings\"
Move-FilesIfExists "data\processed\*" "_data\processed\json\" "Moved data\processed\ → _data\processed\json\"

# Move any other files in data/
if (Test-Path "data") {
    Get-ChildItem -Path "data" -File -ErrorAction SilentlyContinue | Move-Item -Destination "_data\processed\" -Force -ErrorAction SilentlyContinue
}

# Move publications
Move-FilesIfExists "output\publications\*" "_data\publications\" "Moved output\publications\ → _data\publications\"

# Move database exports
Move-FilesIfExists "full_db_export\*" "_data\exports\database\" "Moved full_db_export\ → _data\exports\database\"

# Move materiality exports
Move-FilesIfExists "materiality_exports\*" "_data\exports\materiality\" "Moved materiality_exports\ → _data\exports\materiality\"

# Move test exports
Move-FilesIfExists "test_export\*" "_data\temp\" "Moved test_export\ → _data\temp\"

# Move services/data if it exists
if (Test-Path "services\data") {
    New-Item -ItemType Directory -Force -Path "_data\services" | Out-Null
    Move-FilesIfExists "services\data\*" "_data\services\" "Moved services\data\ → _data\services\"
}

# Step 3: Move archive directories
Write-Host ""
Write-Host "[3/5] Consolidating archive directories..." -ForegroundColor Blue

# Move root archive (old code)
Move-FilesIfExists "archive\*" "docs\archive\code\" "Moved archive\ → docs\archive\code\"

# Move docs/docs_archive (old docs)
Move-FilesIfExists "docs\docs_archive\*" "docs\archive\old_docs\" "Moved docs\docs_archive\ → docs\archive\old_docs\"

# Move old Streamlit backup
if (Test-Path "streamlit_old_backup") {
    Move-Item "streamlit_old_backup" "docs\archive\backups\streamlit_old" -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Moved streamlit_old_backup\ → docs\archive\backups\streamlit_old\" -ForegroundColor Green
}

# Step 4: Clean up empty directories
Write-Host ""
Write-Host "[4/5] Cleaning up empty directories..." -ForegroundColor Blue

$dirsToClean = @("data", "output", "archive", "full_db_export", "materiality_exports", "test_export", "streamlit_old_backup", "docs\docs_archive", "services\data")

foreach ($dir in $dirsToClean) {
    if (Test-Path $dir) {
        $items = Get-ChildItem -Path $dir -Force -ErrorAction SilentlyContinue
        if (-not $items) {
            Remove-Item $dir -Force -ErrorAction SilentlyContinue
            Write-Host "  ✓ Removed empty directory: $dir" -ForegroundColor Green
        } else {
            Write-Host "  ⚠ Directory not empty (review manually): $dir" -ForegroundColor Yellow
        }
    }
}

# Step 5: Update .gitignore
Write-Host ""
Write-Host "[5/5] Updating .gitignore..." -ForegroundColor Blue

$gitignoreContent = Get-Content .gitignore -ErrorAction SilentlyContinue
if (-not ($gitignoreContent -match "^_data/")) {
    Add-Content .gitignore "`n# Consolidated data directory (all runtime data)`n_data/`n!_data/.gitkeep`n!_data/*/.gitkeep"
    Write-Host "  ✓ Added _data/ to .gitignore" -ForegroundColor Green
} else {
    Write-Host "  ✓ _data/ already in .gitignore" -ForegroundColor Green
}

# Create .gitkeep files to preserve structure
New-Item -ItemType File -Force -Path "_data\.gitkeep" | Out-Null
New-Item -ItemType File -Force -Path "_data\processed\.gitkeep" | Out-Null
New-Item -ItemType File -Force -Path "_data\exports\.gitkeep" | Out-Null
New-Item -ItemType File -Force -Path "_data\publications\.gitkeep" | Out-Null
New-Item -ItemType File -Force -Path "_data\temp\.gitkeep" | Out-Null

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Consolidation Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  ✓ All data consolidated in _data\"
Write-Host "  ✓ All archives consolidated in docs\archive\"
Write-Host "  ✓ Empty directories cleaned up"
Write-Host "  ✓ .gitignore updated"
Write-Host ""
Write-Host "New structure:" -ForegroundColor Cyan
Write-Host "  _data\"
Write-Host "    ├── processed\        # Processed data"
Write-Host "    ├── exports\          # All exports"
Write-Host "    ├── publications\     # Generated files"
Write-Host "    └── temp\             # Temporary files"
Write-Host ""
Write-Host "  docs\archive\"
Write-Host "    ├── code\             # Old Python scripts"
Write-Host "    ├── old_docs\         # Old documentation"
Write-Host "    ├── deprecated\       # Deprecated proposals"
Write-Host "    ├── migration_guides\ # Migration docs"
Write-Host "    ├── legacy_deployment\# Old deployment"
Write-Host "    ├── analysis_reports\ # Historical reports"
Write-Host "    └── backups\          # Old backups"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Review _data\ and docs\archive\ directories"
Write-Host "  2. Update code references to use _data\ paths"
Write-Host "  3. Test exports work correctly"
Write-Host "  4. Delete any remaining empty directories"
Write-Host "  5. Commit changes to git"
Write-Host ""
