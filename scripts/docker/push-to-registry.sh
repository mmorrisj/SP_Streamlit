#!/bin/bash
# ============================================
# Push Images to Container Registry
# ============================================
# Supports two image modes:
#
#   --registry (default)
#     Builds docker/registry.Dockerfile — fully self-contained image
#     (ML packages + HuggingFace model baked in, ~2GB).
#     For deployment via Docker Hub mirror: pull-and-run, no manual setup.
#     Pushes:
#       softpower-app  (FastAPI + Streamlit + React + ML, self-contained)
#
#   --airgap
#     Uses existing locally-built softpower-app-airgap:latest (slim image).
#     Requires airgap-build.sh to have been run first.
#     Pushes:
#       softpower-app-airgap  (slim — ML installed separately via setup)
#
# Note: pgvector is sourced from the company's existing mirror — no push needed.
#
# Usage:
#   ./scripts/docker/push-to-registry.sh [mode] [username] [version]
#   ./scripts/docker/push-to-registry.sh registry mmorrisj 1.5.4
#   ./scripts/docker/push-to-registry.sh airgap mmorrisj 1.5.4
#
#   Or via env vars (legacy):
#   REGISTRY=docker.io/yourusername VERSION=1.0.0 ./scripts/docker/push-to-registry.sh
#
# For Docker Hub, username is your Docker Hub username (docker.io/<username> is inferred).
# VERSION defaults to 1.0.0 if not set — always set it explicitly for releases.
# ============================================

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Parse positional and flag arguments
# Positional form: [mode] [username] [version]
# Flag form:       --registry / --airgap
MODE="registry"
_POS_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --airgap)   MODE="airgap" ;;
        --registry) MODE="registry" ;;
        *)          _POS_ARGS+=("$arg") ;;
    esac
done
# Positional: first=mode, second=username/registry, third=version
if [ "${#_POS_ARGS[@]}" -ge 1 ]; then
    case "${_POS_ARGS[0]}" in
        registry) MODE="registry" ;;
        airgap)   MODE="airgap" ;;
    esac
fi
if [ "${#_POS_ARGS[@]}" -ge 2 ] && [ -z "${REGISTRY:-}" ]; then
    _USER="${_POS_ARGS[1]}"
    # Accept bare username (mmorrisj) or full path (docker.io/mmorrisj)
    [[ "$_USER" == *"/"* ]] && REGISTRY="$_USER" || REGISTRY="docker.io/$_USER"
fi
if [ "${#_POS_ARGS[@]}" -ge 3 ] && [ -z "${VERSION:-}" ]; then
    VERSION="${_POS_ARGS[2]}"
fi

# Load .env if available
if [ -f "$PROJECT_ROOT/.env" ]; then
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | grep -v '^\s*$' | xargs)
fi

# Registry from env, argument, or prompt
REGISTRY="${REGISTRY:-${AIRGAP_REGISTRY:-}}"
if [ -z "$REGISTRY" ]; then
    echo -e "${YELLOW}No registry specified.${NC}"
    echo "Set REGISTRY or AIRGAP_REGISTRY in your .env, or pass as env var:"
    echo "  REGISTRY=docker.io/yourusername $0"
    echo ""
    read -p "Enter registry (e.g., docker.io/yourusername): " REGISTRY
    if [ -z "$REGISTRY" ]; then
        echo -e "${RED}Registry is required.${NC}"
        exit 1
    fi
fi

# Semantic version tag — must be set explicitly for each release
VERSION="${VERSION:-1.0.0}"

echo ""
echo "=============================================="
if [ "$MODE" = "registry" ]; then
    echo "Build & Push Registry Image (self-contained)"
else
    echo "Push Air-Gapped Images to Registry (slim)"
fi
echo "=============================================="
echo "Registry:  $REGISTRY"
echo "Version:   $VERSION"
echo "Mode:      $MODE"
echo "=============================================="
echo ""

APP_REMOTE_NAME="softpower-analytics"

# Extract just the hostname for login (e.g. "docker.io/mmorrisj" -> "docker.io")
REGISTRY_HOST="${REGISTRY%%/*}"

# ============================================
# Step 1: Docker login
# (Must happen before buildx --push for registry mode)
# ============================================
echo -e "${BLUE}[1/4]${NC} Docker registry login..."
echo ""

if docker login "$REGISTRY_HOST" 2>/dev/null; then
    echo -e "  ${GREEN}Logged in to $REGISTRY_HOST${NC}"
else
    echo -e "${RED}Login failed. Use a Personal Access Token as the password, not your account password.${NC}"
    echo "  Generate one at: https://hub.docker.com/settings/security"
    exit 1
fi
echo ""

# ============================================
# Step 2: Build or verify app image
# ============================================
if [ "$MODE" = "registry" ]; then
    echo -e "${BLUE}[2/4]${NC} Building self-contained registry image with supply-chain attestations..."
    echo "  Dockerfile: docker/registry.Dockerfile"
    echo "  SBOM: enabled (--sbom=true)"
    echo "  Provenance: max (--provenance=mode=max)"
    echo "  This installs ML packages + bakes in HuggingFace model (~2GB, takes several minutes)..."
    echo ""

    # Ensure a buildx builder capable of attestations is active.
    # 'docker-container' driver is required for --sbom / --provenance support.
    if ! docker buildx inspect softpower-builder &>/dev/null; then
        docker buildx create --name softpower-builder --driver docker-container --use
    else
        docker buildx use softpower-builder
    fi

    # Build and push directly to registry with both tags + attestations.
    # --push is required for attestation manifests (they can't be loaded locally).
    # --provenance=mode=max captures full build graph (vs min which only records base image).
    docker buildx build \
        --sbom=true \
        --provenance=mode=max \
        --push \
        --tag "${REGISTRY}/${APP_REMOTE_NAME}:latest" \
        --tag "${REGISTRY}/${APP_REMOTE_NAME}:${VERSION}" \
        -f "$PROJECT_ROOT/docker/registry.Dockerfile" \
        "$PROJECT_ROOT"

    echo -e "  ${GREEN}Built and pushed:${NC} ${REGISTRY}/${APP_REMOTE_NAME}:{latest,${VERSION}}"
    echo -e "  ${GREEN}Attestations:${NC} SBOM + provenance (max mode) attached"
else
    echo -e "${BLUE}[2/4]${NC} Verifying local airgap image..."
    APP_LOCAL="softpower-app-airgap:latest"
    if docker image inspect "$APP_LOCAL" &>/dev/null; then
        echo -e "  ${GREEN}Found:${NC} $APP_LOCAL"
    else
        echo -e "  ${RED}Missing:${NC} $APP_LOCAL"
        echo "  Build it first: ./scripts/docker/airgap-build.sh"
        exit 1
    fi
fi
echo ""

# ============================================
# Step 3: Tag and push (airgap mode only)
# Registry mode already pushed via buildx above.
# ============================================
if [ "$MODE" = "airgap" ]; then
    echo -e "${BLUE}[3/4]${NC} Tagging airgap image for registry..."
    echo ""
    docker tag "$APP_LOCAL" "${REGISTRY}/${APP_REMOTE_NAME}:latest"
    docker tag "$APP_LOCAL" "${REGISTRY}/${APP_REMOTE_NAME}:${VERSION}"
    echo -e "  ${GREEN}Tagged:${NC} ${REGISTRY}/${APP_REMOTE_NAME}:{latest,${VERSION}}"
    echo ""

    echo -e "${BLUE}[4/4]${NC} Pushing images to registry..."
    echo ""
    docker push "${REGISTRY}/${APP_REMOTE_NAME}:latest"
    docker push "${REGISTRY}/${APP_REMOTE_NAME}:${VERSION}"
    echo -e "  ${GREEN}Pushed:${NC} ${APP_REMOTE_NAME}"
    echo ""
else
    # Steps 3/4 already completed by buildx --push above
    echo -e "${BLUE}[3/4]${NC} Tag + push completed by buildx (skipped separate steps)"
    echo ""
    echo -e "${BLUE}[4/4]${NC} Attestation manifests pushed to registry"
    echo ""
fi

# ============================================
# Summary
# ============================================
echo "=============================================="
echo -e "${GREEN}All Images Pushed Successfully${NC}"
echo "=============================================="
echo ""
echo "Images in registry:"
echo "  ${REGISTRY}/${APP_REMOTE_NAME}:latest"
echo "  ${REGISTRY}/${APP_REMOTE_NAME}:${VERSION}"
echo ""
echo "To pull on another machine:"
echo "  docker pull ${REGISTRY}/${APP_REMOTE_NAME}:latest"
echo ""
if [ "$MODE" = "registry" ]; then
    echo "To run (self-contained, no setup steps needed):"
    echo "  docker pull ${REGISTRY}/${APP_REMOTE_NAME}:latest"
    echo "  docker run -d --name softpower_app --env-file .env \\"
    echo "    -p 8000:8000 -p 8501:8501 \\"
    echo "    ${REGISTRY}/${APP_REMOTE_NAME}:latest"
else
    echo "To use with airgap-deploy.sh, set in .env:"
    echo "  AIRGAP_REGISTRY=${REGISTRY}"
    echo ""
    echo "Then run:"
    echo "  DEPLOY_MODE=standard ./scripts/docker/airgap-deploy.sh start"
fi
echo ""
