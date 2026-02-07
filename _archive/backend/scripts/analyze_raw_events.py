"""
Analyze raw events to understand the consolidation challenge.
"""

from backend.database import get_session
from sqlalchemy import text
import pandas as pd

def analyze_raw_events():
    with get_session() as session:
        print("=" * 80)
        print("RAW EVENTS ANALYSIS")
        print("=" * 80)

        # Total unique events
        total_events = session.execute(
            text("SELECT COUNT(DISTINCT event_name) FROM raw_events")
        ).scalar()
        print(f"\nTotal unique event names: {total_events:,}")

        # Total event-document relationships
        total_relationships = session.execute(
            text("SELECT COUNT(*) FROM raw_events")
        ).scalar()
        print(f"Total event-document relationships: {total_relationships:,}")

        # Events by frequency
        print("\n" + "=" * 80)
        print("TOP 50 MOST FREQUENT EVENTS")
        print("=" * 80)

        top_events = session.execute(text("""
            SELECT
                event_name,
                COUNT(*) as doc_count,
                COUNT(DISTINCT d.initiating_country) as country_count,
                MIN(d.date) as first_seen,
                MAX(d.date) as last_seen
            FROM raw_events re
            JOIN documents d ON re.doc_id = d.doc_id
            GROUP BY event_name
            ORDER BY doc_count DESC
            LIMIT 50
        """)).fetchall()

        for event_name, doc_count, country_count, first_seen, last_seen in top_events:
            print(f"\n{event_name}")
            print(f"  Documents: {doc_count}, Countries: {country_count}")
            print(f"  Period: {first_seen} to {last_seen}")

        # Distribution analysis
        print("\n" + "=" * 80)
        print("FREQUENCY DISTRIBUTION")
        print("=" * 80)

        distribution = session.execute(text("""
            WITH event_counts AS (
                SELECT event_name, COUNT(*) as doc_count
                FROM raw_events
                GROUP BY event_name
            )
            SELECT
                CASE
                    WHEN doc_count = 1 THEN '1 document'
                    WHEN doc_count BETWEEN 2 AND 5 THEN '2-5 documents'
                    WHEN doc_count BETWEEN 6 AND 10 THEN '6-10 documents'
                    WHEN doc_count BETWEEN 11 AND 25 THEN '11-25 documents'
                    WHEN doc_count BETWEEN 26 AND 50 THEN '26-50 documents'
                    WHEN doc_count BETWEEN 51 AND 100 THEN '51-100 documents'
                    WHEN doc_count > 100 THEN '100+ documents'
                END as frequency_bucket,
                COUNT(*) as event_count
            FROM event_counts
            GROUP BY frequency_bucket
            ORDER BY MIN(doc_count)
        """)).fetchall()

        for bucket, count in distribution:
            print(f"{bucket}: {count:,} events")

        # Similar event names (potential duplicates)
        print("\n" + "=" * 80)
        print("POTENTIAL DUPLICATES (Similar Event Names)")
        print("=" * 80)

        similar = session.execute(text("""
            SELECT
                e1.event_name as name1,
                e2.event_name as name2,
                COUNT(DISTINCT e1.doc_id) as count1,
                COUNT(DISTINCT e2.doc_id) as count2
            FROM (SELECT DISTINCT event_name FROM raw_events) e1
            CROSS JOIN (SELECT DISTINCT event_name FROM raw_events) e2
            WHERE e1.event_name < e2.event_name
            AND (
                e1.event_name ILIKE '%' || e2.event_name || '%'
                OR e2.event_name ILIKE '%' || e1.event_name || '%'
                OR SIMILARITY(e1.event_name, e2.event_name) > 0.6
            )
            GROUP BY e1.event_name, e2.event_name
            ORDER BY GREATEST(COUNT(DISTINCT e1.doc_id), COUNT(DISTINCT e2.doc_id)) DESC
            LIMIT 20
        """)).fetchall()

        if similar:
            for name1, name2, count1, count2 in similar:
                print(f"\n'{name1}' ({count1} docs)")
                print(f"  vs")
                print(f"'{name2}' ({count2} docs)")
        else:
            print("(pg_trgm extension needed for similarity analysis)")

        # Events by country
        print("\n" + "=" * 80)
        print("EVENTS BY INITIATING COUNTRY")
        print("=" * 80)

        by_country = session.execute(text("""
            SELECT
                ic.initiating_country,
                COUNT(DISTINCT re.event_name) as unique_events,
                COUNT(*) as total_relationships
            FROM raw_events re
            JOIN initiating_countries ic ON re.doc_id = ic.doc_id
            GROUP BY ic.initiating_country
            ORDER BY unique_events DESC
        """)).fetchall()

        for country, unique_events, total_rels in by_country:
            print(f"{country}: {unique_events:,} unique events, {total_rels:,} total relationships")

if __name__ == "__main__":
    analyze_raw_events()
