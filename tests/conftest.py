"""
Pytest fixtures and configuration for SoftPower project tests.
"""
import os
import sys
import pytest
from typing import Generator
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set testing environment variable
os.environ["TESTING"] = "1"
os.environ["SQL_ECHO"] = "false"


# ===========================================
# Session Scope Fixtures (once per test session)
# ===========================================

@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Get test database URL from environment or use default."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://testuser:testpass@localhost:5432/testdb"
    )


@pytest.fixture(scope="session")
def database_available(test_database_url: str) -> bool:
    """Check if test database is available."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(test_database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception as e:
        print(f"Database not available: {e}")
        return False


# ===========================================
# Database Fixtures
# ===========================================

@pytest.fixture(scope="function")
def db_engine(test_database_url: str, database_available: bool):
    """Create a test database engine."""
    if not database_available:
        pytest.skip("Database not available")

    from sqlalchemy import create_engine
    from shared.database.database import Base

    engine = create_engine(
        test_database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10
    )

    # Create all tables
    Base.metadata.create_all(engine)

    yield engine

    # Cleanup: drop all tables after test
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create a test database session with automatic rollback."""
    from sqlalchemy.orm import sessionmaker, Session

    SessionLocal = sessionmaker(bind=db_engine)
    session: Session = SessionLocal()

    yield session

    # Rollback any uncommitted changes
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def clean_db_session(db_engine):
    """
    Create a clean database session that commits changes.
    Use this when you need to test actual database persistence.
    """
    from sqlalchemy.orm import sessionmaker, Session

    SessionLocal = sessionmaker(bind=db_engine)
    session: Session = SessionLocal()

    yield session

    session.close()


# ===========================================
# Model Fixtures
# ===========================================

@pytest.fixture
def sample_document_data() -> dict:
    """Sample document data for testing.
    Fields must match Document model columns in shared/models/models.py.
    """
    return {
        "doc_id": "TEST001",
        "title": "Test Document",
        "distilled_text": "This is a test document about China's diplomatic activities in Africa.",
        "date": "2024-08-01",
        "salience": "8",
        "salience_bool": "True",
        "initiating_country": "China",
        "recipient_country": "Kenya",
        "category": "Economic",
        "subcategory": "Infrastructure",
        "location": "Nairobi",
        "event_name": "China-Kenya Infrastructure Summit"
    }


@pytest.fixture
def create_test_document(db_session):
    """Factory fixture to create test documents."""
    from shared.models.models import Document

    def _create_document(**kwargs) -> Document:
        """Create and persist a test document."""
        defaults = {
            "doc_id": "TEST001",
            "title": "Test Document",
            "distilled_text": "Test content",
            "date": "2024-08-01",
            "salience": "5",
            "salience_bool": "False"
        }
        defaults.update(kwargs)

        doc = Document(**defaults)
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)
        return doc

    return _create_document


# ===========================================
# API Fixtures
# ===========================================

@pytest.fixture(scope="function")
def api_client():
    """Create FastAPI test client."""
    try:
        from fastapi.testclient import TestClient
        from server.main import app
        return TestClient(app)
    except Exception as e:
        pytest.skip(f"FastAPI app not available: {e}")


@pytest.fixture(scope="function")
def authenticated_api_client(api_client):
    """
    Create authenticated API client.
    Modify this fixture based on your authentication mechanism.
    """
    # Add authentication headers if needed
    # api_client.headers.update({"Authorization": "Bearer test_token"})
    return api_client


# ===========================================
# Configuration Fixtures
# ===========================================

@pytest.fixture(scope="session")
def test_config():
    """Load test configuration."""
    import yaml
    config_path = PROJECT_ROOT / "shared" / "config" / "config.yaml"

    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    return {}


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response for testing."""
    return {
        "choices": [
            {
                "message": {
                    "content": '{"salience": 8, "category": "Economic", "summary": "Test summary"}'
                }
            }
        ]
    }


# ===========================================
# S3 Fixtures
# ===========================================

@pytest.fixture
def mock_s3_client(monkeypatch):
    """Mock S3 client for testing without AWS."""
    class MockS3Client:
        def __init__(self):
            self.files = {}

        def list_parquet_files(self, bucket: str, prefix: str, **kwargs):
            return [f for f in self.files.keys() if f.startswith(prefix)]

        def upload_parquet(self, df, bucket: str, key: str):
            self.files[key] = df
            return {"success": True}

        def download_parquet_as_dataframe(self, bucket: str, key: str):
            return self.files.get(key)

    client = MockS3Client()

    # Mock the get_s3_api_client function
    monkeypatch.setattr(
        "services.pipeline.embeddings.s3.get_s3_api_client",
        lambda: client
    )

    return client


# ===========================================
# Embedding Fixtures
# ===========================================

@pytest.fixture
def mock_embedding_model(monkeypatch):
    """Mock sentence transformer model for testing."""
    import numpy as np

    class MockEmbedder:
        def encode(self, texts, **kwargs):
            """Return random embeddings."""
            if isinstance(texts, str):
                return np.random.rand(384)
            return np.random.rand(len(texts), 384)

    return MockEmbedder()


# ===========================================
# Utility Fixtures
# ===========================================

@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directory for test files."""
    data_dir = tmp_path / "test_data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def capture_logs():
    """Capture log messages during tests."""
    import logging
    from io import StringIO

    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.INFO)

    logger = logging.getLogger()
    logger.addHandler(handler)

    yield log_stream

    logger.removeHandler(handler)


# ===========================================
# Cleanup Fixtures
# ===========================================

@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment after each test."""
    original_env = os.environ.copy()

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# ===========================================
# Markers Setup
# ===========================================

def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-llm-tests",
        action="store_true",
        default=False,
        help="Run LLM tests (may incur API costs)"
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as unit test (fast, no external dependencies)"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow-running"
    )
    config.addinivalue_line(
        "markers", "llm: mark test as requiring LLM API calls"
    )


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests based on naming conventions."""
    for item in items:
        # Mark integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)

        # Mark database tests
        if "database" in item.nodeid or "db_" in item.name:
            item.add_marker(pytest.mark.database)

        # Mark API tests
        if "api" in item.nodeid or "test_api" in item.name:
            item.add_marker(pytest.mark.api)
