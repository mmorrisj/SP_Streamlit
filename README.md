# Soft Power Analytics Platform

A comprehensive analytics platform for processing, analyzing, and visualizing diplomatic documents to identify patterns, events, and trends in soft power activities.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Setup](#setup)
4. [Core Functionality](#core-functionality)
5. [S3 & Embeddings](#s3--embeddings)
6. [Database Management](#database-management)
7. [Processing Pipeline](#processing-pipeline)
8. [Dashboard](#dashboard)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start

### 1. Start Database

```bash
# Start PostgreSQL with pgvector support
docker-compose up -d

# Initialize database
python -c "from backend.database import init_database; init_database()"

# Run migrations
alembic upgrade head
```

### 2. Start FastAPI Server (for S3 operations)

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r backend/requirements.txt

# Start API server (runs outside Docker with AWS credentials)
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start Streamlit Dashboard

```bash
cd sp_streamlit
streamlit run app.py
```

---

## Architecture

### High-Level Overview

```
┌──────────────┐         ┌──────────────┐         ┌───────────────┐
│    S3        │         │   FastAPI    │         │   Docker      │
│  Parquets    │────────>│   Server     │────────>│   PostgreSQL  │
│  JSONs       │   AWS   │   (Host)     │   SQL   │   + pgvector  │
└──────────────┘         └──────────────┘         └───────────────┘
                                │                          │
                                │                          │
                         ┌──────▼───────┐         ┌───────▼────────┐
                         │  Streamlit   │         │   LangChain    │
                         │  Dashboard   │         │   Vector Store │
                         └──────────────┘         └────────────────┘
```

**Key Components:**
- **PostgreSQL + pgvector**: Document storage, metadata, event summaries, embeddings
- **FastAPI**: S3 operations proxy (runs outside Docker with AWS credentials)
- **LangChain**: Vector store interface for semantic search
- **Streamlit**: Interactive analytics dashboard
- **Processing Scripts**: AI analysis, event detection, clustering

### Technology Stack

- **Backend**: SQLAlchemy 2.0, FastAPI, Celery (task queue)
- **Database**: PostgreSQL with pgvector extension
- **Frontend**: Streamlit
- **AI/ML**: OpenAI GPT models, sentence-transformers, HDBSCAN clustering
- **Cloud**: AWS S3 (document/embedding storage), boto3
- **Migrations**: Alembic

---

## Setup

### Prerequisites

- Python 3.9+
- Docker & Docker Compose
- AWS credentials (for S3 access)
- OpenAI API key (for AI processing)

### Environment Configuration

Create `.env` file:

```bash
# Database
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password
POSTGRES_DB=softpower-db
DB_HOST=localhost
DB_PORT=5432

# AWS
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=us-east-1

# API
API_URL=http://localhost:8000

# AI
CLAUDE_KEY=your_openai_key
```

### Install Dependencies

```bash
# Core dependencies
pip install -r requirements.txt

# Backend dependencies
pip install -r backend/requirements.txt

# Install specific packages if needed
pip install boto3 pyarrow pandas langchain langchain-community langchain-huggingface
```

### Database Initialization

```bash
# Start PostgreSQL with pgvector
docker-compose up -d

# Initialize database schema
python -c "from backend.database import init_database; init_database()"

# Run Alembic migrations
alembic upgrade head

# Verify connection
python -c "from backend.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"
```

---

## Core Functionality

### 1. Document Processing Pipeline

The system processes documents through multiple stages:

```
Raw Documents → AI Analysis → Event Detection → Clustering → Dashboard
```

#### Stage 1: Document Ingestion

```bash
# Import raw documents
python backend/scripts/atom.py
```

**What it does:**
- Ingests raw diplomatic documents
- Extracts basic metadata (title, date, source)
- Stores in `documents` table

#### Stage 2: AI Analysis

```bash
# Extract salience, categories, countries, projects
python backend/scripts/atom_extraction.py
```

**What it does:**
- Uses GPT-4 to analyze each document
- Extracts: salience score, category, subcategory, countries, projects, locations
- Updates `documents` table with AI-generated fields

#### Stage 3: Event Detection

```bash
# Group related documents into events
python backend/scripts/daily.py
```

**What it does:**
- Groups documents by date, country, and event name
- Creates daily event summaries
- Populates `event_summaries` table

#### Stage 4: Event Clustering

```bash
# Cluster similar events using embeddings
python backend/scripts/cluster_events.py
```

**What it does:**
- Generates embeddings for event summaries
- Uses HDBSCAN to cluster similar events
- Identifies larger patterns across time

---

## S3 & Embeddings

### S3 Document Processing

#### Process JSON Files from S3

```bash
# Process all unprocessed JSON files
python backend/scripts/dsr.py

# Check processing status
python backend/scripts/dsr.py --status

# Process specific files
python backend/scripts/dsr.py --s3-files file1.json file2.json

# Reprocess files
python backend/scripts/dsr.py --reprocess file1.json file2.json

# Process without embeddings
python backend/scripts/dsr.py --no-embed
```

**How it works:**
- Maintains `processed_files.json` tracker in S3
- Prevents duplicate processing
- Downloads JSON files from S3
- Extracts document data
- Loads into database
- Optionally generates embeddings

### Parquet Embeddings Migration

#### Prerequisites

1. **Start FastAPI server** (handles S3 operations):
   ```bash
   uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Configure AWS credentials** (on machine running FastAPI):
   ```bash
   aws configure
   # or set environment variables
   export AWS_ACCESS_KEY_ID=your_key
   export AWS_SECRET_ACCESS_KEY=your_secret
   ```

#### Migrate Embeddings from S3 Parquet to pgvector

```bash
# Basic migration (automatically skips processed files)
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix embeddings/ \
  --collection chunk_embeddings

# Dry run (test without writing)
python backend/scripts/s3_to_pgvector.py --dry-run

# Force reprocess all files
python backend/scripts/s3_to_pgvector.py --force

# Custom API URL
python backend/scripts/s3_to_pgvector.py --api-url http://your-host:8000

# View processed files
python backend/scripts/s3_to_pgvector.py view chunk_embeddings

# Reset tracker (allow reprocessing)
python backend/scripts/s3_to_pgvector.py reset chunk_embeddings --confirm
```

**Available Collections:**
- `chunk` - Document chunk embeddings
- `daily` - Daily event embeddings
- `weekly` - Weekly event embeddings
- `monthly` - Monthly event embeddings
- `yearly` - Yearly event embeddings

**How it works:**
1. FastAPI server (running on host with AWS credentials) handles S3 operations
2. Script calls FastAPI endpoints to list and download parquet files
3. Parquet files contain embeddings + document IDs
4. Script fetches document metadata from PostgreSQL
5. Inserts embeddings + metadata into LangChain pgvector tables
6. Tracks processed files locally to prevent duplicates

For detailed documentation, see: `backend/FASTAPI_S3_SETUP.md`

---

## Database Management

### Health Check

```bash
# Check database connection
python -c "from backend.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"
```

### Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1

# View migration history
alembic history
```

### Direct Database Access

```bash
# Connect to PostgreSQL
docker exec -it sp_streamlit_postgres_1 psql -U your_username -d softpower-db

# Common queries
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM event_summaries;
SELECT collection_id, COUNT(*) FROM langchain_pg_embedding GROUP BY collection_id;
```

---

## Processing Pipeline

### Full Pipeline Execution

Run the complete processing pipeline in order:

```bash
# 1. Document ingestion
python backend/scripts/atom.py

# 2. AI analysis (extract salience, categories, etc.)
python backend/scripts/atom_extraction.py

# 3. Daily summaries
python backend/scripts/daily.py

# 4. Event clustering
python backend/scripts/cluster_events.py

# 5. Generate embeddings (optional)
python backend/scripts/embeddings.py
```

### Individual Processing Scripts

#### Atom Extraction
```bash
# Process documents with AI analysis
python backend/scripts/atom_extraction.py

# Options:
# --batch-size N       # Process N documents at a time
# --start-date YYYY-MM-DD  # Only process from this date
```

#### Daily Event Summaries
```bash
# Generate daily event summaries
python backend/scripts/daily.py

# Groups documents by:
# - Date
# - Initiating country
# - Event name
```

#### Event Clustering
```bash
# Cluster events using HDBSCAN
python backend/scripts/cluster_events.py

# Parameters configurable in backend/config.yaml:
# - eps: Distance threshold
# - min_samples: Minimum cluster size
# - metric: Distance metric (cosine, euclidean)
```

---

## Dashboard

### Start Dashboard

```bash
cd sp_streamlit
streamlit run app.py
```

Access at: http://localhost:8501

### Dashboard Pages

1. **Overview** - High-level metrics and trends
2. **Daily Events** - Daily event timelines
3. **Weekly Rollup** - Weekly aggregated summaries
4. **Impactful Events** - Most salient events
5. **Materiality Trends** - Category/subcategory trends over time
6. **Materiality Comparison** - Compare countries by category
7. **Recipient Comparison** - Analyze recipient countries
8. **Analytics** - Advanced analytics and filtering
9. **Agent** - LangChain-powered Q&A over documents

### Dashboard Features

- **Interactive Filters**: Date range, countries, categories
- **Visualizations**: Time series, heatmaps, network graphs
- **Export**: Download data as CSV/Excel
- **Real-time Updates**: Refresh data from database
- **Semantic Search**: Query documents using LangChain + pgvector

---

## Configuration

### Main Configuration File

`backend/config.yaml` - Central configuration for all processing:

```yaml
# Database
db_path: './data/softpower.db'

# Date ranges
start_date: '2024-08-01'
report_months:
  - '2024-07'
  - '2024-08'
  # ...

# AI Models
aws:
  default_model: "gpt-4o-mini"

# Event clustering
cluster:
  threshold: 50
  eps: 0.55
  min_samples: 2

# Countries
influencers:
  - China
  - Russia
  - Iran
  # ...

recipients:
  - Egypt
  - Iraq
  - Saudi Arabia
  # ...

# Categories
categories:
  - Economic
  - Social
  - Military
  - Diplomacy

subcategories:
  - Trade
  - Infrastructure
  - Education
  # ...
```

### S3 Configuration

S3 settings in `backend/config.yaml`:

```yaml
directories:
  embeddings: './data/embeddings'
  event_summaries: './data/summaries/events'
```

S3 bucket: `morris-sp-bucket`

---

## FastAPI Endpoints

### Start API Server

```bash
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
```

### Available Endpoints

**API Documentation**: http://localhost:8000/docs

#### General S3
- `POST /s3/list` - List files in S3 bucket
- `POST /s3/download` - Download file content
- `POST /s3/upload` - Upload content to S3
- `GET /s3/download-to-file` - Download file to local path

#### Parquet Operations
- `POST /s3/parquet/list` - List parquet files
- `POST /s3/parquet/metadata` - Get parquet metadata
- `POST /s3/parquet/read` - Read parquet data
- `POST /s3/parquet/sample` - Get sample rows
- `POST /s3/parquet/validate` - Validate schema
- `POST /s3/parquet/extract-ids` - Extract document IDs
- `POST /s3/parquet/batch-metadata` - Batch metadata operations
- `GET /s3/parquet/download-binary` - Download full parquet file

#### AI Queries
- `POST /query` - Query GPT model
- `POST /material_query` - Material-specific queries

For detailed API documentation, see: `backend/FASTAPI_S3_SETUP.md`

---

## Troubleshooting

### Database Issues

**Issue**: Connection refused
```bash
# Check if PostgreSQL is running
docker ps

# Restart PostgreSQL
docker-compose restart postgres

# Check logs
docker-compose logs postgres
```

**Issue**: Migration errors
```bash
# Reset migrations
alembic downgrade base
alembic upgrade head

# If needed, recreate database
docker-compose down -v
docker-compose up -d
python -c "from backend.database import init_database; init_database()"
```

### S3 Access Issues

**Issue**: Access Denied
```bash
# Verify AWS credentials
aws s3 ls s3://morris-sp-bucket/

# Check environment variables
echo $AWS_ACCESS_KEY_ID
echo $AWS_SECRET_ACCESS_KEY

# Reconfigure
aws configure
```

**Issue**: FastAPI not accessible
```bash
# Check if FastAPI is running
curl http://localhost:8000/health

# Start FastAPI
uvicorn backend.api:app --host 0.0.0.0 --port 8000

# Check from Docker container
curl http://host.docker.internal:8000/health
```

### Embedding Issues

**Issue**: Out of memory
```bash
# Reduce batch size
python backend/scripts/s3_to_pgvector.py --embed-batch-size 10

# Process fewer files at once
python backend/scripts/s3_to_pgvector.py --files file1.parquet file2.parquet
```

**Issue**: Duplicate embeddings
```bash
# Check processed files
python backend/scripts/s3_to_pgvector.py view chunk_embeddings

# Reset tracker if needed
python backend/scripts/s3_to_pgvector.py reset chunk_embeddings --confirm
```

### Processing Script Issues

**Issue**: Import errors
```bash
# Ensure Python path is set
export PYTHONPATH=.

# Run from project root
cd /path/to/SP_Streamlit
python backend/scripts/atom.py
```

**Issue**: AI analysis failures
```bash
# Check OpenAI API key
echo $CLAUDE_KEY

# Verify model configuration in backend/config.yaml
# Reduce batch size if rate limited
```

---

## Development

### Project Structure

```
SP_Streamlit/
├── backend/
│   ├── api.py                      # FastAPI server
│   ├── api_client.py               # S3 API client
│   ├── database.py                 # Database setup
│   ├── models.py                   # SQLAlchemy models
│   ├── config.yaml                 # Main configuration
│   ├── scripts/
│   │   ├── atom.py                 # Document ingestion
│   │   ├── atom_extraction.py     # AI analysis
│   │   ├── daily.py                # Daily summaries
│   │   ├── cluster_events.py      # Event clustering
│   │   ├── dsr.py                  # S3 JSON processing
│   │   ├── s3_to_pgvector.py      # Parquet migration
│   │   └── embedding_vectorstore.py # LangChain stores
│   └── services/                   # Business logic
├── sp_streamlit/
│   ├── app.py                      # Main dashboard
│   ├── pages/                      # Dashboard pages
│   └── queries/                    # Database queries
├── data/
│   ├── processed_embeddings/       # Tracker files
│   ├── embeddings/                 # Local embeddings
│   └── summaries/                  # Generated summaries
├── alembic/                        # Database migrations
├── docker-compose.yml              # PostgreSQL setup
├── requirements.txt                # Python dependencies
├── .env                            # Environment variables
└── README.md                       # This file
```

### Adding New Features

#### Add New Document Field
1. Update `backend/models.py` Document model
2. Create migration: `alembic revision --autogenerate -m "add field"`
3. Apply migration: `alembic upgrade head`
4. Update extraction prompts in `backend/scripts/prompts.py`
5. Modify `atom_extraction.py` to extract new field

#### Add New Dashboard Page
1. Create page in `sp_streamlit/pages/NewPage.py`
2. Add query functions in `sp_streamlit/queries/`
3. Add chart functions in `sp_streamlit/charts/`
4. Page automatically appears in sidebar

---

## Performance Optimization

### Database
- Use indexes on frequently queried columns
- Connection pooling configured (pool_size=10, max_overflow=20)
- Batch operations for large inserts

### Processing
- Adjust batch sizes based on available memory
- Use `--no-embed` for faster document loading
- Process embeddings separately in off-peak hours

### S3 Operations
- Binary streaming for large files
- Pagination for file lists
- Local caching with tracker files

---

## Additional Resources

- **S3 & FastAPI Setup**: `backend/FASTAPI_S3_SETUP.md`
- **Migration Guide**: `backend/scripts/S3_PGVECTOR_MIGRATION.md`
- **Developer Guide**: `CLAUDE.md`
- **API Documentation**: http://localhost:8000/docs (when FastAPI is running)

---

## Support

For issues or questions:
1. Check this README and documentation files
2. Review logs: `docker-compose logs`
3. Check GitHub issues: https://github.com/anthropics/claude-code/issues
4. Verify configuration in `backend/config.yaml` and `.env`

---

## License

[Your License Here]
