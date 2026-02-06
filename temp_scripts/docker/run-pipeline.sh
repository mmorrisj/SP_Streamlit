#!/bin/bash
# ============================================
# Run Pipeline Worker
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
echo "Starting Pipeline Worker"
echo "=============================================="
echo ""

# Check if database is running
if ! docker ps --format '{{.Names}}' | grep -q '^softpower_db$'; then
    echo "❌ Error: Database not running"
    echo "   Start it first: ./docker/run-database.sh"
    exit 1
fi

echo "⚙️  Starting Pipeline Worker..."
docker run -d \
    --name softpower_pipeline \
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
    -e REDIS_URL=redis://softpower_redis:6379 \
    -e CLAUDE_KEY=${CLAUDE_KEY} \
    -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
    -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    -v "$(pwd)/services/pipeline:/app/services/pipeline" \
    -v "$(pwd)/shared:/app/shared" \
    -v "$(pwd)/_data:/app/_data" \
    -v "$(pwd)/shared/config/config.yaml:/app/shared/config/config.yaml" \
    --gpus all \
    softpower-pipeline:latest \
    tail -f /dev/null

echo "✅ Pipeline worker started"
echo ""

echo "=============================================="
echo "✅ Pipeline Worker Running"
echo "=============================================="
echo ""
echo "Run pipeline tasks:"
echo "  # Document ingestion"
echo "  docker exec softpower_pipeline python services/pipeline/ingestion/dsr.py"
echo ""
echo "  # AI analysis"
echo "  docker exec softpower_pipeline python services/pipeline/analysis/atom_extraction.py"
echo ""
echo "  # Generate embeddings"
echo "  docker exec softpower_pipeline python services/pipeline/embeddings/embed_missing_documents.py --yes"
echo ""
echo "  # Event processing"
echo "  docker exec softpower_pipeline python services/pipeline/events/batch_cluster_events.py --country China --start-date 2024-08-01 --end-date 2024-08-31"
echo ""
echo "View logs:"
echo "  docker logs -f softpower_pipeline"
echo ""
echo "Note: Remove --gpus all flag if no GPU available"
echo ""
