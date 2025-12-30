"""
Stage 2C: Merge Fragmented Canonical Events into Multi-Day Events

Part of the two-stage batch consolidation pipeline for event processing.

PIPELINE CONTEXT:
  - Stage 1: Daily clustering creates canonical events per day (by design)
  - Stage 2A: consolidate_all_events.py groups events via master_event_id hierarchy
  - Stage 2B: llm_deconflict_canonical_events.py validates groupings, picks best names
  - Stage 2C: THIS SCRIPT - Consolidates daily_event_mentions into multi-day events

WHAT THIS SCRIPT DOES:
  1. For each LLM-validated master event (master_event_id IS NULL AND llm_validated = TRUE)
  2. Find all child events for that master (master_event_id = master.id)
  3. Reassign all daily_event_mentions from children to master
  4. Handle date conflicts by merging article counts
  5. Delete the now-empty child canonical events

IMPORTANT: Only processes validated masters to prevent over-consolidation errors from Stage 2A
(Children are never individually validated - validation applies to the entire group via the master)

RESULT:
  - Master events have MULTIPLE days of daily_event_mentions
  - True multi-day event tracking across the dataset
  - Full traceability from master events → daily mentions → source documents

Usage:
    python merge_canonical_events.py --influencers
    python merge_canonical_events.py --country China
    python merge_canonical_events.py --influencers --dry-run

See EVENT_PROCESSING_ARCHITECTURE.md for complete pipeline documentation.
"""

import argparse
import yaml
from typing import Dict
from sqlalchemy import text

from shared.database.database import get_session


def load_config(config_path: str = 'shared/config/config.yaml') -> dict:
    """Load configuration from config.yaml"""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return {
                'influencers': config.get('influencers', ['China', 'Russia', 'Iran', 'Turkey', 'United States'])
            }
    except Exception as e:
        print(f"[WARNING] Could not load config.yaml: {e}")
        return {'influencers': ['China', 'Russia', 'Iran', 'Turkey', 'United States']}


def merge_canonical_events_for_country(
    session,
    country: str,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Merge fragmented canonical events into multi-day events for a specific country.

    Args:
        session: Database session
        country: Initiating country
        dry_run: If True, don't save changes to database
        verbose: Print progress

    Returns:
        Dict with statistics
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Merging Canonical Events: {country}")
        print('='*80)

    # Get all LLM-validated master events for this country
    # IMPORTANT: Only process masters that have been validated by LLM in Stage 2B
    # This ensures we only merge children of validated consolidations
    master_events = session.execute(text('''
        SELECT id, canonical_name
        FROM canonical_events
        WHERE initiating_country = :country
          AND master_event_id IS NULL
          AND llm_validated = TRUE
        ORDER BY canonical_name
    '''), {'country': country}).fetchall()

    if not master_events:
        if verbose:
            print(f"  No master events found for {country}")
        return {'master_events': 0, 'child_events': 0, 'mentions_reassigned': 0, 'events_deleted': 0}

    if verbose:
        print(f"  Found {len(master_events)} master events")

    stats = {
        'master_events': len(master_events),
        'child_events': 0,
        'mentions_reassigned': 0,
        'events_deleted': 0
    }

    # Process each master event
    for master_id, master_name in master_events:
        # Find all child events for this validated master
        # NOTE: We already filtered for validated masters above, so all these children
        # are part of a validated consolidation and safe to merge
        child_events = session.execute(text('''
            SELECT id, canonical_name
            FROM canonical_events
            WHERE master_event_id = :master_id
        '''), {'master_id': master_id}).fetchall()

        if not child_events:
            continue  # No children for this master

        stats['child_events'] += len(child_events)

        if verbose and len(child_events) > 0:
            safe_name = master_name.encode('ascii', 'replace').decode('ascii')[:60]
            print(f"\n  Master: {safe_name}")
            print(f"    Found {len(child_events)} child events to merge")

        # For each child event, reassign its daily_event_mentions to the master
        for child_id, child_name in child_events:
            # Check how many daily_event_mentions this child has
            mention_count = session.execute(text('''
                SELECT COUNT(*) FROM daily_event_mentions
                WHERE canonical_event_id = :child_id
            '''), {'child_id': child_id}).scalar()

            if mention_count == 0:
                continue

            if verbose:
                safe_child = child_name.encode('ascii', 'replace').decode('ascii')[:50]
                print(f"      Merging {mention_count} mentions from: {safe_child}")

            stats['mentions_reassigned'] += mention_count

            if not dry_run:
                # Get all mentions from child
                child_mentions = session.execute(text('''
                    SELECT mention_date, article_count
                    FROM daily_event_mentions
                    WHERE canonical_event_id = :child_id
                '''), {'child_id': child_id}).fetchall()

                for mention_date, article_count in child_mentions:
                    # Check if master already has a mention for this date
                    existing = session.execute(text('''
                        SELECT article_count
                        FROM daily_event_mentions
                        WHERE canonical_event_id = :master_id
                          AND mention_date = :mention_date
                    '''), {'master_id': master_id, 'mention_date': mention_date}).fetchone()

                    if existing:
                        # Master already has mention for this date - merge the counts
                        new_count = existing[0] + article_count
                        session.execute(text('''
                            UPDATE daily_event_mentions
                            SET article_count = :new_count
                            WHERE canonical_event_id = :master_id
                              AND mention_date = :mention_date
                        '''), {'new_count': new_count, 'master_id': master_id, 'mention_date': mention_date})

                        # Delete the child's mention
                        session.execute(text('''
                            DELETE FROM daily_event_mentions
                            WHERE canonical_event_id = :child_id
                              AND mention_date = :mention_date
                        '''), {'child_id': child_id, 'mention_date': mention_date})
                    else:
                        # No conflict - just reassign to master
                        session.execute(text('''
                            UPDATE daily_event_mentions
                            SET canonical_event_id = :master_id
                            WHERE canonical_event_id = :child_id
                              AND mention_date = :mention_date
                        '''), {'master_id': master_id, 'child_id': child_id, 'mention_date': mention_date})

        # Delete all child events (they're now empty)
        if not dry_run and len(child_events) > 0:
            child_ids = [child_id for child_id, _ in child_events]

            # Delete children
            for child_id in child_ids:
                session.execute(text('''
                    DELETE FROM canonical_events
                    WHERE id = :child_id
                '''), {'child_id': child_id})

            stats['events_deleted'] += len(child_ids)

    # Commit changes
    if not dry_run and stats['events_deleted'] > 0:
        session.commit()
        if verbose:
            print(f"\n  [COMMITTED] Reassigned {stats['mentions_reassigned']} mentions")
            print(f"  [COMMITTED] Deleted {stats['events_deleted']} child events")
    elif dry_run and verbose:
        print(f"\n  [DRY RUN] Would reassign {stats['mentions_reassigned']} mentions")
        print(f"  [DRY RUN] Would delete {stats['events_deleted']} child events")

    return stats


def verify_multi_day_events(
    session,
    country: str,
    verbose: bool = True
) -> None:
    """
    Verify that we now have multi-day events after merging.
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Verification: Multi-Day Events for {country}")
        print('='*80)

    # Check for events with multiple days of mentions
    multi_day = session.execute(text('''
        SELECT
            ce.canonical_name,
            COUNT(DISTINCT dem.mention_date) as days,
            MIN(dem.mention_date) as first_date,
            MAX(dem.mention_date) as last_date,
            SUM(dem.article_count) as total_articles
        FROM canonical_events ce
        JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
        WHERE ce.initiating_country = :country
          AND ce.master_event_id IS NULL
        GROUP BY ce.id, ce.canonical_name
        HAVING COUNT(DISTINCT dem.mention_date) > 1
        ORDER BY COUNT(DISTINCT dem.mention_date) DESC
        LIMIT 10
    '''), {'country': country}).fetchall()

    if multi_day:
        print(f"  SUCCESS! Found {len(multi_day)} multi-day events (showing top 10):")
        print()
        for name, days, first, last, articles in multi_day:
            safe_name = name.encode('ascii', 'replace').decode('ascii')[:60]
            print(f"  {safe_name}")
            print(f"    {days} days: {first} to {last} | {articles:,} total articles")
    else:
        print(f"  WARNING: No multi-day events found for {country}")


def main():
    parser = argparse.ArgumentParser(
        description="Merge fragmented canonical events into multi-day events",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true',
                       help='Process all influencer countries from config.yaml')

    # Options
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be merged without saving to database')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Print detailed progress')

    args = parser.parse_args()

    # Get countries to process
    if args.influencers:
        config = load_config()
        countries = config['influencers']
    elif args.country:
        countries = [args.country]
    else:
        print("[ERROR] Must specify either --country or --influencers")
        return

    print("="*80)
    print("MERGE FRAGMENTED CANONICAL EVENTS")
    print("="*80)
    print("TEMPORARY FIX: Merging daily canonical events into multi-day events")
    print()
    print("ROOT CAUSE (needs permanent fix):")
    print("  - news_event_tracker.py temporal linking not working")
    print("  - Creates separate canonical events per day instead of linking")
    print("="*80)
    print(f"Countries: {', '.join(countries)}")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    print("="*80)

    overall_stats = {
        'total_master_events': 0,
        'total_child_events': 0,
        'total_mentions_reassigned': 0,
        'total_events_deleted': 0
    }

    with get_session() as session:
        for country in countries:
            stats = merge_canonical_events_for_country(
                session,
                country,
                args.dry_run,
                args.verbose
            )

            overall_stats['total_master_events'] += stats['master_events']
            overall_stats['total_child_events'] += stats['child_events']
            overall_stats['total_mentions_reassigned'] += stats['mentions_reassigned']
            overall_stats['total_events_deleted'] += stats['events_deleted']

            # Verify results
            if not args.dry_run:
                verify_multi_day_events(session, country, args.verbose)

    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total master events processed: {overall_stats['total_master_events']}")
    print(f"Total child events found: {overall_stats['total_child_events']}")
    print(f"Daily mentions reassigned: {overall_stats['total_mentions_reassigned']}")
    if not args.dry_run:
        print(f"Child events deleted: {overall_stats['total_events_deleted']}")
    print("="*80)


if __name__ == "__main__":
    main()
