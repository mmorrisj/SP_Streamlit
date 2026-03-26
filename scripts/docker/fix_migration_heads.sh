#!/bin/bash
# ============================================
# Fix Alembic Multiple Heads (Docker Run)
# ============================================
# Runs an ephemeral container to inject the merge migration
# and apply all pending migrations. No docker exec needed.
#
# Usage:
#   ./scripts/docker/fix_migration_heads.sh
#
# Honors the same env vars as production-deploy.sh:
#   APP_IMAGE, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB,
#   DB_PORT, NETWORK_NAME, DB_CONTAINER
# ============================================

set -e

# Load .env if available
if [ -f .env ]; then
    set -a
    . .env
    set +a
fi

# Defaults matching production-deploy.sh
APP_IMAGE="${APP_IMAGE:-softpower-analytics:latest}"
POSTGRES_USER="${POSTGRES_USER:?Set POSTGRES_USER in .env or environment}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env or environment}"
POSTGRES_DB="${POSTGRES_DB:?Set POSTGRES_DB in .env or environment}"
DB_CONTAINER="${DB_CONTAINER:-sp_prod_db}"
NETWORK_NAME="${NETWORK_NAME:-softpower_net}"

echo "[INFO]  Using image: $APP_IMAGE"
echo "[INFO]  Database: $DB_CONTAINER / $POSTGRES_DB"
echo "[INFO]  Network: $NETWORK_NAME"
echo ""

docker run --rm \
    --network "$NETWORK_NAME" \
    -e DOCKER_ENV=true \
    -e DB_HOST="$DB_CONTAINER" \
    -e DB_PORT=5432 \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    "$APP_IMAGE" \
    python3 -c "
import os, subprocess, sys

migration = '''\"\"\"merge search_vector and aiddata branches

Revision ID: 821886869aed
Revises: 006_search_vector, 20260224_aiddata_tables
Create Date: 2026-03-26 13:33:52.540352

\"\"\"
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = \"821886869aed\"
down_revision: Union[str, None] = (\"006_search_vector\", \"20260224_aiddata_tables\")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''

path = '/app/alembic/versions/821886869aed_merge_search_vector_and_aiddata_branches.py'
if os.path.exists(path):
    print(f'Merge migration already exists: {path}')
else:
    with open(path, 'w') as f:
        f.write(migration)
    print(f'Created merge migration: {path}')

print()
print('Running: alembic upgrade head ...')
rc = subprocess.call(['alembic', 'upgrade', 'head'], cwd='/app')
if rc == 0:
    print()
    print('All migrations applied successfully.')
else:
    print(f'alembic upgrade head exited with code {rc}')
    sys.exit(rc)
"

echo ""
echo "[OK]    Migration fix complete. You can now run:"
echo "        ./scripts/docker/production-deploy.sh migrate"
echo "        (it will be a no-op since migrations are already applied)"
