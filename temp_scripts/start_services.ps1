# Non-Docker Service Startup Script for SoftPower Analytics (Windows)
# Usage: .\start_services.ps1 [-Service api|dashboard|client|all|prod] [-Stop]

param(
    [Parameter(Position=0)]
    [ValidateSet("api", "dashboard", "client", "all", "prod")]
    [string]$Service = "all",

    [switch]$Stop
)

# Project root
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "SoftPower Analytics - Service Manager" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

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
    Write-Host "[✗] .env file not found!" -ForegroundColor Red
    exit 1
}

# Function to stop services
function Stop-Services {
    Write-Host "[→] Stopping services..." -ForegroundColor Yellow

    # Stop FastAPI (uvicorn)
    $uvicorn = Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue
    if ($uvicorn) {
        Stop-Process -Name "uvicorn" -Force
        Write-Host "[✓] FastAPI stopped" -ForegroundColor Green
    }

    # Stop Streamlit
    $streamlit = Get-Process -Name "streamlit" -ErrorAction SilentlyContinue
    if ($streamlit) {
        Stop-Process -Name "streamlit" -Force
        Write-Host "[✓] Streamlit stopped" -ForegroundColor Green
    }

    # Stop Node/Vite (React dev server)
    $node = Get-Process | Where-Object { $_.ProcessName -eq "node" -and $_.CommandLine -like "*vite*" } -ErrorAction SilentlyContinue
    if ($node) {
        Stop-Process -Id $node.Id -Force
        Write-Host "[✓] React dev server stopped" -ForegroundColor Green
    }

    # Clean up PID files
    Remove-Item -Path ".api.pid", ".dashboard.pid", ".client.pid" -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "All services stopped." -ForegroundColor Green
}

# Handle stop flag
if ($Stop) {
    Stop-Services
    exit 0
}

# Check if virtual environment exists
if (-not (Test-Path "venv")) {
    Write-Host "[!] Virtual environment not found. Creating..." -ForegroundColor Yellow
    python -m venv venv
    & "venv\Scripts\Activate.ps1"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    Write-Host "[✓] Virtual environment created and dependencies installed" -ForegroundColor Green
} else {
    & "venv\Scripts\Activate.ps1"
    Write-Host "[✓] Activated virtual environment" -ForegroundColor Green
}

# Check database connection
Write-Host "[→] Checking database connection..." -ForegroundColor Blue
$dbCheck = python -c "from shared.database.database import health_check; import sys; sys.exit(0 if health_check() else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[✓] Database connection successful" -ForegroundColor Green
} else {
    Write-Host "[✗] Database connection failed!" -ForegroundColor Red
    Write-Host "[→] Make sure PostgreSQL is running and configured correctly" -ForegroundColor Yellow
    exit 1
}

# Get port configuration from environment
$ApiPort = if ($env:API_PORT) { $env:API_PORT } else { "5001" }
$ApiHost = if ($env:API_HOST) { $env:API_HOST } else { "0.0.0.0" }
$StreamlitPort = if ($env:STREAMLIT_PORT) { $env:STREAMLIT_PORT } else { "8501" }
$StreamlitHost = if ($env:STREAMLIT_HOST) { $env:STREAMLIT_HOST } else { "0.0.0.0" }

# Function to start FastAPI service
function Start-API {
    Write-Host "[→] Starting FastAPI service on port $ApiPort..." -ForegroundColor Blue
    $apiPath = Join-Path $ProjectRoot "services\api"

    # Start in new window
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "cd '$apiPath'; & '$ProjectRoot\venv\Scripts\Activate.ps1'; uvicorn main:app --host $ApiHost --port $ApiPort --reload" `
        -WindowStyle Normal

    Start-Sleep -Seconds 2
    Write-Host "[✓] FastAPI started on http://localhost:$ApiPort" -ForegroundColor Green
}

# Function to start Streamlit dashboard
function Start-Dashboard {
    Write-Host "[→] Starting Streamlit dashboard on port $StreamlitPort..." -ForegroundColor Blue
    $dashboardPath = Join-Path $ProjectRoot "services\dashboard"

    # Start in new window
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "cd '$dashboardPath'; & '$ProjectRoot\venv\Scripts\Activate.ps1'; streamlit run app.py --server.port $StreamlitPort --server.address $StreamlitHost" `
        -WindowStyle Normal

    Start-Sleep -Seconds 2
    Write-Host "[✓] Streamlit started on http://localhost:$StreamlitPort" -ForegroundColor Green
}

# Function to start React Vite dev server
function Start-Client {
    Write-Host "[→] Starting React Vite dev server on port 5000..." -ForegroundColor Blue
    $clientPath = Join-Path $ProjectRoot "client"

    # Start in new window
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "cd '$clientPath'; npm run dev" `
        -WindowStyle Normal

    Start-Sleep -Seconds 3
    Write-Host "[✓] React dev server started on http://localhost:5000" -ForegroundColor Green
}

# Function to build React for production
function Build-Client {
    Write-Host "[→] Building React app for production..." -ForegroundColor Blue
    $clientPath = Join-Path $ProjectRoot "client"

    Push-Location $clientPath
    npm run build
    Pop-Location

    Write-Host "[✓] React app built successfully to client\dist\" -ForegroundColor Green
}

# Function to start production FastAPI (serves React + API)
function Start-Prod {
    Write-Host "[→] Starting FastAPI in production mode (port 8000)..." -ForegroundColor Blue

    # Start in new window
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "cd '$ProjectRoot'; & '$ProjectRoot\venv\Scripts\Activate.ps1'; uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload" `
        -WindowStyle Normal

    Start-Sleep -Seconds 2
    Write-Host "[✓] FastAPI production server started on http://localhost:8000" -ForegroundColor Green
}

# Start requested services
switch ($Service) {
    "api" {
        Start-API
    }
    "dashboard" {
        Start-Dashboard
    }
    "client" {
        Start-Client
    }
    "all" {
        # Development mode: API + React dev server + Streamlit
        Start-API
        Start-Sleep -Seconds 3
        Start-Client
        Start-Sleep -Seconds 3
        Start-Dashboard
    }
    "prod" {
        # Production mode: Build React, then serve via FastAPI + Streamlit
        Build-Client
        Start-Prod
        Start-Sleep -Seconds 3
        Start-Dashboard
    }
}

# Display access URLs
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Services Started Successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

switch ($Service) {
    "prod" {
        Write-Host "React App:  http://localhost:8000 (production build)" -ForegroundColor Cyan
        Write-Host "API:        http://localhost:8000/api/* (same server)" -ForegroundColor Cyan
        Write-Host "Dashboard:  http://localhost:$StreamlitPort" -ForegroundColor Cyan
    }
    "all" {
        Write-Host "React App:  http://localhost:5000 (dev server with hot reload)" -ForegroundColor Cyan
        Write-Host "API:        http://localhost:$ApiPort" -ForegroundColor Cyan
        Write-Host "Dashboard:  http://localhost:$StreamlitPort" -ForegroundColor Cyan
    }
    "api" {
        Write-Host "API:        http://localhost:$ApiPort" -ForegroundColor Cyan
    }
    "dashboard" {
        Write-Host "Dashboard:  http://localhost:$StreamlitPort" -ForegroundColor Cyan
    }
    "client" {
        Write-Host "React App:  http://localhost:5000 (dev server)" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "To stop services, run: .\start_services.ps1 -Stop" -ForegroundColor Yellow
Write-Host ""
