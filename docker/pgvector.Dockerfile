# ============================================
# PostgreSQL 16 + pgvector Extension
# ============================================
# Custom build to ensure base image is current
# and pgvector extension is compiled from source.
#
# Replaces ankane/pgvector:latest which has 337
# unfixed CVEs due to stale base image.
#
# Usage:
#   docker build -f docker/pgvector.Dockerfile -t mmorrisj/pgvector:0.8.1-pg16 .
#   docker push mmorrisj/pgvector:0.8.1-pg16
# ============================================

# Use Debian 13 (trixie) variant to pick up newer libc/OpenLDAP packages
# while staying on PostgreSQL 16.
# Digest-pinned for Docker Scout "Outdated base images" compliance.
# Update digest with: docker pull postgres:16-trixie && docker inspect postgres:16-trixie --format='{{index .RepoDigests 0}}'
FROM postgres:16-trixie@sha256:23af655ba1ddf74eaa002e3deaf5fce022ab8791672336a7c1fb0ef2d57efb7f

# pgvector version and immutable commit SHA for supply-chain pinning.
# SHA must match the tag; verify with:
#   gh api repos/pgvector/pgvector/git/refs/tags/v0.8.1 --jq '.object.sha'
ARG PGVECTOR_VERSION=0.8.1
ARG PGVECTOR_SHA=778dacf20c07caf904557a88705142631818d8cb

# Install build dependencies and compile pgvector.
# Clone by tag for shallow-clone efficiency, then verify the commit SHA
# matches the pinned value to catch tag-mover or supply-chain attacks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        postgresql-server-dev-16 \
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
# On trixie, libsqlite3-0 is required by util-linux dependency chain and cannot
# be safely purged without breaking base package dependencies.
RUN apt-get purge -y build-essential git ca-certificates postgresql-server-dev-16 \
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
