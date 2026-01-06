"""
Backfill primary_recipients and primary_categories for existing canonical_events.

This script populates the previously empty JSONB fields by querying the
recipient_countries and categories tables for documents linked to each event
via daily_event_mentions.

Usage:
    python services/pipeline/events/backfill_canonical_event_recipients.py
    python services/pipeline/events/backfill_canonical_event_recipients.py --dry-run
    python services/pipeline/events/backfill_canonical_event_recipients.py --limit 100
"""

import argparse
import sys
from datetime import datetime
from sqlalchemy import text
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.database.database import get_session
from shared.models.models import CanonicalEvent, DailyEventMention


def backfill_canonical_events(dry_run: bool = False, limit: int = None):
    """
    Backfill primary_recipients and primary_categories for canonical events.

    Args:
        dry_run: If True, show what would be updated without saving
        limit: If specified, only process this many events (for testing)
    """

    with get_session() as session:
        # Get canonical events with empty recipients/categories
        query = text("""
            SELECT id, canonical_name, initiating_country,
                   primary_recipients, primary_categories
            FROM canonical_events
            WHERE (primary_recipients = '{}' OR primary_categories = '{}')
            ORDER BY first_mention_date DESC
        """)

        if limit:
            query = text(str(query) + f" LIMIT {limit}")

        events = session.execute(query).fetchall()

        print(f"\n{'=' * 80}")
        print(f"BACKFILLING CANONICAL EVENT RECIPIENTS & CATEGORIES")
        print(f"{'=' * 80}\n")
        print(f"Found {len(events)} canonical events with empty data")

        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be saved\n")

        updated_count = 0
        skipped_count = 0
        error_count = 0

        for idx, event_row in enumerate(events, 1):
            event_id = event_row[0]
            event_name = event_row[1][:60]  # Truncate for display
            initiating_country = event_row[2]

            try:
                # Get all doc_ids associated with this canonical event
                # via daily_event_mentions (which track all child events too)
                doc_ids_query = text("""
                    SELECT DISTINCT unnest(dem.doc_ids) as doc_id
                    FROM daily_event_mentions dem
                    JOIN canonical_events ce ON dem.canonical_event_id = ce.id
                    WHERE ce.id = :event_id
                       OR ce.master_event_id = :event_id
                """)

                doc_ids_result = session.execute(
                    doc_ids_query,
                    {"event_id": event_id}
                ).fetchall()

                doc_ids = [row[0] for row in doc_ids_result]

                if not doc_ids:
                    if idx % 100 == 0:
                        print(f"  [{idx}/{len(events)}] ⏭️  No documents for event {event_id}")
                    skipped_count += 1
                    continue

                # Query recipient countries
                recipients_query = text("""
                    SELECT rc.recipient_country, COUNT(*) as count
                    FROM recipient_countries rc
                    WHERE rc.doc_id = ANY(:doc_ids)
                    GROUP BY rc.recipient_country
                """)

                recipients_result = session.execute(
                    recipients_query,
                    {"doc_ids": doc_ids}
                ).fetchall()

                primary_recipients = {row[0]: row[1] for row in recipients_result}

                # Query categories
                categories_query = text("""
                    SELECT c.category, COUNT(*) as count
                    FROM categories c
                    WHERE c.doc_id = ANY(:doc_ids)
                    GROUP BY c.category
                """)

                categories_result = session.execute(
                    categories_query,
                    {"doc_ids": doc_ids}
                ).fetchall()

                primary_categories = {row[0]: row[1] for row in categories_result}

                # Update the event using ORM
                if not dry_run:
                    event_obj = session.get(CanonicalEvent, event_id)
                    if event_obj:
                        event_obj.primary_recipients = primary_recipients
                        event_obj.primary_categories = primary_categories

                updated_count += 1

                # Print progress every 100 events
                if idx % 100 == 0 or idx <= 10:
                    recipients_str = ', '.join(list(primary_recipients.keys())[:3])
                    if len(primary_recipients) > 3:
                        recipients_str += f" (+{len(primary_recipients)-3} more)"

                    print(f"  [{idx}/{len(events)}] ✅ {initiating_country} → {recipients_str}")
                    print(f"              {event_name}...")
                    print(f"              {len(doc_ids)} docs, {len(primary_recipients)} recipients, {len(primary_categories)} categories")

            except Exception as e:
                print(f"  [{idx}/{len(events)}] ❌ Error processing event {event_id}: {e}")
                error_count += 1
                continue

        # Commit all updates
        if not dry_run:
            session.commit()
            print(f"\n✅ All changes committed to database")

        # Summary
        print(f"\n{'=' * 80}")
        print(f"BACKFILL COMPLETE")
        print(f"{'=' * 80}")
        print(f"✅ Updated: {updated_count}")
        print(f"⏭️  Skipped (no docs): {skipped_count}")
        print(f"❌ Errors: {error_count}")
        print(f"{'=' * 80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill primary_recipients and primary_categories for canonical events"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without saving changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Only process this many events (for testing)'
    )

    args = parser.parse_args()

    backfill_canonical_events(
        dry_run=args.dry_run,
        limit=args.limit
    )


if __name__ == "__main__":
    main()
