#!/usr/bin/env python3
"""Upload a file to S3.

Usage:
    python scripts/s3_upload_file.py /path/to/file.png
    python scripts/s3_upload_file.py /path/to/file.png --prefix images/subfolder/
    python scripts/s3_upload_file.py /path/to/file.png --key custom-name.png
    python scripts/s3_upload_file.py /path/to/dir/ --recursive
    python scripts/s3_upload_file.py /path/to/file.png --force
"""

import argparse
import os
import sys
import mimetypes

import boto3
from botocore.exceptions import ClientError

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.pipeline.embeddings.s3 import get_bucket_name, file_exists

DEFAULT_PREFIX = "images/"

s3_client = boto3.client('s3')


def upload_file(local_path: str, bucket: str, s3_key: str, force: bool = False) -> bool:
    """Upload a single file to S3.

    Returns True if the file was uploaded, False if skipped.
    """
    if not force and file_exists(bucket, s3_key):
        print(f"Skipping {os.path.basename(local_path)} — already exists at s3://{bucket}/{s3_key}")
        return False

    content_type, _ = mimetypes.guess_type(local_path)
    extra_args = {}
    if content_type:
        extra_args['ContentType'] = content_type

    print(f"Uploading {local_path} -> s3://{bucket}/{s3_key}")
    s3_client.upload_file(local_path, bucket, s3_key, ExtraArgs=extra_args or None)
    return True


def upload_directory(local_dir: str, bucket: str, prefix: str, force: bool = False) -> int:
    """Recursively upload all files in a directory. Returns count of uploaded files."""
    uploaded = 0
    for root, _dirs, files in os.walk(local_dir):
        for filename in files:
            local_path = os.path.join(root, filename)
            relative = os.path.relpath(local_path, local_dir)
            s3_key = f"{prefix}{relative}"
            try:
                if upload_file(local_path, bucket, s3_key, force):
                    uploaded += 1
            except ClientError as e:
                print(f"Error uploading {local_path}: {e}")
    return uploaded


def main():
    parser = argparse.ArgumentParser(description="Upload a file or directory to S3")
    parser.add_argument("path", help="Local file or directory path to upload")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX,
                        help=f"S3 key prefix (default: {DEFAULT_PREFIX})")
    parser.add_argument("--key", default=None,
                        help="Custom S3 key name (overrides prefix + filename)")
    parser.add_argument("--bucket", default=None,
                        help="S3 bucket (default: from config.yaml)")
    parser.add_argument("--recursive", action="store_true",
                        help="Upload all files in a directory recursively")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files in S3")
    args = parser.parse_args()

    local_path = os.path.abspath(args.path)
    bucket = args.bucket or get_bucket_name()

    if not os.path.exists(local_path):
        print(f"Error: {local_path} does not exist")
        sys.exit(1)

    if os.path.isdir(local_path):
        if not args.recursive:
            print("Error: path is a directory. Use --recursive to upload all files.")
            sys.exit(1)
        prefix = args.prefix if args.prefix.endswith('/') else args.prefix + '/'
        count = upload_directory(local_path, bucket, prefix, args.force)
        print(f"Done. Uploaded {count} file(s) to s3://{bucket}/{prefix}")
    else:
        if args.key:
            s3_key = args.key
        else:
            prefix = args.prefix if args.prefix.endswith('/') else args.prefix + '/'
            s3_key = f"{prefix}{os.path.basename(local_path)}"

        try:
            upload_file(local_path, bucket, s3_key, args.force)
            print(f"Done. s3://{bucket}/{s3_key}")
        except ClientError as e:
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
