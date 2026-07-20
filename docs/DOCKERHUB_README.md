# Soft Power Analytics Dashboard

All-in-one container for the Soft Power Analytics Dashboard — a diplomatic document analysis platform with AI-powered semantic search, entity tracking, and interactive visualizations.

## What's Inside

This image bundles everything into a single container managed by supervisord:

- **FastAPI** — React web UI + REST API (port 8000), including the in-app Insight Reports viewer
- **Streamlit** — Analytics & data exploration dashboard (port 8501)
- **ML Models** — Nomic Embed v1.5 (768-dim) + MiniLM reranker pre-baked for offline embedding/RAG
- **Insight reports** — analytic assessments baked in at `docs/reports/`, served at `/intel-reports`
- **Alembic** — Database migration tooling included

> Use tag **`1.8.18` or newer** — earlier tags predate the embedding-model fix.
> Current release: **`1.8.30`**.

## Quick Start

### 1. Start the stack

```yaml
# docker-compose.production.yml
services:
  db:
    image: mmorrisj/pgvector:0.8.2-pg17
    environment:
      POSTGRES_USER: softpower
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: softpower-db
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U softpower -d softpower-db"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  redis:
    image: redis:7-alpine

  app:
    image: mmorrisj/softpower-analytics:${APP_VERSION:-1.8.30}
    environment:
      DOCKER_ENV: "true"
      DB_HOST: db
      DB_PORT: 5432
      POSTGRES_USER: softpower
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: softpower-db
      DATABASE_URL: postgresql+psycopg2://softpower:changeme@db:5432/softpower-db
      REDIS_URL: redis://redis:6379
      API_PORT: 8000
      JWT_SECRET: change-this-to-a-random-string-at-least-32-chars
    ports:
      - "8000:8000"   # FastAPI (React UI + API)
      - "8501:8501"   # Streamlit Dashboard
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

  migrate:
    image: mmorrisj/softpower-analytics:${APP_VERSION:-1.8.30}
    environment:
      DOCKER_ENV: "true"
      DATABASE_URL: postgresql+psycopg2://softpower:changeme@db:5432/softpower-db
    command: alembic upgrade head
    depends_on:
      db:
        condition: service_healthy
    profiles:
      - migrate

volumes:
  pgdata:
```

### 2. Choose a deployment path

#### Path A: Fresh install (empty database)

```bash
# Run database migrations
docker compose -f docker-compose.production.yml --profile migrate up

# Start the application
docker compose -f docker-compose.production.yml up -d

# Create an admin user
docker exec -it <app-container> python scripts/create_admin.py --username admin
```

#### Path B: Restore from backup (existing pg_dump)

> **Do not** run migrations when restoring from a dump — the dump already contains the full schema.

```bash
# Start the stack (db must be healthy before restore)
docker compose -f docker-compose.production.yml up -d

# Copy the dump into the db container
docker cp backup.dump <db-container>:/tmp/backup.dump

# Restore (--clean drops existing objects first)
docker exec <db-container> pg_restore -U softpower -d softpower-db \
  --no-owner --no-privileges --clean --if-exists /tmp/backup.dump

# Reset the admin password (the dump contains the old hash)
docker exec <app-container> python scripts/create_admin.py \
  --username admin --password YourNewPassword --reset-password
```

### 3. Access the dashboard

| Service | URL |
|---|---|
| React UI + API | http://localhost:8000 |
| Streamlit Dashboard | http://localhost:8501 |
| API Health Check | http://localhost:8000/api/health |

## Environment Variables

### Required

| Variable | Description | Example |
|---|---|---|
| `DOCKER_ENV` | Enable Docker mode | `true` |
| `DB_HOST` | PostgreSQL hostname | `db` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_USER` | Database username | `softpower` |
| `POSTGRES_PASSWORD` | Database password | `changeme` |
| `POSTGRES_DB` | Database name | `softpower-db` |
| `DATABASE_URL` | Full SQLAlchemy connection URL | `postgresql+psycopg2://...` |

### Optional

| Variable | Description | Default |
|---|---|---|
| `API_PORT` | FastAPI listen port | `8000` |
| `JWT_SECRET` | JWT signing key (min 32 chars) | Built-in default (change for production) |
| `JWT_EXPIRATION_HOURS` | Token lifetime | `24` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` |
| `CLAUDE_KEY` | LLM API key (OpenAI-compatible; historical name) for chat/RAG and report generation | — |
| `AWS_ACCESS_KEY_ID` | AWS credentials for S3 integration | — |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials for S3 integration | — |

## Database

This image is designed to work with [`mmorrisj/pgvector:0.8.2-pg17`](https://hub.docker.com/r/mmorrisj/pgvector) — PostgreSQL 17 with the pgvector extension compiled from source for vector similarity search.

## Windows / Git Bash Note

Git Bash on Windows automatically converts Unix-style paths (e.g. `/tmp/backup.dump`) to Windows paths, which breaks `docker exec` and `docker cp` commands. Prefix commands with `MSYS_NO_PATHCONV=1`:

```bash
MSYS_NO_PATHCONV=1 docker cp backup.dump sp_prod_db:/tmp/backup.dump
MSYS_NO_PATHCONV=1 docker exec sp_prod_db pg_restore -U softpower -d softpower-db \
  --no-owner --no-privileges --clean --if-exists /tmp/backup.dump
```

## Image Details

| Property | Value |
|---|---|
| Size | ~2 GB |
| Base image | `python:3.13-slim` (Debian Trixie) |
| Python | 3.13 |
| ML runtime | PyTorch (CPU), sentence-transformers |
| Process manager | supervisord (4 FastAPI workers + 1 Streamlit) |
| User | `appuser` (non-root) |
| Attestations | SBOM + Provenance (max mode) |

## Security

- Runs as non-root user (`appuser`)
- Build tools removed after compilation to reduce attack surface
- Base image kept current with zero fixable critical/high CVEs
- Supply chain attestations (SBOM + provenance) attached
- Admin creation requires explicit password (no defaults)
- Force-password-change enabled by default for new admin accounts

## Source

[GitHub Repository](https://github.com/mmorrisj/SoftPower_Analytics)
