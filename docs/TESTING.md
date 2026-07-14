# Testing Guide

This document describes the testing infrastructure for the SoftPower Analytics Dashboard project.

## Table of Contents

- [Overview](#overview)
- [Test Organization](#test-organization)
- [Running Tests](#running-tests)
- [Test Categories](#test-categories)
- [Writing Tests](#writing-tests)
- [CI/CD Integration](#cicd-integration)
- [Coverage Reports](#coverage-reports)
- [Best Practices](#best-practices)

## Overview

The project uses **pytest** as the primary testing framework with extensive fixtures, markers, and coverage reporting.

### Key Features

- **Organized test structure** with fixtures in `conftest.py`
- **Test categorization** using pytest markers (unit, integration, slow, llm, etc.)
- **Database fixtures** with automatic setup/teardown
- **API testing** with FastAPI test client
- **Coverage reporting** with pytest-cov
- **CI/CD integration** with GitHub Actions
- **Parallel test execution** with pytest-xdist

## Test Organization

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures and configuration
├── test_health.py           # Health/smoke tests
├── test_models.py           # Database model unit tests
├── test_api.py              # API integration tests
└── test_pipeline.py         # Pipeline processing tests
```

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov pytest-timeout pytest-xdist
```

### Basic Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_models.py

# Run specific test class
pytest tests/test_models.py::TestDocumentModel

# Run specific test function
pytest tests/test_models.py::TestDocumentModel::test_create_document_minimal
```

### Run Tests by Category

```bash
# Run only unit tests (fast, no external dependencies)
pytest -m unit

# Run only integration tests
pytest -m integration

# Run database tests
pytest -m database

# Run API tests
pytest -m api

# Run pipeline tests
pytest -m pipeline

# Exclude slow tests
pytest -m "not slow"

# Exclude LLM tests (expensive)
pytest -m "not llm"

# Combine markers
pytest -m "integration and not slow and not llm"
```

### Run Tests with Coverage

```bash
# Generate coverage report
pytest --cov=shared --cov=services --cov=server

# Generate HTML coverage report
pytest --cov --cov-report=html

# Open coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows

# Generate terminal report with missing lines
pytest --cov --cov-report=term-missing

# Generate XML report (for CI/CD)
pytest --cov --cov-report=xml
```

### Parallel Test Execution

```bash
# Run tests in parallel (faster)
pytest -n auto  # Auto-detect CPU cores

# Run with specific number of workers
pytest -n 4
```

### Advanced Options

```bash
# Stop on first failure
pytest -x

# Show local variables in tracebacks
pytest -l

# Re-run only failed tests
pytest --lf

# Run tests that failed last time, then all others
pytest --ff

# Show test duration
pytest --durations=10

# Run with specific timeout (prevent hanging tests)
pytest --timeout=300
```

## Test Categories

### Unit Tests (`@pytest.mark.unit`)

Fast tests with no external dependencies. Test individual functions and classes in isolation.

```python
@pytest.mark.unit
def test_document_repr(create_test_document):
    doc = create_test_document(doc_id="TEST002", title="My Test")
    repr_str = repr(doc)
    assert "TEST002" in repr_str
```

### Integration Tests (`@pytest.mark.integration`)

Tests that require external services like databases, APIs, or file systems.

```python
@pytest.mark.integration
@pytest.mark.database
def test_document_categories_relationship(db_session, create_test_document):
    doc = create_test_document(doc_id="CAT002")
    # Test database relationships
```

### Slow Tests (`@pytest.mark.slow`)

Tests that take longer than 1 second. Often excluded in rapid development cycles.

```python
@pytest.mark.slow
def test_large_batch_processing():
    # Process 10,000 records
    pass
```

### LLM Tests (`@pytest.mark.llm`)

Tests that make actual LLM API calls. These may incur costs and are typically mocked or skipped.

```python
@pytest.mark.llm
def test_llm_event_deconfliction():
    # Actual OpenAI API call
    pass
```

### Database Tests (`@pytest.mark.database`)

Tests requiring database connectivity.

```python
@pytest.mark.database
def test_database_health_check():
    from shared.database.database import health_check
    assert health_check() is True
```

## Writing Tests

### Using Fixtures

```python
def test_with_document(create_test_document):
    """create_test_document is a factory fixture."""
    doc = create_test_document(
        doc_id="TEST001",
        title="Test Document",
        salience=8
    )
    assert doc.doc_id == "TEST001"
```

### Database Session Fixtures

```python
def test_with_session(db_session):
    """db_session automatically rolls back after test."""
    from shared.models.models import Document

    doc = Document(doc_id="TEST", title="Test")
    db_session.add(doc)
    db_session.commit()

    # Automatically rolled back after test
```

### API Client Fixtures

```python
def test_api_endpoint(api_client):
    """api_client is a FastAPI TestClient."""
    response = api_client.get("/api/health")
    assert response.status_code == 200
```

### Mocking External Services

```python
def test_with_mock_s3(mock_s3_client):
    """Use mock S3 client instead of real AWS."""
    mock_s3_client.files["test.parquet"] = df
    result = mock_s3_client.list_parquet_files("bucket", "prefix")
    assert len(result) > 0
```

### Test Parameterization

```python
@pytest.mark.parametrize("salience,expected", [
    (8, True),
    (7, True),
    (4, False),
])
def test_salience_threshold(salience, expected):
    result = salience >= 7
    assert result == expected
```

## CI/CD Integration

> **Honest status (2026-07):** the workflows exist (`.github/workflows/ci.yml`, `cd.yml`,
> `release-registry.yml`) but CI is **non-blocking** and line coverage is low (~4% per the
> [maintainability assessment](MAINTAINABILITY_ASSESSMENT.md)). The coverage targets below
> are aspirational. This section replaces the former `CI_CD_SUMMARY.md`, which overstated
> maturity and was removed.

### GitHub Actions Workflow

The CI pipeline runs automatically on:
- Push to `main` or `develop` branches
- Pull requests to `main`

#### Test Jobs

1. **Unit Tests** - Fast tests, no external dependencies
2. **Integration Tests** - Tests with database (PostgreSQL service)
3. **Coverage Report** - Full test suite with coverage

#### Test Services

The CI uses GitHub Actions services to provide:
- **PostgreSQL with pgvector** - For database tests
- **Redis** - For caching tests (future)

### CI Environment Variables

The following are automatically configured in CI:

```yaml
POSTGRES_USER: testuser
POSTGRES_PASSWORD: testpass
POSTGRES_DB: testdb
POSTGRES_HOST: localhost
POSTGRES_PORT: 5432
DATABASE_URL: postgresql+psycopg2://testuser:testpass@localhost:5432/testdb
TESTING: 1
```

### Coverage Reports

Coverage reports are:
- **Uploaded to Codecov** - For historical tracking
- **Stored as artifacts** - Downloadable from GitHub Actions
- **Commented on PRs** - Automatic PR comments with coverage changes

## Coverage Reports

### Local Coverage

```bash
# Generate and view HTML coverage report
pytest --cov --cov-report=html
open htmlcov/index.html
```

### Coverage Configuration

Coverage is configured in [.coveragerc](../.coveragerc):

- **Source directories**: `shared/`, `services/`, `server/`
- **Omitted**: Tests, migrations, config files, Streamlit pages
- **Thresholds**: Configurable minimum coverage percentages

### Coverage Targets

- **Unit tests**: Aim for >80% coverage
- **Integration tests**: Focus on critical paths
- **Overall**: Maintain >70% coverage

## Best Practices

### 1. Test Naming

```python
# Good: Descriptive test names
def test_document_creation_with_valid_data():
    pass

def test_api_returns_404_for_nonexistent_document():
    pass

# Bad: Vague test names
def test_document():
    pass

def test_1():
    pass
```

### 2. Test Isolation

```python
# Good: Each test is independent
def test_create_document(db_session):
    doc = Document(doc_id="TEST001")
    db_session.add(doc)
    db_session.commit()
    # Session automatically rolled back

# Bad: Tests that depend on each other
def test_step_1():
    global document
    document = create_document()

def test_step_2():
    # Depends on test_step_1
    assert document.id is not None
```

### 3. Use Appropriate Markers

```python
# Mark slow tests
@pytest.mark.slow
def test_large_dataset_processing():
    pass

# Mark tests requiring external services
@pytest.mark.integration
@pytest.mark.database
def test_database_query():
    pass

# Mark expensive tests
@pytest.mark.llm
def test_openai_api_call():
    pass
```

### 4. Mock External Services

```python
# Good: Mock external API calls
@patch('services.pipeline.llm_client.OpenAI')
def test_llm_processing(mock_openai):
    mock_openai.return_value.chat.completions.create.return_value = mock_response
    result = process_with_llm("test input")
    assert result is not None

# Bad: Making real API calls in tests
def test_llm_processing():
    result = openai.ChatCompletion.create(...)  # Real API call!
```

### 5. Test Edge Cases

```python
def test_salience_validation():
    # Test normal cases
    assert is_valid_salience(5)

    # Test edge cases
    assert is_valid_salience(0)
    assert is_valid_salience(10)

    # Test invalid cases
    assert not is_valid_salience(-1)
    assert not is_valid_salience(11)
    assert not is_valid_salience("invalid")
```

### 6. Use Fixtures Appropriately

```python
# Good: Fixture provides reusable setup
@pytest.fixture
def sample_document_data():
    return {
        "doc_id": "TEST001",
        "title": "Test Document",
        "salience": 8
    }

def test_with_fixture(sample_document_data):
    doc = Document(**sample_document_data)
    assert doc.doc_id == "TEST001"

# Bad: Duplicating setup in every test
def test_1():
    data = {"doc_id": "TEST001", "title": "Test"}  # Duplicated
    doc = Document(**data)

def test_2():
    data = {"doc_id": "TEST002", "title": "Test"}  # Duplicated
    doc = Document(**data)
```

## Troubleshooting

### Database Connection Issues

```bash
# Check if PostgreSQL is running
docker ps  # For Docker
pg_isready  # For local PostgreSQL

# Set DATABASE_URL explicitly
export DATABASE_URL="postgresql://user:pass@localhost:5432/testdb"
pytest
```

### Import Errors

```bash
# Ensure project root is in Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest
```

### Slow Tests

```bash
# Identify slow tests
pytest --durations=10

# Skip slow tests during development
pytest -m "not slow"
```

### Fixture Not Found

```bash
# Ensure conftest.py is in tests/ directory
ls tests/conftest.py

# Check fixture scope and usage
pytest --fixtures  # List all available fixtures
```

## Contributing

When adding new features:

1. **Write tests first** (TDD approach recommended)
2. **Use appropriate markers** (`@pytest.mark.unit`, etc.)
3. **Maintain coverage** (>70% overall)
4. **Document complex tests** with docstrings
5. **Run tests before committing**: `pytest`
6. **Check coverage**: `pytest --cov`

## Additional Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-cov Documentation](https://pytest-cov.readthedocs.io/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [SQLAlchemy Testing](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)

## Questions?

For questions about testing:
- Check existing tests for examples
- Review [conftest.py](../tests/conftest.py) for available fixtures
- See [pytest.ini](../pytest.ini) for configuration
- Ask in GitHub Issues or PR discussions
