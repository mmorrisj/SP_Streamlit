"""
Find Dates That Need llm_deconflict_clusters.py Processing

Shows which dates have event_clusters but haven't been processed by llm_deconflict_clusters.py
"""

from sqlalchemy import text
from shared.database.database import get_session
import argparse


def find_unprocessed_dates(country: str):
    """Find dates with unprocessed event_clusters."""

    print("=" * 100)
    print(f"UNPROCESSED DATES ANALYSIS: {country}")
    print("=" * 100)

    with get_session() as session:
        # Find dates with event_clusters where llm_deconflicted = FALSE
        unprocessed = session.execute(text("""
            SELECT
                cluster_date,
                COUNT(DISTINCT batch_number) as batches,
                COUNT(*) as clusters,
                COUNT(*) FILTER (WHERE llm_deconflicted = FALSE) as pending_clusters
            FROM event_clusters
            WHERE initiating_country = :country
            GROUP BY cluster_date
            HAVING COUNT(*) FILTER (WHERE llm_deconflicted = FALSE) > 0
            ORDER BY cluster_date
        """), {'country': country}).fetchall()

        if unprocessed:
            print(f"\n❌ Found {len(unprocessed)} dates with unprocessed clusters:\n")

            for cluster_date, batches, total_clusters, pending in unprocessed[:20]:
                print(f"  {cluster_date}: {pending}/{total_clusters} clusters pending ({batches} batches)")

            if len(unprocessed) > 20:
                print(f"\n  ... and {len(unprocessed) - 20} more dates")

            # Get date range
            first_date = unprocessed[0][0]
            last_date = unprocessed[-1][0]

            print(f"\n{'='*100}")
            print("RECOMMENDED ACTION")
            print('='*100)
            print(f"Run llm_deconflict_clusters.py for {country} from {first_date} to {last_date}:")
            print()
            print(f"docker exec -it api-service python services/pipeline/events/llm_deconflict_clusters.py \\")
            print(f"  --country '{country}' --start-date {first_date} --end-date {last_date}")
        else:
            print(f"\n✅ All event_clusters have been deconflicted for {country}")

        # Also check for canonical_events without mentions
        print(f"\n{'='*100}")
        print("ORPHANED CANONICAL EVENTS (events without daily_event_mentions)")
        print('='*100)

        orphaned = session.execute(text("""
            SELECT COUNT(*)
            FROM canonical_events ce
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = ce.id
            WHERE ce.initiating_country = :country
              AND ce.master_event_id IS NULL
              AND dem.id IS NULL
        """), {'country': country}).scalar()

        if orphaned > 0:
            print(f"\n⚠️  WARNING: {orphaned:,} canonical events exist WITHOUT daily_event_mentions")
            print(f"\nThis suggests:")
            print(f"  1. llm_deconflict_clusters.py was interrupted mid-processing")
            print(f"  2. Canonical events were created by a different/older script")
            print(f"  3. Data inconsistency - mentions were deleted but events weren't")

            # Check a sample
            sample = session.execute(text("""
                SELECT
                    ce.canonical_name,
                    ce.first_mention_date,
                    ce.total_articles
                FROM canonical_events ce
                LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = ce.id
                WHERE ce.initiating_country = :country
                  AND ce.master_event_id IS NULL
                  AND dem.id IS NULL
                ORDER BY ce.total_articles DESC
                LIMIT 5
            """), {'country': country}).fetchall()

            print(f"\nTop 5 orphaned events by article count:")
            for name, date, articles in sample:
                safe_name = name.encode('ascii', 'replace').decode('ascii')[:60]
                print(f"  {safe_name}")
                print(f"    Date: {date}, Articles: {articles}")

            print(f"\n🔧 TO FIX:")
            print(f"  These events need daily_event_mentions to be queryable.")
            print(f"  Re-run llm_deconflict_clusters.py for their dates to recreate the mentions.")


def main():
    parser = argparse.ArgumentParser(
        description="Find dates that need llm_deconflict_clusters.py processing"
    )
    parser.add_argument('--country', type=str, required=True, help='Country to analyze')

    args = parser.parse_args()

    find_unprocessed_dates(args.country)


if __name__ == "__main__":
    main()
