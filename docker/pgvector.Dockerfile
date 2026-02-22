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
#   docker build -f docker/pgvector.Dockerfile -t mmorrisj/pgvector:0.8.0-pg16 .
#   docker push mmorrisj/pgvector:0.8.0-pg16
# ============================================

FROM postgres:16-bookworm

# pgvector version to install
ARG PGVECTOR_VERSION=0.8.0

# Install build dependencies and compile pgvector
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        postgresql-server-dev-16 \
    && git clone --branch v${PGVECTOR_VERSION} --depth 1 \
        https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make OPTFLAGS="" \
    && make install

# Verify the extension was installed
RUN pg_config --sharedir | xargs -I{} ls {}/extension/vector.control

# Remove build tools to reduce attack surface
RUN apt-get purge -y build-essential git ca-certificates postgresql-server-dev-16 \
    && apt-get autoremove -y \
    && (dpkg --purge --force-all $(dpkg -l | grep '^rc' | awk '{print $2}') 2>/dev/null || true) \
    && rm -rf /tmp/pgvector /var/lib/apt/lists/*

# Remove gosu (Go 1.24.6 binary) to eliminate CVE-2025-68121 (CRITICAL).
# gosu is only used by the entrypoint when running as root to drop privileges.
# Since we set USER postgres below, the entrypoint's root codepath is never
# executed, making gosu unnecessary.
RUN rm -f /usr/local/bin/gosu

# Run as non-root user (Scout health check: "Default non-root user")
# The postgres base image creates uid 999 (postgres) and its entrypoint
# handles initialization correctly when running as non-root.
USER postgres
