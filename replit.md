# Soft Power Analytics Platform

A comprehensive analytics platform for processing, analyzing, and visualizing diplomatic documents to identify patterns, events, and trends in soft power activities.

## Project Overview

This is a multi-component system built with:
- **Frontend**: React + TypeScript + Vite (port 5000)
- **Backend**: FastAPI REST API (port 8000)
- **Database**: PostgreSQL with pgvector extension
- **AI/ML**: OpenAI GPT models, sentence-transformers, HDBSCAN clustering

## Project Structure

```
/
├── client/                  # React frontend
│   ├── src/
│   │   ├── components/      # Reusable UI components
│   │   ├── pages/           # Page components (Dashboard, Documents, etc.)
│   │   ├── api/             # API client
│   │   └── types/           # TypeScript types
│   └── vite.config.ts       # Vite configuration
├── server/
│   └── main.py              # FastAPI backend server
├── services/
│   ├── dashboard/           # Legacy Streamlit dashboard (archived)
│   ├── api/                 # Additional API services
│   ├── pipeline/            # Data processing pipeline
│   └── publication/         # Publication generation
├── shared/
│   ├── config/              # Configuration files
│   ├── database/            # Database connection module
│   ├── models/              # SQLAlchemy models
│   └── utils/               # Utility functions
├── alembic/                 # Database migrations
├── data/                    # Data storage
└── docs/                    # Documentation
```

## Running the Application

### Development Mode
Two workflows run in parallel:
- **React Frontend**: `cd client && npm run dev` (port 5000)
- **FastAPI Backend**: `PYTHONPATH=/home/runner/workspace uvicorn server.main:app --host localhost --port 8000 --reload`

### Production Build
```bash
cd client && npm run build
PYTHONPATH=/home/runner/workspace uvicorn server.main:app --host 0.0.0.0 --port 5000
```

## API Endpoints

- `GET /api/health` - Health check
- `GET /api/documents/stats` - Document statistics and charts
- `GET /api/documents` - Paginated document list
- `GET /api/events` - Events list
- `GET /api/summaries` - Summaries (daily/weekly/monthly)
- `GET /api/bilateral` - Bilateral relationship data
- `GET /api/categories` - Category and subcategory distributions
- `GET /api/filters` - Available filter options

## Database

Uses Replit's PostgreSQL database. The `DATABASE_URL` environment variable is automatically configured.

Database migrations are managed with Alembic:
```bash
PYTHONPATH=. alembic upgrade head
```

### Key Tables
- `documents` - Core diplomatic documents
- `canonical_events` - Consolidated events
- `event_summaries` - Event summary texts
- `categories`, `subcategories` - Document categorization
- `initiating_countries`, `recipient_countries` - Country relationships

## Configuration

- `client/vite.config.ts` - Frontend server configuration
- `shared/config/config.yaml` - Application configuration
- Environment variables for secrets (DATABASE_URL, OPENAI keys, AWS credentials)

## Recent Changes

- 2025-12-27: Converted from Streamlit to React + FastAPI
  - Created React frontend with Vite + TypeScript
  - Built FastAPI backend with REST API endpoints
  - Implemented Dashboard, Documents, Events, Summaries, Bilateral, Categories pages
  - Connected to existing PostgreSQL database schema
  - Configured development and production workflows
