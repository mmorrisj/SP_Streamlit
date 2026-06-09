# Demo Runbook

A minimal, reproducible path to stand up the Soft Power Analytics stack for a
demo from a fresh checkout. Targets the **default `docker-compose.yml`**
(Compose-managed volume + network — no pre-steps).

> **Validation status:** the compose file has been validated with
> `docker compose config`, but this runbook should be **dry-run end-to-end on
> the actual demo host** before the demo, since image builds, DB migration, and
> LLM/S3 connectivity depend on that environment. Note any gaps here as you go.

---

## 1. Prerequisites

- Docker Engine + Compose v2 (`docker compose version`). The legacy
  `docker-compose` v1 also works.
- A populated `.env` (copy `.env.example` and fill in the values below).
- Network egress to the OpenAI-compatible LLM endpoint (for chat/RAG and report
  features) and to AWS S3 (only if demoing S3-backed ingestion/embeddings).

## 2. Minimal `.env` for a demo

```bash
cp .env.example .env
```

At minimum set:

```ini
# Database (any values; the stack creates this DB on first run)
POSTGRES_USER=softpower
POSTGRES_PASSWORD=change-me
POSTGRES_DB=softpower

# Host port the API/React UI is published on (container always listens on 8000)
API_PORT=7001
# Host port for the Streamlit dashboard
DASHBOARD_PORT=8501

# Skip enterprise JWT for the demo so the UI is reachable without a gateway
DEV_AUTH_BYPASS=true
DEV_AUTH_ROLE=admin

# LLM access (needed for chat/RAG, summaries, report generation)
CLAUDE_KEY=sk-...

# Keep the experimental agent out of the demo build
DISABLE_AGENT=true
```

Leave `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` blank unless demoing S3.

## 3. Start the stack

```bash
# Build images and start db + api + dashboard + redis
docker compose up -d --build

# Apply database migrations (one-off)
docker compose --profile migrate up

# Watch logs
docker compose logs -f api
```

## 4. Smoke checks

```bash
# API health (expect HTTP 200 / {"status": ...})
curl -fsS http://localhost:${API_PORT:-7001}/api/health && echo OK

# DB connectivity from the host (optional)
python -c "from shared.database.database import health_check; print('DB OK' if health_check() else 'DB FAIL')"
```

Then in a browser:

- **React UI + API:** `http://localhost:7001` (or your `API_PORT`)
- **Streamlit dashboard:** `http://localhost:8501` (or your `DASHBOARD_PORT`)

If the database is empty, load a demo dataset/backup before showing data-heavy
pages (see `ENTERPRISE_MIGRATION.md` for import/restore, and the embeddings
backup/restore docs under `services/pipeline/embeddings/`).

## 5. Teardown

```bash
# Stop containers (data persists in the managed postgres_data volume)
docker compose down

# Full reset (DELETES demo data)
docker compose down -v
```

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `env file .../.env not found` | No `.env` | `cp .env.example .env` and fill it in |
| `POSTGRES_USER ... must be set` | Empty required var | Set DB vars in `.env` |
| API 401 / login wall in demo | JWT enforced | Set `DEV_AUTH_BYPASS=true` |
| Port already allocated | Host port in use | Change `API_PORT` / `DASHBOARD_PORT` in `.env` |
| Empty dashboards | No data loaded | Restore a DB/embeddings backup |
| `/api/agent/*` errors | Experimental agent | Set `DISABLE_AGENT=true` (see `agent/README.md`) |

## 7. Compose file selection

- `docker-compose.yml` — **this runbook** (default dev/demo, zero prerequisites).
- `docker-compose.dev.yml` — production-mirroring dev (external volume/network).
- `docker-compose.production.yml` — enterprise/hardened daemon; see
  `PRODUCTION_DOCKER_RUN.md`.
