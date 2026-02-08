"""
Check Pipeline Processing Coverage

This script checks which dates have been processed through each stage of the pipeline.
"""

from sqlalchemy import text
from shared.database.database import get_session
import argparse


def check_coverage(country: str):
    """Check pipeline coverage for a country."""

    print("=" * 100)
    print(f"PIPELINE COVERAGE ANALYSIS: {country}")
    print("=" * 100)

    with get_session() as session:
        # Stage 1: Check raw_events
        print("\nSTAGE 1: RAW EVENTS (from event_clusters)")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                COUNT(DISTINCT cluster_date) as dates_with_clusters,
                MIN(cluster_date) as earliest_date,
                MAX(cluster_date) as latest_date,
                COUNT(*) as total_clusters
            FROM event_clusters
            WHERE initiating_country = :country
        """), {'country': country}).fetchone()

        if result and result[0] > 0:
            print(f"   Dates with event clusters: {result[0]:,}")
            print(f"   Date range: {result[1]} to {result[2]}")
            print(f"   Total clusters: {result[3]:,}")
        else:
            print("   ⚠️  NO EVENT CLUSTERS FOUND - batch_cluster_events.py never ran")

        # Stage 2: Check LLM deconflicted clusters
        print("\nSTAGE 2: LLM DECONFLICTED CLUSTERS")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                COUNT(DISTINCT cluster_date) as dates_deconflicted,
                COUNT(*) FILTER (WHERE llm_deconflicted = TRUE) as deconflicted_clusters,
                COUNT(*) FILTER (WHERE llm_deconflicted = FALSE) as pending_clusters
            FROM event_clusters
            WHERE initiating_country = :country
        """), {'country': country}).fetchone()

        if result:
            print(f"   Dates processed: {result[0]:,}")
            print(f"   Deconflicted clusters: {result[1]:,}")
            print(f"   Pending clusters: {result[2]:,}")
            if result[2] > 0:
                print(f"   ⚠️  WARNING: {result[2]:,} clusters not yet deconflicted by LLM")

        # Stage 3: Check canonical_events created
        print("\nSTAGE 3: CANONICAL EVENTS (created from deconflicted clusters)")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                COUNT(*) as total_canonical,
                COUNT(*) FILTER (WHERE master_event_id IS NULL) as masters,
                COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) as children,
                MIN(first_mention_date) as earliest_event,
                MAX(last_mention_date) as latest_event
            FROM canonical_events
            WHERE initiating_country = :country
        """), {'country': country}).fetchone()

        print(f"   Total canonical events: {result[0]:,}")
        print(f"   Masters: {result[1]:,}")
        print(f"   Children: {result[2]:,}")
        if result[3] and result[4]:
            print(f"   Event date range: {result[3]} to {result[4]}")

        # Stage 4: Check daily_event_mentions
        print("\nSTAGE 4: DAILY EVENT MENTIONS (created by llm_deconflict_clusters.py)")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                COUNT(*) as total_mentions,
                COUNT(DISTINCT mention_date) as dates_with_mentions,
                MIN(mention_date) as earliest_mention,
                MAX(mention_date) as latest_mention,
                COUNT(DISTINCT canonical_event_id) as events_with_mentions
            FROM daily_event_mentions dem
            JOIN canonical_events ce ON dem.canonical_event_id = ce.id
            WHERE ce.initiating_country = :country
        """), {'country': country}).fetchone()

        print(f"   Total daily mentions: {result[0]:,}")
        print(f"   Dates with mentions: {result[1]:,}")
        if result[2] and result[3]:
            print(f"   Mention date range: {result[2]} to {result[3]}")
        print(f"   Canonical events with mentions: {result[4]:,}")

        # Calculate coverage
        canonical_total = session.execute(text("""
            SELECT COUNT(*) FROM canonical_events
            WHERE initiating_country = :country
        """), {'country': country}).scalar()

        if canonical_total > 0:
            coverage = (result[4] / canonical_total) * 100
            print(f"   Coverage: {coverage:.1f}% of canonical events have mentions")

            if coverage < 50:
                print("   🔴 CRITICAL: Most canonical events are missing daily_event_mentions!")
                print("   This means llm_deconflict_clusters.py didn't complete for most dates")

        # Stage 5: Check date coverage gap
        print("\nDATE COVERAGE GAP ANALYSIS")
        print("-" * 100)

        # Compare cluster dates vs mention dates
        result = session.execute(text("""
            SELECT
                ec.cluster_date,
                COUNT(DISTINCT ec.cluster_id) as clusters,
                COUNT(DISTINCT ce.id) as canonical_events,
                COUNT(DISTINCT dem.id) as mentions
            FROM event_clusters ec
            LEFT JOIN canonical_events ce ON ce.initiating_country = ec.initiating_country
                AND ce.first_mention_date <= ec.cluster_date
                AND ce.last_mention_date >= ec.cluster_date
            LEFT JOIN daily_event_mentions dem ON dem.mention_date = ec.cluster_date
                AND dem.canonical_event_id = ce.id
            WHERE ec.initiating_country = :country
            GROUP BY ec.cluster_date
            HAVING COUNT(DISTINCT dem.id) = 0
            ORDER BY ec.cluster_date
            LIMIT 10
        """), {'country': country}).fetchall()

        if result:
            print(f"   Found {len(result)} dates with clusters but NO mentions (showing first 10):")
            for row in result:
                print(f"      {row[0]}: {row[1]} clusters, {row[2]} canonical events, {row[3]} mentions")
            print("\n   ⚠️  These dates need to be processed through llm_deconflict_clusters.py")
        else:
            print("   ✅ All cluster dates have corresponding mentions")

        # Stage 6: Check consolidation
        print("\nSTAGE 5-6: CONSOLIDATION & MERGE")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE master_event_id IS NULL AND llm_validated = TRUE) as validated_masters,
                COUNT(*) FILTER (WHERE master_event_id IS NULL AND llm_validated = FALSE) as unvalidated_masters,
                COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) as children
            FROM canonical_events
            WHERE initiating_country = :country
        """), {'country': country}).fetchone()

        print(f"   Validated masters: {result[0]:,}")
        print(f"   Unvalidated masters: {result[1]:,}")
        print(f"   Children (not yet merged): {result[2]:,}")

        if result[2] > 0:
            print("   ⚠️  merge_canonical_events.py hasn't run yet (children still exist)")
        elif result[0] > 0:
            print("   ✅ merge_canonical_events.py completed (children deleted)")

        # Summary
        print("\n" + "=" * 100)
        print("RECOMMENDATIONS")
        print("=" * 100)

        clusters_deconflicted = session.execute(text("""
            SELECT COUNT(*) FROM event_clusters
            WHERE initiating_country = :country AND llm_deconflicted = FALSE
        """), {'country': country}).scalar()

        if clusters_deconflicted > 0:
            print(f"1. Run llm_deconflict_clusters.py for {country} to process {clusters_deconflicted:,} pending clusters")
            print("   This will create canonical_events and daily_event_mentions")

        if result[1] > result[0]:  # More unvalidated than validated
            print(f"2. Run consolidate_all_events.py for {country} (creates master-child links)")
            print(f"3. Run llm_deconflict_canonical_events.py for {country} (validates groups)")
            print(f"4. Run merge_canonical_events.py for {country} (creates multi-day events)")


def main():
    parser = argparse.ArgumentParser(description="Check pipeline processing coverage")
    parser.add_argument('--country', type=str, required=True, help='Country to analyze')

    args = parser.parse_args()

    check_coverage(args.country)


if __name__ == "__main__":
    main()
