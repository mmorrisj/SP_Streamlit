import boto3
import os
import json
from botocore.exceptions import ClientError
from backend.scripts.utils import Config
from typing import List, Dict, Any

cfg = Config.from_yaml()

session = boto3.Session()
# (2) Create an S3 client or resource
s3_client= boto3.client('s3')
bucket_name = 'morris-sp-bucket'
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

def load_processed_files_tracker(s3_prefix: str = "dsr_extracts/") -> Dict[str, Any]:
    """
    Load the processed files tracker from S3.
    Returns a dictionary with processed file names and metadata.
    """
    tracker_key = f"{s3_prefix}processed_files.json"

    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=tracker_key)
        tracker_data = json.loads(response['Body'].read().decode('utf-8'))
        print(f"Loaded processed files tracker with {len(tracker_data.get('processed_files', []))} entries")
        return tracker_data
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print("No existing processed files tracker found. Creating new one.")
            return {"processed_files": [], "last_updated": None}
        else:
            raise

def save_processed_files_tracker(tracker_data: Dict[str, Any], s3_prefix: str = "dsr_extracts/") -> None:
    """
    Save the processed files tracker to S3.
    """
    from datetime import datetime

    tracker_data["last_updated"] = datetime.utcnow().isoformat()
    tracker_key = f"{s3_prefix}processed_files.json"

    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=tracker_key,
            Body=json.dumps(tracker_data, indent=2),
            ContentType='application/json'
        )
        print(f"Saved processed files tracker to s3://{bucket_name}/{tracker_key}")
    except Exception as e:
        print(f"Error saving processed files tracker: {e}")
        raise

def list_s3_json_files(s3_prefix: str = "dsr_extracts/") -> List[Dict[str, Any]]:
    """
    List all JSON files in the S3 bucket prefix.
    Returns list of file metadata dictionaries.
    """
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

        print(f"Found {len(json_files)} JSON files in s3://{bucket_name}/{s3_prefix}")
        return json_files

    except Exception as e:
        print(f"Error listing S3 files: {e}")
        raise

def download_s3_json_file(s3_key: str) -> List[Dict[str, Any]]:
    """
    Download and parse a JSON file from S3.
    Returns the parsed JSON data.
    """
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        file_content = response['Body'].read().decode('utf-8')
        data = json.loads(file_content)
        print(f"Downloaded and parsed {s3_key}")
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
