#!/usr/bin/env bash
# =====================================================================
# Start postgres + redis + FastAPI under supervisord.
# Foreground process — Ctrl-C or `kill <pid>` shuts everything down.
# Run via nohup or a tmux session if you want it detached.
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.enclave"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Run setup.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${ENCLAVE_DATA:?ENCLAVE_DATA not set}"
: "${CONDA_ENV_NAME:=softpower}"
: "${PGPORT:=5432}"
: "${REDIS_PORT:=6379}"
: "${API_HOST:=0.0.0.0}"
: "${API_PORT:=8000}"
: "${UVICORN_WORKERS:=4}"

# Paths consumed by supervisord.conf via %(ENV_*)s interpolation.
export APP_ROOT
export PGDATA="$ENCLAVE_DATA/pgdata"
export LOG_DIR="$ENCLAVE_DATA/logs"
export RUN_DIR="$ENCLAVE_DATA/run"
export REDIS_CONF="$SCRIPT_DIR/redis.conf"
export PGPORT REDIS_PORT API_HOST API_PORT UVICORN_WORKERS ENCLAVE_DATA

mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
    echo "ERROR: postgres data dir not initialized. Run setup.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV_NAME"

echo "[start] launching supervisord (postgres, redis, fastapi)"
echo "[start] logs: $LOG_DIR"
echo "[start] FastAPI on $API_HOST:$API_PORT"

exec supervisord -c "$SCRIPT_DIR/supervisord.conf" -n
