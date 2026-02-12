"""
Lightweight LLM + S3 Proxy Server

Minimal FastAPI server that serves the LLM, S3, and Batch API endpoints.
Use this instead of the full server/main.py when you only need the
proxy relay for Docker containers (avoids installing the full requirements.txt).

Requirements (install via pip):
    pip install fastapi uvicorn openai boto3 python-dotenv python-multipart

Usage:
    python scripts/llm_proxy.py

    # Or with uvicorn directly
    uvicorn scripts.llm_proxy:app --host 0.0.0.0 --port 7001

Environment Variables:
    # LLM
    OPENAI_PROJ_API or OPENAI_API_KEY  - OpenAI API key (development)
    LITELLM_URL + LITELLM_API_KEY      - LiteLLM proxy (optional, takes priority)
    LITELLM_MODEL                       - Model override for LiteLLM
    AZURE_OPENAI_ENDPOINT               - Azure OpenAI endpoint (production)
    AZURE_OPENAI_API_KEY                - Azure OpenAI key (production)
    AZURE_OPENAI_DEPLOYMENT             - Azure deployment name
    ENV                                 - "production" for Azure, else OpenAI

    # S3
    AWS_ACCESS_KEY_ID                   - AWS credentials
    AWS_SECRET_ACCESS_KEY               - AWS credentials
    AWS_DEFAULT_REGION                  - AWS region (default: us-east-1)
"""

import os
import json
import tempfile
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}")
except ImportError:
    pass

app = FastAPI(
    title="SoftPower Proxy",
    description="Lightweight LLM + S3 proxy relay for Docker containers",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# S3 Client (lazy init)
# ============================================================

_s3_client = None

def get_s3_client():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client('s3')
        print("  [S3] Client initialized")
    return _s3_client


# ============================================================
# Request/Response Models
# ============================================================

class QueryInput(BaseModel):
    sys_prompt: str = ""
    prompt: str
    model: str = "gpt-4o-mini"

class S3DownloadRequest(BaseModel):
    bucket: str
    key: str

class S3ListRequest(BaseModel):
    bucket: str
    prefix: Optional[str] = ""
    max_keys: Optional[int] = 1000

class S3UploadRequest(BaseModel):
    bucket: str
    key: str
    content: str

class ParquetListRequest(BaseModel):
    bucket: str
    prefix: str = "embeddings/"
    max_keys: int = 1000

class JsonListRequest(BaseModel):
    bucket: str
    prefix: str = "dsr_extracts/"
    max_keys: int = 1000

class JsonBatchRequest(BaseModel):
    bucket: str
    keys: List[str]

class BatchCreateRequest(BaseModel):
    input_file_id: str
    endpoint: str = "/v1/chat/completions"
    completion_window: str = "24h"

class BatchStatusRequest(BaseModel):
    batch_id: str


# ============================================================
# Health Checks
# ============================================================

@app.get("/docs-check")
def docs_check():
    return {"status": "ok", "service": "proxy"}

@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "proxy"}


# ============================================================
# LLM Endpoints
# ============================================================

@app.post("/proxy_query")
def proxy_query(input: QueryInput):
    """
    LLM query endpoint with environment-based routing.
    Priority: LiteLLM > Azure (production) > OpenAI (development)
    """
    from openai import OpenAI

    # 1. Try LiteLLM first
    litellm_url = os.getenv('LITELLM_URL', '').strip()
    litellm_key = os.getenv('LITELLM_API_KEY', '').strip()

    if litellm_url and litellm_key:
        litellm_model = os.getenv('LITELLM_MODEL', input.model).strip()
        try:
            print(f"  [LITELLM] Calling {litellm_url} with model {litellm_model}")
            client = OpenAI(api_key=litellm_key, base_url=litellm_url)
            completion = client.chat.completions.create(
                model=litellm_model,
                messages=[
                    {"role": "system", "content": input.sys_prompt},
                    {"role": "user", "content": input.prompt},
                ],
                temperature=0.7,
            )
            content = completion.choices[0].message.content
            return _parse_response(content)
        except Exception as e:
            print(f"  [LITELLM] Failed: {e}, falling back...")

    # 2. Try Azure in production
    env = os.getenv('ENV', 'development').lower()
    azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '').strip()
    azure_key = os.getenv('AZURE_OPENAI_API_KEY', '').strip()

    if env == 'production' and azure_endpoint and azure_key:
        try:
            from openai import AzureOpenAI
            deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', input.model)
            api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')

            print(f"  [AZURE] Calling {azure_endpoint} with deployment {deployment}")
            client = AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                api_version=api_version,
            )
            completion = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": input.sys_prompt},
                    {"role": "user", "content": input.prompt},
                ],
                temperature=0.7,
                max_tokens=4000,
            )
            content = completion.choices[0].message.content
            return _parse_response(content)
        except Exception as e:
            print(f"  [AZURE] Failed: {e}, falling back to OpenAI...")

    # 3. Fall back to OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="No LLM API key configured. Set OPENAI_PROJ_API, OPENAI_API_KEY, "
                   "or LITELLM_URL+LITELLM_API_KEY in .env"
        )

    print(f"  [OPENAI] Calling OpenAI with model {input.model}")
    client = OpenAI(api_key=api_key)
    completion = client.chat.completions.create(
        model=input.model,
        messages=[
            {"role": "system", "content": input.sys_prompt},
            {"role": "user", "content": input.prompt},
        ],
        temperature=0.7,
    )
    content = completion.choices[0].message.content
    return _parse_response(content)


@app.post("/query")
def query_gai(input: QueryInput):
    """Alias for /proxy_query."""
    return proxy_query(input)


@app.post("/material_query")
def material_query_compat(input: QueryInput):
    """Backward-compat alias for /proxy_query."""
    return proxy_query(input)


def _parse_response(content):
    """Try to parse LLM response as JSON, return raw string if not possible."""
    if isinstance(content, (dict, list)):
        return {"response": content}
    if isinstance(content, str):
        try:
            return {"response": json.loads(content)}
        except json.JSONDecodeError:
            return {"response": content}
    return {"response": content}


# ============================================================
# OpenAI Batch API Endpoints
# ============================================================

@app.post("/batch/upload_file")
async def upload_batch_file(file: UploadFile = File(...)):
    """Proxy: upload JSONL file to OpenAI for batch processing."""
    from openai import OpenAI
    import httpx

    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    content = await file.read()
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.jsonl', delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        client = OpenAI(api_key=api_key, timeout=httpx.Timeout(600.0, connect=60.0), max_retries=2)
        with open(tmp_path, 'rb') as f:
            batch_file = client.files.create(file=f, purpose="batch")
        return {
            "file_id": batch_file.id, "filename": batch_file.filename,
            "bytes": batch_file.bytes, "created_at": batch_file.created_at,
            "status": batch_file.status
        }
    finally:
        os.unlink(tmp_path)


@app.post("/batch/create")
async def create_batch(request: BatchCreateRequest):
    """Proxy: create batch job with OpenAI."""
    from openai import OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    client = OpenAI(api_key=api_key)
    batch = client.batches.create(
        input_file_id=request.input_file_id,
        endpoint=request.endpoint,
        completion_window=request.completion_window
    )
    return {
        "id": batch.id, "status": batch.status,
        "created_at": batch.created_at, "input_file_id": batch.input_file_id
    }


@app.post("/batch/status")
async def get_batch_status(request: BatchStatusRequest):
    """Proxy: check batch status with OpenAI."""
    from openai import OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    client = OpenAI(api_key=api_key)
    batch = client.batches.retrieve(request.batch_id)
    return {
        "id": batch.id, "status": batch.status,
        "created_at": batch.created_at,
        "completed_at": getattr(batch, 'completed_at', None),
        "failed_at": getattr(batch, 'failed_at', None),
        "output_file_id": batch.output_file_id,
        "error_file_id": batch.error_file_id,
        "request_counts": getattr(batch, 'request_counts', None)
    }


@app.post("/batch/download_results")
async def download_batch_results(request: BatchStatusRequest):
    """Proxy: download batch results from OpenAI."""
    from openai import OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    client = OpenAI(api_key=api_key)
    batch = client.batches.retrieve(request.batch_id)
    if not batch.output_file_id:
        raise HTTPException(status_code=400, detail="Batch has no output file yet")

    file_content = client.files.content(batch.output_file_id)
    return {
        "batch_id": batch.id, "output_file_id": batch.output_file_id,
        "content": file_content.text, "status": batch.status
    }


# ============================================================
# S3 Endpoints
# ============================================================

@app.post("/s3/download")
async def download_s3_file(request: S3DownloadRequest):
    """Download file from S3."""
    from botocore.exceptions import ClientError
    try:
        response = get_s3_client().get_object(Bucket=request.bucket, Key=request.key)
        content = response['Body'].read()
        return {
            "bucket": request.bucket, "key": request.key, "size": len(content),
            "content": content.decode('utf-8') if request.key.endswith(('.txt', '.json', '.csv')) else None,
            "content_type": response['ContentType']
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


@app.post("/s3/list")
async def list_s3_files(request: S3ListRequest):
    """List files in S3 bucket with optional prefix."""
    from botocore.exceptions import ClientError
    try:
        response = get_s3_client().list_objects_v2(
            Bucket=request.bucket, Prefix=request.prefix, MaxKeys=request.max_keys
        )
        files = [{
            "key": obj['Key'], "size": obj['Size'],
            "last_modified": obj['LastModified'].isoformat()
        } for obj in response.get('Contents', [])]
        return {"bucket": request.bucket, "prefix": request.prefix, "count": len(files), "files": files}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


@app.post("/s3/upload")
async def upload_s3_content(request: S3UploadRequest):
    """Upload content to S3."""
    from botocore.exceptions import ClientError
    try:
        get_s3_client().put_object(
            Bucket=request.bucket, Key=request.key,
            Body=request.content.encode('utf-8'), ContentType='application/json'
        )
        return {"bucket": request.bucket, "key": request.key, "status": "uploaded"}
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")


@app.post("/s3/parquet/list")
async def list_parquet_files(request: ParquetListRequest):
    """List parquet files in S3 prefix."""
    from botocore.exceptions import ClientError
    try:
        s3_prefix = request.prefix.rstrip('/') + '/'
        paginator = get_s3_client().get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket=request.bucket, Prefix=s3_prefix,
            PaginationConfig={'MaxItems': request.max_keys}
        )
        parquet_files = []
        for page in pages:
            for obj in page.get('Contents', []):
                if obj['Key'].endswith('.parquet'):
                    parquet_files.append({
                        'key': obj['Key'], 'filename': obj['Key'].split('/')[-1],
                        'size': obj['Size'], 'size_mb': round(obj['Size'] / (1024 * 1024), 2),
                        'last_modified': obj['LastModified'].isoformat()
                    })
        return {'bucket': request.bucket, 'prefix': request.prefix, 'count': len(parquet_files), 'files': parquet_files}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


@app.get("/s3/parquet/download-binary")
async def download_parquet_binary(bucket: str, key: str):
    """Download parquet file as binary data."""
    from botocore.exceptions import ClientError
    try:
        response = get_s3_client().get_object(Bucket=bucket, Key=key)
        return StreamingResponse(
            response['Body'], media_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{key.split("/")[-1]}"'}
        )
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


@app.post("/s3/json/list")
async def list_json_files(request: JsonListRequest):
    """List JSON files in S3 prefix."""
    from botocore.exceptions import ClientError
    try:
        s3_prefix = request.prefix.rstrip('/') + '/'
        paginator = get_s3_client().get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket=request.bucket, Prefix=s3_prefix,
            PaginationConfig={'MaxItems': request.max_keys}
        )
        json_files = []
        for page in pages:
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.endswith('.json') and 'errors' not in key and 'processed_files.json' not in key:
                    json_files.append({
                        'key': key, 'filename': key.split('/')[-1],
                        'size': obj['Size'], 'last_modified': obj['LastModified'].isoformat()
                    })
        return {'bucket': request.bucket, 'prefix': request.prefix, 'count': len(json_files), 'files': json_files}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


@app.post("/s3/json/download")
async def download_json_file(request: S3DownloadRequest):
    """Download and parse a JSON file from S3."""
    from botocore.exceptions import ClientError
    try:
        response = get_s3_client().get_object(Bucket=request.bucket, Key=request.key)
        content = response['Body'].read().decode('utf-8')
        data = json.loads(content)
        return {'filename': request.key.split('/')[-1], 's3_key': request.key, 'data': data}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")


@app.post("/s3/json/batch-download")
async def batch_download_json(request: JsonBatchRequest):
    """Download multiple JSON files from S3."""
    results = {'bucket': request.bucket, 'successful': 0, 'failed': 0, 'files': []}
    for s3_key in request.keys:
        try:
            response = get_s3_client().get_object(Bucket=request.bucket, Key=s3_key)
            content = response['Body'].read().decode('utf-8')
            data = json.loads(content)
            results['successful'] += 1
            results['files'].append({
                'filename': s3_key.split('/')[-1], 's3_key': s3_key, 'status': 'success', 'data': data
            })
        except Exception as e:
            results['failed'] += 1
            results['files'].append({
                'filename': s3_key.split('/')[-1], 's3_key': s3_key, 'status': 'failed', 'error': str(e)
            })
    return results


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv('LLM_PROXY_PORT', '7001'))
    print(f"\nSoftPower Proxy starting on port {port}")
    print(f"  OpenAI key:  {'set' if os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY') else 'NOT SET'}")
    print(f"  LiteLLM:     {'configured' if os.getenv('LITELLM_URL') else 'not configured'}")
    print(f"  Azure:       {'configured' if os.getenv('AZURE_OPENAI_ENDPOINT') else 'not configured'}")
    print(f"  AWS creds:   {'set' if os.getenv('AWS_ACCESS_KEY_ID') else 'NOT SET (using default chain)'}")
    print(f"  ENV:         {os.getenv('ENV', 'development')}")
    print(f"\n  Endpoints:")
    print(f"    LLM:   POST /proxy_query")
    print(f"    S3:    POST /s3/list, /s3/download, /s3/upload")
    print(f"    Batch: POST /batch/upload_file, /batch/create, /batch/status")
    print(f"    Docs:  http://localhost:{port}/docs")
    print()

    uvicorn.run(app, host="0.0.0.0", port=port)
