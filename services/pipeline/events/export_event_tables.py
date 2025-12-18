"""
Export Event Tables to Parquet Files

Exports event-related tables for fast backup and migration between systems:
- event_clusters (raw daily clusters from DBSCAN)
- daily_event_mentions (event-to-document links)
- event_summaries (period summaries with narratives)

Usage:
    # Export all event tables
    python services/pipeline/events/export_event_tables.py

    # Export specific tables only
    python services/pipeline/events/export_event_tables.py --tables event_clusters daily_event_mentions

    # Export to specific directory
    python services/pipeline/events/export_event_tables.py --output-dir /path/to/backup

    # Export specific countries
    python services/pipeline/events/export_event_tables.py --countries China Iran

    # Export to S3
    python services/pipeline/events/export_event_tables.py --s3-bucket my-bucket --s3-prefix events/backup/
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

from sqlalchemy import text
from shared.database.database import get_engine, get_session

try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


def get_table_stats():
    """Get statistics on event tables."""
    with get_session() as session:
        stats = {}

        # Event clusters
        result = session.execute(text("""
            SELECT
                initiating_country,
                COUNT(*) as total_clusters,
                SUM(cluster_size) as total_events_in_clusters,
                COUNT(*) FILTER (WHERE llm_deconflicted = true) as deconflicted_count
            FROM event_clusters
            GROUP BY initiating_country
            ORDER BY total_clusters DESC
        """))
        stats['event_clusters'] = [
            {
                'country': row[0],
                'total_clusters': row[1],
                'total_events': row[2],
                'deconflicted': row[3]
            }
            for row in result
        ]

        # Daily event mentions
        result = session.execute(text("""
            SELECT
                initiating_country,
                COUNT(*) as total_mentions,
                COUNT(DISTINCT canonical_event_id) as unique_events,
                SUM(article_count) as total_articles
            FROM daily_event_mentions
            GROUP BY initiating_country
            ORDER BY total_mentions DESC
        """))
        stats['daily_event_mentions'] = [
            {
                'country': row[0],
                'total_mentions': row[1],
                'unique_events': row[2],
                'total_articles': row[3] if row[3] else 0
            }
            for row in result
        ]

        # Event summaries
        result = session.execute(text("""
            SELECT
                initiating_country,
                period_type::text,
                COUNT(*) as total_summaries,
                AVG(total_documents_across_categories) as avg_docs
            FROM event_summaries
            GROUP BY initiating_country, period_type
            ORDER BY initiating_country, period_type
        """))
        stats['event_summaries'] = [
            {
                'country': row[0],
                'period_type': row[1],
                'total_summaries': row[2],
                'avg_docs': float(row[3]) if row[3] else 0
            }
            for row in result
        ]

        return stats


def export_event_clusters(output_dir: Path, countries=None, batch_size=10000):
    """Export event_clusters table."""
    print("\n" + "="*80)
    print("EXPORTING EVENT_CLUSTERS")
    print("="*80)

    engine = get_engine()

    # Build where clause
    where_clauses = []
    params = {}

    if countries:
        where_clauses.append("initiating_country = ANY(:countries)")
        params['countries'] = countries

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    # Count total
    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM event_clusters WHERE {where_sql}"),
            params
        ).scalar()

    print(f"Total clusters to export: {total:,}")

    if total == 0:
        return []

    exported_files = []
    offset = 0
    file_num = 0

    while offset < total:
        print(f"\nExporting batch {file_num + 1} (offset {offset:,})...")

        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT
                        id,
                        initiating_country,
                        cluster_date,
                        batch_number,
                        cluster_id,
                        event_names,
                        doc_ids,
                        cluster_size,
                        is_noise,
                        representative_name,
                        processed,
                        llm_deconflicted,
                        created_at,
                        refined_clusters
                    FROM event_clusters
                    WHERE {where_sql}
                    ORDER BY cluster_date, batch_number, cluster_id
                    LIMIT :limit OFFSET :offset
                """),
                {**params, 'limit': batch_size, 'offset': offset}
            )
            rows = result.fetchall()

        df = pd.DataFrame(rows, columns=[
            'id', 'initiating_country', 'cluster_date', 'batch_number', 'cluster_id',
            'event_names', 'doc_ids', 'cluster_size', 'is_noise', 'representative_name',
            'processed', 'llm_deconflicted', 'created_at', 'refined_clusters'
        ])

        # Convert UUID to string
        df['id'] = df['id'].astype(str)

        # Convert arrays to JSON strings for parquet compatibility
        df['event_names'] = df['event_names'].apply(lambda x: json.dumps(x) if x else None)
        df['doc_ids'] = df['doc_ids'].apply(lambda x: json.dumps(x) if x else None)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"event_clusters_{timestamp}_batch{file_num:04d}.parquet"
        filepath = output_dir / filename

        df.to_parquet(filepath, compression='zstd', index=False)

        print(f"  [OK] Exported {len(df):,} clusters to {filename}")
        print(f"       Size: {filepath.stat().st_size / 1024 / 1024:.2f} MB")

        exported_files.append(filepath)
        offset += len(rows)
        file_num += 1

        if len(rows) < batch_size:
            break

    return exported_files


def export_daily_event_mentions(output_dir: Path, countries=None, batch_size=10000):
    """Export daily_event_mentions table."""
    print("\n" + "="*80)
    print("EXPORTING DAILY_EVENT_MENTIONS")
    print("="*80)

    engine = get_engine()

    where_clauses = []
    params = {}

    if countries:
        where_clauses.append("initiating_country = ANY(:countries)")
        params['countries'] = countries

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM daily_event_mentions WHERE {where_sql}"),
            params
        ).scalar()

    print(f"Total mentions to export: {total:,}")

    if total == 0:
        return []

    exported_files = []
    offset = 0
    file_num = 0

    while offset < total:
        print(f"\nExporting batch {file_num + 1} (offset {offset:,})...")

        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT
                        id,
                        canonical_event_id,
                        initiating_country,
                        mention_date,
                        article_count,
                        consolidated_headline,
                        daily_summary,
                        source_names,
                        source_diversity_score,
                        mention_context,
                        news_intensity,
                        doc_ids
                    FROM daily_event_mentions
                    WHERE {where_sql}
                    ORDER BY mention_date, canonical_event_id
                    LIMIT :limit OFFSET :offset
                """),
                {**params, 'limit': batch_size, 'offset': offset}
            )
            rows = result.fetchall()

        df = pd.DataFrame(rows, columns=[
            'id', 'canonical_event_id', 'initiating_country', 'mention_date',
            'article_count', 'consolidated_headline', 'daily_summary', 'source_names',
            'source_diversity_score', 'mention_context', 'news_intensity', 'doc_ids'
        ])

        # Convert UUIDs to strings
        df['id'] = df['id'].astype(str)
        df['canonical_event_id'] = df['canonical_event_id'].astype(str)

        # Convert arrays to JSON strings
        df['source_names'] = df['source_names'].apply(lambda x: json.dumps(x) if x else None)
        df['doc_ids'] = df['doc_ids'].apply(lambda x: json.dumps(x) if x else None)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"daily_event_mentions_{timestamp}_batch{file_num:04d}.parquet"
        filepath = output_dir / filename

        df.to_parquet(filepath, compression='zstd', index=False)

        print(f"  [OK] Exported {len(df):,} mentions to {filename}")
        print(f"       Size: {filepath.stat().st_size / 1024 / 1024:.2f} MB")

        exported_files.append(filepath)
        offset += len(rows)
        file_num += 1

        if len(rows) < batch_size:
            break

    return exported_files


def export_event_summaries(output_dir: Path, countries=None, batch_size=10000):
    """Export event_summaries table."""
    print("\n" + "="*80)
    print("EXPORTING EVENT_SUMMARIES")
    print("="*80)

    engine = get_engine()

    where_clauses = []
    params = {}

    if countries:
        where_clauses.append("initiating_country = ANY(:countries)")
        params['countries'] = countries

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM event_summaries WHERE {where_sql}"),
            params
        ).scalar()

    print(f"Total summaries to export: {total:,}")

    if total == 0:
        return []

    exported_files = []
    offset = 0
    file_num = 0

    while offset < total:
        print(f"\nExporting batch {file_num + 1} (offset {offset:,})...")

        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT
                        id,
                        period_type::text,
                        period_start,
                        period_end,
                        event_name,
                        initiating_country,
                        first_observed_date,
                        last_observed_date,
                        status::text,
                        created_at,
                        updated_at,
                        category_count,
                        subcategory_count,
                        recipient_count,
                        source_count,
                        total_documents_across_categories,
                        count_by_category,
                        count_by_subcategory,
                        count_by_recipient,
                        count_by_source,
                        narrative_summary,
                        material_score,
                        material_justification
                    FROM event_summaries
                    WHERE {where_sql}
                    ORDER BY period_start, initiating_country
                    LIMIT :limit OFFSET :offset
                """),
                {**params, 'limit': batch_size, 'offset': offset}
            )
            rows = result.fetchall()

        df = pd.DataFrame(rows, columns=[
            'id', 'period_type', 'period_start', 'period_end', 'event_name',
            'initiating_country', 'first_observed_date', 'last_observed_date', 'status',
            'created_at', 'updated_at', 'category_count', 'subcategory_count',
            'recipient_count', 'source_count', 'total_documents_across_categories',
            'count_by_category', 'count_by_subcategory', 'count_by_recipient',
            'count_by_source', 'narrative_summary', 'material_score', 'material_justification'
        ])

        # Convert UUID to string
        df['id'] = df['id'].astype(str)

        # Convert JSONB columns to JSON strings for parquet compatibility
        jsonb_columns = ['count_by_category', 'count_by_subcategory', 'count_by_recipient',
                        'count_by_source', 'narrative_summary']
        for col in jsonb_columns:
            df[col] = df[col].apply(lambda x: json.dumps(x) if x is not None else None)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"event_summaries_{timestamp}_batch{file_num:04d}.parquet"
        filepath = output_dir / filename

        df.to_parquet(filepath, compression='zstd', index=False)

        print(f"  [OK] Exported {len(df):,} summaries to {filename}")
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

    # Create manifest
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
    parser = argparse.ArgumentParser(description='Export event tables to parquet files')
    parser.add_argument('--output-dir', type=str, default='./event_exports',
                        help='Output directory for parquet files')
    parser.add_argument('--tables', nargs='+',
                        choices=['event_clusters', 'daily_event_mentions', 'event_summaries', 'all'],
                        default=['all'],
                        help='Tables to export (default: all)')
    parser.add_argument('--countries', nargs='+',
                        help='Countries to export (default: all)')
    parser.add_argument('--batch-size', type=int, default=10000,
                        help='Number of rows per file')
    parser.add_argument('--s3-bucket', type=str,
                        help='S3 bucket to upload to')
    parser.add_argument('--s3-prefix', type=str, default='events/backup/',
                        help='S3 prefix for uploaded files')
    parser.add_argument('--stats-only', action='store_true',
                        help='Only show statistics, do not export')

    args = parser.parse_args()

    # Show statistics
    print("\n" + "="*80)
    print("EVENT TABLES STATISTICS")
    print("="*80)

    stats = get_table_stats()

    print("\nEVENT_CLUSTERS:")
    print(f"{'Country':<20} {'Clusters':<15} {'Events':<15} {'Deconflicted':<15}")
    print("-" * 80)
    for s in stats['event_clusters']:
        print(f"{s['country']:<20} {s['total_clusters']:<15,} {s['total_events']:<15,} {s['deconflicted']:<15,}")

    print("\nDAILY_EVENT_MENTIONS:")
    print(f"{'Country':<20} {'Mentions':<15} {'Unique Events':<15} {'Articles':<15}")
    print("-" * 80)
    for s in stats['daily_event_mentions']:
        print(f"{s['country']:<20} {s['total_mentions']:<15,} {s['unique_events']:<15,} {s['total_articles']:<15,}")

    print("\nEVENT_SUMMARIES:")
    print(f"{'Country':<20} {'Type':<10} {'Summaries':<15} {'Avg Docs':<15}")
    print("-" * 80)
    for s in stats['event_summaries']:
        print(f"{s['country']:<20} {s['period_type']:<10} {s['total_summaries']:<15,} {s['avg_docs']:<15.1f}")

    if args.stats_only:
        return

    # Determine which tables to export
    tables_to_export = args.tables
    if 'all' in tables_to_export:
        tables_to_export = ['event_clusters', 'daily_event_mentions', 'event_summaries']

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_files = []

    # Export each table
    if 'event_clusters' in tables_to_export:
        files = export_event_clusters(output_dir, args.countries, args.batch_size)
        all_files.extend(files)

    if 'daily_event_mentions' in tables_to_export:
        files = export_daily_event_mentions(output_dir, args.countries, args.batch_size)
        all_files.extend(files)

    if 'event_summaries' in tables_to_export:
        files = export_event_summaries(output_dir, args.countries, args.batch_size)
        all_files.extend(files)

    if not all_files:
        print("\n[DONE] No files exported")
        return

    print("\n" + "="*80)
    print("EXPORT COMPLETE")
    print("="*80)
    print(f"\nTotal files: {len(all_files)}")
    total_size = sum(f.stat().st_size for f in all_files) / 1024 / 1024
    print(f"Total size: {total_size:.2f} MB")
    print(f"Location: {output_dir.resolve()}")

    # Upload to S3 if requested
    if args.s3_bucket:
        success = upload_to_s3(all_files, args.s3_bucket, args.s3_prefix)
        if success:
            print(f"\n✅ Successfully uploaded to s3://{args.s3_bucket}/{args.s3_prefix}")
        else:
            print(f"\n❌ Upload to S3 failed")


if __name__ == "__main__":
    main()
