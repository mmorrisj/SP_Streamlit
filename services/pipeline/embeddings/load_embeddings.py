"""
Load pre-computed embeddings from parquet files (local or S3) into LangChain PGVector tables.

This script loads parquet files containing embeddings that are already aligned by doc_id
and stores them in the appropriate LangChain vector store collection.

Usage:
    # Load from local directory
    python load_embeddings.py --source local --directory data/processed_embeddings

    # Load from S3
    python load_embeddings.py --source s3 --s3-prefix embeddings/

    # Check status
    python load_embeddings.py --source local --status
    python load_embeddings.py --source s3 --status

    # Reprocess specific files
    python load_embeddings.py --source local --reprocess file1.parquet file2.parquet
"""

import os
import json
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from pathlib import Path
from sqlalchemy import text
from shared.database.database import get_session, get_engine
from shared.utils.utils import Config
from services.pipeline.embeddings.embedding_vectorstore import chunk_store
from services.pipeline.embeddings.s3 import _get_api_client, bucket_name
import ast

cfg = Config.from_yaml()

# Tracker file locations
LOCAL_TRACKER_FILE = "data/processed_embeddings/.processed_tracker.json"
S3_TRACKER_PREFIX = "embeddings/"

def parse_embedding_string(emb_str: str) -> np.ndarray:
    """
    Parse embedding from string representation to numpy array.

    Args:
        emb_str: String representation of embedding (JSON list format)

    Returns:
        numpy array of float32
    """
    if isinstance(emb_str, str):
        # Parse JSON-like string to Python list
        emb_list = ast.literal_eval(emb_str)
        return np.array(emb_list, dtype=np.float32)
    elif isinstance(emb_str, (list, np.ndarray)):
        return np.array(emb_str, dtype=np.float32)
    else:
        raise ValueError(f"Unexpected embedding type: {type(emb_str)}")

def is_embedding_already_loaded(doc_id: str, collection_name: str = "chunk_embeddings") -> bool:
    """
    Check if a document already has embeddings in LangChain's table for the given collection.

    Args:
        doc_id: Document ID to check
        collection_name: LangChain collection name

    Returns:
        True if embedding exists, False otherwise
    """
    from sqlalchemy import create_engine

    # Build connection string using environment variables (same as embedding_vectorstore.py)
    user = os.getenv("POSTGRES_USER", "matthew50")
    password = os.getenv("POSTGRES_PASSWORD", "softpower")
    db = os.getenv("POSTGRES_DB", "softpower-db")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db}"

    engine = create_engine(connection_string)
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 1
                FROM langchain_pg_embedding
                WHERE cmetadata->>'doc_id' = :doc_id
                  AND collection_id = (
                      SELECT uuid FROM langchain_pg_collection WHERE name = :collection
                  )
                LIMIT 1
            """),
            {"doc_id": str(doc_id), "collection": collection_name},
        )
        return result.first() is not None

def load_parquet_file(file_path: str) -> pd.DataFrame:
    """
    Load a parquet file into a pandas DataFrame.

    Args:
        file_path: Path to parquet file

    Returns:
        DataFrame with embeddings
    """
    print(f"Loading parquet file: {file_path}")
    df = pd.read_parquet(file_path)
    print(f"Loaded {len(df)} rows with columns: {df.columns.tolist()}")
    return df

def load_parquet_from_s3(s3_key: str, api_url: Optional[str] = None) -> pd.DataFrame:
    """
    Download and load a parquet file from S3.

    Args:
        s3_key: S3 object key
        api_url: Optional API URL

    Returns:
        DataFrame with embeddings
    """
    client = _get_api_client(api_url)
    if client:
        try:
            print(f"Downloading parquet from S3 via API: {s3_key}")
            df = client.download_parquet_as_dataframe(bucket=bucket_name, key=s3_key)
            print(f"Loaded {len(df)} rows from S3 (via API)")
            return df
        except Exception as e:
            print(f"API client failed, falling back to direct S3: {e}")

    # Fallback to direct boto3 access
    import boto3
    import io

    s3_client = boto3.client('s3')
    print(f"Downloading parquet from S3 directly: {s3_key}")

    response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
    parquet_buffer = io.BytesIO(response['Body'].read())
    df = pd.read_parquet(parquet_buffer)
    print(f"Loaded {len(df)} rows from S3 (direct)")
    return df

def insert_embeddings_batch(df: pd.DataFrame, collection_name: str = "chunk_embeddings",
                            batch_size: int = 100, skip_existing: bool = True) -> Dict[str, int]:
    """
    Insert embeddings from DataFrame into LangChain PGVector table.

    Args:
        df: DataFrame with columns: doc_id, embedding, text, and metadata columns
        collection_name: LangChain collection name (default: chunk_embeddings)
        batch_size: Number of embeddings to insert per batch
        skip_existing: Skip embeddings that already exist in the database

    Returns:
        Dictionary with counts: {'inserted': N, 'skipped': M, 'errors': K}
    """
    counts = {'inserted': 0, 'skipped': 0, 'errors': 0}

    # Validate required columns
    required_cols = ['doc_id', 'embedding', 'text']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Process in batches
    total_rows = len(df)
    for batch_start in range(0, total_rows, batch_size):
        batch_end = min(batch_start + batch_size, total_rows)
        batch_df = df.iloc[batch_start:batch_end]

        batch_texts = []
        batch_metadatas = []
        batch_ids = []
        batch_embeddings = []

        for idx, row in batch_df.iterrows():
            doc_id = str(row['doc_id'])

            # Skip if already loaded and skip_existing is True
            if skip_existing and is_embedding_already_loaded(doc_id, collection_name):
                counts['skipped'] += 1
                continue

            try:
                # Parse embedding
                embedding = parse_embedding_string(row['embedding'])

                # Prepare metadata (include all available columns)
                metadata = {
                    'doc_id': doc_id,
                    'chunk_index': int(row.get('chunk_index', 0)),
                    'chunk_start_word': int(row.get('chunk_start_word', 0)),
                    'chunk_end_word': int(row.get('chunk_end_word', 0)),
                }

                # Add optional metadata fields
                optional_fields = [
                    'initiating_country', 'recipient_country', 'category', 'subcategory',
                    'event_name', 'location', 'title', 'source_name', 'source_geofocus',
                    'date', 'collection_name', 's3_key'
                ]
                for field in optional_fields:
                    if field in row and pd.notna(row[field]):
                        metadata[field] = str(row[field])

                # Get text content
                text = str(row['text'])

                batch_texts.append(text)
                batch_metadatas.append(metadata)
                batch_ids.append(doc_id)
                batch_embeddings.append(embedding.tolist())

            except Exception as e:
                print(f"Error processing row {idx} (doc_id={doc_id}): {e}")
                counts['errors'] += 1
                continue

        # Insert batch into vector store
        if batch_texts:
            try:
                # Use chunk_store.add_texts with pre-computed embeddings
                chunk_store.add_embeddings(
                    texts=batch_texts,
                    embeddings=batch_embeddings,
                    metadatas=batch_metadatas,
                    ids=batch_ids
                )
                counts['inserted'] += len(batch_texts)
                print(f"✅ Inserted batch {(batch_start//batch_size)+1}: {len(batch_texts)} embeddings")
            except Exception as e:
                print(f"❌ Error inserting batch {(batch_start//batch_size)+1}: {e}")
                counts['errors'] += len(batch_texts)

    return counts

def load_local_processed_tracker() -> Dict[str, Any]:
    """Load the local processed files tracker."""
    tracker_path = Path(LOCAL_TRACKER_FILE)
    if tracker_path.exists():
        with open(tracker_path, 'r') as f:
            return json.load(f)
    return {"processed_files": [], "last_updated": None}

def save_local_processed_tracker(tracker_data: Dict[str, Any]) -> None:
    """Save the local processed files tracker."""
    from datetime import datetime

    tracker_data["last_updated"] = datetime.utcnow().isoformat()
    tracker_path = Path(LOCAL_TRACKER_FILE)
    tracker_path.parent.mkdir(parents=True, exist_ok=True)

    with open(tracker_path, 'w') as f:
        json.dump(tracker_data, indent=2, fp=f)
    print(f"Saved local tracker: {len(tracker_data['processed_files'])} files")

def load_s3_processed_tracker(s3_prefix: str = S3_TRACKER_PREFIX) -> Dict[str, Any]:
    """Load the S3 processed files tracker."""
    from services.pipeline.embeddings.s3 import load_processed_files_tracker

    # Use the existing S3 tracker utilities
    tracker_key = f"{s3_prefix}processed_embeddings.json"

    client = _get_api_client()
    if client:
        try:
            response = client.download_json_file(bucket=bucket_name, key=tracker_key)
            return response['data']
        except Exception as e:
            if '404' in str(e) or 'NoSuchKey' in str(e):
                return {"processed_files": [], "last_updated": None}
            print(f"API client failed, falling back to direct S3: {e}")

    # Fallback to direct boto3
    import boto3
    from botocore.exceptions import ClientError

    s3_client = boto3.client('s3')
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=tracker_key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return {"processed_files": [], "last_updated": None}
        raise

def save_s3_processed_tracker(tracker_data: Dict[str, Any], s3_prefix: str = S3_TRACKER_PREFIX) -> None:
    """Save the S3 processed files tracker."""
    from datetime import datetime

    tracker_data["last_updated"] = datetime.utcnow().isoformat()
    tracker_key = f"{s3_prefix}processed_embeddings.json"

    client = _get_api_client()
    if client:
        try:
            client.upload_json_file(bucket=bucket_name, key=tracker_key, data=tracker_data)
            print(f"Saved S3 tracker: {len(tracker_data['processed_files'])} files")
            return
        except Exception as e:
            print(f"API client failed, falling back to direct S3: {e}")

    # Fallback to direct boto3
    import boto3

    s3_client = boto3.client('s3')
    s3_client.put_object(
        Bucket=bucket_name,
        Key=tracker_key,
        Body=json.dumps(tracker_data, indent=2),
        ContentType='application/json'
    )
    print(f"Saved S3 tracker: {len(tracker_data['processed_files'])} files")

def list_local_parquet_files(directory: str) -> List[str]:
    """List all parquet files in local directory."""
    dir_path = Path(directory)
    if not dir_path.exists():
        print(f"Directory not found: {directory}")
        return []

    parquet_files = list(dir_path.glob("*.parquet"))
    print(f"Found {len(parquet_files)} parquet files in {directory}")
    return [str(f.name) for f in parquet_files]

def list_s3_parquet_files(s3_prefix: str = S3_TRACKER_PREFIX) -> List[Dict[str, Any]]:
    """List all parquet files in S3 prefix."""
    client = _get_api_client()
    if client:
        try:
            response = client.list_parquet_files(bucket=bucket_name, prefix=s3_prefix)
            files = response.get('files', [])
            print(f"Found {len(files)} parquet files in s3://{bucket_name}/{s3_prefix} (via API)")
            return files
        except Exception as e:
            print(f"API client failed, falling back to direct S3: {e}")

    # Fallback to direct boto3
    import boto3

    s3_client = boto3.client('s3')
    parquet_files = []

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix)

        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    if key.endswith('.parquet'):
                        parquet_files.append({
                            'key': key,
                            'filename': key.split('/')[-1],
                            'size': obj['Size'],
                            'last_modified': obj['LastModified']
                        })

        print(f"Found {len(parquet_files)} parquet files in s3://{bucket_name}/{s3_prefix} (direct)")
        return parquet_files

    except Exception as e:
        print(f"Error listing S3 files: {e}")
        raise

def process_local_embeddings(directory: str = "data/processed_embeddings",
                            specific_files: Optional[List[str]] = None,
                            batch_size: int = 100,
                            skip_existing: bool = True) -> Dict[str, int]:
    """
    Process parquet embedding files from local directory.

    Args:
        directory: Local directory containing parquet files
        specific_files: Optional list of specific filenames to process
        batch_size: Batch size for inserting embeddings
        skip_existing: Skip embeddings already in database

    Returns:
        Dictionary with total counts
    """
    print(f"🚀 Processing embeddings from local directory: {directory}")

    # Load tracker
    tracker_data = load_local_processed_tracker()
    processed_files = set(tracker_data.get('processed_files', []))

    # Get files to process
    if specific_files:
        files_to_process = specific_files
        print(f"Processing {len(specific_files)} specific files")
    else:
        all_files = list_local_parquet_files(directory)
        files_to_process = [f for f in all_files if f not in processed_files]
        print(f"Processing {len(files_to_process)} unprocessed files")

    if not files_to_process:
        print("No files to process")
        return {'inserted': 0, 'skipped': 0, 'errors': 0}

    # Process each file
    total_counts = {'inserted': 0, 'skipped': 0, 'errors': 0}

    for filename in files_to_process:
        try:
            file_path = os.path.join(directory, filename)

            # Load parquet file
            df = load_parquet_file(file_path)

            # Insert embeddings
            counts = insert_embeddings_batch(df, batch_size=batch_size, skip_existing=skip_existing)

            # Update totals
            total_counts['inserted'] += counts['inserted']
            total_counts['skipped'] += counts['skipped']
            total_counts['errors'] += counts['errors']

            print(f"✅ Processed {filename}: {counts['inserted']} inserted, {counts['skipped']} skipped, {counts['errors']} errors")

            # Mark as processed (only if not processing specific files)
            if not specific_files and filename not in processed_files:
                processed_files.add(filename)
                tracker_data['processed_files'] = list(processed_files)
                save_local_processed_tracker(tracker_data)

        except Exception as e:
            print(f"❌ Error processing {filename}: {e}")
            total_counts['errors'] += 1
            continue

    print(f"\n📊 Local Processing Complete:")
    print(f"  - Inserted: {total_counts['inserted']}")
    print(f"  - Skipped: {total_counts['skipped']}")
    print(f"  - Errors: {total_counts['errors']}")

    return total_counts

def process_s3_embeddings(s3_prefix: str = S3_TRACKER_PREFIX,
                         specific_files: Optional[List[str]] = None,
                         batch_size: int = 100,
                         skip_existing: bool = True) -> Dict[str, int]:
    """
    Process parquet embedding files from S3 bucket.

    Args:
        s3_prefix: S3 prefix/folder for parquet files
        specific_files: Optional list of specific filenames to process
        batch_size: Batch size for inserting embeddings
        skip_existing: Skip embeddings already in database

    Returns:
        Dictionary with total counts
    """
    print(f"🚀 Processing embeddings from S3: s3://{bucket_name}/{s3_prefix}")

    # Load tracker
    tracker_data = load_s3_processed_tracker(s3_prefix)
    processed_files = set(tracker_data.get('processed_files', []))

    # Get files to process
    if specific_files:
        files_to_process = [{'key': f"{s3_prefix}{f}", 'filename': f} for f in specific_files]
        print(f"Processing {len(specific_files)} specific files")
    else:
        all_files = list_s3_parquet_files(s3_prefix)
        files_to_process = [f for f in all_files if f['filename'] not in processed_files]
        print(f"Processing {len(files_to_process)} unprocessed files")

    if not files_to_process:
        print("No files to process")
        return {'inserted': 0, 'skipped': 0, 'errors': 0}

    # Process each file
    total_counts = {'inserted': 0, 'skipped': 0, 'errors': 0}

    for file_info in files_to_process:
        filename = file_info['filename']
        s3_key = file_info['key']

        try:
            # Load parquet from S3
            df = load_parquet_from_s3(s3_key)

            # Insert embeddings
            counts = insert_embeddings_batch(df, batch_size=batch_size, skip_existing=skip_existing)

            # Update totals
            total_counts['inserted'] += counts['inserted']
            total_counts['skipped'] += counts['skipped']
            total_counts['errors'] += counts['errors']

            print(f"✅ Processed {filename}: {counts['inserted']} inserted, {counts['skipped']} skipped, {counts['errors']} errors")

            # Mark as processed (only if not processing specific files)
            if not specific_files and filename not in processed_files:
                processed_files.add(filename)
                tracker_data['processed_files'] = list(processed_files)
                save_s3_processed_tracker(tracker_data, s3_prefix)

        except Exception as e:
            print(f"❌ Error processing {filename}: {e}")
            total_counts['errors'] += 1
            continue

    print(f"\n📊 S3 Processing Complete:")
    print(f"  - Inserted: {total_counts['inserted']}")
    print(f"  - Skipped: {total_counts['skipped']}")
    print(f"  - Errors: {total_counts['errors']}")

    return total_counts

def show_local_status(directory: str = "data/processed_embeddings"):
    """Show status of local parquet files."""
    print(f"📊 Local Embedding Files Status")
    print("=" * 60)

    tracker_data = load_local_processed_tracker()
    processed_files = set(tracker_data.get('processed_files', []))
    all_files = list_local_parquet_files(directory)
    unprocessed_files = [f for f in all_files if f not in processed_files]

    print(f"Total parquet files: {len(all_files)}")
    print(f"Processed files: {len(processed_files)}")
    print(f"Unprocessed files: {len(unprocessed_files)}")

    if unprocessed_files:
        print("\n📋 Unprocessed files:")
        for filename in unprocessed_files[:10]:
            print(f"  - {filename}")
        if len(unprocessed_files) > 10:
            print(f"  ... and {len(unprocessed_files) - 10} more")

    if tracker_data.get('last_updated'):
        print(f"\n🕒 Last tracker update: {tracker_data['last_updated']}")

def show_s3_status(s3_prefix: str = S3_TRACKER_PREFIX):
    """Show status of S3 parquet files."""
    print(f"📊 S3 Embedding Files Status (s3://{bucket_name}/{s3_prefix})")
    print("=" * 60)

    tracker_data = load_s3_processed_tracker(s3_prefix)
    processed_files = set(tracker_data.get('processed_files', []))
    all_files = list_s3_parquet_files(s3_prefix)
    unprocessed_files = [f for f in all_files if f['filename'] not in processed_files]

    print(f"Total parquet files: {len(all_files)}")
    print(f"Processed files: {len(processed_files)}")
    print(f"Unprocessed files: {len(unprocessed_files)}")

    if unprocessed_files:
        print("\n📋 Unprocessed files:")
        for file_info in unprocessed_files[:10]:
            print(f"  - {file_info['filename']} ({file_info.get('size', 0)} bytes)")
        if len(unprocessed_files) > 10:
            print(f"  ... and {len(unprocessed_files) - 10} more")

    if tracker_data.get('last_updated'):
        print(f"\n🕒 Last tracker update: {tracker_data['last_updated']}")

def reprocess_local_files(filenames: List[str], directory: str = "data/processed_embeddings"):
    """Remove files from local processed list to allow reprocessing."""
    tracker_data = load_local_processed_tracker()
    processed_files = tracker_data['processed_files']

    removed_count = 0
    for filename in filenames:
        if filename in processed_files:
            processed_files.remove(filename)
            removed_count += 1
            print(f"Removed {filename} from processed list")

    if removed_count > 0:
        save_local_processed_tracker(tracker_data)
        print(f"Marked {removed_count} files for reprocessing")
    else:
        print("No files were marked for reprocessing")

def reprocess_s3_files(filenames: List[str], s3_prefix: str = S3_TRACKER_PREFIX):
    """Remove files from S3 processed list to allow reprocessing."""
    tracker_data = load_s3_processed_tracker(s3_prefix)
    processed_files = tracker_data['processed_files']

    removed_count = 0
    for filename in filenames:
        if filename in processed_files:
            processed_files.remove(filename)
            removed_count += 1
            print(f"Removed {filename} from processed list")

    if removed_count > 0:
        save_s3_processed_tracker(tracker_data, s3_prefix)
        print(f"Marked {removed_count} files for reprocessing")
    else:
        print("No files were marked for reprocessing")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load pre-computed embeddings from parquet files into LangChain PGVector")

    # Data source options
    parser.add_argument("--source", choices=["local", "s3"], default="local",
                       help="Data source: local directory or S3 bucket (default: local)")
    parser.add_argument("--directory", type=str, default="data/processed_embeddings",
                       help="Local directory containing parquet files (default: data/processed_embeddings)")
    parser.add_argument("--s3-prefix", type=str, default="embeddings/",
                       help="S3 prefix/folder for parquet files (default: embeddings/)")

    # Processing options
    parser.add_argument("--files", nargs="+", help="Specific files to process")
    parser.add_argument("--batch-size", type=int, default=100,
                       help="Batch size for inserting embeddings (default: 100)")
    parser.add_argument("--force", action="store_true",
                       help="Force reprocessing of embeddings (don't skip existing)")

    # Status and management options
    parser.add_argument("--status", action="store_true",
                       help="Show processing status")
    parser.add_argument("--reprocess", nargs="+",
                       help="Mark files for reprocessing (remove from processed list)")

    args = parser.parse_args()

    if args.source == "local":
        if args.status:
            show_local_status(args.directory)
        elif args.reprocess:
            reprocess_local_files(args.reprocess, args.directory)
            print("\n🚀 Now processing the reprocessed files...")
            process_local_embeddings(
                directory=args.directory,
                specific_files=args.reprocess,
                batch_size=args.batch_size,
                skip_existing=not args.force
            )
        else:
            process_local_embeddings(
                directory=args.directory,
                specific_files=args.files,
                batch_size=args.batch_size,
                skip_existing=not args.force
            )

    elif args.source == "s3":
        if args.status:
            show_s3_status(args.s3_prefix)
        elif args.reprocess:
            reprocess_s3_files(args.reprocess, args.s3_prefix)
            print("\n🚀 Now processing the reprocessed files...")
            process_s3_embeddings(
                s3_prefix=args.s3_prefix,
                specific_files=args.reprocess,
                batch_size=args.batch_size,
                skip_existing=not args.force
            )
        else:
            process_s3_embeddings(
                s3_prefix=args.s3_prefix,
                specific_files=args.files,
                batch_size=args.batch_size,
                skip_existing=not args.force
            )
