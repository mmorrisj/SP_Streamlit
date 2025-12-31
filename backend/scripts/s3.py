"""
Legacy module - S3 utilities now live in services.pipeline.embeddings.s3

This module provides backwards compatibility by re-exporting
all S3 functions from the main module.
"""

from services.pipeline.embeddings.s3 import (
    # Configuration functions
    get_s3_config,
    get_bucket_name,
    get_s3_prefix,
    get_bucket_path,

    # S3 client and variables
    s3_client,
    session,
    bucket_name,
    bucket_path,

    # Core functions
    file_exists,
    s3_upload,

    # API client functions
    _get_api_client,

    # Tracker functions
    load_processed_files_tracker,
    save_processed_files_tracker,

    # File operations
    list_s3_json_files,
    download_s3_json_file,
    get_unprocessed_s3_files,
    mark_file_as_processed,
    reprocess_files,
    load_dsr_from_s3,
)

__all__ = [
    'get_s3_config',
    'get_bucket_name',
    'get_s3_prefix',
    'get_bucket_path',
    's3_client',
    'session',
    'bucket_name',
    'bucket_path',
    'file_exists',
    's3_upload',
    '_get_api_client',
    'load_processed_files_tracker',
    'save_processed_files_tracker',
    'list_s3_json_files',
    'download_s3_json_file',
    'get_unprocessed_s3_files',
    'mark_file_as_processed',
    'reprocess_files',
    'load_dsr_from_s3',
]
