# Air-Gapped Repository Sync Guide

Efficient workflow for keeping an air-gapped deployment in sync with the development repo.

## How It Works

The sync system uses **git bundles** -- binary files that contain git objects and refs. They act like a portable, offline git remote. Incremental bundles contain only new commits since the last sync, making transfers fast (typically KB instead of MB).

```
Connected Network                    Air-Gapped Network
┌──────────────┐    USB/media     ┌────────────────────┐
│  Dev repo     │  ──────────>    │  Local git clone    │
│  (GitHub)     │  git bundle     │       │             │
│               │  + optional     │       ▼             │
│               │  Docker images  │  GitHub mirror      │
└──────────────┘                  └────────────────────┘
```

## Quick Reference

```bash
# Connected side: create sync package
./docker/airgap-sync-export.sh              # Incremental (just new commits)
./docker/airgap-sync-export.sh --full       # Full repo (first time / recovery)
./docker/airgap-sync-export.sh --docker     # Include rebuilt Docker images

# Transfer _airgap_sync/<timestamp>/ to air-gapped network via USB/media

# Air-gapped side: apply sync package
./docker/airgap-sync-import.sh /media/usb/_airgap_sync/20250206-143022
```

## Initial Setup

### Step 1: Create First Full Bundle (Connected Side)

```bash
./docker/airgap-sync-export.sh --full --docker
```

This creates `_airgap_sync/<timestamp>/` containing:
- `repo-full.bundle` -- entire git history (~11MB)
- `softpower-*.tar.gz` -- Docker images (if `--docker` used)
- `sync-manifest.json` -- metadata

### Step 2: Transfer to Air-Gapped Network

Copy the `_airgap_sync/<timestamp>/` directory to removable media.

### Step 3: Bootstrap the Repo (Air-Gapped Side, First Time Only)

```bash
# Clone from the full bundle
git clone /media/usb/_airgap_sync/20250206-143022/repo-full.bundle SoftPower_Analytics
cd SoftPower_Analytics

# Clean up the automatic "bundle" remote, point origin to your mirror
git remote rename origin bundle
git remote remove bundle
git remote add origin https://your-airgap-github/org/SoftPower_Analytics.git

# Push all branches to the mirror
git push -u origin --all
git push origin --tags
```

### Step 4: Load Docker Images (Air-Gapped Side, First Time Only)

```bash
# If Docker images were included
for f in /media/usb/_airgap_sync/20250206-143022/*.tar.gz; do
    gunzip -c "$f" | docker load
done

# Verify
docker images | grep -E "softpower|pgvector|redis"
```

## Ongoing Sync Workflow

### On the Connected Side

```bash
# After making changes and committing...
./docker/airgap-sync-export.sh
```

This detects the last sync point automatically (stored in `_airgap_sync/.last-sync-ref`) and bundles only new commits. Typical output size: a few KB to a few hundred KB.

### Transfer

Copy `_airgap_sync/<timestamp>/` to removable media. Only the latest timestamp directory is needed.

### On the Air-Gapped Side

```bash
./docker/airgap-sync-import.sh /media/usb/_airgap_sync/20250206-153000
```

This:
1. Fetches new commits from the bundle
2. Fast-forward merges your local branch
3. Pushes to the local GitHub mirror (if configured)
4. Loads any included Docker images

## When to Include Docker Images

Docker images are large (hundreds of MB each). Only include them when:

- **First deployment** (`--full --docker`)
- **Dockerfile changed** (rebuild needed)
- **requirements.txt changed** (Python deps)
- **package.json changed** (Node.js deps)
- **Base image update needed** (security patches)

For code-only changes (Python, JS, templates, configs), the git bundle alone is sufficient. The running containers mount or copy the source code.

## Sync Scenarios

### Regular Code Update (Most Common)
```bash
# Connected side
./docker/airgap-sync-export.sh
# Transfer, then air-gapped side
./docker/airgap-sync-import.sh <path>
```
Size: ~KB. Transfer time: seconds.

### Dependency Update
```bash
# Connected side
./docker/airgap-sync-export.sh --docker
# Transfer, then air-gapped side
./docker/airgap-sync-import.sh <path>
./docker/stop-all.sh && ./docker/run-all.sh  # Restart with new images
```
Size: ~hundreds of MB. Transfer time: minutes.

### Recovery / Fresh Install
```bash
# Connected side
./docker/airgap-sync-export.sh --full --docker
# Transfer, then air-gapped side: follow Initial Setup steps above
```

### Database Backup Transfer
Use the existing `docker/airgap-package.sh` for database dumps, or run separately:
```bash
# Connected side: export DB
docker exec softpower_db pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -F c -f /tmp/backup.dump
docker cp softpower_db:/tmp/backup.dump ./softpower-backup.dump

# Air-gapped side: restore DB
docker cp softpower-backup.dump softpower_db:/tmp/backup.dump
docker exec softpower_db pg_restore -U $POSTGRES_USER -d $POSTGRES_DB -c /tmp/backup.dump
```

## File Structure

```
_airgap_sync/
├── .last-sync-ref              # Tracks last exported commit (auto-managed)
├── 20250206-143022/            # Full initial sync
│   ├── repo-full.bundle
│   ├── sync-manifest.json
│   ├── softpower-api.tar.gz
│   ├── softpower-dashboard.tar.gz
│   ├── softpower-pipeline.tar.gz
│   ├── pgvector.tar.gz
│   └── redis.tar.gz
├── 20250207-091500/            # Incremental code-only
│   ├── repo-incremental.bundle
│   └── sync-manifest.json
└── 20250210-140000/            # Incremental + Docker rebuild
    ├── repo-incremental.bundle
    ├── sync-manifest.json
    └── softpower-api.tar.gz
```

## Troubleshooting

**"Bundle verification failed" on import**
The incremental bundle requires commits your local repo doesn't have. Create a full bundle on the connected side:
```bash
./docker/airgap-sync-export.sh --full
```

**"No new commits since last sync"**
Nothing to sync. The export script exits cleanly. Use `--full` to force a full bundle if needed.

**Mirror push fails**
Check that `git remote -v` shows the correct mirror URL:
```bash
git remote set-url origin https://your-airgap-github/org/SoftPower_Analytics.git
git push origin main
```

**Sync marker out of date**
Delete the marker to force a full bundle:
```bash
rm _airgap_sync/.last-sync-ref
./docker/airgap-sync-export.sh
```
