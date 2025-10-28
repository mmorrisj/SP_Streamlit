"""
Weekly Summary Generation Script

This script generates weekly summaries by aggregating daily summaries for master events.
It uses LLM to synthesize daily summaries into weekly narratives in AP journalism style.

Usage:
    python generate_weekly_summaries.py --country China --start-date 2024-09-01 --end-date 2024-09-30
    python generate_weekly_summaries.py --influencers --start-date 2024-09-01 --end-date 2024-09-30
    python generate_weekly_summaries.py --country China --start-date 2024-09-01 --end-date 2024-09-30 --dry-run
"""

import argparse
import json
import yaml
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional
from sqlalchemy import text
from uuid import UUID

from shared.database.database import get_session
from shared.models.models import EventSummary, PeriodType, EventStatus, EventSourceLink
from shared.utils.utils import gai
from services.pipeline.summaries.summary_prompts import WEEKLY_SUMMARY_PROMPT


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


def get_week_ranges(start_date: date, end_date: date) -> List[Tuple[date, date]]:
    """
    Split date range into weekly periods (Monday-Sunday).

    Args:
        start_date: Start date
        end_date: End date

    Returns:
        List of (week_start, week_end) tuples
    """
    ranges = []
    current = start_date

    # Align to Monday (start of week)
    current = current - timedelta(days=current.weekday())

    while current <= end_date:
        week_end = min(current + timedelta(days=6), end_date)
        if week_end >= start_date:  # Only include weeks that overlap with our range
            ranges.append((max(current, start_date), week_end))
        current += timedelta(days=7)

    return ranges


def load_daily_summaries_for_week(
    session,
    country: str,
    week_start: date,
    week_end: date
) -> Dict[str, List[Dict]]:
    """
    Load daily summaries for a specific country and week, grouped by event_name.
    Only loads summaries for master events (where master_event_id IS NULL).

    Returns:
        Dict mapping event_name to list of daily summary dicts
    """
    result = session.execute(text('''
        SELECT
            es.id,
            es.event_name,
            es.period_start,
            es.period_end,
            es.narrative_summary,
            ce.id as canonical_event_id
        FROM event_summaries es
        JOIN canonical_events ce ON es.event_name = ce.canonical_name
        WHERE es.initiating_country = :country
          AND es.period_type = 'DAILY'
          AND es.period_start >= :week_start
          AND es.period_end <= :week_end
          AND ce.master_event_id IS NULL
          AND es.status = 'ACTIVE'
        ORDER BY es.event_name, es.period_start
    '''), {
        'country': country,
        'week_start': week_start,
        'week_end': week_end
    }).fetchall()

    # Group by event_name
    events_map = {}
    for row in result:
        event_name = row[1]
        if event_name not in events_map:
            events_map[event_name] = []

        events_map[event_name].append({
            'summary_id': row[0],
            'event_name': row[1],
            'period_start': row[2],
            'period_end': row[3],
            'narrative_summary': row[4],  # Already a dict from JSONB
            'canonical_event_id': row[5]
        })

    return events_map


def generate_weekly_summary(
    session,
    country: str,
    event_name: str,
    week_start: date,
    week_end: date,
    daily_summaries: List[Dict],
    dry_run: bool = False
) -> Optional[str]:
    """
    Generate a weekly summary for a specific event.

    Returns:
        EventSummary ID if created, None otherwise
    """
    # Check if weekly summary already exists
    existing_summary = session.execute(text('''
        SELECT id FROM event_summaries
        WHERE period_type = 'WEEKLY'
          AND period_start = :week_start
          AND period_end = :week_end
          AND initiating_country = :country
          AND event_name = :event_name
        LIMIT 1
    '''), {
        'week_start': week_start,
        'week_end': week_end,
        'country': country,
        'event_name': event_name
    }).fetchone()

    if existing_summary:
        print(f"    [SKIP] Weekly summary already exists: {existing_summary[0]}")
        return str(existing_summary[0]) if not dry_run else None

    # Format daily summaries for LLM prompt
    daily_summaries_text = []
    for i, summary in enumerate(daily_summaries, 1):
        date_str = summary['period_start'].strftime('%Y-%m-%d')
        narrative = summary['narrative_summary']

        daily_summaries_text.append(f"""**Day {i} ({date_str}):**
Overview: {narrative.get('overview', 'N/A')}
Outcomes: {narrative.get('outcomes', 'N/A')}""")

    daily_summaries_formatted = "\n\n".join(daily_summaries_text)

    # Build prompt
    week_str = f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}"
    prompt = WEEKLY_SUMMARY_PROMPT.format(
        country=country,
        week_start=week_start.strftime('%Y-%m-%d'),
        week_end=week_end.strftime('%Y-%m-%d'),
        event_name=event_name,
        daily_summaries=daily_summaries_formatted
    )

    if dry_run:
        print(f"    [DRY RUN] Would generate weekly summary")
        return None

    # Call LLM via FastAPI proxy
    response = gai(
        sys_prompt="You are an experienced journalist writing in Associated Press (AP) style. Synthesize daily summaries into weekly narratives.",
        user_prompt=prompt,
        model="gpt-4o-mini",
        use_proxy=True
    )

    # Parse JSON response (gai returns dict if successful, string if error)
    if isinstance(response, dict):
        weekly_summary = response
    else:
        try:
            weekly_summary = json.loads(response)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"    [ERROR] Failed to parse LLM response: {e}")
            print(f"    Response: {str(response)[:200]}...")
            return None

    # Validate required fields
    required_fields = ['overview', 'outcomes', 'progression']
    if not all(field in weekly_summary for field in required_fields):
        print(f"    [ERROR] Missing required fields in LLM response")
        return None

    # Get first and last observed dates from daily summaries
    first_observed = min(s['period_start'] for s in daily_summaries)
    last_observed = max(s['period_end'] for s in daily_summaries)

    # Create EventSummary record
    event_summary = EventSummary(
        initiating_country=country,
        event_name=event_name,
        period_type=PeriodType.WEEKLY,
        period_start=week_start,
        period_end=week_end,
        first_observed_date=first_observed,
        last_observed_date=last_observed,
        narrative_summary=weekly_summary,
        status=EventStatus.ACTIVE
    )

    session.add(event_summary)
    session.flush()  # Get the ID

    print(f"    [SAVED] Created weekly summary: {event_summary.id}")
    print(f"    [INFO] Synthesized from {len(daily_summaries)} daily summaries")

    return str(event_summary.id)


def process_week(
    session,
    country: str,
    week_start: date,
    week_end: date,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Process all events for a specific week and country.

    Returns:
        Statistics dict
    """
    print(f"\n{'='*80}")
    print(f"Week: {week_start} to {week_end} | Country: {country}")
    print(f"{'='*80}")

    # Load daily summaries grouped by event
    events_map = load_daily_summaries_for_week(session, country, week_start, week_end)

    if not events_map:
        print(f"  No daily summaries found for this week")
        return {'events': 0, 'summaries_created': 0}

    print(f"  Found {len(events_map)} master events with daily summaries")

    summaries_created = 0

    for event_name, daily_summaries in events_map.items():
        # Only create weekly summary if we have multiple daily summaries
        if len(daily_summaries) < 2:
            # Encode event name to handle Unicode characters
            safe_name = event_name.encode('ascii', 'replace').decode('ascii')
            print(f"  [SKIP] {safe_name}: Only {len(daily_summaries)} daily summary")
            continue

        # Encode event name to handle Unicode characters
        safe_name = event_name.encode('ascii', 'replace').decode('ascii')
        print(f"\n  Event: {safe_name}")
        print(f"    Daily summaries: {len(daily_summaries)} days")

        summary_id = generate_weekly_summary(
            session,
            country,
            event_name,
            week_start,
            week_end,
            daily_summaries,
            dry_run
        )

        if summary_id:
            summaries_created += 1

    # Commit if not dry run
    if not dry_run and summaries_created > 0:
        session.commit()
        print(f"\n  [COMMITTED] Created {summaries_created} weekly summaries")

    return {
        'events': len(events_map),
        'summaries_created': summaries_created
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate weekly summaries from daily summaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true',
                       help='Process all influencer countries from config.yaml')

    # Date range
    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='End date (YYYY-MM-DD)')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving to database')

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    # Get countries to process
    if args.influencers:
        config = load_config()
        countries = config['influencers']
    elif args.country:
        countries = [args.country]
    else:
        print("[ERROR] Must specify either --country or --influencers")
        return

    # Get week ranges
    week_ranges = get_week_ranges(start_date, end_date)

    print("="*80)
    print("WEEKLY SUMMARY GENERATION")
    print("="*80)
    print(f"Date range: {start_date} to {end_date} ({len(week_ranges)} weeks)")
    print(f"Countries: {', '.join(countries)}")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    print("="*80)

    overall_stats = {
        'total_events': 0,
        'total_summaries_created': 0
    }

    with get_session() as session:
        for country in countries:
            for week_start, week_end in week_ranges:
                stats = process_week(session, country, week_start, week_end, args.dry_run)
                overall_stats['total_events'] += stats['events']
                overall_stats['total_summaries_created'] += stats['summaries_created']

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total events processed: {overall_stats['total_events']}")
    print(f"Weekly summaries created: {overall_stats['total_summaries_created']}")
    print("="*80)


if __name__ == "__main__":
    main()
