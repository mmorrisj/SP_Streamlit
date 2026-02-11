# ============================================
# Air-Gapped PostgreSQL + pgvector
# Built on Debian base (no ankane/pgvector needed)
# ============================================
# Base: debian (approved in air-gapped registry)
# Installs PostgreSQL 16 + pgvector extension
# ============================================

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PG_MAJOR=16
ENV PGDATA=/var/lib/postgresql/data

# Install PostgreSQL 16 from PGDG repository + build tools for pgvector
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg2 \
        lsb-release \
        locales \
    && echo "deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg \
    && apt-get update && apt-get install -y --no-install-recommends \
        postgresql-${PG_MAJOR} \
        postgresql-server-dev-${PG_MAJOR} \
        postgresql-client-${PG_MAJOR} \
        build-essential \
        git \
    # Build pgvector extension
    && git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make PG_CONFIG=/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config \
    && make install PG_CONFIG=/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config \
    # Clean up build dependencies to reduce image size
    && apt-get purge -y build-essential git postgresql-server-dev-${PG_MAJOR} gnupg2 lsb-release \
    && apt-get autoremove -y \
    && rm -rf /tmp/pgvector /var/lib/apt/lists/* \
    # Generate locale
    && sed -i 's/^# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen \
    && locale-gen

# Set locale
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Add PostgreSQL bin to PATH
ENV PATH="/usr/lib/postgresql/${PG_MAJOR}/bin:${PATH}"

# Create data directory and set ownership
RUN mkdir -p "$PGDATA" /run/postgresql /var/log/postgresql \
    && chown -R postgres:postgres "$PGDATA" /run/postgresql /var/log/postgresql \
    && chmod 700 "$PGDATA"

# Copy entrypoint script
COPY docker/pg-entrypoint.sh /usr/local/bin/pg-entrypoint.sh
RUN chmod +x /usr/local/bin/pg-entrypoint.sh

EXPOSE 5432

# Shared memory hint for PostgreSQL
# CentOS 7 may need: --shm-size=1g on docker run
VOLUME ["${PGDATA}"]

USER postgres

ENTRYPOINT ["pg-entrypoint.sh"]
CMD ["postgres"]
