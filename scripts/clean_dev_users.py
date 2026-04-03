#!/usr/bin/env python3
"""
Remove dev-bypass users from the database before exporting to enterprise.

Dev users created by DEV_AUTH_BYPASS=true are tagged with enterprise_id='dev-local'.
This script deletes (hard delete) those rows so they don't carry over to enterprise.

Usage:
    # Preview what would be removed (dry run):
    python scripts/clean_dev_users.py

    # Actually remove dev users:
    python scripts/clean_dev_users.py --apply

    # Can also be imported and called from other scripts (e.g., db_export.py):
    from scripts.clean_dev_users import clean_dev_users
    removed = clean_dev_users(apply=True)
"""
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database.database import get_session
from shared.models.models import User

# Marker value set by the dev auth bypass in server/auth.py
DEV_ENTERPRISE_ID = "dev-local"


def clean_dev_users(apply: bool = False) -> int:
    """
    Remove dev-bypass users (enterprise_id='dev-local') from the database.

    Args:
        apply: If True, actually delete. If False, dry-run only.

    Returns:
        Number of dev users found (and removed, if apply=True).
    """
    with get_session() as session:
        dev_users = session.query(User).filter(
            User.enterprise_id == DEV_ENTERPRISE_ID
        ).all()

        if not dev_users:
            print("No dev-bypass users found. Database is clean.")
            return 0

        print(f"Found {len(dev_users)} dev-bypass user(s):")
        for u in dev_users:
            print(f"  - {u.username} (role={u.role.value}, enterprise_id={u.enterprise_id})")

        if apply:
            for u in dev_users:
                session.delete(u)
            session.commit()
            print(f"\nRemoved {len(dev_users)} dev user(s).")
        else:
            print(f"\nDry run - no changes made. Run with --apply to remove.")

        return len(dev_users)


def main():
    parser = argparse.ArgumentParser(
        description="Remove dev-bypass users before exporting database to enterprise"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually remove dev users (default: dry-run only)"
    )
    args = parser.parse_args()
    clean_dev_users(apply=args.apply)


if __name__ == "__main__":
    main()
