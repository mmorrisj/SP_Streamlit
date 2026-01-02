#!/bin/bash
# ============================================
# Run Database Services (PostgreSQL + Redis)
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
echo "Starting Database Services"
echo "=============================================="
echo ""

# Create network if it doesn't exist
docker network create softpower_net 2>/dev/null || echo "Network already exists"

# Create volumes if they don't exist
docker volume create postgres_data 2>/dev/null || true
docker volume create redis_data 2>/dev/null || true

echo "🐘 Starting PostgreSQL + pgvector..."
docker run -d \
    --name softpower_db \
    --network softpower_net \
    --restart unless-stopped \
    -e POSTGRES_USER=$POSTGRES_USER \
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
    -e POSTGRES_DB=$POSTGRES_DB \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -v postgres_data:/var/lib/postgresql/data \
    -p 5432:5432 \
    --shm-size=2gb \
    ankane/pgvector:latest

echo "✅ PostgreSQL started"
echo ""

echo "📦 Starting Redis..."
docker run -d \
    --name softpower_redis \
    --network softpower_net \
    --restart unless-stopped \
    -v redis_data:/data \
    -p 6379:6379 \
    redis:7-alpine \
    redis-server --appendonly yes --maxmemory 1gb --maxmemory-policy allkeys-lru

echo "✅ Redis started"
echo ""

echo "⏳ Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if docker exec softpower_db pg_isready -U $POSTGRES_USER -d $POSTGRES_DB > /dev/null 2>&1; then
        echo "✅ PostgreSQL is ready"
        break
    fi
    echo "   Waiting... ($i/30)"
    sleep 2
done

echo ""
echo "=============================================="
echo "✅ Database Services Running"
echo "=============================================="
echo ""
echo "Access:"
echo "  • PostgreSQL:  localhost:5432"
echo "  • Database:    $POSTGRES_DB"
echo "  • Username:    $POSTGRES_USER"
echo "  • Redis:       localhost:6379"
echo ""
echo "Useful commands:"
echo "  docker logs softpower_db          # View database logs"
echo "  docker logs softpower_redis       # View Redis logs"
echo "  docker exec -it softpower_db psql -U $POSTGRES_USER -d $POSTGRES_DB"
echo ""
