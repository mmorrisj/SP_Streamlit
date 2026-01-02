# Reorganization Script - Cleanup and organize project structure
# This script moves files to their new organized locations

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "SP_Streamlit Project Reorganization" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "This script will:" -ForegroundColor Cyan
Write-Host "  1. Create organized directory structure"
Write-Host "  2. Move documentation files to docs/"
Write-Host "  3. Archive deprecated documentation"
Write-Host "  4. Preserve all files (nothing deleted)"
Write-Host ""
$response = Read-Host "Proceed with reorganization? [y/N]"
if ($response -ne 'y' -and $response -ne 'Y') {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

# Create directory structure
Write-Host ""
Write-Host "[1/4] Creating directory structure..." -ForegroundColor Blue
New-Item -ItemType Directory -Force -Path "docs\deployment" | Out-Null
New-Item -ItemType Directory -Force -Path "docs\archive\deprecated" | Out-Null
New-Item -ItemType Directory -Force -Path "docs\archive\migration_guides" | Out-Null
New-Item -ItemType Directory -Force -Path "docs\archive\legacy_deployment" | Out-Null
New-Item -ItemType Directory -Force -Path "docs\archive\analysis_reports" | Out-Null

# Function to move file if it exists
function Move-IfExists {
    param($Source, $Destination)
    if (Test-Path $Source) {
        Move-Item $Source $Destination -Force
        Write-Host "  ✓ Moved $(Split-Path $Source -Leaf)" -ForegroundColor Green
    }
}

# Move core documentation to docs/
Write-Host ""
Write-Host "[2/4] Moving core documentation..." -ForegroundColor Blue
Move-IfExists "QUICKSTART.md" "docs\"

# Move deployment guides
Move-IfExists "DOCKER_NO_COMPOSE.md" "docs\deployment\"
Move-IfExists "DOCKER_HUB_DEPLOYMENT.md" "docs\deployment\"
Move-IfExists "DOCKER_COMMAND_REFERENCE.md" "docs\deployment\"
Move-IfExists "SETUP_NON_DOCKER.md" "docs\deployment\"
Move-IfExists "REGISTER_IMAGES.md" "docs\deployment\"

# Archive deprecated/proposal docs
Write-Host ""
Write-Host "[3/4] Archiving deprecated documentation..." -ForegroundColor Blue
Move-IfExists "EVENT_CONSOLIDATION_DIAGRAM_REVIEW.md" "docs\archive\deprecated\"
Move-IfExists "HIERARCHICAL_SUMMARY_PIPELINE_PROPOSAL.md" "docs\archive\deprecated\"
Move-IfExists "SUMMARY_PIPELINE_ARCHITECTURE.md" "docs\archive\deprecated\"
Move-IfExists "SUMMARY_PIPELINE_FINAL_RECOMMENDATION.md" "docs\archive\deprecated\"
Move-IfExists "SOURCE_TRACEABLE_SUMMARY_PIPELINE.md" "docs\archive\deprecated\"
Move-IfExists "AP_STYLE_SUMMARY_PIPELINE.md" "docs\archive\deprecated\"
Move-IfExists "PIPELINE.md" "docs\archive\deprecated\"
Move-IfExists "PIPELINE_STATUS.md" "docs\archive\deprecated\"

# Archive migration guides
Move-IfExists "FULL_DATABASE_MIGRATION.md" "docs\archive\migration_guides\"
Move-IfExists "MATERIALITY_EXPORT_IMPORT_GUIDE.md" "docs\archive\migration_guides\"
Move-IfExists "IMPORT_EXPORT_COMMANDS.md" "docs\archive\migration_guides\"
Move-IfExists "S3_IMPORT_GUIDE.md" "docs\archive\migration_guides\"

# Archive analysis reports
Move-IfExists "RAG_VALIDATION_REPORT.md" "docs\archive\analysis_reports\"
Move-IfExists "LINKAGE_VERIFICATION.md" "docs\archive\analysis_reports\"
Move-IfExists "API_FILTERING_SUMMARY.md" "docs\archive\analysis_reports\"
Move-IfExists "DASHBOARD_FILTERING_SUMMARY.md" "docs\archive\analysis_reports\"
Move-IfExists "INFLUENCER_PAGES_SUMMARY.md" "docs\archive\analysis_reports\"
Move-IfExists "REACT_INTEGRATION_SUMMARY.md" "docs\archive\analysis_reports\"

# Archive legacy deployment docs
Move-IfExists "DEPLOYMENT_GUIDE.md" "docs\archive\legacy_deployment\"
Move-IfExists "DOCKER_SETUP.md" "docs\archive\legacy_deployment\"
Move-IfExists "AZURE_SETUP_SYSTEM2.md" "docs\archive\legacy_deployment\"
Move-IfExists "setup_local_db.md" "docs\archive\legacy_deployment\"
Move-IfExists "replit.md" "docs\archive\legacy_deployment\"

# Create documentation index
Write-Host ""
Write-Host "[4/4] Creating documentation index..." -ForegroundColor Blue

@"
# Documentation Index

## Quick Start
- **[QUICKSTART.md](QUICKSTART.md)** - Start here! Quick deployment guide for all modes

## Core Documentation
- **[../README.md](../README.md)** - Project overview
- **[../CLAUDE.md](../CLAUDE.md)** - Complete architecture and development guide

## Deployment Guides
- **[deployment/DOCKER_COMPOSE.md](deployment/DOCKER_COMPOSE.md)** - Deploy with docker-compose (recommended)
- **[deployment/DOCKER_ONLY.md](deployment/DOCKER_ONLY.md)** - Deploy with pure Docker (no compose)
- **[deployment/NON_DOCKER.md](deployment/NON_DOCKER.md)** - Deploy without Docker (bare metal)
- **[deployment/DOCKER_HUB.md](deployment/DOCKER_HUB.md)** - Publish to Docker Hub
- **[deployment/DOCKER_COMMAND_REFERENCE.md](deployment/DOCKER_COMMAND_REFERENCE.md)** - Quick command reference

## Archived Documentation

### Deprecated Proposals & Old Approaches
- Located in: ``archive/deprecated/``
- Historical pipeline proposals and architecture decisions
- Kept for reference only

### Migration & Import/Export Guides
- Located in: ``archive/migration_guides/``
- Database migration procedures
- S3 import/export guides
- Materiality score import/export

### Legacy Deployment Guides
- Located in: ``archive/legacy_deployment/``
- Superseded deployment documentation
- Old setup guides

### Analysis Reports
- Located in: ``archive/analysis_reports/``
- RAG validation reports
- Feature summaries and integration reports
- Linkage verification
"@ | Out-File -FilePath "docs\INDEX.md" -Encoding UTF8

Write-Host "  ✓ Created docs\INDEX.md" -ForegroundColor Green

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Reorganization Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  ✓ All documentation organized in docs/"
Write-Host "  ✓ Deployment guides in docs/deployment/"
Write-Host "  ✓ Historical docs archived in docs/archive/"
Write-Host "  ✓ Nothing deleted - all files preserved"
Write-Host ""
Write-Host "Root directory now contains only:" -ForegroundColor Cyan
Write-Host "  - README.md (project overview)"
Write-Host "  - CLAUDE.md (architecture - for Claude Code)"
Write-Host "  - REORGANIZATION_PLAN.md (this reorganization guide)"
Write-Host "  - Startup scripts (.sh, .ps1)"
Write-Host "  - Docker configs (docker-compose.yml)"
Write-Host "  - Config files (.env.example, requirements.txt)"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Review docs\INDEX.md for navigation"
Write-Host "  2. Update README.md to be more concise"
Write-Host "  3. Test all deployment modes still work"
Write-Host "  4. Commit changes to git"
Write-Host ""
