"""
Wipe Entity Processing Tables

Mirror of events/wipe_event_tables.py for the entity pipeline. Deletes the
embedding-driven entity outputs while preserving the LLM-extracted raw_entities
(the entity analog of raw_events) and the source documents.

Use this to rebuild the entity layer from scratch — e.g. after an embedding
fix, since entity clustering (cluster_daily_entities.py) groups entity names via
DBSCAN on embeddings, so clusters built on bad vectors must be regenerated.

PRESERVED:
- raw_entities (LLM-extracted entity mentions — NOT embedding-dependent)
- documents / raw_events (source data)

DELETED:
- entity_clusters (DBSCAN clusters on entity-name embeddings)
- canonical_entities (consolidated entities + master/child hierarchy)
- daily_entity_mentions (entity-to-document links)
- entity_relationships (co-occurrence + LLM relationship classification)

Usage:
    # Dry run (show what would be deleted)
    python services/pipeline/entities/wipe_entity_tables.py --dry-run

    # Delete ALL entity processing data
    python services/pipeline/entities/wipe_entity_tables.py --yes

    # Delete for specific country only
    python services/pipeline/entities/wipe_entity_tables.py --country China --yes

    # Delete for specific date range only
    python services/pipeline/entities/wipe_entity_tables.py --start-date 2024-08-01 --end-date 2024-08-31 --yes
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, date
from sqlalchemy import text

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.database.database import get_session


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def _country_date_where(country, start_date, end_date, date_col):
    """Build a WHERE clause + params for a table that has initiating_country
    and a single date column to filter on."""
    clauses = []
    params = {}
    if country:
        clauses.append("initiating_country = :country")
        params['country'] = country
    if start_date and end_date:
        clauses.append(f"{date_col} BETWEEN :start_date AND :end_date")
        params['start_date'] = start_date
        params['end_date'] = end_date
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_table_counts(session, country=None, start_date=None, end_date=None):
    """Row counts for the entity tables under the given scope."""
    counts = {}

    # entity_clusters — filter on cluster_date
    where, params = _country_date_where(country, start_date, end_date, "cluster_date")
    counts['entity_clusters'] = session.execute(
        text(f"SELECT COUNT(*) FROM entity_clusters{where}"), params
    ).scalar()

    # canonical_entities — date overlap on first/last_mention_date
    clauses, params = [], {}
    if country:
        clauses.append("initiating_country = :country")
        params['country'] = country
    if start_date and end_date:
        clauses.append("first_mention_date <= :end_date AND last_mention_date >= :start_date")
        params['start_date'] = start_date
        params['end_date'] = end_date
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    counts['canonical_entities'] = session.execute(
        text(f"SELECT COUNT(*) FROM canonical_entities{where}"), params
    ).scalar()

    # daily_entity_mentions — filter on mention_date
    where, params = _country_date_where(country, start_date, end_date, "mention_date")
    counts['daily_entity_mentions'] = session.execute(
        text(f"SELECT COUNT(*) FROM daily_entity_mentions{where}"), params
    ).scalar()

    # entity_relationships — no country column; scope via canonical_entities
    # when filtering, else count all.
    if country or (start_date and end_date):
        sub_clauses, params = [], {}
        if country:
            sub_clauses.append("initiating_country = :country")
            params['country'] = country
        if start_date and end_date:
            sub_clauses.append("first_mention_date <= :end_date AND last_mention_date >= :start_date")
            params['start_date'] = start_date
            params['end_date'] = end_date
        sub_where = " WHERE " + " AND ".join(sub_clauses)
        counts['entity_relationships'] = session.execute(
            text(
                "SELECT COUNT(*) FROM entity_relationships r WHERE "
                f"r.entity_from_id IN (SELECT id FROM canonical_entities{sub_where}) "
                f"OR r.entity_to_id IN (SELECT id FROM canonical_entities{sub_where})"
            ),
            params,
        ).scalar()
    else:
        counts['entity_relationships'] = session.execute(
            text("SELECT COUNT(*) FROM entity_relationships")
        ).scalar()

    return counts


def wipe_entity_tables(country=None, start_date=None, end_date=None,
                       dry_run=False, skip_confirmation=False):
    """Wipe entity processing tables with optional filtering."""
    print("=" * 100)
    print("WIPE ENTITY PROCESSING TABLES")
    print("=" * 100)

    if dry_run:
        print("DRY RUN MODE - No data will be deleted")
        print("=" * 100)

    with get_session() as session:
        filters = []
        if country:
            filters.append(f"Country: {country}")
        if start_date and end_date:
            filters.append(f"Date Range: {start_date} to {end_date}")
        print(f"\nScope: {' + '.join(filters) if filters else 'ALL DATA'}\n")

        print("Current table sizes:")
        print("-" * 100)
        counts_before = get_table_counts(session, country, start_date, end_date)
        total_rows = 0
        for table, count in counts_before.items():
            print(f"  {table:30s}: {count:>10,} rows")
            total_rows += count
        print("-" * 100)
        print(f"  {'TOTAL':30s}: {total_rows:>10,} rows\n")

        if total_rows == 0:
            print("No data to delete (tables are already empty for this scope)")
            return

        print("WARNING: This will DELETE:")
        print("  - entity_relationships, daily_entity_mentions, canonical_entities, entity_clusters")
        print("PRESERVED:")
        print("  - raw_entities (LLM-extracted mentions), documents, raw_events\n")

        if not dry_run and not skip_confirmation:
            if input("Type 'DELETE' to confirm: ") != 'DELETE':
                print("Aborted by user")
                return
            print()

        # Reusable scoped subquery for canonical_entities (used by relationships)
        canon_sub_clauses, canon_params = [], {}
        if country:
            canon_sub_clauses.append("initiating_country = :country")
            canon_params['country'] = country
        if start_date and end_date:
            canon_sub_clauses.append("first_mention_date <= :end_date AND last_mention_date >= :start_date")
            canon_params['start_date'] = start_date
            canon_params['end_date'] = end_date
        canon_sub_where = (" WHERE " + " AND ".join(canon_sub_clauses)) if canon_sub_clauses else ""

        delete_counts = {}

        # 1. entity_relationships (FK -> canonical_entities; delete before parents)
        print("1. Deleting entity_relationships...")
        if not dry_run:
            if canon_sub_where:
                result = session.execute(
                    text(
                        "DELETE FROM entity_relationships WHERE "
                        f"entity_from_id IN (SELECT id FROM canonical_entities{canon_sub_where}) "
                        f"OR entity_to_id IN (SELECT id FROM canonical_entities{canon_sub_where})"
                    ),
                    canon_params,
                )
            else:
                result = session.execute(text("DELETE FROM entity_relationships"))
            delete_counts['entity_relationships'] = result.rowcount
            print(f"   Deleted {result.rowcount:,} rows")
        else:
            print(f"   Would delete {counts_before['entity_relationships']:,} rows")

        # 2. daily_entity_mentions (FK -> canonical_entities)
        print("2. Deleting daily_entity_mentions...")
        where, params = _country_date_where(country, start_date, end_date, "mention_date")
        if not dry_run:
            result = session.execute(text(f"DELETE FROM daily_entity_mentions{where}"), params)
            delete_counts['daily_entity_mentions'] = result.rowcount
            print(f"   Deleted {result.rowcount:,} rows")
        else:
            print(f"   Would delete {counts_before['daily_entity_mentions']:,} rows")

        # 3. canonical_entities (self-FK master_entity_id: children first, then masters)
        print("3. Deleting canonical_entities...")
        clauses, params = [], {}
        if country:
            clauses.append("initiating_country = :country")
            params['country'] = country
        if start_date and end_date:
            clauses.append("first_mention_date <= :end_date AND last_mention_date >= :start_date")
            params['start_date'] = start_date
            params['end_date'] = end_date
        base_where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        if not dry_run:
            child_where = base_where + (" AND " if base_where else " WHERE ") + "master_entity_id IS NOT NULL"
            child = session.execute(text(f"DELETE FROM canonical_entities{child_where}"), params).rowcount
            master_where = base_where + (" AND " if base_where else " WHERE ") + "master_entity_id IS NULL"
            master = session.execute(text(f"DELETE FROM canonical_entities{master_where}"), params).rowcount
            delete_counts['canonical_entities'] = child + master
            print(f"   Deleted {child:,} child + {master:,} master = {child + master:,} rows")
        else:
            print(f"   Would delete {counts_before['canonical_entities']:,} rows")

        # 4. entity_clusters (source data, no FK)
        print("4. Deleting entity_clusters...")
        where, params = _country_date_where(country, start_date, end_date, "cluster_date")
        if not dry_run:
            result = session.execute(text(f"DELETE FROM entity_clusters{where}"), params)
            delete_counts['entity_clusters'] = result.rowcount
            print(f"   Deleted {result.rowcount:,} rows")
        else:
            print(f"   Would delete {counts_before['entity_clusters']:,} rows")

        print()
        if not dry_run:
            session.commit()
            print("=" * 100)
            print("DELETION COMPLETE")
            print(f"Total rows deleted: {sum(delete_counts.values()):,}")
            print("=" * 100)
            print("\nRemaining table sizes:")
            for table, count in get_table_counts(session, country, start_date, end_date).items():
                print(f"  {table:30s}: {count:>10,} rows")
            print("\nNext: re-run the entity stages via run_ingestion_pipeline.py "
                  "(daily_entity_extraction reuses preserved raw_entities; "
                  "entity_clustering onward rebuild on fixed embeddings).")
        else:
            print("=" * 100)
            print("DRY RUN COMPLETE - No data was deleted")
            print("=" * 100)


def main():
    parser = argparse.ArgumentParser(
        description="Wipe entity processing tables to rebuild the entity pipeline from scratch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--country', help='Delete only data for this country')
    parser.add_argument('--start-date', help='Delete only data from this date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='Delete only data up to this date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt (USE WITH CAUTION)')
    args = parser.parse_args()

    start_date = end_date = None
    if bool(args.start_date) ^ bool(args.end_date):
        print("Error: --start-date and --end-date must be used together")
        sys.exit(1)
    if args.start_date and args.end_date:
        try:
            start_date = parse_date(args.start_date)
            end_date = parse_date(args.end_date)
            if start_date > end_date:
                print("Error: start-date must be before or equal to end-date")
                sys.exit(1)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    try:
        wipe_entity_tables(
            country=args.country,
            start_date=start_date,
            end_date=end_date,
            dry_run=args.dry_run,
            skip_confirmation=args.yes,
        )
    except KeyboardInterrupt:
        print("\n\nAborted by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
