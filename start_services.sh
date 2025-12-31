#!/bin/bash
# Non-Docker Service Startup Script for SoftPower Analytics
# Usage: ./start_services.sh [api|dashboard|client|all|prod]
#   api       - Start FastAPI service only
#   dashboard - Start Streamlit dashboard only
#   client    - Start React Vite dev server only
#   all       - Start all services in development mode
#   prod      - Start production mode (FastAPI serves built React app)
#   stop      - Stop all services

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo -e "${GREEN}✓${NC} Loaded environment variables from .env"
else
    echo -e "${RED}✗${NC} .env file not found!"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}!${NC} Virtual environment not found. Creating..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    echo -e "${GREEN}✓${NC} Virtual environment created and dependencies installed"
else
    source venv/bin/activate
    echo -e "${GREEN}✓${NC} Activated virtual environment"
fi

# Check database connection
echo -e "${BLUE}→${NC} Checking database connection..."
python -c "from shared.database.database import health_check; import sys; sys.exit(0 if health_check() else 1)" 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Database connection successful"
else
    echo -e "${RED}✗${NC} Database connection failed!"
    echo -e "${YELLOW}→${NC} Make sure PostgreSQL is running and configured correctly"
    exit 1
fi

# Function to start FastAPI service
start_api() {
    echo -e "${BLUE}→${NC} Starting FastAPI service on port ${API_PORT:-5001}..."
    cd "$PROJECT_ROOT/services/api"
    uvicorn main:app --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-5001} --reload &
    API_PID=$!
    echo -e "${GREEN}✓${NC} FastAPI started (PID: $API_PID)"
    echo $API_PID > "$PROJECT_ROOT/.api.pid"
}

# Function to start Streamlit dashboard
start_dashboard() {
    echo -e "${BLUE}→${NC} Starting Streamlit dashboard on port ${STREAMLIT_PORT:-8501}..."
    cd "$PROJECT_ROOT/services/dashboard"
    streamlit run app.py --server.port ${STREAMLIT_PORT:-8501} --server.address ${STREAMLIT_HOST:-0.0.0.0} &
    DASHBOARD_PID=$!
    echo -e "${GREEN}✓${NC} Streamlit started (PID: $DASHBOARD_PID)"
    echo $DASHBOARD_PID > "$PROJECT_ROOT/.dashboard.pid"
}

# Function to start React Vite dev server
start_client() {
    echo -e "${BLUE}→${NC} Starting React Vite dev server on port 5000..."
    cd "$PROJECT_ROOT/client"
    npm run dev &
    CLIENT_PID=$!
    echo -e "${GREEN}✓${NC} React dev server started (PID: $CLIENT_PID)"
    echo $CLIENT_PID > "$PROJECT_ROOT/.client.pid"
}

# Function to build React for production
build_client() {
    echo -e "${BLUE}→${NC} Building React app for production..."
    cd "$PROJECT_ROOT/client"
    npm run build
    echo -e "${GREEN}✓${NC} React app built successfully to client/dist/"
}

# Function to start production FastAPI (serves React + API)
start_prod() {
    echo -e "${BLUE}→${NC} Starting FastAPI in production mode (port 8000)..."
    cd "$PROJECT_ROOT"
    uvicorn server.main:app --host ${API_HOST:-0.0.0.0} --port 8000 --reload &
    API_PID=$!
    echo -e "${GREEN}✓${NC} FastAPI production server started (PID: $API_PID)"
    echo $API_PID > "$PROJECT_ROOT/.api.pid"
}

# Function to stop services
stop_services() {
    echo -e "${YELLOW}→${NC} Stopping services..."

    if [ -f "$PROJECT_ROOT/.api.pid" ]; then
        kill $(cat "$PROJECT_ROOT/.api.pid") 2>/dev/null || true
        rm "$PROJECT_ROOT/.api.pid"
        echo -e "${GREEN}✓${NC} FastAPI stopped"
    fi

    if [ -f "$PROJECT_ROOT/.dashboard.pid" ]; then
        kill $(cat "$PROJECT_ROOT/.dashboard.pid") 2>/dev/null || true
        rm "$PROJECT_ROOT/.dashboard.pid"
        echo -e "${GREEN}✓${NC} Streamlit stopped"
    fi

    if [ -f "$PROJECT_ROOT/.client.pid" ]; then
        kill $(cat "$PROJECT_ROOT/.client.pid") 2>/dev/null || true
        rm "$PROJECT_ROOT/.client.pid"
        echo -e "${GREEN}✓${NC} React dev server stopped"
    fi

    # Also kill any remaining node/vite processes
    pkill -f "vite" 2>/dev/null || true
}

# Handle script arguments
case "${1:-all}" in
    api)
        start_api
        ;;
    dashboard)
        start_dashboard
        ;;
    client)
        start_client
        ;;
    all)
        # Development mode: API + React dev server + Streamlit
        start_api
        sleep 2
        start_client
        sleep 2
        start_dashboard
        ;;
    prod)
        # Production mode: Build React, then serve via FastAPI + Streamlit
        build_client
        start_prod
        sleep 2
        start_dashboard
        ;;
    stop)
        stop_services
        exit 0
        ;;
    *)
        echo "Usage: $0 [api|dashboard|client|all|prod|stop]"
        echo "  api       - Start FastAPI service only"
        echo "  dashboard - Start Streamlit dashboard only"
        echo "  client    - Start React Vite dev server only"
        echo "  all       - Start all services in development mode"
        echo "  prod      - Start production mode (FastAPI serves built React)"
        echo "  stop      - Stop all services"
        exit 1
        ;;
esac

# Display access URLs
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Services Started Successfully!${NC}"
echo -e "${GREEN}========================================${NC}"

case "${1:-all}" in
    prod)
        echo -e "React App:  http://localhost:8000 ${BLUE}(production build)${NC}"
        echo -e "API:        http://localhost:8000/api/* ${BLUE}(same server)${NC}"
        echo -e "Dashboard:  http://localhost:${STREAMLIT_PORT:-8501}"
        ;;
    all)
        echo -e "React App:  http://localhost:5000 ${BLUE}(dev server with hot reload)${NC}"
        echo -e "API:        http://localhost:${API_PORT:-5001}"
        echo -e "Dashboard:  http://localhost:${STREAMLIT_PORT:-8501}"
        ;;
    api)
        echo -e "API:        http://localhost:${API_PORT:-5001}"
        ;;
    dashboard)
        echo -e "Dashboard:  http://localhost:${STREAMLIT_PORT:-8501}"
        ;;
    client)
        echo -e "React App:  http://localhost:5000 ${BLUE}(dev server)${NC}"
        ;;
esac

echo -e ""
echo -e "${YELLOW}Press Ctrl+C to stop services${NC}"
echo -e "${YELLOW}Or run: ./start_services.sh stop${NC}"
echo ""

# Trap Ctrl+C to stop services
trap stop_services EXIT INT TERM

# Wait for services
wait
