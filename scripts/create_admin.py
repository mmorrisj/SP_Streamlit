#!/usr/bin/env python3
"""
Create initial admin user for the Soft Power Analytics Dashboard.

Usage:
    python scripts/create_admin.py --username admin --password YourSecurePassword
    python scripts/create_admin.py  # Uses defaults: admin / admin123
"""
import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database.database import get_session
from shared.models.models import User, UserRole
from server.auth import hash_password


def create_admin(username: str, password: str, force_password_change: bool = False):
    """
    Create an admin user in the database.

    Args:
        username: Admin username
        password: Admin password
        force_password_change: Whether to force password change on first login
    """
    with get_session() as session:
        # Check if user already exists
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            print(f"User '{username}' already exists.")
            if existing.is_deleted:
                print("Note: This user was previously deleted. Reactivating...")
                existing.is_deleted = False
                existing.deleted_at = None
                existing.password_hash = hash_password(password)
                existing.role = UserRole.ADMIN
                existing.is_active = True
                existing.force_password_change = force_password_change
                session.commit()
                print(f"User '{username}' has been reactivated as admin.")
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
        default="admin123",
        help="Admin password (default: admin123)"
    )
    parser.add_argument(
        "--force-password-change",
        action="store_true",
        help="Require password change on first login"
    )

    args = parser.parse_args()

    if args.password == "admin123":
        print("Warning: Using default password 'admin123'. Change this in production!")
        print()

    create_admin(
        username=args.username,
        password=args.password,
        force_password_change=args.force_password_change
    )


if __name__ == "__main__":
    main()
