# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development Server
```bash
# Run Streamlit dashboard
cd sp_streamlit
streamlit run app.py

# Test database connection
python test_db.py
```

### Database Management
```bash
# Initialize database (creates all tables)
python -c "from backend.database import init_database; init_database()"

# Run Alembic migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Database health check
python -c "from backend.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"
```

### Docker
```bash
# Start PostgreSQL with pgvector support
docker-compose up -d

# Stop services
docker-compose down
```

### Backend Processing Scripts
```bash
# Run individual processing scripts
python backend/scripts/atom_extraction.py
python backend/scripts/daily.py
python backend/scripts/cluster_events.py
python backend/scripts/embeddings.py

# Full processing pipeline (run in order)
python backend/scripts/atom.py           # Document ingestion
python backend/scripts/atom_extraction.py  # AI analysis
python backend/scripts/daily.py         # Daily summaries
python backend/scripts/cluster_events.py   # Event clustering
```

## Architecture

### High-Level Overview
This is a **Soft Power Analytics Dashboard** that processes diplomatic documents through an AI/ML pipeline and provides interactive visualizations. The system analyzes international relations documents to identify patterns, events, and trends in soft power activities.

**Data Flow**: Raw Documents → AI Analysis → Event Detection → Clustering → Dashboard Visualization

### Technology Stack
- **Backend**: SQLAlchemy 2.0 (recently migrated from Flask-SQLAlchemy)
- **Database**: PostgreSQL with pgvector extension for embeddings
- **Frontend**: Streamlit for interactive dashboards
- **AI/ML**: OpenAI GPT models, sentence-transformers, HDBSCAN clustering
- **Migrations**: Alembic for database schema management

### Database Architecture

**Core Entity**: `Document` - Central table containing diplomatic documents with AI-generated analysis

**Normalized Relationships** (many-to-many):
- `categories` / `subcategories` - Document classification
- `initiating_countries` / `recipient_countries` - Geographic relationships
- `projects` - Associated initiatives
- `events` - Clustered event associations

**Key Processing Tables**:
- `events` - Clustered document groups representing real-world events
- `event_summaries` - AI-generated event descriptions
- `embeddings` - Vector representations for similarity analysis

### Processing Pipeline Architecture

1. **Document Ingestion** (`atom.py`): Raw document import and preprocessing
2. **AI Analysis** (`atom_extraction.py`): GPT-4 extracts salience, categories, countries, projects
3. **Event Detection** (`daily.py`): Groups related documents into events
4. **Clustering** (`cluster_events.py`): Uses embeddings + HDBSCAN to identify event clusters
5. **Summarization** (`event_summary.py`): Generates human-readable event descriptions
6. **Dashboard** (`app.py`): Streamlit visualization of trends and patterns

### Configuration Management

**Primary Config**: `backend/config.yaml` - Central configuration for all processing parameters
- Database paths and credentials
- AI model settings (GPT-4, embeddings models)
- Processing thresholds and date ranges
- Country/category taxonomies

**Environment Variables**: `.env` file for sensitive data
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `CLAUDE_KEY` (for AI processing)
- Database connection parameters

## Development Patterns

### Database Session Management
The project uses SQLAlchemy 2.0 with centralized session management:

```python
# Preferred: Context manager (auto-commit/rollback)
from backend.database import get_session
with get_session() as session:
    documents = session.query(Document).filter(...).all()
    # Automatic commit on success, rollback on exception

# Alternative: Manual session management
from backend.database import create_session
session = create_session()
try:
    # operations
    session.commit()
except Exception:
    session.rollback()
finally:
    session.close()
```

**Important**: The codebase is mid-migration from Flask-SQLAlchemy to pure SQLAlchemy 2.0. Some scripts still use the old Flask patterns in `backend/scripts/models.py`, while newer code uses the modern patterns in `backend/models.py`.

### Script Execution Patterns
Backend processing scripts are designed to run independently or as part of a pipeline:

```python
# Most scripts follow this pattern:
def main():
    with get_session() as session:
        # Load config
        config = load_yaml_config('backend/config.yaml')
        # Process data
        results = process_documents(session, config)
        # Auto-commit via context manager

if __name__ == "__main__":
    main()
```

### Configuration Access
```python
import yaml
with open('backend/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Common config sections:
start_date = config['start_date']
models = config['event_models']
countries = config['influencers']
db_path = config['db_path']
```

### Model Relationships
When working with normalized data, use SQLAlchemy relationships:

```python
# Get all categories for a document
doc = session.get(Document, doc_id)
categories = [cat.category for cat in doc.categories]

# Get all documents in a category
from sqlalchemy import text
docs = session.execute(
    text("SELECT d.* FROM documents d JOIN categories c ON d.doc_id = c.doc_id WHERE c.category = :cat"),
    {"cat": "Economic"}
).fetchall()
```

### Common Development Tasks

**Adding New Analysis Fields**:
1. Update `backend/models.py` Document model
2. Create Alembic migration: `alembic revision --autogenerate -m "add new field"`
3. Update extraction prompts in `backend/scripts/prompts.py`
4. Modify `atom_extraction.py` to extract new field

**Adding New Visualizations**:
1. Create query function in `sp_streamlit/queries/`
2. Create chart function in `sp_streamlit/charts/`
3. Add to `sp_streamlit/app.py` main dashboard

**Performance Considerations**:
- Use `session.execute()` with raw SQL for complex analytical queries
- Connection pooling is configured in `backend/database.py` (pool_size=10, max_overflow=20)
- Large batch operations should use `session.bulk_insert_mappings()` or `session.bulk_update_mappings()`

### Environment Setup
```bash
# Install Python dependencies
pip install -r requirements.txt
pip install -r backend/requirements.txt

# Set up PostgreSQL with pgvector
docker-compose up -d

# Configure environment
cp .env.example .env  # Edit with your credentials

# Initialize database
python -c "from backend.database import init_database; init_database()"
```