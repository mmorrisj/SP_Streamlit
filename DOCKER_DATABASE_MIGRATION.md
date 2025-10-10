# Docker & Database Migration Guide

This document explains the updated Docker setup and database connection patterns using modern SQLAlchemy 2.0.

## What Changed

### Before (Flask-SQLAlchemy)
```python
# Old pattern - Flask-SQLAlchemy
from backend.extensions import db
from backend.app import app

with app.app_context():
    results = db.session.query(Document).all()
```

### After (SQLAlchemy 2.0)
```python
# New pattern - Modern SQLAlchemy 2.0
from backend.database import get_session
from backend.models import Document

with get_session() as session:
    results = session.query(Document).all()
```

## Updated Files

### 1. Dockerfile (`streamlit/Dockerfile`)

**Changes:**
- ✅ Copies `backend/database.py` (modern connection manager)
- ✅ Copies `backend/models.py` (SQLAlchemy 2.0 models)
- ✅ Installs both streamlit and backend requirements
- ✅ Creates proper `__init__.py` files for imports
- ✅ Added health check
- ❌ Removed `backend/extensions.py` (Flask-SQLAlchemy - deprecated)
- ❌ Removed `backend/app.py` (Flask app - not needed for Streamlit)
- ❌ Removed `backend/routes.py` (Flask routes - not needed)

**New structure:**
```dockerfile
# Modern dependencies
COPY backend/database.py /app/backend/database.py
COPY backend/models.py /app/backend/models.py
COPY backend/config.yaml /app/backend/config.yaml
COPY backend/scripts /app/backend/scripts
```

### 2. Database Connection (`streamlit/db.py`)

**Before:**
```python
# Old - Direct engine creation
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_session():
    return SessionLocal()
```

**After:**
```python
# New - Import from centralized database manager
from backend.database import get_session, create_session, get_engine, health_check
```

**Benefits:**
- ✅ Connection pooling configured automatically
- ✅ Retry logic on connection failures
- ✅ Health monitoring built-in
- ✅ Environment-aware configuration (dev/prod)
- ✅ SSL support for production
- ✅ Proper connection cleanup

### 3. Model Imports

**Before:**
```python
from backend.scripts.models import Document, Category, Event
```

**After:**
```python
from backend.models import Document, Category, Subcategory, InitiatingCountry, RecipientCountry
```

**Changes:**
- Modern SQLAlchemy 2.0 declarative base
- Type hints with `Mapped[]`
- Proper relationship definitions with `back_populates`
- Consolidated models in single file

## Usage Patterns

### Pattern 1: Context Manager (Recommended)

```python
from backend.database import get_session
from backend.models import Document

# Automatic commit on success, rollback on error
with get_session() as session:
    documents = session.query(Document).filter(
        Document.salience == 'High'
    ).all()
    # Session automatically commits and closes
```

### Pattern 2: Manual Session Management

```python
from backend.database import create_session
from backend.models import Document

# Manual session - you must close it
session = create_session()
try:
    documents = session.query(Document).all()
    session.commit()
except Exception:
    session.rollback()
    raise
finally:
    session.close()
```

### Pattern 3: Engine Access (for raw SQL)

```python
from backend.database import get_engine
from sqlalchemy import text

engine = get_engine()

with engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM documents"))
    count = result.scalar()
```

## Docker Compose Setup

### Environment Variables

Required in `.env`:
```bash
# Database Connection
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password
POSTGRES_DB=softpower-db
DB_HOST=postgres_db  # Service name in docker-compose
DB_PORT=5432

# Connection Pool
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# Debugging (optional)
SQL_ECHO=false
SQL_ECHO_POOL=false
```

### Service Configuration

The `streamlit` service now properly connects to PostgreSQL:

```yaml
streamlit:
  build:
    context: .
    dockerfile: streamlit/Dockerfile
  environment:
    DB_HOST: postgres_db  # Links to 'db' service
  depends_on:
    - db
  networks:
    - softpower_net
```

## Migration Checklist

If you're updating existing code, follow this checklist:

### 1. Update Imports

```python
# ❌ Old
from backend.extensions import db
from backend.scripts.models import Document

# ✅ New
from backend.database import get_session
from backend.models import Document
```

### 2. Update Query Patterns

```python
# ❌ Old
session = get_session()  # Returns raw session
docs = session.query(Document).all()
session.close()

# ✅ New
with get_session() as session:
    docs = session.query(Document).all()
```

### 3. Update Raw SQL Queries

```python
# ❌ Old
from db import engine
result = engine.execute("SELECT * FROM documents")

# ✅ New
from backend.database import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    result = conn.execute(text("SELECT * FROM documents"))
```

### 4. Update Streamlit Pages

For each Streamlit page (e.g., `streamlit/pages/*.py`):

1. Update imports at top of file
2. Replace `db.session` with `get_session()` context manager
3. Test the page

Example:
```python
# In streamlit/pages/Daily_Events.py

# ✅ Modern imports
from backend.database import get_session
from backend.models import Document, EventSummary

# ✅ Modern query
with get_session() as session:
    events = session.query(EventSummary).filter(
        EventSummary.period_type == 'daily'
    ).all()
```

### 5. Rebuild Docker Containers

```bash
# Stop existing containers
docker-compose down

# Rebuild with new Dockerfile
docker-compose build streamlit

# Start services
docker-compose up -d

# Check logs
docker-compose logs streamlit
```

## Testing Database Connection

### From Host Machine

```bash
# Test connection
python -c "from backend.database import health_check; print('✅' if health_check() else '❌')"

# Test query
python -c "
from backend.database import get_session
from backend.models import Document
with get_session() as session:
    count = session.query(Document).count()
    print(f'Documents: {count}')
"
```

### From Docker Container

```bash
# Enter container
docker exec -it streamlit-app bash

# Test connection
python -c "from backend.database import health_check; print('✅' if health_check() else '❌')"

# Test import
python -c "from backend.models import Document; print('✅ Models loaded')"
```

### Health Check Endpoint

If your Streamlit app has a health check page, test it:

```bash
curl http://localhost:8501/_stcore/health
```

## Common Issues & Solutions

### Issue: ModuleNotFoundError: No module named 'backend.extensions'

**Cause:** Old code trying to import Flask-SQLAlchemy

**Solution:**
```python
# Remove this line:
from backend.extensions import db

# Replace with:
from backend.database import get_session
```

### Issue: ImportError: cannot import name 'Document' from 'backend.scripts.models'

**Cause:** Old models location

**Solution:**
```python
# Remove this line:
from backend.scripts.models import Document

# Replace with:
from backend.models import Document
```

### Issue: AttributeError: 'Session' object has no attribute 'query'

**Cause:** Not using context manager properly

**Solution:**
```python
# ❌ Wrong
session = get_session()
docs = session.query(Document).all()

# ✅ Correct
with get_session() as session:
    docs = session.query(Document).all()
```

### Issue: Connection pool exhausted

**Cause:** Not closing sessions properly

**Solution:**
Always use context manager (`with get_session() as session`) which automatically closes connections

### Issue: Can't connect to database from container

**Cause:** Wrong DB_HOST

**Solution:**
In `.env` for Docker:
```bash
DB_HOST=postgres_db  # Service name from docker-compose.yml
```

In `.env` for local development:
```bash
DB_HOST=localhost
```

## Performance Benefits

### Connection Pooling

The new setup uses connection pooling:
- **Pool size**: 10 connections (configurable)
- **Max overflow**: 20 additional connections (configurable)
- **Pool timeout**: 30 seconds (configurable)
- **Pool recycle**: 1 hour (prevents stale connections)
- **Pre-ping**: Validates connections before use

### Automatic Retry

Connection failures automatically retry (configurable):
- Default: 3 retries
- Delay: 1 second between retries

### Health Monitoring

Built-in health check function:
```python
from backend.database import health_check

if health_check():
    print("Database is healthy")
else:
    print("Database connection failed")
```

## Development Workflow

### Local Development (without Docker)

```bash
# 1. Start PostgreSQL
docker-compose up -d db

# 2. Set environment for local connection
export DB_HOST=localhost
export POSTGRES_USER=your_username
export POSTGRES_PASSWORD=your_password

# 3. Run Streamlit locally
cd streamlit
streamlit run app.py
```

### Docker Development

```bash
# 1. Build and start all services
docker-compose up -d --build

# 2. Watch logs
docker-compose logs -f streamlit

# 3. Rebuild after changes
docker-compose up -d --build streamlit
```

### Running Migrations

```bash
# Using docker-compose profile
docker-compose --profile migrate up migrate

# Or manually in container
docker exec -it streamlit-app bash
alembic upgrade head
```

## Next Steps

1. **Update all Streamlit pages** to use new imports
2. **Test each page** to ensure queries work
3. **Update query modules** (`streamlit/queries/*.py`)
4. **Test with Docker Compose** to ensure container connectivity
5. **Update CI/CD pipelines** to use new Dockerfile

## Additional Resources

- **Database Module**: `backend/database.py`
- **Models**: `backend/models.py`
- **Docker Setup**: `docker-compose.yml`
- **Main README**: `README.md`
