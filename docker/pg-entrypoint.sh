#!/bin/bash
set -e

# ============================================
# PostgreSQL + pgvector entrypoint
# Handles first-run initialization and startup
# ============================================

PGDATA="${PGDATA:-/var/lib/postgresql/data}"

# If PGDATA is empty, initialize
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "=== Initializing PostgreSQL database ==="

    # Initialize database cluster
    initdb --username=postgres --encoding=UTF8 --locale=en_US.UTF-8 -D "$PGDATA"

    # Configure authentication: trust connections from Docker network
    cat > "$PGDATA/pg_hba.conf" << 'PGEOF'
# TYPE  DATABASE    USER        ADDRESS         METHOD
local   all         all                         trust
host    all         all         127.0.0.1/32    md5
host    all         all         ::1/128         md5
# Allow connections from Docker network (172.x.x.x)
host    all         all         172.0.0.0/8     md5
# Allow connections from common Docker bridge ranges
host    all         all         10.0.0.0/8      md5
host    all         all         192.168.0.0/16  md5
PGEOF

    # Configure PostgreSQL for container usage
    cat >> "$PGDATA/postgresql.conf" << 'PGEOF'

# Container-optimized settings
listen_addresses = '*'
max_connections = 100
shared_buffers = 256MB
work_mem = 16MB
maintenance_work_mem = 128MB
effective_cache_size = 512MB
# Logging
log_destination = 'stderr'
logging_collector = off
# WAL settings for performance
wal_buffers = 16MB
checkpoint_completion_target = 0.9
# pgvector settings
shared_preload_libraries = ''
PGEOF

    # Start temporarily to create user and database
    pg_ctl -D "$PGDATA" -w start -o "-c listen_addresses='localhost'"

    # Create user and database from environment variables
    POSTGRES_USER="${POSTGRES_USER:-matthew50}"
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-softpower}"
    POSTGRES_DB="${POSTGRES_DB:-softpower-db}"

    echo "=== Creating user: $POSTGRES_USER ==="
    psql -v ON_ERROR_STOP=1 --username=postgres <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${POSTGRES_USER}') THEN
                CREATE USER "${POSTGRES_USER}" WITH SUPERUSER PASSWORD '${POSTGRES_PASSWORD}';
            END IF;
        END
        \$\$;
EOSQL

    echo "=== Creating database: $POSTGRES_DB ==="
    psql -v ON_ERROR_STOP=1 --username=postgres <<-EOSQL
        SELECT 'CREATE DATABASE "${POSTGRES_DB}" OWNER "${POSTGRES_USER}"'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_DB}')\gexec
EOSQL

    echo "=== Enabling pgvector extension ==="
    psql -v ON_ERROR_STOP=1 --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

    # Run any init scripts in /docker-entrypoint-initdb.d/
    if [ -d /docker-entrypoint-initdb.d/ ]; then
        for f in /docker-entrypoint-initdb.d/*.sql; do
            if [ -f "$f" ]; then
                echo "=== Running init script: $f ==="
                psql -v ON_ERROR_STOP=1 --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" -f "$f"
            fi
        done
    fi

    # Stop temporary instance
    pg_ctl -D "$PGDATA" -w stop

    echo "=== PostgreSQL initialization complete ==="
fi

# Start PostgreSQL with the provided command
exec postgres -D "$PGDATA" "$@"
