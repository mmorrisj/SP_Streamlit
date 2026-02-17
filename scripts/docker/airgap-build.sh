#!/bin/bash
# ============================================
# Air-Gapped Package Builder
# Run this on an INTERNET-CONNECTED machine
# Produces a self-contained tar.gz for transfer
# to the air-gapped CentOS 7 target
# ============================================
# Output: softpower-airgap-YYYYMMDD.tar.gz
#   Contains:
#   - 2 Docker image tar files (db + app)
#   - Deployment script
#   - Database backup (if available)
#   - .env.example
# ============================================

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

VERSION="${1:-$(date +%Y%m%d)}"
PACKAGE_DIR="softpower-airgap-${VERSION}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo ""
echo "=============================================="
echo "SoftPower Analytics - Air-Gap Package Builder"
echo "=============================================="
echo "Version:      $VERSION"
echo "Project root: $PROJECT_ROOT"
echo "Output:       ${PACKAGE_DIR}.tar.gz"
echo "=============================================="
echo ""

cd "$PROJECT_ROOT"

# ============================================
# Step 1: Build Docker images
# ============================================
echo -e "${BLUE}[1/6]${NC} Preparing Docker images..."
echo ""

# Database: Use official pgvector image (PostgreSQL 16 + pgvector extension)
# Source: https://hub.docker.com/r/pgvector/pgvector
DB_IMAGE="pgvector/pgvector:0.8.0-pg16"
if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "pgvector/pgvector"; then
    echo -e "  ${GREEN}Database image found: ${DB_IMAGE}${NC}"
else
    echo -e "  ${YELLOW}Database image not found locally: ${DB_IMAGE}${NC}"
    echo "  Attempting to pull from registry..."
    if docker pull "$DB_IMAGE" 2>/dev/null; then
        echo -e "  ${GREEN}Database image pulled${NC}"
    else
        echo -e "  ${RED}Cannot pull ${DB_IMAGE}. Please load it manually:${NC}"
        echo "    docker load -i pgvector-pg16.tar"
        exit 1
    fi
fi

echo ""
echo "  Building application image (FastAPI + Streamlit)..."
docker build \
    -f docker/airgap.Dockerfile \
    -t softpower-app-airgap:latest \
    .
echo -e "  ${GREEN}Application image built${NC}"
echo ""

# ============================================
# Step 2: Download HuggingFace model
# ============================================
echo -e "${BLUE}[2/7]${NC} Downloading sentence-transformers model..."
echo ""

MODEL_DIR="$PACKAGE_DIR/hf_model"
mkdir -p "$MODEL_DIR"

# Download the model into a local directory using the same image
# so the cached format matches exactly what the container expects
docker run --rm \
    -v "$(pwd)/$MODEL_DIR:/export" \
    -e HF_HOME=/export \
    softpower-app-airgap:latest \
    python -c "\
from sentence_transformers import SentenceTransformer; \
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
print('Model downloaded to /export')"

echo -e "  ${GREEN}Model downloaded${NC} ($(du -sh "$MODEL_DIR" | cut -f1))"
echo ""

# ============================================
# Step 3: Export images as tar files
# ============================================
echo -e "${BLUE}[3/7]${NC} Exporting Docker images to tar files..."
echo ""

mkdir -p "$PACKAGE_DIR/images"

docker save "$DB_IMAGE" -o "$PACKAGE_DIR/images/pgvector-pg16.tar"
echo -e "  ${GREEN}pgvector-pg16.tar${NC} ($(du -h "$PACKAGE_DIR/images/pgvector-pg16.tar" | cut -f1))"

docker save softpower-app-airgap:latest -o "$PACKAGE_DIR/images/softpower-app-airgap.tar"
echo -e "  ${GREEN}softpower-app-airgap.tar${NC} ($(du -h "$PACKAGE_DIR/images/softpower-app-airgap.tar" | cut -f1))"
echo ""

# ============================================
# Step 3: Database backup (if running)
# ============================================
echo -e "${BLUE}[4/7]${NC} Checking for database backup..."
echo ""

if docker ps --format '{{.Names}}' | grep -q '^softpower_db$'; then
    echo "  Active database found, creating backup..."
    docker exec softpower_db pg_dump \
        -U "${POSTGRES_USER:-matthew50}" \
        -d "${POSTGRES_DB:-softpower-db}" \
        -F c \
        -f /tmp/backup.dump
    docker cp softpower_db:/tmp/backup.dump "$PACKAGE_DIR/softpower-backup.dump"
    docker exec softpower_db rm /tmp/backup.dump
    echo -e "  ${GREEN}Database backup created${NC} ($(du -h "$PACKAGE_DIR/softpower-backup.dump" | cut -f1))"
else
    echo -e "  ${YELLOW}No running database found, skipping backup${NC}"
    echo "  You can add a backup later: docker exec softpower_db pg_dump ..."
fi
echo ""

# ============================================
# Step 4: Copy deployment files
# ============================================
echo -e "${BLUE}[5/7]${NC} Copying deployment files..."
echo ""

# Deployment script
cp scripts/docker/airgap-deploy.sh "$PACKAGE_DIR/"
chmod +x "$PACKAGE_DIR/airgap-deploy.sh"

# Environment template
if [ -f .env.example ]; then
    cp .env.example "$PACKAGE_DIR/.env.example"
fi

# Alembic files (for migrations run inside the container)
# These are already baked into the app image, but having them
# outside is useful for debugging
mkdir -p "$PACKAGE_DIR/debug"
cp -r alembic "$PACKAGE_DIR/debug/"
cp alembic.ini "$PACKAGE_DIR/debug/"

echo -e "  ${GREEN}Deployment files copied${NC}"
echo ""

# ============================================
# Step 5: Create documentation
# ============================================
echo -e "${BLUE}[6/7]${NC} Creating documentation..."
echo ""

cat > "$PACKAGE_DIR/README.txt" << 'DOCEOF'
========================================================
SoftPower Analytics - Air-Gapped Deployment Package
========================================================

Architecture:
  - 2 Docker containers (no docker-compose needed)
  - Container 1: PostgreSQL 16 + pgvector (official) (database)
  - Container 2: FastAPI + Streamlit (application)

Contents:
  images/
    pgvector-pg16.tar           PostgreSQL 16 + pgvector (official)
    softpower-app-airgap.tar    FastAPI + Streamlit (single container)
  hf_model/                     Pre-downloaded sentence-transformers model
                                (~90MB, mounted as volume at runtime)
  airgap-deploy.sh              Deployment management script
  .env.example                  Environment variable template
  softpower-backup.dump         Database backup (if included)
  debug/                        Alembic migrations (for troubleshooting)

System Requirements:
  - CentOS 7 (or RHEL 7+)
  - Docker 17.05+ (for loading pre-built images)
  - 16GB+ RAM recommended
  - 30GB+ free disk space
  - Ports: 8000 (Web App), 8501 (Streamlit), 5432 (PostgreSQL)

========================================================
QUICK START
========================================================

1. Transfer this directory to the air-gapped system

2. Load Docker images:
     cd softpower-airgap-XXXXXXXX
     ./airgap-deploy.sh load ./images

3. Create environment file:
     cp .env.example .env
     # Edit .env with your credentials

4. Start services:
     ./airgap-deploy.sh start

5. Run database migrations:
     ./airgap-deploy.sh migrate

6. (Optional) Restore database backup:
     ./airgap-deploy.sh restore softpower-backup.dump

7. Access the application:
     Web App:    http://<hostname>:8000
     Streamlit:  http://<hostname>:8501
     API Docs:   http://<hostname>:8000/docs

========================================================
MANAGEMENT COMMANDS
========================================================

  ./airgap-deploy.sh start            Start all services
  ./airgap-deploy.sh stop             Stop all services
  ./airgap-deploy.sh restart          Restart all services
  ./airgap-deploy.sh status           Show service status
  ./airgap-deploy.sh migrate          Run database migrations
  ./airgap-deploy.sh backup           Create database backup
  ./airgap-deploy.sh restore <file>   Restore from backup
  ./airgap-deploy.sh logs [container] View logs

========================================================
TROUBLESHOOTING (CentOS 7)
========================================================

SELinux blocking Docker:
  sudo setenforce 0
  # Or permanently: edit /etc/selinux/config -> SELINUX=permissive

Firewall blocking ports:
  sudo firewall-cmd --zone=public --add-port=8000/tcp --permanent
  sudo firewall-cmd --zone=public --add-port=8501/tcp --permanent
  sudo firewall-cmd --reload

Docker not starting:
  sudo systemctl start docker
  sudo systemctl enable docker

Shared memory errors (PostgreSQL):
  # The deploy script uses --shm-size=1g
  # If still failing, check: sysctl kernel.shmmax

Container networking issues:
  docker network rm softpower_net
  docker network create softpower_net
  ./airgap-deploy.sh restart

Check container logs:
  docker logs softpower_db          # Database logs
  docker logs softpower_app         # Application logs
  docker logs softpower_app 2>&1 | grep ERROR

Database connection test:
  docker exec softpower_db psql -U matthew50 -d softpower-db -c "SELECT 1;"

Disk space check:
  df -h
  docker system df
DOCEOF

cat > "$PACKAGE_DIR/INSTALL_CHECKLIST.txt" << 'CHECKEOF'
Air-Gapped Installation Checklist
==================================

Pre-Installation:
[ ] CentOS 7 / RHEL 7 system ready
[ ] Docker 17.05+ installed and daemon running
[ ] At least 30GB free disk space
[ ] Package transferred to target system
[ ] SELinux set to permissive (or configured for Docker)

Step 1 - Load Images:
[ ] cd to package directory
[ ] Run: ./airgap-deploy.sh load ./images
[ ] Verify: docker images | grep -E "softpower|pgvector"
    - pgvector/pgvector:0.8.0-pg16
    - softpower-app-airgap:latest
[ ] Verify hf_model/ directory is present (sentence-transformers model)

Step 2 - Configure:
[ ] cp .env.example .env
[ ] Edit .env with production credentials
    - POSTGRES_USER, POSTGRES_PASSWORD
    - POSTGRES_DB

Step 3 - Start Services:
[ ] Run: ./airgap-deploy.sh start
[ ] Verify: ./airgap-deploy.sh status
    - softpower_db is running
    - softpower_app is running

Step 4 - Initialize Database:
[ ] Run: ./airgap-deploy.sh migrate
[ ] (If backup available) Run: ./airgap-deploy.sh restore softpower-backup.dump

Step 5 - Verify:
[ ] curl http://localhost:8000/api/health
[ ] Open browser to http://<hostname>:8000
[ ] Open browser to http://<hostname>:8501

Step 6 - Production Hardening:
[ ] Configure firewall rules (ports 8000, 8501)
[ ] Set up systemd service for auto-restart on boot
[ ] Schedule regular database backups
[ ] Test backup/restore cycle
CHECKEOF

echo -e "  ${GREEN}Documentation created${NC}"
echo ""

# ============================================
# Step 6: Create final archive
# ============================================
echo -e "${BLUE}[7/7]${NC} Creating final archive..."
echo ""

tar czf "${PACKAGE_DIR}.tar.gz" "$PACKAGE_DIR"

echo ""
echo "=============================================="
echo -e "${GREEN}Air-Gapped Package Created Successfully${NC}"
echo "=============================================="
echo ""
echo "Package:  ${PACKAGE_DIR}.tar.gz"
echo "Size:     $(du -sh "${PACKAGE_DIR}.tar.gz" | cut -f1)"
echo ""
echo "Contents:"
echo "  images/pgvector-pg16.tar         ($(du -h "$PACKAGE_DIR/images/pgvector-pg16.tar" | cut -f1))"
echo "  images/softpower-app-airgap.tar  ($(du -h "$PACKAGE_DIR/images/softpower-app-airgap.tar" | cut -f1))"
echo "  hf_model/                        ($(du -sh "$PACKAGE_DIR/hf_model" | cut -f1) - sentence-transformers)"
if [ -f "$PACKAGE_DIR/softpower-backup.dump" ]; then
    echo "  softpower-backup.dump            ($(du -h "$PACKAGE_DIR/softpower-backup.dump" | cut -f1))"
fi
echo "  airgap-deploy.sh                 (deployment script)"
echo "  .env.example                     (config template)"
echo "  README.txt                       (instructions)"
echo "  INSTALL_CHECKLIST.txt            (checklist)"
echo ""
echo "Transfer to air-gapped system:"
echo "  scp ${PACKAGE_DIR}.tar.gz user@target:/opt/"
echo ""
echo "On the target system:"
echo "  cd /opt && tar xzf ${PACKAGE_DIR}.tar.gz"
echo "  cd ${PACKAGE_DIR}"
echo "  ./airgap-deploy.sh load ./images"
echo "  ./airgap-deploy.sh start"
echo "  ./airgap-deploy.sh migrate"
echo ""

# Cleanup staging directory (keep the tar.gz)
rm -rf "$PACKAGE_DIR"
echo "Staging directory cleaned up. Package ready: ${PACKAGE_DIR}.tar.gz"
echo ""
