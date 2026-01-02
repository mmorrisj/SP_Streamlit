"""
Export Materiality Scores to Parquet Files

This script exports materiality scores from canonical_events table for fast backup
and migration between systems.

Usage:
    # Export all materiality scores
    python services/pipeline/events/export_materiality_scores.py

    # Export to specific directory
    python services/pipeline/events/export_materiality_scores.py --output-dir /path/to/backup

    # Export only specific countries
    python services/pipeline/events/export_materiality_scores.py --countries China Iran

    # Export to S3
    python services/pipeline/events/export_materiality_scores.py --s3-bucket my-bucket --s3-prefix materiality/backup/

    # Include only scored events (exclude null/0 scores)
    python services/pipeline/events/export_materiality_scores.py --scored-only
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import json

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, and_, or_
from shared.database.database import get_engine, get_session
from shared.models.models import CanonicalEvent

try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


def get_materiality_stats():
    """Get statistics on materiality scores by country."""
    with get_session() as session:
        result = session.execute(text("""
            SELECT
                initiating_country,
                COUNT(*) as total_events,
                COUNT(material_score) as scored_events,
                COUNT(*) FILTER (WHERE material_score IS NULL OR material_score = 0) as unscored_events,
                ROUND(AVG(material_score)::numeric, 2) as avg_score,
                MIN(material_score) as min_score,
                MAX(material_score) as max_score
            FROM canonical_events
            GROUP BY initiating_country
            ORDER BY total_events DESC
        """))

        stats = []
        for row in result:
            stats.append({
                'country': row[0],
                'total': row[1],
                'scored': row[2],
                'unscored': row[3],
                'avg_score': float(row[4]) if row[4] else None,
                'min_score': float(row[5]) if row[5] else None,
                'max_score': float(row[6]) if row[6] else None
            })
        return stats


def export_materiality_scores(output_dir: Path, countries=None, scored_only=False, batch_size=10000):
    """
    Export materiality scores to parquet file(s).

    Args:
        output_dir: Directory to write parquet files
        countries: List of countries to export (None = all)
        scored_only: If True, only export events with non-null, non-zero scores
        batch_size: Number of events per file (for large exports)
    """
    print("\n" + "="*80)
    print("EXPORTING MATERIALITY SCORES")
    print("="*80)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Build query
    engine = get_engine()

    # Count total events to export
    with engine.connect() as conn:
        where_clauses = []
        params = {}

        if countries:
            where_clauses.append("initiating_country = ANY(:countries)")
            params['countries'] = countries

        if scored_only:
            where_clauses.append("material_score IS NOT NULL AND material_score > 0")

        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

        total = conn.execute(
            text(f"SELECT COUNT(*) FROM canonical_events WHERE {where_sql}"),
            params
        ).scalar()

    print(f"\nTotal events to export: {total:,}")

    if total == 0:
        print("[SKIP] No events to export")
        return []

    # Export in batches
    exported_files = []
    offset = 0
    file_num = 0

    while offset < total:
        print(f"\nExporting batch {file_num + 1} (offset {offset:,})...")

        # Fetch batch
        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT
                        id,
                        canonical_name,
                        initiating_country,
                        first_mention_date,
                        last_mention_date,
                        material_score,
                        material_justification,
                        primary_recipients,
                        primary_categories,
                        total_articles,
                        source_count
                    FROM canonical_events
                    WHERE {where_sql}
                    ORDER BY id
                    LIMIT :limit OFFSET :offset
                """),
                {**params, 'limit': batch_size, 'offset': offset}
            )

            rows = result.fetchall()

        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=[
            'id', 'canonical_name', 'initiating_country', 'first_mention_date',
            'last_mention_date', 'material_score', 'material_justification',
            'primary_recipients', 'primary_categories', 'total_articles', 'source_count'
        ])

        # Convert UUID to string for parquet compatibility
        df['id'] = df['id'].astype(str)

        # Write to parquet
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"materiality_scores_{timestamp}_batch{file_num:04d}.parquet"
        filepath = output_dir / filename

        df.to_parquet(filepath, compression='zstd', index=False)

        print(f"  [OK] Exported {len(df):,} events to {filename}")
        print(f"       Size: {filepath.stat().st_size / 1024 / 1024:.2f} MB")

        exported_files.append(filepath)

        offset += len(rows)
        file_num += 1

        if len(rows) < batch_size:
            break

    return exported_files


def upload_to_s3(files: list, bucket: str, prefix: str):
    """Upload exported files to S3."""
    if not BOTO3_AVAILABLE:
        print("[ERROR] boto3 not installed. Cannot upload to S3.")
        return False

    print(f"\n" + "="*80)
    print(f"UPLOADING TO S3: s3://{bucket}/{prefix}")
    print("="*80)

    s3 = boto3.client('s3')

    for filepath in files:
        key = f"{prefix.rstrip('/')}/{filepath.name}"

        try:
            print(f"\nUploading {filepath.name}...")
            s3.upload_file(str(filepath), bucket, key)
            print(f"  [OK] s3://{bucket}/{key}")
        except Exception as e:
            print(f"  [ERROR] Failed to upload {filepath.name}: {e}")
            return False

    # Create manifest file
    manifest = {
        'export_date': datetime.now().isoformat(),
        'total_files': len(files),
        'files': [f.name for f in files]
    }

    manifest_key = f"{prefix.rstrip('/')}/manifest.json"
    try:
        s3.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=json.dumps(manifest, indent=2),
            ContentType='application/json'
        )
        print(f"\n[OK] Uploaded manifest: s3://{bucket}/{manifest_key}")
    except Exception as e:
        print(f"[WARNING] Failed to upload manifest: {e}")

    return True


def main():
    parser = argparse.ArgumentParser(description='Export materiality scores to parquet files')
    parser.add_argument('--output-dir', type=str, default='./_data/exports/materiality',
                        help='Output directory for parquet files')
    parser.add_argument('--countries', nargs='+', help='Countries to export (default: all)')
    parser.add_argument('--scored-only', action='store_true',
                        help='Only export events with non-null, non-zero scores')
    parser.add_argument('--batch-size', type=int, default=10000,
                        help='Number of events per file')
    parser.add_argument('--s3-bucket', type=str, help='S3 bucket to upload to')
    parser.add_argument('--s3-prefix', type=str, default='materiality/backup/',
                        help='S3 prefix for uploaded files')
    parser.add_argument('--stats-only', action='store_true',
                        help='Only show statistics, do not export')

    args = parser.parse_args()

    # Show statistics
    print("\n" + "="*80)
    print("MATERIALITY SCORE STATISTICS")
    print("="*80)

    stats = get_materiality_stats()

    print(f"\n{'Country':<20} {'Total':<10} {'Scored':<10} {'Unscored':<10} {'Avg Score':<10}")
    print("-" * 80)

    for s in stats:
        avg_score_str = f"{s['avg_score']:.2f}" if s['avg_score'] else "N/A"
        print(f"{s['country']:<20} {s['total']:<10,} {s['scored']:<10,} {s['unscored']:<10,} {avg_score_str:<10}")

    if args.stats_only:
        return

    # Export
    output_dir = Path(args.output_dir)
    files = export_materiality_scores(
        output_dir=output_dir,
        countries=args.countries,
        scored_only=args.scored_only,
        batch_size=args.batch_size
    )

    if not files:
        print("\n[DONE] No files exported")
        return

    print("\n" + "="*80)
    print("EXPORT COMPLETE")
    print("="*80)
    print(f"\nTotal files: {len(files)}")
    total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
    print(f"Total size: {total_size:.2f} MB")
    print(f"Location: {output_dir.resolve()}")

    # Upload to S3 if requested
    if args.s3_bucket:
        success = upload_to_s3(files, args.s3_bucket, args.s3_prefix)
        if success:
            print(f"\n✅ Successfully uploaded to s3://{args.s3_bucket}/{args.s3_prefix}")
        else:
            print(f"\n❌ Upload to S3 failed")


if __name__ == "__main__":
    main()
