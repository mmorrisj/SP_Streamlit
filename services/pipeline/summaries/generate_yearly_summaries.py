"""
Yearly Summary Generation Script

This script generates yearly summaries by aggregating monthly summaries for master events.
It uses LLM to synthesize monthly summaries into yearly narratives in AP journalism style.

Usage:
    python generate_yearly_summaries.py --country China --start-date 2024-01-01 --end-date 2024-12-31
    python generate_yearly_summaries.py --influencers --start-date 2024-01-01 --end-date 2024-12-31
    python generate_yearly_summaries.py --country China --year 2024
    python generate_yearly_summaries.py --influencers --year 2024 --dry-run
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
from services.pipeline.summaries.summary_prompts import YEARLY_SUMMARY_PROMPT


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


def get_year_ranges(start_date: date, end_date: date) -> List[Tuple[date, date]]:
    """
    Split date range into yearly periods.

    Args:
        start_date: Start date
        end_date: End date

    Returns:
        List of (year_start, year_end) tuples
    """
    ranges = []
    current = date(start_date.year, 1, 1)  # Start at beginning of year

    while current <= end_date:
        # Get last day of year
        year_end = min(date(current.year, 12, 31), end_date)

        if year_end >= start_date:  # Only include years that overlap with our range
            ranges.append((max(current, start_date), year_end))

        current = date(current.year + 1, 1, 1)

    return ranges


def load_monthly_summaries_for_year(
    session,
    country: str,
    year_start: date,
    year_end: date
) -> Dict[str, List[Dict]]:
    """
    Load monthly summaries for a specific country and year, grouped by event_name.
    Only loads summaries for master events (where master_event_id IS NULL).

    Returns:
        Dict mapping event_name to list of monthly summary dicts
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
          AND es.period_type = 'MONTHLY'
          AND es.period_start >= :year_start
          AND es.period_end <= :year_end
          AND ce.master_event_id IS NULL
          AND es.status = 'ACTIVE'
        ORDER BY es.event_name, es.period_start
    '''), {
        'country': country,
        'year_start': year_start,
        'year_end': year_end
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


def generate_yearly_summary(
    session,
    country: str,
    event_name: str,
    year_start: date,
    year_end: date,
    monthly_summaries: List[Dict],
    dry_run: bool = False
) -> Optional[str]:
    """
    Generate a yearly summary for a specific event.

    Returns:
        EventSummary ID if created, None otherwise
    """
    # Check if yearly summary already exists
    existing_summary = session.execute(text('''
        SELECT id FROM event_summaries
        WHERE period_type = 'YEARLY'
          AND period_start = :year_start
          AND period_end = :year_end
          AND initiating_country = :country
          AND event_name = :event_name
        LIMIT 1
    '''), {
        'year_start': year_start,
        'year_end': year_end,
        'country': country,
        'event_name': event_name
    }).fetchone()

    if existing_summary:
        print(f"    [SKIP] Yearly summary already exists: {existing_summary[0]}")
        return str(existing_summary[0]) if not dry_run else None

    # Format monthly summaries for LLM prompt
    monthly_summaries_text = []
    for i, summary in enumerate(monthly_summaries, 1):
        month_str = summary['period_start'].strftime('%B %Y')
        narrative = summary['narrative_summary']

        monthly_summaries_text.append(f"""**Month {i} ({month_str}):**
Monthly Overview: {narrative.get('monthly_overview', 'N/A')}
Key Outcomes: {narrative.get('key_outcomes', 'N/A')}
Strategic Significance: {narrative.get('strategic_significance', 'N/A')}""")

    monthly_summaries_formatted = "\n\n".join(monthly_summaries_text)

    # Build prompt
    year = year_start.year
    prompt = YEARLY_SUMMARY_PROMPT.format(
        country=country,
        year=year,
        event_name=event_name,
        monthly_summaries=monthly_summaries_formatted
    )

    if dry_run:
        print(f"    [DRY RUN] Would generate yearly summary")
        return None

    # Call LLM via FastAPI proxy
    response = gai(
        sys_prompt="You are an experienced journalist writing in Associated Press (AP) style. Synthesize monthly summaries into yearly strategic narratives.",
        user_prompt=prompt,
        model="gpt-4o-mini",
        use_proxy=True
    )

    # Parse JSON response (gai returns dict if successful, string if error)
    if isinstance(response, dict):
        yearly_summary = response
    else:
        try:
            yearly_summary = json.loads(response)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"    [ERROR] Failed to parse LLM response: {e}")
            print(f"    Response: {str(response)[:200]}...")
            return None

    # Validate required fields
    required_fields = ['yearly_overview', 'major_developments', 'annual_outcomes', 'strategic_assessment']
    if not all(field in yearly_summary for field in required_fields):
        print(f"    [ERROR] Missing required fields in LLM response")
        print(f"    Expected: {required_fields}")
        print(f"    Received: {list(yearly_summary.keys())}")
        return None

    # Get first and last observed dates from monthly summaries
    first_observed = min(s['period_start'] for s in monthly_summaries)
    last_observed = max(s['period_end'] for s in monthly_summaries)

    # Create EventSummary record
    event_summary = EventSummary(
        initiating_country=country,
        event_name=event_name,
        period_type=PeriodType.YEARLY,
        period_start=year_start,
        period_end=year_end,
        first_observed_date=first_observed,
        last_observed_date=last_observed,
        narrative_summary=yearly_summary,
        status=EventStatus.ACTIVE
    )

    session.add(event_summary)
    session.flush()  # Get the ID

    # Collect all unique doc_ids from constituent monthly summaries
    doc_ids = set()
    for monthly in monthly_summaries:
        # Query source links for this monthly summary
        monthly_links = session.execute(text('''
            SELECT doc_id FROM event_source_links
            WHERE event_summary_id = :summary_id
        '''), {'summary_id': monthly['summary_id']}).fetchall()

        doc_ids.update(row[0] for row in monthly_links)

    # Create EventSourceLink records for the yearly summary
    if doc_ids:
        for doc_id in doc_ids:
            link = EventSourceLink(
                event_summary_id=event_summary.id,
                doc_id=doc_id
            )
            session.add(link)

        print(f"    [LINKS] Created {len(doc_ids)} EventSourceLink records")
    else:
        print(f"    [WARNING] No source documents found from monthly summaries")

    print(f"    [SAVED] Created yearly summary: {event_summary.id}")
    print(f"    [INFO] Synthesized from {len(monthly_summaries)} monthly summaries")

    return str(event_summary.id)


def process_year(
    session,
    country: str,
    year_start: date,
    year_end: date,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Process all events for a specific year and country.

    Returns:
        Statistics dict
    """
    print(f"\n{'='*80}")
    print(f"Year: {year_start.year} | Country: {country}")
    print(f"{'='*80}")

    # Load monthly summaries grouped by event
    events_map = load_monthly_summaries_for_year(session, country, year_start, year_end)

    if not events_map:
        print(f"  No monthly summaries found for this year")
        return {'events': 0, 'summaries_created': 0}

    print(f"  Found {len(events_map)} master events with monthly summaries")

    summaries_created = 0

    for event_name, monthly_summaries in events_map.items():
        # Only create yearly summary if we have multiple monthly summaries
        # (at least 2 months of activity to warrant a yearly summary)
        if len(monthly_summaries) < 2:
            # Encode event name to handle Unicode characters
            safe_name = event_name.encode('ascii', 'replace').decode('ascii')
            print(f"  [SKIP] {safe_name}: Only {len(monthly_summaries)} monthly summary")
            continue

        # Encode event name to handle Unicode characters
        safe_name = event_name.encode('ascii', 'replace').decode('ascii')
        print(f"\n  Event: {safe_name}")
        print(f"    Monthly summaries: {len(monthly_summaries)} months")

        summary_id = generate_yearly_summary(
            session,
            country,
            event_name,
            year_start,
            year_end,
            monthly_summaries,
            dry_run
        )

        if summary_id:
            summaries_created += 1

    # Commit if not dry run
    if not dry_run and summaries_created > 0:
        session.commit()
        print(f"\n  [COMMITTED] Created {summaries_created} yearly summaries")

    return {
        'events': len(events_map),
        'summaries_created': summaries_created
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate yearly summaries from monthly summaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true',
                       help='Process all influencer countries from config.yaml')

    # Date range options
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--year', type=int, help='Process specific year (e.g., 2024)')
    date_group.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')

    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD), required if using --start-date')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving to database')

    args = parser.parse_args()

    # Parse dates
    if args.year:
        start_date = date(args.year, 1, 1)
        end_date = date(args.year, 12, 31)
    else:
        if not args.end_date:
            print("[ERROR] --end-date is required when using --start-date")
            return
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

    # Get year ranges
    year_ranges = get_year_ranges(start_date, end_date)

    print("="*80)
    print("YEARLY SUMMARY GENERATION")
    print("="*80)
    print(f"Date range: {start_date} to {end_date} ({len(year_ranges)} years)")
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
            for year_start, year_end in year_ranges:
                stats = process_year(session, country, year_start, year_end, args.dry_run)
                overall_stats['total_events'] += stats['events']
                overall_stats['total_summaries_created'] += stats['summaries_created']

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total events processed: {overall_stats['total_events']}")
    print(f"Yearly summaries created: {overall_stats['total_summaries_created']}")
    print("="*80)


if __name__ == "__main__":
    main()
