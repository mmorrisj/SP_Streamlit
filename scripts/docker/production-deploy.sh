#!/bin/bash
# ============================================
# Production Deployment Script
# Run this ON the the production target system
# No docker-compose required - raw docker only
# ============================================
# Usage: ./production-deploy.sh [start|stop|restart|migrate|status|load|backup|restore]
# ============================================

set -e

# Prevent MSYS/Git Bash on Windows from mangling Unix paths in docker -e flags
# (e.g. /var/lib/postgresql → C:/Program Files/Git/var/lib/postgresql)
export MSYS_NO_PATHCONV=1

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
# (line-by-line parser to safely skip comments and handle quotes)
if [ -f .env ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            \#*|'') continue ;;
        esac
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        value="${value%% \#*}"
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
        DB_IMAGE="${PRODUCTION_REGISTRY}/pgvector:0.8.1-pg16"
    else
        DB_IMAGE="mmorrisj/pgvector:0.8.1-pg16"
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

# Docker resources
NETWORK_NAME="softpower_net"
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

wait_for_db() {
    log_info "Waiting for PostgreSQL to be ready..."
    local max_attempts=30
    for i in $(seq 1 $max_attempts); do
        # Use ephemeral container instead of docker exec (enterprise compatibility)
        if docker run --rm --network "$NETWORK_NAME" \
            "$DB_IMAGE" \
            pg_isready -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" > /dev/null 2>&1; then
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
            --security-opt no-new-privileges:true \
            --cap-drop ALL \
            --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
            --cap-add SETGID --cap-add SETUID \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e PGDATA=/var/lib/postgresql/data/pgdata \
            -v "$DB_VOLUME":/var/lib/postgresql/data \
            -p "${DB_PORT}:5432" \
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
    if docker run --rm --network "$NETWORK_NAME" \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        pg_isready -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" > /dev/null 2>&1 \
    && docker run --rm --network "$NETWORK_NAME" \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "SELECT 1" > /dev/null 2>&1; then
        log_ok "Database credentials verified"
    else
        log_warn "Credential mismatch detected — .env password differs from initialized database"
        log_info "This happens when POSTGRES_PASSWORD changed after the volume was first created."
        log_info "Attempting to update the database password to match .env..."

        # Try connecting with the superuser role 'postgres' (which uses trust auth
        # from the same container on some setups) or via peer auth to reset the password.
        # The most reliable method: use the running container's local socket (no password needed
        # for local connections in default pg_hba.conf).
        # We cannot docker exec in enterprise, so restart the DB container momentarily
        # with trust auth to reset the password.
        docker stop "$DB_CONTAINER" > /dev/null 2>&1
        docker rm "$DB_CONTAINER" > /dev/null 2>&1

        # Start with trust auth (no password required) temporarily
        docker run -d \
            --name "$DB_CONTAINER" \
            --network "$NETWORK_NAME" \
            -e PGDATA=/var/lib/postgresql/data/pgdata \
            -v "$DB_VOLUME":/var/lib/postgresql/data \
            -p "${DB_PORT}:5432" \
            --shm-size=1g \
            "$DB_IMAGE" \
            postgres -c "authentication_timeout=30"

        # Wait for it to be ready
        local fix_attempts=15
        for i in $(seq 1 $fix_attempts); do
            if docker run --rm --network "$NETWORK_NAME" \
                "$DB_IMAGE" \
                pg_isready -h "$DB_CONTAINER" > /dev/null 2>&1; then
                break
            fi
            sleep 2
        done

        # Reset the password to match .env using the existing superuser
        # First, discover the actual superuser name from the pg catalog
        local actual_user
        actual_user=$(docker run --rm --network "$NETWORK_NAME" \
            "$DB_IMAGE" \
            psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d postgres \
            -tAc "SELECT usename FROM pg_user WHERE usesuper LIMIT 1" 2>/dev/null || echo "")

        if [ -z "$actual_user" ]; then
            # Try common superuser names
            for try_user in postgres "$POSTGRES_USER"; do
                actual_user=$(docker run --rm --network "$NETWORK_NAME" \
                    "$DB_IMAGE" \
                    psql -h "$DB_CONTAINER" -U "$try_user" -d postgres \
                    -tAc "SELECT usename FROM pg_user WHERE usesuper LIMIT 1" 2>/dev/null || echo "")
                [ -n "$actual_user" ] && break
            done
        fi

        if [ -n "$actual_user" ]; then
            # Update password for the target user
            docker run --rm --network "$NETWORK_NAME" \
                "$DB_IMAGE" \
                psql -h "$DB_CONTAINER" -U "$actual_user" -d postgres \
                -c "ALTER USER \"$POSTGRES_USER\" WITH PASSWORD '$POSTGRES_PASSWORD';" > /dev/null 2>&1

            # Create user if it doesn't exist (volume was initialized with a different username)
            docker run --rm --network "$NETWORK_NAME" \
                "$DB_IMAGE" \
                psql -h "$DB_CONTAINER" -U "$actual_user" -d postgres \
                -c "DO \$\$ BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
                        CREATE USER \"$POSTGRES_USER\" WITH SUPERUSER PASSWORD '$POSTGRES_PASSWORD';
                    END IF;
                END \$\$;" > /dev/null 2>&1

            # Create database if it doesn't exist
            docker run --rm --network "$NETWORK_NAME" \
                "$DB_IMAGE" \
                psql -h "$DB_CONTAINER" -U "$actual_user" -d postgres \
                -c "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'" 2>/dev/null | grep -q 1 || \
            docker run --rm --network "$NETWORK_NAME" \
                "$DB_IMAGE" \
                psql -h "$DB_CONTAINER" -U "$actual_user" -d postgres \
                -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";" > /dev/null 2>&1

            log_ok "Credentials updated to match .env"
        else
            log_error "Could not connect to PostgreSQL to fix credentials"
            log_info "Manual fix: run './production-deploy.sh rebuild-db' to reset (DESTROYS DATA)"
            log_info "Or update .env to match the original credentials used when the volume was created"
        fi

        # Restart the DB container normally (with password auth)
        docker stop "$DB_CONTAINER" > /dev/null 2>&1
        docker rm "$DB_CONTAINER" > /dev/null 2>&1

        docker run -d \
            --name "$DB_CONTAINER" \
            --network "$NETWORK_NAME" \
            --restart unless-stopped \
            --security-opt no-new-privileges:true \
            --cap-drop ALL \
            --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
            --cap-add SETGID --cap-add SETUID \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e PGDATA=/var/lib/postgresql/data/pgdata \
            -v "$DB_VOLUME":/var/lib/postgresql/data \
            -p "${DB_PORT}:5432" \
            --shm-size=1g \
            "$DB_IMAGE"

        wait_for_db

        # Final verification
        if docker run --rm --network "$NETWORK_NAME" \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "SELECT 1" > /dev/null 2>&1; then
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
    else
        if container_exists "$REDIS_CONTAINER"; then
            log_info "Removing stopped Redis container..."
            docker rm "$REDIS_CONTAINER"
        fi

        log_info "Starting Redis cache..."
        docker run -d \
            --name "$REDIS_CONTAINER" \
            --network "$NETWORK_NAME" \
            --restart unless-stopped \
            --security-opt no-new-privileges:true \
            --cap-drop ALL \
            --cap-add SETGID --cap-add SETUID \
            "$REDIS_IMAGE"

        # Wait for Redis to be ready
        local redis_attempts=10
        for i in $(seq 1 $redis_attempts); do
            if docker run --rm --network "$NETWORK_NAME" \
                "$REDIS_IMAGE" redis-cli -h "$REDIS_CONTAINER" ping 2>/dev/null | grep -q PONG; then
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
            PROXY_API_URL="http://0.0.0.0:8000"
            PROXY_HOST_FLAG=""
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
            if ! docker run --rm "$APP_IMAGE" python3 -c "import sentence_transformers" 2>/dev/null; then
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
            --network "$NETWORK_NAME" \
            --restart unless-stopped \
            --security-opt no-new-privileges:true \
            --cap-drop ALL \
            $VOLUME_FLAGS \
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
            -e DATABASE_URL="$(build_database_url "$DB_CONTAINER" 5432)" \
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
            -e REDIS_URL="redis://${REDIS_CONTAINER}:6379/0" \
            -e CLAUDE_KEY="${CLAUDE_KEY:-}" \
            -e OPENAI_PROJ_API="${OPENAI_PROJ_API:-}" \
            -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}" \
            -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}" \
            -e JWT_SECRET="${JWT_SECRET:-softpower-jwt-secret-change-in-production-min32chars}" \
            -e JWT_EXPIRATION_HOURS="${JWT_EXPIRATION_HOURS:-24}" \
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
        echo "LLM proxy:    host.docker.internal:${LLM_PROXY_PORT}"
    else
        echo "LLM proxy:    disabled (container calls APIs directly)"
    fi
    echo ""
    echo "Access:"
    echo "  React Web App:    http://0.0.0.0:${API_PORT}"
    echo "  API Docs:         http://0.0.0.0:${API_PORT}/docs"
    echo "  Streamlit:        http://0.0.0.0:${STREAMLIT_PORT}"
    echo "  PostgreSQL:       0.0.0.0:${DB_PORT}"
    echo "  Redis cache:      $REDIS_CONTAINER (internal)"
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

    for container in "$APP_CONTAINER" "$REDIS_CONTAINER" "$DB_CONTAINER"; do
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
        log_error "Database is not running. Start it first: ./production-deploy.sh start"
        exit 1
    fi

    # Always use ephemeral container (enterprise compatibility — no docker exec)
    docker run --rm \
        --network "$NETWORK_NAME" \
        -e DOCKER_ENV=true \
        -e DB_HOST="$DB_CONTAINER" \
        -e DB_PORT=5432 \
        -e POSTGRES_USER="$POSTGRES_USER" \
        -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
        -e POSTGRES_DB="$POSTGRES_DB" \
        -e DATABASE_URL="$(build_database_url "$DB_CONTAINER" 5432)" \
        "$APP_IMAGE" \
        alembic upgrade head

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
    # Ephemeral container connects over network (no docker exec needed).
    # Stdout redirection avoids MSYS2 path translation on Windows.
    docker run --rm --network "$NETWORK_NAME" \
        "$DB_IMAGE" \
        pg_dump -h "$DB_CONTAINER" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -F c > "$backup_file"

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
    # Ephemeral container connects over network (no docker exec needed).
    # Stdin redirection avoids MSYS2 path translation on Windows.
    docker run --rm -i --network "$NETWORK_NAME" \
        "$DB_IMAGE" \
        pg_restore -h "$DB_CONTAINER" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --clean --if-exists < "$backup_file" || true

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

            # Use db_import.py with the Docker container auto-detected over network.
            # Pass host-level connection params so the script connects via the
            # published port (no docker exec needed).
            docker run --rm -i \
                --network "$NETWORK_NAME" \
                -v "$(cd "$target" && pwd):/import:ro" \
                -e PGPASSWORD="$POSTGRES_PASSWORD" \
                -e DB_IMAGE="$DB_IMAGE" \
                -e NETWORK_NAME="$NETWORK_NAME" \
                "$APP_IMAGE" \
                python scripts/db_import.py \
                    --input-dir /import \
                    --target-host "$DB_CONTAINER" \
                    --target-port 5432 \
                    --target-user "$POSTGRES_USER" \
                    --target-password "$POSTGRES_PASSWORD" \
                    --target-db "$POSTGRES_DB" \
                    --jobs "$jobs" && import_count=$((import_count + 1)) || fail_count=$((fail_count + 1))

        # --- Single .dump file ---
        elif [ -f "$target" ]; then
            log_info "Importing dump file: $target (additive, no --clean)"

            # pg_restore without --clean: adds data, skips existing objects
            local restore_args="--verbose --if-exists --no-owner --no-privileges"
            if [ "$jobs" -gt 1 ]; then
                restore_args="$restore_args --jobs=$jobs"
            fi

            docker run --rm -i --network "$NETWORK_NAME" \
                -e PGPASSWORD="$POSTGRES_PASSWORD" \
                "$DB_IMAGE" \
                pg_restore $restore_args \
                -h "$DB_CONTAINER" \
                -U "$POSTGRES_USER" \
                -d "$POSTGRES_DB" < "$target" && import_count=$((import_count + 1)) || {
                    # pg_restore returns non-zero on warnings too — check if data loaded
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
    docker run --rm --network "$NETWORK_NAME" \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "ANALYZE;" >/dev/null 2>&1
    log_ok "Statistics updated"

    # Show table counts
    log_info "Current table row counts:"
    docker run --rm --network "$NETWORK_NAME" \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
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
        docker run --rm -it --network "$NETWORK_NAME" \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB"
    else
        # Execute SQL command(s)
        docker run --rm --network "$NETWORK_NAME" \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "$*"
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
        if docker run --rm --network "$NETWORK_NAME" \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            pg_dump -h "$DB_CONTAINER" \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            -F c > "$auto_backup" 2>/dev/null; then
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
            docker rm "$container" >/dev/null 2>&1
            log_ok "Stopped: $container"
        elif container_exists "$container"; then
            docker rm "$container" >/dev/null 2>&1
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

    # Recreate network if needed
    if ! docker network inspect "$NETWORK_NAME" &>/dev/null; then
        docker network create "$NETWORK_NAME"
    fi

    # Recreate volume
    docker volume create "$DB_VOLUME"

    # Start PostgreSQL (it will auto-create the database on first boot)
    docker run -d \
        --name "$DB_CONTAINER" \
        --network "$NETWORK_NAME" \
        --restart unless-stopped \
        --security-opt no-new-privileges:true \
        --cap-drop ALL \
        --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
        --cap-add SETGID --cap-add SETUID \
        -e POSTGRES_USER="$POSTGRES_USER" \
        -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
        -e POSTGRES_DB="$POSTGRES_DB" \
        -e PGDATA=/var/lib/postgresql/data/pgdata \
        -v "$DB_VOLUME":/var/lib/postgresql/data \
        -p "${DB_PORT}:5432" \
        --shm-size=1g \
        "$DB_IMAGE"

    wait_for_db

    # ---- Step 5: Enable pgvector extension ----
    log_info "Step 5/6: Enabling pgvector extension..."
    docker run --rm --network "$NETWORK_NAME" \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
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

        docker run --rm -i --network "$NETWORK_NAME" \
            -e PGPASSWORD="$POSTGRES_PASSWORD" \
            "$DB_IMAGE" \
            pg_restore -h "$DB_CONTAINER" \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            --clean --if-exists < "$backup_file" || true

        log_ok "Database restored from: $backup_file"

        # Run migrations to apply any schema changes since the backup
        log_info "Running migrations to apply any schema changes since backup..."
        docker run --rm \
            --network "$NETWORK_NAME" \
            -e DOCKER_ENV=true \
            -e DB_HOST="$DB_CONTAINER" \
            -e DB_PORT=5432 \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e DATABASE_URL="$(build_database_url "$DB_CONTAINER" 5432)" \
            "$APP_IMAGE" \
            alembic upgrade head
        log_ok "Migrations applied"
    else
        log_info "Step 6/6: Running Alembic migrations (fresh schema)..."
        docker run --rm \
            --network "$NETWORK_NAME" \
            -e DOCKER_ENV=true \
            -e DB_HOST="$DB_CONTAINER" \
            -e DB_PORT=5432 \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -e DATABASE_URL="$(build_database_url "$DB_CONTAINER" 5432)" \
            "$APP_IMAGE" \
            alembic upgrade head
        log_ok "Migrations complete — empty schema created"
    fi

    # ---- Verify ----
    log_info "Verifying database..."
    local table_count
    table_count=$(docker run --rm --network "$NETWORK_NAME" \
        -e PGPASSWORD="$POSTGRES_PASSWORD" \
        "$DB_IMAGE" \
        psql -h "$DB_CONTAINER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
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
