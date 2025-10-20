#!/usr/bin/env python3
"""
PostgreSQL Data Migration Script

This script transfers data from one PostgreSQL database to another.
It uses SQLAlchemy to handle the database operations and supports
both full migrations and selective table migrations.

Usage:
    python postgres_migration.py --source-url "postgresql://user:pass@host:port/source_db"
                                 --target-url "postgresql://user:pass@host:port/target_db"
                                 [--tables table1,table2] [--batch-size 1000] [--verify]

Author: Generated for SP_Streamlit project
"""

import os
import sys
import argparse
import logging
import time
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from contextlib import contextmanager

# Add the parent directory to the path to import our models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from sqlalchemy import create_engine, text, inspect, MetaData, Table
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.engine import Engine

# Import our models
from shared.models.models import Base, Document, Category, Subcategory, InitiatingCountry, RecipientCountry, Project, RawEvent, Citation, EventSummary, PeriodSummary, EventSourceLink

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

class DatabaseMigrator:
    """
    PostgreSQL database migration utility that handles copying data between databases.
    """

    def __init__(self, source_url: str, target_url: str, batch_size: int = 1000):
        """
        Initialize the migrator with source and target database URLs.

        Args:
            source_url: PostgreSQL connection URL for source database
            target_url: PostgreSQL connection URL for target database
            batch_size: Number of records to process in each batch
        """
        self.source_url = source_url
        self.target_url = target_url
        self.batch_size = batch_size
        self.source_engine: Optional[Engine] = None
        self.target_engine: Optional[Engine] = None
        self.source_session_maker = None
        self.target_session_maker = None

        # Define table migration order based on foreign key dependencies
        self.migration_order = [
            'documents',  # Must be first - referenced by all other tables
            'categories',
            'subcategories',
            'initiating_countries',
            'recipient_countries',
            'projects',
            'raw_events',
            'citations',
            'period_summaries',  # Before event_summaries (FK dependency)
            'event_summaries',
            'event_source_links',  # Last - references both documents and event_summaries
        ]

        self.migration_stats = {
            'start_time': None,
            'end_time': None,
            'total_records_migrated': 0,
            'table_stats': {},
            'errors': []
        }

    def setup_connections(self):
        """Establish connections to both source and target databases."""
        try:
            # Source database connection
            self.source_engine = create_engine(
                self.source_url,
                echo=False,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=3600
            )
            self.source_session_maker = sessionmaker(bind=self.source_engine)

            # Target database connection
            self.target_engine = create_engine(
                self.target_url,
                echo=False,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=3600
            )
            self.target_session_maker = sessionmaker(bind=self.target_engine)

            # Test both connections
            with self.source_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Source database connection established")

            with self.target_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Target database connection established")

        except Exception as e:
            logger.error(f"Failed to establish database connections: {e}")
            raise

    @contextmanager
    def get_sessions(self):
        """Context manager to get sessions for both databases."""
        source_session = self.source_session_maker()
        target_session = self.target_session_maker()

        try:
            yield source_session, target_session
        except Exception as e:
            source_session.rollback()
            target_session.rollback()
            logger.error(f"Session error: {e}")
            raise
        finally:
            source_session.close()
            target_session.close()

    def verify_schemas(self) -> bool:
        """
        Verify that both databases have compatible schemas.

        Returns:
            bool: True if schemas are compatible
        """
        try:
            source_inspector = inspect(self.source_engine)
            target_inspector = inspect(self.target_engine)

            source_tables = set(source_inspector.get_table_names())
            target_tables = set(target_inspector.get_table_names())

            logger.info(f"Source database tables: {sorted(source_tables)}")
            logger.info(f"Target database tables: {sorted(target_tables)}")

            # Check if target has all required tables
            missing_tables = source_tables - target_tables
            if missing_tables:
                logger.error(f"Target database missing tables: {missing_tables}")
                return False

            # Verify column compatibility for each table
            for table in source_tables:
                if table in target_tables:
                    source_columns = source_inspector.get_columns(table)
                    target_columns = target_inspector.get_columns(table)

                    source_col_names = {col['name'] for col in source_columns}
                    target_col_names = {col['name'] for col in target_columns}

                    missing_cols = source_col_names - target_col_names
                    if missing_cols:
                        logger.warning(f"Table '{table}' missing columns in target: {missing_cols}")

            logger.info("Schema verification completed")
            return True

        except Exception as e:
            logger.error(f"Schema verification failed: {e}")
            return False

    def create_target_schema(self):
        """Create the target database schema if it doesn't exist."""
        try:
            logger.info("Creating target database schema...")
            Base.metadata.create_all(self.target_engine)
            logger.info("Target database schema created successfully")
        except Exception as e:
            logger.error(f"Failed to create target schema: {e}")
            raise

    def get_table_count(self, session: Session, table_name: str) -> int:
        """Get row count for a specific table."""
        try:
            result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            return result.scalar()
        except Exception as e:
            logger.error(f"Failed to get count for table {table_name}: {e}")
            return 0

    def clear_target_table(self, table_name: str):
        """Clear all data from a target table."""
        try:
            with self.target_engine.connect() as conn:
                # Disable foreign key constraints temporarily
                conn.execute(text("SET session_replication_role = replica;"))
                conn.execute(text(f"DELETE FROM {table_name}"))
                conn.execute(text("SET session_replication_role = DEFAULT;"))
                conn.commit()
            logger.info(f"Cleared target table: {table_name}")
        except Exception as e:
            logger.error(f"Failed to clear target table {table_name}: {e}")
            raise

    def migrate_table_data(self, table_name: str, clear_target: bool = False) -> Dict[str, Any]:
        """
        Migrate data for a specific table.

        Args:
            table_name: Name of the table to migrate
            clear_target: Whether to clear target table before migration

        Returns:
            dict: Migration statistics for this table
        """
        stats = {
            'table': table_name,
            'source_count': 0,
            'migrated_count': 0,
            'errors': 0,
            'start_time': datetime.now(),
            'end_time': None,
            'duration': None
        }

        try:
            with self.get_sessions() as (source_session, target_session):
                # Get source record count
                stats['source_count'] = self.get_table_count(source_session, table_name)
                logger.info(f"Starting migration of '{table_name}' - {stats['source_count']} records")

                if stats['source_count'] == 0:
                    logger.info(f"No data to migrate for table '{table_name}'")
                    stats['end_time'] = datetime.now()
                    stats['duration'] = stats['end_time'] - stats['start_time']
                    return stats

                # Clear target table if requested
                if clear_target:
                    self.clear_target_table(table_name)

                # Get table metadata
                metadata = MetaData()
                metadata.reflect(bind=self.source_engine)
                table = metadata.tables[table_name]

                # Migrate data in batches
                offset = 0
                while True:
                    # Fetch batch from source
                    query = source_session.query(table).offset(offset).limit(self.batch_size)
                    batch = query.all()

                    if not batch:
                        break

                    try:
                        # Insert batch into target
                        for row in batch:
                            # Convert row to dict
                            row_dict = {}
                            for column in table.columns:
                                row_dict[column.name] = getattr(row, column.name)

                            # Insert into target
                            target_session.execute(table.insert().values(**row_dict))

                        target_session.commit()
                        stats['migrated_count'] += len(batch)

                        logger.info(f"Migrated {stats['migrated_count']}/{stats['source_count']} records from '{table_name}'")

                    except Exception as e:
                        target_session.rollback()
                        stats['errors'] += len(batch)
                        logger.error(f"Error migrating batch for '{table_name}': {e}")

                        # Try individual inserts for this batch
                        for row in batch:
                            try:
                                row_dict = {}
                                for column in table.columns:
                                    row_dict[column.name] = getattr(row, column.name)

                                target_session.execute(table.insert().values(**row_dict))
                                target_session.commit()
                                stats['migrated_count'] += 1

                            except Exception as individual_error:
                                target_session.rollback()
                                stats['errors'] += 1
                                logger.error(f"Failed to migrate individual record: {individual_error}")

                    offset += self.batch_size

        except Exception as e:
            logger.error(f"Critical error migrating table '{table_name}': {e}")
            stats['errors'] = stats.get('errors', 0) + 1

        finally:
            stats['end_time'] = datetime.now()
            stats['duration'] = stats['end_time'] - stats['start_time']

            logger.info(f"Completed migration of '{table_name}': "
                       f"{stats['migrated_count']}/{stats['source_count']} records, "
                       f"{stats['errors']} errors, "
                       f"duration: {stats['duration']}")

        return stats

    def migrate_all_data(self, tables: Optional[List[str]] = None, clear_target: bool = False):
        """
        Migrate all data from source to target database.

        Args:
            tables: List of specific tables to migrate (None for all tables)
            clear_target: Whether to clear target tables before migration
        """
        self.migration_stats['start_time'] = datetime.now()

        # Determine which tables to migrate
        tables_to_migrate = tables if tables else self.migration_order

        logger.info(f"Starting full database migration - {len(tables_to_migrate)} tables")

        # Migrate each table in order
        for table_name in tables_to_migrate:
            table_stats = self.migrate_table_data(table_name, clear_target)
            self.migration_stats['table_stats'][table_name] = table_stats
            self.migration_stats['total_records_migrated'] += table_stats['migrated_count']

            if table_stats['errors'] > 0:
                self.migration_stats['errors'].append(f"Table '{table_name}': {table_stats['errors']} errors")

        self.migration_stats['end_time'] = datetime.now()

        # Print final summary
        self.print_migration_summary()

    def verify_migration(self, tables: Optional[List[str]] = None) -> bool:
        """
        Verify that migration was successful by comparing record counts.

        Args:
            tables: List of tables to verify (None for all tables)

        Returns:
            bool: True if verification passes
        """
        tables_to_verify = tables if tables else self.migration_order
        verification_passed = True

        logger.info("Starting migration verification...")

        with self.get_sessions() as (source_session, target_session):
            for table_name in tables_to_verify:
                try:
                    source_count = self.get_table_count(source_session, table_name)
                    target_count = self.get_table_count(target_session, table_name)

                    if source_count == target_count:
                        logger.info(f"✓ Table '{table_name}': {target_count} records (verified)")
                    else:
                        logger.error(f"✗ Table '{table_name}': source={source_count}, target={target_count}")
                        verification_passed = False

                except Exception as e:
                    logger.error(f"Verification failed for table '{table_name}': {e}")
                    verification_passed = False

        if verification_passed:
            logger.info("Migration verification PASSED")
        else:
            logger.error("Migration verification FAILED")

        return verification_passed

    def print_migration_summary(self):
        """Print a detailed summary of the migration."""
        stats = self.migration_stats
        duration = stats['end_time'] - stats['start_time'] if stats['end_time'] and stats['start_time'] else None

        print("\n" + "="*80)
        print("MIGRATION SUMMARY")
        print("="*80)
        print(f"Start Time: {stats['start_time']}")
        print(f"End Time: {stats['end_time']}")
        print(f"Duration: {duration}")
        print(f"Total Records Migrated: {stats['total_records_migrated']:,}")
        print(f"Total Errors: {len(stats['errors'])}")

        print("\nPER-TABLE STATISTICS:")
        print("-" * 80)
        print(f"{'Table':<25} {'Source':<10} {'Migrated':<10} {'Errors':<8} {'Duration':<12}")
        print("-" * 80)

        for table_name, table_stats in stats['table_stats'].items():
            duration_str = str(table_stats['duration']).split('.')[0] if table_stats['duration'] else "N/A"
            print(f"{table_name:<25} {table_stats['source_count']:<10} "
                  f"{table_stats['migrated_count']:<10} {table_stats['errors']:<8} {duration_str:<12}")

        if stats['errors']:
            print("\nERRORS:")
            print("-" * 40)
            for error in stats['errors']:
                print(f"  • {error}")

        print("="*80)

    def cleanup_connections(self):
        """Close all database connections."""
        if self.source_engine:
            self.source_engine.dispose()
        if self.target_engine:
            self.target_engine.dispose()
        logger.info("Database connections closed")

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="PostgreSQL Database Migration Tool")

    parser.add_argument(
        '--source-url',
        required=True,
        help='Source database connection URL (postgresql://user:pass@host:port/db)'
    )

    parser.add_argument(
        '--target-url',
        required=True,
        help='Target database connection URL (postgresql://user:pass@host:port/db)'
    )

    parser.add_argument(
        '--tables',
        help='Comma-separated list of tables to migrate (default: all tables)'
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Number of records to process in each batch (default: 1000)'
    )

    parser.add_argument(
        '--clear-target',
        action='store_true',
        help='Clear target tables before migration'
    )

    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify migration by comparing record counts'
    )

    parser.add_argument(
        '--create-schema',
        action='store_true',
        help='Create target database schema before migration'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    return parser.parse_args()

def main():
    """Main migration function."""
    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse tables list
    tables = None
    if args.tables:
        tables = [table.strip() for table in args.tables.split(',')]

    migrator = None
    try:
        # Initialize migrator
        migrator = DatabaseMigrator(args.source_url, args.target_url, args.batch_size)

        # Setup connections
        migrator.setup_connections()

        # Create target schema if requested
        if args.create_schema:
            migrator.create_target_schema()

        # Verify schemas
        if not migrator.verify_schemas():
            logger.error("Schema verification failed. Aborting migration.")
            return 1

        # Perform migration
        migrator.migrate_all_data(tables, args.clear_target)

        # Verify migration if requested
        if args.verify:
            if not migrator.verify_migration(tables):
                logger.error("Migration verification failed")
                return 1

        logger.info("Migration completed successfully!")
        return 0

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return 1

    finally:
        if migrator:
            migrator.cleanup_connections()

if __name__ == "__main__":
    sys.exit(main())