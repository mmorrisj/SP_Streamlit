#!/bin/bash
# ============================================
# Stop All Services
# Standalone Docker (no Docker Compose)
# ============================================

echo ""
echo "=============================================="
echo "Stopping All Services"
echo "=============================================="
echo ""

echo "🛑 Stopping containers..."

docker stop softpower_pipeline 2>/dev/null && echo "✅ Pipeline stopped" || echo "⚠️  Pipeline not running"
docker stop softpower_dashboard 2>/dev/null && echo "✅ Streamlit stopped" || echo "⚠️  Streamlit not running"
docker stop softpower_api 2>/dev/null && echo "✅ Web app stopped" || echo "⚠️  Web app not running"
docker stop softpower_redis 2>/dev/null && echo "✅ Redis stopped" || echo "⚠️  Redis not running"
docker stop softpower_db 2>/dev/null && echo "✅ PostgreSQL stopped" || echo "⚠️  PostgreSQL not running"

echo ""
echo "🗑️  Removing containers..."

docker rm softpower_pipeline 2>/dev/null && echo "✅ Pipeline removed" || true
docker rm softpower_dashboard 2>/dev/null && echo "✅ Streamlit removed" || true
docker rm softpower_api 2>/dev/null && echo "✅ Web app removed" || true
docker rm softpower_redis 2>/dev/null && echo "✅ Redis removed" || true
docker rm softpower_db 2>/dev/null && echo "✅ PostgreSQL removed" || true

echo ""
echo "=============================================="
echo "✅ All Services Stopped"
echo "=============================================="
echo ""
echo "Data preserved in volumes:"
echo "  • postgres_data"
echo "  • redis_data"
echo ""
echo "To remove data (WARNING: deletes all data):"
echo "  docker volume rm postgres_data redis_data"
echo ""
echo "To restart services:"
echo "  ./docker/run-all.sh"
echo ""
