# backend/database.py - Complete database connection and session management
"""
Centralized database connection and session management for the SoftPower project.
Replaces Flask-SQLAlchemy with pure SQLAlchemy for better performance and flexibility.
"""

import os
import logging
from typing import Generator, Optional
from contextlib import contextmanager
from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the declarative base for models using SQLAlchemy 2.0 style
class Base(DeclarativeBase):
    pass

class DatabaseManager:
    """
    Centralized database connection manager with connection pooling,
    error handling, and health monitoring.
    """
    
    def __init__(self):
        self.engine: Optional[Engine] = None
        self.SessionLocal: Optional[sessionmaker] = None
        self._connection_retries = 3
        self._retry_delay = 1  # seconds
        self._setup_connection()
        self._setup_event_listeners()
    
    def _get_database_url(self) -> str:
        """
        Construct database URL from environment variables with fallbacks.
        Supports both development and production configurations.
        """
        # Primary environment variables (your current setup)
        db_host = os.getenv("DB_HOST", "localhost")
        db_user = os.getenv("POSTGRES_USER", "matthew50")
        db_pass = os.getenv("POSTGRES_PASSWORD", "softpower")
        db_name = os.getenv("POSTGRES_DB", "softpower-db")
        db_port = os.getenv("POSTGRES_PORT", "5432")
        
        # Alternative environment variable names (for flexibility)
        if not all([db_user, db_pass, db_name]):
            db_user = os.getenv("DATABASE_USER", db_user)
            db_pass = os.getenv("DATABASE_PASSWORD", db_pass)
            db_name = os.getenv("DATABASE_NAME", db_name)
        
        # Support for full DATABASE_URL (common in production)
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            # Handle postgres:// vs postgresql:// (common Heroku issue)
            if database_url.startswith("postgres://"):
                database_url = database_url.replace("postgres://", "postgresql://", 1)
            return database_url
        
        # Construct URL from components
        url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        logger.info(f"Database URL: postgresql://{db_user}:***@{db_host}:{db_port}/{db_name}")
        return url
    
    def _get_engine_options(self) -> dict:
        """
        Configure SQLAlchemy engine options for optimal performance and reliability.
        """
        # Base configuration
        options = {
            "echo": os.getenv("SQL_ECHO", "false").lower() == "true",
            "echo_pool": os.getenv("SQL_ECHO_POOL", "false").lower() == "true",
            "future": True,  # Use SQLAlchemy 2.0 style
        }
        
        # Connection pool configuration
        pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
        max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "20"))
        pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
        pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))  # 1 hour
        
        options.update({
            "poolclass": pool.QueuePool,
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": pool_timeout,
            "pool_recycle": pool_recycle,
            "pool_pre_ping": True,  # Validate connections before use
        })
        
        # Development vs Production settings
        if os.getenv("ENVIRONMENT") == "production":
            options.update({
                "connect_args": {
                    "sslmode": "require",
                    "connect_timeout": 10,
                    "application_name": "softpower-app",
                }
            })
        else:
            options.update({
                "connect_args": {
                    "connect_timeout": 10,
                    "application_name": "softpower-dev",
                }
            })
        
        return options
    
    def _setup_connection(self):
        """Initialize database engine and session factory with retry logic."""
        database_url = self._get_database_url()
        engine_options = self._get_engine_options()
        
        for attempt in range(self._connection_retries):
            try:
                self.engine = create_engine(database_url, **engine_options)
                
                # Test the connection - use text() for raw SQL
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                
                self.SessionLocal = sessionmaker(
                    bind=self.engine,
                    autoflush=True,
                    autocommit=False,
                    expire_on_commit=False
                )
                
                logger.info("Database connection established successfully")
                return
                
            except Exception as e:
                logger.error(f"Database connection attempt {attempt + 1} failed: {e}")
                if attempt < self._connection_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    raise ConnectionError(f"Failed to connect to database after {self._connection_retries} attempts: {e}")

    def _setup_event_listeners(self):
        """Setup SQLAlchemy event listeners for monitoring and logging."""
        
        @event.listens_for(self.engine, "connect")
        def set_postgresql_settings(dbapi_connection, connection_record):
            """Configure connection-level settings."""
            if self.engine.dialect.name == 'postgresql':
                with dbapi_connection.cursor() as cursor:
                    # Set timezone to UTC
                    cursor.execute("SET timezone TO 'UTC'")
        
        @event.listens_for(self.engine, "checkout")
        def checkout_listener(dbapi_connection, connection_record, connection_proxy):
            """Log connection checkout in debug mode."""
            if os.getenv("SQL_DEBUG") == "true":
                logger.debug("Connection checked out from pool")
        
        @event.listens_for(self.engine, "checkin")
        def checkin_listener(dbapi_connection, connection_record):
            """Log connection checkin in debug mode."""
            if os.getenv("SQL_DEBUG") == "true":
                logger.debug("Connection checked back into pool")
            
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions with automatic transaction handling.
        
        Usage:
            with db_manager.get_session() as session:
                # Your database operations
                session.add(obj)
                # Automatic commit on success, rollback on exception
        """
        if not self.SessionLocal:
            raise RuntimeError("Database not initialized. Call _setup_connection() first.")
        
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()
    
    def create_session(self) -> Session:
        """
        Create a new database session for manual management.
        
        Note: You must handle commit/rollback/close manually when using this method.
        Prefer get_session() context manager for automatic transaction handling.
        """
        if not self.SessionLocal:
            raise RuntimeError("Database not initialized. Call _setup_connection() first.")
        
        return self.SessionLocal()
    
    def health_check(self) -> bool:
        """
        Perform a health check on the database connection.
        
        Returns:
            bool: True if database is accessible, False otherwise
        """
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    def get_pool_status(self) -> dict:
        """
        Get current connection pool status for monitoring.
        
        Returns:
            dict: Pool statistics including size, checked out connections, etc.
        """
        if not self.engine:
            return {"error": "Engine not initialized"}
        
        pool = self.engine.pool
        return {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "checked_in": pool.checkedin(),
        }
    
    def close_all_connections(self):
        """Close all database connections and dispose of the engine."""
        if self.engine:
            self.engine.dispose()
            logger.info("All database connections closed")
    
    def recreate_connection(self):
        """Recreate the database connection (useful for connection recovery)."""
        logger.info("Recreating database connection...")
        self.close_all_connections()
        self._setup_connection()

# Global database manager instance
db_manager = DatabaseManager()

# Convenience functions for backward compatibility and ease of use
def get_session() -> Generator[Session, None, None]:
    """
    Convenience function to get a database session context manager.
    
    Usage:
        with get_session() as session:
            # Your database operations
    """
    return db_manager.get_session()

def create_session() -> Session:
    """
    Convenience function to create a new session for manual management.
    
    Note: Remember to commit/rollback and close the session manually.
    """
    return db_manager.create_session()

def get_engine() -> Engine:
    """Get the SQLAlchemy engine instance."""
    return db_manager.engine

def health_check() -> bool:
    """Perform a database health check."""
    return db_manager.health_check()

def get_pool_status() -> dict:
    """Get connection pool status."""
    return db_manager.get_pool_status()

# Database initialization and management functions
def init_database():
    """
    Initialize database tables.
    This should be called after all models are imported.
    """
    try:
        # Import models to ensure all models are registered
        from backend.models import Document, Category, Subcategory, InitiatingCountry, RecipientCountry, Project, Citation
        
        Base.metadata.create_all(db_manager.engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

def drop_database():
    """
    Drop all database tables. Use with caution!
    """
    try:
        # Import models to ensure all models are registered
        from backend.models import Document, Category, Subcategory, InitiatingCountry, RecipientCountry, Project, Citation
        
        Base.metadata.drop_all(db_manager.engine)
        logger.info("Database tables dropped successfully")
    except Exception as e:
        logger.error(f"Failed to drop database: {e}")
        raise

# Session decorator for functions that need database access
def with_session(func):
    """
    Decorator to provide a database session to a function.
    
    Usage:
        @with_session
        def my_function(session, other_args):
            # Use session for database operations
    """
    def wrapper(*args, **kwargs):
        with get_session() as session:
            return func(session, *args, **kwargs)
    return wrapper

# Error handling utilities
class DatabaseError(Exception):
    """Custom exception for database-related errors."""
    pass

def handle_db_error(func):
    """
    Decorator to handle common database errors gracefully.
    
    Usage:
        @handle_db_error
        def my_db_function():
            # Database operations that might fail
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DisconnectionError:
            logger.warning("Database disconnection detected, attempting to reconnect...")
            db_manager.recreate_connection()
            return func(*args, **kwargs)  # Retry once
        except SQLAlchemyError as e:
            logger.error(f"Database error in {func.__name__}: {e}")
            raise DatabaseError(f"Database operation failed: {e}")
    return wrapper

# Environment validation
def validate_environment():
    """
    Validate that required environment variables are set.
    Should be called during application startup.
    """
    required_vars = ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars and not os.getenv("DATABASE_URL"):
        raise EnvironmentError(
            f"Missing required environment variables: {missing_vars}. "
            "Either set these variables or provide DATABASE_URL."
        )
    
    logger.info("Environment validation passed")

# Export the Base for model definitions
__all__ = [
    'Base',
    'db_manager', 
    'get_session', 
    'create_session', 
    'get_engine',
    'init_database',
    'drop_database',
    'health_check',
    'get_pool_status',
    'with_session',
    'handle_db_error',
    'validate_environment',
    'DatabaseError'
]