"""
Debug Single Event - Check Database State

For a specific canonical event, show:
- Event_clusters for its date
- Canonical_event record
- Daily_event_mentions (if any)
- What should have been created
"""

from sqlalchemy import text
from shared.database.database import get_session
import argparse


def debug_event(event_name: str, country: str):
    """Debug a single canonical event."""

    print("=" * 100)
    print(f"DEBUG EVENT: {event_name}")
    print("=" * 100)

    with get_session() as session:
        # Find the canonical event
        event = session.execute(text("""
            SELECT id, canonical_name, initiating_country,
                   first_mention_date, last_mention_date,
                   total_articles, total_mention_days,
                   master_event_id, llm_validated
            FROM canonical_events
            WHERE canonical_name = :name
              AND initiating_country = :country
        """), {'name': event_name, 'country': country}).fetchone()

        if not event:
            print(f"\n❌ Canonical event not found!")
            return

        event_id, name, init_country, first_date, last_date, total_articles, mention_days, master_id, validated = event

        print(f"\nCANONICAL EVENT:")
        print(f"  ID: {event_id}")
        print(f"  Name: {name}")
        print(f"  Country: {init_country}")
        print(f"  Date Range: {first_date} to {last_date}")
        print(f"  Total Articles (claimed): {total_articles}")
        print(f"  Total Mention Days (claimed): {mention_days}")
        print(f"  Master Event ID: {master_id}")
        print(f"  LLM Validated: {validated}")

        # Check for daily_event_mentions
        print(f"\n{'='*100}")
        print("DAILY EVENT MENTIONS:")
        print('='*100)

        mentions = session.execute(text("""
            SELECT mention_date, article_count, array_length(doc_ids, 1) as doc_count
            FROM daily_event_mentions
            WHERE canonical_event_id = :event_id
            ORDER BY mention_date
        """), {'event_id': event_id}).fetchall()

        if mentions:
            print(f"\n✅ Found {len(mentions)} daily_event_mentions:")
            for mention_date, article_count, doc_count in mentions:
                print(f"  {mention_date}: {article_count} articles, {doc_count} doc_ids")
        else:
            print(f"\n❌ NO DAILY_EVENT_MENTIONS FOUND!")

        # Check event_clusters for this date
        print(f"\n{'='*100}")
        print(f"EVENT_CLUSTERS for {first_date}:")
        print('='*100)

        clusters = session.execute(text("""
            SELECT cluster_id, cluster_size, batch_number,
                   llm_deconflicted, array_length(doc_ids, 1) as doc_count,
                   array_length(event_names, 1) as name_count
            FROM event_clusters
            WHERE initiating_country = :country
              AND cluster_date = :date
            ORDER BY cluster_id
        """), {'country': country, 'date': first_date}).fetchall()

        if clusters:
            print(f"\n✅ Found {len(clusters)} event_clusters on {first_date}:")
            for cluster_id, size, batch, deconflicted, doc_count, name_count in clusters:
                status = "DECONFLICTED" if deconflicted else "PENDING"
                print(f"  Cluster {cluster_id} (batch {batch}): {size} events, {name_count} names, {doc_count} docs - {status}")
        else:
            print(f"\n⚠️  NO event_clusters found for {first_date}")

        # Check if this event name appears in any cluster's event_names array
        print(f"\n{'='*100}")
        print(f"SEARCH FOR EVENT NAME IN CLUSTERS:")
        print('='*100)

        # This is tricky - need to search for the name in the event_names array
        matching_clusters = session.execute(text("""
            SELECT cluster_id, cluster_date, batch_number,
                   llm_deconflicted, refined_clusters
            FROM event_clusters
            WHERE initiating_country = :country
              AND :event_name = ANY(event_names)
            ORDER BY cluster_date
        """), {'country': country, 'event_name': event_name}).fetchall()

        if matching_clusters:
            print(f"\n✅ Event name found in {len(matching_clusters)} clusters:")
            for cluster_id, cluster_date, batch, deconflicted, refined in matching_clusters:
                status = "DECONFLICTED" if deconflicted else "PENDING"
                print(f"  Cluster {cluster_id} on {cluster_date} (batch {batch}) - {status}")
                if refined:
                    print(f"    Refined clusters: {refined}")
        else:
            print(f"\n❌ Event name NOT found in any event_clusters!")
            print(f"\nThis means the canonical_event was created OUTSIDE the normal pipeline!")

        # DIAGNOSIS
        print(f"\n{'='*100}")
        print("DIAGNOSIS:")
        print('='*100)

        if not mentions and matching_clusters:
            print(f"\n🔴 BUG CONFIRMED:")
            print(f"  - Event_clusters exist for this event and are deconflicted")
            print(f"  - Canonical_event exists")
            print(f"  - But daily_event_mentions were NOT created!")
            print(f"\nThis indicates a bug in llm_deconflict_clusters.py:")
            print(f"  create_canonical_events_from_cluster() created the canonical_event")
            print(f"  but failed to create the daily_event_mention")

        elif not mentions and not matching_clusters:
            print(f"\n🔴 DATA INCONSISTENCY:")
            print(f"  - Canonical_event exists")
            print(f"  - But NO event_clusters contain this event name")
            print(f"  - And NO daily_event_mentions exist")
            print(f"\nThis canonical_event was created OUTSIDE the standard pipeline!")
            print(f"Possibly from:")
            print(f"  1. An old/different script")
            print(f"  2. Manual database insertion")
            print(f"  3. A migration from a different schema")


def main():
    parser = argparse.ArgumentParser(description="Debug a single canonical event")
    parser.add_argument('--event-name', type=str, required=True, help='Exact canonical event name')
    parser.add_argument('--country', type=str, required=True, help='Country')

    args = parser.parse_args()

    debug_event(args.event_name, args.country)


if __name__ == "__main__":
    main()
