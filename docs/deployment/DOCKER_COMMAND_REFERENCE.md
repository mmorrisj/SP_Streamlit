# Docker Command Reference

Quick reference showing docker-compose equivalents for pure Docker commands.

## Starting Services

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose -f docker-compose.production.yml up -d` | `./deploy-docker-only.sh start` |
| | OR manually run all `docker run` commands |

## Stopping Services

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose -f docker-compose.production.yml down` | `./deploy-docker-only.sh stop` |
| | OR `docker stop softpower_*` + `docker rm softpower_*` |

## Viewing Logs

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose logs -f` | `./deploy-docker-only.sh logs` |
| `docker-compose logs -f api` | `docker logs -f softpower_api_prod` |
| `docker-compose logs --tail=100 api` | `docker logs --tail=100 softpower_api_prod` |

## Running Migrations

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose run --rm migrate` | `./deploy-docker-only.sh migrate` |
| | OR `docker run --rm --network softpower_net_prod ... alembic upgrade head` |

## Executing Commands in Containers

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose exec api python script.py` | `docker exec softpower_api_prod python script.py` |
| `docker-compose exec api /bin/bash` | `docker exec -it softpower_api_prod /bin/bash` |
| `docker-compose exec db psql -U matthew50` | `docker exec -it softpower_db_prod psql -U matthew50` |

## Checking Status

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose ps` | `./deploy-docker-only.sh status` |
| | OR `docker ps --filter "name=softpower_"` |

## Restarting Services

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose restart` | `./deploy-docker-only.sh restart` |
| `docker-compose restart api` | `docker restart softpower_api_prod` |

## Pulling New Images

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose pull` | `docker pull yourusername/softpower-api:latest` |
| | `docker pull yourusername/softpower-dashboard:latest` |

## Updating to New Version

| docker-compose | Pure Docker |
|----------------|-------------|
| `docker-compose pull` | `docker pull yourusername/softpower-api:latest` |
| `docker-compose up -d` | `docker stop softpower_api_prod` |
| | `docker rm softpower_api_prod` |
| | `docker run -d ... yourusername/softpower-api:latest` |

## Container Names

When using pure Docker, containers are named explicitly:

| Service | Container Name |
|---------|----------------|
| Database | `softpower_db_prod` |
| Redis | `softpower_redis_prod` |
| API | `softpower_api_prod` |
| Dashboard | `softpower_dashboard_prod` |

## Network and Volume Names

| Resource | Name |
|----------|------|
| Network | `softpower_net_prod` |
| Database Volume | `postgres_data_prod` |

## Common Pipeline Commands

All pipeline scripts work the same way:

```bash
# docker-compose
docker-compose exec api python services/pipeline/events/batch_cluster_events.py --country China

# Pure Docker
docker exec softpower_api_prod python services/pipeline/events/batch_cluster_events.py --country China
```

## Quick Deployment Commands

### Using Scripts (Recommended)

**Linux/macOS:**
```bash
# Start everything
./deploy-docker-only.sh start

# Run migrations
./deploy-docker-only.sh migrate

# View logs
./deploy-docker-only.sh logs softpower_api_prod

# Check status
./deploy-docker-only.sh status

# Stop everything
./deploy-docker-only.sh stop
```

**Windows (PowerShell):**
```powershell
# Start everything
.\deploy-docker-only.ps1 -Command start

# Run migrations
.\deploy-docker-only.ps1 -Command migrate

# View logs
.\deploy-docker-only.ps1 -Command logs -Container softpower_api_prod

# Check status
.\deploy-docker-only.ps1 -Command status

# Stop everything
.\deploy-docker-only.ps1 -Command stop
```

### Manual Commands (Without Scripts)

**Step 1: Create Network and Volume**
```bash
docker network create softpower_net_prod
docker volume create postgres_data_prod
```

**Step 2: Start Database**
```bash
docker run -d \
    --name softpower_db_prod \
    --network softpower_net_prod \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-password \
    -e POSTGRES_DB=softpower-db \
    -p 5432:5432 \
    -v postgres_data_prod:/var/lib/postgresql/data \
    --restart unless-stopped \
    ankane/pgvector:latest
```

**Step 3: Start Redis**
```bash
docker run -d \
    --name softpower_redis_prod \
    --network softpower_net_prod \
    --restart unless-stopped \
    redis:7-alpine
```

**Step 4: Start API**
```bash
docker run -d \
    --name softpower_api_prod \
    --network softpower_net_prod \
    -p 8000:8000 \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db_prod \
    -e DB_PORT=5432 \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-password \
    -e POSTGRES_DB=softpower-db \
    -e REDIS_URL=redis://softpower_redis_prod:6379 \
    -e CLAUDE_KEY=your-claude-key \
    -e OPENAI_PROJ_API=your-openai-key \
    --restart unless-stopped \
    yourusername/softpower-api:latest
```

**Step 5: Start Dashboard**
```bash
docker run -d \
    --name softpower_dashboard_prod \
    --network softpower_net_prod \
    -p 8501:8501 \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db_prod \
    -e DB_PORT=5432 \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-password \
    -e POSTGRES_DB=softpower-db \
    -e API_URL=http://softpower_api_prod:8000 \
    --restart unless-stopped \
    yourusername/softpower-dashboard:latest
```

**Step 6: Run Migrations**
```bash
docker run --rm \
    --network softpower_net_prod \
    -e DOCKER_ENV=true \
    -e DB_HOST=softpower_db_prod \
    -e DB_PORT=5432 \
    -e POSTGRES_USER=matthew50 \
    -e POSTGRES_PASSWORD=your-password \
    -e POSTGRES_DB=softpower-db \
    yourusername/softpower-api:latest \
    alembic upgrade head
```

## Environment Variables

Create a `.env` file in your project root:

```bash
# Database
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=your-secure-password
POSTGRES_DB=softpower-db

# API Keys
CLAUDE_KEY=sk-your-claude-key
OPENAI_PROJ_API=sk-your-openai-key

# AWS (Optional)
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret

# Docker Hub
DOCKER_USERNAME=yourusername
```

Then load it before running commands:

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

## Troubleshooting

### Check if containers are running
```bash
docker ps --filter "name=softpower_"
```

### View logs for errors
```bash
docker logs softpower_api_prod
docker logs softpower_db_prod
```

### Test database connection
```bash
docker exec softpower_db_prod pg_isready -U matthew50
```

### Check network connectivity
```bash
docker network inspect softpower_net_prod
```

### Restart a failed container
```bash
docker restart softpower_api_prod
```

### Remove and recreate a container
```bash
docker stop softpower_api_prod
docker rm softpower_api_prod
# Then run the docker run command again
```

## Access Points

After deployment:

- **React App**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Streamlit Dashboard**: http://localhost:8501
- **PostgreSQL**: localhost:5432 (direct access)

## Additional Resources

- [DOCKER_NO_COMPOSE.md](DOCKER_NO_COMPOSE.md) - Detailed guide for Docker-only deployment
- [DOCKER_HUB_DEPLOYMENT.md](DOCKER_HUB_DEPLOYMENT.md) - Docker Hub deployment guide
- [QUICKSTART.md](QUICKSTART.md) - Quick start guide for all deployment methods
