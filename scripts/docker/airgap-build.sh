#!/bin/bash
# ============================================
# Air-Gapped Package Builder
# Run this on an INTERNET-CONNECTED machine
# Produces a self-contained package for transfer
# to the air-gapped CentOS 7 target
# ============================================
# Output (default): softpower-airgap-YYYYMMDD.tar.gz
# Output (--pack):  softpower-airgap-YYYYMMDD/  (all files safe for transfer)
#   Contains:
#   - 2 Docker image tar files (db + app, slim — no ML packages)
#   - wheels/ directory with heavy ML packages (torch, sentence-transformers)
#   - HuggingFace model directory
#   - Deployment script
#   - Database backup (if available)
#   - .env.example
# ============================================
# Usage:
#   ./airgap-build.sh                  # standard tar.gz output
#   ./airgap-build.sh --pack           # transfer-safe directory (base64 encoded binaries)
#   ./airgap-build.sh --pack 20260217  # with version tag
# ============================================

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Parse flags
PACK_MODE=false
VERSION=""
for arg in "$@"; do
    case "$arg" in
        --pack) PACK_MODE=true ;;
        *)      VERSION="$arg" ;;
    esac
done
VERSION="${VERSION:-$(date +%Y%m%d)}"

PACKAGE_DIR="softpower-airgap-${VERSION}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ "$PACK_MODE" = true ]; then
    OUTPUT_DESC="${PACKAGE_DIR}/  (transfer-safe, all .txt)"
else
    OUTPUT_DESC="${PACKAGE_DIR}.tar.gz"
fi

echo ""
echo "=============================================="
echo "SoftPower Analytics - Air-Gap Package Builder"
echo "=============================================="
echo "Version:      $VERSION"
echo "Project root: $PROJECT_ROOT"
echo "Output:       $OUTPUT_DESC"
echo "=============================================="
echo ""

cd "$PROJECT_ROOT"

# ============================================
# Step 1: Build slim Docker image
# ============================================
echo -e "${BLUE}[1/8]${NC} Preparing Docker images..."
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
echo "  Building slim application image (no ML packages)..."
docker build \
    -f docker/airgap.Dockerfile \
    -t softpower-app-airgap:latest \
    .
echo -e "  ${GREEN}Slim application image built${NC}"
echo ""

# ============================================
# Step 2: Download heavy ML package wheels
# ============================================
echo -e "${BLUE}[2/8]${NC} Downloading ML package wheels..."
echo ""

WHEELS_DIR="$PACKAGE_DIR/wheels"
mkdir -p "$WHEELS_DIR"

# Download wheels inside the slim image so they're platform-compatible.
# Uses docker create + docker cp instead of volume mounts for Windows compatibility.
# PyTorch CPU from pytorch index, everything else from PyPI.
WHEELS_CONTAINER="airgap_build_wheels_$$"
docker rm -f "$WHEELS_CONTAINER" 2>/dev/null || true

echo "  Downloading PyTorch CPU + sentence-transformers + langchain-huggingface wheels..."
docker create --name "$WHEELS_CONTAINER" \
    softpower-app-airgap:latest \
    bash -c "mkdir -p /wheels && \
        pip download --no-cache-dir --dest /wheels \
            --index-url https://download.pytorch.org/whl/cpu \
            torch==2.5.1 && \
        pip download --no-cache-dir --dest /wheels \
            --index-url https://pypi.org/simple \
            sentence-transformers==3.3.1 \
            langchain-huggingface==0.1.2"

docker start -a "$WHEELS_CONTAINER"
docker cp "$WHEELS_CONTAINER":/wheels/. "$WHEELS_DIR/"
docker rm "$WHEELS_CONTAINER"

WHEEL_COUNT=$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | wc -l)
WHEEL_SIZE=$(du -sh "$WHEELS_DIR" | cut -f1)
echo ""
echo -e "  ${GREEN}Downloaded ${WHEEL_COUNT} wheel files${NC} (${WHEEL_SIZE})"
echo ""

# ============================================
# Step 3: Download HuggingFace model
# ============================================
echo -e "${BLUE}[3/8]${NC} Downloading sentence-transformers model..."
echo ""

MODEL_DIR="$PACKAGE_DIR/hf_model"
mkdir -p "$MODEL_DIR"

# Install heavy packages in a temp container, then download and save model.
# Uses docker create + docker cp instead of volume mounts for Windows compatibility.
#
# The model is saved two ways:
#   1. /export/models/all-MiniLM-L6-v2/  — clean model.save() copy (no symlinks,
#      portable across docker cp, tar, pack/unpack transfers). This is the
#      preferred path used by shared/utils/model_cache.py at runtime.
#   2. /export/hub/models--sentence-transformers--all-MiniLM-L6-v2/  — standard
#      HF Hub cache layout (kept as fallback for compatibility).
MODEL_CONTAINER="airgap_build_model_$$"
docker rm -f "$MODEL_CONTAINER" 2>/dev/null || true

docker create --name "$MODEL_CONTAINER" \
    -e HF_HOME=/export \
    softpower-app-airgap:latest \
    bash -c "pip install --no-cache-dir --no-index --find-links /wheels \
        torch sentence-transformers langchain-huggingface 2>/dev/null && \
    python3 -c '
import os, shutil
from sentence_transformers import SentenceTransformer

# Download model into HF Hub cache (/export/hub/...)
model = SentenceTransformer(\"sentence-transformers/all-MiniLM-L6-v2\")

# Save a clean, symlink-free copy for air-gapped portability
direct_path = \"/export/models/all-MiniLM-L6-v2\"
os.makedirs(direct_path, exist_ok=True)
model.save(direct_path)
print(f\"Direct model saved to {direct_path}\")
print(f\"  Contents: {os.listdir(direct_path)}\")

# Also resolve symlinks in the HF Hub cache so it survives transfers
hub_dir = \"/export/hub\"
if os.path.isdir(hub_dir):
    for root, dirs, files in os.walk(hub_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            if os.path.islink(fpath):
                target = os.path.realpath(fpath)
                if os.path.isfile(target):
                    os.unlink(fpath)
                    shutil.copy2(target, fpath)
    print(\"HF Hub cache symlinks resolved to real files\")

print(\"Model export complete\")
'"

# Copy wheel files into the container, then run install + model download
docker cp "$WHEELS_DIR" "$MODEL_CONTAINER":/wheels
docker start -a "$MODEL_CONTAINER"
docker cp "$MODEL_CONTAINER":/export/. "$MODEL_DIR/"
docker rm "$MODEL_CONTAINER"

echo -e "  ${GREEN}Model downloaded${NC} ($(du -sh "$MODEL_DIR" | cut -f1))"
echo ""

# ============================================
# Step 4: Export images as tar files
# ============================================
echo -e "${BLUE}[4/8]${NC} Exporting Docker images to tar files..."
echo ""

mkdir -p "$PACKAGE_DIR/images"

docker save "$DB_IMAGE" -o "$PACKAGE_DIR/images/pgvector-pg16.tar"
echo -e "  ${GREEN}pgvector-pg16.tar${NC} ($(du -h "$PACKAGE_DIR/images/pgvector-pg16.tar" | cut -f1))"

docker save softpower-app-airgap:latest -o "$PACKAGE_DIR/images/softpower-app-airgap.tar"
echo -e "  ${GREEN}softpower-app-airgap.tar${NC} ($(du -h "$PACKAGE_DIR/images/softpower-app-airgap.tar" | cut -f1))"
echo ""

# ============================================
# Step 5: Database backup (if running)
# ============================================
echo -e "${BLUE}[5/8]${NC} Checking for database backup..."
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
# Step 6: Copy deployment files
# ============================================
echo -e "${BLUE}[6/8]${NC} Copying deployment files..."
echo ""

# Deployment script
cp scripts/docker/airgap-deploy.sh "$PACKAGE_DIR/"
chmod +x "$PACKAGE_DIR/airgap-deploy.sh"

# Heavy requirements file (needed by deploy setup command)
cp requirements-airgap-heavy.txt "$PACKAGE_DIR/"

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
# Step 7: Create documentation
# ============================================
echo -e "${BLUE}[7/8]${NC} Creating documentation..."
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
    softpower-app-airgap.tar    FastAPI + Streamlit (slim — no ML packages)
  wheels/                       Pre-downloaded Python wheels (~1.5GB)
                                (torch, sentence-transformers, langchain-huggingface)
                                Installed on target via: ./airgap-deploy.sh setup
  hf_model/                     Pre-downloaded sentence-transformers model
                                (~90MB, mounted as volume at runtime)
  requirements-airgap-heavy.txt List of heavy packages to install from wheels
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

2. If packed for transfer (contains .b64.txt files):
     cd softpower-airgap-XXXXXXXX
     python3 unpack-airgap.py --apply

3. Load Docker images:
     ./airgap-deploy.sh load ./images

4. Install ML packages from wheels (one-time setup):
     ./airgap-deploy.sh setup
     (installs torch, sentence-transformers into the app image)

5. Create environment file:
     cp .env.example .env
     # Edit .env with your credentials

6. Start services:
     ./airgap-deploy.sh start

7. Run database migrations:
     ./airgap-deploy.sh migrate

8. (Optional) Restore database backup:
     ./airgap-deploy.sh restore softpower-backup.dump

9. Access the application:
     Web App:    http://<hostname>:8000
     Streamlit:  http://<hostname>:8501
     API Docs:   http://<hostname>:8000/docs

========================================================
MANAGEMENT COMMANDS
========================================================

  ./airgap-deploy.sh setup              Install ML wheels into app image (one-time)
  ./airgap-deploy.sh start              Start all services
  ./airgap-deploy.sh stop               Stop all services
  ./airgap-deploy.sh restart            Restart all services
  ./airgap-deploy.sh status             Show service status
  ./airgap-deploy.sh migrate            Run database migrations
  ./airgap-deploy.sh backup             Create database backup
  ./airgap-deploy.sh restore <file>     Restore from backup
  ./airgap-deploy.sh logs [container]   View logs

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

Step 1 - Unpack (if transferred via pack):
[ ] cd to package directory
[ ] Run: python3 unpack-airgap.py --apply
    (Skip if package was NOT packed for transfer)

Step 2 - Load Images:
[ ] Run: ./airgap-deploy.sh load ./images
[ ] Verify: docker images | grep -E "softpower|pgvector"
    - pgvector/pgvector:0.8.0-pg16
    - softpower-app-airgap:latest
[ ] Verify hf_model/ directory is present (sentence-transformers model)

Step 3 - Install ML Packages:
[ ] Run: ./airgap-deploy.sh setup
    (Installs torch, sentence-transformers from local wheels)
[ ] Verify: docker images | grep softpower-app-airgap
    Size should increase from ~700MB to ~2GB after setup

Step 4 - Configure:
[ ] cp .env.example .env
[ ] Edit .env with production credentials
    - POSTGRES_USER, POSTGRES_PASSWORD
    - POSTGRES_DB

Step 5 - Start Services:
[ ] Run: ./airgap-deploy.sh start
[ ] Verify: ./airgap-deploy.sh status
    - softpower_db is running
    - softpower_app is running

Step 6 - Initialize Database:
[ ] Run: ./airgap-deploy.sh migrate
[ ] (If backup available) Run: ./airgap-deploy.sh restore softpower-backup.dump

Step 7 - Verify:
[ ] curl http://localhost:8000/api/health
[ ] Open browser to http://<hostname>:8000
[ ] Open browser to http://<hostname>:8501

Step 8 - Production Hardening:
[ ] Configure firewall rules (ports 8000, 8501)
[ ] Set up systemd service for auto-restart on boot
[ ] Schedule regular database backups
[ ] Test backup/restore cycle
CHECKEOF

echo -e "  ${GREEN}Documentation created${NC}"
echo ""

# ============================================
# Step 8: Package for transfer
# ============================================
echo -e "${BLUE}[8/8]${NC} Packaging for transfer..."
echo ""

if [ "$PACK_MODE" = true ]; then
    # --pack mode: base64 encode binaries, rename blocked extensions
    # Result is a directory of transfer-safe .txt files

    # Copy unpack script into the package
    cp "$SCRIPT_DIR/unpack-airgap.py" "$PACKAGE_DIR/"
    echo -e "  ${GREEN}Copied unpack-airgap.py into package${NC}"

    # Run pack-airgap.py
    echo ""
    echo "  Encoding binaries and renaming blocked files..."
    echo ""
    python3 "$SCRIPT_DIR/pack-airgap.py" "$PACKAGE_DIR" --apply

    echo ""
    echo "=============================================="
    echo -e "${GREEN}Transfer-Safe Package Created${NC}"
    echo "=============================================="
    echo ""
    echo "Directory:  ${PACKAGE_DIR}/"
    echo "Size:       $(du -sh "$PACKAGE_DIR" | cut -f1)"
    echo ""
    echo "All files are .txt — safe for transfer systems that block"
    echo "executables and binary files."
    echo ""
    echo "Transfer the '${PACKAGE_DIR}/' directory, then on the target:"
    echo "  cd ${PACKAGE_DIR}"
    echo "  python3 unpack-airgap.py --apply"
    echo "  ./airgap-deploy.sh load ./images"
    echo "  ./airgap-deploy.sh setup"
    echo "  ./airgap-deploy.sh start"
    echo "  ./airgap-deploy.sh migrate"
    echo ""
else
    # Standard mode: tar.gz archive
    echo "Contents:"
    echo "  images/pgvector-pg16.tar         ($(du -h "$PACKAGE_DIR/images/pgvector-pg16.tar" | cut -f1))"
    echo "  images/softpower-app-airgap.tar  ($(du -h "$PACKAGE_DIR/images/softpower-app-airgap.tar" | cut -f1))"
    echo "  wheels/                          ($(du -sh "$PACKAGE_DIR/wheels" | cut -f1) - ML package wheels)"
    echo "  hf_model/                        ($(du -sh "$PACKAGE_DIR/hf_model" | cut -f1) - sentence-transformers)"
    if [ -f "$PACKAGE_DIR/softpower-backup.dump" ]; then
        echo "  softpower-backup.dump            ($(du -h "$PACKAGE_DIR/softpower-backup.dump" | cut -f1))"
    fi
    echo "  airgap-deploy.sh                 (deployment script)"
    echo "  .env.example                     (config template)"
    echo "  README.txt                       (instructions)"
    echo "  INSTALL_CHECKLIST.txt            (checklist)"
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
    echo "Transfer to air-gapped system:"
    echo "  scp ${PACKAGE_DIR}.tar.gz user@target:/opt/"
    echo ""
    echo "On the target system:"
    echo "  cd /opt && tar xzf ${PACKAGE_DIR}.tar.gz"
    echo "  cd ${PACKAGE_DIR}"
    echo "  ./airgap-deploy.sh load ./images"
    echo "  ./airgap-deploy.sh setup"
    echo "  ./airgap-deploy.sh start"
    echo "  ./airgap-deploy.sh migrate"
    echo ""

    # Cleanup staging directory (keep the tar.gz)
    rm -rf "$PACKAGE_DIR"
    echo "Staging directory cleaned up. Package ready: ${PACKAGE_DIR}.tar.gz"
    echo ""
fi
