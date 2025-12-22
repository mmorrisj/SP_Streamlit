"""
Import Event Tables from Parquet Files

Imports event-related tables from parquet files created by export_event_tables.py:
- event_clusters (raw daily clusters from DBSCAN)
- daily_event_mentions (event-to-document links)
- event_summaries (period summaries with narratives)

Usage:
    # Import from local directory
    python services/pipeline/events/import_event_tables.py --input-dir ./event_exports

    # Import from S3
    python services/pipeline/events/import_event_tables.py --s3-bucket my-bucket --s3-prefix events/backup/

    # Dry run (don't actually import)
    python services/pipeline/events/import_event_tables.py --input-dir ./event_exports --dry-run

    # Import specific tables only
    python services/pipeline/events/import_event_tables.py --input-dir ./event_exports --tables event_clusters

    # Clear existing data before import
    python services/pipeline/events/import_event_tables.py --input-dir ./event_exports --clear-existing
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import json
from typing import List, Optional
import uuid

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_engine, get_session

try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


def safe_value(val, default=None):
    """Return value if not NaN/None, otherwise return default."""
    if val is None:
        return default
    if isinstance(val, float) and np.isnan(val):
        return default
    if pd.isna(val):
        return default
    return val


def parse_json_field(val):
    """Parse JSON string field back to Python object."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None
    return val


def convert_to_json_serializable(obj):
    """Recursively convert numpy arrays and other non-JSON-serializable types to native Python types."""
    if obj is None:
        return None
    if isinstance(obj, np.ndarray):
        return [convert_to_json_serializable(item) for item in obj.tolist()]
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: convert_to_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_to_json_serializable(item) for item in obj]
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def prepare_jsonb_field(val):
    """Prepare a field for JSONB insertion - handles numpy arrays and converts to JSON string.

    IMPORTANT: This function MUST return a JSON string (or None), never a Python object,
    because PostgreSQL JSONB expects a string to be cast.
    """
    # Handle null/NaN values
    if val is None:
        return None
    try:
        if isinstance(val, float) and np.isnan(val):
            return None
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        # pd.isna() can fail on certain types like dicts
        pass

    # If it's already a string, try to parse and re-serialize to ensure validity
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            result = json.dumps(convert_to_json_serializable(parsed))
            return result
        except json.JSONDecodeError:
            return None

    # Convert to JSON-serializable format and serialize
    converted = convert_to_json_serializable(val)
    if converted is None:
        return None

    # Always return a JSON string, not a Python object
    result = json.dumps(converted)
    return result


def prepare_text_array_field(val):
    """Prepare a field for PostgreSQL text[] array insertion.

    Converts JSON arrays or Python lists to PostgreSQL array format.
    """
    if val is None or (isinstance(val, float) and np.isnan(val)) or pd.isna(val):
        return None

    # Parse JSON string if needed
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except json.JSONDecodeError:
            return None

    # Convert numpy array to list
    if isinstance(val, np.ndarray):
        val = val.tolist()

    # Must be a list at this point
    if not isinstance(val, list):
        return None

    # Return as Python list - psycopg2 will convert to PostgreSQL array
    return [str(item) for item in val]


def download_from_s3(bucket: str, prefix: str, local_dir: Path) -> List[Path]:
    """Download parquet files from S3 to local directory."""
    if not BOTO3_AVAILABLE:
        print("[ERROR] boto3 not installed. Cannot download from S3.")
        return []

    print(f"\nDownloading from S3: s3://{bucket}/{prefix}")
    local_dir.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client('s3')
    downloaded_files = []

    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)

        if 'Contents' not in response:
            print(f"[WARNING] No files found at s3://{bucket}/{prefix}")
            return []

        parquet_files = [obj for obj in response['Contents'] if obj['Key'].endswith('.parquet')]

        print(f"Found {len(parquet_files)} parquet files to download")

        for obj in parquet_files:
            key = obj['Key']
            filename = Path(key).name
            local_path = local_dir / filename

            try:
                s3.download_file(bucket, key, str(local_path))
                print(f"  [OK] Downloaded {filename}")
                downloaded_files.append(local_path)
            except Exception as e:
                print(f"  [ERROR] Failed to download {filename}: {e}")

    except Exception as e:
        print(f"[ERROR] Failed to list S3 objects: {e}")
        return []

    return downloaded_files


def clear_table(table_name: str, engine):
    """Clear all data from a table."""
    print(f"\n[WARNING] Clearing all data from {table_name}...")

    with engine.connect() as conn:
        try:
            result = conn.execute(text(f"DELETE FROM {table_name}"))
            conn.commit()
            print(f"  [OK] Deleted {result.rowcount} rows from {table_name}")
        except Exception as e:
            print(f"  [ERROR] Failed to clear {table_name}: {e}")
            conn.rollback()


def import_event_clusters(input_files: List[Path], dry_run: bool = False):
    """Import event_clusters table."""
    print("\n" + "="*80)
    print("IMPORTING EVENT_CLUSTERS")
    print("="*80)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")

    total_rows = 0
    inserted_rows = 0
    error_rows = 0

    engine = get_engine()

    # Filter for event_clusters files
    cluster_files = [f for f in input_files if 'event_clusters' in f.name]

    if not cluster_files:
        print("  [SKIP] No event_clusters files found")
        return

    for filepath in cluster_files:
        print(f"\nProcessing {filepath.name}...")

        try:
            df = pd.read_parquet(filepath)
            print(f"  Loaded {len(df):,} clusters")
        except Exception as e:
            print(f"  [ERROR] Failed to read file: {e}")
            continue

        total_rows += len(df)

        if dry_run:
            print("  [DRY RUN] Would import this batch")
            continue

        # Process in batches
        batch_size = 500

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]

            print(f"  Processing batch {i//batch_size + 1} ({len(batch)} clusters)...", end=" ")

            with get_session() as session:
                batch_inserted = 0
                batch_errors = 0

                for _, row in batch.iterrows():
                    try:
                        # Prepare array fields (text[]) and JSONB fields separately
                        event_names = prepare_text_array_field(row.get('event_names'))
                        doc_ids = prepare_text_array_field(row.get('doc_ids'))
                        refined_clusters = prepare_jsonb_field(row.get('refined_clusters'))

                        # Use savepoint so one failed row doesn't abort the whole batch
                        with session.begin_nested():
                            # Insert - event_names/doc_ids are text[], refined_clusters is jsonb
                            session.execute(
                                text("""
                                    INSERT INTO event_clusters (
                                        id, initiating_country, cluster_date, batch_number, cluster_id,
                                        event_names, doc_ids, cluster_size, is_noise, representative_name,
                                        processed, llm_deconflicted, created_at, refined_clusters
                                    ) VALUES (
                                        :id, :initiating_country, :cluster_date, :batch_number, :cluster_id,
                                        :event_names, :doc_ids, :cluster_size, :is_noise, :representative_name,
                                        :processed, :llm_deconflicted, :created_at, CAST(:refined_clusters AS jsonb)
                                    )
                                    ON CONFLICT (id) DO NOTHING
                                """),
                                {
                                    'id': str(row['id']),
                                    'initiating_country': safe_value(row.get('initiating_country')),
                                    'cluster_date': pd.to_datetime(row['cluster_date']).date() if safe_value(row.get('cluster_date')) else None,
                                    'batch_number': int(row['batch_number']) if safe_value(row.get('batch_number')) else 0,
                                    'cluster_id': int(row['cluster_id']) if safe_value(row.get('cluster_id')) else 0,
                                    'event_names': event_names,
                                    'doc_ids': doc_ids,
                                    'cluster_size': int(row['cluster_size']) if safe_value(row.get('cluster_size')) else 0,
                                    'is_noise': bool(row['is_noise']) if safe_value(row.get('is_noise')) is not None else False,
                                    'representative_name': safe_value(row.get('representative_name')),
                                    'processed': bool(row['processed']) if safe_value(row.get('processed')) is not None else False,
                                    'llm_deconflicted': bool(row['llm_deconflicted']) if safe_value(row.get('llm_deconflicted')) is not None else False,
                                    'created_at': pd.to_datetime(row['created_at']) if safe_value(row.get('created_at')) else datetime.now(),
                                    'refined_clusters': refined_clusters
                                }
                            )
                        batch_inserted += 1

                    except Exception as e:
                        print(f"\n  [ERROR] Row failed: {e}")
                        batch_errors += 1
                        continue

                try:
                    session.commit()
                    inserted_rows += batch_inserted
                    error_rows += batch_errors
                    print(f"[OK] inserted={batch_inserted}, errors={batch_errors}")
                except Exception as e:
                    print(f"[ERROR] Batch commit failed: {e}")
                    session.rollback()
                    error_rows += len(batch)

    print(f"\n{'='*80}")
    print(f"Total clusters: {total_rows:,}")
    print(f"Inserted: {inserted_rows:,}")
    print(f"Errors: {error_rows:,}")


def import_daily_event_mentions(input_files: List[Path], dry_run: bool = False):
    """Import daily_event_mentions table."""
    print("\n" + "="*80)
    print("IMPORTING DAILY_EVENT_MENTIONS")
    print("="*80)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")

    total_rows = 0
    inserted_rows = 0
    error_rows = 0

    engine = get_engine()

    # Filter for daily_event_mentions files
    mention_files = [f for f in input_files if 'daily_event_mentions' in f.name]

    if not mention_files:
        print("  [SKIP] No daily_event_mentions files found")
        return

    for filepath in mention_files:
        print(f"\nProcessing {filepath.name}...")

        try:
            df = pd.read_parquet(filepath)
            print(f"  Loaded {len(df):,} mentions")
        except Exception as e:
            print(f"  [ERROR] Failed to read file: {e}")
            continue

        total_rows += len(df)

        if dry_run:
            print("  [DRY RUN] Would import this batch")
            continue

        # Process in batches
        batch_size = 500

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]

            print(f"  Processing batch {i//batch_size + 1} ({len(batch)} mentions)...", end=" ")

            with get_session() as session:
                batch_inserted = 0
                batch_errors = 0

                for _, row in batch.iterrows():
                    try:
                        # Prepare text[] array fields (source_names and doc_ids are PostgreSQL text arrays)
                        source_names = prepare_text_array_field(row.get('source_names'))
                        doc_ids = prepare_text_array_field(row.get('doc_ids'))

                        # Provide defaults for NOT NULL columns
                        # source_names is NOT NULL in the schema, default to empty array
                        if source_names is None:
                            source_names = []
                        # source_diversity_score has default=0.0 in schema
                        source_diversity_score = float(row['source_diversity_score']) if safe_value(row.get('source_diversity_score')) else 0.0

                        # Use savepoint so one failed row doesn't abort the whole batch
                        with session.begin_nested():
                            session.execute(
                                text("""
                                    INSERT INTO daily_event_mentions (
                                        id, canonical_event_id, initiating_country, mention_date,
                                        article_count, consolidated_headline, daily_summary,
                                        source_names, source_diversity_score, mention_context,
                                        news_intensity, doc_ids
                                    ) VALUES (
                                        :id, :canonical_event_id, :initiating_country, :mention_date,
                                        :article_count, :consolidated_headline, :daily_summary,
                                        :source_names, :source_diversity_score, :mention_context,
                                        :news_intensity, :doc_ids
                                    )
                                    ON CONFLICT (id) DO NOTHING
                                """),
                                {
                                    'id': str(row['id']),
                                    'canonical_event_id': str(row['canonical_event_id']),
                                    'initiating_country': safe_value(row.get('initiating_country')),
                                    'mention_date': pd.to_datetime(row['mention_date']).date() if safe_value(row.get('mention_date')) else None,
                                    'article_count': int(row['article_count']) if safe_value(row.get('article_count')) else 0,
                                    'consolidated_headline': safe_value(row.get('consolidated_headline')),
                                    'daily_summary': safe_value(row.get('daily_summary')),
                                    'source_names': source_names,
                                    'source_diversity_score': source_diversity_score,
                                    'mention_context': safe_value(row.get('mention_context')),
                                    'news_intensity': safe_value(row.get('news_intensity')),
                                    'doc_ids': doc_ids
                                }
                            )
                        batch_inserted += 1

                    except Exception as e:
                        print(f"\n  [ERROR] Row failed: {e}")
                        batch_errors += 1
                        continue

                try:
                    session.commit()
                    inserted_rows += batch_inserted
                    error_rows += batch_errors
                    print(f"[OK] inserted={batch_inserted}, errors={batch_errors}")
                except Exception as e:
                    print(f"[ERROR] Batch commit failed: {e}")
                    session.rollback()
                    error_rows += len(batch)

    print(f"\n{'='*80}")
    print(f"Total mentions: {total_rows:,}")
    print(f"Inserted: {inserted_rows:,}")
    print(f"Errors: {error_rows:,}")


def import_event_summaries(input_files: List[Path], dry_run: bool = False):
    """Import event_summaries table."""
    print("\n" + "="*80)
    print("IMPORTING EVENT_SUMMARIES")
    print("="*80)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")

    total_rows = 0
    inserted_rows = 0
    error_rows = 0

    engine = get_engine()

    # Filter for event_summaries files
    summary_files = [f for f in input_files if 'event_summaries' in f.name]

    if not summary_files:
        print("  [SKIP] No event_summaries files found")
        return

    for filepath in summary_files:
        print(f"\nProcessing {filepath.name}...")

        try:
            df = pd.read_parquet(filepath)
            print(f"  Loaded {len(df):,} summaries")
        except Exception as e:
            print(f"  [ERROR] Failed to read file: {e}")
            continue

        total_rows += len(df)

        if dry_run:
            print("  [DRY RUN] Would import this batch")
            continue

        # Process in batches
        batch_size = 500

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]

            print(f"  Processing batch {i//batch_size + 1} ({len(batch)} summaries)...", end=" ")

            with get_session() as session:
                batch_inserted = 0
                batch_errors = 0

                for _, row in batch.iterrows():
                    try:
                        # Prepare JSONB fields - convert numpy arrays to JSON strings
                        count_by_category = prepare_jsonb_field(row.get('count_by_category')) or '{}'
                        count_by_subcategory = prepare_jsonb_field(row.get('count_by_subcategory')) or '{}'
                        count_by_recipient = prepare_jsonb_field(row.get('count_by_recipient')) or '{}'
                        count_by_source = prepare_jsonb_field(row.get('count_by_source')) or '{}'
                        narrative_summary = prepare_jsonb_field(row.get('narrative_summary'))

                        # Use savepoint so one failed row doesn't abort the whole batch
                        with session.begin_nested():
                            session.execute(
                                text("""
                                    INSERT INTO event_summaries (
                                        id, period_type, period_start, period_end, event_name,
                                        initiating_country, first_observed_date, last_observed_date, status,
                                        created_at, updated_at, category_count, subcategory_count,
                                        recipient_count, source_count, total_documents_across_categories,
                                        count_by_category, count_by_subcategory, count_by_recipient,
                                        count_by_source, narrative_summary, material_score, material_justification,
                                        is_deleted
                                    ) VALUES (
                                        :id, :period_type, :period_start, :period_end, :event_name,
                                        :initiating_country, :first_observed_date, :last_observed_date, :status,
                                        :created_at, :updated_at, :category_count, :subcategory_count,
                                        :recipient_count, :source_count, :total_documents_across_categories,
                                        CAST(:count_by_category AS jsonb), CAST(:count_by_subcategory AS jsonb), CAST(:count_by_recipient AS jsonb),
                                        CAST(:count_by_source AS jsonb), CAST(:narrative_summary AS jsonb), :material_score, :material_justification,
                                        :is_deleted
                                    )
                                    ON CONFLICT (id) DO NOTHING
                                """),
                                {
                                    'id': str(row['id']),
                                    'period_type': safe_value(row.get('period_type'), 'DAILY'),
                                    'period_start': pd.to_datetime(row['period_start']).date() if safe_value(row.get('period_start')) else None,
                                    'period_end': pd.to_datetime(row['period_end']).date() if safe_value(row.get('period_end')) else None,
                                    'event_name': safe_value(row.get('event_name'), 'Unnamed Event'),
                                    'initiating_country': safe_value(row.get('initiating_country')),
                                    'first_observed_date': pd.to_datetime(row['first_observed_date']).date() if safe_value(row.get('first_observed_date')) else None,
                                    'last_observed_date': pd.to_datetime(row['last_observed_date']).date() if safe_value(row.get('last_observed_date')) else None,
                                    'status': safe_value(row.get('status'), 'ACTIVE'),
                                    'created_at': pd.to_datetime(row['created_at']) if safe_value(row.get('created_at')) else datetime.now(),
                                    'updated_at': pd.to_datetime(row['updated_at']) if safe_value(row.get('updated_at')) else None,
                                    'category_count': int(row['category_count']) if safe_value(row.get('category_count')) else 0,
                                    'subcategory_count': int(row['subcategory_count']) if safe_value(row.get('subcategory_count')) else 0,
                                    'recipient_count': int(row['recipient_count']) if safe_value(row.get('recipient_count')) else 0,
                                    'source_count': int(row['source_count']) if safe_value(row.get('source_count')) else 0,
                                    'total_documents_across_categories': int(row['total_documents_across_categories']) if safe_value(row.get('total_documents_across_categories')) else 0,
                                    'count_by_category': count_by_category,
                                    'count_by_subcategory': count_by_subcategory,
                                    'count_by_recipient': count_by_recipient,
                                    'count_by_source': count_by_source,
                                    'narrative_summary': narrative_summary,
                                    'material_score': float(row['material_score']) if safe_value(row.get('material_score')) else None,
                                    'material_justification': safe_value(row.get('material_justification')),
                                    'is_deleted': False
                                }
                            )
                        batch_inserted += 1

                    except Exception as e:
                        print(f"\n  [ERROR] Row failed: {e}")
                        batch_errors += 1
                        continue

                try:
                    session.commit()
                    inserted_rows += batch_inserted
                    error_rows += batch_errors
                    print(f"[OK] inserted={batch_inserted}, errors={batch_errors}")
                except Exception as e:
                    print(f"[ERROR] Batch commit failed: {e}")
                    session.rollback()
                    error_rows += len(batch)

    print(f"\n{'='*80}")
    print(f"Total summaries: {total_rows:,}")
    print(f"Inserted: {inserted_rows:,}")
    print(f"Errors: {error_rows:,}")


def main():
    parser = argparse.ArgumentParser(description='Import event tables from parquet files')
    parser.add_argument('--input-dir', type=str, help='Input directory containing parquet files')
    parser.add_argument('--s3-bucket', type=str, help='S3 bucket to download from')
    parser.add_argument('--s3-prefix', type=str, default='events/backup/',
                        help='S3 prefix for files to download')
    parser.add_argument('--tables', nargs='+',
                        choices=['event_clusters', 'daily_event_mentions', 'event_summaries', 'all'],
                        default=['all'],
                        help='Tables to import (default: all)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be imported without actually importing')
    parser.add_argument('--clear-existing', action='store_true',
                        help='Clear existing data before import (WARNING: destructive)')

    args = parser.parse_args()

    # Determine input source
    if args.s3_bucket:
        temp_dir = Path('./temp_event_import')
        input_files = download_from_s3(args.s3_bucket, args.s3_prefix, temp_dir)

        if not input_files:
            print("\n[ERROR] No files downloaded from S3")
            return

    elif args.input_dir:
        input_dir = Path(args.input_dir)

        try:
            dir_exists = input_dir.exists()
        except OSError as e:
            # Handle stale file handle (common in Docker when directory was removed/recreated on host)
            print(f"[ERROR] Cannot access input directory: {input_dir}")
            print(f"        OS Error: {e}")
            print(f"        This often happens in Docker when the directory was removed and recreated on the host.")
            print(f"        Try: 1) Exit and re-enter the container, or 2) Use an absolute path")
            return

        if not dir_exists:
            print(f"[ERROR] Input directory does not exist: {input_dir}")
            return

        try:
            input_files = list(input_dir.glob('*.parquet'))
        except OSError as e:
            print(f"[ERROR] Cannot list files in directory: {input_dir}")
            print(f"        OS Error: {e}")
            print(f"        Try exiting and re-entering the Docker container.")
            return

        if not input_files:
            print(f"[ERROR] No parquet files found in {input_dir}")
            return

        print(f"\nFound {len(input_files)} parquet files in {input_dir}")

    else:
        print("[ERROR] Must specify either --input-dir or --s3-bucket")
        parser.print_help()
        return

    # Determine which tables to import
    tables_to_import = args.tables
    if 'all' in tables_to_import:
        tables_to_import = ['event_clusters', 'daily_event_mentions', 'event_summaries']

    # Clear existing data if requested
    if args.clear_existing and not args.dry_run:
        print("\n" + "="*80)
        print("⚠️  CLEARING EXISTING DATA")
        print("="*80)

        engine = get_engine()

        if 'event_summaries' in tables_to_import:
            clear_table('event_summaries', engine)
        if 'daily_event_mentions' in tables_to_import:
            clear_table('daily_event_mentions', engine)
        if 'event_clusters' in tables_to_import:
            clear_table('event_clusters', engine)

    # Import each table
    if 'event_clusters' in tables_to_import:
        import_event_clusters(input_files, args.dry_run)

    if 'daily_event_mentions' in tables_to_import:
        import_daily_event_mentions(input_files, args.dry_run)

    if 'event_summaries' in tables_to_import:
        import_event_summaries(input_files, args.dry_run)

    # Clean up temp directory if used
    if args.s3_bucket:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\nCleaned up temporary directory: {temp_dir}")

    print("\n" + "="*80)
    print("IMPORT COMPLETE" if not args.dry_run else "DRY RUN COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
