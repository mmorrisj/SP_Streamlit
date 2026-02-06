#!/bin/bash
# ============================================
# Deploy from Internal Registry
# Run after images are approved
# ============================================

set -e

# Registry configuration
REGISTRY="${REGISTRY:-registry.your-company.mil}"
PROJECT="${PROJECT:-softpower}"

echo ""
echo "=============================================="
echo "Soft Power Analytics - Registry Deployment"
echo "Registry: $REGISTRY/$PROJECT"
echo "=============================================="
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Check if .env exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env - Please edit with your credentials"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

echo "Step 1/6: Pulling approved images from registry..."
echo ""

docker pull ${REGISTRY}/${PROJECT}/pgvector:latest
docker pull ${REGISTRY}/${PROJECT}/redis:7-alpine
docker pull ${REGISTRY}/${PROJECT}/api:latest
docker pull ${REGISTRY}/${PROJECT}/dashboard:latest
docker pull ${REGISTRY}/${PROJECT}/pipeline:latest

echo ""
echo "Step 2/6: Tagging images for local use..."
echo ""

docker tag ${REGISTRY}/${PROJECT}/pgvector:latest ankane/pgvector:latest
docker tag ${REGISTRY}/${PROJECT}/redis:7-alpine redis:7-alpine
docker tag ${REGISTRY}/${PROJECT}/api:latest softpower-api:latest
docker tag ${REGISTRY}/${PROJECT}/dashboard:latest softpower-dashboard:latest
docker tag ${REGISTRY}/${PROJECT}/pipeline:latest softpower-pipeline:latest

echo "✅ Images ready"
echo ""

# Create network and volumes
docker network create softpower_net 2>/dev/null || echo "Network already exists"
docker volume create postgres_data 2>/dev/null || true
docker volume create redis_data 2>/dev/null || true

echo "Step 3/6: Starting database services..."
echo ""
"$SCRIPT_DIR/run-database.sh"

echo ""
echo "Step 4/6: Running database migrations..."
echo ""

sleep 5

docker run --rm \
    --network softpower_net \
    -e DB_HOST=softpower_db \
    -e DATABASE_URL=postgresql+psycopg2://${POSTGRES_USER:-matthew50}:${POSTGRES_PASSWORD:-softpower}@softpower_db:5432/${POSTGRES_DB:-softpower-db} \
    -v "$(pwd)/shared:/app/shared" \
    -v "$(pwd)/alembic:/app/alembic" \
    -v "$(pwd)/alembic.ini:/app/alembic.ini" \
    softpower-api:latest \
    alembic upgrade head

echo "✅ Migrations complete"
echo ""

echo "Step 5/6: Starting application services..."
echo ""
"$SCRIPT_DIR/run-webapp.sh"
"$SCRIPT_DIR/run-streamlit.sh"

echo ""
echo "Step 6/6: Starting pipeline worker..."
echo ""
"$SCRIPT_DIR/run-pipeline.sh"

echo ""
echo "=============================================="
echo "✅ Deployed from Registry Successfully!"
echo "=============================================="
echo ""
echo "Access Points:"
echo "  • Web App:    http://localhost:8000"
echo "  • Streamlit:  http://localhost:8501"
echo ""
