# Docker Hub Deployment Guide

This guide explains how to build, push, and deploy the SoftPower Analytics project from Docker Hub for easy one-command deployment.

## Overview

Users can deploy the entire stack with a single command:
```bash
docker-compose -f docker-compose.production.yml up -d
```

## For Project Maintainers: Building and Pushing Images

### Prerequisites

1. Docker Hub account (create at https://hub.docker.com)
2. Docker installed locally
3. Docker CLI logged in:
   ```bash
   docker login
   # Enter your Docker Hub username and password
   ```

### Step 1: Build Production Images

We'll build multi-architecture images (AMD64 and ARM64) using Docker buildx:

```bash
# Enable buildx (one-time setup)
docker buildx create --name multiarch --driver docker-container --use
docker buildx inspect --bootstrap

# Build and push API service (with React frontend)
docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker/api-production.Dockerfile \
  -t yourusername/softpower-api:latest \
  -t yourusername/softpower-api:v1.0.0 \
  --push .

# Build and push Dashboard service
docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker/dashboard.Dockerfile \
  -t yourusername/softpower-dashboard:latest \
  -t yourusername/softpower-dashboard:v1.0.0 \
  --push .

# Note: PostgreSQL and Redis use official images, no custom build needed
```

**Replace `yourusername` with your Docker Hub username throughout this guide.**

### Step 2: Update docker-compose.production.yml

Edit `docker-compose.production.yml` and replace `yourusername` with your actual Docker Hub username:

```yaml
services:
  api:
    image: yourusername/softpower-api:latest

  dashboard:
    image: yourusername/softpower-dashboard:latest
```

### Step 3: Tag and Push Updates

When you make changes to the codebase:

```bash
# Increment version number
VERSION=v1.0.1

# Rebuild and push
docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker/api-production.Dockerfile \
  -t yourusername/softpower-api:latest \
  -t yourusername/softpower-api:$VERSION \
  --push .

docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker/dashboard.Dockerfile \
  -t yourusername/softpower-dashboard:latest \
  -t yourusername/softpower-dashboard:$VERSION \
  --push .
```

## For End Users: Deploying from Docker Hub

### Prerequisites

1. **Docker installed** on your system
2. **Docker Compose** installed (usually included with Docker Desktop)
3. **.env file** with your credentials

### Step 1: Clone Repository Configuration

You only need the configuration files, not the source code:

```bash
# Option A: Clone entire repo (includes source code)
git clone https://github.com/yourusername/SP_Streamlit.git
cd SP_Streamlit

# Option B: Download just the configuration files (minimal)
mkdir softpower-analytics
cd softpower-analytics
curl -O https://raw.githubusercontent.com/yourusername/SP_Streamlit/main/docker-compose.production.yml
curl -O https://raw.githubusercontent.com/yourusername/SP_Streamlit/main/.env.example
```

### Step 2: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
# Required variables:
#   POSTGRES_USER=matthew50
#   POSTGRES_PASSWORD=your-secure-password
#   POSTGRES_DB=softpower-db
#   CLAUDE_KEY=your-claude-api-key
#   OPENAI_PROJ_API=your-openai-api-key (if using OpenAI)
#   AWS_ACCESS_KEY_ID=your-aws-key (if using S3)
#   AWS_SECRET_ACCESS_KEY=your-aws-secret (if using S3)

nano .env  # or vim, code, notepad, etc.
```

### Step 3: Start Services

```bash
# Pull latest images and start all services
docker-compose -f docker-compose.production.yml up -d

# First-time setup: Run database migrations
docker-compose -f docker-compose.production.yml run --rm migrate

# View logs
docker-compose -f docker-compose.production.yml logs -f

# Check service status
docker-compose -f docker-compose.production.yml ps
```

### Step 4: Access the Application

- **React Web App**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Streamlit Dashboard**: http://localhost:8501
- **Database**: localhost:5432 (for direct access)

### Step 5: Running Pipeline Scripts

```bash
# Document ingestion
docker-compose -f docker-compose.production.yml exec api \
  python services/pipeline/ingestion/atom.py

# Event processing
docker-compose -f docker-compose.production.yml exec api \
  python services/pipeline/events/batch_cluster_events.py --country China

# View all available scripts
docker-compose -f docker-compose.production.yml exec api ls -la services/pipeline/
```

## Managing the Deployment

### Updating to Latest Version

```bash
# Pull latest images
docker-compose -f docker-compose.production.yml pull

# Restart services with new images
docker-compose -f docker-compose.production.yml up -d

# Run migrations if needed
docker-compose -f docker-compose.production.yml run --rm migrate
```

### Stopping Services

```bash
# Stop all services (preserves data)
docker-compose -f docker-compose.production.yml down

# Stop and remove volumes (DELETES ALL DATA)
docker-compose -f docker-compose.production.yml down -v
```

### Backup Database

```bash
# Backup to file
docker-compose -f docker-compose.production.yml exec db \
  pg_dump -U matthew50 softpower-db > backup-$(date +%Y%m%d).sql

# Restore from backup
docker-compose -f docker-compose.production.yml exec -T db \
  psql -U matthew50 softpower-db < backup-20241106.sql
```

### View Logs

```bash
# All services
docker-compose -f docker-compose.production.yml logs -f

# Specific service
docker-compose -f docker-compose.production.yml logs -f api
docker-compose -f docker-compose.production.yml logs -f dashboard
docker-compose -f docker-compose.production.yml logs -f db
```

## Production Deployment on Cloud Servers

### AWS EC2 / DigitalOcean / Linode / VPS

1. **Provision server** with at least 4GB RAM, 2 CPU cores
2. **Install Docker**:
   ```bash
   # Ubuntu/Debian
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   # Log out and back in for group to take effect
   ```

3. **Clone and configure**:
   ```bash
   git clone https://github.com/yourusername/SP_Streamlit.git
   cd SP_Streamlit
   cp .env.example .env
   nano .env  # Configure production credentials
   ```

4. **Start services**:
   ```bash
   docker-compose -f docker-compose.production.yml up -d
   docker-compose -f docker-compose.production.yml run --rm migrate
   ```

5. **Configure firewall**:
   ```bash
   # Allow HTTP/HTTPS and application ports
   sudo ufw allow 22/tcp    # SSH
   sudo ufw allow 80/tcp    # HTTP
   sudo ufw allow 443/tcp   # HTTPS
   sudo ufw allow 8000/tcp  # API/React app
   sudo ufw allow 8501/tcp  # Streamlit dashboard
   sudo ufw enable
   ```

6. **Optional: Setup nginx reverse proxy** for SSL and custom domain:
   ```nginx
   # /etc/nginx/sites-available/softpower
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }

       location /dashboard/ {
           proxy_pass http://localhost:8501;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
       }
   }
   ```

7. **Setup auto-restart**:
   ```bash
   # Add to crontab for restart on reboot
   crontab -e
   # Add line:
   @reboot cd /path/to/SP_Streamlit && docker-compose -f docker-compose.production.yml up -d
   ```

### Using Managed PostgreSQL (Recommended for Production)

For production, consider using managed PostgreSQL instead of the Docker container:

1. **Provision PostgreSQL** on AWS RDS, DigitalOcean Managed Databases, or similar
2. **Install pgvector extension** (some providers support this automatically)
3. **Update .env**:
   ```bash
   DB_HOST=your-postgres-hostname.rds.amazonaws.com
   DB_PORT=5432
   POSTGRES_USER=your-db-user
   POSTGRES_PASSWORD=your-db-password
   POSTGRES_DB=softpower-db
   ```

4. **Remove db service** from docker-compose.production.yml or comment it out
5. **Run migrations** against external database:
   ```bash
   docker-compose -f docker-compose.production.yml run --rm migrate
   ```

## Troubleshooting

### Port Already in Use

```bash
# Find what's using the port
sudo lsof -i :8000
sudo netstat -tulpn | grep 8000

# Change ports in docker-compose.production.yml
ports:
  - "8080:8000"  # Change host port to 8080
```

### Database Connection Failed

```bash
# Check database logs
docker-compose -f docker-compose.production.yml logs db

# Verify database is running
docker-compose -f docker-compose.production.yml ps db

# Test connection manually
docker-compose -f docker-compose.production.yml exec db \
  psql -U matthew50 -d softpower-db -c "SELECT 1"
```

### Out of Memory

```bash
# Check resource usage
docker stats

# Increase Docker memory limit in Docker Desktop settings
# Or add resource limits to docker-compose.production.yml:
services:
  api:
    deploy:
      resources:
        limits:
          memory: 2G
```

### Images Not Pulling

```bash
# Check Docker Hub access
docker pull yourusername/softpower-api:latest

# If private images, login first
docker login
```

## Architecture Overview

The production deployment consists of:

1. **API Service** (`yourusername/softpower-api:latest`)
   - FastAPI backend on port 8000
   - Serves React frontend (production build)
   - Handles all API routes at `/api/*`
   - Includes all pipeline scripts

2. **Dashboard Service** (`yourusername/softpower-dashboard:latest`)
   - Streamlit analytics dashboard on port 8501
   - Data exploration and visualization

3. **PostgreSQL Database** (`ankane/pgvector:latest`)
   - PostgreSQL 15 with pgvector extension
   - Persistent storage via Docker volume

4. **Redis** (`redis:7-alpine`)
   - Cache and task queue (optional, for future use)

All services communicate via the `softpower_net` Docker network.

## Benefits of This Deployment Method

✅ **One-Command Deployment**: `docker-compose up -d` is all users need
✅ **No Source Code Required**: Users pull pre-built images from Docker Hub
✅ **Multi-Architecture Support**: Works on AMD64 (x86) and ARM64 (Apple Silicon, AWS Graviton)
✅ **Version Control**: Tagged images allow rollback and controlled updates
✅ **Isolated Environment**: All dependencies bundled in containers
✅ **Easy Updates**: `docker-compose pull && docker-compose up -d`
✅ **Cloud-Ready**: Works on any platform supporting Docker (AWS, GCP, Azure, DigitalOcean, etc.)

## Security Considerations

1. **Never commit .env to Git**: Use `.env.example` as template
2. **Use strong passwords** for PostgreSQL
3. **Rotate API keys** periodically
4. **Enable firewall** on production servers
5. **Use HTTPS** in production via nginx reverse proxy
6. **Limit database exposure**: Only expose port 5432 if you need direct access
7. **Regular backups**: Automate database backups
8. **Keep images updated**: Regularly rebuild and push security updates

## Next Steps

After deployment:

1. **Run initial data ingestion**:
   ```bash
   docker-compose -f docker-compose.production.yml exec api \
     python services/pipeline/ingestion/atom.py
   ```

2. **Generate embeddings**:
   ```bash
   docker-compose -f docker-compose.production.yml exec api \
     python services/pipeline/embeddings/embed_missing_documents.py
   ```

3. **Process events**:
   ```bash
   docker-compose -f docker-compose.production.yml exec api \
     python services/pipeline/events/batch_cluster_events.py --country China
   ```

4. **Monitor logs** for any issues:
   ```bash
   docker-compose -f docker-compose.production.yml logs -f
   ```

See [QUICKSTART.md](QUICKSTART.md) and [CLAUDE.md](CLAUDE.md) for full pipeline documentation.
