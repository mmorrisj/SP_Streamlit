# How to Register Your Docker Images to Docker Hub

This guide explains the simple process of "registering" (pushing) your built Docker images to Docker Hub so users can pull and deploy them.

## What is "Registering" a Docker Image?

"Registering" an image means:
1. Building your Docker image locally
2. Tagging it with your Docker Hub username
3. Pushing it to Docker Hub (a public image registry)
4. Once pushed, anyone can pull and run your image with `docker pull yourusername/imagename`

Think of it like publishing a package to npm or PyPI - you're making your pre-built application available for others to download.

## Prerequisites

1. **Docker Hub Account** (free)
   - Sign up at https://hub.docker.com
   - Choose a username (this will be used in image names)

2. **Docker Desktop Installed**
   - Windows/Mac: https://www.docker.com/products/docker-desktop
   - Linux: Follow Docker CE installation guide

3. **Command Line Access**
   - Windows: PowerShell (Admin recommended)
   - Mac/Linux: Terminal

## Step-by-Step: Registering Your Images

### Step 1: Login to Docker Hub

Open your terminal/PowerShell and login:

```bash
docker login
```

Enter your Docker Hub username and password when prompted.

**Expected Output:**
```
Login Succeeded
```

### Step 2: Run the Build Script

We've created automated scripts to build and push your images.

**On Windows (PowerShell):**
```powershell
# Replace 'yourusername' with your actual Docker Hub username
.\build-and-push.ps1 -Username "yourusername" -Version "v1.0.0"
```

**On Linux/Mac:**
```bash
# Make script executable
chmod +x build-and-push.sh

# Replace 'yourusername' with your actual Docker Hub username
./build-and-push.sh yourusername v1.0.0
```

**What This Does:**
1. Logs you into Docker Hub (if not already logged in)
2. Sets up multi-architecture builds (AMD64 + ARM64)
3. Builds the API image (includes React frontend) - **~10-15 minutes**
4. Pushes to `yourusername/softpower-api:latest` and `yourusername/softpower-api:v1.0.0`
5. Builds the Dashboard image - **~5-8 minutes**
6. Pushes to `yourusername/softpower-dashboard:latest` and `yourusername/softpower-dashboard:v1.0.0`

**Expected Output:**
```
[1/4] Logging into Docker Hub...
Login Succeeded

[2/4] Setting up buildx for multi-architecture builds...
[+] Building 0.5s (1/1) FINISHED

[3/4] Building and pushing API service (with React frontend)...
[+] Building 847.3s (27/27) FINISHED
 => exporting to image
 => pushing yourusername/softpower-api:latest
 => pushing yourusername/softpower-api:v1.0.0

[4/4] Building and pushing Dashboard service...
[+] Building 423.1s (19/19) FINISHED
 => pushing yourusername/softpower-dashboard:latest
 => pushing yourusername/softpower-dashboard:v1.0.0

✅ Successfully pushed images to Docker Hub!
```

### Step 3: Verify on Docker Hub

1. Go to https://hub.docker.com
2. Login with your credentials
3. Click "Repositories" in the top menu
4. You should see:
   - `yourusername/softpower-api`
   - `yourusername/softpower-dashboard`

### Step 4: Update Production Config

Edit [docker-compose.production.yml](docker-compose.production.yml) and replace `yourusername` with your actual Docker Hub username:

```yaml
services:
  api:
    image: YOURUSERNAME/softpower-api:latest  # <-- Change this

  dashboard:
    image: YOURUSERNAME/softpower-dashboard:latest  # <-- Change this

  migrate:
    image: YOURUSERNAME/softpower-api:latest  # <-- Change this
```

**For example, if your Docker Hub username is `john123`:**
```yaml
services:
  api:
    image: john123/softpower-api:latest

  dashboard:
    image: john123/softpower-dashboard:latest

  migrate:
    image: john123/softpower-api:latest
```

### Step 5: Test the Deployment

On your local machine, test pulling and running from Docker Hub:

```bash
# Pull images
docker pull yourusername/softpower-api:latest
docker pull yourusername/softpower-dashboard:latest

# Start services
docker-compose -f docker-compose.production.yml up -d

# Run migrations
docker-compose -f docker-compose.production.yml run --rm migrate

# Check status
docker-compose -f docker-compose.production.yml ps
```

**Expected Output:**
```
NAME                         STATUS              PORTS
softpower_api_prod           running             0.0.0.0:8000->8000/tcp
softpower_dashboard_prod     running             0.0.0.0:8501->8501/tcp
softpower_db_prod            running             0.0.0.0:5432->5432/tcp
```

Visit http://localhost:8000 to see the React app and http://localhost:8501 for the Streamlit dashboard.

## Updating Your Images

When you make changes to your code, rebuild and push new versions:

```powershell
# Windows
.\build-and-push.ps1 -Username "yourusername" -Version "v1.0.1"
```

```bash
# Linux/Mac
./build-and-push.sh yourusername v1.0.1
```

This creates new tagged versions while keeping `latest` updated. Users can:
- Pull `latest` for newest version: `docker pull yourusername/softpower-api:latest`
- Pull specific version for stability: `docker pull yourusername/softpower-api:v1.0.0`

## Manual Build (Advanced)

If you prefer manual control instead of using the scripts:

```bash
# 1. Login
docker login

# 2. Enable buildx
docker buildx create --name softpower-builder --driver docker-container --use
docker buildx inspect --bootstrap

# 3. Build and push API
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/api-production.Dockerfile \
  -t yourusername/softpower-api:latest \
  -t yourusername/softpower-api:v1.0.0 \
  --push \
  .

# 4. Build and push Dashboard
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/dashboard.Dockerfile \
  -t yourusername/softpower-dashboard:latest \
  -t yourusername/softpower-dashboard:v1.0.0 \
  --push \
  .
```

## For End Users: Deploying from Docker Hub

Once you've registered your images, share the following with your users:

1. **Download deployment files:**
   ```bash
   curl -O https://raw.githubusercontent.com/yourusername/SP_Streamlit/main/docker-compose.production.yml
   curl -O https://raw.githubusercontent.com/yourusername/SP_Streamlit/main/.env.example
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   nano .env  # Edit with real credentials
   ```

3. **Deploy:**
   ```bash
   docker-compose -f docker-compose.production.yml up -d
   docker-compose -f docker-compose.production.yml run --rm migrate
   ```

That's it! No source code, no build process - just pull and run.

## Troubleshooting

### "unauthorized: authentication required"

You're not logged into Docker Hub. Run:
```bash
docker login
```

### "denied: requested access to the resource is denied"

Your repository is set to private. Either:
1. Make it public in Docker Hub repository settings
2. Users need to login and be granted access

### Build fails with "failed to solve"

1. Check you're in the project root directory
2. Verify docker/api-production.Dockerfile and docker/dashboard.Dockerfile exist
3. Ensure client/ and all source directories exist

### Push is very slow

Multi-architecture builds take longer. First push is slowest (uploads all layers). Subsequent pushes only upload changed layers.

To push single architecture (faster for testing):
```bash
docker build -f docker/api-production.Dockerfile -t yourusername/softpower-api:latest .
docker push yourusername/softpower-api:latest
```

## Image Sizes

Expected sizes after optimization:
- `softpower-api`: ~600-800 MB (includes Python, Node build artifacts, React build)
- `softpower-dashboard`: ~400-600 MB (includes Python, Streamlit)

Multi-architecture manifests show combined size. Each architecture is downloaded separately when pulled.

## Private vs Public Images

**Public (Default):**
- Anyone can pull without authentication
- Free on Docker Hub
- Good for open source projects

**Private:**
- Requires Docker Hub Pro ($5/month for 5 private repos)
- Users must login and be granted access
- Good for proprietary applications

## Next Steps

After successfully registering your images:

1. ✅ Update docker-compose.production.yml with your username
2. ✅ Test deployment locally
3. ✅ Share deployment files with users
4. ✅ Create GitHub releases with version tags
5. ✅ Document deployment in README.md

See [DOCKER_HUB_DEPLOYMENT.md](DOCKER_HUB_DEPLOYMENT.md) for complete production deployment guide.
