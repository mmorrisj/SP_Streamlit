"""
Show Documents for a Canonical Event

Demonstrates how doc_ids array links to actual documents.
"""

from sqlalchemy import text
from shared.database.database import get_session
import argparse


def show_event_documents(event_name: str, country: str = None):
    """Show all documents for a canonical event via daily_event_mentions."""

    print("=" * 100)
    print(f"DOCUMENTS FOR EVENT: {event_name}")
    print("=" * 100)

    with get_session() as session:
        # First, find the canonical event
        query = """
            SELECT id, canonical_name, initiating_country,
                   first_mention_date, last_mention_date, total_articles
            FROM canonical_events
            WHERE canonical_name = :event_name
        """
        params = {'event_name': event_name}

        if country:
            query += " AND initiating_country = :country"
            params['country'] = country

        event = session.execute(text(query), params).fetchone()

        if not event:
            print(f"\n❌ Event not found: {event_name}")
            return

        event_id, name, init_country, first_date, last_date, total_articles = event

        print(f"\nCanonical Event Info:")
        print(f"  ID: {event_id}")
        print(f"  Name: {name}")
        print(f"  Country: {init_country}")
        print(f"  Date Range: {first_date} to {last_date}")
        print(f"  Total Articles (claimed): {total_articles}")

        # Check for daily_event_mentions
        print(f"\n{'='*100}")
        print("DAILY EVENT MENTIONS (Link to Documents)")
        print('='*100)

        mentions = session.execute(text("""
            SELECT
                mention_date,
                article_count,
                array_length(doc_ids, 1) as doc_count,
                doc_ids
            FROM daily_event_mentions
            WHERE canonical_event_id = :event_id
            ORDER BY mention_date
        """), {'event_id': event_id}).fetchall()

        if not mentions:
            print(f"\n❌ NO DAILY_EVENT_MENTIONS FOUND!")
            print(f"\nThis event has NO doc_ids array - cannot link to documents.")
            print(f"This is why query_master_events.py returns 'Total: 0 documents'")

            print(f"\n{'='*100}")
            print("DIAGNOSIS")
            print('='*100)
            print(f"The canonical_event exists and claims {total_articles} articles,")
            print(f"but there are no daily_event_mentions records to tell us WHICH documents.")
            print(f"\nPossible causes:")
            print(f"  1. llm_deconflict_clusters.py never ran for this event's dates")
            print(f"  2. This canonical_event was created by a different/older script")
            print(f"  3. daily_event_mentions were deleted but canonical_event wasn't")

            print(f"\nTo fix:")
            print(f"  Option 1: Re-run llm_deconflict_clusters.py for date {first_date}")
            print(f"  Option 2: Run backfill_daily_mentions.py to reconstruct from raw_events")
            return

        print(f"\n✅ Found {len(mentions)} daily mentions")
        print(f"\nMentions by Date:")

        total_docs_in_mentions = 0
        all_doc_ids = []

        for mention_date, article_count, doc_count, doc_ids in mentions:
            print(f"\n  {mention_date}:")
            print(f"    Article Count: {article_count}")
            print(f"    Doc IDs Count: {doc_count}")
            print(f"    Doc IDs: {doc_ids[:3] if doc_ids else []}{'...' if doc_ids and len(doc_ids) > 3 else ''}")

            if doc_ids:
                total_docs_in_mentions += len(doc_ids)
                all_doc_ids.extend(doc_ids)

        # Now query the actual documents
        print(f"\n{'='*100}")
        print(f"ACTUAL DOCUMENTS (from doc_ids array)")
        print('='*100)

        if not all_doc_ids:
            print(f"\n❌ No doc_ids in daily_event_mentions!")
            return

        # Remove duplicates
        unique_doc_ids = list(set(all_doc_ids))

        print(f"\nTotal doc_ids in mentions: {len(all_doc_ids)}")
        print(f"Unique doc_ids: {len(unique_doc_ids)}")

        # Query actual documents
        documents = session.execute(text("""
            SELECT
                d.doc_id,
                d.published_date,
                d.headline,
                d.source_name
            FROM documents d
            WHERE d.doc_id = ANY(:doc_ids)
            ORDER BY d.published_date
        """), {'doc_ids': unique_doc_ids}).fetchall()

        print(f"\nDocuments found in database: {len(documents)}")

        if len(documents) < len(unique_doc_ids):
            print(f"⚠️  WARNING: {len(unique_doc_ids) - len(documents)} doc_ids not found in documents table")

        if documents:
            print(f"\nSample Documents (first 10):")
            for i, (doc_id, pub_date, headline, source) in enumerate(documents[:10], 1):
                safe_headline = headline[:60] if headline else 'No headline'
                print(f"\n  {i}. {doc_id}")
                print(f"     Date: {pub_date}")
                print(f"     Source: {source}")
                print(f"     Headline: {safe_headline}")

            if len(documents) > 10:
                print(f"\n  ... and {len(documents) - 10} more documents")

        # Date range from actual documents
        if documents:
            actual_first = min(d[1] for d in documents)
            actual_last = max(d[1] for d in documents)

            print(f"\n{'='*100}")
            print("DATE RANGE COMPARISON")
            print('='*100)
            print(f"Canonical Event Claims:  {first_date} to {last_date}")
            print(f"Actual Documents Range:  {actual_first} to {actual_last}")
            print(f"Span: {(actual_last - actual_first).days + 1} days")


def main():
    parser = argparse.ArgumentParser(
        description="Show how doc_ids array links canonical events to documents"
    )
    parser.add_argument('--event-name', type=str, required=True,
                       help='Exact canonical event name')
    parser.add_argument('--country', type=str, help='Filter by country')

    args = parser.parse_args()

    show_event_documents(args.event_name, args.country)


if __name__ == "__main__":
    main()
