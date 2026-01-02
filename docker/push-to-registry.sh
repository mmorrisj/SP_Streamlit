#!/bin/bash
# ============================================
# Push Images to Internal Container Registry
# Run on air-gapped system after loading tar files
# ============================================

set -e

# Configuration
REGISTRY="${REGISTRY:-registry.your-company.mil}"
PROJECT="${PROJECT:-softpower}"

echo ""
echo "=============================================="
echo "Push Images to Internal Registry"
echo "Registry: $REGISTRY"
echo "Project: $PROJECT"
echo "=============================================="
echo ""

# Check if logged in to registry
echo "🔐 Step 1: Docker registry login"
echo "Please login to your internal registry:"
docker login $REGISTRY

echo ""
echo "🏷️  Step 2: Tagging images for registry..."
echo ""

# Tag base images
docker tag ankane/pgvector:latest ${REGISTRY}/${PROJECT}/pgvector:latest
echo "  ✅ Tagged: ${REGISTRY}/${PROJECT}/pgvector:latest"

docker tag redis:7-alpine ${REGISTRY}/${PROJECT}/redis:7-alpine
echo "  ✅ Tagged: ${REGISTRY}/${PROJECT}/redis:7-alpine"

# Tag application images
docker tag softpower-api:latest ${REGISTRY}/${PROJECT}/api:latest
echo "  ✅ Tagged: ${REGISTRY}/${PROJECT}/api:latest"

docker tag softpower-dashboard:latest ${REGISTRY}/${PROJECT}/dashboard:latest
echo "  ✅ Tagged: ${REGISTRY}/${PROJECT}/dashboard:latest"

docker tag softpower-pipeline:latest ${REGISTRY}/${PROJECT}/pipeline:latest
echo "  ✅ Tagged: ${REGISTRY}/${PROJECT}/pipeline:latest"

echo ""
echo "📤 Step 3: Pushing images to registry..."
echo "(This will trigger security scanning)"
echo ""

docker push ${REGISTRY}/${PROJECT}/pgvector:latest
echo "  ✅ Pushed: pgvector"

docker push ${REGISTRY}/${PROJECT}/redis:7-alpine
echo "  ✅ Pushed: redis"

docker push ${REGISTRY}/${PROJECT}/api:latest
echo "  ✅ Pushed: api"

docker push ${REGISTRY}/${PROJECT}/dashboard:latest
echo "  ✅ Pushed: dashboard"

docker push ${REGISTRY}/${PROJECT}/pipeline:latest
echo "  ✅ Pushed: pipeline"

echo ""
echo "=============================================="
echo "✅ All Images Pushed to Registry"
echo "=============================================="
echo ""
echo "Images in registry:"
echo "  • ${REGISTRY}/${PROJECT}/pgvector:latest"
echo "  • ${REGISTRY}/${PROJECT}/redis:7-alpine"
echo "  • ${REGISTRY}/${PROJECT}/api:latest"
echo "  • ${REGISTRY}/${PROJECT}/dashboard:latest"
echo "  • ${REGISTRY}/${PROJECT}/pipeline:latest"
echo ""
echo "⚠️  NEXT STEPS:"
echo "1. Wait for security scans to complete"
echo "2. Review scan results with security team"
echo "3. Get images approved"
echo "4. Once approved, run: ./docker/run-all-registry.sh"
echo ""
echo "Check scan status in your registry web UI:"
echo "  https://${REGISTRY}"
echo ""
