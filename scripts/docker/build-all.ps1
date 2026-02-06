# ============================================
# Build All Docker Images Separately (PowerShell)
# For systems with Docker but no Docker Compose
# ============================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "Building All Docker Images (Standalone Mode)" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""

# Create network if it doesn't exist
Write-Host "📡 Creating Docker network..." -ForegroundColor Cyan
try {
    docker network create softpower_net 2>$null
} catch {
    Write-Host "Network already exists"
}
Write-Host ""

# Create volumes if they don't exist
Write-Host "💾 Creating Docker volumes..." -ForegroundColor Cyan
try { docker volume create postgres_data 2>$null } catch { Write-Host "postgres_data already exists" }
try { docker volume create pgadmin_data 2>$null } catch { Write-Host "pgadmin_data already exists" }
try { docker volume create redis_data 2>$null } catch { Write-Host "redis_data already exists" }
Write-Host ""

# Build each service
Write-Host "🔨 Building images..." -ForegroundColor Cyan
Write-Host ""

Write-Host "1/3 Building React Web App + FastAPI..." -ForegroundColor Yellow
docker build -f docker/api-production.Dockerfile -t softpower-api:latest .
Write-Host "✅ API image built" -ForegroundColor Green
Write-Host ""

Write-Host "2/3 Building Streamlit Dashboard..." -ForegroundColor Yellow
docker build -f docker/dashboard.Dockerfile -t softpower-dashboard:latest .
Write-Host "✅ Dashboard image built" -ForegroundColor Green
Write-Host ""

Write-Host "3/3 Building Pipeline Worker..." -ForegroundColor Yellow
docker build -f docker/pipeline.Dockerfile -t softpower-pipeline:latest .
Write-Host "✅ Pipeline image built" -ForegroundColor Green
Write-Host ""

Write-Host "==============================================" -ForegroundColor Green
Write-Host "✅ All Images Built Successfully!" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Images created:"
Write-Host "  • softpower-api:latest"
Write-Host "  • softpower-dashboard:latest"
Write-Host "  • softpower-pipeline:latest"
Write-Host ""
Write-Host "External images to be pulled:"
Write-Host "  • ankane/pgvector:latest (PostgreSQL)"
Write-Host "  • redis:7-alpine"
Write-Host "  • dpage/pgadmin4:latest (optional)"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  .\docker\run-all.ps1         # Start all services"
Write-Host "  .\docker\run-database.ps1    # Start only database"
Write-Host "  .\docker\run-webapp.ps1      # Start only web app"
Write-Host ""
