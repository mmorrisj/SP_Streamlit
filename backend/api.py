from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import tempfile
import boto3
from botocore.exceptions import ClientError
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from backend.scripts.utils import gai, fetch_gai_content, fetch_gai_response

app = FastAPI(title="SoftPower Backend API")

# S3 client (will use host's IAM role/credentials)
s3_client = boto3.client('s3')

# Request/Response models
class S3DownloadRequest(BaseModel):
    bucket: str
    key: str

class S3ListRequest(BaseModel):
    bucket: str
    prefix: Optional[str] = ""
    max_keys: Optional[int] = 1000

class S3FileInfo(BaseModel):
    key: str
    size: int
    last_modified: str

class QueryInput(BaseModel):
    model: str = "gpt-4.1"
    sys_prompt: str
    prompt: str

@app.post("/query")
def query_gai(input: QueryInput):
    response = gai(sys_prompt='',user_prompt=input.prompt,model=input.model)
    return fetch_gai_content(response)

@app.post("/material_query")
def material_gai_query(input: QueryInput):
    content = gai(input.sys_prompt, input.prompt, input.model)
    # If B returns string or C returns dict, either:
    return {"response": content}

@app.get("/")
async def root():
    return {"message": "SoftPower Backend API is running"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ml-backend",
        "db_host": os.getenv('DB_HOST', 'not configured')
    }

@app.post("/s3/download")
async def download_s3_file(request: S3DownloadRequest):
    """Download file from S3 and return content"""
    try:
        response = s3_client.get_object(Bucket=request.bucket, Key=request.key)
        content = response['Body'].read()
        return {
            "bucket": request.bucket,
            "key": request.key,
            "size": len(content),
            "content": content.decode('utf-8') if request.key.endswith(('.txt', '.json', '.csv')) else None,
            "content_type": response['ContentType']
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.post("/s3/list")
async def list_s3_files(request: S3ListRequest):
    """List files in S3 bucket with optional prefix"""
    try:
        response = s3_client.list_objects_v2(
            Bucket=request.bucket,
            Prefix=request.prefix,
            MaxKeys=request.max_keys
        )
        
        files = []
        for obj in response.get('Contents', []):
            files.append({
                "key": obj['Key'],
                "size": obj['Size'],
                "last_modified": obj['LastModified'].isoformat()
            })
        
        return {
            "bucket": request.bucket,
            "prefix": request.prefix,
            "count": len(files),
            "files": files
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.get("/s3/download-to-file")
async def download_s3_to_file(bucket: str, key: str, local_path: str):
    """Download S3 file directly to a local path"""
    try:
        s3_client.download_file(bucket, key, local_path)
        return {
            "bucket": bucket,
            "key": key,
            "local_path": local_path,
            "status": "downloaded"
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


class S3UploadRequest(BaseModel):
    bucket: str
    key: str
    content: str

@app.post("/s3/upload")
async def upload_s3_content(request: S3UploadRequest):
    """Upload content to S3"""
    try:
        s3_client.put_object(
            Bucket=request.bucket,
            Key=request.key,
            Body=request.content.encode('utf-8'),
            ContentType='application/json'
        )
        return {
            "bucket": request.bucket,
            "key": request.key,
            "status": "uploaded"
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")


# ============================================================================
# Parquet-Specific Endpoints
# ============================================================================

class ParquetListRequest(BaseModel):
    bucket: str
    prefix: str = "embeddings/"
    max_keys: int = 1000

class ParquetDownloadRequest(BaseModel):
    bucket: str
    key: str
    num_rows: Optional[int] = None  # If specified, only return this many rows

class ParquetValidateRequest(BaseModel):
    bucket: str
    key: str
    required_columns: Optional[List[str]] = None

class ParquetBatchRequest(BaseModel):
    bucket: str
    keys: List[str]


@app.post("/s3/parquet/list")
async def list_parquet_files(request: ParquetListRequest):
    """List all parquet files in S3 prefix"""
    try:
        s3_prefix = request.prefix.rstrip('/') + '/'
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket=request.bucket,
            Prefix=s3_prefix,
            PaginationConfig={'MaxItems': request.max_keys}
        )

        parquet_files = []
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    if key.endswith('.parquet'):
                        parquet_files.append({
                            'key': key,
                            'filename': key.split('/')[-1],
                            'size': obj['Size'],
                            'size_mb': round(obj['Size'] / (1024 * 1024), 2),
                            'last_modified': obj['LastModified'].isoformat()
                        })

        return {
            'bucket': request.bucket,
            'prefix': request.prefix,
            'count': len(parquet_files),
            'files': parquet_files
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/s3/parquet/metadata")
async def get_parquet_metadata(request: S3DownloadRequest):
    """Get metadata from parquet file without downloading full data"""
    temp_path = None
    try:
        # Download to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.parquet')
        temp_path = temp_file.name
        temp_file.close()

        s3_client.download_file(request.bucket, request.key, temp_path)

        # Read parquet metadata
        parquet_file = pq.ParquetFile(temp_path)
        metadata = parquet_file.metadata

        return {
            'filename': request.key.split('/')[-1],
            's3_key': request.key,
            'num_rows': metadata.num_rows,
            'num_columns': metadata.num_columns,
            'num_row_groups': metadata.num_row_groups,
            'columns': [
                {
                    'name': parquet_file.schema[i].name,
                    'type': str(parquet_file.schema[i].physical_type)
                }
                for i in range(len(parquet_file.schema))
            ],
            'created_by': metadata.created_by,
            'format_version': metadata.format_version
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@app.post("/s3/parquet/read")
async def read_parquet_file(request: ParquetDownloadRequest):
    """Read parquet file from S3 and return data"""
    temp_path = None
    try:
        # Download to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.parquet')
        temp_path = temp_file.name
        temp_file.close()

        s3_client.download_file(request.bucket, request.key, temp_path)

        # Read parquet file
        df = pd.read_parquet(temp_path)

        # Limit rows if specified
        if request.num_rows:
            df = df.head(request.num_rows)

        # Convert to dict, handling special types
        data = []
        for _, row in df.iterrows():
            row_dict = {}
            for col, val in row.items():
                # Handle numpy arrays (embeddings)
                if isinstance(val, np.ndarray):
                    row_dict[col] = {
                        'type': 'array',
                        'shape': list(val.shape),
                        'dtype': str(val.dtype),
                        'sample': val[:5].tolist() if len(val) > 5 else val.tolist()
                    }
                # Handle lists
                elif isinstance(val, list):
                    row_dict[col] = {
                        'type': 'list',
                        'length': len(val),
                        'sample': val[:5] if len(val) > 5 else val
                    }
                # Handle pandas timestamps
                elif pd.isna(val):
                    row_dict[col] = None
                # Handle regular values
                else:
                    row_dict[col] = val
            data.append(row_dict)

        return {
            'filename': request.key.split('/')[-1],
            's3_key': request.key,
            'total_rows': len(df),
            'returned_rows': len(data),
            'columns': list(df.columns),
            'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()},
            'data': data
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@app.post("/s3/parquet/sample")
async def get_parquet_sample(request: ParquetDownloadRequest):
    """Get a sample of rows from parquet file (default 10 rows)"""
    if not request.num_rows:
        request.num_rows = 10

    return await read_parquet_file(request)


@app.post("/s3/parquet/validate")
async def validate_parquet_schema(request: ParquetValidateRequest):
    """Validate parquet file schema"""
    temp_path = None
    try:
        # Download to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.parquet')
        temp_path = temp_file.name
        temp_file.close()

        s3_client.download_file(request.bucket, request.key, temp_path)

        # Read parquet file
        df = pd.read_parquet(temp_path)

        # Default validation for embedding files
        if request.required_columns is None:
            # Flexible column names
            id_cols = ['doc_id', 'document_id', 'id', 'atom_id', 'ATOM ID']
            embedding_cols = ['embedding', 'embeddings', 'vector']

            has_id = any(col in df.columns for col in id_cols)
            has_embedding = any(col in df.columns for col in embedding_cols)

            found_id_col = next((col for col in id_cols if col in df.columns), None)
            found_emb_col = next((col for col in embedding_cols if col in df.columns), None)

            is_valid = has_id and has_embedding

            errors = []
            if not has_id:
                errors.append(f"Missing ID column (expected one of: {id_cols})")
            if not has_embedding:
                errors.append(f"Missing embedding column (expected one of: {embedding_cols})")

            return {
                'valid': is_valid,
                'filename': request.key.split('/')[-1],
                's3_key': request.key,
                'columns': list(df.columns),
                'num_rows': len(df),
                'has_id_column': has_id,
                'has_embedding_column': has_embedding,
                'found_id_column': found_id_col,
                'found_embedding_column': found_emb_col,
                'errors': errors
            }
        else:
            # Check for specific required columns
            missing_cols = [col for col in request.required_columns if col not in df.columns]
            is_valid = len(missing_cols) == 0

            return {
                'valid': is_valid,
                'filename': request.key.split('/')[-1],
                's3_key': request.key,
                'columns': list(df.columns),
                'num_rows': len(df),
                'required_columns': request.required_columns,
                'missing_columns': missing_cols,
                'errors': [f"Missing required columns: {missing_cols}"] if missing_cols else []
            }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except Exception as e:
        return {
            'valid': False,
            'filename': request.key.split('/')[-1],
            's3_key': request.key,
            'errors': [f"Error validating schema: {str(e)}"]
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@app.post("/s3/parquet/extract-ids")
async def extract_doc_ids(request: S3DownloadRequest):
    """Extract all document IDs from a parquet file"""
    temp_path = None
    try:
        # Download to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.parquet')
        temp_path = temp_file.name
        temp_file.close()

        s3_client.download_file(request.bucket, request.key, temp_path)

        # Read parquet file
        df = pd.read_parquet(temp_path)

        # Find ID column
        id_cols = ['doc_id', 'document_id', 'id', 'atom_id', 'ATOM ID']
        id_col = next((col for col in id_cols if col in df.columns), None)

        if not id_col:
            raise HTTPException(status_code=400, detail=f"No ID column found. Expected one of: {id_cols}")

        # Extract unique IDs
        doc_ids = df[id_col].unique().tolist()
        doc_ids = [str(doc_id) for doc_id in doc_ids]

        return {
            'filename': request.key.split('/')[-1],
            's3_key': request.key,
            'id_column': id_col,
            'total_rows': len(df),
            'unique_ids': len(doc_ids),
            'doc_ids': doc_ids
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@app.post("/s3/parquet/batch-metadata")
async def batch_get_parquet_metadata(request: ParquetBatchRequest):
    """Get metadata for multiple parquet files"""
    results = {
        'bucket': request.bucket,
        'total_files': len(request.keys),
        'processed': 0,
        'failed': 0,
        'total_rows': 0,
        'files': []
    }

    for s3_key in request.keys:
        temp_path = None
        try:
            # Download to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.parquet')
            temp_path = temp_file.name
            temp_file.close()

            s3_client.download_file(request.bucket, s3_key, temp_path)

            # Read parquet metadata
            parquet_file = pq.ParquetFile(temp_path)
            metadata = parquet_file.metadata

            results['processed'] += 1
            results['total_rows'] += metadata.num_rows
            results['files'].append({
                'filename': s3_key.split('/')[-1],
                's3_key': s3_key,
                'num_rows': metadata.num_rows,
                'num_columns': metadata.num_columns,
                'status': 'success'
            })

        except Exception as e:
            results['failed'] += 1
            results['files'].append({
                'filename': s3_key.split('/')[-1],
                's3_key': s3_key,
                'status': 'failed',
                'error': str(e)
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    return results


@app.get("/s3/parquet/download-binary")
async def download_parquet_binary(bucket: str, key: str):
    """Download parquet file as binary data"""
    from fastapi.responses import StreamingResponse
    try:
        # Stream file from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)

        return StreamingResponse(
            response['Body'],
            media_type='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{key.split("/")[-1]}"'
            }
        )
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# S3 API Client (for programmatic access to above endpoints)
# ============================================================================

import requests
from io import BytesIO


class S3APIClient:
    """Client for interacting with FastAPI S3 endpoints."""

    def __init__(self, api_url: Optional[str] = None):
        """
        Initialize API client.

        Args:
            api_url: Base URL of FastAPI server (default: from env or http://host.docker.internal:5001)
        """
        self.api_url = api_url or os.getenv('API_URL', 'http://host.docker.internal:5001')
        self.api_url = self.api_url.rstrip('/')

    def list_parquet_files(
        self,
        bucket: str,
        prefix: str = 'embeddings/',
        max_keys: int = 1000
    ) -> Dict[str, Any]:
        """
        List parquet files in S3.

        Args:
            bucket: S3 bucket name
            prefix: S3 prefix/folder
            max_keys: Maximum number of files to return

        Returns:
            Response with file list
        """
        response = requests.post(
            f'{self.api_url}/s3/parquet/list',
            json={'bucket': bucket, 'prefix': prefix, 'max_keys': max_keys}
        )
        response.raise_for_status()
        return response.json()

    def get_parquet_metadata(self, bucket: str, key: str) -> Dict[str, Any]:
        """
        Get metadata from parquet file.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            Parquet metadata
        """
        response = requests.post(
            f'{self.api_url}/s3/parquet/metadata',
            json={'bucket': bucket, 'key': key}
        )
        response.raise_for_status()
        return response.json()

    def read_parquet_data(
        self,
        bucket: str,
        key: str,
        num_rows: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Read parquet file data.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            num_rows: Optional limit on number of rows

        Returns:
            Parquet data and metadata
        """
        payload = {'bucket': bucket, 'key': key}
        if num_rows:
            payload['num_rows'] = num_rows

        response = requests.post(
            f'{self.api_url}/s3/parquet/read',
            json=payload
        )
        response.raise_for_status()
        return response.json()

    def get_parquet_sample(
        self,
        bucket: str,
        key: str,
        num_rows: int = 10
    ) -> Dict[str, Any]:
        """
        Get sample rows from parquet file.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            num_rows: Number of sample rows

        Returns:
            Sample data and metadata
        """
        response = requests.post(
            f'{self.api_url}/s3/parquet/sample',
            json={'bucket': bucket, 'key': key, 'num_rows': num_rows}
        )
        response.raise_for_status()
        return response.json()

    def validate_parquet_schema(
        self,
        bucket: str,
        key: str,
        required_columns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Validate parquet file schema.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            required_columns: Optional list of required columns

        Returns:
            Validation result
        """
        payload = {'bucket': bucket, 'key': key}
        if required_columns:
            payload['required_columns'] = required_columns

        response = requests.post(
            f'{self.api_url}/s3/parquet/validate',
            json=payload
        )
        response.raise_for_status()
        return response.json()

    def extract_doc_ids(self, bucket: str, key: str) -> Dict[str, Any]:
        """
        Extract document IDs from parquet file.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            List of document IDs
        """
        response = requests.post(
            f'{self.api_url}/s3/parquet/extract-ids',
            json={'bucket': bucket, 'key': key}
        )
        response.raise_for_status()
        return response.json()

    def batch_get_metadata(
        self,
        bucket: str,
        keys: List[str]
    ) -> Dict[str, Any]:
        """
        Get metadata for multiple parquet files.

        Args:
            bucket: S3 bucket name
            keys: List of S3 object keys

        Returns:
            Batch metadata results
        """
        response = requests.post(
            f'{self.api_url}/s3/parquet/batch-metadata',
            json={'bucket': bucket, 'keys': keys}
        )
        response.raise_for_status()
        return response.json()

    def download_parquet_as_dataframe(
        self,
        bucket: str,
        key: str,
        num_rows: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Download full parquet file and convert to DataFrame with complete embeddings.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            num_rows: Optional limit on rows (applied after download)

        Returns:
            pandas DataFrame with full embedding arrays
        """
        # Download binary parquet file
        response = requests.get(
            f'{self.api_url}/s3/parquet/download-binary',
            params={'bucket': bucket, 'key': key},
            stream=True
        )
        response.raise_for_status()

        # Save to temp file and read with pandas
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.parquet') as temp_file:
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_path = temp_file.name

        try:
            # Read parquet file
            df = pd.read_parquet(temp_path)

            # Limit rows if specified
            if num_rows:
                df = df.head(num_rows)

            return df
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)


# Singleton instance
_s3_api_client = None


def get_s3_api_client(api_url: Optional[str] = None) -> S3APIClient:
    """Get or create S3 API client instance."""
    global _s3_api_client
    if _s3_api_client is None or api_url:
        _s3_api_client = S3APIClient(api_url)
    return _s3_api_client