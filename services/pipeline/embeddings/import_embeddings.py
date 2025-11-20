"""
Import Embeddings and Event Summaries from Parquet Files

This script imports embeddings and event summaries from parquet files
created by export_embeddings.py. Much faster than regenerating embeddings.

Usage:
    # Import from local directory
    python services/pipeline/embeddings/import_embeddings.py --input-dir ./embedding_exports

    # Import from S3
    python services/pipeline/embeddings/import_embeddings.py --s3-bucket my-bucket --s3-prefix embeddings/backup/

    # Dry run (don't actually import)
    python services/pipeline/embeddings/import_embeddings.py --input-dir ./embedding_exports --dry-run

    # Skip event summaries (import only embeddings)
    python services/pipeline/embeddings/import_embeddings.py --input-dir ./embedding_exports --skip-event-summaries

    # Clear existing data before import
    python services/pipeline/embeddings/import_embeddings.py --input-dir ./embedding_exports --clear-existing
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import json
from typing import List, Dict

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_engine, get_session
import boto3
from botocore.exceptions import ClientError


def download_from_s3(bucket: str, prefix: str, local_dir: Path) -> List[Path]:
    """Download parquet files from S3 to local directory."""
    print(f"Downloading from S3: s3://{bucket}/{prefix}")

    s3 = boto3.client('s3')
    local_dir.mkdir(parents=True, exist_ok=True)

    # List all files with prefix
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)

    if 'Contents' not in response:
        print(f"[ERROR] No files found at s3://{bucket}/{prefix}")
        return []

    downloaded_files = []

    for obj in response['Contents']:
        key = obj['Key']
        filename = Path(key).name

        if not filename.endswith('.parquet') and not filename.endswith('.json'):
            continue

        local_path = local_dir / filename

        try:
            s3.download_file(bucket, key, str(local_path))
            print(f"  [OK] Downloaded {filename}")
            downloaded_files.append(local_path)
        except ClientError as e:
            print(f"  [ERROR] Failed to download {filename}: {e}")

    return downloaded_files


def load_manifest(input_dir: Path) -> Dict:
    """Load the export manifest file."""
    manifest_path = input_dir / 'export_manifest.json'

    if not manifest_path.exists():
        print(f"[WARNING] No manifest file found at {manifest_path}")
        return None

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    print("\nManifest Information:")
    print("="*100)
    print(f"  Export timestamp: {manifest.get('export_timestamp', 'Unknown')}")
    print(f"  Total files: {manifest.get('total_files', 0)}")
    print(f"  Total embeddings: {manifest.get('metadata', {}).get('total_embeddings', 0):,}")
    print(f"  Collections: {', '.join(manifest.get('metadata', {}).get('collections', []))}")
    print("="*100)

    return manifest


def ensure_collection_exists(collection_name: str) -> str:
    """Ensure a collection exists, create if not. Returns collection UUID."""
    engine = get_engine()

    with engine.connect() as conn:
        # Check if collection exists
        result = conn.execute(text("""
            SELECT uuid FROM langchain_pg_collection WHERE name = :name
        """), {"name": collection_name})

        row = result.fetchone()

        if row:
            return str(row[0])

        # Create collection
        result = conn.execute(text("""
            INSERT INTO langchain_pg_collection (name, cmetadata)
            VALUES (:name, :metadata)
            RETURNING uuid
        """), {"name": collection_name, "metadata": json.dumps({})})

        conn.commit()
        uuid = result.fetchone()[0]
        print(f"  [CREATED] Collection '{collection_name}' with UUID {uuid}")
        return str(uuid)


def clear_collection(collection_name: str):
    """Delete all embeddings in a collection."""
    print(f"  [CLEAR] Deleting existing embeddings in {collection_name}...")

    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM langchain_pg_embedding
            WHERE collection_id = (
                SELECT uuid FROM langchain_pg_collection WHERE name = :name
            )
        """), {"name": collection_name})

        conn.commit()
        print(f"  [OK] Deleted {result.rowcount:,} existing embeddings")


def import_parquet_to_collection(parquet_file: Path, collection_name: str, dry_run: bool = False):
    """
    Import embeddings from parquet file into a collection.

    Args:
        parquet_file: Path to parquet file
        collection_name: Name of the collection
        dry_run: If True, don't actually insert data
    """
    print(f"\nImporting {parquet_file.name} into collection '{collection_name}'")

    # Read parquet file
    df = pd.read_parquet(parquet_file)
    print(f"  Loaded {len(df):,} embeddings from file")

    if dry_run:
        print(f"  [DRY RUN] Would import {len(df):,} embeddings")
        return

    # Ensure collection exists
    collection_uuid = ensure_collection_exists(collection_name)

    # Convert cmetadata from JSON strings back to dicts
    df['cmetadata'] = df['cmetadata'].apply(lambda x: json.loads(x) if pd.notna(x) and x else {})

    # Prepare data for bulk insert
    engine = get_engine()

    # Insert in batches
    batch_size = 1000
    total_inserted = 0

    with engine.connect() as conn:
        for start_idx in range(0, len(df), batch_size):
            batch = df.iloc[start_idx:start_idx + batch_size]

            # Build insert statement with ON CONFLICT DO NOTHING for idempotency
            for _, row in batch.iterrows():
                conn.execute(text("""
                    INSERT INTO langchain_pg_embedding
                    (uuid, collection_id, embedding, document, cmetadata, custom_id)
                    VALUES (
                        :uuid::uuid,
                        :collection_id::uuid,
                        :embedding::vector,
                        :document,
                        :cmetadata::json,
                        :custom_id
                    )
                    ON CONFLICT (uuid) DO NOTHING
                """), {
                    "uuid": row['uuid'],
                    "collection_id": collection_uuid,
                    "embedding": row['embedding'],
                    "document": row['document'],
                    "cmetadata": json.dumps(row['cmetadata']),
                    "custom_id": row['custom_id']
                })

            conn.commit()
            total_inserted += len(batch)
            print(f"  [OK] Inserted batch {start_idx//batch_size + 1}: {len(batch)} embeddings (total: {total_inserted:,})")

    print(f"  [COMPLETE] Imported {total_inserted:,} embeddings into '{collection_name}'")


def import_event_summaries(parquet_file: Path, dry_run: bool = False, clear_existing: bool = False):
    """Import event_summaries table from parquet file."""
    print(f"\nImporting event_summaries from {parquet_file.name}")

    # Read parquet file
    df = pd.read_parquet(parquet_file)
    print(f"  Loaded {len(df):,} event summaries from file")

    if dry_run:
        print(f"  [DRY RUN] Would import {len(df):,} event summaries")
        return

    # Clear existing if requested
    if clear_existing:
        with get_session() as session:
            result = session.execute(text("DELETE FROM event_summaries"))
            session.commit()
            print(f"  [CLEAR] Deleted {result.rowcount:,} existing event summaries")

    # Convert JSON strings back to JSONB
    jsonb_cols = ['count_by_category', 'count_by_subcategory', 'count_by_recipient', 'count_by_source', 'narrative_summary']
    for col in jsonb_cols:
        df[col] = df[col].apply(lambda x: json.loads(x) if pd.notna(x) and x else {})

    # Use pandas to_sql for efficient import
    engine = get_engine()

    # Insert in batches with ON CONFLICT handling
    batch_size = 500
    total_inserted = 0

    with engine.connect() as conn:
        for start_idx in range(0, len(df), batch_size):
            batch = df.iloc[start_idx:start_idx + batch_size]

            for _, row in batch.iterrows():
                conn.execute(text("""
                    INSERT INTO event_summaries (
                        id, period_type, period_start, period_end, event_name,
                        initiating_country, first_observed_date, last_observed_date,
                        status, period_summary_id, created_at, updated_at, created_by,
                        is_deleted, deleted_at, category_count, subcategory_count,
                        recipient_count, source_count, total_documents_across_categories,
                        total_documents_across_subcategories, total_documents_across_recipients,
                        total_documents_across_sources, count_by_category, count_by_subcategory,
                        count_by_recipient, count_by_source, narrative_summary,
                        material_score, material_justification
                    ) VALUES (
                        :id::uuid, :period_type, :period_start, :period_end, :event_name,
                        :initiating_country, :first_observed_date, :last_observed_date,
                        :status, :period_summary_id::uuid, :created_at, :updated_at, :created_by,
                        :is_deleted, :deleted_at, :category_count, :subcategory_count,
                        :recipient_count, :source_count, :total_documents_across_categories,
                        :total_documents_across_subcategories, :total_documents_across_recipients,
                        :total_documents_across_sources, :count_by_category::jsonb,
                        :count_by_subcategory::jsonb, :count_by_recipient::jsonb,
                        :count_by_source::jsonb, :narrative_summary::jsonb,
                        :material_score, :material_justification
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        period_type = EXCLUDED.period_type,
                        event_name = EXCLUDED.event_name,
                        narrative_summary = EXCLUDED.narrative_summary,
                        updated_at = EXCLUDED.updated_at
                """), row.to_dict())

            conn.commit()
            total_inserted += len(batch)
            print(f"  [OK] Inserted batch {start_idx//batch_size + 1}: {len(batch)} summaries (total: {total_inserted:,})")

    print(f"  [COMPLETE] Imported {total_inserted:,} event summaries")


def import_event_source_links(parquet_file: Path, dry_run: bool = False, clear_existing: bool = False):
    """Import event_source_links table from parquet file."""
    print(f"\nImporting event_source_links from {parquet_file.name}")

    # Read parquet file
    df = pd.read_parquet(parquet_file)
    print(f"  Loaded {len(df):,} source links from file")

    if dry_run:
        print(f"  [DRY RUN] Would import {len(df):,} source links")
        return

    # Clear existing if requested
    if clear_existing:
        with get_session() as session:
            result = session.execute(text("DELETE FROM event_source_links"))
            session.commit()
            print(f"  [CLEAR] Deleted {result.rowcount:,} existing source links")

    # Use pandas to_sql for efficient import
    engine = get_engine()

    # Insert in batches
    batch_size = 1000
    total_inserted = 0

    with engine.connect() as conn:
        for start_idx in range(0, len(df), batch_size):
            batch = df.iloc[start_idx:start_idx + batch_size]

            for _, row in batch.iterrows():
                conn.execute(text("""
                    INSERT INTO event_source_links (
                        id, event_summary_id, doc_id, contribution_weight, linked_at
                    ) VALUES (
                        :id::uuid, :event_summary_id::uuid, :doc_id,
                        :contribution_weight, :linked_at
                    )
                    ON CONFLICT (id) DO NOTHING
                """), row.to_dict())

            conn.commit()
            total_inserted += len(batch)
            print(f"  [OK] Inserted batch {start_idx//batch_size + 1}: {len(batch)} links (total: {total_inserted:,})")

    print(f"  [COMPLETE] Imported {total_inserted:,} event source links")


def main():
    parser = argparse.ArgumentParser(
        description='Import embeddings and event summaries from parquet files',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--input-dir',
        type=str,
        help='Directory containing exported parquet files'
    )
    parser.add_argument(
        '--s3-bucket',
        type=str,
        help='Download from S3 bucket (alternative to --input-dir)'
    )
    parser.add_argument(
        '--s3-prefix',
        type=str,
        default='embeddings/backup/',
        help='S3 prefix for files (default: embeddings/backup/)'
    )
    parser.add_argument(
        '--skip-event-summaries',
        action='store_true',
        help='Skip importing event_summaries table'
    )
    parser.add_argument(
        '--clear-existing',
        action='store_true',
        help='Clear existing data before import (DESTRUCTIVE!)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test import without actually inserting data'
    )

    args = parser.parse_args()

    if not args.input_dir and not args.s3_bucket:
        parser.error("Must specify either --input-dir or --s3-bucket")

    print("="*100)
    print("EMBEDDING & EVENT SUMMARY IMPORT")
    print("="*100)

    # Download from S3 if specified
    if args.s3_bucket:
        temp_dir = Path('./temp_import')
        input_dir = temp_dir
        download_from_s3(args.s3_bucket, args.s3_prefix, temp_dir)
    else:
        input_dir = Path(args.input_dir)

    if not input_dir.exists():
        print(f"[ERROR] Input directory does not exist: {input_dir}")
        return

    # Load manifest
    manifest = load_manifest(input_dir)

    # Find all parquet files
    parquet_files = list(input_dir.glob("*.parquet"))

    if not parquet_files:
        print(f"[ERROR] No parquet files found in {input_dir}")
        return

    print(f"\nFound {len(parquet_files)} parquet file(s)")

    # Separate event_summaries and source_links from embedding files
    event_summary_files = [f for f in parquet_files if f.name == 'event_summaries.parquet']
    source_link_files = [f for f in parquet_files if f.name == 'event_source_links.parquet']
    embedding_files = [f for f in parquet_files if 'event_summaries' not in f.name and 'event_source_links' not in f.name]

    print(f"  Embedding files: {len(embedding_files)}")
    print(f"  Event summary files: {len(event_summary_files)}")
    print(f"  Source link files: {len(source_link_files)}")

    if args.dry_run:
        print("\n[DRY RUN MODE] - No data will be modified")

    # Import embeddings
    for parquet_file in embedding_files:
        # Extract collection name from filename
        collection_name = parquet_file.stem.split('_part')[0]  # Handle partitioned files

        if args.clear_existing and not args.dry_run:
            clear_collection(collection_name)

        import_parquet_to_collection(parquet_file, collection_name, args.dry_run)

    # Import event summaries
    if not args.skip_event_summaries and event_summary_files:
        for parquet_file in event_summary_files:
            import_event_summaries(parquet_file, args.dry_run, args.clear_existing)

    # Import event source links
    if not args.skip_event_summaries and source_link_files:
        for parquet_file in source_link_files:
            import_event_source_links(parquet_file, args.dry_run, args.clear_existing)

    print("\n" + "="*100)
    print("IMPORT COMPLETE")
    print("="*100)

    if args.dry_run:
        print("\n[DRY RUN] No data was actually imported")
        print("Remove --dry-run flag to perform actual import")

    # Clean up temp files if downloaded from S3
    if args.s3_bucket:
        import shutil
        shutil.rmtree(temp_dir)
        print(f"\n[OK] Cleaned up temporary files from {temp_dir}")


if __name__ == '__main__':
    main()
