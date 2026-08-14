#!/usr/bin/env bash
# =====================================================================
# Soft Power Analytics – enclave one-shot setup
# =====================================================================
# Idempotent: safe to re-run. Performs:
#   1. Create the conda env from environment.yml (if missing)
#   2. Initialize the postgres data directory at $ENCLAVE_DATA/pgdata
#   3. Start postgres temporarily, create the database + pgvector ext
#   4. Run alembic migrations to head
#   5. Stop the temporary postgres
#
# Models must already be extracted to $HF_HOME before the app runs.
# This script does NOT extract them — see the "Extract baked models"
# section in the deployment notes.
#
# Usage:
#   cp .env.enclave.example .env.enclave   # then edit
#   ./setup.sh
#
# Run from any cwd; uses $SCRIPT_DIR-relative paths.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.enclave"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Copy .env.enclave.example and edit." >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${ENCLAVE_DATA:?ENCLAVE_DATA must be set in .env.enclave}"
: "${POSTGRES_USER:?POSTGRES_USER must be set in .env.enclave}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env.enclave}"
: "${POSTGRES_DB:?POSTGRES_DB must be set in .env.enclave}"
: "${PGPORT:=5432}"
: "${CONDA_ENV_NAME:=softpower}"

PGDATA="$ENCLAVE_DATA/pgdata"
LOG_DIR="$ENCLAVE_DATA/logs"
RUN_DIR="$ENCLAVE_DATA/run"
REDIS_DATA_DIR="$ENCLAVE_DATA/redis"

mkdir -p "$ENCLAVE_DATA" "$LOG_DIR" "$RUN_DIR" "$REDIS_DATA_DIR"

# ---- 1. Conda env ---------------------------------------------------
echo "[setup] checking conda env: $CONDA_ENV_NAME"
if ! command -v conda >/dev/null 2>&1; then
    echo "ERROR: conda not on PATH" >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV_NAME"; then
    echo "[setup] creating conda env from environment.yml (this can take 10-20 min)"
    conda env create -n "$CONDA_ENV_NAME" -f "$SCRIPT_DIR/environment.yml"
else
    echo "[setup] conda env $CONDA_ENV_NAME already exists; skipping create"
fi

conda activate "$CONDA_ENV_NAME"

# ---- 2. Postgres initdb --------------------------------------------
if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
    echo "[setup] initializing postgres at $PGDATA"
    initdb -D "$PGDATA" \
        --auth-local=trust \
        --auth-host=scram-sha-256 \
        --username="$POSTGRES_USER" \
        --encoding=UTF8 \
        --no-locale

    {
        echo ""
        echo "# enclave overrides"
        echo "listen_addresses = '127.0.0.1'"
        echo "port = $PGPORT"
        echo "unix_socket_directories = '$RUN_DIR'"
        echo "shared_buffers = 256MB"
        echo "max_connections = 100"
    } >> "$PGDATA/postgresql.conf"
else
    echo "[setup] postgres data dir already initialized; skipping initdb"
fi

# ---- 3. Start temp postgres, set password, create DB + extension ---
echo "[setup] starting postgres for one-shot setup"
pg_ctl -D "$PGDATA" \
    -l "$LOG_DIR/pg_setup.log" \
    -o "-h 127.0.0.1 -p $PGPORT -k $RUN_DIR" \
    -w start

cleanup_pg() {
    pg_ctl -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
}
trap cleanup_pg EXIT

# Set/refresh password (idempotent — always rewrites).
# Double single quotes so passwords containing ' don't break the SQL.
ESCAPED_PW="${POSTGRES_PASSWORD//\'/\'\'}"
psql -h "$RUN_DIR" -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "ALTER USER \"$POSTGRES_USER\" WITH PASSWORD '$ESCAPED_PW';"
unset ESCAPED_PW

# Create DB if missing.
if ! psql -h "$RUN_DIR" -U "$POSTGRES_USER" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'" | grep -qx 1; then
    echo "[setup] creating database $POSTGRES_DB"
    createdb -h "$RUN_DIR" -U "$POSTGRES_USER" "$POSTGRES_DB"
else
    echo "[setup] database $POSTGRES_DB already exists"
fi

# Install pgvector extension (idempotent).
psql -h "$RUN_DIR" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c \
    "CREATE EXTENSION IF NOT EXISTS vector;"

# ---- 4. Alembic migrations -----------------------------------------
echo "[setup] running alembic migrations"
cd "$APP_ROOT"
PYTHONPATH="$APP_ROOT" alembic upgrade head

# ---- 5. Sanity warnings on missing model files ---------------------
NOMIC_MARKER="$HF_HOME/models/nomic-embed-text-v1.5/modules.json"
if [[ -n "${HF_HOME:-}" && ! -f "$NOMIC_MARKER" ]]; then
    cat >&2 <<EOF

WARNING: nomic embedding model not found at:
  $NOMIC_MARKER

Extract it from the Docker image (on a host that can pull the image):
  docker pull mmorrisj/softpower-analytics:<tag>
  docker create --name extract mmorrisj/softpower-analytics:<tag>
  docker cp extract:/app/.cache/huggingface/. \$HF_HOME/
  docker cp extract:/app/.cache/tiktoken/. \$TIKTOKEN_CACHE_DIR/
  docker rm extract

Then move \$HF_HOME and \$TIKTOKEN_CACHE_DIR into the enclave's persistent storage.
EOF
fi

echo "[setup] done. Start services with: ./start.sh"
