#!/bin/bash
# ============================================
# Push Air-Gapped Images to Container Registry
# ============================================
# Pushes the 2-container airgap stack to a registry:
#   1. softpower-app-airgap  (FastAPI + Streamlit consolidated)
#   2. pgvector/pgvector     (PostgreSQL 16 + pgvector)
#
# Usage:
#   REGISTRY=docker.io/yourusername ./scripts/docker/push-to-registry.sh
#   REGISTRY=registry.company.mil/softpower ./scripts/docker/push-to-registry.sh
#
# For Docker Hub, REGISTRY should be: docker.io/<your-dockerhub-username>
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

# Version tag (date-based, overridable)
VERSION="${VERSION:-$(date +%Y%m%d)}"

# Source images (must exist locally)
APP_LOCAL="softpower-app-airgap:latest"
DB_LOCAL="pgvector/pgvector:0.8.0-pg16"

echo ""
echo "=============================================="
echo "Push Air-Gapped Images to Registry"
echo "=============================================="
echo "Registry:  $REGISTRY"
echo "Version:   $VERSION"
echo "=============================================="
echo ""

# ============================================
# Step 1: Verify local images exist
# ============================================
echo -e "${BLUE}[1/4]${NC} Verifying local images..."
echo ""

for img in "$APP_LOCAL" "$DB_LOCAL"; do
    if docker image inspect "$img" &>/dev/null; then
        echo -e "  ${GREEN}Found:${NC} $img"
    else
        echo -e "  ${RED}Missing:${NC} $img"
        if [ "$img" = "$APP_LOCAL" ]; then
            echo "  Build it first: ./scripts/docker/airgap-build.sh"
        else
            echo "  Pull it first:  docker pull $img"
        fi
        exit 1
    fi
done
echo ""

# ============================================
# Step 2: Docker login
# ============================================
echo -e "${BLUE}[2/4]${NC} Docker registry login..."
echo ""

# Check if already logged in by attempting a token-based check
if docker login "$REGISTRY" --get-login &>/dev/null 2>&1; then
    echo -e "  ${GREEN}Already logged in to $REGISTRY${NC}"
else
    docker login "$REGISTRY"
fi
echo ""

# ============================================
# Step 3: Tag images
# ============================================
echo -e "${BLUE}[3/4]${NC} Tagging images for registry..."
echo ""

# Tag with both :latest and :YYYYMMDD
docker tag "$APP_LOCAL" "${REGISTRY}/softpower-app-airgap:latest"
docker tag "$APP_LOCAL" "${REGISTRY}/softpower-app-airgap:${VERSION}"
echo -e "  ${GREEN}Tagged:${NC} ${REGISTRY}/softpower-app-airgap:{latest,${VERSION}}"

docker tag "$DB_LOCAL" "${REGISTRY}/pgvector:0.8.0-pg16"
echo -e "  ${GREEN}Tagged:${NC} ${REGISTRY}/pgvector:0.8.0-pg16"
echo ""

# ============================================
# Step 4: Push images
# ============================================
echo -e "${BLUE}[4/4]${NC} Pushing images to registry..."
echo ""

docker push "${REGISTRY}/softpower-app-airgap:latest"
docker push "${REGISTRY}/softpower-app-airgap:${VERSION}"
echo -e "  ${GREEN}Pushed:${NC} softpower-app-airgap"

docker push "${REGISTRY}/pgvector:0.8.0-pg16"
echo -e "  ${GREEN}Pushed:${NC} pgvector"
echo ""

# ============================================
# Summary
# ============================================
echo "=============================================="
echo -e "${GREEN}All Images Pushed Successfully${NC}"
echo "=============================================="
echo ""
echo "Images in registry:"
echo "  ${REGISTRY}/softpower-app-airgap:latest"
echo "  ${REGISTRY}/softpower-app-airgap:${VERSION}"
echo "  ${REGISTRY}/pgvector:0.8.0-pg16"
echo ""
echo "To pull on another machine:"
echo "  docker pull ${REGISTRY}/softpower-app-airgap:latest"
echo "  docker pull ${REGISTRY}/pgvector:0.8.0-pg16"
echo ""
echo "To use with airgap-deploy.sh, set in .env:"
echo "  AIRGAP_REGISTRY=${REGISTRY}"
echo ""
echo "Then run:"
echo "  DEPLOY_MODE=standard ./scripts/docker/airgap-deploy.sh start"
echo ""
