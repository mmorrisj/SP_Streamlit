#!/bin/bash
# ============================================
# Run All Services (Standalone Docker)
# No Docker Compose Required
# ============================================

set -e

API_PORT="${API_PORT:-8000}"

echo ""
echo "=============================================="
echo "Soft Power Analytics - Full Deployment"
echo "Standalone Docker Mode"
echo "=============================================="
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env from template"
        echo ""
        echo "⚠️  IMPORTANT: Edit .env with your credentials"
        read -p "Press Enter after editing .env, or Ctrl+C to cancel..."
    else
        echo "❌ Error: .env.example not found"
        exit 1
    fi
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

echo "Step 1/6: Building Docker images..."
echo ""
"$SCRIPT_DIR/build-all.sh"

echo ""
echo "Step 2/6: Starting database services..."
echo ""
"$SCRIPT_DIR/run-database.sh"

echo ""
echo "Step 3/6: Running database migrations..."
echo ""

# Wait for database to be ready
echo "⏳ Waiting for database..."
sleep 5

# Run migrations
echo "🔄 Running Alembic migrations..."
docker run --rm \
    --network softpower_net \
    -e DB_HOST=softpower_db \
    -e POSTGRES_USER=${POSTGRES_USER:-matthew50} \
    -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-softpower} \
    -e POSTGRES_DB=${POSTGRES_DB:-softpower-db} \
    -e DATABASE_URL=postgresql+psycopg2://${POSTGRES_USER:-matthew50}:${POSTGRES_PASSWORD:-softpower}@softpower_db:5432/${POSTGRES_DB:-softpower-db} \
    -v "$(pwd)/shared:/app/shared" \
    -v "$(pwd)/alembic:/app/alembic" \
    -v "$(pwd)/alembic.ini:/app/alembic.ini" \
    softpower-api:latest \
    alembic upgrade head

echo "✅ Migrations complete"
echo ""

echo "Step 4/6: Starting web application..."
echo ""
"$SCRIPT_DIR/run-webapp.sh"

echo ""
echo "Step 5/6: Starting Streamlit dashboard..."
echo ""
"$SCRIPT_DIR/run-streamlit.sh"

echo ""
echo "Step 6/6: Starting pipeline worker..."
echo ""
"$SCRIPT_DIR/run-pipeline.sh"

echo ""
echo "=============================================="
echo "✅ Full Stack Deployed Successfully!"
echo "=============================================="
echo ""
echo "🌐 Access Points:"
echo "  • React Web App:    http://localhost:${API_PORT}"
echo "  • API Docs:         http://localhost:${API_PORT}/docs"
echo "  • Streamlit:        http://localhost:8501"
echo "  • PostgreSQL:       localhost:5432"
echo "  • Redis:            localhost:6379"
echo ""
echo "⚙️  Pipeline Commands:"
echo "  docker exec softpower_pipeline python services/pipeline/ingestion/dsr.py"
echo "  docker exec softpower_pipeline python services/pipeline/analysis/atom_extraction.py"
echo "  docker exec softpower_pipeline python services/pipeline/embeddings/embed_missing_documents.py --yes"
echo ""
echo "📊 View Logs:"
echo "  docker logs -f softpower_api         # Web app logs"
echo "  docker logs -f softpower_dashboard   # Streamlit logs"
echo "  docker logs -f softpower_pipeline    # Pipeline logs"
echo "  docker logs -f softpower_db          # Database logs"
echo ""
echo "🛑 Stop All Services:"
echo "  ./docker/stop-all.sh"
echo ""
