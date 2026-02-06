#!/bin/bash
# ============================================
# Run Web Application (React + FastAPI)
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
echo "Starting Web Application"
echo "=============================================="
echo ""

# Check if database is running
if ! docker ps --format '{{.Names}}' | grep -q '^softpower_db$'; then
    echo "❌ Error: Database not running"
    echo "   Start it first: ./docker/run-database.sh"
    exit 1
fi

echo "🌐 Starting React Web App + FastAPI..."
docker run -d \
    --name softpower_api \
    --network softpower_net \
    --restart unless-stopped \
    -e DOCKER_ENV=true \
    -e NODE_ENV=production \
    -e DB_HOST=softpower_db \
    -e DB_PORT=5432 \
    -e POSTGRES_HOST=softpower_db \
    -e POSTGRES_PORT=5432 \
    -e POSTGRES_USER=$POSTGRES_USER \
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
    -e POSTGRES_DB=$POSTGRES_DB \
    -e DATABASE_URL=postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB} \
    -e REDIS_URL=redis://softpower_redis:6379 \
    -e CLAUDE_KEY=${CLAUDE_KEY} \
    -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
    -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
    -v "$(pwd)/shared/config/config.yaml:/app/shared/config/config.yaml:ro" \
    -v "$(pwd)/_data:/app/_data" \
    -p 8000:8000 \
    --add-host=host.docker.internal:host-gateway \
    softpower-api:latest

echo "✅ Web app started"
echo ""

echo "⏳ Waiting for API to be healthy..."
for i in {1..30}; do
    if curl -f http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✅ API is healthy"
        break
    fi
    echo "   Waiting... ($i/30)"
    sleep 2
done

echo ""
echo "=============================================="
echo "✅ Web Application Running"
echo "=============================================="
echo ""
echo "Access:"
echo "  • Web App:     http://localhost:8000"
echo "  • API Docs:    http://localhost:8000/docs"
echo "  • Health:      http://localhost:8000/api/health"
echo ""
echo "Useful commands:"
echo "  docker logs -f softpower_api      # View logs"
echo "  docker restart softpower_api      # Restart"
echo "  docker stop softpower_api         # Stop"
echo ""
