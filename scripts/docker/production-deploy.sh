#!/bin/bash
# ============================================
# Production Deployment Script
# Run this ON the production target system.
# No docker-compose required — raw docker only.
# ============================================
# Usage: ./production-deploy.sh [start|stop|restart|migrate|status|load|backup|restore|psql|import|rebuild-db]
# ============================================
#
# Enterprise / kiosk daemon compatibility:
#   The script avoids `docker exec`, `docker cp`, `docker rm` of existing
#   containers, `docker run --rm`, and custom Docker networks — operations
#   that fail with `setns: permission denied` on hardened daemons.
#
#   All runtime paths (start, stop, restart, migrate, backup, restore, psql,
#   status, logs, import, rebuild-db) use:
#     * --network host on every container (no bridge networks)
#     * docker start || docker run pattern for idempotent service launches
#     * Host-native psql / pg_dump / pg_restore over TCP to 127.0.0.1:$DB_PORT
#       when those binaries are present (falls back to no-rm container if not)
#     * docker stop without docker rm; stopped containers are left in place
#       and reused by docker start on next launch
#
#   The cmd_setup subcommand (image preparation with ML wheels) is the only
#   path that requires docker cp / docker rm — it's intended for permissive
#   build hosts, not the enterprise deployment target. Use a pre-baked
#   registry image (mmorrisj/softpower-analytics:latest) on enterprise.
# ============================================

set -e

# Prevent MSYS/Git Bash on Windows from mangling Unix paths in docker -e flags
# (e.g. /var/lib/postgresql → C:/Program Files/Git/var/lib/postgresql)
export MSYS_NO_PATHCONV=1

# Colors (ANSI escape sequences)
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ============================================
# Configuration
# ============================================

# Load from .env if available, otherwise use defaults
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip blank lines and comments
        case "$line" in
            ''|\#*) continue ;;
        esac
        # Skip lines without an = sign
        case "$line" in
            *=*) ;;
            *) continue ;;
        esac
        # Split on first = only
        key="${line%%=*}"
        value="${line#*=}"
        # Strip leading/trailing whitespace from key
        key="$(echo "$key" | xargs)"
        # Skip keys that start with # (indented comments)
        case "$key" in
            \#*|'') continue ;;
        esac
        # Strip surrounding quotes from value
        case "$value" in
            \"*\") value="${value#\"}"; value="${value%\"}" ;;
            \'*\') value="${value#\'}"; value="${value%\'}" ;;
        esac
        export "$key=$value"
    done < .env
fi

POSTGRES_USER="${POSTGRES_USER:-}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_DB="${POSTGRES_DB:-}"
DB_PORT="${DB_PORT:-5432}"
API_PORT="${API_PORT:-8000}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

# Validate required database credentials
_missing_vars=""
[ -z "$POSTGRES_USER" ] && _missing_vars="$_missing_vars POSTGRES_USER"
[ -z "$POSTGRES_PASSWORD" ] && _missing_vars="$_missing_vars POSTGRES_PASSWORD"
[ -z "$POSTGRES_DB" ] && _missing_vars="$_missing_vars POSTGRES_DB"
if [ -n "$_missing_vars" ]; then
    log_error "Required environment variables not set:$_missing_vars"
    log_info "Set them in your .env file or export them before running this script."
    exit 1
fi

# LLM/S3 Proxy Relay
# The container lacks certificate authorizations to call external APIs directly.
# LLM and S3 requests are proxied through a host-side FastAPI on LLM_PROXY_PORT.
# Set LLM_PROXY_PORT=0 to disable (container calls APIs directly).
LLM_PROXY_PORT="${LLM_PROXY_PORT:-7001}"

# Deployment mode: "production" or "standard"
# production = TRANSFORMERS_OFFLINE=1, HF_HUB_OFFLINE=1 (no network access to HuggingFace)
# standard = TRANSFORMERS_OFFLINE=0, HF_HUB_OFFLINE=0 (model still baked in, but can reach out)
DEPLOY_MODE="${DEPLOY_MODE:-production}"

if [ "$DEPLOY_MODE" = "production" ]; then
    TRANSFORMERS_OFFLINE=1
    HF_HUB_OFFLINE=1
else
    TRANSFORMERS_OFFLINE=0
    HF_HUB_OFFLINE=0
fi

# Image type: "registry" (self-contained, ML baked in) or "slim" (needs setup + hf_model)
# "registry" images are pulled from Docker Hub (mmorrisj/softpower-analytics:X.Y.Z)
# "slim" images are built locally by production-build.sh (softpower-app-production:latest)
# Default: auto-detect from PRODUCTION_REGISTRY or APP_IMAGE
IMAGE_TYPE="${IMAGE_TYPE:-auto}"

# Allow direct image name override (highest priority)
APP_IMAGE="${APP_IMAGE:-}"
DB_IMAGE="${DB_IMAGE:-}"
APP_VERSION="${APP_VERSION:-latest}"

# Auto-detect IMAGE_TYPE if set to "auto"
if [ "$IMAGE_TYPE" = "auto" ]; then
    if [ -n "$APP_IMAGE" ] && echo "$APP_IMAGE" | grep -q "softpower-analytics"; then
        IMAGE_TYPE="registry"
    elif [ -n "$PRODUCTION_REGISTRY" ]; then
        IMAGE_TYPE="registry"
    else
        IMAGE_TYPE="slim"
    fi
fi

# Build image names from PRODUCTION_REGISTRY if not explicitly set
if [ -z "$DB_IMAGE" ]; then
    if [ -n "$PRODUCTION_REGISTRY" ]; then
        DB_IMAGE="${PRODUCTION_REGISTRY}/pgvector:0.8.2-pg17"
    else
        DB_IMAGE="mmorrisj/pgvector:0.8.2-pg17"
    fi
fi

if [ -z "$APP_IMAGE" ]; then
    if [ "$IMAGE_TYPE" = "registry" ] && [ -n "$PRODUCTION_REGISTRY" ]; then
        APP_IMAGE="${PRODUCTION_REGISTRY}/softpower-analytics:${APP_VERSION}"
    elif [ -n "$PRODUCTION_REGISTRY" ]; then
        APP_IMAGE="${PRODUCTION_REGISTRY}/softpower-analytics:latest"
    else
        APP_IMAGE="softpower-analytics:latest"
    fi
fi

# HuggingFace model directory (sentence-transformers, mounted as volume)
# Default: hf_model/ next to this script (produced by production-build.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="${MODEL_DIR:-${SCRIPT_DIR}/hf_model}"

# Redis image (replace with enterprise hardened image on-site, e.g. dhi/redis:7)
REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}"

# Container names
DB_CONTAINER="sp_prod_db"
APP_CONTAINER="sp_prod_app"
REDIS_CONTAINER="sp_prod_redis"

# Networking: this script uses host networking (--network host) for every
# container. Custom Docker bridge networks require the daemon to bind-mount
# /proc/<pid>/ns/net into /var/run/docker/netns/, which fails on enterprise
# kiosk hosts with "permission denied". Host networking avoids that bind
# mount entirely. Inter-container traffic flows through 127.0.0.1:<port>.
DB_HOSTNAME="127.0.0.1"
REDIS_HOSTNAME="127.0.0.1"
REDIS_PORT="${REDIS_PORT:-6379}"

# Docker resources
DB_VOLUME="softpower_production_prod_pgdata"

# ============================================
# Helper Functions
# ============================================

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# URL-encode a string for use in DATABASE_URL (handles @, /, #, %, spaces, etc.)
urlencode() {
    python3 -c "import urllib.parse; print(urllib.parse.quote_plus('$1'))" 2>/dev/null \
        || printf '%s' "$1"  # Fallback: use raw value if python3 unavailable
}

# Build a properly-encoded DATABASE_URL from component env vars
build_database_url() {
    local encoded_user encoded_pass
    encoded_user=$(urlencode "$POSTGRES_USER")
    encoded_pass=$(urlencode "$POSTGRES_PASSWORD")
    echo "postgresql+psycopg2://${encoded_user}:${encoded_pass}@${1}:${2}/${POSTGRES_DB}"
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Try: sudo systemctl start docker"
        exit 1
    fi
}

# ----------------------------------------------------------------------------
# Host-native Postgres client wrappers
# ----------------------------------------------------------------------------
# On enterprise / kiosk hosts, `docker run --rm` triggers setns failures during
# container teardown. These helpers prefer the host's psql/pg_dump/pg_restore/
# pg_isready binaries when present (so DB admin ops happen over TCP, no
# setns). They fall back to `docker run` WITHOUT `--rm` on hosts where the
# native tools are unavailable — short-lived admin containers stay in `Exited`
# state but don't trigger the teardown setns.
#
# Connection always goes to 127.0.0.1:$DB_PORT (the DB container runs with
# --network host, so its port is on the host's loopback).
# ----------------------------------------------------------------------------

_have_native_pg() {
    command -v psql &>/dev/null && command -v pg_isready &>/dev/null
}

_pg_isready_host() {
    if _have_native_pg; then
        PGPASSWORD="$POSTGRES_PASSWORD" pg_isready \
            -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
    else
        # No --rm: container stays in Exited state on enterprise daemon, harmless.
        docker run --name "sp_pgcheck_$(date +%s%N)" --network host \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            pg_isready -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
    fi
}

_psql_host() {
    if _have_native_pg; then
        PGPASSWORD="$POSTGRES_PASSWORD" psql \
            -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" "$@"
    else
        docker run --name "sp_psql_$(date +%s%N)" --network host \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            psql -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" "$@"
    fi
}

_pg_dump_host() {
    if command -v pg_dump &>/dev/null; then
        PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
            -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" "$@"
    else
        docker run --name "sp_pgdump_$(date +%s%N)" --network host \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            pg_dump -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" "$@"
    fi
}

_pg_restore_host() {
    if command -v pg_restore &>/dev/null; then
        PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
            -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" "$@"
    else
        docker run -i --name "sp_pgrestore_$(date +%s%N)" --network host \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            pg_restore -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" "$@"
    fi
}

# Try `docker rm` but don't fail if the daemon blocks it (setns enforcement).
# Use this instead of bare `docker rm` everywhere — keeps the script
# operational on hosts where existing-container removal is forbidden.
_docker_rm_best_effort() {
    docker rm "$@" 2>/dev/null || \
        log_warn "Could not remove $* (likely setns-blocked); ignoring. Stopped container remains."
}

wait_for_db() {
    log_info "Waiting for PostgreSQL to be ready..."
    local max_attempts=30
    for i in $(seq 1 $max_attempts); do
        if _pg_isready_host > /dev/null 2>&1; then
            log_ok "PostgreSQL is ready"
            return 0
        fi
        echo "  Waiting... ($i/$max_attempts)"
        sleep 2
    done
    log_error "PostgreSQL did not become ready in time"
    return 1
}

wait_for_api() {
    log_info "Waiting for API to be healthy..."
    local max_attempts=30
    for i in $(seq 1 $max_attempts); do
        if curl -sf http://127.0.0.1:${API_PORT}/api/health > /dev/null 2>&1; then
            log_ok "API is healthy"
            return 0
        fi
        echo "  Waiting... ($i/$max_attempts)"
        sleep 2
    done
    log_warn "API health check timed out (may still be starting)"
    return 1
}

container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${1}$"
}

container_exists() {
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${1}$"
}

# ============================================
# Setup: Install heavy ML packages from wheels
# ============================================
cmd_setup() {
    echo ""
    echo "=============================================="
    echo "Installing ML packages from local wheels"
    echo "=============================================="
    echo ""

    # NOTE: cmd_setup uses `docker cp` and `docker commit` to install ML deps
    # into a slim image. Both `docker cp` and `docker rm` of the build container
    # are blocked on enterprise/kiosk daemons with setns enforcement. This
    # subcommand is intended for IMAGE PREPARATION on a permissive build host,
    # not for runtime deployment on the enterprise host. On the enterprise host,
    # use a pre-baked registry image (mmorrisj/softpower-analytics:latest) and
    # skip this subcommand entirely.

    # Registry images already have ML packages baked in — skip setup
    if [ "$IMAGE_TYPE" = "registry" ]; then
        log_ok "Registry image detected: $APP_IMAGE"
        log_ok "ML packages (torch, sentence-transformers, langchain-huggingface) are already baked in"
        log_info "The 'setup' step is only needed for slim images built by production-build.sh"
        echo ""
        echo "Next steps:"
        echo "  ./production-deploy.sh start"
        echo "  ./production-deploy.sh migrate  (or restore from dump)"
        echo ""
        return 0
    fi

    # Locate wheels directory (next to this script)
    local wheels_dir="${SCRIPT_DIR}/wheels"
    if [ ! -d "$wheels_dir" ]; then
        log_error "Wheels directory not found: $wheels_dir"
        log_info "Expected: wheels/ directory produced by production-build.sh"
        exit 1
    fi

    local wheel_count
    wheel_count=$(ls -1 "$wheels_dir"/*.whl 2>/dev/null | wc -l)
    if [ "$wheel_count" -eq 0 ]; then
        log_error "No .whl files found in $wheels_dir"
        exit 1
    fi

    # Locate requirements file (packages to install from wheels)
    local req_file="${SCRIPT_DIR}/requirements-production-heavy.txt"
    if [ ! -f "$req_file" ]; then
        log_warn "requirements-production-heavy.txt not found, using built-in package list"
        req_file=""
    fi

    # Verify the slim image is loaded
    if ! docker image inspect "$APP_IMAGE" &>/dev/null; then
        log_error "App image not found: $APP_IMAGE"
        log_info "Run './production-deploy.sh load ./images' first"
        exit 1
    fi

    log_info "Found $wheel_count wheel files in $wheels_dir"
    log_info "Installing into $APP_IMAGE (this may take a minute)..."
    echo ""

    # Build the pip install command.
    # Prefer requirements-production-heavy.txt (versioned, matches what build downloaded)
    # with a hard-coded fallback for backwards compatibility.
    local pip_cmd="pip install --no-cache-dir --no-index --find-links /wheels"
    if [ -n "$req_file" ]; then
        pip_cmd="$pip_cmd -r /requirements-production-heavy.txt"
    else
        pip_cmd="$pip_cmd torch sentence-transformers langchain-huggingface"
    fi

    # Create temp container, copy wheels in, pip install, then commit.
    # Uses docker cp instead of volume mounts for cross-platform compatibility.
    local setup_container="softpower_setup_$$"
    docker rm -f "$setup_container" 2>/dev/null || true

    docker create --name "$setup_container" \
        "$APP_IMAGE" \
        bash -c "$pip_cmd"

    docker cp "$wheels_dir" "$setup_container":/wheels
    if [ -n "$req_file" ]; then
        docker cp "$req_file" "$setup_container":/requirements-production-heavy.txt
    fi
    docker start -a "$setup_container"

    # Commit the container as the updated image
    docker commit "$setup_container" "$APP_IMAGE"
    docker rm "$setup_container"

    echo ""
    log_ok "ML packages installed into $APP_IMAGE"
    log_info "Image size: $(docker images "$APP_IMAGE" --format '{{.Size}}')"

    # Verify ML packages are importable in the committed image
    echo ""
    log_info "Verifying ML package installation..."
    if docker run --rm "$APP_IMAGE" python3 -c \
        "import torch; import sentence_transformers; import langchain_huggingface; print('OK')" \
        2>/dev/null | grep -q "OK"; then
        log_ok "ML packages verified: torch, sentence-transformers, langchain-huggingface"
    else
        log_error "ML package verification FAILED — imports did not succeed"
        log_info "Check the pip install output above for errors"
        log_info "You may need to re-run: ./production-deploy.sh setup"
        exit 1
    fi

    echo ""
    echo "Next steps:"
    echo "  ./production-deploy.sh start"
    echo "  ./production-deploy.sh migrate"
    echo ""
}

# ============================================
# Load Images from tar files
# ============================================
cmd_load() {
    echo ""
    echo "=============================================="
    echo "Loading Docker Images from tar files"
    echo "=============================================="
    echo ""

    local image_dir="${1:-.}"

    if [ ! -d "$image_dir" ]; then
        log_error "Image directory not found: $image_dir"
        log_info "Usage: $0 load ./images"
        exit 1
    fi

    # Load all tar files (softpower app images + pgvector)
    local loaded=0
    for tarfile in "$image_dir"/*.tar; do
        if [ -f "$tarfile" ]; then
            log_info "Loading $(basename "$tarfile")..."
            docker load -i "$tarfile"
            log_ok "Loaded $(basename "$tarfile")"
            loaded=$((loaded + 1))
        fi
    done

    if [ "$loaded" -eq 0 ]; then
        log_error "No .tar files found in $image_dir"
        # Check for packed (base64-encoded) images that need unpacking first
        local b64_count
        b64_count=$(ls -1 "$image_dir"/*.b64.txt 2>/dev/null | wc -l)
        if [ "$b64_count" -gt 0 ]; then
            log_info "Found $b64_count .b64.txt file(s) — images are still packed for transfer"
            log_info "Run 'python3 unpack-production.py --apply' first to decode them"
        else
            log_info "Expected: pgvector-pg16.tar and softpower-app-production.tar"
            log_info "Re-run production-build.sh to regenerate the package"
        fi
        exit 1
    fi

    echo ""
    log_ok "Loaded $loaded image(s)"
    log_info "Current images:"
    docker images | grep -E "softpower|pgvector|REPOSITORY" || true
    echo ""
}

# ============================================
# Start Services
# ============================================
cmd_start() {
    echo ""
    echo "=============================================="
    echo "SoftPower Analytics - Production Deployment"
    echo "=============================================="
    echo ""

    check_docker

    # Verify images exist (try pulling from registry if not local)
    for img in "$DB_IMAGE" "$APP_IMAGE"; do
        if docker image inspect "$img" &>/dev/null; then
            log_ok "Image found: $img"
        elif [ -n "$PRODUCTION_REGISTRY" ] && [ "$DEPLOY_MODE" != "production" ]; then
            log_info "Pulling $img from registry..."
            if docker pull "$img"; then
                log_ok "Pulled: $img"
            else
                log_error "Failed to pull: $img"
                exit 1
            fi
        else
            log_error "Image not found: $img"
            log_info "Run './production-deploy.sh load' first to load images from tar files"
            exit 1
        fi
    done

    log_ok "Network: host (containers share host network namespace)"

    # Create volume
    if ! docker volume inspect "$DB_VOLUME" &>/dev/null; then
        log_info "Creating Docker volume: $DB_VOLUME"
        docker volume create "$DB_VOLUME"
    fi
    log_ok "Volume: $DB_VOLUME"

    # --- Start PostgreSQL ---
    if container_running "$DB_CONTAINER"; then
        log_ok "Database already running"
    elif container_exists "$DB_CONTAINER" && docker start "$DB_CONTAINER" >/dev/null 2>&1; then
        log_ok "Restarted existing database container (no setns required)"
    else
        # No existing container, or start failed — create fresh.
        # On enterprise daemons docker rm of an existing stopped container is
        # blocked; we best-effort it and proceed (docker run will fail if the
        # name is still in use, in which case the user must rename).
        if container_exists "$DB_CONTAINER"; then
            log_info "Removing stopped database container..."
            _docker_rm_best_effort "$DB_CONTAINER"
        fi

        log_info "Starting PostgreSQL + pgvector..."
        docker run -d \
            --name "$DB_CONTAINER" \
            --network host \
            --restart unless-stopped \
            --security-opt no-new-privileges:true \
            --cap-drop ALL \
            --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
            --cap-add SETGID --cap-add SETUID \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e PGDATA=/var/lib/postgresql/data/pgdata \
            -e PGPORT="$DB_PORT" \
            -v "$DB_VOLUME":/var/lib/postgresql/data \
            --shm-size=1g \
            "$DB_IMAGE"

        log_ok "PostgreSQL container started"
    fi

    wait_for_db

    # --- Credential drift guard ---
    # PostgreSQL only applies POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB on
    # first initdb.  If the volume already contains an initialized database,
    # those env vars are silently ignored on subsequent starts.  Detect the
    # mismatch early and fix it so credentials in .env always work.
    log_info "Verifying database credentials match .env..."
    if _pg_isready_host > /dev/null 2>&1 \
    && _psql_host -d "$POSTGRES_DB" -c "SELECT 1" > /dev/null 2>&1; then
        log_ok "Database credentials verified"
    else
        log_warn "Credential mismatch detected — .env password differs from initialized database"
        log_info "This happens when POSTGRES_PASSWORD changed after the volume was first created."
        log_info "Attempting to update the database password to match .env..."

        # The recovery flow stops the main DB container and starts a transient
        # trust-auth container on the same volume. On enterprise daemons we
        # cannot `docker rm` the main container, so the transient runs under a
        # separate name. Once credentials are fixed in the volume, the trust
        # container is stopped and the main container is `docker start`'d
        # again with normal password auth.
        local trust_container="${DB_CONTAINER}_trust"

        docker stop "$DB_CONTAINER" > /dev/null 2>&1
        # If a stale trust container from a prior run is around, stop+best-effort-rm it.
        docker stop "$trust_container" > /dev/null 2>&1 || true
        _docker_rm_best_effort "$trust_container" > /dev/null 2>&1 || true

        # Start a SEPARATELY NAMED trust-auth container on the same volume
        docker run -d \
            --name "$trust_container" \
            --network host \
            -e PGDATA=/var/lib/postgresql/data/pgdata \
            -e PGPORT="$DB_PORT" \
            -v "$DB_VOLUME":/var/lib/postgresql/data \
            --shm-size=1g \
            "$DB_IMAGE" \
            postgres -c "authentication_timeout=30"

        # Wait for trust-auth container to be ready
        local fix_attempts=15
        for i in $(seq 1 $fix_attempts); do
            if _pg_isready_host > /dev/null 2>&1; then
                break
            fi
            sleep 2
        done

        # Discover the actual superuser name from pg_user
        local actual_user
        actual_user=$(PGPASSWORD="" _psql_host -d postgres \
            -tAc "SELECT usename FROM pg_user WHERE usesuper LIMIT 1" 2>/dev/null || echo "")

        if [ -z "$actual_user" ]; then
            for try_user in postgres "$POSTGRES_USER"; do
                actual_user=$(PGPASSWORD="" POSTGRES_USER="$try_user" _psql_host -d postgres \
                    -tAc "SELECT usename FROM pg_user WHERE usesuper LIMIT 1" 2>/dev/null || echo "")
                [ -n "$actual_user" ] && break
            done
        fi

        if [ -n "$actual_user" ]; then
            # Update password for the target user
            PGPASSWORD="" POSTGRES_USER="$actual_user" _psql_host -d postgres \
                -c "ALTER USER \"$POSTGRES_USER\" WITH PASSWORD '$POSTGRES_PASSWORD';" > /dev/null 2>&1

            # Create user if it doesn't exist
            PGPASSWORD="" POSTGRES_USER="$actual_user" _psql_host -d postgres \
                -c "DO \$\$ BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
                        CREATE USER \"$POSTGRES_USER\" WITH SUPERUSER PASSWORD '$POSTGRES_PASSWORD';
                    END IF;
                END \$\$;" > /dev/null 2>&1

            # Create database if it doesn't exist
            PGPASSWORD="" POSTGRES_USER="$actual_user" _psql_host -d postgres \
                -c "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'" 2>/dev/null | grep -q 1 || \
            PGPASSWORD="" POSTGRES_USER="$actual_user" _psql_host -d postgres \
                -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";" > /dev/null 2>&1

            log_ok "Credentials updated to match .env"
        else
            log_error "Could not connect to PostgreSQL to fix credentials"
            log_info "Manual fix: run './production-deploy.sh rebuild-db' to reset (DESTROYS DATA)"
            log_info "Or update .env to match the original credentials used when the volume was created"
        fi

        # Stop the trust-auth container and restart the main one with normal password auth
        docker stop "$trust_container" > /dev/null 2>&1
        _docker_rm_best_effort "$trust_container" > /dev/null 2>&1 || true

        # Re-start the main DB container (it already exists; docker start avoids setns)
        if ! docker start "$DB_CONTAINER" > /dev/null 2>&1; then
            # Container was removed previously (permissive daemon) — recreate
            docker run -d \
                --name "$DB_CONTAINER" \
                --network host \
                --restart unless-stopped \
                --security-opt no-new-privileges:true \
                --cap-drop ALL \
                --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
                --cap-add SETGID --cap-add SETUID \
                -e POSTGRES_USER="$POSTGRES_USER" \
                -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
                -e POSTGRES_DB="$POSTGRES_DB" \
                -e PGDATA=/var/lib/postgresql/data/pgdata \
                -e PGPORT="$DB_PORT" \
                -v "$DB_VOLUME":/var/lib/postgresql/data \
                --shm-size=1g \
                "$DB_IMAGE"
        fi

        wait_for_db

        # Final verification
        if _psql_host -d "$POSTGRES_DB" -c "SELECT 1" > /dev/null 2>&1; then
            log_ok "Credential fix verified — .env credentials now work"
        else
            log_error "Credential fix failed. Manual intervention required."
            log_info "Options:"
            log_info "  1. Update .env to match the original volume credentials"
            log_info "  2. Run './production-deploy.sh rebuild-db' (DESTROYS DATA)"
        fi
    fi

    # --- Start Redis ---
    if container_running "$REDIS_CONTAINER"; then
        log_ok "Redis already running"
    elif container_exists "$REDIS_CONTAINER" && docker start "$REDIS_CONTAINER" >/dev/null 2>&1; then
        log_ok "Restarted existing Redis container"
    else
        if container_exists "$REDIS_CONTAINER"; then
            log_info "Removing stopped Redis container..."
            _docker_rm_best_effort "$REDIS_CONTAINER"
        fi

        log_info "Starting Redis cache..."
        # Bind redis to 127.0.0.1 only — host networking exposes the port on
        # the host's network interface, and the app reaches it via loopback.
        docker run -d \
            --name "$REDIS_CONTAINER" \
            --network host \
            --restart unless-stopped \
            --security-opt no-new-privileges:true \
            --cap-drop ALL \
            --cap-add SETGID --cap-add SETUID \
            "$REDIS_IMAGE" \
            redis-server --bind 127.0.0.1 --port "$REDIS_PORT"

        # Wait for Redis to be ready — prefer host-native redis-cli or nc
        local redis_attempts=10
        for i in $(seq 1 $redis_attempts); do
            local is_up=0
            if command -v redis-cli &>/dev/null; then
                redis-cli -h "$REDIS_HOSTNAME" -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG && is_up=1
            elif command -v nc &>/dev/null; then
                nc -z "$REDIS_HOSTNAME" "$REDIS_PORT" 2>/dev/null && is_up=1
            else
                # Non-rm transient container as last resort
                docker run --name "sp_redischeck_$(date +%s%N)" --network host \
                    "$REDIS_IMAGE" redis-cli -h "$REDIS_HOSTNAME" -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG && is_up=1
            fi

            if [ "$is_up" = "1" ]; then
                log_ok "Redis is ready"
                break
            fi
            if [ "$i" -eq "$redis_attempts" ]; then
                log_warn "Redis did not respond — caching will be disabled (app continues without it)"
            fi
            sleep 1
        done
    fi

    # --- Start Application ---
    if container_running "$APP_CONTAINER"; then
        log_ok "Application already running"
    elif container_exists "$APP_CONTAINER" && docker start "$APP_CONTAINER" >/dev/null 2>&1; then
        log_ok "Restarted existing application container"
    else
        if container_exists "$APP_CONTAINER"; then
            log_info "Removing stopped application container..."
            _docker_rm_best_effort "$APP_CONTAINER"
        fi

        # Proxy config: if LLM_PROXY_PORT is set and non-zero, route LLM/S3
        # calls through a host-side proxy. Otherwise, the container calls APIs directly.
        # With host networking, the container shares the host's loopback, so the
        # proxy is reachable at 127.0.0.1 (no host.docker.internal hostname needed).
        if [ "$LLM_PROXY_PORT" != "0" ] && [ -n "$LLM_PROXY_PORT" ]; then
            PROXY_API_URL="http://127.0.0.1:${LLM_PROXY_PORT}"
            log_info "LLM/S3 proxy: 127.0.0.1:${LLM_PROXY_PORT}"
        else
            PROXY_API_URL="http://127.0.0.1:${API_PORT}"
            log_info "LLM/S3 proxy: disabled (container calls APIs directly)"
        fi

        # Registry images have ML + model baked in; slim images need external checks
        local VOLUME_FLAGS=""
        if [ "$IMAGE_TYPE" = "slim" ]; then
            # Verify HuggingFace model directory exists and contains model files
            if [ ! -d "$MODEL_DIR" ]; then
                log_error "HuggingFace model directory not found: $MODEL_DIR"
                log_info "The model is packaged in hf_model/ by production-build.sh"
                log_info "Set MODEL_DIR=/path/to/hf_model to override"
                exit 1
            fi
            # Check for the model marker files
            if [ ! -f "$MODEL_DIR/models/all-MiniLM-L6-v2/modules.json" ]; then
                log_error "Embedding model missing: $MODEL_DIR/models/all-MiniLM-L6-v2/modules.json"
                log_info "The hf_model/ directory exists but appears empty or incomplete"
                log_info "Re-run production-build.sh to regenerate the model export"
                exit 1
            fi
            if [ ! -f "$MODEL_DIR/models/ms-marco-MiniLM-L-6-v2/config.json" ]; then
                log_warn "Reranker model missing: $MODEL_DIR/models/ms-marco-MiniLM-L-6-v2/config.json"
                log_info "Reranking will be disabled. Re-run production-build.sh to include it."
            fi
            log_ok "Model dir: $MODEL_DIR (verified)"

            # Pre-flight: verify ML packages were installed (./production-deploy.sh setup)
            # No --rm: stopped container is harmless and avoids the teardown
            # setns failure on enterprise daemons.
            if ! docker run --name "sp_mlcheck_$(date +%s%N)" "$APP_IMAGE" \
                python3 -c "import sentence_transformers" 2>/dev/null; then
                log_error "ML packages not installed in $APP_IMAGE"
                log_info "Run './production-deploy.sh setup' first to install torch + sentence-transformers"
                exit 1
            fi
            log_ok "ML packages: installed"

            VOLUME_FLAGS="-v $(cd "$MODEL_DIR" && pwd):/app/.cache/huggingface"
        else
            log_ok "Registry image: ML packages + model baked in"
        fi

        log_info "Starting application (FastAPI + Streamlit)..."
        docker run -d \
            --name "$APP_CONTAINER" \
            --network host \
            --restart unless-stopped \
            --security-opt no-new-privileges:true \
            --cap-drop ALL \
            $VOLUME_FLAGS \
            -e DOCKER_ENV=true \
            -e NODE_ENV=production \
            -e DB_HOST="$DB_HOSTNAME" \
            -e DB_PORT="$DB_PORT" \
            -e POSTGRES_HOST="$DB_HOSTNAME" \
            -e POSTGRES_PORT="$DB_PORT" \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e DATABASE_URL="$(build_database_url "$DB_HOSTNAME" "$DB_PORT")" \
            -e API_PORT="$API_PORT" \
            -e STREAMLIT_PORT="$STREAMLIT_PORT" \
            -e DB_POOL_SIZE="${DB_POOL_SIZE:-10}" \
            -e DB_MAX_OVERFLOW="${DB_MAX_OVERFLOW:-20}" \
            -e DB_POOL_TIMEOUT="${DB_POOL_TIMEOUT:-30}" \
            -e DB_POOL_RECYCLE="${DB_POOL_RECYCLE:-3600}" \
            -e API_URL="$PROXY_API_URL" \
            -e S3_PROXY_URL="$PROXY_API_URL" \
            -e USE_S3_API_CLIENT="true" \
            -e TRANSFORMERS_OFFLINE="$TRANSFORMERS_OFFLINE" \
            -e HF_HUB_OFFLINE="$HF_HUB_OFFLINE" \
            -e HF_HOME="/app/.cache/huggingface" \
            -e SENTENCE_TRANSFORMERS_HOME="/app/.cache/huggingface/hub" \
            -e TIKTOKEN_CACHE_DIR="/app/.cache/tiktoken" \
            -e REDIS_URL="redis://${REDIS_HOSTNAME}:${REDIS_PORT}/0" \
            -e CLAUDE_KEY="${CLAUDE_KEY:-}" \
            -e OPENAI_PROJ_API="${OPENAI_PROJ_API:-}" \
            -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}" \
            -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}" \
            -e JWT_SECRET="${JWT_SECRET:-softpower-jwt-secret-change-in-production-min32chars}" \
            -e JWT_EXPIRATION_HOURS="${JWT_EXPIRATION_HOURS:-24}" \
            -e DEV_AUTH_BYPASS="${DEV_AUTH_BYPASS:-}" \
            -e DEV_AUTH_ROLE="${DEV_AUTH_ROLE:-admin}" \
            "$APP_IMAGE"

        log_ok "Application container started"
    fi

    wait_for_api

    echo ""
    echo "=============================================="
    echo -e "${GREEN}Deployment Complete${NC}"
    echo "=============================================="
    echo ""
    echo "Image type:   $IMAGE_TYPE"
    echo "Deploy mode:  $DEPLOY_MODE"
    echo "HF offline:   TRANSFORMERS_OFFLINE=$TRANSFORMERS_OFFLINE, HF_HUB_OFFLINE=$HF_HUB_OFFLINE"
    if [ "$IMAGE_TYPE" = "slim" ]; then
        echo "Model dir:    $MODEL_DIR"
    else
        echo "Model dir:    (baked into image)"
    fi
    echo "App image:    $APP_IMAGE"
    if [ "$LLM_PROXY_PORT" != "0" ] && [ -n "$LLM_PROXY_PORT" ]; then
        echo "LLM proxy:    127.0.0.1:${LLM_PROXY_PORT}"
    else
        echo "LLM proxy:    disabled (container calls APIs directly)"
    fi
    echo "Network:      host (containers share host network namespace)"
    echo ""
    echo "Access:"
    echo "  React Web App:    http://0.0.0.0:${API_PORT}"
    echo "  API Docs:         http://0.0.0.0:${API_PORT}/docs"
    echo "  Streamlit:        http://0.0.0.0:${STREAMLIT_PORT}"
    echo "  PostgreSQL:       0.0.0.0:${DB_PORT}"
    echo "  Redis cache:      127.0.0.1:${REDIS_PORT} (loopback only)"
    echo ""
    if [ "$LLM_PROXY_PORT" != "0" ] && [ -n "$LLM_PROXY_PORT" ]; then
        echo "LLM/S3 proxy prerequisite:"
        echo "  The host-side proxy must be running on port ${LLM_PROXY_PORT}."
        echo "  Start it with:  python llm_proxy.py"
        echo "  Or disable with: LLM_PROXY_PORT=0 in .env"
        echo ""
    fi
    echo "First-time setup:"
    echo "  ./production-deploy.sh migrate     # Run database migrations"
    echo ""
    echo "View logs:"
    echo "  docker logs -f $APP_CONTAINER  # Application logs"
    echo "  docker logs -f $DB_CONTAINER   # Database logs"
    echo ""
}

# ============================================
# Stop Services
# ============================================
cmd_stop() {
    echo ""
    log_info "Stopping services..."

    # On enterprise daemons docker rm of existing containers is blocked; we
    # stop them and leave the stopped record in place. The next `start` will
    # pick them up via `docker start` (no setns) rather than recreating.
    for container in "$APP_CONTAINER" "$REDIS_CONTAINER" "$DB_CONTAINER"; do
        if container_running "$container"; then
            docker stop "$container" >/dev/null 2>&1
            _docker_rm_best_effort "$container" >/dev/null 2>&1 || true
            log_ok "Stopped: $container"
        elif container_exists "$container"; then
            _docker_rm_best_effort "$container" >/dev/null 2>&1 || true
            log_info "Stopped container exists: $container (left in place if removal was blocked)"
        else
            log_info "Not running: $container"
        fi
    done

    echo ""
    log_ok "All services stopped"
    log_info "Data volume preserved: $DB_VOLUME"
    echo ""
}

# ============================================
# Run Migrations
# ============================================
cmd_migrate() {
    echo ""
    log_info "Running database migrations..."

    if ! container_running "$DB_CONTAINER"; then
        log_error "Database is not running. Start it first: ./production-deploy.sh start"
        exit 1
    fi

    # Transient migration container — no --rm (setns-safe on enterprise daemons).
    # The container exits after alembic completes; the stopped record is harmless.
    # Writes any missing merge migrations before running alembic upgrade head.
    docker run \
        --name "sp_migrate_$(date +%s)" \
        --network host \
        -e DOCKER_ENV=true \
        -e DB_HOST="$DB_HOSTNAME" \
        -e DB_PORT="$DB_PORT" \
        -e POSTGRES_USER="$POSTGRES_USER" \
        -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
        -e POSTGRES_DB="$POSTGRES_DB" \
        -e DATABASE_URL="$(build_database_url "$DB_HOSTNAME" "$DB_PORT")" \
        "$APP_IMAGE" \
        python3 -c "
import os, subprocess, sys

# --- Merge migration: 006_search_vector + 20260224_aiddata_tables ---
merge_path = '/app/alembic/versions/821886869aed_merge_search_vector_and_aiddata_branches.py'
if not os.path.exists(merge_path):
    with open(merge_path, 'w') as f:
        f.write('''\"\"\"merge search_vector and aiddata branches

Revision ID: 821886869aed
Revises: 006_search_vector, 20260224_aiddata_tables
Create Date: 2026-03-26 13:33:52.540352

\"\"\"
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = \"821886869aed\"
down_revision = (\"006_search_vector\", \"20260224_aiddata_tables\")
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
''')
    print('Injected merge migration for multiple heads fix')

sys.exit(subprocess.call(['alembic', 'upgrade', 'head'], cwd='/app'))
"

    log_ok "Migrations complete"
    echo ""
}

# ============================================
# Show Status
# ============================================
cmd_status() {
    echo ""
    echo "=============================================="
    echo "Service Status"
    echo "=============================================="
    echo ""

    # Check containers
    for container in "$DB_CONTAINER" "$REDIS_CONTAINER" "$APP_CONTAINER"; do
        if container_running "$container"; then
            log_ok "$container is running"
        elif container_exists "$container"; then
            log_warn "$container exists but is stopped"
        else
            log_info "$container is not deployed"
        fi
    done

    echo ""
    log_info "Container details:"
    docker ps -a --filter "name=softpower" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true

    echo ""
    log_info "Image type:  $IMAGE_TYPE"
    log_info "Deploy mode: $DEPLOY_MODE (TRANSFORMERS_OFFLINE=$TRANSFORMERS_OFFLINE)"
    if [ "$IMAGE_TYPE" = "slim" ]; then
        log_info "Model dir:   $MODEL_DIR"
    else
        log_info "Model dir:   (baked into image)"
    fi
    log_info "App image:   $APP_IMAGE"

    echo ""
    log_info "Docker images:"
    docker images | grep -E "softpower|pgvector|REPOSITORY" || true

    echo ""
    log_info "Volumes:"
    docker volume ls --filter "name=softpower" 2>/dev/null || true

    echo ""
    log_info "Network:    host (containers share host network namespace)"
    echo ""
}

# ============================================
# Database Backup
# ============================================
cmd_backup() {
    local backup_file="${1:-softpower-backup-$(date +%Y%m%d-%H%M%S).dump}"

    if ! container_running "$DB_CONTAINER"; then
        log_error "Database is not running"
        exit 1
    fi

    log_info "Creating database backup..."
    # Uses host-native pg_dump when available; falls back to non-rm container.
    _pg_dump_host -d "$POSTGRES_DB" -F c -f "$backup_file"

    log_ok "Backup saved to: $backup_file ($(du -h "$backup_file" | cut -f1))"
    echo ""
}

# ============================================
# Database Restore
# ============================================
cmd_restore() {
    local backup_file="$1"

    if [ -z "$backup_file" ]; then
        log_error "Usage: ./production-deploy.sh restore <backup-file>"
        exit 1
    fi

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        exit 1
    fi

    if ! container_running "$DB_CONTAINER"; then
        log_error "Database is not running. Start it first."
        exit 1
    fi

    log_info "Restoring database from: $backup_file"
    # Uses host-native pg_restore when available; falls back to non-rm container.
    # pg_restore may return non-zero on warnings — that's normal, hence || true.
    _pg_restore_host -d "$POSTGRES_DB" --clean --if-exists \
        --no-owner --no-privileges --verbose \
        "$backup_file" || true

    log_ok "Database restored from $backup_file"
    echo ""
}

# ============================================
# Import: Additive load from dump file(s)
# Unlike 'restore' (which uses --clean to replace), this adds data
# to the existing database without dropping tables first.
# ============================================
cmd_import() {
    if [ $# -eq 0 ]; then
        echo ""
        echo "Import dump file(s) into the running database (additive — no table drops)."
        echo ""
        echo "Usage:"
        echo "  $0 import <file.dump>              # Import single dump file"
        echo "  $0 import <dir>                     # Import chunked export (manifest.json)"
        echo "  $0 import <file1.dump> <file2.dump> # Import multiple dump files in sequence"
        echo ""
        echo "Options (via environment variables):"
        echo "  IMPORT_JOBS=4  $0 import file.dump  # Parallel restore (default: 1)"
        echo ""
        exit 1
    fi

    if ! container_running "$DB_CONTAINER"; then
        log_error "Database is not running. Start it first: ./production-deploy.sh start"
        exit 1
    fi

    local jobs="${IMPORT_JOBS:-1}"
    local import_count=0
    local fail_count=0

    for target in "$@"; do
        # --- Directory with manifest.json (chunked export from db_export.py) ---
        if [ -d "$target" ]; then
            if [ ! -f "$target/manifest.json" ]; then
                log_error "Directory has no manifest.json: $target"
                log_info "Expected a chunked export created by scripts/db_export.py"
                fail_count=$((fail_count + 1))
                continue
            fi

            log_info "Importing chunked export from: $target"

            # Prefer host-native python scripts/db_import.py path (no Docker
            # involvement, no setns risk). Fall back to a non-rm container if
            # the host doesn't have Python with project deps installed.
            if command -v python3 &>/dev/null && python3 -c "import psycopg2" &>/dev/null; then
                python3 scripts/db_import.py \
                    --input-dir "$target" \
                    --target-host "$DB_HOSTNAME" \
                    --target-port "$DB_PORT" \
                    --target-user "$POSTGRES_USER" \
                    --target-password "$POSTGRES_PASSWORD" \
                    --target-db "$POSTGRES_DB" \
                    --jobs "$jobs" && import_count=$((import_count + 1)) || fail_count=$((fail_count + 1))
            else
                docker run -i \
                    --name "sp_import_$(date +%s)" \
                    --network host \
                    -v "$(cd "$target" && pwd):/import:ro" \
                    -e PGPASSWORD="$POSTGRES_PASSWORD" \
                    -e DB_IMAGE="$DB_IMAGE" \
                    "$APP_IMAGE" \
                    python scripts/db_import.py \
                        --input-dir /import \
                        --target-host "$DB_HOSTNAME" \
                        --target-port "$DB_PORT" \
                        --target-user "$POSTGRES_USER" \
                        --target-password "$POSTGRES_PASSWORD" \
                        --target-db "$POSTGRES_DB" \
                        --jobs "$jobs" && import_count=$((import_count + 1)) || fail_count=$((fail_count + 1))
            fi

        # --- Single .dump file ---
        elif [ -f "$target" ]; then
            log_info "Importing dump file: $target (additive, no --clean)"

            # pg_restore without --clean: adds data, skips existing objects
            local restore_args="--verbose --if-exists --no-owner --no-privileges"
            if [ "$jobs" -gt 1 ]; then
                restore_args="--jobs=$jobs $restore_args"
            fi

            _pg_restore_host -d "$POSTGRES_DB" $restore_args "$target" \
                && import_count=$((import_count + 1)) || {
                    log_warn "pg_restore exited non-zero for $target (may be warnings only)"
                    import_count=$((import_count + 1))
                }

        else
            log_error "Not found: $target"
            fail_count=$((fail_count + 1))
        fi
    done

    echo ""
    log_ok "Import complete: $import_count succeeded, $fail_count failed"

    # Run ANALYZE to update statistics after bulk import
    log_info "Running ANALYZE to update table statistics..."
    _psql_host -d "$POSTGRES_DB" -c "ANALYZE;" >/dev/null 2>&1
    log_ok "Statistics updated"

    # Show table counts
    log_info "Current table row counts:"
    _psql_host -d "$POSTGRES_DB" \
        -c "SELECT relname AS table, reltuples::bigint AS approx_rows
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = 'public'
            AND reltuples > 0
            ORDER BY reltuples DESC;"
    echo ""
}

# ============================================
# Run SQL against the database
# ============================================
cmd_psql() {
    if ! container_running "$DB_CONTAINER"; then
        log_error "Database is not running"
        exit 1
    fi

    if [ $# -eq 0 ]; then
        # Interactive psql session
        log_info "Opening interactive psql session (Ctrl+D to exit)..."
        # Interactive psql needs a TTY. Native psql on the host is best;
        # fall back to a non-rm container only when host psql is missing.
        if _have_native_pg; then
            PGPASSWORD="$POSTGRES_PASSWORD" psql \
                -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB"
        else
            docker run -it --name "sp_psql_$(date +%s)" --network host \
                -e PGPASSWORD="$POSTGRES_PASSWORD" \
                "$DB_IMAGE" \
                psql -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB"
        fi
    else
        # Execute SQL command(s) via host-native psql when available
        _psql_host -d "$POSTGRES_DB" -c "$*"
    fi
}

# ============================================
# Rebuild Database (drop + recreate + migrate)
# ============================================
cmd_rebuild_db() {
    local backup_file="${1:-}"
    local skip_confirm="${2:-}"

    echo ""
    echo "=============================================="
    echo "Database Rebuild"
    echo "=============================================="
    echo ""
    log_warn "This will DESTROY the existing database and recreate it from scratch."
    echo ""
    echo "  Database:  $POSTGRES_DB"
    echo "  User:      $POSTGRES_USER"
    echo "  Volume:    $DB_VOLUME"
    if [ -n "$backup_file" ]; then
        echo "  Restore:   $backup_file"
    else
        echo "  Restore:   (none — empty schema only)"
    fi
    echo ""

    # Safety confirmation
    if [ "$skip_confirm" != "--yes" ]; then
        echo -n "Type 'rebuild' to confirm: "
        read -r confirm
        if [ "$confirm" != "rebuild" ]; then
            log_info "Aborted."
            exit 0
        fi
    fi

    check_docker

    # ---- Step 1: Backup existing database (if running) ----
    if container_running "$DB_CONTAINER"; then
        local auto_backup="softpower-pre-rebuild-$(date +%Y%m%d-%H%M%S).dump"
        log_info "Step 1/6: Creating safety backup before rebuild..."
        if _pg_dump_host -d "$POSTGRES_DB" -F c -f "$auto_backup" 2>/dev/null; then
            local backup_size
            backup_size=$(du -h "$auto_backup" 2>/dev/null | cut -f1)
            if [ -s "$auto_backup" ]; then
                log_ok "Safety backup saved: $auto_backup ($backup_size)"
            else
                rm -f "$auto_backup"
                log_warn "Backup was empty (database may be new/empty) — skipping"
            fi
        else
            rm -f "$auto_backup"
            log_warn "Could not create safety backup — database may be unreachable"
        fi
    else
        log_info "Step 1/6: Database not running — skipping safety backup"
    fi

    # ---- Step 2: Stop all services ----
    log_info "Step 2/6: Stopping all services..."
    for container in "$APP_CONTAINER" "$REDIS_CONTAINER" "$DB_CONTAINER"; do
        if container_running "$container"; then
            docker stop "$container" >/dev/null 2>&1
            _docker_rm_best_effort "$container" >/dev/null 2>&1 || true
            log_ok "Stopped: $container"
        elif container_exists "$container"; then
            _docker_rm_best_effort "$container" >/dev/null 2>&1 || true
        fi
    done

    # ---- Step 3: Remove the database volume ----
    log_info "Step 3/6: Removing database volume ($DB_VOLUME)..."
    if docker volume inspect "$DB_VOLUME" &>/dev/null; then
        docker volume rm "$DB_VOLUME"
        log_ok "Volume removed: $DB_VOLUME"
    else
        log_info "Volume did not exist"
    fi

    # ---- Step 4: Start fresh database ----
    log_info "Step 4/6: Starting fresh PostgreSQL..."

    # Recreate volume
    docker volume create "$DB_VOLUME"

    # Start PostgreSQL (it will auto-create the database on first boot)
    docker run -d \
        --name "$DB_CONTAINER" \
        --network host \
        --restart unless-stopped \
        --security-opt no-new-privileges:true \
        --cap-drop ALL \
        --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
        --cap-add SETGID --cap-add SETUID \
        -e POSTGRES_USER="$POSTGRES_USER" \
        -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
        -e POSTGRES_DB="$POSTGRES_DB" \
        -e PGDATA=/var/lib/postgresql/data/pgdata \
        -e PGPORT="$DB_PORT" \
        -v "$DB_VOLUME":/var/lib/postgresql/data \
        --shm-size=1g \
        "$DB_IMAGE"

    wait_for_db

    # ---- Step 5: Enable pgvector extension ----
    log_info "Step 5/6: Enabling pgvector extension..."
    _psql_host -d "$POSTGRES_DB" \
        -c "CREATE EXTENSION IF NOT EXISTS vector;" \
        -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
        -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');"

    log_ok "Extensions enabled"

    # ---- Step 6: Run migrations or restore ----
    if [ -n "$backup_file" ]; then
        log_info "Step 6/6: Restoring database from backup..."

        if [ ! -f "$backup_file" ]; then
            log_error "Backup file not found: $backup_file"
            log_info "Database is running but empty. You can restore manually later:"
            log_info "  ./production-deploy.sh restore <backup-file>"
            exit 1
        fi

        _pg_restore_host -d "$POSTGRES_DB" --clean --if-exists \
            --no-owner --no-privileges --verbose "$backup_file" || true

        log_ok "Database restored from: $backup_file"

        # Run migrations to apply any schema changes since the backup
        log_info "Running migrations to apply any schema changes since backup..."
        docker run --name "sp_migrate_$(date +%s)" \
            --network host \
            -e DOCKER_ENV=true \
            -e DB_HOST="$DB_HOSTNAME" \
            -e DB_PORT="$DB_PORT" \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e DATABASE_URL="$(build_database_url "$DB_HOSTNAME" "$DB_PORT")" \
            "$APP_IMAGE" \
            alembic upgrade head
        log_ok "Migrations applied"
    else
        log_info "Step 6/6: Running Alembic migrations (fresh schema)..."
        docker run --name "sp_migrate_$(date +%s)" \
            --network host \
            -e DOCKER_ENV=true \
            -e DB_HOST="$DB_HOSTNAME" \
            -e DB_PORT="$DB_PORT" \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e DATABASE_URL="$(build_database_url "$DB_HOSTNAME" "$DB_PORT")" \
            "$APP_IMAGE" \
            alembic upgrade head
        log_ok "Migrations complete — empty schema created"
    fi

    # ---- Verify ----
    log_info "Verifying database..."
    local table_count
    table_count=$(_psql_host -d "$POSTGRES_DB" \
        -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')

    echo ""
    echo "=============================================="
    echo -e "${GREEN}Database Rebuild Complete${NC}"
    echo "=============================================="
    echo ""
    echo "  Tables:    ${table_count:-unknown}"
    echo "  Database:  $POSTGRES_DB"
    echo "  Port:      $DB_PORT"
    echo ""
    echo "Next steps:"
    echo "  ./production-deploy.sh start    # Start the application"
    if [ -z "$backup_file" ]; then
        echo "  ./production-deploy.sh restore <file>  # Restore data from backup"
    fi
    echo ""
}

# ============================================
# Main
# ============================================
case "${1:-help}" in
    setup)
        cmd_setup
        ;;
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_stop
        sleep 3
        cmd_start
        ;;
    migrate)
        cmd_migrate
        ;;
    status)
        cmd_status
        ;;
    load)
        cmd_load "${2:-.}"
        ;;
    backup)
        cmd_backup "$2"
        ;;
    restore)
        cmd_restore "$2"
        ;;
    import)
        shift
        cmd_import "$@"
        ;;
    rebuild-db)
        cmd_rebuild_db "$2" "$3"
        ;;
    psql)
        shift
        cmd_psql "$@"
        ;;
    logs)
        container="${2:-$APP_CONTAINER}"
        docker logs -f "$container"
        ;;
    *)
        echo ""
        echo "SoftPower Analytics - Production Deployment"
        echo ""
        echo "Usage: $0 {command} [args]"
        echo ""
        echo "Commands:"
        echo "  load [dir]          Load Docker images from tar files in [dir] (default: current dir)"
        echo "  setup               Install ML packages from wheels into app image (one-time)"
        echo "  start               Start all services (database + application)"
        echo "  stop                Stop all services (preserves data)"
        echo "  restart             Stop then start all services"
        echo "  migrate             Run database migrations (Alembic)"
        echo "  status              Show status of all containers"
        echo "  backup [file]       Create database backup"
        echo "  restore <file>      Restore database from backup (replaces existing data)"
        echo "  import <files|dir>  Import dump file(s) into database (additive — no drops)"
        echo "  rebuild-db [file]   Drop database, recreate schema, optionally restore from backup"
        echo "  psql [sql]          Open interactive psql session, or execute SQL command"
        echo "  logs [container]    Tail container logs (default: app)"
        echo ""
        echo "First-time deployment (registry images from Docker Hub):"
        echo "  1. $0 start             # Start database + application"
        echo "  2. $0 migrate           # Initialize database schema"
        echo "     — or —"
        echo "  2. $0 restore backup.dump  # Restore data from dump"
        echo ""
        echo "First-time deployment (slim images from production-build.sh):"
        echo "  1. $0 load ./images     # Load pre-built Docker images"
        echo "  2. $0 setup             # Install ML packages from wheels"
        echo "  3. $0 start             # Start database + application"
        echo "  4. $0 migrate           # Initialize database schema"
        echo "  5. $0 restore backup.dump  # Restore data (if you have a backup)"
        echo ""
        echo "Environment:"
        echo "  Create a .env file to override defaults (see .env.example)"
        echo "  Key variables: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB"
        echo ""
        echo "  IMAGE_TYPE=registry       Self-contained image (ML baked in, from Docker Hub)"
        echo "  IMAGE_TYPE=slim           Slim image (needs setup + hf_model, from production-build.sh)"
        echo "  IMAGE_TYPE=auto           Auto-detect from APP_IMAGE or PRODUCTION_REGISTRY (default)"
        echo "  APP_IMAGE=...             Override app image name directly"
        echo "  DB_IMAGE=...              Override database image name directly"
        echo "  APP_VERSION=latest        Tag for registry images (default: latest)"
        echo "  PRODUCTION_REGISTRY=...   Registry prefix (implies IMAGE_TYPE=registry)"
        echo ""
        echo "  DEPLOY_MODE=production    HuggingFace fully offline (default)"
        echo "  DEPLOY_MODE=standard      HuggingFace can reach network"
        echo "  MODEL_DIR=./hf_model      Path to HuggingFace model directory (slim only)"
        echo "  LLM_PROXY_PORT=7001       Host-side LLM/S3 proxy port (default: 7001)"
        echo "  LLM_PROXY_PORT=0          Disable proxy (container calls APIs directly)"
        echo "  REDIS_IMAGE=redis:7-alpine  Redis image (default; swap for enterprise hardened image)"
        echo ""
        exit 1
        ;;
esac
