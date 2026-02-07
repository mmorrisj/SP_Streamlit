# FastAPI S3 Integration Setup

This document explains how S3 operations work via FastAPI endpoints, running outside Docker to access AWS credentials.

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌────────────┐
│  Docker         │ HTTP    │  FastAPI         │  AWS    │    S3      │
│  Container      │────────>│  (Host Machine)  │────────>│   Bucket   │
│  - pgvector     │         │  - api.py        │  SDK    │            │
│  - s3_to_pgvec  │         │  - AWS creds     │         │  *.parquet │
└─────────────────┘         └──────────────────┘         └────────────┘
```

**Why FastAPI for S3?**
- Docker containers don't have AWS credentials configured
- Host machine has IAM role or AWS credentials
- FastAPI acts as proxy, handling all S3 operations
- Parquet files can be large (embeddings) - binary streaming is efficient

## Setup

### 1. Start FastAPI Server

The FastAPI server must run on the host machine (outside Docker):

```bash
# Install dependencies
pip install fastapi uvicorn boto3 pandas pyarrow

# Start server
cd backend
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Configure AWS Credentials

The FastAPI server uses boto3, which requires AWS credentials:

**Option A: AWS CLI**
```bash
aws configure
```

**Option B: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1
```

**Option C: IAM Role** (if running on EC2)
- Attach IAM role with S3 read permissions to EC2 instance

### 3. Set API URL (Optional)

If FastAPI runs on a different host/port:

```bash
# In .env file
API_URL=http://your-host:8000

# Or as environment variable
export API_URL=http://your-host:8000
```

## FastAPI Endpoints

### General S3 Endpoints

#### List Files
```http
POST /s3/list
Content-Type: application/json

{
  "bucket": "morris-sp-bucket",
  "prefix": "embeddings/",
  "max_keys": 1000
}
```

#### Download File
```http
POST /s3/download
Content-Type: application/json

{
  "bucket": "morris-sp-bucket",
  "key": "embeddings/file.parquet"
}
```

### Parquet-Specific Endpoints

#### List Parquet Files
```http
POST /s3/parquet/list
Content-Type: application/json

{
  "bucket": "morris-sp-bucket",
  "prefix": "embeddings/",
  "max_keys": 1000
}
```

Response:
```json
{
  "bucket": "morris-sp-bucket",
  "prefix": "embeddings/",
  "count": 12,
  "files": [
    {
      "key": "embeddings/doc_embeddings_01.parquet",
      "filename": "doc_embeddings_01.parquet",
      "size": 52428800,
      "size_mb": 50.0,
      "last_modified": "2025-01-15T10:30:45.000Z"
    }
  ]
}
```

#### Get Parquet Metadata
```http
POST /s3/parquet/metadata
Content-Type: application/json

{
  "bucket": "morris-sp-bucket",
  "key": "embeddings/doc_embeddings_01.parquet"
}
```

Response:
```json
{
  "filename": "doc_embeddings_01.parquet",
  "s3_key": "embeddings/doc_embeddings_01.parquet",
  "num_rows": 1500,
  "num_columns": 3,
  "num_row_groups": 1,
  "columns": [
    {"name": "doc_id", "type": "BYTE_ARRAY"},
    {"name": "embedding", "type": "FLOAT"},
    {"name": "text", "type": "BYTE_ARRAY"}
  ],
  "created_by": "parquet-cpp version 1.5.1-SNAPSHOT",
  "format_version": "1.0"
}
```

#### Validate Parquet Schema
```http
POST /s3/parquet/validate
Content-Type: application/json

{
  "bucket": "morris-sp-bucket",
  "key": "embeddings/doc_embeddings_01.parquet",
  "required_columns": ["doc_id", "embedding"]  // optional
}
```

Response:
```json
{
  "valid": true,
  "filename": "doc_embeddings_01.parquet",
  "s3_key": "embeddings/doc_embeddings_01.parquet",
  "columns": ["doc_id", "embedding", "text"],
  "num_rows": 1500,
  "has_id_column": true,
  "has_embedding_column": true,
  "found_id_column": "doc_id",
  "found_embedding_column": "embedding",
  "errors": []
}
```

#### Get Sample Data
```http
POST /s3/parquet/sample
Content-Type: application/json

{
  "bucket": "morris-sp-bucket",
  "key": "embeddings/doc_embeddings_01.parquet",
  "num_rows": 10
}
```

#### Extract Document IDs
```http
POST /s3/parquet/extract-ids
Content-Type: application/json

{
  "bucket": "morris-sp-bucket",
  "key": "embeddings/doc_embeddings_01.parquet"
}
```

Response:
```json
{
  "filename": "doc_embeddings_01.parquet",
  "s3_key": "embeddings/doc_embeddings_01.parquet",
  "id_column": "doc_id",
  "total_rows": 1500,
  "unique_ids": 1500,
  "doc_ids": ["doc123", "doc456", ...]
}
```

#### Download Full Parquet (Binary)
```http
GET /s3/parquet/download-binary?bucket=morris-sp-bucket&key=embeddings/file.parquet
```

Returns binary stream of parquet file. Used by API client to get full embeddings.

## Using the API Client

### Python API Client

The `backend/api_client.py` module provides a convenient Python interface:

```python
from backend.api_client import get_s3_api_client

# Initialize client
client = get_s3_api_client()  # Uses API_URL env var or localhost:8000
# Or specify URL
client = get_s3_api_client('http://your-host:8000')

# List parquet files
files = client.list_parquet_files(
    bucket='morris-sp-bucket',
    prefix='embeddings/'
)
print(f"Found {files['count']} files")

# Get metadata
metadata = client.get_parquet_metadata(
    bucket='morris-sp-bucket',
    key='embeddings/doc_embeddings_01.parquet'
)
print(f"Rows: {metadata['num_rows']}")

# Validate schema
validation = client.validate_parquet_schema(
    bucket='morris-sp-bucket',
    key='embeddings/doc_embeddings_01.parquet'
)
if validation['valid']:
    print(f"✓ Valid schema with columns: {validation['columns']}")

# Download as DataFrame (with full embeddings)
df = client.download_parquet_as_dataframe(
    bucket='morris-sp-bucket',
    key='embeddings/doc_embeddings_01.parquet'
)
print(f"Downloaded {len(df)} rows")
print(df.head())
```

## S3 to pgvector Migration with FastAPI

The `s3_to_pgvector.py` script now uses FastAPI for all S3 operations:

```bash
# Ensure FastAPI server is running
uvicorn backend.api:app --host 0.0.0.0 --port 8000

# Run migration (automatically uses API)
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix embeddings/ \
  --collection chunk_embeddings

# Specify custom API URL
python backend/scripts/s3_to_pgvector.py \
  --s3-prefix embeddings/ \
  --collection chunk_embeddings \
  --api-url http://your-host:8000

# Use environment variable
export API_URL=http://your-host:8000
python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/ --collection chunk_embeddings
```

### How It Works

1. **Script starts**: Initializes API client with configured URL
2. **List files**: Calls `/s3/parquet/list` to discover parquet files
3. **Download files**: For each file, calls `/s3/parquet/download-binary` to stream full parquet data
4. **Process locally**: Reads parquet with pandas, extracts embeddings and metadata
5. **Query database**: Fetches document metadata from PostgreSQL (inside Docker)
6. **Insert embeddings**: Writes to pgvector via LangChain (inside Docker)
7. **Track progress**: Updates local tracker file to prevent duplicates

## Running in Production

### Using Docker Compose

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg16
    # ... postgres config

  api:
    build: ./backend
    command: uvicorn api:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    environment:
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - AWS_DEFAULT_REGION=us-east-1
    volumes:
      - ~/.aws:/root/.aws:ro  # Mount AWS credentials
```

### Environment Variables

```bash
# .env file
API_URL=http://api:8000  # If API is in Docker
# or
API_URL=http://host.docker.internal:8000  # If API on host from Docker

AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=us-east-1

POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=softpower-db
DB_HOST=postgres
DB_PORT=5432
```

## Troubleshooting

### Issue: Connection Refused

**Error:**
```
requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionRefusedError(10061, ...))
```

**Solution:**
1. Ensure FastAPI server is running: `uvicorn backend.api:app --host 0.0.0.0 --port 8000`
2. Check API_URL is correct
3. If running from Docker, use `host.docker.internal:8000` instead of `localhost:8000`

### Issue: AWS Access Denied

**Error:**
```
botocore.exceptions.ClientError: An error occurred (AccessDenied) when calling the ListObjectsV2 operation
```

**Solution:**
1. Configure AWS credentials on the machine running FastAPI
2. Ensure IAM user/role has S3 read permissions
3. Check bucket name is correct

### Issue: Import Error

**Error:**
```
ModuleNotFoundError: No module named 'backend.api_client'
```

**Solution:**
Ensure you're running from project root and Python path is set:
```bash
cd /path/to/SP_Streamlit
export PYTHONPATH=.
python backend/scripts/s3_to_pgvector.py ...
```

### Issue: Parquet File Too Large

**Error:**
```
Memory Error or timeout
```

**Solution:**
- Process files in smaller batches
- Increase FastAPI timeout settings
- Consider splitting large parquet files

## Performance Considerations

### Binary Streaming
- Full parquet files are streamed as binary (efficient)
- No JSON encoding/decoding of large arrays
- Temp files used for processing

### Pagination
- List operations support pagination
- Default max 1000 files per request
- Increase `max_keys` if needed

### Concurrent Requests
- FastAPI supports async/concurrent requests
- Multiple parquet files can be downloaded in parallel
- Use batch endpoints when possible

## Testing Endpoints

### Using curl

```bash
# Test health
curl http://localhost:8000/health

# List parquet files
curl -X POST http://localhost:8000/s3/parquet/list \
  -H "Content-Type: application/json" \
  -d '{"bucket": "morris-sp-bucket", "prefix": "embeddings/"}'

# Get metadata
curl -X POST http://localhost:8000/s3/parquet/metadata \
  -H "Content-Type: application/json" \
  -d '{"bucket": "morris-sp-bucket", "key": "embeddings/file.parquet"}'

# Download binary
curl "http://localhost:8000/s3/parquet/download-binary?bucket=morris-sp-bucket&key=embeddings/file.parquet" \
  --output downloaded.parquet
```

### Using Python requests

```python
import requests

# List files
response = requests.post(
    'http://localhost:8000/s3/parquet/list',
    json={'bucket': 'morris-sp-bucket', 'prefix': 'embeddings/'}
)
print(response.json())

# Download binary
response = requests.get(
    'http://localhost:8000/s3/parquet/download-binary',
    params={'bucket': 'morris-sp-bucket', 'key': 'embeddings/file.parquet'},
    stream=True
)
with open('downloaded.parquet', 'wb') as f:
    for chunk in response.iter_content(chunk_size=8192):
        f.write(chunk)
```

## API Documentation

Once FastAPI is running, interactive API documentation is available at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

These provide interactive interfaces to test all endpoints.
