#!/bin/bash
# ============================================
# Air-Gapped Deployment Script
# Run this ON the air-gapped CentOS 7 system
# No docker-compose required - raw docker only
# ============================================
# Usage: ./airgap-deploy.sh [start|stop|restart|migrate|status|load|backup|restore]
# ============================================

set -e

# Colors (CentOS 7 compatible)
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
    export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)
fi

POSTGRES_USER="${POSTGRES_USER:-matthew50}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-softpower}"
POSTGRES_DB="${POSTGRES_DB:-softpower-db}"
DB_PORT="${DB_PORT:-5432}"
API_PORT="${API_PORT:-8000}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

# Image names
# Database: Official pgvector image (PostgreSQL 16 + pgvector extension)
# Source: https://hub.docker.com/r/pgvector/pgvector
DB_IMAGE="pgvector/pgvector:0.8.0-pg16"
# Application: Built by airgap-build.sh
APP_IMAGE="softpower-app-airgap:latest"

# Container names
DB_CONTAINER="softpower_db"
APP_CONTAINER="softpower_app"

# Docker resources
NETWORK_NAME="softpower_net"
DB_VOLUME="softpower_pgdata"

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

wait_for_db() {
    log_info "Waiting for PostgreSQL to be ready..."
    local max_attempts=30
    for i in $(seq 1 $max_attempts); do
        if docker exec "$DB_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" > /dev/null 2>&1; then
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
        if curl -sf http://localhost:${API_PORT}/api/health > /dev/null 2>&1; then
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
# Load Images from tar files
# ============================================
cmd_load() {
    echo ""
    echo "=============================================="
    echo "Loading Docker Images from tar files"
    echo "=============================================="
    echo ""

    local image_dir="${1:-.}"

    # Load all tar files (softpower app images + bitnami pgvector)
    for tarfile in "$image_dir"/*.tar; do
        if [ -f "$tarfile" ]; then
            log_info "Loading $(basename $tarfile)..."
            docker load -i "$tarfile"
            log_ok "Loaded $(basename $tarfile)"
        fi
    done

    echo ""
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
    echo "SoftPower Analytics - Air-Gapped Deployment"
    echo "=============================================="
    echo ""

    check_docker

    # Verify images exist
    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "pgvector/pgvector"; then
        log_error "Database image not found: $DB_IMAGE"
        log_info "Run './airgap-deploy.sh load' first to load images from tar files"
        exit 1
    fi
    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "$APP_IMAGE"; then
        log_error "Application image not found: $APP_IMAGE"
        log_info "Run './airgap-deploy.sh load' first to load images from tar files"
        exit 1
    fi

    # Create network
    if ! docker network inspect "$NETWORK_NAME" &>/dev/null; then
        log_info "Creating Docker network: $NETWORK_NAME"
        docker network create "$NETWORK_NAME"
    fi
    log_ok "Network: $NETWORK_NAME"

    # Create volume
    if ! docker volume inspect "$DB_VOLUME" &>/dev/null; then
        log_info "Creating Docker volume: $DB_VOLUME"
        docker volume create "$DB_VOLUME"
    fi
    log_ok "Volume: $DB_VOLUME"

    # --- Start PostgreSQL ---
    if container_running "$DB_CONTAINER"; then
        log_ok "Database already running"
    else
        if container_exists "$DB_CONTAINER"; then
            log_info "Removing stopped database container..."
            docker rm "$DB_CONTAINER"
        fi

        log_info "Starting PostgreSQL + pgvector..."
        docker run -d \
            --name "$DB_CONTAINER" \
            --network "$NETWORK_NAME" \
            --restart unless-stopped \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -v "$DB_VOLUME":/var/lib/postgresql/data \
            -p "${DB_PORT}:5432" \
            --shm-size=1g \
            "$DB_IMAGE"

        log_ok "PostgreSQL container started"
    fi

    wait_for_db

    # --- Start Application ---
    if container_running "$APP_CONTAINER"; then
        log_ok "Application already running"
    else
        if container_exists "$APP_CONTAINER"; then
            log_info "Removing stopped application container..."
            docker rm "$APP_CONTAINER"
        fi

        log_info "Starting application (FastAPI + Streamlit)..."
        docker run -d \
            --name "$APP_CONTAINER" \
            --network "$NETWORK_NAME" \
            --restart unless-stopped \
            -e DOCKER_ENV=true \
            -e NODE_ENV=production \
            -e DB_HOST="$DB_CONTAINER" \
            -e DB_PORT=5432 \
            -e POSTGRES_HOST="$DB_CONTAINER" \
            -e POSTGRES_PORT=5432 \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DB_CONTAINER}:5432/${POSTGRES_DB}" \
            -e DB_POOL_SIZE="${DB_POOL_SIZE:-10}" \
            -e DB_MAX_OVERFLOW="${DB_MAX_OVERFLOW:-20}" \
            -e DB_POOL_TIMEOUT="${DB_POOL_TIMEOUT:-30}" \
            -e DB_POOL_RECYCLE="${DB_POOL_RECYCLE:-3600}" \
            -e API_URL="http://localhost:8000" \
            -e BACKEND_API_URL="http://localhost:8000" \
            -e FASTAPI_URL="http://localhost:8000/material_query" \
            -e TRANSFORMERS_OFFLINE=1 \
            -e HF_HUB_OFFLINE=1 \
            -e CLAUDE_KEY="${CLAUDE_KEY:-}" \
            -p "${API_PORT}:8000" \
            -p "${STREAMLIT_PORT}:8501" \
            "$APP_IMAGE"

        log_ok "Application container started"
    fi

    wait_for_api

    echo ""
    echo "=============================================="
    echo -e "${GREEN}Deployment Complete${NC}"
    echo "=============================================="
    echo ""
    echo "Access:"
    echo "  React Web App:    http://localhost:${API_PORT}"
    echo "  API Docs:         http://localhost:${API_PORT}/docs"
    echo "  Streamlit:        http://localhost:${STREAMLIT_PORT}"
    echo "  PostgreSQL:       localhost:${DB_PORT}"
    echo ""
    echo "First-time setup:"
    echo "  ./airgap-deploy.sh migrate     # Run database migrations"
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

    for container in "$APP_CONTAINER" "$DB_CONTAINER"; do
        if container_running "$container"; then
            docker stop "$container"
            docker rm "$container"
            log_ok "Stopped: $container"
        elif container_exists "$container"; then
            docker rm "$container"
            log_ok "Removed stopped: $container"
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
        log_error "Database is not running. Start it first: ./airgap-deploy.sh start"
        exit 1
    fi

    # Run alembic inside the app container if running, otherwise ephemeral
    if container_running "$APP_CONTAINER"; then
        docker exec "$APP_CONTAINER" alembic upgrade head
    else
        docker run --rm \
            --network "$NETWORK_NAME" \
            -e DOCKER_ENV=true \
            -e DB_HOST="$DB_CONTAINER" \
            -e DB_PORT=5432 \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DB_CONTAINER}:5432/${POSTGRES_DB}" \
            "$APP_IMAGE" \
            alembic upgrade head
    fi

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
    for container in "$DB_CONTAINER" "$APP_CONTAINER"; do
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
    log_info "Docker images:"
    docker images | grep -E "softpower|REPOSITORY" || true

    echo ""
    log_info "Volumes:"
    docker volume ls --filter "name=softpower" 2>/dev/null || true

    echo ""
    log_info "Network:"
    docker network inspect "$NETWORK_NAME" --format '{{range .Containers}}  {{.Name}}{{"\n"}}{{end}}' 2>/dev/null || echo "  Network not created"
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
    docker exec "$DB_CONTAINER" pg_dump \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -F c \
        -f /tmp/backup.dump

    docker cp "$DB_CONTAINER":/tmp/backup.dump "$backup_file"
    docker exec "$DB_CONTAINER" rm /tmp/backup.dump

    log_ok "Backup saved to: $backup_file ($(du -h "$backup_file" | cut -f1))"
    echo ""
}

# ============================================
# Database Restore
# ============================================
cmd_restore() {
    local backup_file="$1"

    if [ -z "$backup_file" ]; then
        log_error "Usage: ./airgap-deploy.sh restore <backup-file>"
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
    docker cp "$backup_file" "$DB_CONTAINER":/tmp/backup.dump

    docker exec "$DB_CONTAINER" pg_restore \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --clean --if-exists \
        /tmp/backup.dump || true

    docker exec "$DB_CONTAINER" rm /tmp/backup.dump

    log_ok "Database restored from $backup_file"
    echo ""
}

# ============================================
# Main
# ============================================
case "${1:-help}" in
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
    logs)
        container="${2:-$APP_CONTAINER}"
        docker logs -f "$container"
        ;;
    *)
        echo ""
        echo "SoftPower Analytics - Air-Gapped Deployment"
        echo ""
        echo "Usage: $0 {command} [args]"
        echo ""
        echo "Commands:"
        echo "  load [dir]          Load Docker images from tar files in [dir] (default: current dir)"
        echo "  start               Start all services (database + application)"
        echo "  stop                Stop all services (preserves data)"
        echo "  restart             Stop then start all services"
        echo "  migrate             Run database migrations (Alembic)"
        echo "  status              Show status of all containers"
        echo "  backup [file]       Create database backup"
        echo "  restore <file>      Restore database from backup"
        echo "  logs [container]    Tail container logs (default: app)"
        echo ""
        echo "First-time deployment:"
        echo "  1. $0 load ./images     # Load pre-built Docker images"
        echo "  2. $0 start             # Start database + application"
        echo "  3. $0 migrate           # Initialize database schema"
        echo "  4. $0 restore backup.dump  # Restore data (if you have a backup)"
        echo ""
        echo "Environment:"
        echo "  Create a .env file to override defaults (see .env.example)"
        echo "  Key variables: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB"
        echo ""
        exit 1
        ;;
esac
