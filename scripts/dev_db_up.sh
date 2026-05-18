#!/usr/bin/env bash
# Spin up an isolated dev Postgres container seeded from the existing
# softpower_db, for testing the agent workflow without touching the main DB.
#
# What it does:
#   1. Sanity-check that the source container is running and .env is present.
#   2. Refuse if the test container/volume already exist (run dev_db_down.sh first).
#   3. Start a sibling pgvector container on a separate port + volume.
#   4. pg_dump the source DB and pipe it into the test DB (preserves
#      alembic_version, so the upgrade in step 5 only applies new migrations).
#   5. Run `alembic upgrade head` against the test DB to add the new
#      agent_* tables on top of the copied schema.
#   6. Print env-var exports for pointing the agent at the test DB.
#
# Configurable via environment (sensible defaults below):
#   AGENT_TEST_DB_NAME     target database name           (default softpower_agent_test)
#   AGENT_TEST_CONTAINER   target container name          (default softpower_db_agent_test)
#   AGENT_TEST_VOLUME      target docker volume name      (default postgres_data_agent_test)
#   AGENT_TEST_PORT        host port for target Postgres  (default 5433)
#   AGENT_SOURCE_CONTAINER source container name to copy  (default softpower_db)
#   AGENT_PGVECTOR_IMAGE   image to use for the target    (default mmorrisj/pgvector:0.8.1-pg17)
#   AGENT_NETWORK          docker network                 (default softpower_net)

set -euo pipefail

# ----- config --------------------------------------------------------------
TEST_DB_NAME="${AGENT_TEST_DB_NAME:-softpower_agent_test}"
TEST_CONTAINER="${AGENT_TEST_CONTAINER:-softpower_db_agent_test}"
TEST_VOLUME="${AGENT_TEST_VOLUME:-postgres_data_agent_test}"
TEST_PORT="${AGENT_TEST_PORT:-5433}"
SOURCE_CONTAINER="${AGENT_SOURCE_CONTAINER:-softpower_db}"
PGVECTOR_IMAGE="${AGENT_PGVECTOR_IMAGE:-mmorrisj/pgvector:0.8.1-pg17}"
NETWORK="${AGENT_NETWORK:-softpower_net}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

# ----- helpers -------------------------------------------------------------
log()  { printf "\033[1;34m[dev-db-up]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[dev-db-up] %s\033[0m\n" "$*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

container_running() { docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -q true; }
container_exists()  { docker inspect "$1" >/dev/null 2>&1; }
volume_exists()     { docker volume inspect "$1" >/dev/null 2>&1; }

# ----- preflight -----------------------------------------------------------
require_cmd docker

[[ -f "$ENV_FILE" ]] || fail ".env not found at $ENV_FILE"

# Load .env without polluting the parent shell beyond what we need
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_USER:?POSTGRES_USER not set in .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set in .env}"
: "${POSTGRES_DB:?POSTGRES_DB not set in .env}"

container_running "$SOURCE_CONTAINER" \
  || fail "source container '$SOURCE_CONTAINER' is not running. Start the dev stack first: docker compose -f docker-compose.dev.yml up -d db"

if container_exists "$TEST_CONTAINER"; then
  fail "test container '$TEST_CONTAINER' already exists. Run scripts/dev_db_down.sh first."
fi
if volume_exists "$TEST_VOLUME"; then
  fail "test volume '$TEST_VOLUME' already exists. Run scripts/dev_db_down.sh first."
fi

# Ensure the network exists (it will if the dev stack is up)
docker network inspect "$NETWORK" >/dev/null 2>&1 \
  || { log "network '$NETWORK' not found, creating"; docker network create "$NETWORK" >/dev/null; }

# ----- start target container ---------------------------------------------
log "starting test container '$TEST_CONTAINER' on host port $TEST_PORT (db=$TEST_DB_NAME)"
docker run -d \
  --name "$TEST_CONTAINER" \
  --network "$NETWORK" \
  --shm-size 1g \
  -p "$TEST_PORT:5432" \
  -e POSTGRES_USER="$POSTGRES_USER" \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  -e POSTGRES_DB="$TEST_DB_NAME" \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v "$TEST_VOLUME:/var/lib/postgresql/data" \
  "$PGVECTOR_IMAGE" >/dev/null

# ----- wait until target is accepting connections -------------------------
log "waiting for test container to become healthy..."
for i in {1..60}; do
  if docker exec "$TEST_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$TEST_DB_NAME" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [[ $i -eq 60 ]]; then
    fail "test container did not become healthy within 60 seconds. Check: docker logs $TEST_CONTAINER"
  fi
done
log "test container is up"

# ----- dump + restore ------------------------------------------------------
# pg_dump runs inside the source container (so we don't need pg_dump on the
# host); output is piped through the host into psql running in the target.
# Large DBs can take a few minutes here.
log "copying $SOURCE_CONTAINER/$POSTGRES_DB -> $TEST_CONTAINER/$TEST_DB_NAME (this may take a few minutes)"
docker exec "$SOURCE_CONTAINER" \
    pg_dump -U "$POSTGRES_USER" --no-owner --no-privileges "$POSTGRES_DB" \
  | docker exec -i "$TEST_CONTAINER" \
    psql -U "$POSTGRES_USER" -d "$TEST_DB_NAME" -v ON_ERROR_STOP=0 >/dev/null
log "copy complete"

# ----- apply pending migrations -------------------------------------------
# The dump preserved alembic_version. `alembic upgrade head` will only apply
# revisions that aren't already in that table — i.e., the new agent_* ones.
log "running alembic upgrade head against the test DB"

ALEMBIC_ENV=(
  -e POSTGRES_USER="$POSTGRES_USER"
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
  -e POSTGRES_DB="$TEST_DB_NAME"
  -e DB_HOST="$TEST_CONTAINER"
  -e DB_PORT=5432
)

# Prefer the api image if it's built (mirrors how docker-compose's
# alembic-migrate service runs). Fall back to host python if not.
if docker image inspect softpower_streamlit-api:latest >/dev/null 2>&1; then
  log "using softpower_streamlit-api:latest image for alembic"
  docker run --rm \
    --network "$NETWORK" \
    "${ALEMBIC_ENV[@]}" \
    -v "$ROOT_DIR:/app" \
    -w /app \
    softpower_streamlit-api:latest \
    alembic upgrade head
elif command -v alembic >/dev/null 2>&1; then
  log "softpower_streamlit-api image not found; using host alembic"
  ( cd "$ROOT_DIR" && \
    POSTGRES_USER="$POSTGRES_USER" \
    POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    POSTGRES_DB="$TEST_DB_NAME" \
    DB_HOST=localhost \
    DB_PORT="$TEST_PORT" \
    alembic upgrade head
  )
else
  fail "neither softpower_streamlit-api image nor host 'alembic' is available; build the image or install requirements.txt"
fi

# ----- done ----------------------------------------------------------------
cat <<EOF

\033[1;32m[dev-db-up]\033[0m test DB is ready.

  container : $TEST_CONTAINER
  database  : $TEST_DB_NAME
  host port : $TEST_PORT
  volume    : $TEST_VOLUME

To point the agent workflow at it from the host, export:

  export DB_HOST=localhost
  export DB_PORT=$TEST_PORT
  export POSTGRES_DB=$TEST_DB_NAME
  export POSTGRES_USER=$POSTGRES_USER
  export POSTGRES_PASSWORD=$POSTGRES_PASSWORD

Or from inside the docker network (e.g. an api container), use:
  DB_HOST=$TEST_CONTAINER  DB_PORT=5432

Quick smoke test (from another shell, with the env vars above and your
LLM API key set):

  uvicorn server.main:app --host 0.0.0.0 --port 8001 --reload
  curl -X POST http://localhost:8001/api/agent/workflows/report \\
    -H 'content-type: application/json' \\
    -d '{"recipient":"Egypt","influencer":"China","start_date":"2024-01-01","end_date":"2024-03-31"}' \\
    | jq '.status, .steps[] | {stage_name, status, summary}'

When done, tear it down:  scripts/dev_db_down.sh
EOF
