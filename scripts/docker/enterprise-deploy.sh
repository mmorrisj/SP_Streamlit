#!/usr/bin/env bash
# ============================================
# SoftPower Analytics — Enterprise Deploy (hosted PostgreSQL)
# ============================================
#
# Deploys the app + Redis against an enterprise-managed PostgreSQL service
# (e.g. internal pg18 + pgvector) using docker-compose.enterprise.yml.
# There is NO database container — the DB lives on the hosted service.
#
# What it does:
#   1. Loads .env and validates required vars (including DB_HOST).
#   2. Pre-flight: confirms the hosted DB is reachable and that the
#      `vector` and `pg_trgm` extensions are enabled in the target database.
#   3. Runs Alembic migrations against the hosted DB (--profile migrate).
#   4. Starts the stack (redis + app) with `docker compose up -d`.
#   5. Prints status.
#
# Pre-flight uses host-native psql/pg_isready when available, and otherwise
# falls back to a psycopg2 check inside the app image. Use --skip-checks to
# bypass pre-flight, and --no-migrate to skip migrations.
#
# Usage:
#   scripts/docker/enterprise-deploy.sh                 # full deploy
#   scripts/docker/enterprise-deploy.sh check           # pre-flight only
#   scripts/docker/enterprise-deploy.sh migrate         # migrations only
#   scripts/docker/enterprise-deploy.sh start           # start stack only
#   scripts/docker/enterprise-deploy.sh stop            # stop stack
#   scripts/docker/enterprise-deploy.sh status          # show status
#   scripts/docker/enterprise-deploy.sh logs [service]  # tail logs
#
# Flags (for the default/deploy command):
#   --skip-checks   Skip DB connectivity / extension pre-flight
#   --no-migrate    Do not run Alembic migrations
# ============================================

set -euo pipefail

# Prevent MSYS/Git Bash on Windows from mangling Unix paths in docker -e flags
export MSYS_NO_PATHCONV=1

# Colors
GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Resolve repo root (script lives in scripts/docker/) and run from there so
# relative paths (.env, docker-compose.enterprise.yml, ./reports) resolve.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="docker-compose.enterprise.yml"
APP_IMAGE_DEFAULT="mmorrisj/softpower-analytics:1.8.6"

# ============================================
# Load .env
# ============================================
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|\#*) continue ;; esac
        case "$line" in *=*) ;; *) continue ;; esac
        key="${line%%=*}"; value="${line#*=}"
        key="$(echo "$key" | xargs)"
        case "$key" in \#*|'') continue ;; esac
        case "$value" in
            \"*\") value="${value#\"}"; value="${value%\"}" ;;
            \'*\') value="${value#\'}"; value="${value%\'}" ;;
        esac
        export "$key=$value"
    done < .env
else
    log_warn ".env not found in $REPO_ROOT — relying on exported environment variables."
fi

POSTGRES_USER="${POSTGRES_USER:-}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_DB="${POSTGRES_DB:-}"
DB_HOST="${DB_HOST:-${POSTGRES_HOST:-}}"
DB_PORT="${DB_PORT:-${POSTGRES_PORT:-5432}}"
APP_IMAGE="${APP_IMAGE:-$APP_IMAGE_DEFAULT}"
API_PORT="${API_PORT:-8000}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

# Export so docker compose interpolation sees the resolved values
export DB_HOST DB_PORT APP_IMAGE

# ============================================
# Helpers
# ============================================
require_vars() {
    local missing=""
    [ -z "$POSTGRES_USER" ]     && missing="$missing POSTGRES_USER"
    [ -z "$POSTGRES_PASSWORD" ] && missing="$missing POSTGRES_PASSWORD"
    [ -z "$POSTGRES_DB" ]       && missing="$missing POSTGRES_DB"
    [ -z "$DB_HOST" ]           && missing="$missing DB_HOST"
    if [ -n "$missing" ]; then
        log_error "Required variables not set:$missing"
        log_info  "Set them in .env (DB_HOST must point at the hosted PostgreSQL service)."
        exit 1
    fi
}

check_docker() {
    command -v docker >/dev/null 2>&1 || { log_error "Docker is not installed or not in PATH"; exit 1; }
    docker info >/dev/null 2>&1 || { log_error "Docker daemon not running. Try: sudo systemctl start docker"; exit 1; }
}

# docker compose vs docker-compose
compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$COMPOSE_FILE" "$@"
    else
        docker-compose -f "$COMPOSE_FILE" "$@"
    fi
}

_have_native_pg() { command -v psql >/dev/null 2>&1 && command -v pg_isready >/dev/null 2>&1; }

# Run a single SQL statement against the hosted DB, printing a bare result.
# Prefers host-native psql; falls back to psql inside the app image (no --rm
# so container teardown setns is never triggered on hardened daemons).
_psql_scalar() {
    local sql="$1"
    if _have_native_pg; then
        PGPASSWORD="$POSTGRES_PASSWORD" psql \
            -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "$sql" 2>/dev/null
    else
        docker run --name "sp_ent_psql_$(date +%s%N)" --network host \
            -e PGPASSWORD="$POSTGRES_PASSWORD" "$APP_IMAGE" \
            psql -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "$sql" 2>/dev/null
    fi
}

# ============================================
# Commands
# ============================================
cmd_check() {
    require_vars
    log_info "Pre-flight against hosted PostgreSQL ${DB_HOST}:${DB_PORT}/${POSTGRES_DB}"

    # 1) Reachability
    local one
    one="$(_psql_scalar 'SELECT 1;' || true)"
    if [ "$one" != "1" ]; then
        log_error "Cannot connect to ${DB_HOST}:${DB_PORT} as '${POSTGRES_USER}' (db '${POSTGRES_DB}')."
        log_info  "Verify the host/port/credentials, network reachability, and TLS settings."
        log_info  "If the hosted service requires TLS, keep ENVIRONMENT=production (sslmode=require)."
        exit 1
    fi
    log_ok "Database reachable."

    # 2) Required extensions
    local missing_ext=""
    for ext in vector pg_trgm; do
        local present
        present="$(_psql_scalar "SELECT 1 FROM pg_extension WHERE extname = '${ext}';" || true)"
        if [ "$present" = "1" ]; then
            log_ok "Extension '${ext}' enabled."
        else
            missing_ext="$missing_ext $ext"
        fi
    done
    if [ -n "$missing_ext" ]; then
        log_error "Missing extension(s) in '${POSTGRES_DB}':$missing_ext"
        log_info  "Enable them (as a user with rights), then re-run:"
        for ext in $missing_ext; do
            log_info  "  CREATE EXTENSION IF NOT EXISTS ${ext};"
        done
        exit 1
    fi
    log_ok "Pre-flight passed."
}

cmd_migrate() {
    require_vars
    log_info "Running Alembic migrations against ${DB_HOST}:${DB_PORT}/${POSTGRES_DB}"
    # The migrate service exits when done; run it in the foreground and
    # propagate its exit code so a failed migration fails the deploy.
    compose --profile migrate up --no-log-prefix \
        --abort-on-container-exit --exit-code-from migrate migrate
    # Best-effort cleanup of the exited migrate container (ignore setns failures).
    docker rm sp_ent_migrate >/dev/null 2>&1 || true
    log_ok "Migrations complete."
}

cmd_start() {
    require_vars
    log_info "Starting enterprise stack (redis + app)..."
    compose up -d redis app
    log_ok "Stack started."
    cmd_status || true
    log_info "FastAPI:   http://127.0.0.1:${API_PORT}"
    log_info "Streamlit: http://127.0.0.1:${STREAMLIT_PORT}"
}

cmd_stop() {
    log_info "Stopping enterprise stack (hosted DB is untouched)..."
    compose stop redis app || true
    log_ok "Stack stopped."
}

cmd_status() {
    compose ps
}

cmd_logs() {
    local svc="${1:-}"
    if [ -n "$svc" ]; then
        compose logs -f --tail=100 "$svc"
    else
        compose logs -f --tail=100 app
    fi
}

cmd_deploy() {
    local skip_checks="false" do_migrate="true"
    for arg in "$@"; do
        case "$arg" in
            --skip-checks) skip_checks="true" ;;
            --no-migrate)  do_migrate="false" ;;
            *) log_warn "Unknown flag: $arg" ;;
        esac
    done

    check_docker
    require_vars
    log_info "Enterprise deploy → hosted PostgreSQL ${DB_HOST}:${DB_PORT}/${POSTGRES_DB}"

    [ "$skip_checks" = "true" ] && log_warn "Skipping pre-flight checks (--skip-checks)" || cmd_check
    [ "$do_migrate" = "true" ]  && cmd_migrate || log_warn "Skipping migrations (--no-migrate)"
    cmd_start
    log_ok "Enterprise deploy complete."
}

usage() {
    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ============================================
# Dispatch
# ============================================
check_docker
cmd="${1:-deploy}"
[ $# -gt 0 ] && shift || true
case "$cmd" in
    deploy)  cmd_deploy "$@" ;;
    check)   cmd_check ;;
    migrate) cmd_migrate ;;
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    logs)    cmd_logs "$@" ;;
    -h|--help|help) usage ;;
    *) log_error "Unknown command: $cmd"; echo; usage; exit 1 ;;
esac
