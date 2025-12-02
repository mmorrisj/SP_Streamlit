"""
Backfill count_by_recipient in event_summaries from canonical_events.

Now that canonical_events have been backfilled with primary_recipients,
we need to update the event_summaries that were generated before the backfill.

Usage:
    python services/pipeline/summaries/backfill_event_summary_recipients.py
    python services/pipeline/summaries/backfill_event_summary_recipients.py --dry-run
"""

import sys
import argparse
from sqlalchemy import text

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.database.database import get_session
from shared.models.models import EventSummary, CanonicalEvent


def backfill_event_summaries(dry_run: bool = False):
    """
    Backfill count_by_recipient in event_summaries from canonical_events.

    Args:
        dry_run: If True, show what would be updated without saving
    """

    with get_session() as session:
        # Get event summaries with empty recipients
        summaries = session.query(EventSummary).filter(
            EventSummary.count_by_recipient == {}
        ).all()

        print(f"\n{'=' * 80}")
        print(f"BACKFILLING EVENT SUMMARY RECIPIENTS")
        print(f"{'=' * 80}\n")
        print(f"Found {len(summaries)} event summaries with empty count_by_recipient")

        if dry_run:
            print("DRY RUN MODE - No changes will be saved\n")

        updated_count = 0
        no_canonical_count = 0

        for idx, summary in enumerate(summaries, 1):
            try:
                # Find the master canonical event for this summary
                # Event summaries reference canonical events by name + country + date range
                canonical = session.query(CanonicalEvent).filter(
                    CanonicalEvent.canonical_name == summary.event_name,
                    CanonicalEvent.initiating_country == summary.initiating_country,
                    CanonicalEvent.master_event_id.is_(None),  # Master events only
                    CanonicalEvent.first_mention_date <= summary.period_end,
                    CanonicalEvent.last_mention_date >= summary.period_start
                ).first()

                if not canonical:
                    if idx % 1000 == 0:
                        print(f"  [{idx}/{len(summaries)}] No canonical event found for: {summary.event_name[:50]}")
                    no_canonical_count += 1
                    continue

                # Copy primary_recipients and primary_categories
                if canonical.primary_recipients or canonical.primary_categories:
                    if not dry_run:
                        summary.count_by_recipient = canonical.primary_recipients or {}
                        summary.count_by_category = canonical.primary_categories or {}
                        # Update denormalized counts
                        summary.update_basic_counts()

                    updated_count += 1

                    if idx % 100 == 0 or idx <= 10:
                        recipients_str = ', '.join(list(canonical.primary_recipients.keys())[:3]) if canonical.primary_recipients else 'None'
                        if canonical.primary_recipients and len(canonical.primary_recipients) > 3:
                            recipients_str += f" (+{len(canonical.primary_recipients)-3} more)"

                        print(f"  [{idx}/{len(summaries)}] {summary.initiating_country} → {recipients_str}")
                        print(f"              {summary.event_name[:60]}...")

            except Exception as e:
                print(f"  [{idx}/{len(summaries)}] Error: {e}")
                continue

        # Commit all updates
        if not dry_run:
            session.commit()
            print(f"\nAll changes committed to database")

        # Summary
        print(f"\n{'=' * 80}")
        print(f"BACKFILL COMPLETE")
        print(f"{'=' * 80}")
        print(f"Updated: {updated_count}")
        print(f"No canonical event: {no_canonical_count}")
        print(f"{'=' * 80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill count_by_recipient in event_summaries from canonical_events"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without saving changes'
    )

    args = parser.parse_args()

    backfill_event_summaries(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
