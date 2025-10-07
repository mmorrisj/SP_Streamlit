# S3 to pgvector Migration Guide

This guide explains how to migrate document embeddings from S3 parquet files into the pgvector database for use with LangChain.

## Overview

The migration script (`s3_to_pgvector.py`) performs the following steps:

1. **Pull parquet files from S3** - Downloads embedding files from your S3 bucket
2. **Look up document metadata** - Fetches full document metadata from PostgreSQL database
3. **Populate pgvector tables** - Inserts embeddings with metadata into LangChain pgvector collections

## Prerequisites

### 1. Install Dependencies

```bash
pip install boto3 pyarrow
```

Or update requirements:
```bash
pip install -r requirements.txt
pip install -r backend/requirements.txt
```

### 2. Configure AWS Credentials

Set up AWS credentials for S3 access. Choose one method:

**Option A: AWS CLI Configuration**
```bash
aws configure
```

**Option B: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
```

**Option C: IAM Role** (if running on EC2/ECS)
- Ensure your instance has an IAM role with S3 read permissions

### 3. Configure Database Connection

Ensure your `.env` file contains PostgreSQL credentials:
```env
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password
POSTGRES_DB=softpower-db
DB_HOST=localhost
DB_PORT=5432
```

### 4. Verify Database is Running

```bash
# If using Docker
docker-compose up -d

# Test connection
python -c "from backend.database import health_check; print('✅ Connected' if health_check() else '❌ Failed')"
```

## Parquet File Schema

Your parquet files should contain the following columns:

**Required:**
- `doc_id` (or `document_id`, `id`, `atom_id`, `ATOM ID`) - Document identifier
- `embedding` (or `embeddings`, `vector`) - Embedding vector (array of floats)

**Optional:**
- `text` (or `distilled_text`, `content`, `body`) - Document text

Example parquet schema:
```python
{
    'doc_id': ['doc123', 'doc456', ...],
    'embedding': [[0.1, 0.2, ...], [0.3, 0.4, ...], ...],
    'text': ['Document text...', 'More text...', ...]
}
```

## Usage Examples

### Basic Migration

Migrate all parquet files from S3 to the `chunk_embeddings` collection:

```bash
python backend/scripts/s3_to_pgvector.py \
  --bucket morris-sp-bucket \
  --s3-prefix embeddings/ \
  --collection chunk_embeddings
```

### Dry Run (Test Mode)

Test the migration without writing to the database:

```bash
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix embeddings/ \
  --collection chunk_embeddings \
  --dry-run
```

This will:
- Download and validate parquet files
- Fetch document metadata
- Show what would be inserted
- NOT write to database

### Process Specific Files

Migrate only specific parquet files:

```bash
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix embeddings/ \
  --collection chunk_embeddings \
  --files document_embeddings_2024_01.parquet document_embeddings_2024_02.parquet
```

### Different Collections

Migrate to different LangChain collections:

```bash
# Daily event embeddings
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix event_embeddings/daily/ \
  --collection daily

# Weekly event embeddings
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix event_embeddings/weekly/ \
  --collection weekly

# Monthly event embeddings
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix event_embeddings/monthly/ \
  --collection monthly
```

### Available Collections

The script supports the following predefined collections:
- `chunk` - Document chunk embeddings
- `daily` - Daily event embeddings
- `weekly` - Weekly event embeddings
- `monthly` - Monthly event embeddings
- `yearly` - Yearly event embeddings

## Command-Line Options

```bash
python backend/scripts/s3_to_pgvector.py [OPTIONS]

Options:
  --bucket TEXT          S3 bucket name (default: morris-sp-bucket)
  --s3-prefix TEXT       S3 prefix/folder containing parquet files (default: embeddings/)
  --collection TEXT      Target LangChain collection name (default: chunk_embeddings)
  --files FILE [FILE...] Specific parquet files to process (optional)
  --dry-run             Run without inserting into database
  -h, --help            Show help message
```

## How It Works

### 1. Parquet File Discovery
```
S3 Bucket: morris-sp-bucket
├── embeddings/
│   ├── document_embeddings_2024_01.parquet
│   ├── document_embeddings_2024_02.parquet
│   └── document_embeddings_2024_03.parquet
```

### 2. Data Extraction
For each parquet file:
- Download from S3
- Validate schema (check for required columns)
- Normalize column names to standard format

### 3. Metadata Lookup
For each `doc_id` in the parquet file:
- Query PostgreSQL `documents` table
- Fetch metadata: title, date, source, categories, countries, etc.
- Build comprehensive metadata dictionary

### 4. pgvector Insertion
```python
# LangChain pgvector tables structure
langchain_pg_collection      # Collection metadata
├── uuid (primary key)
├── name (e.g., "chunk_embeddings")
└── cmetadata (JSONB)

langchain_pg_embedding       # Embeddings + metadata
├── id (primary key)
├── collection_id (foreign key)
├── embedding (vector)       # pgvector type
├── document (text)          # Document text
└── cmetadata (JSONB)        # Searchable metadata
    ├── doc_id
    ├── title
    ├── date
    ├── source_name
    ├── event_name
    ├── category
    └── ...
```

### 5. Metadata Stored in pgvector

Each document gets the following metadata in the `cmetadata` JSONB field:
- `doc_id` - Original document ID
- `title` - Document title
- `date` - Publication date
- `source_name` - News source
- `event_name` - Associated event
- `category` - Primary category
- `subcategory` - Subcategory
- `initiating_country` - Country initiating soft power activity
- `recipient_country` - Recipient country
- `salience` - Salience score
- `salience_bool` - Binary salience flag

This metadata enables rich semantic search with filtering:
```python
# Example: Search with filters
results = vector_store.similarity_search(
    query="economic cooperation",
    filter={"category": "Economic", "initiating_country": "China"},
    k=10
)
```

## Monitoring Progress

The script provides detailed progress output:

```
================================================================================
Processing: embeddings/document_embeddings_2024_01.parquet
================================================================================
Downloading embeddings/document_embeddings_2024_01.parquet...
  Loaded 1500 rows from embeddings/document_embeddings_2024_01.parquet
Normalized 1500 records
Fetched metadata for 1450 documents (out of 1500 requested)
Prepared 1450 documents for insertion
Inserting 1450 documents into chunk_embeddings...
✓ Successfully inserted 1450 documents

================================================================================
MIGRATION SUMMARY
================================================================================
Total files processed: 3/3
Total documents inserted: 4350
Failed files: 0
Duration: 125.43 seconds
```

## Troubleshooting

### Issue: AWS Access Denied

**Error:**
```
botocore.exceptions.ClientError: An error occurred (AccessDenied) when calling the ListObjectsV2 operation: Access Denied
```

**Solution:**
1. Verify AWS credentials are configured
2. Check IAM permissions for S3 bucket access
3. Ensure bucket name is correct

### Issue: Document Not Found in Database

**Warning:**
```
Warning: Document doc123 not found in database, skipping
```

**Solution:**
- This is normal if parquet files contain more documents than the database
- Documents without metadata are skipped
- Run document ingestion first: `python backend/scripts/atom.py`

### Issue: Invalid Parquet Schema

**Error:**
```
Error: No ID column found. Expected one of: ['doc_id', 'document_id', 'id', 'atom_id', 'ATOM ID']
```

**Solution:**
1. Check parquet file structure:
   ```python
   import pandas as pd
   df = pd.read_parquet('your_file.parquet')
   print(df.columns)
   ```
2. Ensure file has required columns
3. If column names differ, update the script's `validate_parquet_schema()` method

### Issue: Database Connection Failed

**Error:**
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Solution:**
1. Start PostgreSQL: `docker-compose up -d`
2. Verify connection string in `.env`
3. Check database health: `python -c "from backend.database import health_check; health_check()"`

## Performance Considerations

### Batch Processing
- Documents are fetched in batches of 1000 for efficiency
- LangChain `add_texts()` handles bulk insertion

### Large Files
- Files are downloaded to `/tmp` and cleaned up after processing
- For very large parquet files (>1GB), consider splitting into smaller chunks

### Parallel Processing
To process multiple S3 prefixes in parallel:

```bash
# Run in separate terminal windows
python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/2024-01/ &
python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/2024-02/ &
python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/2024-03/ &
```

## Querying After Migration

Once migration is complete, query embeddings using LangChain:

```python
from backend.scripts.embedding_vectorstore import chunk_store

# Semantic search
results = chunk_store.similarity_search(
    query="economic cooperation between China and Egypt",
    k=10
)

# Search with metadata filters
results = chunk_store.similarity_search(
    query="infrastructure projects",
    filter={"category": "Economic", "subcategory": "Infrastructure"},
    k=5
)

# Get embeddings by doc_ids
from backend.scripts.embedding_vectorstore import get_embeddings_by_ids
embeddings = get_embeddings_by_ids(chunk_store, ['doc123', 'doc456'])
```

## Next Steps

After successful migration:

1. **Verify Data**: Query the pgvector tables to confirm embeddings are present
   ```sql
   SELECT collection_id, COUNT(*)
   FROM langchain_pg_embedding
   GROUP BY collection_id;
   ```

2. **Test Semantic Search**: Run sample queries to verify search quality

3. **Integrate with Dashboard**: Update Streamlit app to use pgvector for search

4. **Monitor Performance**: Track query latency and optimize indexes if needed

5. **Set up Regular Syncs**: Schedule periodic migrations for new embeddings
   ```bash
   # Add to cron or task scheduler
   0 2 * * * cd /path/to/project && python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/
   ```

## Additional Resources

- [LangChain PGVector Documentation](https://python.langchain.com/docs/integrations/vectorstores/pgvector)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [AWS S3 Documentation](https://docs.aws.amazon.com/s3/)
- [Parquet Format Specification](https://parquet.apache.org/docs/)
