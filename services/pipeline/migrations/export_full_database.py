"""
Full Database Export Script

Exports ALL tables from System 1 in the correct dependency order for migration to System 2.
This creates a complete snapshot of the database state.

Usage:
    # Export to local directory
    python services/pipeline/migrations/export_full_database.py --output-dir ./full_export

    # Export and upload to S3
    python services/pipeline/migrations/export_full_database.py --output-dir ./full_export \
        --s3-bucket my-bucket --s3-prefix db-exports/20241120/

    # Export with custom batch size
    python services/pipeline/migrations/export_full_database.py --output-dir ./full_export --batch-size 5000

Tables exported (in order):
    1. documents (base table - 496,783 rows)
    2. Normalized relationships (categories, subcategories, countries, raw_events)
    3. Event processing (event_clusters, canonical_events, daily_event_mentions, event_summaries)
    4. Bilateral summaries (if present)

Output:
    - Parquet files (zstd compressed) for each table
    - manifest.json with export metadata
    - Optional S3 upload
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_engine, get_session

# Optional S3 support
try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# Table export order (respects foreign key dependencies)
EXPORT_ORDER = [
    # Base document table
    {
        'name': 'documents',
        'query': 'SELECT * FROM documents ORDER BY doc_id',
        'batch_size': 10000,
        'description': 'Core documents table'
    },
    # Normalized relationship tables
    {
        'name': 'categories',
        'query': 'SELECT * FROM categories ORDER BY doc_id, category',
        'batch_size': 50000,
        'description': 'Document categories (many-to-many)'
    },
    {
        'name': 'subcategories',
        'query': 'SELECT * FROM subcategories ORDER BY doc_id, subcategory',
        'batch_size': 50000,
        'description': 'Document subcategories (many-to-many)'
    },
    {
        'name': 'initiating_countries',
        'query': 'SELECT * FROM initiating_countries ORDER BY doc_id, initiating_country',
        'batch_size': 50000,
        'description': 'Document initiating countries (many-to-many)'
    },
    {
        'name': 'recipient_countries',
        'query': 'SELECT * FROM recipient_countries ORDER BY doc_id, recipient_country',
        'batch_size': 50000,
        'description': 'Document recipient countries (many-to-many)'
    },
    {
        'name': 'raw_events',
        'query': 'SELECT * FROM raw_events ORDER BY doc_id, event_name',
        'batch_size': 50000,
        'description': 'Document raw events (many-to-many)'
    },
    # Event processing tables
    {
        'name': 'event_clusters',
        'query': '''
            SELECT
                id, initiating_country, cluster_date, batch_number, cluster_id,
                event_names, doc_ids, cluster_size, is_noise, representative_name,
                centroid_embedding, processed, llm_deconflicted, created_at, refined_clusters
            FROM event_clusters
            ORDER BY initiating_country, cluster_date, batch_number, cluster_id
        ''',
        'batch_size': 10000,
        'description': 'DBSCAN event clusters'
    },
    {
        'name': 'canonical_events',
        'query': '''
            SELECT
                id, master_event_id, canonical_name, initiating_country,
                first_mention_date, last_mention_date, total_mention_days, total_articles,
                story_phase, days_since_last_mention, unique_sources, source_count,
                peak_mention_date, peak_daily_article_count, consolidated_description,
                key_facts, embedding_vector, alternative_names, primary_categories,
                primary_recipients, material_score, material_justification
            FROM canonical_events
            ORDER BY initiating_country, first_mention_date, id
        ''',
        'batch_size': 10000,
        'description': 'Canonical events'
    },
    {
        'name': 'daily_event_mentions',
        'query': '''
            SELECT
                id, canonical_event_id, initiating_country, mention_date,
                article_count, consolidated_headline, daily_summary,
                source_names, source_diversity_score, mention_context,
                news_intensity, doc_ids
            FROM daily_event_mentions
            ORDER BY initiating_country, mention_date, canonical_event_id
        ''',
        'batch_size': 10000,
        'description': 'Daily event mentions (event-to-document links)'
    },
    {
        'name': 'event_summaries',
        'query': '''
            SELECT
                id, period_type, period_start, period_end, event_name,
                initiating_country, first_observed_date, last_observed_date, status,
                period_summary_id, created_at, updated_at, created_by, is_deleted, deleted_at,
                category_count, subcategory_count, recipient_count, source_count,
                total_documents_across_categories, total_documents_across_subcategories,
                total_documents_across_recipients, total_documents_across_sources,
                count_by_category, count_by_subcategory, count_by_recipient,
                count_by_source, narrative_summary, material_score, material_justification
            FROM event_summaries
            ORDER BY initiating_country, period_type, period_start
        ''',
        'batch_size': 5000,
        'description': 'Event summaries (daily/weekly/monthly/yearly)'
    },
]

# Optional tables (export if they exist)
OPTIONAL_TABLES = [
    {
        'name': 'bilateral_relationship_summaries',
        'query': 'SELECT * FROM bilateral_relationship_summaries ORDER BY initiating_country, recipient_country',
        'batch_size': 1000,
        'description': 'Bilateral relationship summaries'
    },
    {
        'name': 'country_category_summaries',
        'query': 'SELECT * FROM country_category_summaries ORDER BY initiating_country, category',
        'batch_size': 1000,
        'description': 'Country-category summaries'
    },
    {
        'name': 'bilateral_category_summaries',
        'query': 'SELECT * FROM bilateral_category_summaries ORDER BY initiating_country, recipient_country, category',
        'batch_size': 1000,
        'description': 'Bilateral category summaries'
    },
]


def table_exists(session, table_name: str) -> bool:
    """Check if a table exists in the database."""
    result = session.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = :table_name
        )
    """), {'table_name': table_name}).fetchone()
    return result[0] if result else False


def get_table_count(session, table_name: str) -> int:
    """Get row count for a table."""
    try:
        result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
        return result[0] if result else 0
    except Exception as e:
        print(f"  [WARNING] Could not count rows in {table_name}: {e}")
        return 0


def convert_columns_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Convert DataFrame columns to parquet-compatible types."""
    # Convert UUID columns to strings
    for col in df.columns:
        if df[col].dtype == 'object':
            # Check if it's a UUID column
            sample = df[col].dropna().head(1)
            if len(sample) > 0:
                val = sample.iloc[0]
                if hasattr(val, '__class__') and 'UUID' in str(val.__class__):
                    df[col] = df[col].astype(str)

    # Convert JSONB columns to JSON strings
    jsonb_columns = []
    for col in df.columns:
        if df[col].dtype == 'object':
            sample = df[col].dropna().head(1)
            if len(sample) > 0:
                val = sample.iloc[0]
                if isinstance(val, dict) or isinstance(val, list):
                    jsonb_columns.append(col)

    for col in jsonb_columns:
        df[col] = df[col].apply(lambda x: json.dumps(x) if x is not None else None)

    return df


def export_table(session, table_config: Dict, output_dir: Path, file_num: int = 0) -> Dict:
    """Export a single table to parquet file(s)."""
    table_name = table_config['name']
    query = table_config['query']
    batch_size = table_config['batch_size']

    print(f"\n{'='*80}")
    print(f"Exporting: {table_name}")
    print(f"{'='*80}")

    # Get total count
    total_rows = get_table_count(session, table_name)
    print(f"Total rows: {total_rows:,}")

    if total_rows == 0:
        print("  [SKIP] Table is empty")
        return {
            'table': table_name,
            'files': [],
            'total_rows': 0,
            'status': 'empty'
        }

    # Export in batches
    exported_files = []
    total_exported = 0
    batch_num = 0

    offset = 0
    while offset < total_rows:
        # Fetch batch
        batch_query = f"{query} LIMIT {batch_size} OFFSET {offset}"
        df = pd.read_sql(batch_query, session.connection())

        if len(df) == 0:
            break

        # Convert types for parquet
        df = convert_columns_for_parquet(df)

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{table_name}_{timestamp}_batch{batch_num:04d}.parquet"
        filepath = output_dir / filename

        # Write parquet
        df.to_parquet(filepath, compression='zstd', index=False)

        file_size_mb = filepath.stat().st_size / 1024 / 1024
        print(f"  Batch {batch_num + 1}: {len(df):,} rows -> {filename} ({file_size_mb:.2f} MB)")

        exported_files.append(filename)
        total_exported += len(df)
        batch_num += 1
        offset += batch_size

    print(f"\n  [OK] Exported {total_exported:,} rows in {len(exported_files)} file(s)")

    return {
        'table': table_name,
        'description': table_config['description'],
        'files': exported_files,
        'total_rows': total_exported,
        'batch_count': len(exported_files),
        'status': 'success'
    }


def export_all_tables(output_dir: Path, include_optional: bool = True):
    """Export all tables to the output directory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*80)
    print("FULL DATABASE EXPORT")
    print("="*80)
    print(f"\nOutput directory: {output_dir}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    manifest = {
        'export_timestamp': datetime.now().isoformat(),
        'export_dir': str(output_dir),
        'tables': [],
        'total_files': 0,
        'total_rows': 0,
        'total_size_mb': 0.0
    }

    with get_session() as session:
        # Export required tables
        for table_config in EXPORT_ORDER:
            try:
                result = export_table(session, table_config, output_dir)
                manifest['tables'].append(result)
                manifest['total_files'] += len(result['files'])
                manifest['total_rows'] += result['total_rows']
            except Exception as e:
                print(f"\n  [ERROR] Error exporting {table_config['name']}: {e}")
                import traceback
                traceback.print_exc()
                manifest['tables'].append({
                    'table': table_config['name'],
                    'files': [],
                    'total_rows': 0,
                    'status': 'error',
                    'error': str(e)
                })

        # Export optional tables
        if include_optional:
            print("\n" + "="*80)
            print("OPTIONAL TABLES")
            print("="*80)

            for table_config in OPTIONAL_TABLES:
                if table_exists(session, table_config['name']):
                    try:
                        result = export_table(session, table_config, output_dir)
                        manifest['tables'].append(result)
                        manifest['total_files'] += len(result['files'])
                        manifest['total_rows'] += result['total_rows']
                    except Exception as e:
                        print(f"\n  [ERROR] Error exporting {table_config['name']}: {e}")
                        manifest['tables'].append({
                            'table': table_config['name'],
                            'files': [],
                            'total_rows': 0,
                            'status': 'error',
                            'error': str(e)
                        })
                else:
                    print(f"\n[SKIP] {table_config['name']} - table does not exist")

    # Calculate total size
    for file in output_dir.glob('*.parquet'):
        manifest['total_size_mb'] += file.stat().st_size / 1024 / 1024

    # Write manifest
    manifest_path = output_dir / 'manifest.json'
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    # Print summary
    print("\n" + "="*80)
    print("EXPORT COMPLETE")
    print("="*80)
    print(f"\nTotal tables exported: {len([t for t in manifest['tables'] if t['status'] == 'success'])}")
    print(f"Total files created: {manifest['total_files']:,}")
    print(f"Total rows exported: {manifest['total_rows']:,}")
    print(f"Total size: {manifest['total_size_mb']:.2f} MB")
    print(f"\nManifest: {manifest_path}")

    # Print table breakdown
    print("\nTable Breakdown:")
    print(f"{'Table':<40} {'Rows':<15} {'Files':<10} {'Status':<10}")
    print("-" * 80)
    for table in manifest['tables']:
        print(f"{table['table']:<40} {table['total_rows']:>14,} {len(table['files']):>9} {table['status']:<10}")


def upload_to_s3(output_dir: Path, bucket: str, prefix: str) -> List[str]:
    """Upload exported files to S3.

    Args:
        output_dir: Local directory containing exported files
        bucket: S3 bucket name
        prefix: S3 prefix (folder path)

    Returns:
        List of uploaded S3 keys
    """
    if not BOTO3_AVAILABLE:
        print("[ERROR] boto3 not available for S3 upload")
        return []

    print(f"\n{'='*80}")
    print("UPLOADING TO S3")
    print("="*80)
    print(f"Destination: s3://{bucket}/{prefix}")

    # Ensure prefix ends with /
    if prefix and not prefix.endswith('/'):
        prefix = prefix + '/'

    s3 = boto3.client('s3')
    uploaded_keys = []

    # Get all parquet and json files
    files_to_upload = list(output_dir.glob('*.parquet')) + list(output_dir.glob('*.json'))

    print(f"Found {len(files_to_upload)} files to upload")

    for local_file in files_to_upload:
        s3_key = f"{prefix}{local_file.name}"

        try:
            file_size_mb = local_file.stat().st_size / 1024 / 1024
            print(f"  Uploading {local_file.name} ({file_size_mb:.2f} MB)...", end=" ")

            s3.upload_file(
                str(local_file),
                bucket,
                s3_key
            )

            print(f"[OK]")
            uploaded_keys.append(s3_key)

        except ClientError as e:
            print(f"[ERROR] {e}")

    print(f"\n[OK] Uploaded {len(uploaded_keys)} files to s3://{bucket}/{prefix}")
    return uploaded_keys


def main():
    parser = argparse.ArgumentParser(
        description='Export full database for System 2 migration',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--output-dir', type=str, required=True,
                       help='Output directory for parquet files')
    parser.add_argument('--skip-optional', action='store_true',
                       help='Skip optional tables (bilateral summaries, etc.)')
    parser.add_argument('--s3-bucket', type=str,
                       help='Upload to S3 bucket after export (optional)')
    parser.add_argument('--s3-prefix', type=str, default='full_db_export/',
                       help='S3 prefix for uploaded files (default: full_db_export/)')

    args = parser.parse_args()

    # Run export
    export_all_tables(
        output_dir=args.output_dir,
        include_optional=not args.skip_optional
    )

    # Upload to S3 if requested
    if args.s3_bucket:
        if not BOTO3_AVAILABLE:
            print("\n[ERROR] Cannot upload to S3: boto3 not installed")
            print("Install with: pip install boto3")
            return

        uploaded = upload_to_s3(
            output_dir=Path(args.output_dir),
            bucket=args.s3_bucket,
            prefix=args.s3_prefix
        )

        if uploaded:
            print(f"\nTo restore from S3, use:")
            print(f"  python services/pipeline/migrations/import_full_database.py \\")
            print(f"      --s3-bucket {args.s3_bucket} --s3-prefix {args.s3_prefix}")


if __name__ == "__main__":
    main()
