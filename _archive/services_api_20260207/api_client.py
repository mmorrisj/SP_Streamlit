"""
Legacy module - API client now lives in backend.api

This module provides backwards compatibility by re-exporting
the S3APIClient and get_s3_api_client from the main API module.
"""

from services.api.main import S3APIClient, get_s3_api_client

__all__ = ['S3APIClient', 'get_s3_api_client']
