# Soft Power Analytics Platform

Soft Power Analytics is a document intelligence platform for ingesting DSR data, building event/entity pipelines, scoring materiality, and serving analytics through FastAPI, React, and Streamlit.

## Current Architecture

- `services/`: ingestion, embeddings, events, summaries, entities, batch jobs, and pipeline orchestration
- `server/`: FastAPI app (`server/main.py`)
- `client/`: React frontend served by FastAPI in containerized deployments
- `services/dashboard/`: Streamlit dashboard
- `shared/`: SQLAlchemy models, DB/session management, shared config/utilities
- `docker/`: Dockerfiles for API, dashboard, production, and preprocessing runtimes

## Quick Start (Docker Compose - Dev)

1. Create env file:
```bash
cp .env.example .env
```

2. Start core services:
```bash
docker compose up -d db redis api dashboard
```

3. (Optional) run migrations:
```bash
docker compose --profile migrate up migrate
```

4. Verify:
- API health: `http://localhost:7001/api/health` (default mapping from compose)
- Streamlit: `http://localhost:8501`

## Local Run (Without Docker for API/Dashboard)

Install dependencies:
```bash
pip install -r requirements.txt
```

Run API:
```bash
uvicorn server.main:app --host 0.0.0.0 --port 7001
```

Run Streamlit:
```bash
streamlit run services/dashboard/app.py
```

## Batch-First Ingestion Pipeline

Primary orchestrator:
- `services/run_ingestion_pipeline.py`

Run full pipeline:
```bash
python services/run_ingestion_pipeline.py --start-date 2026-02-18 --end-date 2026-02-24 --source local
```

Run a subset profile:
```bash
python services/run_ingestion_pipeline.py --start-date 2026-02-18 --end-date 2026-02-24 --profile events
python services/run_ingestion_pipeline.py --start-date 2026-02-18 --end-date 2026-02-24 --profile summaries
python services/run_ingestion_pipeline.py --start-date 2026-02-18 --end-date 2026-02-24 --profile entities
```

Use iterative mode instead of batch mode:
```bash
python services/run_ingestion_pipeline.py --start-date 2026-02-18 --end-date 2026-02-24 --execution-mode iterative
```

Dry run:
```bash
python services/run_ingestion_pipeline.py --start-date 2026-02-18 --end-date 2026-02-24 --dry-run
```

## Preprocessing Image (Pipeline-Only Runtime)

Build:
```bash
docker build -f docker/preprocessing.Dockerfile -t softpower-preprocessing:latest .
```

Run as a persistent worker container:
```bash
docker run -d --name sp-preprocess `
  --restart unless-stopped `
  --env-file .env.docker `
  -v "${PWD}\data:/app/data" `
  -v "${PWD}\_data:/app/_data" `
  softpower-preprocessing:latest `
  sleep infinity
```

Exec into container:
```bash
docker exec -it sp-preprocess bash
```

Run common pipeline commands inside container:
```bash
python services/pipeline/ingestion/dsr.py --source local
python services/pipeline/embeddings/embed_missing_documents.py --yes
python services/pipeline/events/batch_cluster_events.py --country Iran --start-date 2026-02-18 --end-date 2026-02-24
```

## Environment Notes

- `.env` is the host/local default.
- `.env.docker` should be used for containerized preprocessing runs.
- If DB runs on host (not inside compose network), set:
  - `DB_HOST=host.docker.internal`
  - `POSTGRES_HOST=host.docker.internal`
- If DB runs in compose network, use service/container name (`softpower_db` in dev compose).

## Database Access

Connect to dev DB container:
```bash
docker exec -it softpower_db psql -U <POSTGRES_USER> -d <POSTGRES_DB>
```

## Troubleshooting

Container cannot reach DB (`localhost` connection refused):
- Inside a container, `localhost` points to the container itself.
- Use `host.docker.internal` (host DB) or `softpower_db` (compose DB).

`langchain_pg_embedding` schema/column errors during embeddings:
- Confirm current schema in Postgres:
```bash
docker exec -it softpower_db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\d+ langchain_pg_embedding"
```
- If schema is from an older layout, run migrations and align table definitions before rerunning embeddings.

## Useful Docs

- [DOCKER_WORKFLOW.md](DOCKER_WORKFLOW.md)
- [docker-compose.yml](docker-compose.yml)
- [docker-compose.production.yml](docker-compose.production.yml)
- [services/pipeline/batch/README_BATCH_PROCESSING.md](services/pipeline/batch/README_BATCH_PROCESSING.md)
