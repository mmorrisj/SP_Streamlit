#!/usr/bin/env python3
"""
Create initial admin user for the Soft Power Analytics Dashboard.

Usage:
    # Interactive (prompts for password - most secure):
    python scripts/create_admin.py --username admin

    # Non-interactive (for scripted deployments):
    python scripts/create_admin.py --username admin --password YourSecurePassword

    # Reset password for existing user (e.g. after pg_restore):
    python scripts/create_admin.py --username admin --password NewPass --reset-password

    # Skip force-password-change requirement:
    python scripts/create_admin.py --username admin --password Pass --no-force-password-change
"""
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database.database import get_session
from shared.models.models import User, UserRole
from server.auth import hash_password


def create_admin(username: str, password: str, force_password_change: bool = False,
                  reset_password: bool = False):
    """
    Create an admin user in the database.

    Args:
        username: Admin username
        password: Admin password
        force_password_change: Whether to force password change on first login
        reset_password: If True, reset password for existing users
    """
    with get_session() as session:
        # Check if user already exists
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            if existing.is_deleted:
                print(f"User '{username}' was previously deleted. Reactivating...")
                existing.is_deleted = False
                existing.deleted_at = None
                existing.password_hash = hash_password(password)
                existing.role = UserRole.ADMIN
                existing.is_active = True
                existing.force_password_change = force_password_change
                session.commit()
                print(f"User '{username}' has been reactivated as admin.")
                return

            if reset_password:
                existing.password_hash = hash_password(password)
                existing.force_password_change = force_password_change
                session.commit()
                print(f"Password reset for user '{username}'.")
                return

            print(f"User '{username}' already exists.")
            print("  Hint: use --reset-password to update the password")
            return

        # Create new admin user
        admin = User(
            username=username,
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
            display_name="Administrator",
            force_password_change=force_password_change,
            is_active=True
        )
        session.add(admin)
        session.commit()

        print(f"Admin user '{username}' created successfully!")
        print("  Role: admin")
        print(f"  Force password change: {force_password_change}")


def main():
    parser = argparse.ArgumentParser(
        description="Create an admin user for the Soft Power Analytics Dashboard"
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="Admin username (default: admin)"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Admin password (required in production; prompts if omitted)"
    )
    parser.add_argument(
        "--force-password-change",
        action="store_true",
        default=True,
        help="Require password change on first login (default: True)"
    )
    parser.add_argument(
        "--no-force-password-change",
        action="store_false",
        dest="force_password_change",
        help="Do NOT require password change on first login"
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        default=False,
        help="Reset password if user already exists (useful after pg_restore)"
    )

    args = parser.parse_args()

    if args.password is None:
        import getpass
        args.password = getpass.getpass("Enter admin password: ")
        if not args.password:
            print("Error: Password cannot be empty.")
            sys.exit(1)

    create_admin(
        username=args.username,
        password=args.password,
        force_password_change=args.force_password_change,
        reset_password=args.reset_password
    )


if __name__ == "__main__":
    main()
