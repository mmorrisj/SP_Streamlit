"""
Database connection module for Streamlit application.
Uses modern SQLAlchemy 2.0 with centralized database management.
"""

from shared.database.database import get_session, create_session, get_engine, health_check
from contextlib import contextmanager

# Re-export the main functions for backwards compatibility
__all__ = ['get_session', 'create_session', 'get_engine', 'health_check']

# Legacy compatibility - if old code uses db.get_session() without context manager
def get_db_session():
    """
    Legacy function for backwards compatibility.

    DEPRECATED: Use get_session() context manager instead:
        with get_session() as session:
            # your code here

    Returns:
        Session object (must be closed manually)
    """
    return create_session()