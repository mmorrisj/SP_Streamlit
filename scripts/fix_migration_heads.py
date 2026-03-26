#!/usr/bin/env python3
"""
Fix Alembic multiple heads error by creating a merge migration.

Run this on any system where `alembic upgrade head` fails with:
  "Multiple head revisions are present; please specify a target revision"

Usage (bare metal):
    python scripts/fix_migration_heads.py

Usage (docker run - no exec needed):
    See scripts/docker/fix_migration_heads.sh
"""

import os
import subprocess
import sys

MERGE_MIGRATION = """\
\"\"\"merge search_vector and aiddata branches

Revision ID: 821886869aed
Revises: 006_search_vector, 20260224_aiddata_tables
Create Date: 2026-03-26 13:33:52.540352

\"\"\"
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '821886869aed'
down_revision: Union[str, None] = ('006_search_vector', '20260224_aiddata_tables')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""

def main():
    # Find project root (where alembic/ directory lives)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    versions_dir = os.path.join(project_root, "alembic", "versions")

    if not os.path.isdir(versions_dir):
        # Try current working directory
        versions_dir = os.path.join(os.getcwd(), "alembic", "versions")
        project_root = os.getcwd()

    if not os.path.isdir(versions_dir):
        print(f"ERROR: Cannot find alembic/versions/ directory.")
        print(f"  Run this script from the project root or from scripts/")
        sys.exit(1)

    target = os.path.join(
        versions_dir,
        "821886869aed_merge_search_vector_and_aiddata_branches.py",
    )

    if os.path.exists(target):
        print(f"Merge migration already exists: {target}")
    else:
        with open(target, "w") as f:
            f.write(MERGE_MIGRATION)
        print(f"Created merge migration: {target}")

    # Run alembic upgrade head
    print("\nRunning: alembic upgrade head ...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=project_root,
    )
    if result.returncode == 0:
        print("\nAll migrations applied successfully.")
    else:
        print(f"\nalembic upgrade head exited with code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
