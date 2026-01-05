#!/bin/bash
# ============================================
# Build All Docker Images Separately
# For systems with Docker but no Docker Compose
# ============================================

set -e

echo ""
echo "=============================================="
echo "Building All Docker Images (Standalone Mode)"
echo "=============================================="
echo ""

# Create network if it doesn't exist
echo "📡 Creating Docker network..."
docker network create softpower_net 2>/dev/null || echo "Network already exists"
echo ""

# Create volumes if they don't exist
echo "💾 Creating Docker volumes..."
docker volume create postgres_data 2>/dev/null || echo "postgres_data already exists"
docker volume create pgadmin_data 2>/dev/null || echo "pgadmin_data already exists"
docker volume create redis_data 2>/dev/null || echo "redis_data already exists"
echo ""

# Build each service
echo "🔨 Building images..."
echo ""

echo "1/3 Building React Web App + FastAPI..."
docker build -f docker/api-production.Dockerfile -t softpower-api:latest .
echo "✅ API image built"
echo ""

echo "2/3 Building Streamlit Dashboard..."
docker build -f docker/dashboard.Dockerfile -t softpower-dashboard:latest .
echo "✅ Dashboard image built"
echo ""

echo "3/3 Building Pipeline Worker..."
docker build -f docker/pipeline.Dockerfile -t softpower-pipeline:latest .
echo "✅ Pipeline image built"
echo ""

echo "=============================================="
echo "✅ All Images Built Successfully!"
echo "=============================================="
echo ""
echo "Images created:"
echo "  • softpower-api:latest"
echo "  • softpower-dashboard:latest"
echo "  • softpower-pipeline:latest"
echo ""
echo "External images to be pulled:"
echo "  • ankane/pgvector:latest (PostgreSQL)"
echo "  • redis:7-alpine"
echo "  • dpage/pgadmin4:latest (optional)"
echo ""
echo "Next steps:"
echo "  ./docker/run-all.sh         # Start all services"
echo "  ./docker/run-database.sh    # Start only database"
echo "  ./docker/run-webapp.sh      # Start only web app"
echo ""
