#!/usr/bin/env python3
"""
Database Migration Wrapper Script

Easy-to-use wrapper for the PostgreSQL migration tool.
Provides simple commands for common migration scenarios.

Usage:
    python migrate_database.py --help
    python migrate_database.py config  # Show current configuration
    python migrate_database.py migrate --source "postgresql://..." --target "postgresql://..."
    python migrate_database.py migrate --env  # Use environment variables
"""

import os
import sys
import argparse
from pathlib import Path

# Add backend to Python path
backend_path = Path(__file__).parent / "backend"
sys.path.append(str(backend_path))

from backend.scripts.postgres_migration import DatabaseMigrator
from backend.scripts.migration_config import (
    MigrationConfig,
    get_migration_config_from_env,
    get_sp_project_config,
    validate_config,
    print_config_summary,
    create_sample_env_file,
    TABLE_GROUPS
)


def show_config():
    """Display current migration configuration."""
    print("Current Migration Configuration")
    print("="*50)

    try:
        # Try to get config from environment
        config = get_migration_config_from_env()
        print("Configuration source: Environment variables")
    except Exception:
        # Fall back to SP project defaults
        config = get_sp_project_config()
        print("Configuration source: SP Project defaults")

    print_config_summary(config)

    # Validate and show any issues
    errors = validate_config(config)
    if errors:
        print("\nConfiguration Issues:")
        for error in errors:
            print(f"  ❌ {error}")
    else:
        print("\n✅ Configuration is valid")


def run_migration(args):
    """Run the database migration."""
    try:
        # Determine source and target URLs
        if args.source and args.target:
            source_url = args.source
            target_url = args.target
            print("Using provided database URLs")
        elif args.env:
            config = get_migration_config_from_env()
            source_url = config.source_db.connection_url
            target_url = config.target_db.connection_url
            print("Using environment variable configuration")
        else:
            config = get_sp_project_config()
            source_url = config.source_db.connection_url
            target_url = config.target_db.connection_url
            print("Using SP project default configuration")

        # Parse tables
        tables = None
        if args.tables:
            if args.tables in TABLE_GROUPS:
                tables = TABLE_GROUPS[args.tables]
                print(f"Using table group '{args.tables}': {tables}")
            else:
                tables = [t.strip() for t in args.tables.split(',')]
                print(f"Using custom table list: {tables}")

        # Show what we're about to do
        print("\nMigration Plan:")
        print(f"  Source: {source_url.replace(source_url.split('@')[0].split('//')[1], '***')}")
        print(f"  Target: {target_url.replace(target_url.split('@')[0].split('//')[1], '***')}")
        print(f"  Tables: {tables or 'All tables'}")
        print(f"  Batch Size: {args.batch_size}")
        print(f"  Clear Target: {args.clear_target}")
        print(f"  Verify: {args.verify}")

        # Confirm before proceeding
        if not args.yes:
            response = input("\nProceed with migration? [y/N]: ")
            if response.lower() != 'y':
                print("Migration cancelled")
                return

        # Initialize migrator
        migrator = DatabaseMigrator(source_url, target_url, args.batch_size)

        # Setup connections
        print("\nSetting up database connections...")
        migrator.setup_connections()

        # Create target schema if requested
        if args.create_schema:
            print("Creating target database schema...")
            migrator.create_target_schema()

        # Verify schemas
        print("Verifying database schemas...")
        if not migrator.verify_schemas():
            print("❌ Schema verification failed. Aborting migration.")
            return 1

        # Perform migration
        print("Starting migration...")
        migrator.migrate_all_data(tables, args.clear_target)

        # Verify migration if requested
        if args.verify:
            print("Verifying migration...")
            if not migrator.verify_migration(tables):
                print("❌ Migration verification failed")
                return 1

        print("✅ Migration completed successfully!")
        return 0

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return 1

    finally:
        if 'migrator' in locals():
            migrator.cleanup_connections()


def setup_sample_config():
    """Create sample configuration files."""
    create_sample_env_file()

    # Create a sample docker-compose for testing
    docker_compose = """version: '3.8'
services:
  postgres-source:
    image: postgres:15
    environment:
      POSTGRES_DB: source_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - source_data:/var/lib/postgresql/data

  postgres-target:
    image: postgres:15
    environment:
      POSTGRES_DB: target_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    ports:
      - "5433:5432"
    volumes:
      - target_data:/var/lib/postgresql/data

volumes:
  source_data:
  target_data:
"""

    with open("docker-compose.migration-test.yml", "w") as f:
        f.write(docker_compose)

    print("\nSample files created:")
    print("  • migration.env.sample - Environment configuration")
    print("  • docker-compose.migration-test.yml - Test databases")
    print("\nTo test the migration:")
    print("  1. docker-compose -f docker-compose.migration-test.yml up -d")
    print("  2. Copy migration.env.sample to .env and configure")
    print("  3. python migrate_database.py migrate --env")


def main():
    parser = argparse.ArgumentParser(description="Database Migration Tool")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Config command
    config_parser = subparsers.add_parser('config', help='Show current configuration')

    # Setup command
    setup_parser = subparsers.add_parser('setup', help='Create sample configuration files')

    # Migrate command
    migrate_parser = subparsers.add_parser('migrate', help='Run database migration')

    # Migration source options (mutually exclusive)
    source_group = migrate_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--env', action='store_true',
                            help='Use environment variables for configuration')
    source_group.add_argument('--source', help='Source database URL')

    migrate_parser.add_argument('--target', help='Target database URL')

    # Migration options
    migrate_parser.add_argument('--tables',
                              help='Tables to migrate (comma-separated or group name: core_documents, event_summaries, all_tables)')
    migrate_parser.add_argument('--batch-size', type=int, default=1000,
                              help='Records per batch (default: 1000)')
    migrate_parser.add_argument('--clear-target', action='store_true',
                              help='Clear target tables before migration')
    migrate_parser.add_argument('--verify', action='store_true', default=True,
                              help='Verify migration by comparing counts')
    migrate_parser.add_argument('--create-schema', action='store_true',
                              help='Create target database schema')
    migrate_parser.add_argument('--yes', '-y', action='store_true',
                              help='Skip confirmation prompt')
    migrate_parser.add_argument('--verbose', '-v', action='store_true',
                              help='Enable verbose logging')

    args = parser.parse_args()

    if args.command == 'config':
        show_config()
    elif args.command == 'setup':
        setup_sample_config()
    elif args.command == 'migrate':
        # Validate arguments
        if not args.env and not (args.source and args.target):
            print("Error: Must provide either --env or both --source and --target URLs")
            return 1

        return run_migration(args)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())