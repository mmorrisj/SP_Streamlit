#!/usr/bin/env bash
# Gracefully stop a running supervisord (and all its child processes)
# started by start.sh. Looks up the pid from $RUN_DIR/supervisord.pid.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.enclave"

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
: "${ENCLAVE_DATA:?ENCLAVE_DATA not set}"

PIDFILE="$ENCLAVE_DATA/run/supervisord.pid"
if [[ ! -f "$PIDFILE" ]]; then
    echo "[stop] no pidfile at $PIDFILE — nothing to stop"
    exit 0
fi

PID="$(cat "$PIDFILE")"
if ! kill -0 "$PID" 2>/dev/null; then
    echo "[stop] pid $PID not running; removing stale pidfile"
    rm -f "$PIDFILE"
    exit 0
fi

echo "[stop] sending SIGTERM to supervisord pid $PID"
kill -TERM "$PID"

# Wait up to 30s for graceful shutdown.
for _ in $(seq 1 30); do
    kill -0 "$PID" 2>/dev/null || { echo "[stop] stopped"; exit 0; }
    sleep 1
done

echo "[stop] still alive after 30s; sending SIGKILL"
kill -KILL "$PID" || true
rm -f "$PIDFILE"
