#!/bin/bash
# Build and Push SoftPower Analytics Images to Docker Hub
# Usage: ./build-and-push.sh [your-dockerhub-username] [version]

set -e

# Configuration
DOCKER_USERNAME="${1:-yourusername}"  # Replace with your Docker Hub username
VERSION="${2:-latest}"

echo "========================================="
echo "Building and Pushing SoftPower Images"
echo "Docker Hub Username: $DOCKER_USERNAME"
echo "Version: $VERSION"
echo "========================================="

# Step 1: Login to Docker Hub
echo ""
echo "[1/4] Logging into Docker Hub..."
docker login

# Step 2: Create buildx builder (for multi-architecture support)
echo ""
echo "[2/4] Setting up buildx for multi-architecture builds..."
docker buildx create --name softpower-builder --driver docker-container --use 2>/dev/null || docker buildx use softpower-builder
docker buildx inspect --bootstrap

# Step 3: Build and push API service (includes React frontend)
echo ""
echo "[3/4] Building and pushing API service (with React frontend)..."
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/api-production.Dockerfile \
  -t $DOCKER_USERNAME/softpower-api:latest \
  -t $DOCKER_USERNAME/softpower-api:$VERSION \
  --push \
  .

# Step 4: Build and push Dashboard service
echo ""
echo "[4/4] Building and pushing Dashboard service..."
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/dashboard.Dockerfile \
  -t $DOCKER_USERNAME/softpower-dashboard:latest \
  -t $DOCKER_USERNAME/softpower-dashboard:$VERSION \
  --push \
  .

echo ""
echo "========================================="
echo "✅ Successfully pushed images to Docker Hub!"
echo "========================================="
echo ""
echo "Images pushed:"
echo "  - $DOCKER_USERNAME/softpower-api:latest"
echo "  - $DOCKER_USERNAME/softpower-api:$VERSION"
echo "  - $DOCKER_USERNAME/softpower-dashboard:latest"
echo "  - $DOCKER_USERNAME/softpower-dashboard:$VERSION"
echo ""
echo "Next steps:"
echo "  1. Update docker-compose.production.yml with your username"
echo "  2. Share docker-compose.production.yml with users"
echo "  3. Users can deploy with: docker-compose -f docker-compose.production.yml up -d"
echo ""
