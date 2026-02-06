#!/bin/bash
# Deploy SoftPower Analytics using pure Docker (no docker-compose required)
# Usage: ./deploy-docker-only.sh [start|stop|restart|logs|status]

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration (load from .env or use defaults)
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

POSTGRES_USER=${POSTGRES_USER:-matthew50}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-softpower}
POSTGRES_DB=${POSTGRES_DB:-softpower-db}
DB_PORT=${DB_PORT:-5432}
API_PORT=${API_PORT:-8000}
STREAMLIT_PORT=${STREAMLIT_PORT:-8501}

# Docker image names (replace 'yourusername' with your Docker Hub username)
DOCKER_USERNAME=${DOCKER_USERNAME:-yourusername}
API_IMAGE="${DOCKER_USERNAME}/softpower-api:latest"
DASHBOARD_IMAGE="${DOCKER_USERNAME}/softpower-dashboard:latest"

# Container names
DB_CONTAINER="softpower_db_prod"
REDIS_CONTAINER="softpower_redis_prod"
API_CONTAINER="softpower_api_prod"
DASHBOARD_CONTAINER="softpower_dashboard_prod"

# Network and volume names
NETWORK_NAME="softpower_net_prod"
DB_VOLUME="postgres_data_prod"

# Function to create network
create_network() {
    if ! docker network inspect $NETWORK_NAME &>/dev/null; then
        echo -e "${BLUE}→${NC} Creating Docker network: $NETWORK_NAME"
        docker network create $NETWORK_NAME
        echo -e "${GREEN}✓${NC} Network created"
    else
        echo -e "${GREEN}✓${NC} Network $NETWORK_NAME already exists"
    fi
}

# Function to create volume
create_volume() {
    if ! docker volume inspect $DB_VOLUME &>/dev/null; then
        echo -e "${BLUE}→${NC} Creating Docker volume: $DB_VOLUME"
        docker volume create $DB_VOLUME
        echo -e "${GREEN}✓${NC} Volume created"
    else
        echo -e "${GREEN}✓${NC} Volume $DB_VOLUME already exists"
    fi
}

# Function to start PostgreSQL
start_db() {
    echo -e "${BLUE}→${NC} Starting PostgreSQL with pgvector..."

    docker run -d \
        --name $DB_CONTAINER \
        --network $NETWORK_NAME \
        -e POSTGRES_USER=$POSTGRES_USER \
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
        -e POSTGRES_DB=$POSTGRES_DB \
        -p $DB_PORT:5432 \
        -v $DB_VOLUME:/var/lib/postgresql/data \
        --restart unless-stopped \
        ankane/pgvector:latest

    echo -e "${GREEN}✓${NC} PostgreSQL started (container: $DB_CONTAINER)"
    echo -e "   Waiting for database to be ready..."

    # Wait for PostgreSQL to be ready
    for i in {1..30}; do
        if docker exec $DB_CONTAINER pg_isready -U $POSTGRES_USER &>/dev/null; then
            echo -e "${GREEN}✓${NC} Database is ready"
            break
        fi
        sleep 1
    done
}

# Function to start Redis
start_redis() {
    echo -e "${BLUE}→${NC} Starting Redis..."

    docker run -d \
        --name $REDIS_CONTAINER \
        --network $NETWORK_NAME \
        --restart unless-stopped \
        redis:7-alpine

    echo -e "${GREEN}✓${NC} Redis started (container: $REDIS_CONTAINER)"
}

# Function to start API service
start_api() {
    echo -e "${BLUE}→${NC} Starting API service..."
    echo -e "   Pulling image: $API_IMAGE"
    docker pull $API_IMAGE

    docker run -d \
        --name $API_CONTAINER \
        --network $NETWORK_NAME \
        -p $API_PORT:8000 \
        -e DOCKER_ENV=true \
        -e DB_HOST=$DB_CONTAINER \
        -e DB_PORT=5432 \
        -e POSTGRES_USER=$POSTGRES_USER \
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
        -e POSTGRES_DB=$POSTGRES_DB \
        -e DB_POOL_SIZE=${DB_POOL_SIZE:-10} \
        -e DB_MAX_OVERFLOW=${DB_MAX_OVERFLOW:-20} \
        -e DB_POOL_TIMEOUT=${DB_POOL_TIMEOUT:-30} \
        -e DB_POOL_RECYCLE=${DB_POOL_RECYCLE:-3600} \
        -e REDIS_URL=redis://$REDIS_CONTAINER:6379 \
        -e CLAUDE_KEY=${CLAUDE_KEY} \
        -e OPENAI_PROJ_API=${OPENAI_PROJ_API} \
        -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
        -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
        -e AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1} \
        -e API_URL=${API_URL:-http://host.docker.internal:5001} \
        -e FASTAPI_URL=http://$API_CONTAINER:8000/material_query \
        --restart unless-stopped \
        $API_IMAGE

    echo -e "${GREEN}✓${NC} API service started (container: $API_CONTAINER)"
}

# Function to start Dashboard service
start_dashboard() {
    echo -e "${BLUE}→${NC} Starting Streamlit Dashboard..."
    echo -e "   Pulling image: $DASHBOARD_IMAGE"
    docker pull $DASHBOARD_IMAGE

    docker run -d \
        --name $DASHBOARD_CONTAINER \
        --network $NETWORK_NAME \
        -p $STREAMLIT_PORT:8501 \
        -e DOCKER_ENV=true \
        -e DB_HOST=$DB_CONTAINER \
        -e DB_PORT=5432 \
        -e POSTGRES_USER=$POSTGRES_USER \
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
        -e POSTGRES_DB=$POSTGRES_DB \
        -e DB_POOL_SIZE=${DB_POOL_SIZE:-5} \
        -e DB_MAX_OVERFLOW=${DB_MAX_OVERFLOW:-10} \
        -e DB_POOL_TIMEOUT=${DB_POOL_TIMEOUT:-30} \
        -e DB_POOL_RECYCLE=${DB_POOL_RECYCLE:-3600} \
        -e API_URL=http://$API_CONTAINER:8000 \
        -e FASTAPI_URL=http://$API_CONTAINER:8000/material_query \
        --restart unless-stopped \
        $DASHBOARD_IMAGE

    echo -e "${GREEN}✓${NC} Dashboard started (container: $DASHBOARD_CONTAINER)"
}

# Function to run migrations
run_migrations() {
    echo -e "${BLUE}→${NC} Running database migrations..."

    docker run --rm \
        --network $NETWORK_NAME \
        -e DOCKER_ENV=true \
        -e DB_HOST=$DB_CONTAINER \
        -e DB_PORT=5432 \
        -e POSTGRES_USER=$POSTGRES_USER \
        -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
        -e POSTGRES_DB=$POSTGRES_DB \
        $API_IMAGE \
        alembic upgrade head

    echo -e "${GREEN}✓${NC} Migrations completed"
}

# Function to stop all containers
stop_all() {
    echo -e "${YELLOW}→${NC} Stopping all containers..."

    for container in $DASHBOARD_CONTAINER $API_CONTAINER $REDIS_CONTAINER $DB_CONTAINER; do
        if docker ps -q -f name=$container | grep -q .; then
            docker stop $container
            docker rm $container
            echo -e "${GREEN}✓${NC} Stopped and removed: $container"
        fi
    done
}

# Function to show logs
show_logs() {
    container=${1:-$API_CONTAINER}
    echo -e "${BLUE}→${NC} Showing logs for: $container"
    docker logs -f $container
}

# Function to show status
show_status() {
    echo -e "${BLUE}→${NC} Container status:"
    echo ""
    docker ps -a --filter "name=softpower_" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo -e "${BLUE}→${NC} Network status:"
    docker network inspect $NETWORK_NAME --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo "Network not created"
    echo ""
    echo -e "${BLUE}→${NC} Volume status:"
    docker volume inspect $DB_VOLUME --format 'Size: {{.Mountpoint}}' 2>/dev/null || echo "Volume not created"
}

# Function to start all services
start_all() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}SoftPower Analytics - Docker Deployment${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    # Check if .env exists
    if [ ! -f .env ]; then
        echo -e "${RED}✗${NC} .env file not found!"
        echo -e "${YELLOW}→${NC} Please create .env file with your configuration"
        echo -e "${YELLOW}→${NC} See .env.example for template"
        exit 1
    fi

    # Create network and volume
    create_network
    create_volume

    # Start services in order
    start_db
    sleep 3
    start_redis
    sleep 2
    start_api
    sleep 5
    start_dashboard

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}All Services Started!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "React App:  http://localhost:$API_PORT"
    echo -e "API Docs:   http://localhost:$API_PORT/docs"
    echo -e "Dashboard:  http://localhost:$STREAMLIT_PORT"
    echo -e "Database:   localhost:$DB_PORT"
    echo ""
    echo -e "${YELLOW}First-time setup: Run migrations${NC}"
    echo -e "  ./deploy-docker-only.sh migrate"
    echo ""
}

# Main command handler
case "${1:-start}" in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        start_all
        ;;
    migrate)
        run_migrations
        ;;
    logs)
        show_logs $2
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|migrate|logs [container]|status}"
        echo ""
        echo "Commands:"
        echo "  start    - Start all services"
        echo "  stop     - Stop all services"
        echo "  restart  - Restart all services"
        echo "  migrate  - Run database migrations"
        echo "  logs     - Show logs (optionally specify container name)"
        echo "  status   - Show status of all containers"
        echo ""
        echo "Examples:"
        echo "  $0 start"
        echo "  $0 logs $API_CONTAINER"
        echo "  $0 status"
        exit 1
        ;;
esac
