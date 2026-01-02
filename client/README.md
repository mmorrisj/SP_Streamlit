# Soft Power Analytics Web Application

Modern React + TypeScript + Vite web application for visualizing diplomatic soft power analytics.

## Table of Contents
- [Quick Start](#quick-start)
- [Development Setup](#development-setup)
- [Production Deployment](#production-deployment)
- [Data Population Pipeline](#data-population-pipeline)
- [Environment Configuration](#environment-configuration)
- [Architecture](#architecture)

---

## Quick Start

### Development Mode (Recommended for Development)

```bash
# 1. Install dependencies
cd client
npm install

# 2. Start development server (with hot reload)
npm run dev
# Opens at http://localhost:5000

# 3. In separate terminal, start FastAPI backend
cd ../server
uvicorn main:app --host 0.0.0.0 --port 5001 --reload
# API available at http://localhost:8000/api
```

### Production Mode

```bash
# 1. Build React app
cd client
npm run build
# Creates optimized bundle in client/dist/

# 2. Start production server (serves React + API)
cd ../server
uvicorn main:app --host 0.0.0.0 --port 5001
# Full app available at http://localhost:8000
```

---

## Development Setup

### Prerequisites

- **Node.js**: v18+ (for React/Vite)
- **Python**: 3.11+ (for FastAPI backend)
- **PostgreSQL**: 14+ with pgvector extension
- **AWS Account**: For S3 document storage (optional)

### 1. Install Dependencies

```bash
# Frontend dependencies
cd client
npm install

# Backend dependencies (if not already installed)
cd ..
pip install -r requirements.txt
```

### 2. Environment Variables

Create `.env` file in project root:

```bash
# Database
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=softpower_db
DB_HOST=localhost
DB_PORT=5432

# OpenAI API (used via CLAUDE_KEY env var)
CLAUDE_KEY=your_openai_api_key

# AWS S3 (optional - for document storage)
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
S3_BUCKET=your-bucket-name
S3_REGION=us-east-1

# API Configuration
API_URL=http://localhost:8000
```

### 3. Database Setup

```bash
# Initialize database schema
python -c "from shared.database.database import init_database; init_database()"

# Run Alembic migrations
alembic upgrade head

# Verify connection
python -c "from shared.database.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"
```

### 4. Start Development Servers

**Terminal 1 - Frontend (Hot Reload)**
```bash
cd client
npm run dev
# http://localhost:5000
```

**Terminal 2 - Backend API**
```bash
cd server
uvicorn main:app --host 0.0.0.0 --port 5001 --reload
# http://localhost:8000/api
```

**API Proxy Configuration**: In development mode, Vite proxies `/api/*` requests to `http://localhost:8000`. See [vite.config.ts](vite.config.ts) for proxy settings.

### Available Scripts

```bash
npm run dev       # Start dev server with hot reload
npm run build     # Build for production
npm run preview   # Preview production build locally
npm run lint      # Run ESLint
```

---

## Production Deployment

### Option 1: Unified Production Server (Recommended)

The production server serves both the React frontend and FastAPI backend from a single process.

```bash
# 1. Build React app
cd client
npm run build

# 2. Start unified server
cd ../server
uvicorn main:app --host 0.0.0.0 --port 5001

# Access full app at http://localhost:8000
# API endpoints at http://localhost:8000/api/*
```

**How it works**: [server/main.py](../server/main.py) uses FastAPI's `StaticFiles` to serve `client/dist/` at root and API routes at `/api/*`.

### Option 2: Docker Deployment

```bash
# Start full stack (React frontend + FastAPI + PostgreSQL + Redis)
docker-compose up -d

# Access web app at http://localhost:8000
# Dashboard at http://localhost:8501 (Streamlit)
```
n### Option 3: Full Docker Build (No Host Dependencies)

Build React **inside Docker** using multi-stage build. No Node.js required on host.

```bash
# Build and start all services (builds React in Docker)
docker-compose -f docker-compose.build.yml up -d --build

# Run database migrations
docker-compose -f docker-compose.build.yml --profile migrate up

# Access web app at http://localhost:8000
# Dashboard at http://localhost:8501 (Streamlit)
```

**Advantages:**
- No Node.js installation required
- Consistent builds across environments
- Perfect for CI/CD pipelines
- Deploy anywhere with Docker

**How it works:** Multi-stage Dockerfile builds React in Stage 1 (Node.js), then copies built files to Stage 2 (Python). Final image only contains Python + static React files.

**See:** [Full Docker Build Guide](../docs/deployment/DOCKER_BUILD.md) for details.


### Production Checklist

- [ ] Build React app: `npm run build`
- [ ] Set `NODE_ENV=production` in environment
- [ ] Configure production database credentials in `.env`
- [ ] Set secure `CLAUDE_KEY` for OpenAI API
- [ ] Configure AWS credentials for S3 access
- [ ] Run database migrations: `alembic upgrade head`
- [ ] Test health endpoint: `curl http://localhost:8000/api/health`

---

## Data Population Pipeline

The web app visualizes data processed through the AI/ML pipeline. Follow these steps to populate the database.

### Pipeline Overview

```
Raw Documents (S3)
  → Document Ingestion
  → AI Analysis (GPT-4)
  → Event Detection
  → Embeddings Generation
  → Web App Visualization
```

### Step-by-Step Data Population

#### 1. Document Ingestion

Import raw diplomatic documents into the database.

**Option A: Process JSON from S3**
```bash
python services/pipeline/ingestion/dsr.py
# Imports JSON documents from S3 bucket (configured in shared/config/config.yaml)

# Check status
python services/pipeline/ingestion/dsr.py --status
```

**Option B: Ingest from Atom Feed**
```bash
python services/pipeline/ingestion/atom.py
# Processes documents from atom feed source
```

#### 2. AI Analysis & Extraction

Extract salience, categories, countries, projects, and locations using GPT-4.

```bash
python services/pipeline/analysis/atom_extraction.py

# This populates:
# - Document salience scores
# - Categories & subcategories
# - Initiating & recipient countries
# - Projects & citations
# - Locations
```

**Configuration**: Edit `shared/config/config.yaml` to set:
- OpenAI model: `aws.default_model`
- Processing date ranges: `start_date`, `end_date`
- Country lists: `influencers`, `recipients`

#### 3. Generate Embeddings

Create vector embeddings for semantic search and similarity analysis.

```bash
# Embed all documents missing embeddings
python services/pipeline/embeddings/embed_missing_documents.py --yes

# Check embedding status
python services/pipeline/embeddings/embed_missing_documents.py --status

# Embed event summaries (after event processing)
python services/pipeline/embeddings/embed_event_summaries.py --yes
```

**Time Estimate**: ~45 hours for large datasets (300K+ documents). Consider using backup/restore for faster rebuilds.

#### 4. Event Processing (2-Stage Pipeline)

Detect and consolidate events from documents.

**Stage 1: Daily Event Detection**
```bash
# Stage 1A: Cluster daily events using DBSCAN + embeddings
python services/pipeline/events/batch_cluster_events.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31

# Stage 1B: LLM validates clusters and creates canonical events
python services/pipeline/events/llm_deconflict_clusters.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31
```

**Stage 2: Batch Consolidation (Run Periodically)**
```bash
# Stage 2A: Group canonical events using embedding similarity
python services/pipeline/events/consolidate_all_events.py --influencers

# Stage 2B: LLM validates consolidation, picks best names
python services/pipeline/events/llm_deconflict_canonical_events.py --influencers

# Stage 2C: Merge daily event mentions into multi-day events
python services/pipeline/events/merge_canonical_events.py --influencers
```

**Optional: Materiality Scoring**
```bash
python services/pipeline/events/score_canonical_event_materiality.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-31
```

#### 5. Verify Data in Web App

Once pipeline completes, data should be visible in the web app:

```bash
# Start web app (if not already running)
cd client && npm run dev

# Check these pages:
# - Documents: http://localhost:5000/documents
# - Events: http://localhost:5000/events
# - Countries: http://localhost:5000/countries
# - Analytics: http://localhost:5000/analytics
```

### Quick Test with Sample Data

For testing, process a small date range:

```bash
# 1. Ingest documents (sample)
python services/pipeline/ingestion/dsr.py --limit 100

# 2. AI analysis
python services/pipeline/analysis/atom_extraction.py

# 3. Generate embeddings
python services/pipeline/embeddings/embed_missing_documents.py --yes

# 4. Process events (small date range)
python services/pipeline/events/batch_cluster_events.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-07

python services/pipeline/events/llm_deconflict_clusters.py \
    --country China --start-date 2024-08-01 --end-date 2024-08-07

# 5. Check web app for data
```

### Backup & Restore (Fast Data Recovery)

**Export embeddings to S3** (saves ~45 hours regeneration time):
```bash
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./_data/exports/embeddings/$(date +%Y%m%d) \
    --include-event-summaries \
    --s3-bucket your-bucket \
    --s3-prefix embeddings/backup/$(date +%Y%m%d)/
```

**Restore embeddings** (15-20 minutes vs 45 hours):
```bash
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./_data/exports/embeddings/20241106
```

**Export event data**:
```bash
python services/pipeline/events/export_event_tables.py \
    --output-dir ./_data/exports/events/
```

**Restore event data**:
```bash
python services/pipeline/events/import_event_tables.py \
    --input-dir ./_data/exports/events/
```

---

## Environment Configuration

### Development vs Production

**Development** (npm run dev):
- React dev server: `http://localhost:5000`
- API server: `http://localhost:8000`
- Hot reload enabled
- Source maps enabled
- Vite proxy: `/api/*` → `http://localhost:8000/api/*`

**Production** (npm run build + server):
- Unified server: `http://localhost:8000`
- Optimized bundle in `client/dist/`
- Static file serving via FastAPI
- No hot reload
- Minified JS/CSS

### API Endpoints

All API routes are prefixed with `/api/`:

```
GET  /api/health              # Health check
GET  /api/documents           # List documents
GET  /api/events              # List events
GET  /api/countries           # List countries
GET  /api/analytics           # Analytics data
POST /api/search              # Semantic search
```

See [server/main.py](../server/main.py) for full API documentation.

### Database Connection

The app uses SQLAlchemy 2.0 with connection pooling:

```python
# Configuration in shared/database/database.py
DB_POOL_SIZE=10          # Default pool size
DB_MAX_OVERFLOW=20       # Max additional connections
DB_POOL_TIMEOUT=30       # Connection timeout (seconds)
DB_POOL_RECYCLE=3600     # Recycle connections after 1 hour
```

### S3 Configuration

S3 settings in `shared/config/config.yaml`:

```yaml
s3:
  bucket: "your-bucket-name"
  region: "us-east-1"
  prefixes:
    dsr_extracts: "dsr_extracts/"
    embeddings: "embeddings/"
    exports: "exports/"
    backups: "backups/"
```

Override via environment variables:
- `S3_BUCKET` - Override bucket name
- `S3_REGION` - Override region

---

## Architecture

### Tech Stack

**Frontend**:
- React 19 + TypeScript
- Vite (build tool)
- React Router (routing)
- TanStack Query (data fetching)
- Recharts (data visualization)
- Lucide React (icons)
- Axios (HTTP client)

**Backend**:
- FastAPI (Python web framework)
- SQLAlchemy 2.0 (ORM)
- PostgreSQL + pgvector (database)
- OpenAI GPT-4 (AI analysis)
- Sentence-transformers (embeddings)

### Directory Structure

```
client/
├── src/
│   ├── pages/              # Page components
│   ├── components/         # Reusable components
│   ├── services/           # API client services
│   ├── hooks/              # React hooks
│   ├── types/              # TypeScript types
│   ├── App.tsx             # Main app component
│   └── main.tsx            # Entry point
├── public/                 # Static assets
├── dist/                   # Production build output
├── package.json            # Node.js dependencies
├── vite.config.ts          # Vite configuration
└── tsconfig.json           # TypeScript configuration
```

### Data Flow

```
User Browser
  ↓ HTTP Request
FastAPI Server (/api/*)
  ↓ SQLAlchemy Query
PostgreSQL Database
  ↓ Vector Search (pgvector)
Document Embeddings
  ↓ Results
React Components
  ↓ Recharts Visualization
User Dashboard
```

### Key React Components

- **DocumentList**: Browse and filter documents
- **EventTimeline**: Visualize events over time
- **CountryMap**: Geographic distribution of activities
- **AnalyticsCharts**: Trend analysis and insights
- **SemanticSearch**: Vector-based document search

### State Management

- **React Query**: Server state caching and synchronization
- **React Router**: Client-side routing
- **Local State**: Component-level state with useState/useReducer

---

## Troubleshooting

### Development Server Issues

**Problem**: Vite dev server won't start
```bash
# Solution: Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

**Problem**: API requests fail with CORS errors
```bash
# Solution: Check Vite proxy config in vite.config.ts
# Ensure API server is running on http://localhost:8000
```

### Build Issues

**Problem**: TypeScript compilation errors
```bash
# Solution: Check TypeScript version compatibility
npm list typescript
# Should be ~5.9.3

# Check for type errors
npx tsc --noEmit
```

**Problem**: Build fails with memory issues
```bash
# Solution: Increase Node.js memory limit
export NODE_OPTIONS="--max-old-space-size=4096"
npm run build
```

### Database Connection Issues

**Problem**: Cannot connect to PostgreSQL
```bash
# Solution: Verify database is running
python -c "from shared.database.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"

# Check pool status
python -c "from shared.database.database import get_pool_status; print(get_pool_status())"
```

**Problem**: Slow query performance
```bash
# Solution: Check database indexes
psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\d+ documents"

# Check pool settings
# Increase DB_POOL_SIZE if needed (default: 10)
```

### Data Pipeline Issues

**Problem**: No data showing in web app
```bash
# Solution: Verify pipeline completed
# 1. Check documents exist
psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT COUNT(*) FROM documents;"

# 2. Check embeddings exist
python services/pipeline/embeddings/embed_missing_documents.py --status

# 3. Check events exist
psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT COUNT(*) FROM canonical_events;"
```

**Problem**: Embeddings generation too slow
```bash
# Solution: Use backup/restore instead
# Export embeddings from production
python services/pipeline/embeddings/export_embeddings.py \
    --output-dir ./_data/exports/embeddings/backup \
    --include-event-summaries

# Import on new system (15-20 minutes vs 45 hours)
python services/pipeline/embeddings/import_embeddings.py \
    --input-dir ./_data/exports/embeddings/backup
```

---

## Additional Resources

- **Main Documentation**: [../README.md](../README.md)
- **Development Guide**: [../CLAUDE.md](../CLAUDE.md)
- **Pipeline Scripts**: [../CURRENT_PIPELINE_SCRIPTS.md](../CURRENT_PIPELINE_SCRIPTS.md)
- **Deployment Guides**: [../docs/deployment/](../docs/deployment/)
- **API Documentation**: [../server/main.py](../server/main.py)

---

## Contributing

### Adding New Features

1. Create feature branch: `git checkout -b feature/new-feature`
2. Develop in `src/` with TypeScript
3. Test with `npm run dev`
4. Build with `npm run build`
5. Test production build with `npm run preview`
6. Submit pull request

### Code Style

- **TypeScript**: Strict mode enabled
- **Linting**: ESLint with React hooks rules
- **Formatting**: Consistent 2-space indentation
- **Components**: Functional components with hooks
- **File naming**: PascalCase for components, camelCase for utilities

---

## License

See [../LICENSE](../LICENSE) for details.
