#!/bin/bash
# ============================================
# Production Wipe Script
# Clears all data and containers for a clean
# re-deploy. Run BEFORE production-deploy.sh
# ============================================
# Usage: ./production-wipe.sh [--wipe-users] [--yes]
#
# Options:
#   --wipe-users  Also wipe user accounts (by default users are preserved)
#   --yes         Skip confirmation prompt
#
# This script:
#   1. Exports users table for preservation (unless --wipe-users)
#   2. Stops all SoftPower containers
#   3. Removes all SoftPower containers
#   4. Destroys the database volume (ALL DATA LOST)
#   5. Removes the Docker network
#   6. Starts fresh DB, runs migrations, restores users
#
# Without --preserve-users, after running this do a fresh deploy:
#   ./production-deploy.sh start
#   ./production-deploy.sh migrate
#   ./production-deploy.sh restore <backup-file>   # optional
# ============================================

set -e

# Prevent MSYS/Git Bash on Windows from mangling Unix paths
export MSYS_NO_PATHCONV=1

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ============================================
# Configuration (mirrors production-deploy.sh)
# ============================================

if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)
fi

POSTGRES_USER="${POSTGRES_USER:-}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_DB="${POSTGRES_DB:-}"
DB_PORT="${DB_PORT:-5432}"

# Image resolution (mirrors production-deploy.sh)
APP_IMAGE="${APP_IMAGE:-}"
DB_IMAGE="${DB_IMAGE:-}"
APP_VERSION="${APP_VERSION:-latest}"
IMAGE_TYPE="${IMAGE_TYPE:-auto}"

if [ "$IMAGE_TYPE" = "auto" ]; then
    if [ -n "$APP_IMAGE" ] && echo "$APP_IMAGE" | grep -q "softpower-analytics"; then
        IMAGE_TYPE="registry"
    elif [ -n "$PRODUCTION_REGISTRY" ]; then
        IMAGE_TYPE="registry"
    else
        IMAGE_TYPE="slim"
    fi
fi

if [ -z "$DB_IMAGE" ]; then
    if [ -n "$PRODUCTION_REGISTRY" ]; then
        DB_IMAGE="${PRODUCTION_REGISTRY}/pgvector:0.8.1-pg17"
    else
        DB_IMAGE="mmorrisj/pgvector:0.8.1-pg17"
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

# Container names (must match production-deploy.sh)
DB_CONTAINER="sp_prod_db"
APP_CONTAINER="sp_prod_app"
REDIS_CONTAINER="sp_prod_redis"

# Networking: host networking (see production-deploy.sh for rationale).
DB_HOSTNAME="127.0.0.1"

# Docker resources
DB_VOLUME="softpower_production_prod_pgdata"

# ============================================
# Parse Arguments
# ============================================

PRESERVE_USERS=true
SKIP_CONFIRM=false

for arg in "$@"; do
    case "$arg" in
        --wipe-users) PRESERVE_USERS=false ;;
        --yes)        SKIP_CONFIRM=true ;;
        *)            echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

# ============================================
# Helper Functions
# ============================================

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

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

container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${1}$"
}

container_exists() {
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${1}$"
}

# URL-encode a string for use in DATABASE_URL
urlencode() {
    python3 -c "import urllib.parse; print(urllib.parse.quote_plus('$1'))" 2>/dev/null \
        || printf '%s' "$1"
}

build_database_url() {
    local encoded_user encoded_pass
    encoded_user=$(urlencode "$POSTGRES_USER")
    encoded_pass=$(urlencode "$POSTGRES_PASSWORD")
    echo "postgresql+psycopg2://${encoded_user}:${encoded_pass}@${1}:${2}/${POSTGRES_DB}"
}

wait_for_db() {
    log_info "Waiting for PostgreSQL to be ready..."
    local max_attempts=30
    for i in $(seq 1 $max_attempts); do
        if docker run --rm --network host \
            "$DB_IMAGE" \
            pg_isready -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" > /dev/null 2>&1; then
            log_ok "PostgreSQL is ready"
            return 0
        fi
        echo "  Waiting... ($i/$max_attempts)"
        sleep 2
    done
    log_error "PostgreSQL did not become ready in time"
    return 1
}

# ============================================
# Main
# ============================================

echo ""
echo "=============================================="
echo "SoftPower Analytics - Production Wipe"
echo "=============================================="
echo ""
log_warn "This will DESTROY all data and remove all containers."
if [ "$PRESERVE_USERS" = true ]; then
    log_info "User accounts will be PRESERVED (pass --wipe-users to also remove them)"
else
    log_warn "User accounts will also be WIPED (--wipe-users)"
fi
echo ""
echo "  Containers:  $APP_CONTAINER, $REDIS_CONTAINER, $DB_CONTAINER"
echo "  Volume:      $DB_VOLUME (ALL DATABASE DATA)"
echo "  Network:     host (containers share host network namespace)"
echo ""

# Safety confirmation
if [ "$SKIP_CONFIRM" != true ]; then
    echo -n "Type 'wipe' to confirm: "
    read -r confirm
    if [ "$confirm" != "wipe" ]; then
        log_info "Aborted."
        exit 0
    fi
    echo ""
fi

check_docker

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USERS_DUMP=""

# ---- Step 1: Safety backup + export users (if database is running) ----
if container_running "$DB_CONTAINER" && [ -n "$POSTGRES_USER" ] && [ -n "$POSTGRES_PASSWORD" ]; then
    auto_backup="softpower-pre-wipe-$(date +%Y%m%d-%H%M%S).dump"
    log_info "Step 1: Creating safety backup before wipe..."
    if docker run --rm --network host \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        pg_dump -h "$DB_HOSTNAME" -p "$DB_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -F c > "$auto_backup" 2>/dev/null; then
        if [ -s "$auto_backup" ]; then
            backup_size=$(du -h "$auto_backup" 2>/dev/null | cut -f1)
            log_ok "Safety backup saved: $auto_backup ($backup_size)"
        else
            rm -f "$auto_backup"
            log_warn "Backup was empty (database may be new/empty) — skipping"
        fi
    else
        rm -f "$auto_backup"
        log_warn "Could not create safety backup — database may be unreachable"
    fi

    # Export users table if --preserve-users
    if [ "$PRESERVE_USERS" = true ]; then
        USERS_DUMP="softpower-users-$(date +%Y%m%d-%H%M%S).sql"
        log_info "Exporting users table for preservation..."

        # Use pg_dump to export just the users table data (--data-only --table=users)
        # --inserts produces INSERT statements that work regardless of column order changes
        if docker run --rm --network host \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            pg_dump -h "$DB_HOSTNAME" -p "$DB_PORT" \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            --data-only --table=users --inserts \
            > "$USERS_DUMP" 2>/dev/null; then
            if [ -s "$USERS_DUMP" ]; then
                user_count=$(grep -c "^INSERT" "$USERS_DUMP" 2>/dev/null || echo "0")
                log_ok "Exported $user_count user(s) to $USERS_DUMP"
            else
                rm -f "$USERS_DUMP"
                USERS_DUMP=""
                log_warn "Users table was empty — nothing to preserve"
            fi
        else
            rm -f "$USERS_DUMP"
            USERS_DUMP=""
            log_warn "Could not export users table — will proceed without preservation"
        fi
    fi
else
    log_info "Step 1: Database not running — skipping safety backup"
    if [ "$PRESERVE_USERS" = true ]; then
        log_warn "Cannot preserve users — database is not running"
        log_info "User data may still be in a prior safety backup"
    fi
fi

# ---- Step 2: Stop and remove all containers ----
log_info "Step 2: Stopping and removing containers..."
for container in "$APP_CONTAINER" "$REDIS_CONTAINER" "$DB_CONTAINER"; do
    if container_running "$container"; then
        docker stop "$container" >/dev/null 2>&1
        docker rm "$container" >/dev/null 2>&1
        log_ok "Stopped and removed: $container"
    elif container_exists "$container"; then
        docker rm "$container" >/dev/null 2>&1
        log_ok "Removed stopped: $container"
    else
        log_info "Not present: $container"
    fi
done

# ---- Step 3: Remove database volume ----
log_info "Step 3: Removing database volume ($DB_VOLUME)..."
if docker volume inspect "$DB_VOLUME" &>/dev/null; then
    docker volume rm "$DB_VOLUME"
    log_ok "Volume removed: $DB_VOLUME"
else
    log_info "Volume did not exist"
fi

# ---- Step 4: Network cleanup (no-op for host networking) ----
log_info "Step 4: Network cleanup — using host networking, nothing to remove"

# ---- Step 5: Restore users (if --preserve-users and we have a dump) ----
if [ "$PRESERVE_USERS" = true ] && [ -n "$USERS_DUMP" ] && [ -f "$USERS_DUMP" ]; then
    echo ""
    log_info "Step 5: Restoring user accounts into fresh database..."

    # Recreate volume
    docker volume create "$DB_VOLUME"

    # Start fresh PostgreSQL (host networking)
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

    # Enable extensions
    log_info "Enabling pgvector + pg_trgm extensions..."
    docker run --rm --network host \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "CREATE EXTENSION IF NOT EXISTS vector;" \
        -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" > /dev/null 2>&1
    log_ok "Extensions enabled"

    # Run migrations to create schema
    log_info "Running Alembic migrations (fresh schema)..."
    docker run --rm \
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
    log_ok "Migrations complete — fresh schema created"

    # Restore users data
    log_info "Restoring users from $USERS_DUMP..."
    docker run --rm -i --network host \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        < "$USERS_DUMP" > /dev/null 2>&1

    # Verify
    restored_count=$(docker run --rm --network host \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_HOSTNAME" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -t -c "SELECT count(*) FROM users;" 2>/dev/null | tr -d ' ')

    log_ok "Restored ${restored_count:-0} user(s)"

    # Clean up the users dump file
    rm -f "$USERS_DUMP"

    # Stop the DB — let production-deploy.sh start manage the full stack
    log_info "Stopping database (production-deploy.sh start will bring everything up)..."
    docker stop "$DB_CONTAINER" >/dev/null 2>&1
    docker rm "$DB_CONTAINER" >/dev/null 2>&1

    echo ""
    echo "=============================================="
    echo -e "${GREEN}Wipe Complete — Users Preserved${NC}"
    echo "=============================================="
    echo ""
    echo "Database wiped and rebuilt with ${restored_count:-0} user(s) restored."
    echo "Schema is up to date (migrations applied)."
    echo ""
    echo "Next steps:"
    echo "  ./production-deploy.sh start      # Start full stack"
    echo "  ./production-deploy.sh restore <backup-file>   # Optional: restore other data"
    echo ""
    echo "NOTE: production-deploy.sh start will skip migrations if schema is"
    echo "      already current. User accounts are ready to use immediately."
    echo ""
else
    echo ""
    echo "=============================================="
    echo -e "${GREEN}Wipe Complete${NC}"
    echo "=============================================="
    echo ""
    echo "All containers, data, and network have been removed."
    echo ""
    echo "Next steps — fresh deploy:"
    echo "  ./production-deploy.sh start      # Start containers (fresh database)"
    echo "  ./production-deploy.sh migrate    # Create schema via Alembic"
    echo "  ./production-deploy.sh restore <backup-file>   # Optional: restore data"
    echo ""
fi
