# ============================================
# PostgreSQL 17 + pgvector Extension
# ============================================
# Custom build to ensure base image is current
# and pgvector extension is compiled from source.
#
# Replaces ankane/pgvector:latest which has 337
# unfixed CVEs due to stale base image.
#
# Usage:
#   docker buildx build -f docker/pgvector.Dockerfile \
#       --sbom=true --provenance=mode=max \
#       -t mmorrisj/pgvector:0.8.2-pg17 --push .
# ============================================

# Target: Rocky 9+ (kernel 5.14+, glibc 2.34+).
# PostgreSQL 17 for performance improvements (incremental backup, vacuum, JSON_TABLE).
FROM postgres:18-bookworm@sha256:9479eac93922431e8a512b016d7362ae264f4ba139f840891b51f02931e450db

# pgvector version and immutable commit SHA for supply-chain pinning.
# SHA must match the tag; verify with:
#   gh api repos/pgvector/pgvector/git/refs/tags/v0.8.2 --jq '.object.sha'
ARG PGVECTOR_VERSION=0.8.2
ARG PGVECTOR_SHA=cab9da72c04353f143bb06b42ab70a403daac64a

# Install build dependencies and compile pgvector.
# Clone by tag for shallow-clone efficiency, then verify the commit SHA
# matches the pinned value to catch tag-mover or supply-chain attacks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        postgresql-server-dev-17 \
    && git clone --branch v${PGVECTOR_VERSION} --depth 1 \
        https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && ACTUAL_SHA=$(git rev-parse HEAD) \
    && echo "pgvector HEAD: ${ACTUAL_SHA}" \
    && [ "${ACTUAL_SHA}" = "${PGVECTOR_SHA}" ] \
        || { echo "SHA MISMATCH: expected ${PGVECTOR_SHA}, got ${ACTUAL_SHA}"; exit 1; } \
    && make OPTFLAGS="" \
    && make install

# Verify the extension was installed
RUN pg_config --sharedir | xargs -I{} ls {}/extension/vector.control

# Remove build tools and unneeded runtime packages to reduce attack surface.
RUN apt-get purge -y build-essential git ca-certificates postgresql-server-dev-17 \
    gnupg gpg gpg-wks-client gpg-wks-server \
    && apt-get autoremove -y \
    && (dpkg --purge --force-all $(dpkg -l | grep '^rc' | awk '{print $2}') 2>/dev/null || true) \
    && rm -rf /tmp/pgvector /var/lib/apt/lists/*

# Remove gosu (Go 1.24.6 binary) to eliminate CVE-2025-68121 (CRITICAL).
# gosu is only used by the entrypoint when running as root to drop privileges.
# Since we set USER postgres below, the entrypoint's root codepath is never
# executed, making gosu unnecessary.
RUN rm -f /usr/local/bin/gosu

# Remove tar's rmt binary (TEMP-0290435-0B57B5) — remote tape server
# is unused and has insufficient input validation.
RUN rm -f /usr/sbin/rmt

# Run as non-root user (Scout health check: "Default non-root user")
# The postgres base image creates uid 999 (postgres) and its entrypoint
# handles initialization correctly when running as non-root.
USER postgres
