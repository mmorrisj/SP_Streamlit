# Soft Power Analytics Platform

A comprehensive analytics platform for processing, analyzing, and visualizing diplomatic documents to identify patterns, events, and trends in soft power activities.

## Project Overview

This is a multi-component system built with:
- **Frontend**: Streamlit dashboard (port 5000)
- **Backend**: FastAPI for S3 operations and LLM queries
- **Database**: PostgreSQL with pgvector extension
- **AI/ML**: OpenAI GPT models, sentence-transformers, HDBSCAN clustering

## Project Structure

```
/
├── services/
│   ├── dashboard/       # Streamlit frontend (main entry point)
│   │   ├── app.py       # Main dashboard application
│   │   ├── pages/       # Additional dashboard pages
│   │   ├── queries/     # Database query modules
│   │   └── charts/      # Chart visualization modules
│   ├── api/             # FastAPI backend service
│   ├── pipeline/        # Data processing pipeline
│   └── publication/     # Publication generation
├── shared/
│   ├── config/          # Configuration files
│   ├── database/        # Database connection module
│   ├── models/          # SQLAlchemy models
│   └── utils/           # Utility functions
├── alembic/             # Database migrations
├── data/                # Data storage
└── docs/                # Documentation
```

## Running the Application

The Streamlit Dashboard runs automatically via the configured workflow:
- Binds to `0.0.0.0:5000`
- Uses `PYTHONPATH=/home/runner/workspace` for proper module resolution

## Database

Uses Replit's PostgreSQL database. The `DATABASE_URL` environment variable is automatically configured.

Database migrations are managed with Alembic:
```bash
PYTHONPATH=. alembic upgrade head
```

## Configuration

- `.streamlit/config.toml` - Streamlit server configuration
- `shared/config/config.yaml` - Application configuration
- Environment variables for secrets (DATABASE_URL, OPENAI keys, AWS credentials)

## Recent Changes

- 2025-12-27: Initial Replit environment setup
  - Configured Streamlit to run on port 5000 with CORS disabled
  - Fixed config path resolution in shared/utils/utils.py
  - Set up PostgreSQL database with pgvector extension
  - Ran Alembic migrations to create database schema
  - Configured deployment settings
