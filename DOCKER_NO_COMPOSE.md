# Deploying Without Docker Compose

This guide shows how to deploy SoftPower Analytics on systems that have Docker but not Docker Compose (older Docker versions, embedded systems, certain Linux distros).

## Quick Start (Using Scripts)

We've created deployment scripts that replicate docker-compose functionality using pure `docker` commands.

### Linux/macOS

```bash
# Make script executable
chmod +x deploy-docker-only.sh

# Start all services
./deploy-docker-only.sh start

# Run migrations (first-time setup)
./deploy-docker-only.sh migrate

# View status
./deploy-docker-only.sh status

# View logs
./deploy-docker-only.sh logs softpower_api_prod

# Stop all services
./deploy-docker-only.sh stop
```

### Windows (PowerShell)

```powershell
# Start all services
.\deploy-docker-only.ps1 -Command start

# Run migrations (first-time setup)
.\deploy-docker-only.ps1 -Command migrate

# View status
.\deploy-docker-only.ps1 -Command status

# View logs
.\deploy-docker-only.ps1 -Command logs -Container softpower_api_prod

# Stop all services
.\deploy-docker-only.ps1 -Command stop
```

## Manual Deployment (Step-by-Step)

If you prefer to run commands manually or understand what the script does:

### Step 1: Create .env File

```bash
cat > .env << EOF
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=your-secure-password
POSTGRES_DB=softpower-db
CLAUDE_KEY=sk-your-claude-key
OPENAI_PROJ_API=sk-your-openai-key
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
DOCKER_USERNAME=yourusername
EOF
```

### Step 2: Load Environment Variables

**Linux/macOS:**
```bash
export $(grep -v '^#' .env | xargs)
```

**Windows (PowerShell):**
```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#].+?)=(.+)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim().Trim("'", '"')
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}
```

### Step 3: Create Docker Network

All containers need to communicate on the same network:

```bash
docker network create softpower_net_prod
```

**What this does**: Creates a virtual network where containers can talk to each other by name (e.g., API can connect to database using hostname `softpower_db_prod`).

### Step 4: Create Docker Volume

Database data needs to persist:

```bash
docker volume create postgres_data_prod
```

**What this does**: Creates a storage volume for PostgreSQL data that survives container restarts/deletions.

### Step 5: Start PostgreSQL

```bash
docker run -d \
    --name softpower_db_prod \
    --network softpower_net_prod \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-secure-password \
    -e POSTGRES_DB=softpower-db \
    -p 5432:5432 \
    -v postgres_data_prod:/var/lib/postgresql/data \
    --restart unless-stopped \
    ankane/pgvector:latest
```

**Explanation**:
- `-d`: Run in background (detached)
- `--name`: Container name (used by other containers to connect)
- `--network`: Attach to our custom network
- `-e`: Environment variables
- `-p 5432:5432`: Expose port 5432 to host
- `-v`: Mount volume for data persistence
- `--restart unless-stopped`: Auto-restart on boot

**Wait for database to be ready**:
```bash
# Check if ready
docker exec softpower_db_prod pg_isready -U matthew50

# Or watch logs
docker logs -f softpower_db_prod
```

### Step 6: Start Redis

```bash
docker run -d \
    --name softpower_redis_prod \
    --network softpower_net_prod \
    --restart unless-stopped \
    redis:7-alpine
```

### Step 7: Start API Service

Replace `yourusername` with your Docker Hub username:

```bash
docker run -d \
    --name softpower_api_prod \
    --network softpower_net_prod \
    -p 8000:8000 \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db_prod \
    -e DB_PORT=5432 \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-secure-password \
    -e POSTGRES_DB=softpower-db \
    -e REDIS_URL=redis://softpower_redis_prod:6379 \
    -e CLAUDE_KEY=sk-your-claude-key \
    -e OPENAI_PROJ_API=sk-your-openai-key \
    -e AWS_ACCESS_KEY_ID=your-aws-key \
    -e AWS_SECRET_ACCESS_KEY=your-aws-secret \
    --restart unless-stopped \
    yourusername/softpower-api:latest
```

**Important**: Notice `DB_HOST=softpower_db_prod` - this is the PostgreSQL container name. Docker's network DNS resolves this to the correct IP.

### Step 8: Start Streamlit Dashboard

```bash
docker run -d \
    --name softpower_dashboard_prod \
    --network softpower_net_prod \
    -p 8501:8501 \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db_prod \
    -e DB_PORT=5432 \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-secure-password \
    -e POSTGRES_DB=softpower-db \
    -e API_URL=http://softpower_api_prod:8000 \
    --restart unless-stopped \
    yourusername/softpower-dashboard:latest
```

### Step 9: Run Database Migrations (First-Time Setup)

```bash
docker run --rm \
    --network softpower_net_prod \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db_prod \
    -e DB_PORT=5432 \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-secure-password \
    -e POSTGRES_DB=softpower-db \
    yourusername/softpower-api:latest \
    alembic upgrade head
```

**Note**: `--rm` means the container is automatically deleted after migrations finish.

### Step 10: Verify Everything is Running

```bash
docker ps
```

**Expected output**:
```
CONTAINER ID   IMAGE                              STATUS         PORTS
abc123         yourusername/softpower-api         Up 2 minutes   0.0.0.0:8000->8000/tcp
def456         yourusername/softpower-dashboard   Up 1 minute    0.0.0.0:8501->8501/tcp
ghi789         ankane/pgvector:latest             Up 3 minutes   0.0.0.0:5432->5432/tcp
jkl012         redis:7-alpine                     Up 3 minutes   6379/tcp
```

### Step 11: Access the Application

- **React App**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Streamlit Dashboard**: http://localhost:8501
- **Database**: localhost:5432 (for direct SQL access)

## Common Operations

### View Logs

```bash
# All logs from a container
docker logs softpower_api_prod

# Follow logs (live stream)
docker logs -f softpower_api_prod

# Last 100 lines
docker logs --tail 100 softpower_api_prod

# Since specific time
docker logs --since 2024-01-01T10:00:00 softpower_api_prod
```

### Run Pipeline Scripts

```bash
# Document ingestion
docker exec softpower_api_prod \
    python services/pipeline/ingestion/atom.py

# Event processing
docker exec softpower_api_prod \
    python services/pipeline/events/batch_cluster_events.py --country China

# Interactive shell in container
docker exec -it softpower_api_prod /bin/bash
```

### Update to New Version

```bash
# Pull new image
docker pull yourusername/softpower-api:latest

# Stop old container
docker stop softpower_api_prod
docker rm softpower_api_prod

# Start new container (same docker run command as Step 7)
docker run -d \
    --name softpower_api_prod \
    --network softpower_net_prod \
    -p 8000:8000 \
    ... (all the same options)
    yourusername/softpower-api:latest

# Run migrations if needed
docker run --rm \
    --network softpower_net_prod \
    ... (same options as Step 9)
    yourusername/softpower-api:latest \
    alembic upgrade head
```

### Restart a Container

```bash
docker restart softpower_api_prod
```

### Stop All Containers

```bash
docker stop softpower_dashboard_prod softpower_api_prod softpower_redis_prod softpower_db_prod
```

### Remove All Containers (Preserves Data)

```bash
docker rm softpower_dashboard_prod softpower_api_prod softpower_redis_prod softpower_db_prod
```

**Note**: Database data is safe in the `postgres_data_prod` volume.

### Completely Remove Everything (INCLUDING DATA)

```bash
# Stop and remove containers
docker stop softpower_dashboard_prod softpower_api_prod softpower_redis_prod softpower_db_prod
docker rm softpower_dashboard_prod softpower_api_prod softpower_redis_prod softpower_db_prod

# Remove network
docker network rm softpower_net_prod

# Remove volume (⚠️ THIS DELETES ALL DATABASE DATA)
docker volume rm postgres_data_prod
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs softpower_api_prod

# Common issues:
# - Database not ready yet (wait 10-20 seconds)
# - Missing environment variables
# - Network not created
# - Port already in use
```

### Can't Connect to Database

```bash
# Verify database is running
docker ps | grep softpower_db_prod

# Test database connection
docker exec softpower_db_prod pg_isready -U matthew50

# Check if API can reach database
docker exec softpower_api_prod ping softpower_db_prod

# Verify network
docker network inspect softpower_net_prod
```

### Port Already in Use

```bash
# Find what's using port 8000
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Use different port
docker run -p 8080:8000 ...  # Expose on 8080 instead
```

### Container Keeps Restarting

```bash
# View why it's failing
docker logs softpower_api_prod

# Run without restart to see error
docker run --rm -it \
    --name softpower_api_test \
    --network softpower_net_prod \
    -e DB_HOST=softpower_db_prod \
    ... (other options)
    yourusername/softpower-api:latest
```

### Image Pull Fails

```bash
# Login to Docker Hub first
docker login

# Verify image exists
docker pull yourusername/softpower-api:latest

# Try specific version
docker pull yourusername/softpower-api:v1.0.0
```

## Comparison: docker-compose vs Pure Docker

| Feature | docker-compose | Pure Docker |
|---------|----------------|-------------|
| **Single config file** | ✓ docker-compose.yml | ❌ Multiple commands |
| **Start all services** | `docker-compose up -d` | Run each `docker run` manually |
| **Stop all services** | `docker-compose down` | Stop each container manually |
| **View logs** | `docker-compose logs -f` | `docker logs -f <container>` |
| **Network creation** | Automatic | Manual: `docker network create` |
| **Volume creation** | Automatic | Manual: `docker volume create` |
| **Environment variables** | From .env automatically | Must export or pass with -e |
| **Service dependencies** | Automatic (depends_on) | Manual ordering |
| **Scaling** | `docker-compose up --scale api=3` | Manual duplication |
| **Updates** | `docker-compose pull && up -d` | Pull and restart manually |

**Bottom line**: docker-compose is much easier, but pure Docker gives you more control and works everywhere Docker is installed.

## Production Tips

### 1. Use a Process Manager

Instead of running containers manually, use systemd (Linux) or Windows Services:

**systemd example** (`/etc/systemd/system/softpower.service`):
```ini
[Unit]
Description=SoftPower Analytics
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/softpower
ExecStart=/opt/softpower/deploy-docker-only.sh start
ExecStop=/opt/softpower/deploy-docker-only.sh stop

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable softpower
sudo systemctl start softpower
```

### 2. Automated Backups

```bash
# Backup database
docker exec softpower_db_prod pg_dump -U matthew50 softpower-db > backup-$(date +%Y%m%d).sql

# Backup volume
docker run --rm \
    -v postgres_data_prod:/data \
    -v $(pwd):/backup \
    alpine tar czf /backup/postgres-backup-$(date +%Y%m%d).tar.gz /data
```

### 3. Health Checks

```bash
# Add to cron to monitor services
#!/bin/bash
if ! docker ps | grep -q softpower_api_prod; then
    docker start softpower_api_prod
    echo "Restarted API container at $(date)" >> /var/log/softpower-restart.log
fi
```

### 4. Resource Limits

Prevent containers from using too much memory/CPU:

```bash
docker run -d \
    --name softpower_api_prod \
    --memory="2g" \
    --cpus="1.5" \
    ... (other options)
    yourusername/softpower-api:latest
```

## Benefits of Using the Provided Scripts

The `deploy-docker-only.sh` and `deploy-docker-only.ps1` scripts provide:

✅ **Automatic dependency ordering** (DB → Redis → API → Dashboard)
✅ **Health checks** (waits for DB to be ready)
✅ **Environment variable loading** (from .env)
✅ **Error handling** (stops if something fails)
✅ **Consistent naming** (all containers, networks, volumes use same prefix)
✅ **Easy updates** (`./deploy-docker-only.sh restart`)
✅ **Status monitoring** (`./deploy-docker-only.sh status`)
✅ **Log viewing** (`./deploy-docker-only.sh logs <container>`)

## Next Steps

After deployment:

1. Run migrations: `./deploy-docker-only.sh migrate`
2. Access React app: http://localhost:8000
3. Run pipeline scripts: `docker exec softpower_api_prod python services/pipeline/...`
4. Monitor logs: `./deploy-docker-only.sh logs softpower_api_prod`
5. Setup automated backups
6. Configure firewall/nginx if needed

For more details, see:
- [DOCKER_HUB_DEPLOYMENT.md](DOCKER_HUB_DEPLOYMENT.md) - Full deployment guide
- [QUICKSTART.md](QUICKSTART.md) - Quick reference
- [CLAUDE.md](CLAUDE.md) - Architecture overview
