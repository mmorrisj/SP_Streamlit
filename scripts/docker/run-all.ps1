# ============================================
# Run All Services (Standalone Docker - PowerShell)
# No Docker Compose Required
# ============================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "Soft Power Analytics - Full Deployment" -ForegroundColor Green
Write-Host "Standalone Docker Mode" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""

# Get script directory and project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

# Check if .env exists
if (-not (Test-Path .env)) {
    Write-Host "⚠️  Warning: .env file not found" -ForegroundColor Yellow
    if (Test-Path .env.example) {
        Copy-Item .env.example .env
        Write-Host "✅ Created .env from template" -ForegroundColor Green
        Write-Host ""
        Write-Host "⚠️  IMPORTANT: Edit .env with your credentials" -ForegroundColor Yellow
        Read-Host "Press Enter after editing .env, or Ctrl+C to cancel"
    } else {
        Write-Host "❌ Error: .env.example not found" -ForegroundColor Red
        exit 1
    }
}

# Load environment variables from .env
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        Set-Item -Path "env:$name" -Value $value
    }
}

$ApiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
$POSTGRES_USER = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "matthew50" }
$POSTGRES_PASSWORD = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "softpower" }
$POSTGRES_DB = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "softpower-db" }

Write-Host "Step 1/6: Building Docker images..." -ForegroundColor Cyan
Write-Host ""
& "$ScriptDir\build-all.ps1"

Write-Host ""
Write-Host "Step 2/6: Starting database services..." -ForegroundColor Cyan
Write-Host ""

# Create network and volumes
docker network create softpower_net 2>$null
docker volume create postgres_data 2>$null
docker volume create redis_data 2>$null

# Start PostgreSQL
Write-Host "🐘 Starting PostgreSQL + pgvector..." -ForegroundColor Yellow
docker run -d `
    --name softpower_db `
    --network softpower_net `
    --restart unless-stopped `
    -e POSTGRES_USER=$POSTGRES_USER `
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
    -e POSTGRES_DB=$POSTGRES_DB `
    -e PGDATA=/var/lib/postgresql/data/pgdata `
    -v postgres_data:/var/lib/postgresql/data `
    -p 5432:5432 `
    --shm-size=2gb `
    ankane/pgvector:latest

# Start Redis
Write-Host "📦 Starting Redis..." -ForegroundColor Yellow
docker run -d `
    --name softpower_redis `
    --network softpower_net `
    --restart unless-stopped `
    -v redis_data:/data `
    -p 6379:6379 `
    redis:7-alpine `
    redis-server --appendonly yes --maxmemory 1gb --maxmemory-policy allkeys-lru

Write-Host ""
Write-Host "Step 3/6: Running database migrations..." -ForegroundColor Cyan
Write-Host ""

# Wait for database
Write-Host "⏳ Waiting for database..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Run migrations
Write-Host "🔄 Running Alembic migrations..." -ForegroundColor Yellow
docker run --rm `
    --network softpower_net `
    -e DB_HOST=softpower_db `
    -e POSTGRES_USER=$POSTGRES_USER `
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
    -e POSTGRES_DB=$POSTGRES_DB `
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB}" `
    -v "${PWD}/shared:/app/shared" `
    -v "${PWD}/alembic:/app/alembic" `
    -v "${PWD}/alembic.ini:/app/alembic.ini" `
    softpower-api:latest `
    alembic upgrade head

Write-Host "✅ Migrations complete" -ForegroundColor Green
Write-Host ""

Write-Host "Step 4/6: Starting web application..." -ForegroundColor Cyan
Write-Host ""

docker run -d `
    --name softpower_api `
    --network softpower_net `
    --restart unless-stopped `
    -e DOCKER_ENV=true `
    -e NODE_ENV=production `
    -e DB_HOST=softpower_db `
    -e POSTGRES_USER=$POSTGRES_USER `
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
    -e POSTGRES_DB=$POSTGRES_DB `
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB}" `
    -e REDIS_URL=redis://softpower_redis:6379 `
    -e CLAUDE_KEY=$env:CLAUDE_KEY `
    -v "${PWD}/shared/config/config.yaml:/app/shared/config/config.yaml:ro" `
    -v "${PWD}/_data:/app/_data" `
    -p ${ApiPort}:8000 `
    softpower-api:latest

Write-Host "✅ Web app started" -ForegroundColor Green
Write-Host ""

Write-Host "Step 5/6: Starting Streamlit dashboard..." -ForegroundColor Cyan
Write-Host ""

docker run -d `
    --name softpower_dashboard `
    --network softpower_net `
    --restart unless-stopped `
    -e DOCKER_ENV=true `
    -e DB_HOST=softpower_db `
    -e POSTGRES_USER=$POSTGRES_USER `
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
    -e POSTGRES_DB=$POSTGRES_DB `
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB}" `
    -e API_URL=http://softpower_api:8000 `
    -v "${PWD}/services/dashboard:/app/services/dashboard:ro" `
    -v "${PWD}/shared:/app/shared:ro" `
    -p 8501:8501 `
    softpower-dashboard:latest

Write-Host "✅ Streamlit started" -ForegroundColor Green
Write-Host ""

Write-Host "Step 6/6: Starting pipeline worker..." -ForegroundColor Cyan
Write-Host ""

docker run -d `
    --name softpower_pipeline `
    --network softpower_net `
    --restart unless-stopped `
    -e DOCKER_ENV=true `
    -e DB_HOST=softpower_db `
    -e POSTGRES_USER=$POSTGRES_USER `
    -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
    -e POSTGRES_DB=$POSTGRES_DB `
    -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@softpower_db:5432/${POSTGRES_DB}" `
    -e CLAUDE_KEY=$env:CLAUDE_KEY `
    -v "${PWD}/services/pipeline:/app/services/pipeline" `
    -v "${PWD}/shared:/app/shared" `
    -v "${PWD}/_data:/app/_data" `
    softpower-pipeline:latest `
    tail -f /dev/null

Write-Host "✅ Pipeline worker started" -ForegroundColor Green
Write-Host ""

Write-Host "==============================================" -ForegroundColor Green
Write-Host "✅ Full Stack Deployed Successfully!" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""
Write-Host "🌐 Access Points:" -ForegroundColor Cyan
Write-Host "  • React Web App:    http://localhost:$ApiPort"
Write-Host "  • API Docs:         http://localhost:$ApiPort/docs"
Write-Host "  • Streamlit:        http://localhost:8501"
Write-Host "  • PostgreSQL:       localhost:5432"
Write-Host "  • Redis:            localhost:6379"
Write-Host ""
Write-Host "⚙️  Pipeline Commands:" -ForegroundColor Cyan
Write-Host "  docker exec softpower_pipeline python services/pipeline/ingestion/dsr.py"
Write-Host "  docker exec softpower_pipeline python services/pipeline/analysis/atom_extraction.py"
Write-Host ""
Write-Host "📊 View Logs:" -ForegroundColor Cyan
Write-Host "  docker logs -f softpower_api"
Write-Host "  docker logs -f softpower_dashboard"
Write-Host "  docker logs -f softpower_pipeline"
Write-Host ""
Write-Host "🛑 Stop All Services:" -ForegroundColor Yellow
Write-Host "  .\docker\stop-all.ps1"
Write-Host ""
