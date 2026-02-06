# ============================================
# Full Production Stack Deployment (PowerShell)
# Database + Pipeline + Web App + Streamlit
# ============================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "Soft Power Analytics - Full Stack Deployment" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""

# Check if .env exists
if (-not (Test-Path .env)) {
    Write-Host "⚠️  Warning: .env file not found" -ForegroundColor Yellow
    Write-Host ""
    if (Test-Path .env.example) {
        Copy-Item .env.example .env
        Write-Host "✅ Created .env from template" -ForegroundColor Green
        Write-Host ""
        Write-Host "⚠️  IMPORTANT: Edit .env with your credentials before continuing" -ForegroundColor Yellow
        Write-Host ""
        Read-Host "Press Enter after editing .env, or Ctrl+C to cancel"
    } else {
        Write-Host "❌ Error: .env.example not found" -ForegroundColor Red
        exit 1
    }
}

Write-Host "📦 Building Docker images..." -ForegroundColor Cyan
Write-Host "   This includes:"
Write-Host "   - PostgreSQL + pgvector"
Write-Host "   - React web app (built inside Docker)"
Write-Host "   - FastAPI backend"
Write-Host "   - Streamlit dashboard"
Write-Host "   - Pipeline processing service"
Write-Host "   - Redis cache"
Write-Host ""
Write-Host "   ⏱️  Estimated time: 10-15 minutes (first build)" -ForegroundColor Yellow
Write-Host ""

# Build all services
docker-compose -f docker-compose.full.yml build --parallel

Write-Host ""
Write-Host "✅ All images built successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Starting services..." -ForegroundColor Cyan
Write-Host ""

# Start all services
docker-compose -f docker-compose.full.yml up -d

Write-Host ""
Write-Host "⏳ Waiting for database to be ready..." -ForegroundColor Cyan
Write-Host ""

# Wait for database
$maxRetries = 30
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    $dbReady = docker-compose -f docker-compose.full.yml exec -T db pg_isready -U matthew50 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Database is ready" -ForegroundColor Green
        break
    }
    Write-Host "   Waiting for PostgreSQL..." -ForegroundColor Gray
    Start-Sleep -Seconds 2
    $retryCount++
}

if ($retryCount -eq $maxRetries) {
    Write-Host "❌ Database failed to start" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "🔄 Running database migrations..." -ForegroundColor Cyan
Write-Host ""

# Run migrations
docker-compose -f docker-compose.full.yml --profile migrate up

Write-Host ""
Write-Host "⏳ Waiting for services to be healthy..." -ForegroundColor Cyan
Write-Host ""

# Wait for API
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 2 2>$null
        if ($response.StatusCode -eq 200) {
            Write-Host "✅ Web API is healthy" -ForegroundColor Green
            break
        }
    } catch {
        # Not ready yet
    }
    Write-Host "   Waiting for API..." -ForegroundColor Gray
    Start-Sleep -Seconds 2
    $retryCount++
}

if ($retryCount -eq $maxRetries) {
    Write-Host "❌ API failed to start" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check logs:"
    Write-Host "  docker-compose -f docker-compose.full.yml logs api"
    exit 1
}

# Wait for Streamlit
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8501/_stcore/health" -UseBasicParsing -TimeoutSec 2 2>$null
        if ($response.StatusCode -eq 200) {
            Write-Host "✅ Streamlit dashboard is healthy" -ForegroundColor Green
            break
        }
    } catch {
        # Not ready yet
    }
    Write-Host "   Waiting for Streamlit..." -ForegroundColor Gray
    Start-Sleep -Seconds 2
    $retryCount++
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "✅ Full Stack Deployed Successfully!" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""
Write-Host "🌐 Access Points:" -ForegroundColor Cyan
Write-Host "  • React Web App:    http://localhost:8000"
Write-Host "  • API Docs:         http://localhost:8000/docs"
Write-Host "  • Streamlit:        http://localhost:8501"
Write-Host "  • PostgreSQL:       localhost:5432"
Write-Host "  • Redis:            localhost:6379"
Write-Host ""
Write-Host "🔧 Management (Optional):" -ForegroundColor Cyan
Write-Host "  Start pgAdmin:      docker-compose -f docker-compose.full.yml --profile management up -d"
Write-Host "  Access pgAdmin:     http://localhost:5050"
Write-Host "    Email:            admin@softpower.local"
Write-Host "    Password:         admin"
Write-Host ""
Write-Host "⚙️  Pipeline Commands:" -ForegroundColor Cyan
Write-Host "  # Document ingestion from S3"
Write-Host "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/ingestion/dsr.py"
Write-Host ""
Write-Host "  # AI analysis"
Write-Host "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/analysis/atom_extraction.py"
Write-Host ""
Write-Host "  # Generate embeddings"
Write-Host "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/embeddings/embed_missing_documents.py --yes"
Write-Host ""
Write-Host "  # Event processing (Stage 1A)"
Write-Host "  docker-compose -f docker-compose.full.yml exec pipeline python services/pipeline/events/batch_cluster_events.py --country China --start-date 2024-08-01 --end-date 2024-08-31"
Write-Host ""
Write-Host "📊 Useful Commands:" -ForegroundColor Cyan
Write-Host "  • View all logs:    docker-compose -f docker-compose.full.yml logs -f"
Write-Host "  • View API logs:    docker-compose -f docker-compose.full.yml logs -f api"
Write-Host "  • View pipeline:    docker-compose -f docker-compose.full.yml logs -f pipeline"
Write-Host "  • Stop all:         docker-compose -f docker-compose.full.yml down"
Write-Host "  • Restart service:  docker-compose -f docker-compose.full.yml restart [service-name]"
Write-Host ""
Write-Host "📈 Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Access web app: http://localhost:8000"
Write-Host "  2. Run pipeline to populate data (see commands above)"
Write-Host "  3. View analytics in Streamlit: http://localhost:8501"
Write-Host ""
