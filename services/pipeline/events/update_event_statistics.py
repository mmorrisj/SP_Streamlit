"""
Update Canonical Event Statistics

Recalculates summary statistics on canonical_events based on actual
daily_event_mentions data. This should be run after merge_canonical_events.py
to ensure master events have accurate metadata.

Fields updated:
- first_mention_date: MIN(mention_date)
- last_mention_date: MAX(mention_date)
- total_mention_days: COUNT(DISTINCT mention_date)
- total_articles: SUM(article_count)
- peak_mention_date: Date with MAX article_count
- peak_daily_article_count: MAX article_count

Usage:
    python update_event_statistics.py --influencers
    python update_event_statistics.py --country Russia
    python update_event_statistics.py --country Russia --dry-run
"""

import argparse
import yaml
from typing import Dict, List
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


def update_statistics_for_country(
    session,
    country: str,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Update statistics for all canonical events in a country.

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
        print(f"Updating Event Statistics: {country}")
        print('='*80)

    # Get all master events (events that should have aggregated stats)
    # These are events with master_event_id IS NULL
    master_events = session.execute(text('''
        SELECT ce.id, ce.canonical_name,
               ce.first_mention_date as old_first,
               ce.last_mention_date as old_last,
               ce.total_mention_days as old_days,
               ce.total_articles as old_articles
        FROM canonical_events ce
        WHERE ce.initiating_country = :country
          AND ce.master_event_id IS NULL
        ORDER BY ce.canonical_name
    '''), {'country': country}).fetchall()

    if not master_events:
        if verbose:
            print(f"  No master events found for {country}")
        return {'events_checked': 0, 'events_updated': 0}

    if verbose:
        print(f"  Found {len(master_events)} master events to check")

    stats = {
        'events_checked': len(master_events),
        'events_updated': 0,
        'events_with_no_mentions': 0
    }

    for event_id, event_name, old_first, old_last, old_days, old_articles in master_events:
        # Calculate actual statistics from daily_event_mentions
        actual_stats = session.execute(text('''
            SELECT
                MIN(mention_date) as first_date,
                MAX(mention_date) as last_date,
                COUNT(DISTINCT mention_date) as days_count,
                SUM(article_count) as total_articles,
                MAX(article_count) as peak_articles
            FROM daily_event_mentions
            WHERE canonical_event_id = :event_id
        '''), {'event_id': event_id}).fetchone()

        if actual_stats[0] is None:
            # No daily_event_mentions for this event
            stats['events_with_no_mentions'] += 1
            continue

        first_date, last_date, days_count, total_articles, peak_articles = actual_stats

        # Get peak date (date with max article count)
        peak_date_result = session.execute(text('''
            SELECT mention_date
            FROM daily_event_mentions
            WHERE canonical_event_id = :event_id
            ORDER BY article_count DESC
            LIMIT 1
        '''), {'event_id': event_id}).fetchone()
        peak_date = peak_date_result[0] if peak_date_result else None

        # Check if update needed
        needs_update = (
            old_first != first_date or
            old_last != last_date or
            old_days != days_count or
            old_articles != total_articles
        )

        if needs_update:
            stats['events_updated'] += 1

            if verbose:
                safe_name = event_name.encode('ascii', 'replace').decode('ascii')[:50]
                print(f"\n  Updating: {safe_name}")
                print(f"    Date range: {old_first} to {old_last} -> {first_date} to {last_date}")
                print(f"    Days: {old_days} -> {days_count}")
                print(f"    Articles: {old_articles} -> {total_articles}")
                if peak_date:
                    print(f"    Peak date: {peak_date} ({peak_articles} articles)")

            if not dry_run:
                session.execute(text('''
                    UPDATE canonical_events
                    SET first_mention_date = :first_date,
                        last_mention_date = :last_date,
                        total_mention_days = :days_count,
                        total_articles = :total_articles,
                        peak_mention_date = :peak_date,
                        peak_daily_article_count = :peak_articles
                    WHERE id = :event_id
                '''), {
                    'event_id': event_id,
                    'first_date': first_date,
                    'last_date': last_date,
                    'days_count': days_count,
                    'total_articles': total_articles,
                    'peak_date': peak_date,
                    'peak_articles': peak_articles
                })

    # Commit changes
    if not dry_run and stats['events_updated'] > 0:
        session.commit()
        if verbose:
            print(f"\n  [COMMITTED] Updated {stats['events_updated']} events")
    elif dry_run and verbose:
        print(f"\n  [DRY RUN] Would update {stats['events_updated']} events")

    if stats['events_with_no_mentions'] > 0 and verbose:
        print(f"  [WARNING] {stats['events_with_no_mentions']} events have no daily_event_mentions")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Update canonical event statistics from daily_event_mentions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true',
                       help='Process all influencer countries from config.yaml')

    # Options
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be updated without saving to database')
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
    print("UPDATE CANONICAL EVENT STATISTICS")
    print("="*80)
    print("Recalculating summary fields from daily_event_mentions")
    print(f"Countries: {', '.join(countries)}")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    print("="*80)

    overall_stats = {
        'total_checked': 0,
        'total_updated': 0,
        'total_no_mentions': 0
    }

    with get_session() as session:
        for country in countries:
            stats = update_statistics_for_country(
                session,
                country,
                args.dry_run,
                args.verbose
            )

            overall_stats['total_checked'] += stats['events_checked']
            overall_stats['total_updated'] += stats['events_updated']
            overall_stats['total_no_mentions'] += stats.get('events_with_no_mentions', 0)

    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total events checked: {overall_stats['total_checked']}")
    print(f"Events updated: {overall_stats['total_updated']}")
    if overall_stats['total_no_mentions'] > 0:
        print(f"Events with no mentions: {overall_stats['total_no_mentions']}")
    print("="*80)


if __name__ == "__main__":
    main()
