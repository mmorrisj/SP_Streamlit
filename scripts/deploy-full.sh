#!/bin/bash
# ============================================
# Full Production Stack Deployment
# Database + Pipeline + Web App + Streamlit
# ============================================

set -e  # Exit on error

echo ""
echo "=============================================="
echo "Soft Power Analytics - Full Stack Deployment"
echo "=============================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found"
    echo ""
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env from template"
        echo ""
        echo "⚠️  IMPORTANT: Edit .env with your credentials before continuing"
        echo ""
        read -p "Press Enter after editing .env, or Ctrl+C to cancel..."
    else
        echo "❌ Error: .env.example not found"
        exit 1
    fi
fi

echo "📦 Building Docker images..."
echo "   This includes:"
echo "   - PostgreSQL + pgvector"
echo "   - React web app (built inside Docker)"
echo "   - FastAPI backend"
echo "   - Streamlit dashboard"
echo "   - Pipeline processing service"
echo "   - Redis cache"
echo ""
echo "   ⏱️  Estimated time: 10-15 minutes (first build)"
echo ""

# Build all services
docker-compose -f docker-compose.full.yml build --parallel

echo ""
echo "✅ All images built successfully!"
echo ""
echo "🚀 Starting services..."
echo ""

# Start all services
docker-compose -f docker-compose.full.yml up -d

echo ""
echo "⏳ Waiting for database to be ready..."
echo ""

# Wait for database
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if docker-compose -f docker-compose.full.yml exec -T db pg_isready -U ${POSTGRES_USER:-matthew50} > /dev/null 2>&1; then
        echo "✅ Database is ready"
        break
    fi
    echo "   Waiting for PostgreSQL..."
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ Database failed to start"
    exit 1
fi

echo ""
echo "🔄 Running database migrations..."
echo ""

# Run migrations
docker-compose -f docker-compose.full.yml --profile migrate up

echo ""
echo "⏳ Waiting for services to be healthy..."
echo ""

# Wait for API
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✅ Web API is healthy"
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
    echo "  docker-compose -f docker-compose.full.yml logs api"
    exit 1
fi

# Wait for Streamlit
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f http://localhost:8501/_stcore/health > /dev/null 2>&1; then
        echo "✅ Streamlit dashboard is healthy"
        break
    fi
    echo "   Waiting for Streamlit..."
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

echo ""
echo "=============================================="
echo "✅ Full Stack Deployed Successfully!"
echo "=============================================="
echo ""
echo "🌐 Access Points:"
echo "  • React Web App:    http://localhost:8000"
echo "  • API Docs:         http://localhost:8000/docs"
echo "  • Streamlit:        http://localhost:8501"
echo "  • PostgreSQL:       localhost:5432"
echo "  • Redis:            localhost:6379"
echo ""
echo "🔧 Management (Optional):"
echo "  Start pgAdmin:      docker-compose -f docker-compose.full.yml --profile management up -d"
echo "  Access pgAdmin:     http://localhost:5050"
echo "    Email:            ${PGADMIN_EMAIL:-admin@softpower.local}"
echo "    Password:         ${PGADMIN_PASSWORD:-admin}"
echo ""
echo "⚙️  Pipeline Commands:"
echo "  # Document ingestion from S3"
echo "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/ingestion/dsr.py"
echo ""
echo "  # AI analysis"
echo "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/analysis/atom_extraction.py"
echo ""
echo "  # Generate embeddings"
echo "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/embeddings/embed_missing_documents.py --yes"
echo ""
echo "  # Event processing (Stage 1A)"
echo "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/events/batch_cluster_events.py --country China --start-date 2024-08-01 --end-date 2024-08-31"
echo ""
echo "📊 Useful Commands:"
echo "  • View all logs:    docker-compose -f docker-compose.full.yml logs -f"
echo "  • View API logs:    docker-compose -f docker-compose.full.yml logs -f api"
echo "  • View pipeline:    docker-compose -f docker-compose.full.yml logs -f pipeline"
echo "  • Stop all:         docker-compose -f docker-compose.full.yml down"
echo "  • Restart service:  docker-compose -f docker-compose.full.yml restart [service-name]"
echo ""
echo "📈 Next Steps:"
echo "  1. Access web app: http://localhost:8000"
echo "  2. Run pipeline to populate data (see commands above)"
echo "  3. View analytics in Streamlit: http://localhost:8501"
echo ""
