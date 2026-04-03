#!/usr/bin/env python3
"""
Promote a user to admin role for the Soft Power Analytics Dashboard.

With enterprise JWT auth, users are auto-provisioned when they first access
the application. This script lets you pre-create or promote a user to admin.

Usage:
    # Promote an existing user to admin:
    python scripts/create_admin.py --username john.doe

    # Pre-create an admin user (before their first login via the gateway):
    python scripts/create_admin.py --username john.doe --enterprise-id "abc-123"

    # Set a specific role:
    python scripts/create_admin.py --username john.doe --role analyst
"""
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database.database import get_session
from shared.models.models import User, UserRole


def promote_user(username: str, role: str = "admin", enterprise_id: str = None,
                 display_name: str = None):
    """
    Promote or pre-create a user with the specified role.

    Args:
        username: Username (should match enterprise JWT preferred_username/email)
        role: Role to assign (admin, analyst, viewer)
        enterprise_id: Enterprise JWT 'sub' claim (optional, for pre-provisioning)
        display_name: Display name (optional)
    """
    try:
        user_role = UserRole(role)
    except ValueError:
        print(f"Error: Invalid role '{role}'. Must be one of: admin, analyst, viewer")
        sys.exit(1)

    with get_session() as session:
        # Check if user already exists
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            if existing.is_deleted:
                print(f"User '{username}' was previously deleted. Reactivating...")
                existing.is_deleted = False
                existing.deleted_at = None
                existing.role = user_role
                existing.is_active = True
                if enterprise_id:
                    existing.enterprise_id = enterprise_id
                if display_name:
                    existing.display_name = display_name
                session.commit()
                print(f"User '{username}' reactivated with role: {role}")
                return

            old_role = existing.role.value
            existing.role = user_role
            if enterprise_id:
                existing.enterprise_id = enterprise_id
            if display_name:
                existing.display_name = display_name
            session.commit()
            print(f"User '{username}' updated: {old_role} -> {role}")
            return

        # Pre-create user (they'll be matched by username on first gateway login)
        user = User(
            username=username,
            enterprise_id=enterprise_id,
            role=user_role,
            display_name=display_name or username,
            is_active=True
        )
        session.add(user)
        session.commit()

        print(f"User '{username}' pre-created with role: {role}")
        if enterprise_id:
            print(f"  Enterprise ID: {enterprise_id}")
        print("  They will be matched on first login via the enterprise gateway.")


def main():
    parser = argparse.ArgumentParser(
        description="Promote or pre-create a user for the Soft Power Analytics Dashboard"
    )
    parser.add_argument(
        "--username",
        required=True,
        help="Username (should match enterprise JWT preferred_username or email claim)"
    )
    parser.add_argument(
        "--role",
        default="admin",
        choices=["admin", "analyst", "viewer"],
        help="Role to assign (default: admin)"
    )
    parser.add_argument(
        "--enterprise-id",
        default=None,
        help="Enterprise JWT 'sub' claim for pre-provisioning (optional)"
    )
    parser.add_argument(
        "--display-name",
        default=None,
        help="Display name (optional)"
    )

    args = parser.parse_args()

    promote_user(
        username=args.username,
        role=args.role,
        enterprise_id=args.enterprise_id,
        display_name=args.display_name
    )


if __name__ == "__main__":
    main()
