#!/bin/bash
# ============================================
# Air-Gapped Sync - IMPORT (Air-Gapped Side)
# Applies git bundles and loads Docker images
# ============================================
#
# Usage:
#   ./docker/airgap-sync-import.sh <path-to-sync-dir>
#
# This script:
#   1. Fetches new commits from the git bundle into your local mirror
#   2. Loads any Docker images included in the sync package
#   3. Optionally pushes to the local GitHub mirror
#
# First-time setup (clone from full bundle):
#   git clone repo-full.bundle SoftPower_Analytics
#   cd SoftPower_Analytics
#   git remote rename origin bundle
#   git remote add origin <your-local-github-mirror-url>
#   git push -u origin --all

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <path-to-sync-directory>"
    echo ""
    echo "Example:"
    echo "  $0 /media/usb/_airgap_sync/20250206-143022"
    exit 1
fi

SYNC_DIR="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "=============================================="
echo "Air-Gapped Sync - IMPORT"
echo "=============================================="
echo ""

# --- Validate sync directory ---

if [ ! -f "$SYNC_DIR/sync-manifest.json" ]; then
    echo "Error: No sync-manifest.json found in $SYNC_DIR"
    echo "Are you pointing to the right directory?"
    exit 1
fi

echo "Sync manifest:"
cat "$SYNC_DIR/sync-manifest.json"
echo ""
echo ""

# --- Determine bundle type ---

BUNDLE_FILE=""
if [ -f "$SYNC_DIR/repo-full.bundle" ]; then
    BUNDLE_FILE="$SYNC_DIR/repo-full.bundle"
    BUNDLE_TYPE="full"
elif [ -f "$SYNC_DIR/repo-incremental.bundle" ]; then
    BUNDLE_FILE="$SYNC_DIR/repo-incremental.bundle"
    BUNDLE_TYPE="incremental"
else
    echo "Error: No git bundle found in $SYNC_DIR"
    exit 1
fi

echo "[1/3] Applying git bundle ($BUNDLE_TYPE)..."

# Verify the bundle is valid
if ! git bundle verify "$BUNDLE_FILE" 2>/dev/null; then
    if [ "$BUNDLE_TYPE" = "incremental" ]; then
        echo ""
        echo "Error: Bundle verification failed."
        echo "This incremental bundle requires commits you don't have."
        echo "You may need a full bundle to catch up."
        echo ""
        echo "On the connected side, run:"
        echo "  ./docker/airgap-sync-export.sh --full"
        exit 1
    else
        echo "Warning: Bundle verification returned warnings (may be OK for full bundles)"
    fi
fi

# Fetch from bundle
SOURCE_BRANCH=$(python3 -c "import json; print(json.load(open('$SYNC_DIR/sync-manifest.json'))['source_branch'])" 2>/dev/null || echo "main")

cd "$REPO_ROOT"

if [ "$BUNDLE_TYPE" = "full" ]; then
    # For full bundles, add as remote temporarily and fetch everything
    git remote add bundle "$BUNDLE_FILE" 2>/dev/null || git remote set-url bundle "$BUNDLE_FILE"
    git fetch bundle
    git merge bundle/"$SOURCE_BRANCH" --ff-only 2>/dev/null || {
        echo "  Fast-forward merge not possible. Current branch may have diverged."
        echo "  You can manually merge with: git merge bundle/$SOURCE_BRANCH"
    }
    git remote remove bundle 2>/dev/null || true
else
    # For incremental bundles, fetch directly
    git fetch "$BUNDLE_FILE" "$SOURCE_BRANCH":"$SOURCE_BRANCH" 2>/dev/null || \
    git pull "$BUNDLE_FILE" "$SOURCE_BRANCH"
fi

echo "  Git sync complete. Current HEAD: $(git rev-parse --short HEAD)"
echo ""

# --- Push to local GitHub mirror (optional) ---

echo "[2/3] Pushing to local GitHub mirror..."
LOCAL_MIRROR=$(git remote get-url origin 2>/dev/null || echo "")
if [ -n "$LOCAL_MIRROR" ] && [ "$LOCAL_MIRROR" != "$BUNDLE_FILE" ]; then
    echo "  Mirror: $LOCAL_MIRROR"
    if git push origin "$SOURCE_BRANCH" 2>/dev/null; then
        echo "  Pushed to mirror."
    else
        echo "  Warning: Push to mirror failed. You may need to push manually:"
        echo "    git push origin $SOURCE_BRANCH"
    fi
else
    echo "  No mirror remote configured. Skipping."
    echo "  To set up: git remote add origin <your-github-mirror-url>"
fi
echo ""

# --- Docker images ---

echo "[3/3] Loading Docker images..."
LOADED=0

for tarfile in "$SYNC_DIR"/*.tar.gz; do
    [ -f "$tarfile" ] || continue
    BASENAME=$(basename "$tarfile")
    # Skip non-Docker tar.gz files
    case "$BASENAME" in
        softpower-*|pgvector*|redis*)
            echo "  Loading $BASENAME..."
            gunzip -c "$tarfile" | docker load
            LOADED=$((LOADED + 1))
            ;;
    esac
done

if [ "$LOADED" -eq 0 ]; then
    echo "  No Docker images in this sync package."
else
    echo "  Loaded $LOADED Docker image(s)."
fi
echo ""

# --- Summary ---

echo "=============================================="
echo "Import complete!"
echo "=============================================="
echo ""
echo "  Branch: $SOURCE_BRANCH"
echo "  HEAD:   $(git rev-parse --short HEAD)"
echo "  Images: $LOADED loaded"
echo ""

if [ "$LOADED" -gt 0 ]; then
    echo "To restart services with updated images:"
    echo "  ./docker/stop-all.sh && ./docker/run-all.sh"
    echo ""
fi

echo "To verify:"
echo "  git log --oneline -5"
echo "  docker images | grep softpower"
echo ""
