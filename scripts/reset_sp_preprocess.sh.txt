#!/usr/bin/env bash
# Rebuild and recreate the standalone sp-preprocess container.
#
# Usage:
#   bash scripts/reset_sp_preprocess.sh
#   bash scripts/reset_sp_preprocess.sh --no-build
#   bash scripts/reset_sp_preprocess.sh --no-cache
#
# Optional env overrides:
#   IMAGE_NAME, CONTAINER_NAME, DOCKERFILE, ENV_FILE

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-softpower-preprocessing:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-sp-preprocess}"
DOCKERFILE="${DOCKERFILE:-docker/preprocessing.Dockerfile}"
ENV_FILE="${ENV_FILE:-.env.docker}"

SKIP_BUILD=0
NO_CACHE=0

usage() {
    cat <<'EOF'
Usage: reset_sp_preprocess.sh [options]

Options:
  --no-build   Recreate container without rebuilding image
  --no-cache   Build image without Docker cache
  -h, --help   Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-build)
            SKIP_BUILD=1
            shift
            ;;
        --no-cache)
            NO_CACHE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is not installed or not on PATH."
    exit 1
fi

if [[ ! -f "$DOCKERFILE" ]]; then
    echo "ERROR: Dockerfile not found: $DOCKERFILE"
    exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: env file not found: $ENV_FILE"
    exit 1
fi

echo "Project root: $PROJECT_ROOT"
echo "Image:        $IMAGE_NAME"
echo "Container:    $CONTAINER_NAME"

if [[ "$SKIP_BUILD" -eq 0 ]]; then
    BUILD_ARGS=()
    if [[ "$NO_CACHE" -eq 1 ]]; then
        BUILD_ARGS+=(--no-cache)
    fi

    echo "Building image..."
    docker build "${BUILD_ARGS[@]}" -f "$DOCKERFILE" -t "$IMAGE_NAME" .
else
    echo "Skipping image build (--no-build)."
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    echo "Removing existing container: $CONTAINER_NAME"
    docker rm -f "$CONTAINER_NAME"
fi

echo "Creating container: $CONTAINER_NAME"
docker run -d --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --env-file "$ENV_FILE" \
    -v "${PROJECT_ROOT}/data:/app/data" \
    -v "${PROJECT_ROOT}/_data:/app/_data" \
    "$IMAGE_NAME" \
    sleep infinity

echo "Container recreated successfully."
echo "Try:"
echo "  docker exec -it $CONTAINER_NAME python services/run_ingestion_pipeline.py --help"
