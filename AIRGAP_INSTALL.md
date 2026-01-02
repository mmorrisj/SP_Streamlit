# Air-Gapped Installation Guide (CentOS 7)

Complete guide for deploying on air-gapped CentOS 7 systems with only Docker support.

---

## Prerequisites on Air-Gapped System

- CentOS 7
- Docker installed (via internal mirrors)
- Sufficient disk space (~20GB for images + data)
- Transfer mechanism (USB, internal network, etc.)

---

## Part 1: Prepare Transfer Package (Internet-Connected System)

### Build Docker Images

```bash
cd SP_Streamlit

# Build all images
./docker/build-all.sh

# Export images as tar files
docker save softpower-api:latest -o softpower-api.tar
docker save softpower-dashboard:latest -o softpower-dashboard.tar
docker save softpower-pipeline:latest -o softpower-pipeline.tar

# Export base images
docker pull ankane/pgvector:latest
docker pull redis:7-alpine
docker save ankane/pgvector:latest -o pgvector.tar
docker save redis:7-alpine -o redis.tar
```

### Export Database Backup

```bash
# Export your current database
docker exec softpower_db pg_dump -U matthew50 -d softpower-db -F c -f /tmp/backup.dump
docker cp softpower_db:/tmp/backup.dump ./softpower-backup.dump
gzip softpower-backup.dump
```

### Create Transfer Package

```bash
mkdir airgap-transfer
cd airgap-transfer

# Copy everything needed
cp ../softpower-*.tar .
cp ../pgvector.tar .
cp ../redis.tar .
cp ../softpower-backup.dump.gz .
cp -r ../SP_Streamlit .

# Create this installation guide
cp ../SP_Streamlit/AIRGAP_INSTALL.md .

# Verify contents
ls -lh
```

### Transfer to Air-Gapped System

```bash
# Option 1: Internal file share/transfer application
cp -r airgap-transfer /mnt/secure-transfer/
# Or use your organization's file transfer tool

# Option 2: SCP via bastion/jump host
scp -r airgap-transfer user@bastion:/approved-transfer/

# Option 3: Create archive and use secure file transfer
tar czf airgap-transfer.tar.gz airgap-transfer/
# Upload via organization's approved file transfer application
# (USB drives are NOT permitted in this environment)
```

---

## Part 2: Installation on Air-Gapped CentOS 7

### Step 1: Verify Docker Installation

```bash
# Check Docker is installed
docker --version

# If not installed, install from internal mirrors:
sudo yum install docker -y

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $(whoami)

# Log out and back in, then verify
docker ps
```

### Step 2: Load Docker Images

```bash
# Navigate to transfer package
cd /opt/airgap-transfer  # Or wherever you transferred files

# Load all images
docker load -i pgvector.tar
docker load -i redis.tar
docker load -i softpower-api.tar
docker load -i softpower-dashboard.tar
docker load -i softpower-pipeline.tar

# Verify images loaded
docker images

# Expected output:
# REPOSITORY              TAG       IMAGE ID       CREATED        SIZE
# softpower-api           latest    xxxxx          X hours ago    1.2GB
# softpower-dashboard     latest    xxxxx          X hours ago    800MB
# softpower-pipeline      latest    xxxxx          X hours ago    2.5GB
# ankane/pgvector         latest    xxxxx          X hours ago    300MB
# redis                   7-alpine  xxxxx          X hours ago    30MB
```

### Step 3: Setup Application

```bash
# Copy application to proper location
sudo mkdir -p /opt/softpower
sudo cp -r SP_Streamlit/* /opt/softpower/
cd /opt/softpower

# Make scripts executable
chmod +x docker/*.sh

# Create .env file
cp .env.example .env

# Edit with your credentials
vi .env
# Set at minimum:
# POSTGRES_USER=matthew50
# POSTGRES_PASSWORD=your_secure_password
# POSTGRES_DB=softpower-db
# CLAUDE_KEY=your_openai_key (if needed)
```

### Step 4: Create Network and Volumes

```bash
# Create Docker network
docker network create softpower_net

# Create volumes
docker volume create postgres_data
docker volume create redis_data
```

### Step 5: Start Services

```bash
cd /opt/softpower

# Start database services
./docker/run-database.sh

# Wait for database to be ready (30 seconds)
sleep 30

# Verify database is running
docker ps | grep softpower_db
docker exec softpower_db pg_isready -U matthew50
```

### Step 6: Restore Database from Backup

```bash
# Copy backup file to accessible location
cp /opt/airgap-transfer/softpower-backup.dump.gz /opt/softpower/

# Decompress
gunzip softpower-backup.dump.gz

# Copy into database container
docker cp softpower-backup.dump softpower_db:/tmp/

# Restore data
docker exec softpower_db pg_restore \
  -U matthew50 \
  -d softpower-db \
  --clean \
  --if-exists \
  -v \
  /tmp/backup.dump

# Verify data loaded
docker exec softpower_db psql -U matthew50 -d softpower-db -c "SELECT COUNT(*) FROM documents;"
# Should show: 496783
```

### Step 7: Start Application Services

```bash
# Start web app
./docker/run-webapp.sh

# Wait for startup (30 seconds)
sleep 30

# Verify web app is running
curl http://localhost:8000/api/health
# Should return: {"status":"healthy",...}

# Start Streamlit (optional)
./docker/run-streamlit.sh

# Start pipeline worker (optional)
./docker/run-pipeline.sh
```

### Step 8: Verify Deployment

```bash
# Check all containers are running
docker ps

# Expected output:
# CONTAINER ID   IMAGE                    STATUS    PORTS                    NAMES
# xxxxx          softpower-pipeline       Up        -                        softpower_pipeline
# xxxxx          softpower-dashboard      Up        0.0.0.0:8501->8501/tcp   softpower_dashboard
# xxxxx          softpower-api            Up        0.0.0.0:8000->8000/tcp   softpower_api
# xxxxx          redis:7-alpine           Up        0.0.0.0:6379->6379/tcp   softpower_redis
# xxxxx          ankane/pgvector          Up        0.0.0.0:5432->5432/tcp   softpower_db

# Check logs
docker logs softpower_api
docker logs softpower_db

# Test web app
curl http://localhost:8000/api/health
curl http://localhost:8000/docs

# If you have a browser on the system
# Navigate to: http://localhost:8000
```

---

## CentOS 7 Specific Considerations

### SELinux

If SELinux is enabled and causing issues:

```bash
# Check SELinux status
getenforce

# If Enforcing, you may need to adjust policies
# Option 1: Set to permissive (not recommended for production)
sudo setenforce 0

# Option 2: Add proper SELinux contexts
sudo chcon -Rt svirt_sandbox_file_t /opt/softpower
```

### Firewall Configuration

```bash
# Check firewall status
sudo systemctl status firewalld

# Open required ports
sudo firewall-cmd --permanent --add-port=8000/tcp    # Web app
sudo firewall-cmd --permanent --add-port=8501/tcp    # Streamlit
sudo firewall-cmd --permanent --add-port=5432/tcp    # PostgreSQL (optional)
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-ports
```

### Storage Configuration

CentOS 7 may have limited `/var` space by default:

```bash
# Check disk space
df -h

# If /var is full, you can move Docker's data directory
# 1. Stop Docker
sudo systemctl stop docker

# 2. Create new directory on larger partition
sudo mkdir -p /opt/docker

# 3. Edit Docker daemon config
sudo vi /etc/docker/daemon.json
# Add:
{
  "data-root": "/opt/docker"
}

# 4. Copy existing data
sudo rsync -aP /var/lib/docker/ /opt/docker/

# 5. Restart Docker
sudo systemctl start docker

# 6. Verify
docker info | grep "Docker Root Dir"
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs softpower_api

# Check if port is already in use
sudo netstat -tlnp | grep 8000

# Check Docker daemon logs
sudo journalctl -u docker -f
```

### Database Restore Fails

```bash
# Check PostgreSQL logs
docker logs softpower_db

# Try restore with verbose output
docker exec softpower_db pg_restore \
  -U matthew50 \
  -d softpower-db \
  --clean \
  --if-exists \
  -v \
  /tmp/backup.dump 2>&1 | tee restore.log

# If specific errors, you can restore without --clean
docker exec softpower_db pg_restore \
  -U matthew50 \
  -d softpower-db \
  -v \
  /tmp/backup.dump
```

### Network Issues

```bash
# Verify network exists
docker network ls | grep softpower_net

# Recreate if needed
docker network rm softpower_net
docker network create softpower_net

# Reconnect containers
docker network connect softpower_net softpower_db
docker network connect softpower_net softpower_api
```

### Permission Issues

```bash
# Ensure proper permissions
sudo chown -R $(whoami):$(whoami) /opt/softpower

# Ensure Docker socket accessible
sudo chmod 666 /var/run/docker.sock

# Or add user to docker group (better)
sudo usermod -aG docker $(whoami)
# Log out and back in
```

---

## System Service (Auto-start on Boot)

Create systemd service for auto-start:

```bash
# Create service file
sudo vi /etc/systemd/system/softpower.service
```

```ini
[Unit]
Description=Soft Power Analytics Stack
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/softpower
ExecStart=/opt/softpower/docker/run-all.sh
ExecStop=/opt/softpower/docker/stop-all.sh
User=root

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable softpower
sudo systemctl start softpower

# Check status
sudo systemctl status softpower
```

---

## Maintenance

### View Logs

```bash
# Application logs
docker logs -f softpower_api

# Database logs
docker logs -f softpower_db

# All logs
docker logs -f softpower_api softpower_db softpower_redis
```

### Backup Database

```bash
# Create backup
docker exec softpower_db pg_dump \
  -U matthew50 \
  -d softpower-db \
  -F c \
  -f /tmp/backup-$(date +%Y%m%d).dump

# Copy out
docker cp softpower_db:/tmp/backup-$(date +%Y%m%d).dump /opt/backups/
```

### Update Application

To update the application with new images:

```bash
# 1. Get new tar files from internet-connected system
# 2. Load new images
docker load -i softpower-api-new.tar

# 3. Stop old containers
./docker/stop-all.sh

# 4. Start with new images
./docker/run-all.sh
```

### Stop All Services

```bash
cd /opt/softpower
./docker/stop-all.sh
```

### Remove Everything (Clean Slate)

```bash
# Stop all
./docker/stop-all.sh

# Remove containers
docker rm softpower_api softpower_dashboard softpower_pipeline softpower_db softpower_redis

# Remove images
docker rmi softpower-api softpower-dashboard softpower-pipeline ankane/pgvector redis:7-alpine

# WARNING: This deletes all data
docker volume rm postgres_data redis_data

# Remove network
docker network rm softpower_net
```

---

## Verification Checklist

- [ ] Docker installed and running
- [ ] All 5 Docker images loaded
- [ ] Network `softpower_net` created
- [ ] Volumes created: `postgres_data`, `redis_data`
- [ ] Database container running
- [ ] Database has 496K documents
- [ ] Web app running on port 8000
- [ ] Streamlit running on port 8501 (optional)
- [ ] Pipeline worker running (optional)
- [ ] Firewall allows ports 8000, 8501
- [ ] Can access web app from browser

---

## Support Information

**Installed Location**: `/opt/softpower`
**Container Names**:
- `softpower_db` (PostgreSQL)
- `softpower_redis` (Redis)
- `softpower_api` (Web App)
- `softpower_dashboard` (Streamlit)
- `softpower_pipeline` (Pipeline Worker)

**Network**: `softpower_net`
**Volumes**: `postgres_data`, `redis_data`
**Ports**: 8000 (Web), 8501 (Streamlit), 5432 (DB), 6379 (Redis)
