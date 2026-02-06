# Deploy SoftPower Analytics using pure Docker (no docker-compose required)
# Usage: .\deploy-docker-only.ps1 -Command [start|stop|restart|logs|status|migrate]

param(
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "restart", "migrate", "logs", "status")]
    [string]$Command = "start",

    [Parameter(Position=1)]
    [string]$Container = "softpower_api_prod"
)

# Load environment variables from .env
if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^([^#].+?)=(.+)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim("'", '"')
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    Write-Host "[✓] Loaded environment variables from .env" -ForegroundColor Green
} else {
    if ($Command -eq "start") {
        Write-Host "[✗] .env file not found!" -ForegroundColor Red
        Write-Host "[→] Please create .env file with your configuration" -ForegroundColor Yellow
        Write-Host "[→] See .env.example for template" -ForegroundColor Yellow
        exit 1
    }
}

# Configuration
$POSTGRES_USER = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "matthew50" }
$POSTGRES_PASSWORD = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "softpower" }
$POSTGRES_DB = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "softpower-db" }
$DB_PORT = if ($env:DB_PORT) { $env:DB_PORT } else { "5432" }
$API_PORT = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
$STREAMLIT_PORT = if ($env:STREAMLIT_PORT) { $env:STREAMLIT_PORT } else { "8501" }

# Docker image names (replace 'yourusername' with your Docker Hub username)
$DOCKER_USERNAME = if ($env:DOCKER_USERNAME) { $env:DOCKER_USERNAME } else { "yourusername" }
$API_IMAGE = "$DOCKER_USERNAME/softpower-api:latest"
$DASHBOARD_IMAGE = "$DOCKER_USERNAME/softpower-dashboard:latest"

# Container names
$DB_CONTAINER = "softpower_db_prod"
$REDIS_CONTAINER = "softpower_redis_prod"
$API_CONTAINER = "softpower_api_prod"
$DASHBOARD_CONTAINER = "softpower_dashboard_prod"

# Network and volume names
$NETWORK_NAME = "softpower_net_prod"
$DB_VOLUME = "postgres_data_prod"

# Function to create network
function Create-Network {
    $networkExists = docker network inspect $NETWORK_NAME 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[→] Creating Docker network: $NETWORK_NAME" -ForegroundColor Blue
        docker network create $NETWORK_NAME
        Write-Host "[✓] Network created" -ForegroundColor Green
    } else {
        Write-Host "[✓] Network $NETWORK_NAME already exists" -ForegroundColor Green
    }
}

# Function to create volume
function Create-Volume {
    $volumeExists = docker volume inspect $DB_VOLUME 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[→] Creating Docker volume: $DB_VOLUME" -ForegroundColor Blue
        docker volume create $DB_VOLUME
        Write-Host "[✓] Volume created" -ForegroundColor Green
    } else {
        Write-Host "[✓] Volume $DB_VOLUME already exists" -ForegroundColor Green
    }
}

# Function to start PostgreSQL
function Start-Database {
    Write-Host "[→] Starting PostgreSQL with pgvector..." -ForegroundColor Blue

    docker run -d `
        --name $DB_CONTAINER `
        --network $NETWORK_NAME `
        -e POSTGRES_USER=$POSTGRES_USER `
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
        -e POSTGRES_DB=$POSTGRES_DB `
        -p "${DB_PORT}:5432" `
        -v "${DB_VOLUME}:/var/lib/postgresql/data" `
        --restart unless-stopped `
        ankane/pgvector:latest

    Write-Host "[✓] PostgreSQL started (container: $DB_CONTAINER)" -ForegroundColor Green
    Write-Host "   Waiting for database to be ready..." -ForegroundColor Yellow

    # Wait for PostgreSQL to be ready
    for ($i = 1; $i -le 30; $i++) {
        $ready = docker exec $DB_CONTAINER pg_isready -U $POSTGRES_USER 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[✓] Database is ready" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 1
    }
}

# Function to start Redis
function Start-RedisCache {
    Write-Host "[→] Starting Redis..." -ForegroundColor Blue

    docker run -d `
        --name $REDIS_CONTAINER `
        --network $NETWORK_NAME `
        --restart unless-stopped `
        redis:7-alpine

    Write-Host "[✓] Redis started (container: $REDIS_CONTAINER)" -ForegroundColor Green
}

# Function to start API service
function Start-ApiService {
    Write-Host "[→] Starting API service..." -ForegroundColor Blue
    Write-Host "   Pulling image: $API_IMAGE" -ForegroundColor Cyan
    docker pull $API_IMAGE

    docker run -d `
        --name $API_CONTAINER `
        --network $NETWORK_NAME `
        -p "${API_PORT}:8000" `
        -e DOCKER_ENV=true `
        -e DB_HOST=$DB_CONTAINER `
        -e DB_PORT=5432 `
        -e POSTGRES_USER=$POSTGRES_USER `
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
        -e POSTGRES_DB=$POSTGRES_DB `
        -e DB_POOL_SIZE=$env:DB_POOL_SIZE `
        -e DB_MAX_OVERFLOW=$env:DB_MAX_OVERFLOW `
        -e DB_POOL_TIMEOUT=$env:DB_POOL_TIMEOUT `
        -e DB_POOL_RECYCLE=$env:DB_POOL_RECYCLE `
        -e REDIS_URL="redis://${REDIS_CONTAINER}:6379" `
        -e CLAUDE_KEY=$env:CLAUDE_KEY `
        -e OPENAI_PROJ_API=$env:OPENAI_PROJ_API `
        -e AWS_ACCESS_KEY_ID=$env:AWS_ACCESS_KEY_ID `
        -e AWS_SECRET_ACCESS_KEY=$env:AWS_SECRET_ACCESS_KEY `
        -e AWS_DEFAULT_REGION=$env:AWS_DEFAULT_REGION `
        -e API_URL=$env:API_URL `
        -e FASTAPI_URL="http://${API_CONTAINER}:8000/material_query" `
        --restart unless-stopped `
        $API_IMAGE

    Write-Host "[✓] API service started (container: $API_CONTAINER)" -ForegroundColor Green
}

# Function to start Dashboard service
function Start-DashboardService {
    Write-Host "[→] Starting Streamlit Dashboard..." -ForegroundColor Blue
    Write-Host "   Pulling image: $DASHBOARD_IMAGE" -ForegroundColor Cyan
    docker pull $DASHBOARD_IMAGE

    docker run -d `
        --name $DASHBOARD_CONTAINER `
        --network $NETWORK_NAME `
        -p "${STREAMLIT_PORT}:8501" `
        -e DOCKER_ENV=true `
        -e DB_HOST=$DB_CONTAINER `
        -e DB_PORT=5432 `
        -e POSTGRES_USER=$POSTGRES_USER `
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
        -e POSTGRES_DB=$POSTGRES_DB `
        -e DB_POOL_SIZE=$env:DB_POOL_SIZE `
        -e DB_MAX_OVERFLOW=$env:DB_MAX_OVERFLOW `
        -e DB_POOL_TIMEOUT=$env:DB_POOL_TIMEOUT `
        -e DB_POOL_RECYCLE=$env:DB_POOL_RECYCLE `
        -e API_URL="http://${API_CONTAINER}:8000" `
        -e FASTAPI_URL="http://${API_CONTAINER}:8000/material_query" `
        --restart unless-stopped `
        $DASHBOARD_IMAGE

    Write-Host "[✓] Dashboard started (container: $DASHBOARD_CONTAINER)" -ForegroundColor Green
}

# Function to run migrations
function Run-Migrations {
    Write-Host "[→] Running database migrations..." -ForegroundColor Blue

    docker run --rm `
        --network $NETWORK_NAME `
        -e DOCKER_ENV=true `
        -e DB_HOST=$DB_CONTAINER `
        -e DB_PORT=5432 `
        -e POSTGRES_USER=$POSTGRES_USER `
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD `
        -e POSTGRES_DB=$POSTGRES_DB `
        $API_IMAGE `
        alembic upgrade head

    Write-Host "[✓] Migrations completed" -ForegroundColor Green
}

# Function to stop all containers
function Stop-AllContainers {
    Write-Host "[→] Stopping all containers..." -ForegroundColor Yellow

    $containers = @($DASHBOARD_CONTAINER, $API_CONTAINER, $REDIS_CONTAINER, $DB_CONTAINER)
    foreach ($container in $containers) {
        $exists = docker ps -a -q -f name=$container
        if ($exists) {
            docker stop $container 2>$null
            docker rm $container 2>$null
            Write-Host "[✓] Stopped and removed: $container" -ForegroundColor Green
        }
    }
}

# Function to show logs
function Show-Logs {
    param([string]$ContainerName)
    Write-Host "[→] Showing logs for: $ContainerName" -ForegroundColor Blue
    docker logs -f $ContainerName
}

# Function to show status
function Show-Status {
    Write-Host "[→] Container status:" -ForegroundColor Blue
    Write-Host ""
    docker ps -a --filter "name=softpower_" --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
    Write-Host ""
    Write-Host "[→] Network status:" -ForegroundColor Blue
    $networkInfo = docker network inspect $NETWORK_NAME 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Network $NETWORK_NAME exists" -ForegroundColor Green
    } else {
        Write-Host "Network not created" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "[→] Volume status:" -ForegroundColor Blue
    $volumeInfo = docker volume inspect $DB_VOLUME 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Volume $DB_VOLUME exists" -ForegroundColor Green
    } else {
        Write-Host "Volume not created" -ForegroundColor Yellow
    }
}

# Function to start all services
function Start-AllServices {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "SoftPower Analytics - Docker Deployment" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""

    # Create network and volume
    Create-Network
    Create-Volume

    # Start services in order
    Start-Database
    Start-Sleep -Seconds 3
    Start-RedisCache
    Start-Sleep -Seconds 2
    Start-ApiService
    Start-Sleep -Seconds 5
    Start-DashboardService

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "All Services Started!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "React App:  http://localhost:$API_PORT" -ForegroundColor Cyan
    Write-Host "API Docs:   http://localhost:$API_PORT/docs" -ForegroundColor Cyan
    Write-Host "Dashboard:  http://localhost:$STREAMLIT_PORT" -ForegroundColor Cyan
    Write-Host "Database:   localhost:$DB_PORT" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "First-time setup: Run migrations" -ForegroundColor Yellow
    Write-Host "  .\deploy-docker-only.ps1 -Command migrate" -ForegroundColor Yellow
    Write-Host ""
}

# Main command handler
switch ($Command) {
    "start" {
        Start-AllServices
    }
    "stop" {
        Stop-AllContainers
    }
    "restart" {
        Stop-AllContainers
        Start-Sleep -Seconds 2
        Start-AllServices
    }
    "migrate" {
        Run-Migrations
    }
    "logs" {
        Show-Logs -ContainerName $Container
    }
    "status" {
        Show-Status
    }
}
