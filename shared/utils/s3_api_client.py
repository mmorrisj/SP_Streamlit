"""
S3 API Client for interacting with FastAPI S3 proxy endpoints.

Extracted from the archived services/api/main.py so pipeline code
can access S3 through the FastAPI proxy without importing the server itself.
"""

import os
import requests
import pandas as pd
from io import BytesIO
from typing import Any, Dict, List, Optional


class S3APIClient:
    """Client for interacting with FastAPI S3 endpoints."""

    def __init__(self, api_url: Optional[str] = None):
        self.api_url = api_url or os.getenv('API_URL', 'http://host.docker.internal:5001')
        self.api_url = self.api_url.rstrip('/')

    def list_parquet_files(self, bucket: str, prefix: str = 'embeddings/', max_keys: int = 1000) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/parquet/list', json={'bucket': bucket, 'prefix': prefix, 'max_keys': max_keys})
        response.raise_for_status()
        return response.json()

    def get_parquet_metadata(self, bucket: str, key: str) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/parquet/metadata', json={'bucket': bucket, 'key': key})
        response.raise_for_status()
        return response.json()

    def read_parquet_data(self, bucket: str, key: str, num_rows: Optional[int] = None) -> Dict[str, Any]:
        payload = {'bucket': bucket, 'key': key}
        if num_rows:
            payload['num_rows'] = num_rows
        response = requests.post(f'{self.api_url}/s3/parquet/read', json=payload)
        response.raise_for_status()
        return response.json()

    def get_parquet_sample(self, bucket: str, key: str, num_rows: int = 10) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/parquet/sample', json={'bucket': bucket, 'key': key, 'num_rows': num_rows})
        response.raise_for_status()
        return response.json()

    def validate_parquet_schema(self, bucket: str, key: str, required_columns: Optional[List[str]] = None) -> Dict[str, Any]:
        payload = {'bucket': bucket, 'key': key}
        if required_columns:
            payload['required_columns'] = required_columns
        response = requests.post(f'{self.api_url}/s3/parquet/validate', json=payload)
        response.raise_for_status()
        return response.json()

    def extract_doc_ids(self, bucket: str, key: str) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/parquet/extract-ids', json={'bucket': bucket, 'key': key})
        response.raise_for_status()
        return response.json()

    def batch_get_metadata(self, bucket: str, keys: List[str]) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/parquet/batch-metadata', json={'bucket': bucket, 'keys': keys})
        response.raise_for_status()
        return response.json()

    def download_parquet_as_dataframe(self, bucket: str, key: str, num_rows: Optional[int] = None) -> pd.DataFrame:
        import tempfile
        response = requests.get(f'{self.api_url}/s3/parquet/download-binary', params={'bucket': bucket, 'key': key}, stream=True)
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.parquet') as temp_file:
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_path = temp_file.name
        try:
            df = pd.read_parquet(temp_path)
            if num_rows:
                df = df.head(num_rows)
            return df
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def list_json_files(self, bucket: str, prefix: str = 'dsr_extracts/', max_keys: int = 1000) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/json/list', json={'bucket': bucket, 'prefix': prefix, 'max_keys': max_keys})
        response.raise_for_status()
        return response.json()

    def download_json_file(self, bucket: str, key: str) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/json/download', json={'bucket': bucket, 'key': key})
        response.raise_for_status()
        return response.json()

    def batch_download_json(self, bucket: str, keys: List[str]) -> Dict[str, Any]:
        response = requests.post(f'{self.api_url}/s3/json/batch-download', json={'bucket': bucket, 'keys': keys})
        response.raise_for_status()
        return response.json()

    def upload_json_file(self, bucket: str, key: str, data: Dict[str, Any]) -> Dict[str, Any]:
        import json as json_lib
        content = json_lib.dumps(data, indent=2)
        response = requests.post(f'{self.api_url}/s3/upload', json={'bucket': bucket, 'key': key, 'content': content})
        response.raise_for_status()
        return response.json()


_s3_api_client = None


def get_s3_api_client(api_url: Optional[str] = None) -> S3APIClient:
    """Get or create S3 API client instance."""
    global _s3_api_client
    if _s3_api_client is None or api_url:
        _s3_api_client = S3APIClient(api_url)
    return _s3_api_client
