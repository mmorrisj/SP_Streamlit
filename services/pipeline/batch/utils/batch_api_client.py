"""
OpenAI Batch API client that works through FastAPI proxy.

This module provides a client for OpenAI Batch API operations that routes
requests through a FastAPI proxy server running on the host machine. This
allows Docker containers to access the OpenAI API via the host's credentials.

Usage:
    from services.pipeline.batch.utils.batch_api_client import get_batch_api_client

    client = get_batch_api_client()

    # Upload file
    result = client.upload_file('/path/to/input.jsonl')
    file_id = result['file_id']

    # Create batch
    batch = client.create_batch(file_id)
    batch_id = batch['id']

    # Check status
    status = client.get_batch_status(batch_id)

    # Download results when complete
    if status['status'] == 'completed':
        results = client.download_results(batch_id)
"""
import os
import requests
from typing import Dict, Any, Optional
from pathlib import Path


class BatchAPIClient:
    """Client for OpenAI Batch API operations via FastAPI proxy."""

    def __init__(self, api_url: Optional[str] = None):
        """
        Initialize Batch API client.

        Args:
            api_url: Base URL of FastAPI server (defaults to API_URL env var)
        """
        if api_url is None:
            api_url = os.getenv('API_URL', '').strip()
            if not api_url:
                # Backward compat: try FASTAPI_URL and extract base
                fastapi_url = os.getenv('FASTAPI_URL', '').strip()
                if fastapi_url:
                    api_url = fastapi_url.split('/proxy_query')[0].split('/material_query')[0]

        if not api_url:
            raise ValueError(
                "API_URL environment variable not set. "
                "Set API_URL=http://localhost:5001 (or appropriate host)"
            )

        self.base_url = api_url.rstrip('/')
        print(f"[BATCH API] Using proxy at: {self.base_url}")

    def upload_file(self, file_path: str) -> Dict[str, Any]:
        """
        Upload JSONL file to OpenAI for batch processing.

        Args:
            file_path: Path to JSONL file

        Returns:
            Dictionary with file_id and metadata

        Raises:
            requests.RequestException: If upload fails
        """
        url = f"{self.base_url}/batch/upload_file"

        with open(file_path, 'rb') as f:
            files = {'file': (Path(file_path).name, f, 'application/jsonl')}
            response = requests.post(url, files=files, timeout=300)

        response.raise_for_status()
        return response.json()

    def create_batch(
        self,
        input_file_id: str,
        endpoint: str = "/v1/chat/completions",
        completion_window: str = "24h"
    ) -> Dict[str, Any]:
        """
        Create batch job with OpenAI.

        Args:
            input_file_id: OpenAI file ID from upload_file()
            endpoint: OpenAI API endpoint (default: /v1/chat/completions)
            completion_window: Time window for completion (default: 24h)

        Returns:
            Dictionary with batch ID and metadata

        Raises:
            requests.RequestException: If batch creation fails
        """
        url = f"{self.base_url}/batch/create"

        payload = {
            "input_file_id": input_file_id,
            "endpoint": endpoint,
            "completion_window": completion_window
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """
        Get status of batch job.

        Args:
            batch_id: OpenAI batch ID

        Returns:
            Dictionary with batch status and metadata

        Raises:
            requests.RequestException: If status check fails
        """
        url = f"{self.base_url}/batch/status"

        payload = {"batch_id": batch_id}

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def download_results(self, batch_id: str) -> Dict[str, Any]:
        """
        Download batch processing results.

        Args:
            batch_id: OpenAI batch ID

        Returns:
            Dictionary with content and metadata

        Raises:
            requests.RequestException: If download fails
        """
        url = f"{self.base_url}/batch/download_results"

        payload = {"batch_id": batch_id}

        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()


# Singleton instance
_batch_api_client = None


def get_batch_api_client(api_url: Optional[str] = None) -> BatchAPIClient:
    """Get or create Batch API client instance."""
    global _batch_api_client
    if _batch_api_client is None or api_url:
        _batch_api_client = BatchAPIClient(api_url)
    return _batch_api_client
