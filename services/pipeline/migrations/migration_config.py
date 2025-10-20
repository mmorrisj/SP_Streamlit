#!/usr/bin/env python3
"""
Migration Configuration and Helper Functions

This module provides configuration management and helper functions
for PostgreSQL database migrations.
"""

import os
from typing import Dict, Optional, List
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    """Database configuration class."""
    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def connection_url(self) -> str:
        """Generate PostgreSQL connection URL."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    def __str__(self) -> str:
        """String representation with hidden password."""
        return f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.database}"


@dataclass
class MigrationConfig:
    """Migration configuration settings."""
    source_db: DatabaseConfig
    target_db: DatabaseConfig
    batch_size: int = 1000
    tables_to_migrate: Optional[List[str]] = None
    clear_target_tables: bool = False
    verify_after_migration: bool = True
    create_target_schema: bool = False
    log_level: str = "INFO"


def get_database_config_from_env(prefix: str = "") -> DatabaseConfig:
    """
    Create DatabaseConfig from environment variables.

    Args:
        prefix: Environment variable prefix (e.g., 'SOURCE_' or 'TARGET_')

    Returns:
        DatabaseConfig object
    """
    return DatabaseConfig(
        host=os.getenv(f"{prefix}DB_HOST", "localhost"),
        port=int(os.getenv(f"{prefix}DB_PORT", "5432")),
        user=os.getenv(f"{prefix}POSTGRES_USER", "postgres"),
        password=os.getenv(f"{prefix}POSTGRES_PASSWORD", ""),
        database=os.getenv(f"{prefix}POSTGRES_DB", "postgres")
    )


def get_migration_config_from_env() -> MigrationConfig:
    """
    Create MigrationConfig from environment variables.

    Environment variables:
        SOURCE_DB_HOST, SOURCE_DB_PORT, SOURCE_POSTGRES_USER, etc.
        TARGET_DB_HOST, TARGET_DB_PORT, TARGET_POSTGRES_USER, etc.
        MIGRATION_BATCH_SIZE
        MIGRATION_TABLES (comma-separated)
        MIGRATION_CLEAR_TARGET (true/false)
        MIGRATION_VERIFY (true/false)
        MIGRATION_CREATE_SCHEMA (true/false)
        MIGRATION_LOG_LEVEL
    """
    source_db = get_database_config_from_env("SOURCE_")
    target_db = get_database_config_from_env("TARGET_")

    # Parse tables list
    tables_str = os.getenv("MIGRATION_TABLES")
    tables = [t.strip() for t in tables_str.split(",")] if tables_str else None

    return MigrationConfig(
        source_db=source_db,
        target_db=target_db,
        batch_size=int(os.getenv("MIGRATION_BATCH_SIZE", "1000")),
        tables_to_migrate=tables,
        clear_target_tables=os.getenv("MIGRATION_CLEAR_TARGET", "false").lower() == "true",
        verify_after_migration=os.getenv("MIGRATION_VERIFY", "true").lower() == "true",
        create_target_schema=os.getenv("MIGRATION_CREATE_SCHEMA", "false").lower() == "true",
        log_level=os.getenv("MIGRATION_LOG_LEVEL", "INFO").upper()
    )


# Predefined database configurations for common scenarios
COMMON_CONFIGS = {
    "local_to_local": MigrationConfig(
        source_db=DatabaseConfig("localhost", 5432, "postgres", "password", "source_db"),
        target_db=DatabaseConfig("localhost", 5432, "postgres", "password", "target_db"),
        batch_size=1000,
        verify_after_migration=True
    ),

    "local_to_docker": MigrationConfig(
        source_db=DatabaseConfig("localhost", 5432, "postgres", "password", "source_db"),
        target_db=DatabaseConfig("localhost", 5433, "postgres", "password", "target_db"),
        batch_size=1000,
        verify_after_migration=True
    ),

    "production_backup": MigrationConfig(
        source_db=DatabaseConfig("prod-host", 5432, "prod_user", "prod_pass", "prod_db"),
        target_db=DatabaseConfig("backup-host", 5432, "backup_user", "backup_pass", "backup_db"),
        batch_size=5000,
        verify_after_migration=True,
        create_target_schema=True
    )
}


def get_sp_project_config() -> MigrationConfig:
    """
    Get configuration specific to the SP_Streamlit project.
    This uses the existing database configuration from your project.
    """
    # Use your existing configuration pattern
    source_db = DatabaseConfig(
        host=os.getenv("SOURCE_DB_HOST", "localhost"),
        port=int(os.getenv("SOURCE_DB_PORT", "5432")),
        user=os.getenv("SOURCE_POSTGRES_USER", "matthew50"),
        password=os.getenv("SOURCE_POSTGRES_PASSWORD", "softpower"),
        database=os.getenv("SOURCE_POSTGRES_DB", "softpower-db")
    )

    target_db = DatabaseConfig(
        host=os.getenv("TARGET_DB_HOST", "localhost"),
        port=int(os.getenv("TARGET_DB_PORT", "5433")),  # Different port for target
        user=os.getenv("TARGET_POSTGRES_USER", "matthew50"),
        password=os.getenv("TARGET_POSTGRES_PASSWORD", "softpower"),
        database=os.getenv("TARGET_POSTGRES_DB", "softpower-db-new")
    )

    return MigrationConfig(
        source_db=source_db,
        target_db=target_db,
        batch_size=1000,
        verify_after_migration=True,
        create_target_schema=True
    )


# Table groups for selective migration
TABLE_GROUPS = {
    "core_documents": [
        "documents",
        "categories",
        "subcategories",
        "initiating_countries",
        "recipient_countries",
        "projects",
        "raw_events",
        "citations"
    ],

    "event_summaries": [
        "period_summaries",
        "event_summaries",
        "event_source_links"
    ],

    "all_tables": [
        "documents",
        "categories",
        "subcategories",
        "initiating_countries",
        "recipient_countries",
        "projects",
        "raw_events",
        "citations",
        "period_summaries",
        "event_summaries",
        "event_source_links"
    ]
}


def validate_config(config: MigrationConfig) -> List[str]:
    """
    Validate migration configuration.

    Args:
        config: MigrationConfig to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Check source database config
    if not config.source_db.host:
        errors.append("Source database host is required")
    if not config.source_db.user:
        errors.append("Source database user is required")
    if not config.source_db.password:
        errors.append("Source database password is required")
    if not config.source_db.database:
        errors.append("Source database name is required")

    # Check target database config
    if not config.target_db.host:
        errors.append("Target database host is required")
    if not config.target_db.user:
        errors.append("Target database user is required")
    if not config.target_db.password:
        errors.append("Target database password is required")
    if not config.target_db.database:
        errors.append("Target database name is required")

    # Check if source and target are the same
    if (config.source_db.host == config.target_db.host and
        config.source_db.port == config.target_db.port and
        config.source_db.database == config.target_db.database):
        errors.append("Source and target databases cannot be the same")

    # Validate batch size
    if config.batch_size <= 0:
        errors.append("Batch size must be greater than 0")

    # Validate table names if specified
    if config.tables_to_migrate:
        valid_tables = set(TABLE_GROUPS["all_tables"])
        invalid_tables = set(config.tables_to_migrate) - valid_tables
        if invalid_tables:
            errors.append(f"Invalid table names: {invalid_tables}")

    return errors


def print_config_summary(config: MigrationConfig):
    """Print a summary of the migration configuration."""
    print("="*60)
    print("MIGRATION CONFIGURATION SUMMARY")
    print("="*60)
    print(f"Source Database: {config.source_db}")
    print(f"Target Database: {config.target_db}")
    print(f"Batch Size: {config.batch_size:,}")
    print(f"Tables to Migrate: {config.tables_to_migrate or 'All tables'}")
    print(f"Clear Target Tables: {config.clear_target_tables}")
    print(f"Verify After Migration: {config.verify_after_migration}")
    print(f"Create Target Schema: {config.create_target_schema}")
    print(f"Log Level: {config.log_level}")
    print("="*60)


# Example usage and testing functions
def create_sample_env_file():
    """Create a sample .env file for migration configuration."""
    sample_env = """
# Source Database Configuration
SOURCE_DB_HOST=localhost
SOURCE_DB_PORT=5432
SOURCE_POSTGRES_USER=postgres
SOURCE_POSTGRES_PASSWORD=your_source_password
SOURCE_POSTGRES_DB=source_database

# Target Database Configuration
TARGET_DB_HOST=localhost
TARGET_DB_PORT=5433
TARGET_POSTGRES_USER=postgres
TARGET_POSTGRES_PASSWORD=your_target_password
TARGET_POSTGRES_DB=target_database

# Migration Settings
MIGRATION_BATCH_SIZE=1000
MIGRATION_TABLES=documents,categories,subcategories
MIGRATION_CLEAR_TARGET=false
MIGRATION_VERIFY=true
MIGRATION_CREATE_SCHEMA=true
MIGRATION_LOG_LEVEL=INFO
"""

    with open("migration.env.sample", "w") as f:
        f.write(sample_env.strip())

    print("Sample environment file created: migration.env.sample")
    print("Copy this to .env and update with your actual database credentials.")


if __name__ == "__main__":
    # Demo the configuration system
    print("Migration Configuration System Demo")
    print("-" * 40)

    # Show SP project config
    sp_config = get_sp_project_config()
    print_config_summary(sp_config)

    # Validate config
    errors = validate_config(sp_config)
    if errors:
        print("Configuration Errors:")
        for error in errors:
            print(f"  • {error}")
    else:
        print("✓ Configuration is valid")

    # Create sample env file
    print("\nCreating sample environment file...")
    create_sample_env_file()