"""
Full Database Import Script

Imports ALL tables from System 1 export to System 2 in the correct dependency order.
This replicates the exact database state from System 1.

Usage:
    # Test import (dry run)
    python services/pipeline/migrations/import_full_database.py --input-dir ./full_export --dry-run

    # Actual import
    python services/pipeline/migrations/import_full_database.py --input-dir ./full_export

    # Clear and import (WARNING: destructive!)
    python services/pipeline/migrations/import_full_database.py --input-dir ./full_export --clear-existing

Tables imported (in order):
    1. documents
    2. Normalized relationships
    3. Event processing tables
    4. Bilateral summaries (if present)
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_engine, get_session


def safe_value(val, default=None):
    """Return value if not NaN/None, otherwise return default."""
    if val is None:
        return default
    if isinstance(val, float) and np.isnan(val):
        return default
    if pd.isna(val):
        return default
    return val


def convert_to_json_serializable(obj):
    """Recursively convert numpy arrays to native Python types."""
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
    """Prepare JSONB field for PostgreSQL insertion."""
    if val is None:
        return None
    try:
        if isinstance(val, float) and np.isnan(val):
            return None
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            result = json.dumps(convert_to_json_serializable(parsed))
            return result
        except json.JSONDecodeError:
            return None

    converted = convert_to_json_serializable(val)
    if converted is None:
        return None

    return json.dumps(converted)


def prepare_text_array_field(val):
    """Prepare text[] array field for PostgreSQL insertion."""
    if val is None or (isinstance(val, float) and np.isnan(val)) or pd.isna(val):
        return None

    if isinstance(val, str):
        try:
            val = json.loads(val)
        except json.JSONDecodeError:
            return None

    if isinstance(val, np.ndarray):
        val = val.tolist()

    if not isinstance(val, list):
        return None

    return [str(item) for item in val]


def prepare_float_array_field(val):
    """Prepare float[] array field for PostgreSQL insertion."""
    if val is None or (isinstance(val, float) and np.isnan(val)) or pd.isna(val):
        return None

    if isinstance(val, str):
        try:
            val = json.loads(val)
        except json.JSONDecodeError:
            return None

    if isinstance(val, np.ndarray):
        val = val.tolist()

    if not isinstance(val, list):
        return None

    return [float(item) for item in val]


def clear_table(session, table_name: str):
    """Clear all data from a table."""
    try:
        session.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
        session.commit()
        print(f"  ✓ Cleared table: {table_name}")
    except Exception as e:
        print(f"  ⚠️  Could not clear {table_name}: {e}")
        session.rollback()


def import_documents(files: List[Path], session, dry_run: bool = False) -> int:
    """Import documents table."""
    print("\nImporting documents...")
    total_imported = 0
    batch_size = 500

    for filepath in files:
        print(f"  Processing {filepath.name}...")
        df = pd.read_parquet(filepath)

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]
            print(f"    Batch {i//batch_size + 1} ({len(batch)} rows)...", end=" ")

            if dry_run:
                print("[DRY RUN]")
                continue

            batch_inserted = 0
            for _, row in batch.iterrows():
                try:
                    with session.begin_nested():
                        session.execute(
                            text("""
                                INSERT INTO documents (
                                    doc_id, title, source_name, source_geofocus, source_consumption,
                                    source_description, source_medium, source_location, source_editorial,
                                    date, collection_name, gai_engine, gai_promptid, gai_promptversion,
                                    salience, salience_justification, salience_bool, category,
                                    category_justification, subcategory, initiating_country,
                                    recipient_country, _projects, lat_long, location,
                                    monetary_commitment, distilled_text, event_name, project_name
                                ) VALUES (
                                    :doc_id, :title, :source_name, :source_geofocus, :source_consumption,
                                    :source_description, :source_medium, :source_location, :source_editorial,
                                    :date, :collection_name, :gai_engine, :gai_promptid, :gai_promptversion,
                                    :salience, :salience_justification, :salience_bool, :category,
                                    :category_justification, :subcategory, :initiating_country,
                                    :recipient_country, :projects, :lat_long, :location,
                                    :monetary_commitment, :distilled_text, :event_name, :project_name
                                )
                                ON CONFLICT (doc_id) DO NOTHING
                            """),
                            {
                                'doc_id': safe_value(row.get('doc_id')),
                                'title': safe_value(row.get('title')),
                                'source_name': safe_value(row.get('source_name')),
                                'source_geofocus': safe_value(row.get('source_geofocus')),
                                'source_consumption': safe_value(row.get('source_consumption')),
                                'source_description': safe_value(row.get('source_description')),
                                'source_medium': safe_value(row.get('source_medium')),
                                'source_location': safe_value(row.get('source_location')),
                                'source_editorial': safe_value(row.get('source_editorial')),
                                'date': pd.to_datetime(row['date']).date() if safe_value(row.get('date')) else None,
                                'collection_name': safe_value(row.get('collection_name')),
                                'gai_engine': safe_value(row.get('gai_engine')),
                                'gai_promptid': safe_value(row.get('gai_promptid')),
                                'gai_promptversion': int(row['gai_promptversion']) if safe_value(row.get('gai_promptversion')) else None,
                                'salience': safe_value(row.get('salience')),
                                'salience_justification': safe_value(row.get('salience_justification')),
                                'salience_bool': safe_value(row.get('salience_bool')),
                                'category': safe_value(row.get('category')),
                                'category_justification': safe_value(row.get('category_justification')),
                                'subcategory': safe_value(row.get('subcategory')),
                                'initiating_country': safe_value(row.get('initiating_country')),
                                'recipient_country': safe_value(row.get('recipient_country')),
                                'projects': safe_value(row.get('_projects')),
                                'lat_long': safe_value(row.get('lat_long')),
                                'location': safe_value(row.get('location')),
                                'monetary_commitment': safe_value(row.get('monetary_commitment')),
                                'distilled_text': safe_value(row.get('distilled_text')),
                                'event_name': safe_value(row.get('event_name')),
                                'project_name': safe_value(row.get('project_name')),
                            }
                        )
                    batch_inserted += 1
                except Exception as e:
                    print(f"\n      [ERROR] Row failed: {e}")
                    continue

            try:
                session.commit()
                print(f"[OK] {batch_inserted} rows")
                total_imported += batch_inserted
            except Exception as e:
                print(f"[ERROR] Batch commit failed: {e}")
                session.rollback()

    return total_imported


def import_relationship_table(table_name: str, files: List[Path], session, dry_run: bool = False) -> int:
    """Import a many-to-many relationship table (categories, subcategories, etc.)."""
    print(f"\nImporting {table_name}...")
    total_imported = 0
    batch_size = 1000

    for filepath in files:
        print(f"  Processing {filepath.name}...")
        df = pd.read_parquet(filepath)

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]
            print(f"    Batch {i//batch_size + 1} ({len(batch)} rows)...", end=" ")

            if dry_run:
                print("[DRY RUN]")
                continue

            batch_inserted = 0
            for _, row in batch.iterrows():
                try:
                    with session.begin_nested():
                        # Get columns dynamically
                        col1_name = list(row.index)[0]  # doc_id
                        col2_name = list(row.index)[1]  # category/subcategory/etc

                        session.execute(
                            text(f"""
                                INSERT INTO {table_name} ({col1_name}, {col2_name})
                                VALUES (:col1, :col2)
                                ON CONFLICT ({col1_name}, {col2_name}) DO NOTHING
                            """),
                            {
                                'col1': safe_value(row[col1_name]),
                                'col2': safe_value(row[col2_name])
                            }
                        )
                    batch_inserted += 1
                except Exception as e:
                    print(f"\n      [ERROR] Row failed: {e}")
                    continue

            try:
                session.commit()
                print(f"[OK] {batch_inserted} rows")
                total_imported += batch_inserted
            except Exception as e:
                print(f"[ERROR] Batch commit failed: {e}")
                session.rollback()

    return total_imported


def import_table_from_manifest(table_info: Dict, input_dir: Path, session, dry_run: bool = False) -> int:
    """Import a table based on manifest information."""
    table_name = table_info['table']
    files = [input_dir / f for f in table_info['files']]

    if not files:
        print(f"\n[SKIP] {table_name} - no files")
        return 0

    # Handle special cases
    if table_name == 'documents':
        return import_documents(files, session, dry_run)
    elif table_name in ['categories', 'subcategories', 'initiating_countries', 'recipient_countries', 'raw_events']:
        return import_relationship_table(table_name, files, session, dry_run)
    elif table_name == 'event_clusters':
        from services.pipeline.events.import_event_tables import import_event_clusters
        return import_event_clusters(files, dry_run)
    elif table_name == 'canonical_events':
        return import_canonical_events(files, session, dry_run)
    elif table_name == 'daily_event_mentions':
        from services.pipeline.events.import_event_tables import import_daily_event_mentions
        return import_daily_event_mentions(files, dry_run)
    elif table_name == 'event_summaries':
        from services.pipeline.events.import_event_tables import import_event_summaries
        return import_event_summaries(files, dry_run)
    else:
        print(f"\n⚠️  {table_name} - import not implemented yet")
        return 0


def import_canonical_events(files: List[Path], session, dry_run: bool = False) -> int:
    """Import canonical_events table."""
    print("\nImporting canonical_events...")
    total_imported = 0
    batch_size = 500

    for filepath in files:
        print(f"  Processing {filepath.name}...")
        df = pd.read_parquet(filepath)

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]
            print(f"    Batch {i//batch_size + 1} ({len(batch)} rows)...", end=" ")

            if dry_run:
                print("[DRY RUN]")
                continue

            batch_inserted = 0
            for _, row in batch.iterrows():
                try:
                    # Prepare fields
                    unique_sources = prepare_text_array_field(row.get('unique_sources'))
                    alternative_names = prepare_text_array_field(row.get('alternative_names'))
                    embedding_vector = prepare_float_array_field(row.get('embedding_vector'))
                    key_facts = prepare_jsonb_field(row.get('key_facts'))
                    primary_categories = prepare_jsonb_field(row.get('primary_categories'))
                    primary_recipients = prepare_jsonb_field(row.get('primary_recipients'))

                    with session.begin_nested():
                        session.execute(
                            text("""
                                INSERT INTO canonical_events (
                                    id, master_event_id, canonical_name, initiating_country,
                                    first_mention_date, last_mention_date, total_mention_days,
                                    total_articles, story_phase, days_since_last_mention,
                                    unique_sources, source_count, peak_mention_date,
                                    peak_daily_article_count, consolidated_description,
                                    key_facts, embedding_vector, alternative_names,
                                    primary_categories, primary_recipients,
                                    material_score, material_justification
                                ) VALUES (
                                    :id, :master_event_id, :canonical_name, :initiating_country,
                                    :first_mention_date, :last_mention_date, :total_mention_days,
                                    :total_articles, :story_phase, :days_since_last_mention,
                                    :unique_sources, :source_count, :peak_mention_date,
                                    :peak_daily_article_count, :consolidated_description,
                                    CAST(:key_facts AS jsonb), :embedding_vector, :alternative_names,
                                    CAST(:primary_categories AS jsonb), CAST(:primary_recipients AS jsonb),
                                    :material_score, :material_justification
                                )
                                ON CONFLICT (id) DO NOTHING
                            """),
                            {
                                'id': str(row['id']),
                                'master_event_id': str(row['master_event_id']) if safe_value(row.get('master_event_id')) else None,
                                'canonical_name': safe_value(row.get('canonical_name')),
                                'initiating_country': safe_value(row.get('initiating_country')),
                                'first_mention_date': pd.to_datetime(row['first_mention_date']).date() if safe_value(row.get('first_mention_date')) else None,
                                'last_mention_date': pd.to_datetime(row['last_mention_date']).date() if safe_value(row.get('last_mention_date')) else None,
                                'total_mention_days': int(row['total_mention_days']) if safe_value(row.get('total_mention_days')) else 1,
                                'total_articles': int(row['total_articles']) if safe_value(row.get('total_articles')) else 0,
                                'story_phase': safe_value(row.get('story_phase')),
                                'days_since_last_mention': int(row['days_since_last_mention']) if safe_value(row.get('days_since_last_mention')) else 0,
                                'unique_sources': unique_sources,
                                'source_count': int(row['source_count']) if safe_value(row.get('source_count')) else 0,
                                'peak_mention_date': pd.to_datetime(row['peak_mention_date']).date() if safe_value(row.get('peak_mention_date')) else None,
                                'peak_daily_article_count': int(row['peak_daily_article_count']) if safe_value(row.get('peak_daily_article_count')) else 0,
                                'consolidated_description': safe_value(row.get('consolidated_description')),
                                'key_facts': key_facts,
                                'embedding_vector': embedding_vector,
                                'alternative_names': alternative_names,
                                'primary_categories': primary_categories,
                                'primary_recipients': primary_recipients,
                                'material_score': float(row['material_score']) if safe_value(row.get('material_score')) else None,
                                'material_justification': safe_value(row.get('material_justification')),
                            }
                        )
                    batch_inserted += 1
                except Exception as e:
                    print(f"\n      [ERROR] Row failed: {e}")
                    continue

            try:
                session.commit()
                print(f"[OK] {batch_inserted} rows")
                total_imported += batch_inserted
            except Exception as e:
                print(f"[ERROR] Batch commit failed: {e}")
                session.rollback()

    return total_imported


def import_full_database(input_dir: Path, dry_run: bool = False, clear_existing: bool = False):
    """Import full database from export directory."""
    input_dir = Path(input_dir)

    # Load manifest
    manifest_path = input_dir / 'manifest.json'
    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}")
        return

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    print("\n" + "="*80)
    print("FULL DATABASE IMPORT")
    print("="*80)
    print(f"\nInput directory: {input_dir}")
    print(f"Export timestamp: {manifest['export_timestamp']}")
    print(f"Total tables: {len(manifest['tables'])}")
    print(f"Total rows: {manifest['total_rows']:,}")
    print(f"Total size: {manifest['total_size_mb']:.2f} MB")

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made to the database")

    if clear_existing and not dry_run:
        print("\n⚠️  WARNING: This will clear all existing data!")
        response = input("Type 'yes' to continue: ")
        if response.lower() != 'yes':
            print("Aborted.")
            return

    results = {}

    with get_session() as session:
        # Clear tables if requested
        if clear_existing and not dry_run:
            print("\nClearing existing tables...")
            for table_info in reversed(manifest['tables']):  # Reverse order for FK constraints
                clear_table(session, table_info['table'])

        # Import tables
        for table_info in manifest['tables']:
            if table_info['status'] != 'success':
                print(f"\n[SKIP] {table_info['table']} - not exported successfully")
                continue

            try:
                imported = import_table_from_manifest(table_info, input_dir, session, dry_run)
                results[table_info['table']] = {
                    'imported': imported,
                    'expected': table_info['total_rows'],
                    'status': 'success'
                }
            except Exception as e:
                print(f"\n[ERROR] Failed to import {table_info['table']}: {e}")
                import traceback
                traceback.print_exc()
                results[table_info['table']] = {
                    'imported': 0,
                    'expected': table_info['total_rows'],
                    'status': 'error',
                    'error': str(e)
                }

    # Print summary
    print("\n" + "="*80)
    print("IMPORT COMPLETE" if not dry_run else "DRY RUN COMPLETE")
    print("="*80)

    print("\nImport Results:")
    print(f"{'Table':<40} {'Imported':<15} {'Expected':<15} {'Status':<10}")
    print("-" * 80)
    for table_name, result in results.items():
        print(f"{table_name:<40} {result['imported']:>14,} {result['expected']:>14,} {result['status']:<10}")

    total_imported = sum(r['imported'] for r in results.values())
    total_expected = sum(r['expected'] for r in results.values())
    print(f"\n{'TOTAL':<40} {total_imported:>14,} {total_expected:>14,}")


def main():
    parser = argparse.ArgumentParser(description='Import full database from System 1 export')
    parser.add_argument('--input-dir', type=str, required=True,
                       help='Input directory containing parquet files and manifest.json')
    parser.add_argument('--dry-run', action='store_true',
                       help='Test import without making changes')
    parser.add_argument('--clear-existing', action='store_true',
                       help='Clear existing data before import (WARNING: destructive!)')

    args = parser.parse_args()

    import_full_database(
        input_dir=args.input_dir,
        dry_run=args.dry_run,
        clear_existing=args.clear_existing
    )


if __name__ == "__main__":
    main()
