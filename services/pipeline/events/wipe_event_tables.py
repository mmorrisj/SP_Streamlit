"""
Wipe Event Processing Tables

This script deletes all event processing outputs while preserving the raw_events table.
Use this to restart the event processing pipeline from scratch and avoid conflicting data issues.

PRESERVED:
- raw_events (flattened event data from documents)
- documents (source documents)

DELETED:
- event_clusters (DBSCAN clusters from Stage 1)
- canonical_events (consolidated events from Stage 1-2)
- daily_event_mentions (event-to-document links from Stage 1-2)
- event_summaries (narrative summaries - optional)
- period_summaries (period aggregations - optional)

Usage:
    # Dry run (show what would be deleted)
    python services/pipeline/events/wipe_event_tables.py --dry-run

    # Delete ALL event processing data
    python services/pipeline/events/wipe_event_tables.py

    # Delete for specific country only
    python services/pipeline/events/wipe_event_tables.py --country "United States"

    # Delete for specific date range only
    python services/pipeline/events/wipe_event_tables.py --start-date 2024-08-01 --end-date 2024-08-31

    # Delete for specific country and date range
    python services/pipeline/events/wipe_event_tables.py --country "United States" --start-date 2024-08-01 --end-date 2024-08-31

    # Skip confirmation prompt (USE WITH CAUTION)
    python services/pipeline/events/wipe_event_tables.py --yes
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


def get_table_counts(session, country: str = None, start_date: date = None, end_date: date = None):
    """
    Get row counts for event tables with optional filtering.

    Returns:
        Dict with table names and row counts
    """
    counts = {}

    # Build WHERE clause for filtering
    where_clauses = []
    params = {}

    if country:
        where_clauses.append("initiating_country = :country")
        params['country'] = country

    if start_date and end_date:
        # Different date columns for different tables
        date_filters = {
            'event_clusters': 'cluster_date',
            'canonical_events': 'first_mention_date',  # or last_mention_date
            'daily_event_mentions': 'mention_date'
        }

    # Event clusters
    where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    if start_date and end_date and where_clauses:
        where_clause += " AND cluster_date BETWEEN :start_date AND :end_date"
    elif start_date and end_date:
        where_clause = " WHERE cluster_date BETWEEN :start_date AND :end_date"

    query_params = params.copy()
    if start_date and end_date:
        query_params.update({'start_date': start_date, 'end_date': end_date})

    counts['event_clusters'] = session.execute(
        text(f"SELECT COUNT(*) FROM event_clusters{where_clause}"),
        query_params
    ).scalar()

    # Canonical events
    where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    if start_date and end_date and where_clauses:
        where_clause += " AND first_mention_date <= :end_date AND last_mention_date >= :start_date"
    elif start_date and end_date:
        where_clause = " WHERE first_mention_date <= :end_date AND last_mention_date >= :start_date"

    counts['canonical_events'] = session.execute(
        text(f"SELECT COUNT(*) FROM canonical_events{where_clause}"),
        query_params
    ).scalar()

    # Daily event mentions
    where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    if start_date and end_date and where_clauses:
        where_clause += " AND mention_date BETWEEN :start_date AND :end_date"
    elif start_date and end_date:
        where_clause = " WHERE mention_date BETWEEN :start_date AND :end_date"

    counts['daily_event_mentions'] = session.execute(
        text(f"SELECT COUNT(*) FROM daily_event_mentions{where_clause}"),
        query_params
    ).scalar()

    # Event summaries (no country/date filtering - small table)
    counts['event_summaries'] = session.execute(
        text("SELECT COUNT(*) FROM event_summaries")
    ).scalar()

    # Period summaries (no country/date filtering - small table)
    counts['period_summaries'] = session.execute(
        text("SELECT COUNT(*) FROM period_summaries")
    ).scalar()

    return counts


def wipe_event_tables(
    country: str = None,
    start_date: date = None,
    end_date: date = None,
    dry_run: bool = False,
    skip_confirmation: bool = False
):
    """
    Wipe event processing tables with optional filtering.

    Args:
        country: Optional country filter
        start_date: Optional start date filter
        end_date: Optional end date filter
        dry_run: If True, show what would be deleted without deleting
        skip_confirmation: If True, skip confirmation prompt
    """
    print("=" * 100)
    print("WIPE EVENT PROCESSING TABLES")
    print("=" * 100)

    if dry_run:
        print("🔍 DRY RUN MODE - No data will be deleted")
        print("=" * 100)

    with get_session() as session:
        # Build filter description
        filters = []
        if country:
            filters.append(f"Country: {country}")
        if start_date and end_date:
            filters.append(f"Date Range: {start_date} to {end_date}")

        filter_desc = " + ".join(filters) if filters else "ALL DATA"

        print(f"\nScope: {filter_desc}")
        print()

        # Get current counts
        print("Current table sizes:")
        print("-" * 100)
        counts_before = get_table_counts(session, country, start_date, end_date)

        total_rows = 0
        for table, count in counts_before.items():
            print(f"  {table:30s}: {count:>10,} rows")
            total_rows += count

        print("-" * 100)
        print(f"  {'TOTAL':30s}: {total_rows:>10,} rows")
        print()

        if total_rows == 0:
            print("✅ No data to delete (tables are already empty for this scope)")
            return

        # Warning
        print("⚠️  WARNING: This will DELETE the following:")
        print("-" * 100)
        print("  ❌ event_clusters - Stage 1 clustering results")
        print("  ❌ canonical_events - Consolidated event records")
        print("  ❌ daily_event_mentions - Event-to-document links")
        if counts_before['event_summaries'] > 0:
            print("  ❌ event_summaries - Narrative summaries")
        if counts_before['period_summaries'] > 0:
            print("  ❌ period_summaries - Period aggregations")
        print()
        print("✅ PRESERVED:")
        print("  ✅ raw_events - Flattened event data from documents")
        print("  ✅ documents - Source documents")
        print("-" * 100)
        print()

        # Confirmation
        if not dry_run and not skip_confirmation:
            response = input("⚠️  Are you ABSOLUTELY SURE you want to delete this data? Type 'DELETE' to confirm: ")
            if response != 'DELETE':
                print("❌ Aborted by user")
                return
            print()

        if dry_run:
            print("🔍 DRY RUN - Would delete the following:")
            print()

        # Build WHERE clauses and params
        where_clauses = []
        params = {}

        if country:
            where_clauses.append("initiating_country = :country")
            params['country'] = country

        delete_counts = {}

        # Delete in correct order to respect foreign keys

        # 1. Event summaries (no FKs to other event tables)
        if counts_before['event_summaries'] > 0:
            print("1. Deleting event_summaries...")
            if not dry_run:
                result = session.execute(text("DELETE FROM event_summaries"))
                delete_counts['event_summaries'] = result.rowcount
                print(f"   ✅ Deleted {result.rowcount:,} rows")
            else:
                print(f"   🔍 Would delete {counts_before['event_summaries']:,} rows")

        # 2. Period summaries (no FKs to other event tables)
        if counts_before['period_summaries'] > 0:
            print("2. Deleting period_summaries...")
            if not dry_run:
                result = session.execute(text("DELETE FROM period_summaries"))
                delete_counts['period_summaries'] = result.rowcount
                print(f"   ✅ Deleted {result.rowcount:,} rows")
            else:
                print(f"   🔍 Would delete {counts_before['period_summaries']:,} rows")

        # 3. Daily event mentions (FK to canonical_events)
        print("3. Deleting daily_event_mentions...")
        where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        if start_date and end_date and where_clauses:
            where_clause += " AND mention_date BETWEEN :start_date AND :end_date"
        elif start_date and end_date:
            where_clause = " WHERE mention_date BETWEEN :start_date AND :end_date"

        query_params = params.copy()
        if start_date and end_date:
            query_params.update({'start_date': start_date, 'end_date': end_date})

        if not dry_run:
            result = session.execute(
                text(f"DELETE FROM daily_event_mentions{where_clause}"),
                query_params
            )
            delete_counts['daily_event_mentions'] = result.rowcount
            print(f"   ✅ Deleted {result.rowcount:,} rows")
        else:
            print(f"   🔍 Would delete {counts_before['daily_event_mentions']:,} rows")

        # 4. Canonical events (FK to itself for master_event_id)
        # Delete children first, then masters
        print("4. Deleting canonical_events...")
        where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        if start_date and end_date and where_clauses:
            where_clause += " AND first_mention_date <= :end_date AND last_mention_date >= :start_date"
        elif start_date and end_date:
            where_clause = " WHERE first_mention_date <= :end_date AND last_mention_date >= :start_date"

        if not dry_run:
            # Delete children first
            child_clause = where_clause + (" AND " if where_clause else " WHERE ") + "master_event_id IS NOT NULL"
            result = session.execute(
                text(f"DELETE FROM canonical_events{child_clause}"),
                query_params
            )
            child_count = result.rowcount

            # Delete masters
            master_clause = where_clause + (" AND " if where_clause else " WHERE ") + "master_event_id IS NULL"
            result = session.execute(
                text(f"DELETE FROM canonical_events{master_clause}"),
                query_params
            )
            master_count = result.rowcount

            total_canonical = child_count + master_count
            delete_counts['canonical_events'] = total_canonical
            print(f"   ✅ Deleted {child_count:,} child events")
            print(f"   ✅ Deleted {master_count:,} master events")
            print(f"   ✅ Total: {total_canonical:,} rows")
        else:
            print(f"   🔍 Would delete {counts_before['canonical_events']:,} rows")

        # 5. Event clusters (no FKs but is the source data)
        print("5. Deleting event_clusters...")
        where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        if start_date and end_date and where_clauses:
            where_clause += " AND cluster_date BETWEEN :start_date AND :end_date"
        elif start_date and end_date:
            where_clause = " WHERE cluster_date BETWEEN :start_date AND :end_date"

        if not dry_run:
            result = session.execute(
                text(f"DELETE FROM event_clusters{where_clause}"),
                query_params
            )
            delete_counts['event_clusters'] = result.rowcount
            print(f"   ✅ Deleted {result.rowcount:,} rows")
        else:
            print(f"   🔍 Would delete {counts_before['event_clusters']:,} rows")

        print()

        # Commit changes
        if not dry_run:
            session.commit()
            print("=" * 100)
            print("✅ DELETION COMPLETE")
            print("=" * 100)

            total_deleted = sum(delete_counts.values())
            print(f"Total rows deleted: {total_deleted:,}")
            print()

            # Verify deletion
            print("Remaining table sizes:")
            print("-" * 100)
            counts_after = get_table_counts(session, country, start_date, end_date)
            for table, count in counts_after.items():
                print(f"  {table:30s}: {count:>10,} rows")
            print("-" * 100)
            print()

            print("✅ Event processing tables wiped successfully!")
            print()
            print("Next steps:")
            print("  1. Run batch_cluster_events.py to recreate clusters")
            print("  2. Run llm_deconflict_clusters.py to create canonical events")
            print("  3. Run consolidate_all_events.py to group across dates")
            print("  4. Run llm_deconflict_canonical_events.py to validate groups")
            print("  5. Run merge_canonical_events.py to create multi-day events")
        else:
            print("=" * 100)
            print("🔍 DRY RUN COMPLETE - No data was deleted")
            print("=" * 100)
            print()
            print("To actually delete this data, run without --dry-run flag")


def main():
    parser = argparse.ArgumentParser(
        description="Wipe event processing tables to restart pipeline from scratch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--country',
        help='Delete only data for this country'
    )
    parser.add_argument(
        '--start-date',
        help='Delete only data from this date onwards (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        help='Delete only data up to this date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation prompt (USE WITH CAUTION)'
    )

    args = parser.parse_args()

    # Validate date arguments
    start_date = None
    end_date = None

    if args.start_date and not args.end_date:
        print("Error: --start-date requires --end-date")
        sys.exit(1)

    if args.end_date and not args.start_date:
        print("Error: --end-date requires --start-date")
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

    # Execute wipe
    try:
        wipe_event_tables(
            country=args.country,
            start_date=start_date,
            end_date=end_date,
            dry_run=args.dry_run,
            skip_confirmation=args.yes
        )
    except KeyboardInterrupt:
        print("\n\n❌ Aborted by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
