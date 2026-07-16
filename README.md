# Soft Power Analytics Platform

Soft Power Analytics ingests open-source news reporting about state influence activity in the
Middle East & North Africa, runs an AI/ML pipeline that turns ~765K documents into named
events, resolved entities, and materiality-scored initiatives, and serves the results as
interactive analytics, a research assistant, and analytic insight reports.

```
raw documents ─► salience gate ─► LLM extraction ─► normalized DB ─► embeddings
      ─► event clustering & consolidation ─► entity resolution ─► summaries & materiality
      ─► React app · Streamlit dashboard · RAG chat · insight reports
```

---

## What You Can Do

### Web application (React + FastAPI, `:8000`)

**Situational awareness**
- **Dashboard** — weekly activity tempo by influencer, recent intelligence, category mix
- **Events** — canonical events with detail pages, source mentions, and cross-period views
- **Documents / Summaries / Bilateral** — the corpus, AI narratives, and pair-level rollups
- **Influencer profiles** — China, Iran, Russia, Turkey, United States one-pagers
- **Country Comparison · Materiality Map · Competing Influence** — cross-actor views

**Research**
- **Research (chat)** — RAG over the corpus with entity-aware retrieval, inline source
  citations, and research projects that collect documents toward a report
- **Agent** — experimental multi-step agentic report workflow

**Insight reports**
- **Insight Reports** — the analytic reports from [`docs/reports/`](docs/reports/README.md)
  rendered in-app: report figures hydrate into interactive charts from their audit CSVs
  (Chart / Figure / Data toggle), and initiative charts are **click-to-drill** — every named
  initiative traces back to its canonical event and the source documents behind it, with
  self-reported vs third-party provenance flagged per document
- **Publication** — parameterized report generator (per influencer/recipient/period) with
  claim-vs-source validation and Word export

**Operations**
- **Alerts** — rule-based monitoring with in-app notifications
- **Ingestion** — upload → validate → run pipeline from the browser (analyst+)

### Streamlit dashboard (`:8501`)

Exploratory analytics over the same database — trends, distributions, drilldowns — for
analysis that hasn't yet earned a first-class React page.

### Analytic insight reports (`docs/reports/`)

Version-controlled markdown assessments with charts and per-figure audit CSVs, produced by an
agentic investigation pipeline with adversarial verification of every finding:

| Product | Scope |
|---|---|
| [MENA Theater Assessment](docs/reports/mena_theater/report.md) | Cross-actor synthesis: influence market, contested terrain, initiative ledger, networks, early warning |
| 5 × [initiator deep dives](docs/reports/README.md) | China, Iran, Russia, Turkey (+ U.S. relational lens) |
| 3 × category contests | Economic, Military, Social — cross-actor |
| 17 × recipient cards | "Who courts X?" for each MENA state |

---

## Methodology

The full doctrine lives in [`docs/INSIGHT_REPORT_PROMPT.md`](docs/INSIGHT_REPORT_PROMPT.md) and the
[white paper](docs/Soft_Power_Analytics_White_Paper.md); this is the short version.

**Pipeline lineage** (what a number in the app actually is):

1. **Source** — open-source news/media (ATOM CSV + DSR JSON exports). The corpus reflects
   *media reporting*, not a ground-truth ledger of activity. Coverage begins 2024-08-01.
2. **Salience gate** — an LLM judges whether each document describes a genuine soft-power
   influence event; non-salient documents are dropped.
3. **Extraction** — an LLM extracts category (Economic / Social / Military / Diplomacy),
   subcategory, initiating and recipient countries, named projects, location + lat/long,
   monetary commitment, and a distilled text. These are model inferences and carry error.
4. **Normalization** — PostgreSQL with many-to-many tables for multi-valued fields.
5. **Embeddings** — Nomic v1.5 (768-dim) vectors for documents, events, and entities (pgvector).
6. **Event detection** — two stages: same-day DBSCAN clustering with LLM deconfliction into
   canonical events, then cross-date consolidation into multi-day events. Every event links
   back to its source documents.
7. **Entity resolution** — canonical entities (people, orgs, SOEs, ministries) with a
   co-occurrence relationship graph.
8. **Scoring & summaries** — an LLM materiality score (~1–10) per event, plus bilateral and
   category rollup narratives.

**Analytic doctrine** (how the reports read the data):

- **Volume ≠ activity.** Raw document counts measure media attention. The corpus over-indexes
  on Iranian state media, so raw cross-actor comparisons are not apples-to-apples.
- **Provenance normalization.** Every document is classified self-reported (the initiator's
  own media ecosystem) vs third-party via `source_geofocus`; magnitudes are reported on the
  third-party-corroborated basis.
- **The initiative gate.** The honest unit of analysis is the named canonical event, gated at
  ≥50% third-party coverage from ≥3 independent outlets — not the article.
- **Traceability.** Every event, chart, and report finding can be walked back to source
  documents (`daily_event_mentions` → `documents`); report figures ship their underlying
  numbers as sibling CSVs.

**Standing caveats:** category/recipient/entity labels are LLM-extracted; `material_score` is
a model judgment, not a measured outcome; monetary figures are *announced*, not verified;
absence of reporting is not evidence of absence of activity.

---

## Quick Start

The zero-prerequisite path — full stack (React+API, Streamlit, PostgreSQL+pgvector, Redis)
from a fresh checkout:

```bash
cp .env.example .env                    # add credentials (see Environment Variables)
docker compose up -d --build            # default docker-compose.yml
docker compose --profile migrate up     # run DB migrations
```

- React app + API: http://localhost:8000
- Streamlit dashboard: http://localhost:8501

Full walkthrough (including demo data): [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md).

### Deploying somewhere real?

**[`DEPLOYMENT.md`](DEPLOYMENT.md) is the decision tree — start there.** Summary:

| Scenario | Path |
|---|---|
| Local demo / first run | default `docker-compose.yml` + [DEMO_RUNBOOK](docs/DEMO_RUNBOOK.md) |
| Development with hot-reload | `docker-compose.dev.yml` + [DOCKER_WORKFLOW.md](DOCKER_WORKFLOW.md) |
| Standard production | `docker-compose.production.yml` / `scripts/docker/production-deploy.sh` |
| Enterprise / hardened daemon | [`PRODUCTION_DOCKER_RUN.md`](PRODUCTION_DOCKER_RUN.md) (raw `docker run`, no exec) |
| Pipeline-only worker | `docker/preprocessing.Dockerfile` (see Pipeline below) |

Published images: `mmorrisj/softpower-analytics:1.8.28` (self-contained app, SBOM +
provenance attestations) and `mmorrisj/pgvector:0.8.2-pg17`. Releases are built and pushed via
`scripts/docker/push-to-registry.sh` (always `--pull --sbom=true --provenance=mode=max`).
Deploy targets do **not** auto-pull — `docker pull` the new tag before deploying.

---

## Production Operations

All production Docker operations go through one script:

```bash
./scripts/docker/production-deploy.sh <command>
```

| Command | Description |
|---|---|
| `start` / `stop` / `restart` | Manage all services (DB + Redis + App) |
| `migrate` | Run Alembic migrations |
| `status` | Container and image status |
| `backup [file]` / `restore <file>` | pg_dump backup / full restore |
| `import <files\|dir>` | Import dump files additively |
| `rebuild-db [file]` | Drop DB, recreate schema, optionally restore |
| `psql [sql]` | Interactive psql or one-shot SQL |
| `logs [container]` | Tail logs |
| `load [dir]` | Load images from tar files |

Wipe-and-rebuild (preserves users by default): `./scripts/docker/production-wipe.sh`.

### Database export / import

```bash
# Binary (includes embeddings) — chunked by default, good for transfer
python scripts/db_export.py --output-dir ./db_export            # add --single-file, --docker-container
./scripts/docker/production-deploy.sh import ./db_export/       # or: restore <file>

# CSV (human-readable; embeddings skipped by default)
python scripts/db_export_csv.py --output-dir ./db_csv_export
python scripts/db_import_csv.py --input-dir ./db_csv_export --docker-container
```

**Embeddings** regenerate in ~45 hours but restore from Parquet in ~15–20 minutes — always
back them up separately: see
[`services/pipeline/embeddings/README_BACKUP_RESTORE.md`](services/pipeline/embeddings/README_BACKUP_RESTORE.md).

---

## Ingestion Pipeline

Primary orchestrator (also runnable from the in-app Ingestion page):

```bash
python services/run_ingestion_pipeline.py \
    --start-date 2026-02-18 --end-date 2026-02-24 --source local
# Focused runs: --profile events | summaries | entities   ·   Preview: --dry-run
```

Individual stages (ingestion, embeddings, two-stage event clustering, entity resolution,
bilateral summaries) are documented in [CLAUDE.md](CLAUDE.md) and the service READMEs
([events](services/pipeline/events/README_EVENT_SUMMARIES.md),
[publication](services/publication/README.md)).

**Pipeline-only container** (no web stack):

```bash
docker build -f docker/preprocessing.Dockerfile -t softpower-preprocessing:latest .
docker run -d --name sp-preprocess --restart unless-stopped --env-file .env.docker \
    -v "${PWD}/data:/app/data" softpower-preprocessing:latest sleep infinity
docker exec -it sp-preprocess python services/run_ingestion_pipeline.py --dry-run \
    --start-date 2026-02-18 --end-date 2026-02-24
```

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Database credentials |
| `DB_HOST` | Database host (`localhost` or container name) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `DB_PORT` | `5432` | Database port |
| `API_PORT` | `8000` | FastAPI port |
| `STREAMLIT_PORT` | `8501` | Streamlit port |
| `JWT_SECRET` | built-in default | JWT signing key (min 32 chars — change for production) |
| `JWT_EXPIRATION_HOURS` | `24` | Token lifetime |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `CLAUDE_KEY` | — | **LLM API key (OpenAI-compatible).** Historical name — this is the OpenAI key used by extraction, chat/RAG, and report generation |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | S3 credentials |
| `LLM_PROXY_PORT` | `7001` | Host-side LLM/S3 proxy port (0 to disable) |
| `DOCKER_ENV` | — | Set `true` inside containers (compose files do this) |

---

## Database

```bash
./scripts/docker/production-deploy.sh psql            # Docker production
docker exec -it softpower_db psql -U $POSTGRES_USER -d $POSTGRES_DB   # compose dev
alembic upgrade head                                   # apply migrations (local)
alembic revision --autogenerate -m "description"       # new migration after model changes
```

```python
from shared.database.database import health_check, get_pool_status
print("Connected" if health_check() else "Failed"); print(get_pool_status())
```

---

## Troubleshooting

- **Container can't reach DB** (`localhost` refused): inside a container `localhost` is the
  container itself — use `host.docker.internal` (host DB) or the container name (compose DB).
- **Port already in use:** change in `.env` (`API_PORT=5002`, `STREAMLIT_PORT=8502`).
- **Module import errors:** run from the project root with the venv active; all imports use
  the `shared.` prefix.

---

## Repository Layout

```
client/            React + TypeScript frontend (Vite; served by FastAPI in production)
server/            FastAPI server (API + React UI + chat/RAG + insight reports + S3/LLM proxy)
  routers/         Extracted API routers (influencer, ingestion, intel_reports)
services/
  dashboard/       Streamlit analytics dashboard
  chat/            RAG service (semantic search + LLM responses)
  publication/     Word-document publication generator
  pipeline/        Ingestion, analysis, events, entities, embeddings, summaries
shared/            SQLAlchemy models, DB/session management, config, utilities
docs/
  reports/         Analytic insight reports (served in-app at /intel-reports)
  INSIGHT_REPORT_PROMPT.md   Report-generation doctrine & methodology
docker/            Dockerfiles (registry, production, pgvector, preprocessing, dev)
scripts/           Deployment, release, export/import, and utility scripts
alembic/           Database migrations
```

---

## Documentation

| Document | Description |
|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | **Start here for any deployment** — the decision tree |
| [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md) | Zero-prerequisite demo walkthrough |
| [PRODUCTION_DOCKER_RUN.md](PRODUCTION_DOCKER_RUN.md) | Enterprise / hardened-daemon deployment |
| [DOCKER_WORKFLOW.md](DOCKER_WORKFLOW.md) | Development workflow and image builds |
| [CLAUDE.md](CLAUDE.md) | Complete architecture and development guide |
| [docs/Soft_Power_Analytics_White_Paper.md](docs/Soft_Power_Analytics_White_Paper.md) | Platform white paper |
| [docs/INSIGHT_REPORT_PROMPT.md](docs/INSIGHT_REPORT_PROMPT.md) | Analytic methodology & report doctrine |
| [docs/reports/README.md](docs/reports/README.md) | The insight reports + cross-actor synthesis |
| [docs/TESTING.md](docs/TESTING.md) | Test suite usage |
| [docs/INDEX.md](docs/INDEX.md) | Full documentation index |
