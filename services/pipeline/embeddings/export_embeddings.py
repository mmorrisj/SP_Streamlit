"""
Export Embeddings and Event Summaries to Parquet Files

This script exports all embeddings and event summaries to compressed parquet files
for fast backup and restoration. This is much faster than regenerating embeddings.

Usage:
    # Export everything to default location (./_data/exports/embeddings/)
    python services/pipeline/embeddings/export_embeddings.py

    # Export to specific directory
    python services/pipeline/embeddings/export_embeddings.py --output-dir /path/to/backup

    # Export only specific collections
    python services/pipeline/embeddings/export_embeddings.py --collections chunk_embeddings daily_event_embeddings

    # Include event summaries table
    python services/pipeline/embeddings/export_embeddings.py --include-event-summaries

    # Export to S3
    python services/pipeline/embeddings/export_embeddings.py --s3-bucket my-bucket --s3-prefix embeddings/backup/
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import json

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_engine, get_session
import boto3
from botocore.exceptions import ClientError


def get_available_collections():
    """Get list of collections with embeddings."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT c.name, c.uuid, COUNT(e.uuid) as embedding_count
            FROM langchain_pg_collection c
            LEFT JOIN langchain_pg_embedding e ON c.uuid = e.collection_id
            GROUP BY c.name, c.uuid
            HAVING COUNT(e.uuid) > 0
            ORDER BY c.name
        """))

        collections = []
        for row in result:
            collections.append({
                'name': row[0],
                'uuid': str(row[1]),
                'count': row[2]
            })
        return collections


def export_collection_to_parquet(collection_name: str, collection_uuid: str, output_dir: Path, batch_size: int = 10000):
    """
    Export a collection's embeddings to parquet file(s).

    Args:
        collection_name: Name of the collection
        collection_uuid: UUID of the collection
        output_dir: Directory to write parquet files
        batch_size: Number of embeddings per file (for large collections)
    """
    print(f"\nExporting collection: {collection_name}")
    print(f"  UUID: {collection_uuid}")

    engine = get_engine()

    # Get total count
    with engine.connect() as conn:
        total = conn.execute(text("""
            SELECT COUNT(*) FROM langchain_pg_embedding WHERE collection_id = :uuid
        """), {"uuid": collection_uuid}).scalar()

    print(f"  Total embeddings: {total:,}")

    if total == 0:
        print("  [SKIP] No embeddings to export")
        return []

    exported_files = []
    offset = 0
    file_num = 0

    while offset < total:
        # Fetch batch
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    uuid,
                    collection_id,
                    embedding::text,
                    document,
                    cmetadata,
                    custom_id
                FROM langchain_pg_embedding
                WHERE collection_id = :uuid
                ORDER BY uuid
                LIMIT :limit OFFSET :offset
            """), {"uuid": collection_uuid, "limit": batch_size, "offset": offset})

            rows = result.fetchall()

        if not rows:
            break

        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=['uuid', 'collection_id', 'embedding', 'document', 'cmetadata', 'custom_id'])

        # Convert UUIDs to strings
        df['uuid'] = df['uuid'].astype(str)
        df['collection_id'] = df['collection_id'].astype(str)

        # Convert cmetadata to JSON strings
        df['cmetadata'] = df['cmetadata'].apply(lambda x: json.dumps(x) if x else None)

        # Determine filename
        if total <= batch_size:
            filename = f"{collection_name}.parquet"
        else:
            filename = f"{collection_name}_part{file_num:04d}.parquet"

        filepath = output_dir / filename

        # Write parquet with compression
        df.to_parquet(
            filepath,
            compression='zstd',
            index=False,
            engine='pyarrow'
        )

        exported_files.append(filepath)
        file_size_mb = filepath.stat().st_size / (1024 * 1024)

        print(f"  [OK] Exported {len(rows):,} embeddings to {filename} ({file_size_mb:.1f} MB)")

        offset += batch_size
        file_num += 1

    return exported_files


def export_event_summaries_to_parquet(output_dir: Path):
    """Export event_summaries table to parquet file."""
    print("\nExporting event_summaries table...")

    with get_session() as session:
        # Use pandas read_sql for efficient export
        query = """
            SELECT
                id,
                period_type,
                period_start,
                period_end,
                event_name,
                initiating_country,
                first_observed_date,
                last_observed_date,
                status,
                period_summary_id,
                created_at,
                updated_at,
                created_by,
                is_deleted,
                deleted_at,
                category_count,
                subcategory_count,
                recipient_count,
                source_count,
                total_documents_across_categories,
                total_documents_across_subcategories,
                total_documents_across_recipients,
                total_documents_across_sources,
                count_by_category,
                count_by_subcategory,
                count_by_recipient,
                count_by_source,
                narrative_summary,
                material_score,
                material_justification
            FROM event_summaries
            ORDER BY period_start DESC, initiating_country
        """

        df = pd.read_sql(query, session.bind)

        # Convert UUIDs to strings
        df['id'] = df['id'].astype(str)
        df['period_summary_id'] = df['period_summary_id'].astype(str)

        # Convert JSONB columns to JSON strings
        jsonb_cols = ['count_by_category', 'count_by_subcategory', 'count_by_recipient', 'count_by_source', 'narrative_summary']
        for col in jsonb_cols:
            df[col] = df[col].apply(lambda x: json.dumps(x) if pd.notna(x) else None)

        filepath = output_dir / "event_summaries.parquet"
        df.to_parquet(
            filepath,
            compression='zstd',
            index=False,
            engine='pyarrow'
        )

        file_size_mb = filepath.stat().st_size / (1024 * 1024)
        print(f"  [OK] Exported {len(df):,} event summaries to event_summaries.parquet ({file_size_mb:.1f} MB)")

        return filepath


def export_event_source_links_to_parquet(output_dir: Path):
    """Export event_source_links table to parquet file."""
    print("\nExporting event_source_links table...")

    with get_session() as session:
        # Check if table exists
        from sqlalchemy import inspect
        inspector = inspect(session.bind)
        if 'event_source_links' not in inspector.get_table_names():
            print("  [SKIP] event_source_links table does not exist")
            return None

        query = """
            SELECT
                id,
                event_summary_id,
                doc_id,
                contribution_weight,
                linked_at
            FROM event_source_links
            ORDER BY event_summary_id, doc_id
        """

        df = pd.read_sql(query, session.bind)

        # Convert UUIDs to strings
        df['id'] = df['id'].astype(str)
        df['event_summary_id'] = df['event_summary_id'].astype(str)

        filepath = output_dir / "event_source_links.parquet"
        df.to_parquet(
            filepath,
            compression='zstd',
            index=False,
            engine='pyarrow'
        )

        file_size_mb = filepath.stat().st_size / (1024 * 1024)
        print(f"  [OK] Exported {len(df):,} source links to event_source_links.parquet ({file_size_mb:.1f} MB)")

        return filepath


def upload_to_s3(local_files: list, bucket: str, prefix: str):
    """Upload exported files to S3."""
    print(f"\nUploading to S3: s3://{bucket}/{prefix}")

    s3 = boto3.client('s3')
    uploaded = []

    for local_file in local_files:
        s3_key = f"{prefix}{local_file.name}"

        try:
            s3.upload_file(
                str(local_file),
                bucket,
                s3_key
            )
            print(f"  [OK] Uploaded {local_file.name} to s3://{bucket}/{s3_key}")
            uploaded.append(s3_key)
        except ClientError as e:
            print(f"  [ERROR] Failed to upload {local_file.name}: {e}")

    return uploaded


def create_manifest(output_dir: Path, exported_files: list, metadata: dict):
    """Create a manifest file with export metadata."""
    manifest = {
        'export_timestamp': datetime.now().isoformat(),
        'total_files': len(exported_files),
        'files': [str(f.name) for f in exported_files],
        'metadata': metadata
    }

    manifest_path = output_dir / 'export_manifest.json'
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"\n[OK] Created manifest: {manifest_path}")
    return manifest_path


def main():
    parser = argparse.ArgumentParser(
        description='Export embeddings and event summaries to parquet files for fast backup/restore',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        default='./_data/exports/embeddings',
        help='Directory to store exported parquet files (default: ./_data/exports/embeddings)'
    )
    parser.add_argument(
        '--collections',
        nargs='+',
        help='Specific collections to export (default: all collections with embeddings)'
    )
    parser.add_argument(
        '--include-event-summaries',
        action='store_true',
        help='Also export the event_summaries table'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10000,
        help='Number of embeddings per parquet file for large collections (default: 10000)'
    )
    parser.add_argument(
        '--s3-bucket',
        type=str,
        help='Upload to S3 bucket (optional)'
    )
    parser.add_argument(
        '--s3-prefix',
        type=str,
        default='embeddings/backup/',
        help='S3 prefix for uploaded files (default: embeddings/backup/)'
    )

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("="*100)
    print("EMBEDDING & EVENT SUMMARY EXPORT")
    print("="*100)
    print(f"Output directory: {output_dir.absolute()}")
    print(f"Batch size: {args.batch_size:,} embeddings per file")

    # Get available collections
    available_collections = get_available_collections()

    if not available_collections:
        print("\n[WARNING] No collections with embeddings found!")
        return

    print(f"\nAvailable collections:")
    for col in available_collections:
        print(f"  - {col['name']}: {col['count']:,} embeddings")

    # Determine which collections to export
    if args.collections:
        collections_to_export = [c for c in available_collections if c['name'] in args.collections]
        if not collections_to_export:
            print(f"\n[ERROR] None of the specified collections found: {args.collections}")
            return
    else:
        collections_to_export = available_collections

    print(f"\nExporting {len(collections_to_export)} collection(s)...")

    # Export collections
    all_exported_files = []
    total_embeddings = 0

    for collection in collections_to_export:
        files = export_collection_to_parquet(
            collection['name'],
            collection['uuid'],
            output_dir,
            args.batch_size
        )
        all_exported_files.extend(files)
        total_embeddings += collection['count']

    # Export event summaries and source links if requested
    if args.include_event_summaries:
        summary_file = export_event_summaries_to_parquet(output_dir)
        all_exported_files.append(summary_file)

        # Also export event source links
        source_links_file = export_event_source_links_to_parquet(output_dir)
        if source_links_file:
            all_exported_files.append(source_links_file)

    # Create manifest
    metadata = {
        'total_embeddings': total_embeddings,
        'collections': [c['name'] for c in collections_to_export],
        'include_event_summaries': args.include_event_summaries
    }
    manifest_file = create_manifest(output_dir, all_exported_files, metadata)
    all_exported_files.append(manifest_file)

    # Calculate total size
    total_size_mb = sum(f.stat().st_size for f in all_exported_files) / (1024 * 1024)

    print("\n" + "="*100)
    print("EXPORT COMPLETE")
    print("="*100)
    print(f"Total files: {len(all_exported_files)}")
    print(f"Total size: {total_size_mb:.1f} MB")
    print(f"Total embeddings: {total_embeddings:,}")
    print(f"Output directory: {output_dir.absolute()}")

    # Upload to S3 if requested
    if args.s3_bucket:
        uploaded_keys = upload_to_s3(all_exported_files, args.s3_bucket, args.s3_prefix)
        print(f"\n[OK] Uploaded {len(uploaded_keys)} files to S3")

    print("\nTo restore these embeddings, use:")
    print(f"  python services/pipeline/embeddings/import_embeddings.py --input-dir {output_dir}")
    print("="*100)


if __name__ == '__main__':
    main()
