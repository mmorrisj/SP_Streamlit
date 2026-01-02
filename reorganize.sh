#!/bin/bash
# Reorganization Script - Cleanup and organize project structure
# This script moves files to their new organized locations

set -e

echo "========================================="
echo "SP_Streamlit Project Reorganization"
echo "========================================="
echo ""
echo "This script will:"
echo "  1. Create organized directory structure"
echo "  2. Move documentation files to docs/"
echo "  3. Archive deprecated documentation"
echo "  4. Preserve all files (nothing deleted)"
echo ""
read -p "Proceed with reorganization? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Create directory structure
echo ""
echo "[1/4] Creating directory structure..."
mkdir -p docs/deployment
mkdir -p docs/archive/deprecated
mkdir -p docs/archive/migration_guides
mkdir -p docs/archive/legacy_deployment
mkdir -p docs/archive/analysis_reports

# Move core documentation to docs/
echo ""
echo "[2/4] Moving core documentation..."

# Keep at root: README.md, .env.example, requirements.txt, docker-compose files
# Move these to docs/:
[ -f "QUICKSTART.md" ] && mv QUICKSTART.md docs/ && echo "  ✓ Moved QUICKSTART.md"

# Move deployment guides
[ -f "DOCKER_NO_COMPOSE.md" ] && mv DOCKER_NO_COMPOSE.md docs/deployment/ && echo "  ✓ Moved DOCKER_NO_COMPOSE.md"
[ -f "DOCKER_HUB_DEPLOYMENT.md" ] && mv DOCKER_HUB_DEPLOYMENT.md docs/deployment/ && echo "  ✓ Moved DOCKER_HUB_DEPLOYMENT.md"
[ -f "DOCKER_COMMAND_REFERENCE.md" ] && mv DOCKER_COMMAND_REFERENCE.md docs/deployment/ && echo "  ✓ Moved DOCKER_COMMAND_REFERENCE.md"
[ -f "SETUP_NON_DOCKER.md" ] && mv SETUP_NON_DOCKER.md docs/deployment/ && echo "  ✓ Moved SETUP_NON_DOCKER.md"
[ -f "REGISTER_IMAGES.md" ] && mv REGISTER_IMAGES.md docs/deployment/ && echo "  ✓ Moved REGISTER_IMAGES.md"

# Archive deprecated/proposal docs
echo ""
echo "[3/4] Archiving deprecated documentation..."
[ -f "EVENT_CONSOLIDATION_DIAGRAM_REVIEW.md" ] && mv EVENT_CONSOLIDATION_DIAGRAM_REVIEW.md docs/archive/deprecated/ && echo "  ✓ Archived EVENT_CONSOLIDATION_DIAGRAM_REVIEW.md"
[ -f "HIERARCHICAL_SUMMARY_PIPELINE_PROPOSAL.md" ] && mv HIERARCHICAL_SUMMARY_PIPELINE_PROPOSAL.md docs/archive/deprecated/ && echo "  ✓ Archived HIERARCHICAL_SUMMARY_PIPELINE_PROPOSAL.md"
[ -f "SUMMARY_PIPELINE_ARCHITECTURE.md" ] && mv SUMMARY_PIPELINE_ARCHITECTURE.md docs/archive/deprecated/ && echo "  ✓ Archived SUMMARY_PIPELINE_ARCHITECTURE.md"
[ -f "SUMMARY_PIPELINE_FINAL_RECOMMENDATION.md" ] && mv SUMMARY_PIPELINE_FINAL_RECOMMENDATION.md docs/archive/deprecated/ && echo "  ✓ Archived SUMMARY_PIPELINE_FINAL_RECOMMENDATION.md"
[ -f "SOURCE_TRACEABLE_SUMMARY_PIPELINE.md" ] && mv SOURCE_TRACEABLE_SUMMARY_PIPELINE.md docs/archive/deprecated/ && echo "  ✓ Archived SOURCE_TRACEABLE_SUMMARY_PIPELINE.md"
[ -f "AP_STYLE_SUMMARY_PIPELINE.md" ] && mv AP_STYLE_SUMMARY_PIPELINE.md docs/archive/deprecated/ && echo "  ✓ Archived AP_STYLE_SUMMARY_PIPELINE.md"
[ -f "PIPELINE.md" ] && mv PIPELINE.md docs/archive/deprecated/ && echo "  ✓ Archived PIPELINE.md"
[ -f "PIPELINE_STATUS.md" ] && mv PIPELINE_STATUS.md docs/archive/deprecated/ && echo "  ✓ Archived PIPELINE_STATUS.md"

# Archive migration guides
[ -f "FULL_DATABASE_MIGRATION.md" ] && mv FULL_DATABASE_MIGRATION.md docs/archive/migration_guides/ && echo "  ✓ Archived FULL_DATABASE_MIGRATION.md"
[ -f "MATERIALITY_EXPORT_IMPORT_GUIDE.md" ] && mv MATERIALITY_EXPORT_IMPORT_GUIDE.md docs/archive/migration_guides/ && echo "  ✓ Archived MATERIALITY_EXPORT_IMPORT_GUIDE.md"
[ -f "IMPORT_EXPORT_COMMANDS.md" ] && mv IMPORT_EXPORT_COMMANDS.md docs/archive/migration_guides/ && echo "  ✓ Archived IMPORT_EXPORT_COMMANDS.md"
[ -f "S3_IMPORT_GUIDE.md" ] && mv S3_IMPORT_GUIDE.md docs/archive/migration_guides/ && echo "  ✓ Archived S3_IMPORT_GUIDE.md"

# Archive analysis reports
[ -f "RAG_VALIDATION_REPORT.md" ] && mv RAG_VALIDATION_REPORT.md docs/archive/analysis_reports/ && echo "  ✓ Archived RAG_VALIDATION_REPORT.md"
[ -f "LINKAGE_VERIFICATION.md" ] && mv LINKAGE_VERIFICATION.md docs/archive/analysis_reports/ && echo "  ✓ Archived LINKAGE_VERIFICATION.md"
[ -f "API_FILTERING_SUMMARY.md" ] && mv API_FILTERING_SUMMARY.md docs/archive/analysis_reports/ && echo "  ✓ Archived API_FILTERING_SUMMARY.md"
[ -f "DASHBOARD_FILTERING_SUMMARY.md" ] && mv DASHBOARD_FILTERING_SUMMARY.md docs/archive/analysis_reports/ && echo "  ✓ Archived DASHBOARD_FILTERING_SUMMARY.md"
[ -f "INFLUENCER_PAGES_SUMMARY.md" ] && mv INFLUENCER_PAGES_SUMMARY.md docs/archive/analysis_reports/ && echo "  ✓ Archived INFLUENCER_PAGES_SUMMARY.md"
[ -f "REACT_INTEGRATION_SUMMARY.md" ] && mv REACT_INTEGRATION_SUMMARY.md docs/archive/analysis_reports/ && echo "  ✓ Archived REACT_INTEGRATION_SUMMARY.md"

# Archive legacy deployment docs
[ -f "DEPLOYMENT_GUIDE.md" ] && mv DEPLOYMENT_GUIDE.md docs/archive/legacy_deployment/ && echo "  ✓ Archived DEPLOYMENT_GUIDE.md"
[ -f "DOCKER_SETUP.md" ] && mv DOCKER_SETUP.md docs/archive/legacy_deployment/ && echo "  ✓ Archived DOCKER_SETUP.md"
[ -f "AZURE_SETUP_SYSTEM2.md" ] && mv AZURE_SETUP_SYSTEM2.md docs/archive/legacy_deployment/ && echo "  ✓ Archived AZURE_SETUP_SYSTEM2.md"
[ -f "setup_local_db.md" ] && mv setup_local_db.md docs/archive/legacy_deployment/ && echo "  ✓ Archived setup_local_db.md"
[ -f "replit.md" ] && mv replit.md docs/archive/legacy_deployment/ && echo "  ✓ Archived replit.md"

# Create documentation index
echo ""
echo "[4/4] Creating documentation index..."
cat > docs/INDEX.md << 'EOF'
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
- Located in: `archive/deprecated/`
- Historical pipeline proposals and architecture decisions
- Kept for reference only

### Migration & Import/Export Guides
- Located in: `archive/migration_guides/`
- Database migration procedures
- S3 import/export guides
- Materiality score import/export

### Legacy Deployment Guides
- Located in: `archive/legacy_deployment/`
- Superseded deployment documentation
- Old setup guides

### Analysis Reports
- Located in: `archive/analysis_reports/`
- RAG validation reports
- Feature summaries and integration reports
- Linkage verification
EOF

echo "  ✓ Created docs/INDEX.md"

echo ""
echo "========================================="
echo "Reorganization Complete!"
echo "========================================="
echo ""
echo "Summary:"
echo "  ✓ All documentation organized in docs/"
echo "  ✓ Deployment guides in docs/deployment/"
echo "  ✓ Historical docs archived in docs/archive/"
echo "  ✓ Nothing deleted - all files preserved"
echo ""
echo "Root directory now contains only:"
echo "  - README.md (project overview)"
echo "  - CLAUDE.md (architecture - for Claude Code)"
echo "  - REORGANIZATION_PLAN.md (this reorganization guide)"
echo "  - Startup scripts (.sh, .ps1)"
echo "  - Docker configs (docker-compose.yml)"
echo "  - Config files (.env.example, requirements.txt)"
echo ""
echo "Next steps:"
echo "  1. Review docs/INDEX.md for navigation"
echo "  2. Update README.md to be more concise"
echo "  3. Test all deployment modes still work"
echo "  4. Commit changes to git"
echo ""
