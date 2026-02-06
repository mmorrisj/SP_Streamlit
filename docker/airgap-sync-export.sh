#!/bin/bash
# ============================================
# Air-Gapped Sync - EXPORT (Connected Side)
# Creates incremental git bundles for transfer
# ============================================
#
# Usage:
#   ./docker/airgap-sync-export.sh                  # Incremental bundle (commits since last sync)
#   ./docker/airgap-sync-export.sh --full            # Full bundle (entire repo history)
#   ./docker/airgap-sync-export.sh --docker          # Include Docker images
#   ./docker/airgap-sync-export.sh --docker --full   # Full bundle + Docker images
#
# Output goes to: _airgap_sync/<timestamp>/
# Transfer that directory to the air-gapped network.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT_DIR="_airgap_sync/${TIMESTAMP}"
MARKER_FILE="_airgap_sync/.last-sync-ref"
INCLUDE_DOCKER=false
FULL_BUNDLE=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --docker)  INCLUDE_DOCKER=true ;;
        --full)    FULL_BUNDLE=true ;;
        --help|-h)
            echo "Usage: $0 [--full] [--docker]"
            echo ""
            echo "  --full     Create full bundle (entire repo history)"
            echo "  --docker   Also export Docker images (large!)"
            echo ""
            echo "Without --full, creates an incremental bundle with only"
            echo "new commits since the last sync."
            exit 0
            ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

echo ""
echo "=============================================="
echo "Air-Gapped Sync - EXPORT"
echo "Timestamp: $TIMESTAMP"
echo "=============================================="
echo ""

mkdir -p "$OUTPUT_DIR"

# --- Git Bundle ---

CURRENT_REF=$(git rev-parse HEAD)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
ALL_BRANCHES=$(git for-each-ref --format='%(refname)' refs/heads/)

if [ "$FULL_BUNDLE" = true ]; then
    echo "[1/3] Creating FULL git bundle (all branches, all history)..."
    BUNDLE_FILE="$OUTPUT_DIR/repo-full.bundle"
    git bundle create "$BUNDLE_FILE" --all
    BUNDLE_TYPE="full"
else
    if [ -f "$MARKER_FILE" ]; then
        LAST_REF=$(cat "$MARKER_FILE")
        # Verify the ref still exists
        if git cat-file -t "$LAST_REF" >/dev/null 2>&1; then
            NEW_COMMITS=$(git rev-list --count "$LAST_REF".."$CURRENT_REF" 2>/dev/null || echo "0")
            if [ "$NEW_COMMITS" = "0" ]; then
                echo "No new commits since last sync ($LAST_REF)."
                echo "Use --full to force a full bundle, or make changes first."
                rm -rf "$OUTPUT_DIR"
                exit 0
            fi
            echo "[1/3] Creating INCREMENTAL git bundle ($NEW_COMMITS new commits)..."
            echo "  Basis: $LAST_REF"
            echo "  Head:  $CURRENT_REF"
            BUNDLE_FILE="$OUTPUT_DIR/repo-incremental.bundle"
            git bundle create "$BUNDLE_FILE" "$LAST_REF".."$CURRENT_BRANCH"
            BUNDLE_TYPE="incremental"
        else
            echo "  Warning: Last sync ref $LAST_REF no longer exists."
            echo "  Falling back to full bundle."
            BUNDLE_FILE="$OUTPUT_DIR/repo-full.bundle"
            git bundle create "$BUNDLE_FILE" --all
            BUNDLE_TYPE="full"
        fi
    else
        echo "[1/3] No previous sync found. Creating FULL git bundle..."
        BUNDLE_FILE="$OUTPUT_DIR/repo-full.bundle"
        git bundle create "$BUNDLE_FILE" --all
        BUNDLE_TYPE="full"
    fi
fi

BUNDLE_SIZE=$(du -h "$BUNDLE_FILE" | cut -f1)
echo "  Bundle: $(basename "$BUNDLE_FILE") ($BUNDLE_SIZE)"
echo ""

# --- Metadata ---

echo "[2/3] Writing sync metadata..."
cat > "$OUTPUT_DIR/sync-manifest.json" << EOF
{
    "timestamp": "$TIMESTAMP",
    "bundle_type": "$BUNDLE_TYPE",
    "source_branch": "$CURRENT_BRANCH",
    "source_ref": "$CURRENT_REF",
    "previous_ref": "$(cat "$MARKER_FILE" 2>/dev/null || echo 'none')",
    "includes_docker": $INCLUDE_DOCKER
}
EOF
echo "  Manifest written."
echo ""

# --- Docker Images (optional) ---

if [ "$INCLUDE_DOCKER" = true ]; then
    echo "[3/3] Exporting Docker images..."

    # Build if not already built
    if ! docker image inspect softpower-api:latest >/dev/null 2>&1; then
        echo "  Building images first..."
        "$SCRIPT_DIR/build-all.sh"
    fi

    docker save softpower-api:latest | gzip > "$OUTPUT_DIR/softpower-api.tar.gz"
    echo "  softpower-api.tar.gz ($(du -h "$OUTPUT_DIR/softpower-api.tar.gz" | cut -f1))"

    docker save softpower-dashboard:latest | gzip > "$OUTPUT_DIR/softpower-dashboard.tar.gz"
    echo "  softpower-dashboard.tar.gz ($(du -h "$OUTPUT_DIR/softpower-dashboard.tar.gz" | cut -f1))"

    docker save softpower-pipeline:latest | gzip > "$OUTPUT_DIR/softpower-pipeline.tar.gz"
    echo "  softpower-pipeline.tar.gz ($(du -h "$OUTPUT_DIR/softpower-pipeline.tar.gz" | cut -f1))"

    # Base images only on full bundle (first time)
    if [ "$BUNDLE_TYPE" = "full" ]; then
        echo "  Pulling and saving base images..."
        docker pull ankane/pgvector:latest
        docker pull redis:7-alpine
        docker save ankane/pgvector:latest | gzip > "$OUTPUT_DIR/pgvector.tar.gz"
        echo "  pgvector.tar.gz ($(du -h "$OUTPUT_DIR/pgvector.tar.gz" | cut -f1))"
        docker save redis:7-alpine | gzip > "$OUTPUT_DIR/redis.tar.gz"
        echo "  redis.tar.gz ($(du -h "$OUTPUT_DIR/redis.tar.gz" | cut -f1))"
    fi
    echo ""
else
    echo "[3/3] Skipping Docker images (use --docker to include)."
    echo ""
fi

# --- Update sync marker ---

echo "$CURRENT_REF" > "$MARKER_FILE"

# --- Summary ---

TOTAL_SIZE=$(du -sh "$OUTPUT_DIR" | cut -f1)

echo "=============================================="
echo "Export complete!"
echo "=============================================="
echo ""
echo "  Output:    $OUTPUT_DIR/"
echo "  Size:      $TOTAL_SIZE"
echo "  Type:      $BUNDLE_TYPE"
echo "  Branch:    $CURRENT_BRANCH"
echo "  Commit:    ${CURRENT_REF:0:12}"
echo ""
echo "Contents:"
ls -lh "$OUTPUT_DIR/"
echo ""
echo "Transfer '$OUTPUT_DIR/' to the air-gapped system, then run:"
echo "  ./docker/airgap-sync-import.sh <path-to-transfer-dir>"
echo ""
