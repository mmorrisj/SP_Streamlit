# Air-Gapped Deployment with Internal Container Registry

Complete guide for deploying on air-gapped CentOS 7 systems with internal container registry and security scanning requirements.

---

## Overview

This deployment method is designed for highly secure, air-gapped environments where:
- Direct internet access is not available
- All container images must be scanned for security vulnerabilities
- Images must be approved by security team before deployment
- Only Docker is available (no Docker Compose)

**Deployment Workflow**:
1. Build images on internet-connected system
2. Export images as tar files
3. Transfer to air-gapped system via approved method
4. Load images into local Docker
5. Push images to internal container registry
6. Wait for automated security scanning
7. Security team reviews and approves
8. Deploy from approved registry images

---

## Prerequisites

### Internet-Connected Build System

- Docker installed
- Git access to repository
- Sufficient disk space (~30GB)
- Access to transfer mechanism (USB, secure file transfer)

### Air-Gapped Target System

- **OS**: CentOS 7 (or compatible RHEL 7)
- **Docker**: Installed via internal mirrors
- **Container Registry**: Internal registry accessible (e.g., registry.your-company.mil)
- **Registry Access**: Credentials for pushing/pulling images
- **Disk Space**: ~20GB for images + data
- **Network**: Access to internal container registry
- **Permissions**: Ability to run Docker commands

### Required Information

Before starting, gather:
- **Registry URL**: `registry.your-company.mil` (example)
- **Project/Namespace**: `softpower` (example)
- **Registry Credentials**: Username and password
- **Security Team Contact**: For approval process
- **Transfer Method**: USB, SCP, internal file share

---

## Part 1: Build Images (Internet-Connected System)

### Step 1: Clone Repository and Prepare

```bash
cd SP_Streamlit

# Ensure you have latest code
git pull origin main

# Make build scripts executable
chmod +x docker/*.sh
```

### Step 2: Build All Docker Images

```bash
# Build all images
./docker/build-all.sh

# Verify images were created
docker images | grep softpower
```

Expected output:
```
REPOSITORY              TAG       IMAGE ID       CREATED         SIZE
softpower-api           latest    xxxxx          2 minutes ago   1.2GB
softpower-dashboard     latest    xxxxx          3 minutes ago   800MB
softpower-pipeline      latest    xxxxx          5 minutes ago   2.5GB
```

### Step 3: Pull Base Images

```bash
# Pull PostgreSQL with pgvector
docker pull ankane/pgvector:latest

# Pull Redis
docker pull redis:7-alpine

# Verify
docker images | grep -E "pgvector|redis"
```

### Step 4: Export Images as Tar Files

```bash
# Create export directory
mkdir -p airgap-transfer/images

# Export application images
docker save softpower-api:latest -o airgap-transfer/images/softpower-api.tar
docker save softpower-dashboard:latest -o airgap-transfer/images/softpower-dashboard.tar
docker save softpower-pipeline:latest -o airgap-transfer/images/softpower-pipeline.tar

# Export base images
docker save ankane/pgvector:latest -o airgap-transfer/images/pgvector.tar
docker save redis:7-alpine -o airgap-transfer/images/redis.tar

# Verify tar files
ls -lh airgap-transfer/images/
```

Expected sizes:
- `softpower-api.tar`: ~1.2GB
- `softpower-dashboard.tar`: ~800MB
- `softpower-pipeline.tar`: ~2.5GB
- `pgvector.tar`: ~300MB
- `redis.tar`: ~30MB
- **Total**: ~5GB

### Step 5: Package Application Code and Scripts

```bash
cd SP_Streamlit

# Copy deployment scripts
cp -r docker airgap-transfer/
cp -r shared airgap-transfer/
cp -r alembic airgap-transfer/
cp alembic.ini airgap-transfer/

# Copy configuration
cp .env.example airgap-transfer/
cp AIRGAP_REGISTRY.md airgap-transfer/

# Copy database backup (if needed)
# docker exec softpower_db pg_dump -U matthew50 -d softpower-db -F c -f /tmp/backup.dump
# docker cp softpower_db:/tmp/backup.dump airgap-transfer/softpower-backup.dump
# gzip airgap-transfer/softpower-backup.dump
```

### Step 6: Create Transfer Archive

```bash
# Create single archive
tar czf airgap-softpower-$(date +%Y%m%d).tar.gz airgap-transfer/

# Verify archive
ls -lh airgap-softpower-*.tar.gz

# Calculate checksum for integrity verification
sha256sum airgap-softpower-*.tar.gz > airgap-softpower-$(date +%Y%m%d).sha256
```

### Step 7: Transfer to Air-Gapped System

Use your organization's approved file transfer application:

**Option 1: Internal File Share/Transfer Application**
```bash
# Copy to approved file transfer location
cp airgap-softpower-*.tar.gz /mnt/secure-transfer/
cp airgap-softpower-*.sha256 /mnt/secure-transfer/

# Or use your organization's file transfer tool
# Example: Accellion, MOVEit, or similar secure file transfer
```

**Option 2: SCP via Bastion/Jump Host**
```bash
# Transfer via bastion host
scp airgap-softpower-*.tar.gz user@bastion.company.mil:/approved-transfer/
scp airgap-softpower-*.sha256 user@bastion.company.mil:/approved-transfer/

# From bastion to air-gapped system
scp airgap-softpower-*.tar.gz airgap-user@airgap-system:/tmp/
```

**Option 3: Organization's Secure File Transfer Application**
```bash
# Use your organization's approved file transfer tool
# Common tools: Accellion, MOVEit, Citrix ShareFile, etc.
#
# 1. Upload to transfer application web portal
# 2. Download from air-gapped system's transfer portal
# 3. Or use CLI if available

# Example with generic transfer CLI:
transfer-tool upload airgap-softpower-*.tar.gz
transfer-tool upload airgap-softpower-*.sha256
```

**Important Notes**:
- USB drives are NOT permitted in this environment
- Use only approved file transfer applications
- Ensure checksum file (.sha256) is transferred with the archive
- Verify file integrity after transfer using checksum

---

## Part 2: Load Images (Air-Gapped CentOS 7)

### Step 1: Verify Docker Installation

```bash
# Check Docker version
docker --version

# If not installed, install from internal mirrors
sudo yum install docker -y

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $(whoami)

# Log out and back in, then verify
docker ps
```

### Step 2: Extract Transfer Package

```bash
# Navigate to transfer location
cd /tmp  # Or wherever you transferred files

# Verify checksum
sha256sum -c airgap-softpower-20241106.sha256

# Extract archive
tar xzf airgap-softpower-20241106.tar.gz

# Navigate to extracted directory
cd airgap-transfer
```

### Step 3: Load Docker Images

```bash
# Load all images
cd images

docker load -i pgvector.tar
docker load -i redis.tar
docker load -i softpower-api.tar
docker load -i softpower-dashboard.tar
docker load -i softpower-pipeline.tar

# Verify images loaded
docker images
```

Expected output:
```
REPOSITORY              TAG       IMAGE ID       CREATED        SIZE
softpower-api           latest    xxxxx          X hours ago    1.2GB
softpower-dashboard     latest    xxxxx          X hours ago    800MB
softpower-pipeline      latest    xxxxx          X hours ago    2.5GB
ankane/pgvector         latest    xxxxx          X hours ago    300MB
redis                   7-alpine  xxxxx          X hours ago    30MB
```

### Step 4: Setup Application Files

```bash
# Create installation directory
sudo mkdir -p /opt/softpower
sudo chown -R $(whoami):$(whoami) /opt/softpower

# Copy application files
cd ..  # Back to airgap-transfer directory
cp -r docker /opt/softpower/
cp -r shared /opt/softpower/
cp -r alembic /opt/softpower/
cp alembic.ini /opt/softpower/

# Make scripts executable
chmod +x /opt/softpower/docker/*.sh

# Create .env file
cp .env.example /opt/softpower/.env

# Edit with your credentials
vi /opt/softpower/.env
```

---

## Part 3: Push to Internal Container Registry

### Step 1: Configure Registry Settings

```bash
cd /opt/softpower

# Set registry environment variables
export REGISTRY="registry.your-company.mil"  # Your registry URL
export PROJECT="softpower"                    # Your project namespace

# Or edit docker/push-to-registry.sh to set defaults
vi docker/push-to-registry.sh
# Update REGISTRY and PROJECT variables
```

### Step 2: Login to Container Registry

```bash
# Login to your internal registry
docker login registry.your-company.mil

# Enter credentials when prompted
# Username: your-username
# Password: your-password

# Verify login succeeded
cat ~/.docker/config.json
```

### Step 3: Push Images to Registry

```bash
# Run push script
./docker/push-to-registry.sh
```

**What this script does**:
1. Tags all 5 images for your registry:
   - `registry.your-company.mil/softpower/pgvector:latest`
   - `registry.your-company.mil/softpower/redis:7-alpine`
   - `registry.your-company.mil/softpower/api:latest`
   - `registry.your-company.mil/softpower/dashboard:latest`
   - `registry.your-company.mil/softpower/pipeline:latest`

2. Pushes each image to registry
3. Registry automatically triggers security scanning

Expected output:
```
🔐 Step 1: Docker registry login
Login Succeeded

🏷️  Step 2: Tagging images for registry...
  ✅ Tagged: registry.your-company.mil/softpower/pgvector:latest
  ✅ Tagged: registry.your-company.mil/softpower/redis:7-alpine
  ✅ Tagged: registry.your-company.mil/softpower/api:latest
  ✅ Tagged: registry.your-company.mil/softpower/dashboard:latest
  ✅ Tagged: registry.your-company.mil/softpower/pipeline:latest

📤 Step 3: Pushing images to registry...
(This will trigger security scanning)

The push refers to repository [registry.your-company.mil/softpower/api]
...
  ✅ Pushed: api

✅ All Images Pushed to Registry
```

---

## Part 4: Security Scanning and Approval

### Step 1: Wait for Security Scans

After pushing images, the container registry automatically scans for vulnerabilities.

**Check scan status**:
- Access your registry web UI: `https://registry.your-company.mil`
- Navigate to `softpower` project
- View scan results for each image

**Scan checks for**:
- Known CVEs (Common Vulnerabilities and Exposures)
- Outdated packages with security issues
- Malware signatures
- Configuration issues

**Typical scan time**: 5-30 minutes per image

### Step 2: Review Scan Results

**Common findings and remediation**:

| Finding | Severity | Remediation |
|---------|----------|-------------|
| CVE in base Python packages | Medium | Update Python base image version |
| Outdated npm packages | Low-Medium | Run `npm audit fix` and rebuild |
| PostgreSQL CVE | High | Update pgvector base image |
| Missing security headers | Low | Add to FastAPI configuration |

**Severity levels**:
- 🔴 **Critical**: Must fix before deployment
- 🟠 **High**: Should fix or get security exception
- 🟡 **Medium**: Review and document
- 🟢 **Low**: Acceptable risk

### Step 3: Address Security Findings

If critical/high findings are discovered:

**Option A: Fix and Rebuild**
```bash
# On internet-connected system:
# 1. Update Dockerfiles to fix vulnerabilities
# 2. Rebuild images
./docker/build-all.sh

# 3. Re-export and transfer to air-gapped system
docker save softpower-api:latest -o softpower-api-fixed.tar

# 4. On air-gapped system, reload and re-push
docker load -i softpower-api-fixed.tar
./docker/push-to-registry.sh
```

**Option B: Request Security Exception**
- Document why vulnerability is not exploitable
- Submit exception request to security team
- Wait for approval

### Step 4: Get Approval

**Contact your security team**:
```
To: security-team@your-company.mil
Subject: Container Image Approval Request - Soft Power Analytics

Project: softpower
Registry: registry.your-company.mil
Images:
  - softpower/api:latest
  - softpower/dashboard:latest
  - softpower/pipeline:latest
  - softpower/pgvector:latest
  - softpower/redis:7-alpine

Scan results reviewed. [No critical findings / Exception requested for CVE-XXXX]

Please approve for production deployment.
```

**Wait for approval** - typically 1-5 business days depending on organization

---

## Part 5: Deploy from Approved Registry Images

Once images are approved by security team:

### Step 1: Verify Images are Approved

```bash
# Check registry UI or CLI
docker pull registry.your-company.mil/softpower/api:latest

# Should succeed without errors
```

### Step 2: Create Network and Volumes

```bash
cd /opt/softpower

# Create Docker network
docker network create softpower_net

# Create volumes
docker volume create postgres_data
docker volume create redis_data
```

### Step 3: Configure Environment

```bash
# Edit .env file with production credentials
vi .env
```

Required settings:
```bash
# Database
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=softpower-db
DB_HOST=softpower_db
DB_PORT=5432

# AI/ML (if needed)
CLAUDE_KEY=your_api_key_here

# Registry
REGISTRY=registry.your-company.mil
PROJECT=softpower
```

### Step 4: Deploy Full Stack

```bash
# Run deployment from registry
./docker/run-all-registry.sh
```

**What this script does**:
1. Pulls all 5 approved images from registry
2. Tags them for local use
3. Creates network and volumes
4. Starts PostgreSQL + Redis
5. Runs database migrations
6. Starts web app (React + FastAPI)
7. Starts Streamlit dashboard
8. Starts pipeline worker

### Step 5: Verify Deployment

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

# Check web app health
curl http://localhost:8000/api/health

# Should return: {"status":"healthy",...}

# Check logs
docker logs softpower_api
docker logs softpower_db
```

### Step 6: Restore Database Backup (if needed)

If you transferred a database backup:

```bash
# Decompress backup
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
```

### Step 7: Configure Firewall

```bash
# Open required ports
sudo firewall-cmd --permanent --add-port=8000/tcp    # Web app
sudo firewall-cmd --permanent --add-port=8501/tcp    # Streamlit
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-ports
```

### Step 8: Access Application

**From local system**:
- Web App: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Streamlit: http://localhost:8501

**From other systems** (if firewall allows):
- Web App: http://airgap-hostname:8000
- Streamlit: http://airgap-hostname:8501

---

## CentOS 7 Specific Considerations

### SELinux Configuration

If SELinux causes container issues:

```bash
# Check SELinux status
getenforce

# Option 1: Set to permissive (for testing only)
sudo setenforce 0

# Option 2: Add proper SELinux contexts (recommended)
sudo chcon -Rt svirt_sandbox_file_t /opt/softpower

# Option 3: Create custom policy (most secure)
# Work with your system administrator
```

### Docker Storage Driver

CentOS 7 uses `devicemapper` by default. For better performance:

```bash
# Check current driver
docker info | grep "Storage Driver"

# If using devicemapper, consider switching to overlay2
sudo vi /etc/docker/daemon.json
```

```json
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true"
  ]
}
```

```bash
# Restart Docker
sudo systemctl restart docker
```

### Limited /var Space

If `/var` partition is small:

```bash
# Check disk space
df -h

# Move Docker data directory to larger partition
sudo systemctl stop docker
sudo mkdir -p /opt/docker
sudo vi /etc/docker/daemon.json
```

```json
{
  "data-root": "/opt/docker"
}
```

```bash
# Copy existing data
sudo rsync -aP /var/lib/docker/ /opt/docker/

# Restart Docker
sudo systemctl start docker

# Verify new location
docker info | grep "Docker Root Dir"
```

---

## Maintenance and Updates

### View Logs

```bash
# Application logs
docker logs -f softpower_api

# Database logs
docker logs -f softpower_db

# Pipeline logs
docker logs -f softpower_pipeline

# All logs since yesterday
docker logs --since 24h softpower_api
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

# Compress
gzip /opt/backups/backup-$(date +%Y%m%d).dump
```

### Update Application

When new version is available:

```bash
# 1. On internet-connected system: Build new images
./docker/build-all.sh

# 2. Export new images
docker save softpower-api:latest -o softpower-api-v2.tar
# ... export other images

# 3. Transfer to air-gapped system

# 4. Load new images
docker load -i softpower-api-v2.tar

# 5. Push to registry
./docker/push-to-registry.sh

# 6. Wait for security scan and approval

# 7. Stop old containers
docker stop softpower_api softpower_dashboard softpower_pipeline

# 8. Deploy new version
./docker/run-all-registry.sh
```

### Stop All Services

```bash
cd /opt/softpower
./docker/stop-all.sh
```

### Restart Services

```bash
# Restart individual service
docker restart softpower_api

# Or restart all
./docker/stop-all.sh
./docker/run-all-registry.sh
```

---

## Troubleshooting

### Registry Login Fails

```bash
# Error: unauthorized: authentication required

# Solution 1: Verify credentials
docker login registry.your-company.mil
# Re-enter username and password

# Solution 2: Check registry is accessible
ping registry.your-company.mil
curl https://registry.your-company.mil

# Solution 3: Verify certificate trust
# Add registry CA certificate to system trust store
sudo cp registry-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### Image Pull Fails

```bash
# Error: manifest unknown: manifest unknown

# Solution: Verify image exists in registry
curl -u username:password https://registry.your-company.mil/v2/softpower/api/tags/list

# Check exact image name
docker pull registry.your-company.mil/softpower/api:latest
```

### Container Won't Start

```bash
# Check logs for errors
docker logs softpower_api

# Common issues:

# 1. Port already in use
sudo netstat -tlnp | grep 8000
# Kill process or use different port

# 2. Database not ready
docker logs softpower_db
# Wait longer or check database health

# 3. Environment variables missing
docker exec softpower_api env | grep DATABASE_URL
# Verify .env file is loaded
```

### Database Connection Errors

```bash
# Verify database is running
docker ps | grep softpower_db

# Test connection
docker exec softpower_db pg_isready -U matthew50

# Check database logs
docker logs softpower_db

# Verify network
docker network inspect softpower_net
```

### Security Scan Never Completes

**Possible causes**:
1. Registry scanner service down - contact registry admin
2. Image too large - check registry limits
3. Network issue - verify registry connectivity

**Solutions**:
```bash
# Check registry status page
curl https://registry.your-company.mil/api/health

# Contact registry administrators
# Check for maintenance windows or known issues
```

### Out of Disk Space

```bash
# Check disk usage
df -h

# Clean up Docker
docker system prune -a  # WARNING: removes unused images/containers
docker volume prune     # WARNING: removes unused volumes

# Remove old images
docker images
docker rmi <old-image-id>
```

---

## Security Best Practices

### Credentials Management

```bash
# DO NOT commit .env file to git
echo ".env" >> .gitignore

# Use strong passwords
# Generate with: openssl rand -base64 32

# Rotate credentials regularly
# Update .env and restart containers
```

### Network Security

```bash
# Restrict PostgreSQL to Docker network only
# Remove port mapping in production:
# Edit docker/run-database.sh
# Remove: -p 5432:5432

# Use firewall rules
sudo firewall-cmd --permanent --add-rich-rule='
  rule family="ipv4"
  source address="10.0.0.0/8"
  port protocol="tcp" port="8000"
  accept'
```

### Container Security

```bash
# Run containers with read-only filesystem (where possible)
docker run --read-only ...

# Drop capabilities
docker run --cap-drop=ALL --cap-add=CHOWN ...

# Use non-root user
# Already configured in Dockerfiles

# Scan running containers
docker scan softpower-api
```

### Audit Logging

```bash
# Enable Docker event logging
sudo vi /etc/docker/daemon.json
```

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

---

## Registry Workflow Reference

**Quick reference for the complete workflow**:

| Step | Location | Command | Time |
|------|----------|---------|------|
| 1. Build | Internet System | `./docker/build-all.sh` | 15 min |
| 2. Export | Internet System | `docker save ... -o *.tar` | 10 min |
| 3. Transfer | Physical/Network | Varies | 1-24 hours |
| 4. Load | Air-Gap System | `docker load -i *.tar` | 5 min |
| 5. Push to Registry | Air-Gap System | `./docker/push-to-registry.sh` | 10 min |
| 6. Security Scan | Automatic | Wait | 30-60 min |
| 7. Review | Security Team | Manual | 1-5 days |
| 8. Approve | Security Team | Manual | - |
| 9. Deploy | Air-Gap System | `./docker/run-all-registry.sh` | 5 min |

**Total time**: 1-5 business days (mostly waiting for approval)

---

## Verification Checklist

Before considering deployment complete:

- [ ] Docker installed and running on CentOS 7
- [ ] All 5 images loaded successfully
- [ ] Registry login successful
- [ ] All images pushed to internal registry
- [ ] Security scans completed (no critical findings)
- [ ] Security team approval received
- [ ] Images pulled from approved registry
- [ ] Network `softpower_net` created
- [ ] Volumes created: `postgres_data`, `redis_data`
- [ ] Database container running
- [ ] Database migrations completed
- [ ] Web app running on port 8000
- [ ] Streamlit running on port 8501
- [ ] Pipeline worker running
- [ ] Firewall configured (ports 8000, 8501)
- [ ] Can access web app from browser
- [ ] Data restored (if applicable)
- [ ] Logs look healthy (no errors)

---

## Support Information

**Installed Location**: `/opt/softpower`

**Container Names**:
- `softpower_db` (PostgreSQL with pgvector)
- `softpower_redis` (Redis cache)
- `softpower_api` (React + FastAPI web app)
- `softpower_dashboard` (Streamlit analytics)
- `softpower_pipeline` (Data processing worker)

**Network**: `softpower_net`

**Volumes**:
- `postgres_data` (database storage)
- `redis_data` (cache storage)

**Ports**:
- 8000: React web app + FastAPI
- 8501: Streamlit dashboard
- 5432: PostgreSQL (optional, for direct access)
- 6379: Redis (internal)

**Registry Images**:
- `registry.your-company.mil/softpower/api:latest`
- `registry.your-company.mil/softpower/dashboard:latest`
- `registry.your-company.mil/softpower/pipeline:latest`
- `registry.your-company.mil/softpower/pgvector:latest`
- `registry.your-company.mil/softpower/redis:7-alpine`

**Key Scripts**:
- `docker/push-to-registry.sh` - Push images to registry
- `docker/run-all-registry.sh` - Deploy from registry
- `docker/stop-all.sh` - Stop all services
- `docker/build-all.sh` - Build images (internet system only)

---

## Next Steps

After successful deployment:

1. **Configure backups**: Set up automated database backups
2. **Monitor resources**: Set up monitoring for CPU, memory, disk
3. **Document configuration**: Record your specific registry URLs, project names
4. **Train users**: Provide access and training to end users
5. **Plan updates**: Establish process for future updates
6. **Test disaster recovery**: Practice restore from backup

---

## Additional Resources

- [AIRGAP_INSTALL.md](AIRGAP_INSTALL.md) - Air-gapped deployment without registry
- [STANDALONE_DOCKER.md](docs/deployment/STANDALONE_DOCKER.md) - Standalone Docker commands reference
- [FULL_STACK.md](docs/deployment/FULL_STACK.md) - Full stack Docker Compose guide (non-air-gapped)
- [client/README.md](client/README.md) - Web application documentation
- [CLAUDE.md](CLAUDE.md) - Complete project architecture and development guide
