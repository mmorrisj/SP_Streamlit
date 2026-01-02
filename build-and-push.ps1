# Build and Push SoftPower Analytics Images to Docker Hub
# Usage: .\build-and-push.ps1 -Username "your-dockerhub-username" -Version "v1.0.0"

param(
    [Parameter(Mandatory=$true)]
    [string]$Username,

    [Parameter(Mandatory=$false)]
    [string]$Version = "latest"
)

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Building and Pushing SoftPower Images" -ForegroundColor Green
Write-Host "Docker Hub Username: $Username" -ForegroundColor Cyan
Write-Host "Version: $Version" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""

# Step 1: Login to Docker Hub
Write-Host "[1/4] Logging into Docker Hub..." -ForegroundColor Blue
docker login
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Docker login failed!" -ForegroundColor Red
    exit 1
}

# Step 2: Create buildx builder (for multi-architecture support)
Write-Host ""
Write-Host "[2/4] Setting up buildx for multi-architecture builds..." -ForegroundColor Blue
docker buildx create --name softpower-builder --driver docker-container --use 2>$null
if ($LASTEXITCODE -ne 0) {
    docker buildx use softpower-builder
}
docker buildx inspect --bootstrap

# Step 3: Build and push API service (includes React frontend)
Write-Host ""
Write-Host "[3/4] Building and pushing API service (with React frontend)..." -ForegroundColor Blue
Write-Host "  This may take 10-15 minutes for multi-architecture build..." -ForegroundColor Yellow

docker buildx build `
  --platform linux/amd64,linux/arm64 `
  -f docker/api-production.Dockerfile `
  -t "$Username/softpower-api:latest" `
  -t "$Username/softpower-api:$Version" `
  --push `
  .

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ API build failed!" -ForegroundColor Red
    exit 1
}

# Step 4: Build and push Dashboard service
Write-Host ""
Write-Host "[4/4] Building and pushing Dashboard service..." -ForegroundColor Blue

docker buildx build `
  --platform linux/amd64,linux/arm64 `
  -f docker/dashboard.Dockerfile `
  -t "$Username/softpower-dashboard:latest" `
  -t "$Username/softpower-dashboard:$Version" `
  --push `
  .

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Dashboard build failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "✅ Successfully pushed images to Docker Hub!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Images pushed:" -ForegroundColor Cyan
Write-Host "  - $Username/softpower-api:latest"
Write-Host "  - $Username/softpower-api:$Version"
Write-Host "  - $Username/softpower-dashboard:latest"
Write-Host "  - $Username/softpower-dashboard:$Version"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Update docker-compose.production.yml with your username"
Write-Host "  2. Share docker-compose.production.yml with users"
Write-Host "  3. Users can deploy with: docker-compose -f docker-compose.production.yml up -d"
Write-Host ""
