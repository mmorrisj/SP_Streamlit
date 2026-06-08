# Deployment Guide — Start Here

The project has several deployment paths documented across multiple files. This
page is the **decision tree**: find your scenario, then follow the linked doc.
(The linked docs remain authoritative for their scenario; this page only routes.)

```
What are you doing?
│
├─ Local demo / first run on a laptop ─────────────► docs/DEMO_RUNBOOK.md
│     default docker-compose.yml, zero prerequisites
│
├─ Local development with hot-reload / debugging ──► DOCKER_WORKFLOW.md
│     docker-compose.dev.yml (external volume + network, mirrors prod)
│
├─ Standard production (permissive Docker daemon) ─► docs/deployment/PRODUCTION_INSTALL.md
│     docker-compose.production.yml
│
├─ Enterprise / hardened daemon ───────────────────► PRODUCTION_DOCKER_RUN.md
│     no `docker exec`, no bridge networks, --network host, TCP-only psql
│
├─ Migrating data to a new host / Rocky 9 ─────────► ENTERPRISE_MIGRATION.md
│
└─ Just pulling the published image ───────────────► docs/DOCKERHUB_README.md
```

## Quick reference

| Scenario | Compose file | Primary doc |
|---|---|---|
| Demo / quickstart | `docker-compose.yml` | [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md) |
| Local dev (hot-reload) | `docker-compose.dev.yml` | [DOCKER_WORKFLOW.md](DOCKER_WORKFLOW.md) |
| Standard production | `docker-compose.production.yml` | [docs/deployment/PRODUCTION_INSTALL.md](docs/deployment/PRODUCTION_INSTALL.md) |
| Enterprise hardened daemon | `docker-compose.production.yml` (host networking) | [PRODUCTION_DOCKER_RUN.md](PRODUCTION_DOCKER_RUN.md) |
| Windows host | `docker-compose.windows.yml` | [DOCKER_WORKFLOW.md](DOCKER_WORKFLOW.md) |
| Preprocessing batch jobs | `docker-compose.preprocessing.yml` | [services/pipeline/batch/README_BATCH_PROCESSING.md](services/pipeline/batch/README_BATCH_PROCESSING.md) |
| Data migration / restore | — | [ENTERPRISE_MIGRATION.md](ENTERPRISE_MIGRATION.md) |

## ⚠️ Important: do not mix daemon assumptions

The **enterprise hardened-daemon** path (`PRODUCTION_DOCKER_RUN.md`) deliberately
avoids patterns that the dev/standard docs use freely — `docker exec`, custom
bridge networks, and `--rm`. Applying permissive-daemon instructions on a
hardened host (or vice-versa) leads to silent failures. Confirm which daemon you
are on **before** choosing a doc.

## Common to all paths

- Populate `.env` from `.env.example` (DB creds, `CLAUDE_KEY`, optional AWS/S3).
- Run Alembic migrations after the DB is up (`--profile migrate`).
- See [CLAUDE.md](CLAUDE.md) for architecture and the environment-variable hierarchy.

---

> **Maintainer note:** the five+ deployment docs above overlap and should
> eventually be merged into this file (see `docs/MAINTAINABILITY_ASSESSMENT.md`
> §5). For now this page is the single entry point; the others are kept as the
> detailed references it links to.
