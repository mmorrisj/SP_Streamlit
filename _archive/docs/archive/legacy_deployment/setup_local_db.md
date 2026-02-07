# Local Database Setup Guide

This guide walks you through setting up a local PostgreSQL database that mirrors your production environment.

## Prerequisites

- Docker Desktop installed and running
- Your `.env` file configured with credentials

## Step 1: Create Docker Network and Volume

First, create the external network and volume that Docker Compose expects:

```bash
# Create the network
docker network create softpower_net

# Create the persistent volume for PostgreSQL data
docker volume create softpower_streamlit_postgres_data
```

## Step 2: Start PostgreSQL Database

Start only the database service:

```bash
docker-compose up -d db
```

This will:
- Pull the `ankane/pgvector` image (PostgreSQL with vector extension)
- Start the database on port **5433** (host) → 5432 (container)
- Create persistent storage in the `softpower_streamlit_postgres_data` volume

## Step 3: Verify Database is Running

Check the database container status:

```bash
docker ps --filter "name=softpower_db"
```

You should see:
```
CONTAINER ID   IMAGE             STATUS         PORTS
xxxxx          ankane/pgvector   Up X seconds   0.0.0.0:5433->5432/tcp
```

## Step 4: Create Database Tables with Alembic

Run migrations to create all tables with the updated schema:

```bash
docker-compose --profile migrate up
```

This will:
- Run all Alembic migrations
- Create the `documents` table with the new `project_name` field
- Create all relationship tables (categories, subcategories, etc.)
- Create event summary tables
- Set up pgvector extensions

**Note**: If you need to manually run migrations:

```bash
# Inside the backend container
docker exec -it ml-backend alembic upgrade head
```

## Step 5: Verify Tables Were Created

Connect to PostgreSQL and check tables:

```bash
docker exec -it softpower_db psql -U matthew50 -d softpower-db
```

Inside the PostgreSQL shell:

```sql
-- List all tables
\dt

-- Describe the documents table
\d documents

-- Check for project_name field
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'documents'
  AND column_name IN ('event_name', 'project_name', '_projects');

-- Exit
\q
```

## Step 6: Test Database Connection from Notebook

Open `data_check_local.ipynb` and run the first cell. You should see:

```
✅ Configured for local connection to Docker PostgreSQL:
   Connection: postgresql://matthew50:***@localhost:5433/softpower-db

Testing connection...
✅ Database connection successful!
```

## Step 7: Load Sample Data

Process your sample JSON files to populate the database:

```bash
# From the project root
python backend/scripts/dsr.py --source local --relocate
```

This will:
- Load JSON files from `data/` folder
- Parse them with the updated `parse_doc()` function
- Handle both old schema (`project-name`) and new schema (`event-name`)
- Move processed files to `data/processed/`

**Expected Output:**
```
Looking for files in: C:\Users\mmorr\Desktop\Apps\SP_Streamlit\data
loaded data/1-4August_DSNR_EXTRACT.json...
loaded data/5-6August_DSNR_EXTRACT.json...
loaded data/results-2025-10-08-2025-10-14.json...
3 documents loaded...

ℹ️  Doc xxx: Using 'project-name' as fallback: 'Moscow Format'
ℹ️  Doc xxx: Using 'projects' as fallback: 'Peace Negotiations'

✅ Committed batch of 100 documents
...
DSR Processing complete:
  - Loaded: XXXX documents
  - Skipped: XX documents
  - Errors: X documents
```

## Troubleshooting

### Port 5433 Already in Use

If you get a port conflict:

```bash
# Find what's using port 5433
netstat -ano | findstr :5433

# Option 1: Stop the conflicting service
# Option 2: Change the port in docker-compose.yml
```

### Database Connection Failed

Check your `.env` file has:

```env
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=softpower
POSTGRES_DB=softpower-db
DB_HOST=localhost
DB_PORT=5433  # For local connection outside Docker

# OpenAI API for local development
OPENAI_PROJ_API=sk-proj-...  # Your OpenAI API key
```

### FastAPI LLM Proxy Setup

For local development, the FastAPI server can call OpenAI directly:

1. **Make sure `OPENAI_PROJ_API` is set** in your `.env` file
2. **Start the FastAPI server**:
   ```bash
   cd C:\Users\mmorr\Desktop\Apps\SP_Streamlit
   uvicorn backend.api:app --host 0.0.0.0 --port 5001 --reload
   ```
3. **Test the endpoint**:
   ```bash
   curl -X POST http://localhost:5001/material_query \
     -H "Content-Type: application/json" \
     -d '{
       "model": "gpt-4o-mini",
       "sys_prompt": "You are a helpful assistant.",
       "prompt": "Say hello!"
     }'
   ```

The `/material_query` endpoint will now use your OpenAI API key directly for development purposes.

### Volume Permission Issues

On Windows, Docker volumes should work automatically. If you have issues:

```bash
# Remove and recreate the volume
docker-compose down
docker volume rm softpower_streamlit_postgres_data
docker volume create softpower_streamlit_postgres_data
docker-compose up -d db
```

### Schema Out of Sync

If you modified models and need to recreate tables:

```bash
# Warning: This will DELETE all data!
docker exec -it softpower_db psql -U matthew50 -d softpower-db -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Then run migrations again
docker-compose --profile migrate up
```

## Next Steps

1. **Analyze Sample Data**: Run `compare_schema.ipynb` to see field distribution
2. **Test Parsing**: Run `analyze_json_parsing.ipynb` to verify event-name consolidation
3. **Query Documents**: Use `data_check_local.ipynb` to explore parsed results
4. **Process More Data**: Point to S3 with `--source s3` or add more local JSON files

## Useful Commands

```bash
# View database logs
docker-compose logs -f db

# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v

# Restart just the database
docker-compose restart db

# Connect to PostgreSQL shell
docker exec -it softpower_db psql -U matthew50 -d softpower-db

# Backup database
docker exec softpower_db pg_dump -U matthew50 softpower-db > backup.sql

# Restore database
docker exec -i softpower_db psql -U matthew50 -d softpower-db < backup.sql
```
