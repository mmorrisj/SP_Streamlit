# Documentation Index

## Quick Start
- **[QUICKSTART.md](QUICKSTART.md)** - Pointer to the canonical quick start (README) and the deployment decision tree
- **[DEMO_RUNBOOK.md](DEMO_RUNBOOK.md)** - Stand up the full stack for a demo (default docker-compose.yml)

## Core Documentation
- **[../README.md](../README.md)** - Project overview: analytics, methodology, deployment
- **[../CLAUDE.md](../CLAUDE.md)** - Complete architecture and development guide
- **[MAINTAINABILITY_ASSESSMENT.md](MAINTAINABILITY_ASSESSMENT.md)** - Maintainability review & transition roadmap

## Analytics & Methodology
- **[../docs/reports/README.md](reports/README.md)** - The analytic insight reports: MENA theater assessment, initiator/category/recipient reports (served in-app at `/intel-reports`)
- **[INSIGHT_REPORT_PROMPT.md](INSIGHT_REPORT_PROMPT.md)** - Analytic doctrine: provenance normalization, the corroborated-initiative gate, report-generation playbook
- **[reports/_derived/manifest.md](reports/_derived/manifest.md)** - Derived analytics artifacts (DDL + promotion recommendations)
- **[Soft_Power_Analytics_White_Paper.md](Soft_Power_Analytics_White_Paper.md)** - Platform white paper (v4.0)

## Deployment Guides
- **[../DEPLOYMENT.md](../DEPLOYMENT.md)** - Start here: decision tree routing to the right deployment doc
- **[deployment/PRODUCTION_INSTALL.md](deployment/PRODUCTION_INSTALL.md)** - Production Docker deployment (no compose)
- **[../PRODUCTION_DOCKER_RUN.md](../PRODUCTION_DOCKER_RUN.md)** - Enterprise / hardened-daemon deployment (raw docker run)
- **[ENTERPRISE_CUTOVER_RUNBOOK.md](ENTERPRISE_CUTOVER_RUNBOOK.md)** - Point-in-time runbook: embedding-fix cutover + full rebuild (archive after cutover)
- **[DOCKERHUB_README.md](DOCKERHUB_README.md)** - Docker Hub image documentation
- **[../DOCKER_WORKFLOW.md](../DOCKER_WORKFLOW.md)** - Docker build and workflow reference

## Pipeline & Services
- **[../services/pipeline/events/README_EVENT_SUMMARIES.md](../services/pipeline/events/README_EVENT_SUMMARIES.md)** - Event summary generation
- **[../services/pipeline/embeddings/README_BACKUP_RESTORE.md](../services/pipeline/embeddings/README_BACKUP_RESTORE.md)** - Embedding backup/restore (Parquet)
- **[../services/publication/README.md](../services/publication/README.md)** - Word-document publication service

## Security & Compliance
- **[CVE_MITIGATION_REPORT.md](CVE_MITIGATION_REPORT.md)** - CVE analysis and remediation
- **[deployment/ENTERPRISE_CVE_EXCEPTION_REQUEST.md](deployment/ENTERPRISE_CVE_EXCEPTION_REQUEST.md)** - Enterprise CVE exception template

## Testing & CI/CD
- **[TESTING.md](TESTING.md)** - Testing guide, CI workflows, and honest coverage status

## Archived Documentation
- Located in: `../_archive/docs/`
- Historical pipeline proposals and architecture decisions
- Legacy deployment guides (airgap, non-Docker, CentOS 7)
- Kept for reference only
