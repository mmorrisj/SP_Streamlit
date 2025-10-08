import boto3
import os
import json
from botocore.exceptions import ClientError
from backend.scripts.utils import Config
from typing import List, Dict, Any, Optional
from backend.api import get_s3_api_client

cfg = Config.from_yaml()

session = boto3.Session()
# (2) Create an S3 client or resource
s3_client= boto3.client('s3')
bucket_name = 'morris-sp-bucket'

# Initialize API client for S3 operations (will use FastAPI proxy when available)
_use_api_client = os.getenv('USE_S3_API_CLIENT', 'true').lower() == 'true'
_api_client = get_s3_api_client() if _use_api_client else None
def file_exists(bucket, key):
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        else:
            raise  # re-raise unexpected errors
def s3_upload(directory,file_type,s3_dir,bucket='morris-sp-bucket',force=False):
    # Upload .json files if they don't already exist
    for filename in os.listdir(directory):
        if filename.endswith(file_type):
            full_path = os.path.join(directory, filename)
            s3_key = f'{s3_dir}/{filename}'
            if force:
                print(f"Uploading {filename} to s3://{bucket_name}/{s3_key}")
                s3_client.upload_file(full_path, bucket_name, s3_key)
            else:
                if file_exists(bucket, s3_key):
                    print(f"Skipping {filename} — already exists in S3.")
                else:
                    print(f"Uploading {filename} to s3://{bucket_name}/{s3_key}")
                    s3_client.upload_file(full_path, bucket_name, s3_key)
    print("Upload complete.")

    
    
bucket_path = f"s3://{bucket_name}/dsr_extracts/"

def load_processed_files_tracker(s3_prefix: str = "dsr_extracts/", api_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Load the processed files tracker from S3.
    Returns a dictionary with processed file names and metadata.

    Args:
        s3_prefix: S3 prefix/folder
        api_url: Optional API URL (overrides default)
    """
    tracker_key = f"{s3_prefix}processed_files.json"

    # Use API client if available
    if _use_api_client or api_url:
        try:
            client = get_s3_api_client(api_url) if api_url else _api_client
            response = client.download_json_file(bucket=bucket_name, key=tracker_key)
            tracker_data = response['data']
            print(f"Loaded processed files tracker with {len(tracker_data.get('processed_files', []))} entries (via API)")
            return tracker_data
        except Exception as e:
            # If file doesn't exist, return empty tracker
            if '404' in str(e) or 'NoSuchKey' in str(e):
                print("No existing processed files tracker found. Creating new one.")
                return {"processed_files": [], "last_updated": None}
            print(f"API client failed, falling back to direct S3: {e}")
            # Fall through to direct S3 access

    # Fallback to direct boto3 access
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=tracker_key)
        tracker_data = json.loads(response['Body'].read().decode('utf-8'))
        print(f"Loaded processed files tracker with {len(tracker_data.get('processed_files', []))} entries (direct)")
        return tracker_data
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print("No existing processed files tracker found. Creating new one.")
            return {"processed_files": [], "last_updated": None}
        else:
            raise

def save_processed_files_tracker(tracker_data: Dict[str, Any], s3_prefix: str = "dsr_extracts/", api_url: Optional[str] = None) -> None:
    """
    Save the processed files tracker to S3.

    Args:
        tracker_data: Tracker data to save
        s3_prefix: S3 prefix/folder
        api_url: Optional API URL (overrides default)
    """
    from datetime import datetime

    tracker_data["last_updated"] = datetime.utcnow().isoformat()
    tracker_key = f"{s3_prefix}processed_files.json"

    # Use API client if available
    if _use_api_client or api_url:
        try:
            client = get_s3_api_client(api_url) if api_url else _api_client
            client.upload_json_file(bucket=bucket_name, key=tracker_key, data=tracker_data)
            print(f"Saved processed files tracker to s3://{bucket_name}/{tracker_key} (via API)")
            return
        except Exception as e:
            print(f"API client failed, falling back to direct S3: {e}")
            # Fall through to direct S3 access

    # Fallback to direct boto3 access
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=tracker_key,
            Body=json.dumps(tracker_data, indent=2),
            ContentType='application/json'
        )
        print(f"Saved processed files tracker to s3://{bucket_name}/{tracker_key} (direct)")
    except Exception as e:
        print(f"Error saving processed files tracker: {e}")
        raise

def list_s3_json_files(s3_prefix: str = "dsr_extracts/", api_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all JSON files in the S3 bucket prefix.
    Returns list of file metadata dictionaries.

    Args:
        s3_prefix: S3 prefix/folder to search
        api_url: Optional API URL (overrides default)
    """
    # Use API client if available
    if _use_api_client or api_url:
        try:
            client = get_s3_api_client(api_url) if api_url else _api_client
            response = client.list_json_files(bucket=bucket_name, prefix=s3_prefix)
            json_files = response['files']

            # Convert to match old format (add last_modified as datetime-like object)
            from datetime import datetime
            for file_info in json_files:
                if isinstance(file_info.get('last_modified'), str):
                    file_info['last_modified'] = datetime.fromisoformat(file_info['last_modified'].replace('Z', '+00:00'))

            print(f"Found {len(json_files)} JSON files in s3://{bucket_name}/{s3_prefix} (via API)")
            return json_files
        except Exception as e:
            print(f"API client failed, falling back to direct S3: {e}")
            # Fall through to direct S3 access

    # Fallback to direct boto3 access
    json_files = []
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix)

        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    if key.endswith('.json') and 'errors' not in key and 'processed_files.json' not in key:
                        json_files.append({
                            'key': key,
                            'filename': key.split('/')[-1],
                            'size': obj['Size'],
                            'last_modified': obj['LastModified']
                        })

        print(f"Found {len(json_files)} JSON files in s3://{bucket_name}/{s3_prefix} (direct)")
        return json_files

    except Exception as e:
        print(f"Error listing S3 files: {e}")
        raise

def download_s3_json_file(s3_key: str, api_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Download and parse a JSON file from S3.
    Returns the parsed JSON data.

    Args:
        s3_key: S3 object key
        api_url: Optional API URL (overrides default)
    """
    # Use API client if available
    if _use_api_client or api_url:
        try:
            client = get_s3_api_client(api_url) if api_url else _api_client
            response = client.download_json_file(bucket=bucket_name, key=s3_key)
            print(f"Downloaded and parsed {s3_key} (via API)")
            return response['data']
        except Exception as e:
            print(f"API client failed, falling back to direct S3: {e}")
            # Fall through to direct S3 access

    # Fallback to direct boto3 access
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        file_content = response['Body'].read().decode('utf-8')
        data = json.loads(file_content)
        print(f"Downloaded and parsed {s3_key} (direct)")
        return data
    except Exception as e:
        print(f"Error downloading {s3_key}: {e}")
        raise

def get_unprocessed_s3_files(s3_prefix: str = "dsr_extracts/") -> List[Dict[str, Any]]:
    """
    Get list of JSON files from S3 that haven't been processed yet.
    """
    # Load processed files tracker
    tracker_data = load_processed_files_tracker(s3_prefix)
    processed_files = set(tracker_data.get('processed_files', []))

    # Get all JSON files in S3
    all_files = list_s3_json_files(s3_prefix)

    # Filter out already processed files
    unprocessed_files = [
        file_info for file_info in all_files
        if file_info['filename'] not in processed_files
    ]

    print(f"Found {len(unprocessed_files)} unprocessed files out of {len(all_files)} total JSON files")
    return unprocessed_files

def mark_file_as_processed(filename: str, s3_prefix: str = "dsr_extracts/") -> None:
    """
    Mark a file as processed in the tracker.
    """
    tracker_data = load_processed_files_tracker(s3_prefix)
    if filename not in tracker_data['processed_files']:
        tracker_data['processed_files'].append(filename)
        save_processed_files_tracker(tracker_data, s3_prefix)
        print(f"Marked {filename} as processed")

def reprocess_files(filenames: List[str], s3_prefix: str = "dsr_extracts/") -> None:
    """
    Remove files from the processed list to allow reprocessing.
    """
    tracker_data = load_processed_files_tracker(s3_prefix)
    processed_files = tracker_data['processed_files']

    removed_count = 0
    for filename in filenames:
        if filename in processed_files:
            processed_files.remove(filename)
            removed_count += 1
            print(f"Removed {filename} from processed list")

    if removed_count > 0:
        save_processed_files_tracker(tracker_data, s3_prefix)
        print(f"Marked {removed_count} files for reprocessing")
    else:
        print("No files were marked for reprocessing")

def load_dsr_from_s3(s3_prefix: str = "dsr_extracts/", specific_files: List[str] = None) -> List[List[Dict[str, Any]]]:
    """
    Load DSR JSON files from S3 bucket.

    Args:
        s3_prefix: S3 prefix/folder to search for JSON files
        specific_files: Optional list of specific filenames to process

    Returns:
        List of parsed JSON data from each file
    """
    dsr_data = []

    if specific_files:
        # Process only specific files
        files_to_process = []
        for filename in specific_files:
            s3_key = f"{s3_prefix}{filename}"
            files_to_process.append({
                'key': s3_key,
                'filename': filename
            })
        print(f"Processing {len(specific_files)} specific files")
    else:
        # Get unprocessed files
        files_to_process = get_unprocessed_s3_files(s3_prefix)

    if not files_to_process:
        print("No files to process")
        return dsr_data

    for file_info in files_to_process:
        try:
            # Download and parse the JSON file
            data = download_s3_json_file(file_info['key'])
            dsr_data.append(data)

            # Mark as processed (only if not processing specific files)
            if not specific_files:
                mark_file_as_processed(file_info['filename'], s3_prefix)

        except Exception as e:
            print(f"Error processing {file_info['filename']}: {e}")
            continue

    print(f"Successfully loaded {len(dsr_data)} DSR files from S3")
    return dsr_data
