#!/usr/bin/env python
"""
Process daily news events over a date range for specific countries.

Usage:
    python -m backend.scripts.process_date_range --start-date 2024-08-01 --end-date 2024-08-31 --country China
    python -m backend.scripts.process_date_range --start-date 2024-08-01 --end-date 2024-08-31  # All countries
"""

from datetime import date, timedelta
from backend.database import get_session
from backend.scripts.news_event_tracker import NewsEventTracker
from backend.scripts.utils import Config

def process_date_range(
    start_date: date,
    end_date: date,
    country: str = None,
    skip_empty: bool = True
):
    """
    Process daily news events over a date range.

    Args:
        start_date: First date to process
        end_date: Last date to process (inclusive)
        country: Specific country to process. If None, processes all countries.
        skip_empty: If True, skips dates with no events (default: True)
    """
    config = Config.from_yaml()

    # Determine which countries to process
    if country:
        if country not in config.influencers:
            raise ValueError(f"Country '{country}' not found in config. Available: {list(config.influencers)}")
        countries_to_process = [country]
    else:
        countries_to_process = config.influencers

    # Validate date range
    if start_date > end_date:
        raise ValueError(f"Start date ({start_date}) must be before or equal to end date ({end_date})")

    # Calculate total days
    total_days = (end_date - start_date).days + 1

    print("=" * 80)
    print(f"PROCESSING DATE RANGE")
    print("=" * 80)
    print(f"Date Range: {start_date} to {end_date} ({total_days} days)")
    print(f"Countries: {', '.join(countries_to_process)}")
    print(f"Skip empty dates: {skip_empty}")
    print("=" * 80)

    # Track statistics
    stats = {
        'total_days_processed': 0,
        'total_events_found': 0,
        'days_with_events': 0,
        'days_without_events': 0,
        'events_by_country': {c: 0 for c in countries_to_process}
    }

    with get_session() as session:
        tracker = NewsEventTracker(session)

        # Iterate through date range
        current_date = start_date
        while current_date <= end_date:
            print(f"\n{'='*80}")
            print(f"Processing: {current_date} ({current_date.strftime('%A')})")
            print(f"Progress: Day {stats['total_days_processed'] + 1}/{total_days}")
            print(f"{'='*80}")

            day_had_events = False

            for country_name in countries_to_process:
                print(f"  Processing {country_name}...")

                try:
                    # Process this date/country combination
                    daily_mentions = tracker.process_daily_articles(
                        current_date,
                        country_name
                    )

                    event_count = len(daily_mentions)

                    if event_count > 0:
                        print(f"    ✅ Found {event_count} unique events")
                        stats['total_events_found'] += event_count
                        stats['events_by_country'][country_name] += event_count
                        day_had_events = True
                    else:
                        print(f"    ⚠️  No events found")

                except Exception as e:
                    print(f"    ❌ Error processing {country_name}: {e}")
                    continue

            # Update stats
            stats['total_days_processed'] += 1
            if day_had_events:
                stats['days_with_events'] += 1
            else:
                stats['days_without_events'] += 1

            # Update event staleness for all events
            if day_had_events:
                _update_all_event_staleness(session, current_date)

            # Commit after each day
            session.commit()

            # Move to next day
            current_date += timedelta(days=1)

    # Print summary
    print("\n" + "=" * 80)
    print("PROCESSING COMPLETE")
    print("=" * 80)
    print(f"Date range: {start_date} to {end_date}")
    print(f"Total days processed: {stats['total_days_processed']}")
    print(f"Days with events: {stats['days_with_events']}")
    print(f"Days without events: {stats['days_without_events']}")
    print(f"Total events found: {stats['total_events_found']}")
    print(f"\nEvents by country:")
    for country_name, count in sorted(stats['events_by_country'].items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            print(f"  {country_name}: {count} events")
    print("=" * 80)

    return stats


def _update_all_event_staleness(session, current_date: date):
    """Update days_since_last_mention for all events."""
    from backend.models import CanonicalEvent
    from sqlalchemy import select

    stmt = select(CanonicalEvent)
    events = session.scalars(stmt).all()

    for event in events:
        days_since = (current_date - event.last_mention_date).days
        event.days_since_last_mention = days_since

        # Update story phase if needed
        if days_since > 30 and event.story_phase != 'dormant':
            event.story_phase = 'dormant'


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description='Process daily news events over a date range',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process China events for August 2024
  python -m backend.scripts.process_date_range --start-date 2024-08-01 --end-date 2024-08-31 --country China

  # Process all countries for a week
  python -m backend.scripts.process_date_range --start-date 2024-08-01 --end-date 2024-08-07

  # Process with all dates (including empty ones)
  python -m backend.scripts.process_date_range --start-date 2024-08-01 --end-date 2024-08-31 --country Iran --no-skip-empty
        """
    )

    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        required=True,
        help='End date (YYYY-MM-DD, inclusive)'
    )
    parser.add_argument(
        '--country',
        type=str,
        help='Specific country to process. If not specified, processes all countries in config.'
    )
    parser.add_argument(
        '--no-skip-empty',
        action='store_false',
        dest='skip_empty',
        help='Process all dates even if they have no events (default: skip empty dates)'
    )

    args = parser.parse_args()

    # Parse dates
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)

    # Run processing
    try:
        stats = process_date_range(
            start_date=start_date,
            end_date=end_date,
            country=args.country,
            skip_empty=args.skip_empty
        )
    except Exception as e:
        print(f"\n❌ Processing failed: {e}")
        raise
