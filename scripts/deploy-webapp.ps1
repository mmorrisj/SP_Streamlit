# ============================================
# Deploy Web App to Existing Database (PowerShell)
# No database setup needed - connects to existing
# ============================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Web App Deployment (Existing Database)" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# Check if existing database container is running
$dbRunning = docker ps --format '{{.Names}}' | Select-String -Pattern '^softpower_db$'

if (-not $dbRunning) {
    Write-Host "❌ Error: PostgreSQL container 'softpower_db' is not running" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please start your database first:"
    Write-Host "  docker start softpower_db"
    Write-Host ""
    exit 1
}

Write-Host "✅ Found existing database: softpower_db" -ForegroundColor Green
Write-Host ""

# Check if database has data
try {
    $docCount = docker exec softpower_db psql -U matthew50 -d softpower-db -t -c "SELECT COUNT(*) FROM documents;" 2>$null
    $docCount = $docCount.Trim()
    Write-Host "✅ Database contains $docCount documents" -ForegroundColor Green
    Write-Host ""
} catch {
    Write-Host "⚠️  Warning: Could not query documents table" -ForegroundColor Yellow
    Write-Host "   Database may be empty or credentials incorrect"
    Write-Host ""
}

# Check if network exists
$networkExists = docker network ls --format '{{.Name}}' | Select-String -Pattern '^softpower_net$'

if (-not $networkExists) {
    Write-Host "⚠️  Network 'softpower_net' not found, creating..." -ForegroundColor Yellow
    docker network create softpower_net
    Write-Host "✅ Network created" -ForegroundColor Green
    Write-Host ""
}

Write-Host "📦 Building web app Docker image..." -ForegroundColor Cyan
Write-Host "   (This builds React inside Docker - may take 8-12 minutes)"
Write-Host ""

# Build web app image
docker-compose -f docker-compose.webapp.yml build --progress=plain

Write-Host ""
Write-Host "✅ Build complete!" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Starting web app..." -ForegroundColor Cyan
Write-Host ""

# Start web app (connects to existing database)
docker-compose -f docker-compose.webapp.yml up -d

Write-Host ""
Write-Host "⏳ Waiting for API to be healthy..." -ForegroundColor Cyan
Write-Host ""

# Wait for API health check
$maxRetries = 30
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 2 2>$null
        if ($response.StatusCode -eq 200) {
            Write-Host "✅ API is healthy" -ForegroundColor Green
            break
        }
    } catch {
        # API not ready yet
    }
    Write-Host "   Waiting for API..." -ForegroundColor Gray
    Start-Sleep -Seconds 2
    $retryCount++
}

if ($retryCount -eq $maxRetries) {
    Write-Host "❌ API failed to start" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check logs:"
    Write-Host "  docker-compose -f docker-compose.webapp.yml logs api"
    exit 1
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "✅ Web App Deployed Successfully!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Access points:" -ForegroundColor Cyan
Write-Host "  • Web App:       http://localhost:8000"
Write-Host "  • API Docs:      http://localhost:8000/docs"
Write-Host "  • API Health:    http://localhost:8000/api/health"
Write-Host ""
Write-Host "Database:" -ForegroundColor Cyan
Write-Host "  • Container:     softpower_db (existing)"
if ($docCount) {
    Write-Host "  • Documents:     $docCount"
}
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  • View logs:     docker-compose -f docker-compose.webapp.yml logs -f api"
Write-Host "  • Stop web app:  docker-compose -f docker-compose.webapp.yml down"
Write-Host "  • Rebuild:       docker-compose -f docker-compose.webapp.yml up -d --build"
Write-Host ""
Write-Host "Optional: Start Streamlit dashboard:" -ForegroundColor Yellow
Write-Host "  docker-compose -f docker-compose.webapp.yml --profile dashboard up -d"
Write-Host ""
