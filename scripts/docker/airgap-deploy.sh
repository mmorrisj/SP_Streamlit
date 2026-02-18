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

# LLM/S3 Proxy Relay
# The container lacks certificate authorizations to call external APIs directly.
# LLM and S3 requests are proxied through a host-side FastAPI on LLM_PROXY_PORT.
# Set LLM_PROXY_PORT=0 to disable (container calls APIs directly).
LLM_PROXY_PORT="${LLM_PROXY_PORT:-7001}"

# Deployment mode: "airgap" or "standard"
# airgap  = TRANSFORMERS_OFFLINE=1, HF_HUB_OFFLINE=1 (no network access to HuggingFace)
# standard = TRANSFORMERS_OFFLINE=0, HF_HUB_OFFLINE=0 (model still baked in, but can reach out)
DEPLOY_MODE="${DEPLOY_MODE:-airgap}"

if [ "$DEPLOY_MODE" = "airgap" ]; then
    TRANSFORMERS_OFFLINE=1
    HF_HUB_OFFLINE=1
else
    TRANSFORMERS_OFFLINE=0
    HF_HUB_OFFLINE=0
fi

# Image names
# If AIRGAP_REGISTRY is set, use registry-prefixed image names
if [ -n "$AIRGAP_REGISTRY" ]; then
    DB_IMAGE="${AIRGAP_REGISTRY}/pgvector:0.8.0-pg16"
    APP_IMAGE="${AIRGAP_REGISTRY}/softpower-app-airgap:latest"
else
    # Database: Official pgvector image (PostgreSQL 16 + pgvector extension)
    DB_IMAGE="pgvector/pgvector:0.8.0-pg16"
    # Application: Built by airgap-build.sh
    APP_IMAGE="softpower-app-airgap:latest"
fi

# HuggingFace model directory (sentence-transformers, mounted as volume)
# Default: hf_model/ next to this script (produced by airgap-build.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="${MODEL_DIR:-${SCRIPT_DIR}/hf_model}"

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
# Setup: Install heavy ML packages from wheels
# ============================================
cmd_setup() {
    echo ""
    echo "=============================================="
    echo "Installing ML packages from local wheels"
    echo "=============================================="
    echo ""

    # Locate wheels directory (next to this script)
    local wheels_dir="${SCRIPT_DIR}/wheels"
    if [ ! -d "$wheels_dir" ]; then
        log_error "Wheels directory not found: $wheels_dir"
        log_info "Expected: wheels/ directory produced by airgap-build.sh"
        exit 1
    fi

    local wheel_count
    wheel_count=$(ls -1 "$wheels_dir"/*.whl 2>/dev/null | wc -l)
    if [ "$wheel_count" -eq 0 ]; then
        log_error "No .whl files found in $wheels_dir"
        exit 1
    fi

    # Verify the slim image is loaded
    if ! docker image inspect "$APP_IMAGE" &>/dev/null; then
        log_error "App image not found: $APP_IMAGE"
        log_info "Run './airgap-deploy.sh load ./images' first"
        exit 1
    fi

    log_info "Found $wheel_count wheel files in $wheels_dir"
    log_info "Installing into $APP_IMAGE (this may take a minute)..."
    echo ""

    # Create temp container, copy wheels in, pip install, then commit.
    # Uses docker cp instead of volume mounts for cross-platform compatibility.
    local setup_container="softpower_setup_$$"
    docker rm -f "$setup_container" 2>/dev/null || true

    docker create --name "$setup_container" \
        "$APP_IMAGE" \
        pip install --no-cache-dir --no-index --find-links /wheels \
            torch sentence-transformers langchain-huggingface

    docker cp "$wheels_dir" "$setup_container":/wheels
    docker start -a "$setup_container"

    # Commit the container as the updated image
    docker commit "$setup_container" "$APP_IMAGE"
    docker rm "$setup_container"

    echo ""
    log_ok "ML packages installed into $APP_IMAGE"
    log_info "Image size: $(docker images "$APP_IMAGE" --format '{{.Size}}')"
    echo ""
    echo "Next steps:"
    echo "  ./airgap-deploy.sh start"
    echo "  ./airgap-deploy.sh migrate"
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

    # Verify images exist (try pulling from registry if not local)
    for img in "$DB_IMAGE" "$APP_IMAGE"; do
        if docker image inspect "$img" &>/dev/null; then
            log_ok "Image found: $img"
        elif [ -n "$AIRGAP_REGISTRY" ] && [ "$DEPLOY_MODE" != "airgap" ]; then
            log_info "Pulling $img from registry..."
            if docker pull "$img"; then
                log_ok "Pulled: $img"
            else
                log_error "Failed to pull: $img"
                exit 1
            fi
        else
            log_error "Image not found: $img"
            log_info "Run './airgap-deploy.sh load' first to load images from tar files"
            exit 1
        fi
    done

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

        # Proxy config: if LLM_PROXY_PORT is set and non-zero, route LLM/S3
        # calls through a host-side proxy. Otherwise, the container calls APIs directly.
        if [ "$LLM_PROXY_PORT" != "0" ] && [ -n "$LLM_PROXY_PORT" ]; then
            PROXY_API_URL="http://host.docker.internal:${LLM_PROXY_PORT}"
            PROXY_HOST_FLAG="--add-host=host.docker.internal:host-gateway"
            log_info "LLM/S3 proxy: host.docker.internal:${LLM_PROXY_PORT}"
        else
            PROXY_API_URL="http://localhost:8000"
            PROXY_HOST_FLAG=""
            log_info "LLM/S3 proxy: disabled (container calls APIs directly)"
        fi

        # Verify HuggingFace model directory
        if [ ! -d "$MODEL_DIR" ]; then
            log_error "HuggingFace model directory not found: $MODEL_DIR"
            log_info "The model is packaged in hf_model/ by airgap-build.sh"
            log_info "Set MODEL_DIR=/path/to/hf_model to override"
            exit 1
        fi
        log_ok "Model dir: $MODEL_DIR"

        log_info "Starting application (FastAPI + Streamlit)..."
        docker run -d \
            --name "$APP_CONTAINER" \
            --network "$NETWORK_NAME" \
            --restart unless-stopped \
            -v "$(cd "$MODEL_DIR" && pwd)":/app/.cache/huggingface \
            $PROXY_HOST_FLAG \
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
            -e API_URL="$PROXY_API_URL" \
            -e TRANSFORMERS_OFFLINE="$TRANSFORMERS_OFFLINE" \
            -e HF_HUB_OFFLINE="$HF_HUB_OFFLINE" \
            -e HF_HOME="/app/.cache/huggingface" \
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
    echo "Deploy mode:  $DEPLOY_MODE"
    echo "HF offline:   TRANSFORMERS_OFFLINE=$TRANSFORMERS_OFFLINE, HF_HUB_OFFLINE=$HF_HUB_OFFLINE"
    echo "Model dir:    $MODEL_DIR"
    echo "App image:    $APP_IMAGE"
    if [ "$LLM_PROXY_PORT" != "0" ] && [ -n "$LLM_PROXY_PORT" ]; then
        echo "LLM proxy:    host.docker.internal:${LLM_PROXY_PORT}"
    else
        echo "LLM proxy:    disabled (container calls APIs directly)"
    fi
    echo ""
    echo "Access:"
    echo "  React Web App:    http://localhost:${API_PORT}"
    echo "  API Docs:         http://localhost:${API_PORT}/docs"
    echo "  Streamlit:        http://localhost:${STREAMLIT_PORT}"
    echo "  PostgreSQL:       localhost:${DB_PORT}"
    echo ""
    if [ "$LLM_PROXY_PORT" != "0" ] && [ -n "$LLM_PROXY_PORT" ]; then
        echo "LLM/S3 proxy prerequisite:"
        echo "  The host-side proxy must be running on port ${LLM_PROXY_PORT}."
        echo "  Start it with:  python llm_proxy.py"
        echo "  Or disable with: LLM_PROXY_PORT=0 in .env"
        echo ""
    fi
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
    log_info "Deploy mode: $DEPLOY_MODE (TRANSFORMERS_OFFLINE=$TRANSFORMERS_OFFLINE)"
    log_info "Model dir:   $MODEL_DIR"
    log_info "App image:   $APP_IMAGE"

    echo ""
    log_info "Docker images:"
    docker images | grep -E "softpower|pgvector|REPOSITORY" || true

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
        echo "  setup               Install ML packages from wheels into app image (one-time)"
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
        echo "  2. $0 setup             # Install ML packages from wheels"
        echo "  3. $0 start             # Start database + application"
        echo "  4. $0 migrate           # Initialize database schema"
        echo "  5. $0 restore backup.dump  # Restore data (if you have a backup)"
        echo ""
        echo "Environment:"
        echo "  Create a .env file to override defaults (see .env.example)"
        echo "  Key variables: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB"
        echo ""
        echo "  DEPLOY_MODE=airgap      HuggingFace fully offline (default)"
        echo "  DEPLOY_MODE=standard    HuggingFace can reach network"
        echo "  AIRGAP_REGISTRY=...     Use registry-prefixed image name"
        echo "  MODEL_DIR=./hf_model    Path to HuggingFace model directory"
        echo "  LLM_PROXY_PORT=7001     Host-side LLM/S3 proxy port (default: 7001)"
        echo "  LLM_PROXY_PORT=0        Disable proxy (container calls APIs directly)"
        echo ""
        exit 1
        ;;
esac
