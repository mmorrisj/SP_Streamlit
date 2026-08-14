# Running the In-App Feedback Survey on the Enterprise Stack

This guide gets the feedback survey page (added in release **2.0.0**, PR #159)
working on the enterprise deployment (`docker-compose.enterprise.yml` — hosted
PostgreSQL, no `db` container, host networking).

## What the survey is

- A **Feedback** page in the React UI at `/survey` (clipboard icon in the left
  nav). Question definitions live entirely in the client.
- Responses are stored in a new Postgres table, `survey_responses`: respondent
  identity from the enterprise JWT, an extracted 1–5 `overall_rating` column
  for cheap aggregation, and the full answer payload as JSONB (so questions
  can change without further migrations).
- API: `POST /api/survey/responses` (any authenticated user) and
  `GET /api/survey/responses` (**analyst or admin role required** — returns
  raw responses plus computed aggregates).

## Prerequisites

- The enterprise host already runs the stack from `docker-compose.enterprise.yml`
  with a populated `.env` (`DB_HOST`, `POSTGRES_*`, etc.).
- App image **2.0.0 or later**. Earlier images (1.8.x) contain neither the
  survey page nor the API routes.
- The hosted database is reachable and already has the `vector` and `pg_trgm`
  extensions (existing deployments will).

## Step 1 — Pull the 2.0.0 image

> ⚠️ The deploy script does **not** pull images. If you skip this step,
> `docker compose` silently reuses whatever tag is cached locally.

```bash
docker pull mmorrisj/softpower-analytics:2.0.0
```

## Step 2 — Point the stack at 2.0.0

In the repo's `.env` on the enterprise host, set (or update) `APP_IMAGE` —
both the `app` and `migrate` services read it:

```bash
APP_IMAGE=mmorrisj/softpower-analytics:2.0.0
```

Note: `scripts/docker/enterprise-deploy.sh` falls back to an old default
(`1.8.6`) when `APP_IMAGE` is unset, so set it explicitly.

## Step 3 — Run the database migration

The survey table ships as Alembic revision `20260807_survey_responses`
(`alembic upgrade head` applies it plus anything else the DB is behind on).
The migration is idempotent — it no-ops if `survey_responses` already exists.

```bash
# Recommended: wraps pre-flight checks + migration
scripts/docker/enterprise-deploy.sh migrate

# Or directly:
docker compose -f docker-compose.enterprise.yml --profile migrate up
```

## Step 4 — Restart the app on the new image

```bash
# Full deploy (pre-flight + migrate + start) — steps 3 and 4 in one:
scripts/docker/enterprise-deploy.sh

# Or just recreate the app container:
docker compose -f docker-compose.enterprise.yml up -d
```

## Step 5 — Verify

1. **Table exists** (from any host with psql access to the hosted DB):
   ```sql
   SELECT COUNT(*) FROM survey_responses;
   ```
2. **UI**: open `http://<host>:8000`, log in, click **Feedback** in the left
   nav (or go to `/survey`), submit a test response.
3. **API** (with a valid JWT):
   ```bash
   curl -H "Authorization: Bearer <token>" \
        http://127.0.0.1:8000/api/survey/responses
   ```
   Expect a `responses` array and a `summary` block with `avg_overall`,
   per-question `rating_averages`, and `would_use_counts`.

## Collecting and reading results

- **In-app / API**: `GET /api/survey/responses?limit=500` (max 1000) —
  requires an **analyst** or **admin** JWT role. Regular users can submit
  but get `403` when reading.
- **SQL** (for export or ad-hoc analysis):
  ```sql
  SELECT created_at, username, user_role, overall_rating, answers
  FROM survey_responses
  ORDER BY created_at DESC;
  ```
  Per-feature ratings live under `answers->'ratings'`, multiple choice under
  keys like `answers->>'would_use'`, free text under the remaining keys.

## Operational notes

- **Shared demo logins**: identity comes from the JWT, so if demo machines
  share a login, all responses record the same `username`. Distinguish
  sessions by `created_at` or add an identifying free-text question.
- **Input limits**: the server truncates free-text answers to 4,000
  characters and drops empty values; fully empty submissions are rejected
  with `400`.
- **Rollback**: the migration has a clean `downgrade()`
  (`alembic downgrade -1` drops the table and its index). Reverting the
  image to a 1.8.x tag removes the page/API but leaves the table untouched.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| No **Feedback** item in the nav | App still on a 1.8.x image — check `docker inspect sp_ent_app --format '{{.Config.Image}}'`, then redo steps 1–2 and recreate the container. |
| `500` on survey submit | Migration not applied — run step 3 and check `docker logs sp_ent_migrate`. |
| `403` when reading responses | JWT role is not `analyst`/`admin`. Submissions still work for any authenticated user. |
| Migration fails on connectivity | Run `scripts/docker/enterprise-deploy.sh check` — validates `DB_HOST` reachability and required extensions. Hosted DB without TLS? Set `ENVIRONMENT` to a non-production value in `.env` (production enforces `sslmode=require`). |
