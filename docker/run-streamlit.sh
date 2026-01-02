#!/bin/bash
# ============================================
# Run Streamlit Dashboard
# Standalone Docker (no Docker Compose)
# ============================================

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Defaults
POSTGRES_USER=${POSTGRES_USER:-matthew50}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-softpower}
POSTGRES_DB=${POSTGRES_DB:-softpower-db}

echo ""
echo "=============================================="
echo "Starting Streamlit Dashboard"
echo "=============================================="
echo ""

# Check if database is running
if ! docker ps --format '{{.Names}}' | grep -q '^softpower_db$'; then
    echo "❌ Error: Database not running"
    echo "   Start it first: ./docker/run-database.sh"
    exit 1
fi

echo "📊 Starting Streamlit Dashboard..."
docker run -d \
    --name softpower_dashboard \
    --network softpower_net \
    --restart unless-stopped \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db \
    -e DB_PORT=5432 \
    -e POSTGRES_HOST=softpower_db \
    -e POSTGRES_PORT=5432 \
    -e POSTGRES_USER=$POSTGRES_USER \
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
    -e POSTGRES_DB=$POSTGRES_DB \
    -e DATABASE_URL=postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB} \
    -e BACKEND_API_URL=http://softpower_api:8000 \
    -e API_URL=http://softpower_api:8000 \
    -e REDIS_URL=redis://softpower_redis:6379 \
    -v "$(pwd)/services/dashboard:/app/services/dashboard:ro" \
    -v "$(pwd)/shared:/app/shared:ro" \
    -p 8501:8501 \
    softpower-dashboard:latest

echo "✅ Streamlit started"
echo ""

echo "⏳ Waiting for Streamlit to be healthy..."
for i in {1..30}; do
    if curl -f http://localhost:8501/_stcore/health > /dev/null 2>&1; then
        echo "✅ Streamlit is healthy"
        break
    fi
    echo "   Waiting... ($i/30)"
    sleep 2
done

echo ""
echo "=============================================="
echo "✅ Streamlit Dashboard Running"
echo "=============================================="
echo ""
echo "Access:"
echo "  • Dashboard:   http://localhost:8501"
echo ""
echo "Useful commands:"
echo "  docker logs -f softpower_dashboard    # View logs"
echo "  docker restart softpower_dashboard    # Restart"
echo "  docker stop softpower_dashboard       # Stop"
echo ""
