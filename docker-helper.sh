#!/bin/bash

# Docker Helper Commands for SP_Streamlit

set -e  # Exit on any error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .env file exists
check_env() {
    if [ ! -f .env ]; then
        print_error ".env file not found! Please create it with required environment variables."
        exit 1
    fi
}

# Start all containers
start() {
    print_status "Starting Docker containers..."
    check_env
    docker-compose up -d
    print_status "Containers started successfully!"
}

# Stop all containers
stop() {
    print_status "Stopping Docker containers..."
    docker-compose down
    print_status "Containers stopped successfully!"
}

# Restart all containers
restart() {
    print_status "Restarting Docker containers..."
    check_env
    docker-compose down
    docker-compose up -d
    print_status "Containers restarted successfully!"
}

# Show container status
status() {
    print_status "Container status:"
    docker-compose ps
}

# Show container logs
logs() {
    local service=${1:-""}
    if [ -z "$service" ]; then
        print_status "Showing logs for all containers:"
        docker-compose logs -f
    else
        print_status "Showing logs for $service:"
        docker-compose logs -f "$service"
    fi
}

# Clean up containers and volumes
clean() {
    print_warning "This will remove all containers and volumes. Are you sure? (y/N)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        print_status "Cleaning up containers and volumes..."
        docker-compose down -v --remove-orphans
        docker system prune -f
        print_status "Cleanup completed!"
    else
        print_status "Cleanup cancelled."
    fi
}

# Connect to PostgreSQL database
db_connect() {
    print_status "Connecting to PostgreSQL database..."
    docker-compose exec postgres psql -U postgres -d vectordb
}

# Show database logs
db_logs() {
    print_status "Showing PostgreSQL logs:"
    docker-compose logs -f postgres
}

# Backup database
db_backup() {
    local backup_name="backup_$(date +%Y%m%d_%H%M%S).sql"
    print_status "Creating database backup: $backup_name"
    docker-compose exec -T postgres pg_dump -U postgres vectordb > "$backup_name"
    print_status "Backup created: $backup_name"
}

# Show help
help() {
    echo "Docker Helper Commands for SP_Streamlit"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start       Start all Docker containers"
    echo "  stop        Stop all Docker containers"
    echo "  restart     Restart all Docker containers"
    echo "  status      Show container status"
    echo "  logs [svc]  Show logs (optionally for specific service)"
    echo "  clean       Remove containers and volumes (with confirmation)"
    echo "  db-connect  Connect to PostgreSQL database"
    echo "  db-logs     Show PostgreSQL container logs"
    echo "  db-backup   Create database backup"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 logs postgres"
    echo "  $0 db-connect"
}

# Main command dispatcher
case "${1:-help}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs "$2"
        ;;
    clean)
        clean
        ;;
    db-connect)
        db_connect
        ;;
    db-logs)
        db_logs
        ;;
    db-backup)
        db_backup
        ;;
    help|--help|-h)
        help
        ;;
    *)
        print_error "Unknown command: $1"
        help
        exit 1
        ;;
esac