"""
Backfill Missing Daily Event Mentions from Documents

This script creates daily_event_mentions for canonical_events that are missing them
by matching event names back to documents and grouping by date.
"""

from sqlalchemy import text
from shared.database.database import get_session
from collections import defaultdict
import argparse


def backfill_daily_mentions(country: str, dry_run: bool = False, verbose: bool = True):
    """
    Create daily_event_mentions for canonical_events that don't have them.

    Strategy:
    1. Find canonical_events without daily_event_mentions
    2. For each event, find matching documents by searching raw_events
    3. Group documents by published_date
    4. Create daily_event_mention records
    """

    print("=" * 100)
    print(f"BACKFILLING DAILY MENTIONS: {country}")
    print("=" * 100)

    with get_session() as session:
        # Find canonical events without mentions
        orphaned_events = session.execute(text("""
            SELECT ce.id, ce.canonical_name, ce.alternative_names
            FROM canonical_events ce
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = ce.id
            WHERE ce.initiating_country = :country
              AND ce.master_event_id IS NULL
              AND dem.id IS NULL
            ORDER BY ce.canonical_name
        """), {'country': country}).fetchall()

        if not orphaned_events:
            print(f"\n✅ No orphaned canonical events found for {country}")
            return {'events_processed': 0, 'mentions_created': 0}

        print(f"\nFound {len(orphaned_events):,} canonical events without daily_event_mentions")

        if dry_run:
            print("\n[DRY RUN MODE] - No changes will be saved\n")

        stats = {
            'events_processed': 0,
            'mentions_created': 0,
            'events_with_no_docs': 0
        }

        for event_id, canonical_name, alternative_names in orphaned_events:
            alternative_names = alternative_names or []
            all_names = [canonical_name] + alternative_names

            if verbose:
                safe_name = canonical_name.encode('ascii', 'replace').decode('ascii')[:60]
                print(f"\nProcessing: {safe_name}")
                print(f"  Searching for documents matching {len(all_names)} name variants...")

            # Find documents matching this event by name
            # Search in raw_events table which has event_name and doc_id
            doc_ids_by_date = defaultdict(list)

            for name in all_names:
                result = session.execute(text("""
                    SELECT DISTINCT
                        re.doc_id,
                        d.published_date
                    FROM raw_events re
                    JOIN documents d ON d.doc_id = re.doc_id
                    WHERE re.initiating_country = :country
                      AND re.event_name = :event_name
                    ORDER BY d.published_date
                """), {'country': country, 'event_name': name}).fetchall()

                for doc_id, pub_date in result:
                    doc_ids_by_date[pub_date].append(doc_id)

            if not doc_ids_by_date:
                if verbose:
                    print(f"  ⚠️  No matching documents found in raw_events")
                stats['events_with_no_docs'] += 1
                continue

            total_docs = sum(len(docs) for docs in doc_ids_by_date.values())
            if verbose:
                print(f"  Found {total_docs} documents across {len(doc_ids_by_date)} dates")

            # Create daily_event_mentions for each date
            for mention_date, doc_ids in doc_ids_by_date.items():
                # Remove duplicates
                doc_ids = list(set(doc_ids))

                if verbose:
                    print(f"    {mention_date}: {len(doc_ids)} documents")

                if not dry_run:
                    # Check if mention already exists (shouldn't, but be safe)
                    existing = session.execute(text("""
                        SELECT id FROM daily_event_mentions
                        WHERE canonical_event_id = :event_id
                          AND mention_date = :mention_date
                    """), {'event_id': event_id, 'mention_date': mention_date}).fetchone()

                    if existing:
                        if verbose:
                            print(f"      [SKIP] Mention already exists")
                        continue

                    # Create new mention
                    session.execute(text("""
                        INSERT INTO daily_event_mentions (
                            canonical_event_id,
                            initiating_country,
                            mention_date,
                            article_count,
                            doc_ids,
                            consolidated_headline,
                            mention_context,
                            news_intensity
                        ) VALUES (
                            :event_id,
                            :country,
                            :mention_date,
                            :article_count,
                            :doc_ids,
                            :canonical_name,
                            'execution',
                            'developing'
                        )
                    """), {
                        'event_id': event_id,
                        'country': country,
                        'mention_date': mention_date,
                        'article_count': len(doc_ids),
                        'doc_ids': doc_ids,
                        'canonical_name': canonical_name
                    })

                    stats['mentions_created'] += 1

            stats['events_processed'] += 1

            # Commit every 10 events
            if not dry_run and stats['events_processed'] % 10 == 0:
                session.commit()
                if verbose:
                    print(f"\n  [CHECKPOINT] Committed progress ({stats['events_processed']} events)")

        # Final commit
        if not dry_run and stats['events_processed'] > 0:
            session.commit()
            print(f"\n[COMMITTED] Final changes")

        # Summary
        print("\n" + "=" * 100)
        print("SUMMARY")
        print("=" * 100)
        print(f"Events processed: {stats['events_processed']:,}")
        print(f"Daily mentions created: {stats['mentions_created']:,}")
        print(f"Events with no matching documents: {stats['events_with_no_docs']:,}")

        if stats['events_with_no_docs'] > 0:
            print(f"\n⚠️  WARNING: {stats['events_with_no_docs']} events couldn't be linked to documents")
            print(f"   This may be due to event names not matching raw_events table")

        return stats


def main():
    parser = argparse.ArgumentParser(
        description="Backfill missing daily_event_mentions from raw_events",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--country', type=str, required=True, help='Country to process')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without saving')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print detailed progress')

    args = parser.parse_args()

    backfill_daily_mentions(args.country, args.dry_run, args.verbose)


if __name__ == "__main__":
    main()
