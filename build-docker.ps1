# ============================================
# Full Docker Build Script (PowerShell)
# Builds React inside Docker (multi-stage build)
# ============================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Soft Power Analytics - Docker Build" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# Check if .env exists
if (-not (Test-Path .env)) {
    Write-Host "⚠️  Warning: .env file not found" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Creating .env from .env.example..."

    if (Test-Path .env.example) {
        Copy-Item .env.example .env
        Write-Host "✅ Created .env file" -ForegroundColor Green
        Write-Host ""
        Write-Host "⚠️  IMPORTANT: Edit .env with your credentials before continuing" -ForegroundColor Yellow
        Write-Host ""
        Read-Host "Press Enter after editing .env, or Ctrl+C to cancel"
    } else {
        Write-Host "❌ Error: .env.example not found" -ForegroundColor Red
        exit 1
    }
}

Write-Host "📦 Building Docker images (this may take 8-12 minutes)..." -ForegroundColor Cyan
Write-Host ""

# Build all services
docker-compose -f docker-compose.build.yml build --progress=plain

Write-Host ""
Write-Host "✅ Build complete!" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Starting services..." -ForegroundColor Cyan
Write-Host ""

# Start services
docker-compose -f docker-compose.build.yml up -d

Write-Host ""
Write-Host "⏳ Waiting for services to be healthy..." -ForegroundColor Cyan
Write-Host ""

# Wait for database to be ready
$maxRetries = 30
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    $dbReady = docker-compose -f docker-compose.build.yml exec -T db pg_isready -U matthew50 2>$null
    if ($LASTEXITCODE -eq 0) {
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

Write-Host "✅ Database ready" -ForegroundColor Green
Write-Host ""

# Run migrations
Write-Host "🔄 Running database migrations..." -ForegroundColor Cyan
docker-compose -f docker-compose.build.yml --profile migrate up

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "✅ Deployment Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Access points:" -ForegroundColor Cyan
Write-Host "  • Web App:       http://localhost:8000"
Write-Host "  • API Docs:      http://localhost:8000/docs"
Write-Host "  • Streamlit:     http://localhost:8501"
Write-Host "  • PostgreSQL:    localhost:5432"
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  • View logs:     docker-compose -f docker-compose.build.yml logs -f api"
Write-Host "  • Stop all:      docker-compose -f docker-compose.build.yml down"
Write-Host "  • Rebuild:       docker-compose -f docker-compose.build.yml up -d --build"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Check health: curl http://localhost:8000/api/health"
Write-Host "  2. Populate data: See client/README.md 'Data Population Pipeline'"
Write-Host ""
