#!/bin/bash
# ============================================
# Full Docker Build Script
# Builds React inside Docker (multi-stage build)
# ============================================

set -e  # Exit on error

API_PORT="${API_PORT:-8000}"

echo ""
echo "=========================================="
echo "Soft Power Analytics - Docker Build"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found"
    echo ""
    echo "Creating .env from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env file"
        echo ""
        echo "⚠️  IMPORTANT: Edit .env with your credentials before continuing"
        echo ""
        read -p "Press Enter after editing .env, or Ctrl+C to cancel..."
    else
        echo "❌ Error: .env.example not found"
        exit 1
    fi
fi

echo "📦 Building Docker images (this may take 8-12 minutes)..."
echo ""

# Build all services
docker-compose -f docker-compose.build.yml build --progress=plain

echo ""
echo "✅ Build complete!"
echo ""
echo "🚀 Starting services..."
echo ""

# Start services
docker-compose -f docker-compose.build.yml up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
echo ""

# Wait for database to be ready
until docker-compose -f docker-compose.build.yml exec -T db pg_isready -U ${POSTGRES_USER:-matthew50} > /dev/null 2>&1; do
    echo "   Waiting for PostgreSQL..."
    sleep 2
done

echo "✅ Database ready"
echo ""

# Run migrations
echo "🔄 Running database migrations..."
docker-compose -f docker-compose.build.yml --profile migrate up

echo ""
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "Access points:"
echo "  • Web App:       http://localhost:${API_PORT}"
echo "  • API Docs:      http://localhost:${API_PORT}/docs"
echo "  • Streamlit:     http://localhost:8501"
echo "  • PostgreSQL:    localhost:5432"
echo ""
echo "Useful commands:"
echo "  • View logs:     docker-compose -f docker-compose.build.yml logs -f api"
echo "  • Stop all:      docker-compose -f docker-compose.build.yml down"
echo "  • Rebuild:       docker-compose -f docker-compose.build.yml up -d --build"
echo ""
echo "Next steps:"
echo "  1. Check health: curl http://localhost:${API_PORT}/api/health"
echo "  2. Populate data: See client/README.md 'Data Population Pipeline'"
echo ""
