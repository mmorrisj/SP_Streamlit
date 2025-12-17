"""
Import Materiality Scores from Parquet Files

This script imports materiality scores from parquet files created by export_materiality_scores.py
and updates the canonical_events table. This is useful for migrating scores between systems.

Usage:
    # Import from local directory
    python services/pipeline/events/import_materiality_scores.py --input-dir ./materiality_exports

    # Import from S3
    python services/pipeline/events/import_materiality_scores.py --s3-bucket my-bucket --s3-prefix materiality/backup/

    # Dry run (don't actually import, just show what would be imported)
    python services/pipeline/events/import_materiality_scores.py --input-dir ./materiality_exports --dry-run

    # Only update existing events (don't create new ones)
    python services/pipeline/events/import_materiality_scores.py --input-dir ./materiality_exports --update-only

    # Overwrite existing scores
    python services/pipeline/events/import_materiality_scores.py --input-dir ./materiality_exports --overwrite
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import json
from typing import List, Optional

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, and_
from shared.database.database import get_engine, get_session
from shared.models.models import CanonicalEvent

try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


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
        # List objects
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


def import_materiality_scores(
    input_files: List[Path],
    dry_run: bool = False,
    update_only: bool = False,
    overwrite: bool = False
):
    """
    Import materiality scores from parquet files.

    Args:
        input_files: List of parquet files to import
        dry_run: If True, don't actually import, just show what would be done
        update_only: If True, only update existing events (don't create new ones)
        overwrite: If True, overwrite existing scores (default: skip events with scores)
    """
    print("\n" + "="*80)
    print("IMPORTING MATERIALITY SCORES")
    print("="*80)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made to the database\n")

    total_events = 0
    updated_events = 0
    skipped_events = 0
    created_events = 0
    error_events = 0

    engine = get_engine()

    for filepath in input_files:
        print(f"\nProcessing {filepath.name}...")

        # Load parquet file
        try:
            df = pd.read_parquet(filepath)
            print(f"  Loaded {len(df):,} events from file")
        except Exception as e:
            print(f"  [ERROR] Failed to read parquet file: {e}")
            continue

        total_events += len(df)

        # Process in batches
        batch_size = 1000

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]

            print(f"  Processing batch {i//batch_size + 1} ({len(batch)} events)...", end=" ")

            if dry_run:
                print("[DRY RUN]")
                continue

            with get_session() as session:
                for _, row in batch.iterrows():
                    try:
                        # Check if event exists
                        existing = session.query(CanonicalEvent).filter(
                            CanonicalEvent.id == row['id']
                        ).first()

                        if existing:
                            # Update existing event
                            if existing.material_score and not overwrite:
                                # Skip - already has a score
                                skipped_events += 1
                                continue

                            # Update score and justification
                            existing.material_score = row['material_score'] if pd.notna(row['material_score']) else None
                            existing.material_justification = row['material_justification'] if pd.notna(row['material_justification']) else None

                            updated_events += 1

                        else:
                            # Create new event (if not update_only mode)
                            if update_only:
                                skipped_events += 1
                                continue

                            new_event = CanonicalEvent(
                                id=row['id'],
                                canonical_name=row.get('canonical_name', 'Imported Event'),
                                initiating_country=row['initiating_country'],
                                first_mention_date=pd.to_datetime(row['first_mention_date']).date() if pd.notna(row.get('first_mention_date')) else None,
                                last_mention_date=pd.to_datetime(row['last_mention_date']).date() if pd.notna(row.get('last_mention_date')) else None,
                                material_score=row['material_score'] if pd.notna(row['material_score']) else None,
                                material_justification=row['material_justification'] if pd.notna(row['material_justification']) else None,
                                primary_recipients=row.get('primary_recipients') if pd.notna(row.get('primary_recipients')) else None,
                                primary_categories=row.get('primary_categories') if pd.notna(row.get('primary_categories')) else None,
                                total_articles=row.get('total_articles', 0),
                                source_count=row.get('source_count', 0)
                            )

                            session.add(new_event)
                            created_events += 1

                    except Exception as e:
                        print(f"\n  [ERROR] Failed to process event ID {row['id']}: {e}")
                        error_events += 1
                        session.rollback()
                        continue

                # Commit batch
                try:
                    session.commit()
                    print("[OK]")
                except Exception as e:
                    print(f"[ERROR] Failed to commit batch: {e}")
                    session.rollback()
                    error_events += len(batch)

    # Print summary
    print("\n" + "="*80)
    print("IMPORT COMPLETE" if not dry_run else "DRY RUN COMPLETE")
    print("="*80)
    print(f"\nTotal events in files: {total_events:,}")
    print(f"Updated events: {updated_events:,}")
    print(f"Created events: {created_events:,}")
    print(f"Skipped events: {skipped_events:,}")
    print(f"Error events: {error_events:,}")

    if dry_run:
        print("\n⚠️  This was a dry run - no changes were made to the database")
        print("    Run without --dry-run to actually import the data")


def main():
    parser = argparse.ArgumentParser(description='Import materiality scores from parquet files')
    parser.add_argument('--input-dir', type=str, help='Input directory containing parquet files')
    parser.add_argument('--s3-bucket', type=str, help='S3 bucket to download from')
    parser.add_argument('--s3-prefix', type=str, default='materiality/backup/',
                        help='S3 prefix for files to download')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be imported without actually importing')
    parser.add_argument('--update-only', action='store_true',
                        help='Only update existing events, do not create new ones')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite existing scores (default: skip events with scores)')

    args = parser.parse_args()

    # Determine input source
    if args.s3_bucket:
        # Download from S3
        temp_dir = Path('./temp_materiality_import')
        input_files = download_from_s3(args.s3_bucket, args.s3_prefix, temp_dir)

        if not input_files:
            print("\n[ERROR] No files downloaded from S3")
            return

    elif args.input_dir:
        # Use local directory
        input_dir = Path(args.input_dir)

        if not input_dir.exists():
            print(f"[ERROR] Input directory does not exist: {input_dir}")
            return

        input_files = list(input_dir.glob('*.parquet'))

        if not input_files:
            print(f"[ERROR] No parquet files found in {input_dir}")
            return

        print(f"\nFound {len(input_files)} parquet files in {input_dir}")

    else:
        print("[ERROR] Must specify either --input-dir or --s3-bucket")
        parser.print_help()
        return

    # Import scores
    import_materiality_scores(
        input_files=input_files,
        dry_run=args.dry_run,
        update_only=args.update_only,
        overwrite=args.overwrite
    )

    # Clean up temp directory if used
    if args.s3_bucket:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\nCleaned up temporary directory: {temp_dir}")


if __name__ == "__main__":
    main()
