#!/bin/bash
# ============================================
# Deploy Web App to Existing Database
# No database setup needed - connects to existing
# ============================================

set -e  # Exit on error

API_PORT="${API_PORT:-8000}"

echo ""
echo "=========================================="
echo "Web App Deployment (Existing Database)"
echo "=========================================="
echo ""

# Check if existing database container is running
if ! docker ps --format '{{.Names}}' | grep -q '^softpower_db$'; then
    echo "❌ Error: PostgreSQL container 'softpower_db' is not running"
    echo ""
    echo "Please start your database first:"
    echo "  docker start softpower_db"
    echo ""
    exit 1
fi

echo "✅ Found existing database: softpower_db"
echo ""

# Check if database has data
DOC_COUNT=$(docker exec softpower_db psql -U ${POSTGRES_USER:-matthew50} -d ${POSTGRES_DB:-softpower-db} -t -c "SELECT COUNT(*) FROM documents;" 2>/dev/null | tr -d ' ')

if [ -z "$DOC_COUNT" ]; then
    echo "⚠️  Warning: Could not query documents table"
    echo "   Database may be empty or credentials incorrect"
    echo ""
else
    echo "✅ Database contains $DOC_COUNT documents"
    echo ""
fi

# Check if network exists
if ! docker network ls --format '{{.Name}}' | grep -q '^softpower_net$'; then
    echo "⚠️  Network 'softpower_net' not found, creating..."
    docker network create softpower_net
    echo "✅ Network created"
    echo ""
fi

echo "📦 Building web app Docker image..."
echo "   (This builds React inside Docker - may take 8-12 minutes)"
echo ""

# Build web app image
docker-compose -f docker-compose.webapp.yml build --progress=plain

echo ""
echo "✅ Build complete!"
echo ""
echo "🚀 Starting web app..."
echo ""

# Start web app (connects to existing database)
docker-compose -f docker-compose.webapp.yml up -d

echo ""
echo "⏳ Waiting for API to be healthy..."
echo ""

# Wait for API health check
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f http://localhost:${API_PORT}/api/health > /dev/null 2>&1; then
        echo "✅ API is healthy"
        break
    fi
    echo "   Waiting for API..."
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ API failed to start"
    echo ""
    echo "Check logs:"
    echo "  docker-compose -f docker-compose.webapp.yml logs api"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ Web App Deployed Successfully!"
echo "=========================================="
echo ""
echo "Access points:"
echo "  • Web App:       http://localhost:${API_PORT}"
echo "  • API Docs:      http://localhost:${API_PORT}/docs"
echo "  • API Health:    http://localhost:${API_PORT}/api/health"
echo ""
echo "Database:"
echo "  • Container:     softpower_db (existing)"
echo "  • Documents:     $DOC_COUNT"
echo ""
echo "Useful commands:"
echo "  • View logs:     docker-compose -f docker-compose.webapp.yml logs -f api"
echo "  • Stop web app:  docker-compose -f docker-compose.webapp.yml down"
echo "  • Rebuild:       docker-compose -f docker-compose.webapp.yml up -d --build"
echo ""
echo "Optional: Start Streamlit dashboard:"
echo "  docker-compose -f docker-compose.webapp.yml --profile dashboard up -d"
echo ""
