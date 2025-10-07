"""
API Client for FastAPI S3 Operations

This client communicates with the FastAPI backend running outside Docker
to handle all S3 operations, including parquet file access.
"""

import os
import requests
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from io import BytesIO


class S3APIClient:
    """Client for interacting with FastAPI S3 endpoints."""

    def __init__(self, api_url: Optional[str] = None):
        """
        Initialize API client.

        Args:
            api_url: Base URL of FastAPI server (default: from env or localhost)
        """
        self.api_url = api_url or os.getenv('API_URL', 'http://localhost:8000')
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
            import os
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
