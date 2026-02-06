#!/bin/bash
# ============================================
# Create Air-Gapped Deployment Package
# Run this on internet-connected system
# ============================================

set -e

VERSION=${1:-$(date +%Y%m%d)}
PACKAGE_NAME="softpower-airgap-${VERSION}"

echo ""
echo "=============================================="
echo "Creating Air-Gapped Deployment Package"
echo "Version: $VERSION"
echo "=============================================="
echo ""

# Create package directory
mkdir -p "$PACKAGE_NAME"
cd "$PACKAGE_NAME"

echo "📦 Step 1/6: Building Docker images..."
cd ..
./docker/build-all.sh
cd "$PACKAGE_NAME"
echo ""

echo "💾 Step 2/6: Exporting Docker images to tar files..."
docker save softpower-api:latest -o softpower-api.tar
echo "  ✅ softpower-api.tar ($(du -h softpower-api.tar | cut -f1))"

docker save softpower-dashboard:latest -o softpower-dashboard.tar
echo "  ✅ softpower-dashboard.tar ($(du -h softpower-dashboard.tar | cut -f1))"

docker save softpower-pipeline:latest -o softpower-pipeline.tar
echo "  ✅ softpower-pipeline.tar ($(du -h softpower-pipeline.tar | cut -f1))"

# Pull and save base images
echo "  Pulling base images..."
docker pull ankane/pgvector:latest
docker pull redis:7-alpine

docker save ankane/pgvector:latest -o pgvector.tar
echo "  ✅ pgvector.tar ($(du -h pgvector.tar | cut -f1))"

docker save redis:7-alpine -o redis.tar
echo "  ✅ redis.tar ($(du -h redis.tar | cut -f1))"
echo ""

echo "💿 Step 3/6: Exporting database backup..."
if docker ps --format '{{.Names}}' | grep -q '^softpower_db$'; then
    docker exec softpower_db pg_dump -U matthew50 -d softpower-db -F c -f /tmp/backup.dump
    docker cp softpower_db:/tmp/backup.dump ./softpower-backup.dump
    gzip softpower-backup.dump
    echo "  ✅ softpower-backup.dump.gz ($(du -h softpower-backup.dump.gz | cut -f1))"
else
    echo "  ⚠️  No database running, skipping backup"
    echo "  You can add a backup later if needed"
fi
echo ""

echo "📋 Step 4/6: Copying application files..."
cd ..
cp -r SP_Streamlit "$PACKAGE_NAME/"
rm -rf "$PACKAGE_NAME/SP_Streamlit/client/node_modules"
rm -rf "$PACKAGE_NAME/SP_Streamlit/client/dist"
rm -rf "$PACKAGE_NAME/SP_Streamlit/_data"
rm -rf "$PACKAGE_NAME/SP_Streamlit/.git"
echo "  ✅ Application files copied"
echo ""

cd "$PACKAGE_NAME"

echo "📄 Step 5/6: Creating documentation..."
cat > README.txt << 'EOF'
========================================
Soft Power Analytics - Air-Gapped Package
========================================

Contents:
---------
1. Docker Images (tar files):
   - softpower-api.tar          (React Web App + FastAPI)
   - softpower-dashboard.tar    (Streamlit Dashboard)
   - softpower-pipeline.tar     (Data Processing Pipeline)
   - pgvector.tar               (PostgreSQL + pgvector)
   - redis.tar                  (Redis Cache)

2. Database Backup:
   - softpower-backup.dump.gz   (Database with existing data)

3. Application Code:
   - SP_Streamlit/              (Source code and scripts)

4. Documentation:
   - SP_Streamlit/AIRGAP_INSTALL.md   (Complete installation guide)

Installation Instructions:
-------------------------
See SP_Streamlit/AIRGAP_INSTALL.md for complete step-by-step guide.

Quick Start:
-----------
1. Transfer this entire directory to air-gapped system
2. Load Docker images:
   docker load -i pgvector.tar
   docker load -i redis.tar
   docker load -i softpower-api.tar
   docker load -i softpower-dashboard.tar
   docker load -i softpower-pipeline.tar

3. Follow SP_Streamlit/AIRGAP_INSTALL.md for complete setup

System Requirements:
-------------------
- CentOS 7 (or similar RHEL-based system)
- Docker installed
- 20GB+ disk space
- 8GB+ RAM recommended

Support:
--------
For issues during installation, see troubleshooting section in AIRGAP_INSTALL.md
EOF

# Create installation checklist
cat > INSTALL_CHECKLIST.txt << 'EOF'
Air-Gapped Installation Checklist
==================================

Pre-Installation:
[ ] CentOS 7 system ready
[ ] Docker installed and running
[ ] Sufficient disk space (20GB+)
[ ] Package transferred to system

Installation Steps:
[ ] Load all 5 Docker images
[ ] Verify images with: docker images
[ ] Copy application to /opt/softpower
[ ] Create .env file with credentials
[ ] Make scripts executable: chmod +x docker/*.sh
[ ] Create network: docker network create softpower_net
[ ] Create volumes: docker volume create postgres_data redis_data
[ ] Start database: ./docker/run-database.sh
[ ] Restore database backup
[ ] Verify data: docker exec softpower_db psql -U matthew50 -d softpower-db -c "SELECT COUNT(*) FROM documents;"
[ ] Start web app: ./docker/run-webapp.sh
[ ] Test web app: curl http://localhost:8000/api/health
[ ] Configure firewall (ports 8000, 8501)
[ ] Start Streamlit (optional): ./docker/run-streamlit.sh
[ ] Start pipeline (optional): ./docker/run-pipeline.sh

Post-Installation:
[ ] All containers running: docker ps
[ ] Web app accessible in browser
[ ] Data visible in application
[ ] Set up systemd service for auto-start
[ ] Create backup schedule
[ ] Document system for operations team

Troubleshooting:
If issues occur, check:
- Docker logs: docker logs softpower_api
- SELinux: getenforce (should be Permissive or Disabled)
- Firewall: firewall-cmd --list-ports
- Disk space: df -h
- Network: docker network inspect softpower_net
EOF

echo "  ✅ Documentation created"
echo ""

cd ..

echo "📦 Step 6/6: Creating final archive..."
tar czf "${PACKAGE_NAME}.tar.gz" "$PACKAGE_NAME"
echo "  ✅ ${PACKAGE_NAME}.tar.gz created"
echo ""

# Show summary
PACKAGE_SIZE=$(du -sh "${PACKAGE_NAME}.tar.gz" | cut -f1)

echo "=============================================="
echo "✅ Air-Gapped Package Created Successfully!"
echo "=============================================="
echo ""
echo "Package: ${PACKAGE_NAME}.tar.gz"
echo "Size: $PACKAGE_SIZE"
echo ""
echo "Contents:"
echo "  • 5 Docker images (tar files)"
if [ -f "$PACKAGE_NAME/softpower-backup.dump.gz" ]; then
    echo "  • Database backup ($(du -h "$PACKAGE_NAME/softpower-backup.dump.gz" | cut -f1))"
fi
echo "  • Application source code"
echo "  • Installation documentation"
echo "  • Installation checklist"
echo ""
echo "Transfer Instructions:"
echo "  1. Copy ${PACKAGE_NAME}.tar.gz to air-gapped system"
echo "  2. Extract: tar xzf ${PACKAGE_NAME}.tar.gz"
echo "  3. Follow SP_Streamlit/AIRGAP_INSTALL.md"
echo ""
echo "Verification:"
ls -lh "${PACKAGE_NAME}.tar.gz"
echo ""
