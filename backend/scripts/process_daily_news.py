# backend/scripts/process_daily_news.py

from datetime import date
from backend.database import get_session
from backend.scripts.news_event_tracker import NewsEventTracker
from backend.config import load_yaml_config
from sqlalchemy import select

def process_daily_news(target_date: date = None, country: str = None):
    """
    Main daily processing function.
    Run this once per day after news articles are ingested.

    Args:
        target_date: Date to process. Defaults to today.
        country: Specific country to process. If None, processes all countries.
    """
    if target_date is None:
        target_date = date.today()

    config = load_yaml_config('backend/config.yaml')

    # Determine which countries to process
    if country:
        if country not in config['influencers']:
            raise ValueError(f"Country '{country}' not found in config. Available: {list(config['influencers'].keys())}")
        countries_to_process = [country]
    else:
        countries_to_process = config['influencers'].keys()

    with get_session() as session:
        tracker = NewsEventTracker(session)

        print(f"Processing news for {target_date}...")

        for country_name in countries_to_process:
            print(f"  Processing {country_name}...")

            daily_mentions = tracker.process_daily_articles(
                target_date,
                country_name
            )

            print(f"    Found {len(daily_mentions)} unique events")

        # Update all events' days_since_last_mention
        _update_all_event_staleness(session, target_date)

        session.commit()
        print("✅ Daily processing complete")

def _update_all_event_staleness(session, current_date: date):
    """Update days_since_last_mention for all events."""
    from backend.models import CanonicalEvent
    
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
    parser = argparse.ArgumentParser(description='Process daily news for event tracking')
    parser.add_argument('--date', type=str, help='Date to process (YYYY-MM-DD). Defaults to today.')
    parser.add_argument('--country', type=str, help='Specific country to process. If not specified, processes all countries.')
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else date.today()
    process_daily_news(target_date, country=args.country)