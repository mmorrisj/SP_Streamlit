"""
Monthly Summary Publication Generator

This script generates monthly summary publications from EventSummary records.
It extracts overview and outcome narratives with sourced document IDs for each event.

Usage:
    python generate_monthly_summary_publications.py --country China --start-date 2024-10-01 --end-date 2024-10-31
    python generate_monthly_summary_publications.py --influencers --start-date 2024-10-01 --end-date 2024-10-31
    python generate_monthly_summary_publications.py --country China --month 2024-10
"""

import argparse
import json
import yaml
from datetime import datetime, date
from typing import List, Dict, Optional
from pathlib import Path

from shared.database.database import get_session
from shared.models.models import EventSummary, EventSourceLink, PeriodType, EventStatus, Document


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


def get_monthly_summaries(
    session,
    country: str,
    start_date: date,
    end_date: date
) -> List[Dict]:
    """
    Get all monthly event summaries for a country and time period.

    Returns:
        List of dictionaries containing event summary data with source doc IDs
    """
    # Query monthly EventSummary records
    summaries = session.query(EventSummary).filter(
        EventSummary.initiating_country == country,
        EventSummary.period_type == PeriodType.MONTHLY,
        EventSummary.period_start >= start_date,
        EventSummary.period_end <= end_date,
        EventSummary.status == EventStatus.ACTIVE,
        EventSummary.is_deleted == False
    ).order_by(EventSummary.event_name).all()

    results = []

    for summary in summaries:
        # Extract overview and outcome from narrative_summary JSONB
        # The monthly summaries use different field names than daily/weekly
        narrative = summary.narrative_summary or {}
        overview = narrative.get('monthly_overview', narrative.get('overview', ''))
        outcome = narrative.get('key_outcomes', narrative.get('outcome', ''))
        strategic_significance = narrative.get('strategic_significance', '')

        # Get source document IDs linked to this event summary
        source_links = session.query(EventSourceLink).filter(
            EventSourceLink.event_summary_id == summary.id
        ).all()

        doc_ids = [link.doc_id for link in source_links]

        # Build the result dictionary
        result = {
            'event_summary_id': str(summary.id),
            'event_name': summary.event_name,
            'period_start': summary.period_start.isoformat(),
            'period_end': summary.period_end.isoformat(),
            'overview': overview,
            'outcome': outcome,
            'strategic_significance': strategic_significance,
            'doc_ids': doc_ids,
            'categories': summary.count_by_category,
            'recipients': summary.count_by_recipient,
            'sources': summary.count_by_source,
            'total_documents': summary.total_documents_across_categories
        }

        results.append(result)

    return results


def format_summary_for_publication(summaries: List[Dict], country: str, start_date: date, end_date: date) -> Dict:
    """
    Format summaries into publication-ready structure.

    Returns:
        Dictionary with events organized by category
    """
    # Group by category
    by_category = {}

    for summary in summaries:
        # Get primary category (category with most documents)
        categories = summary['categories']
        if not categories:
            primary_category = 'Uncategorized'
        else:
            primary_category = max(categories.items(), key=lambda x: x[1])[0]

        if primary_category not in by_category:
            by_category[primary_category] = []

        # Format the event with paragraphs and their sources
        event_data = {
            'event_name': summary['event_name'],
            'overview': {
                'text': summary['overview'],
                'source_doc_ids': summary['doc_ids']  # All docs contributed to this event
            },
            'outcome': {
                'text': summary['outcome'],
                'source_doc_ids': summary['doc_ids']  # All docs contributed to this event
            },
            'strategic_significance': {
                'text': summary['strategic_significance'],
                'source_doc_ids': summary['doc_ids']  # All docs contributed to this event
            },
            'metadata': {
                'period': f"{summary['period_start']} to {summary['period_end']}",
                'total_documents': summary['total_documents'],
                'categories': summary['categories'],
                'recipients': summary['recipients'],
                'top_sources': dict(sorted(summary['sources'].items(), key=lambda x: x[1], reverse=True)[:5])
            }
        }

        by_category[primary_category].append(event_data)

    # Create the final publication structure
    publication = {
        'country': country,
        'period_start': start_date.isoformat(),
        'period_end': end_date.isoformat(),
        'generated_at': datetime.utcnow().isoformat(),
        'total_events': len(summaries),
        'events_by_category': by_category
    }

    return publication


def save_publication(publication: Dict, output_dir: str = '_data/publications'):
    """Save publication to JSON file"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    country = publication['country']
    start = publication['period_start']
    end = publication['period_end']

    filename = f"{country}_{start}_{end}_monthly_summary.json"
    filepath = output_path / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(publication, f, indent=2, ensure_ascii=False)

    print(f"[SAVED] {filepath}")
    return filepath


def print_summary_statistics(publication: Dict):
    """Print summary statistics"""
    print("\n" + "="*80)
    print(f"MONTHLY SUMMARY PUBLICATION")
    print("="*80)
    print(f"Country: {publication['country']}")
    print(f"Period: {publication['period_start']} to {publication['period_end']}")
    print(f"Total Events: {publication['total_events']}")
    print(f"\nEvents by Category:")

    for category, events in publication['events_by_category'].items():
        print(f"  {category}: {len(events)} events")

    print("="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Generate monthly summary publications from EventSummary records')
    parser.add_argument('--country', type=str, help='Specific country to process')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--month', type=str, help='Month to process (YYYY-MM), alternative to start/end dates')
    parser.add_argument('--output-dir', type=str, default='_data/publications', help='Output directory for publications')

    args = parser.parse_args()

    # Load config
    config = load_config()

    # Determine countries to process
    if args.influencers:
        countries = config['influencers']
    elif args.country:
        countries = [args.country]
    else:
        print("[ERROR] Must specify either --country or --influencers")
        return

    # Parse dates
    if args.month:
        # Parse YYYY-MM format
        year, month = map(int, args.month.split('-'))
        start_date = date(year, month, 1)
        # Get last day of month
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            from calendar import monthrange
            last_day = monthrange(year, month)[1]
            end_date = date(year, month, last_day)
    else:
        if not args.start_date or not args.end_date:
            print("[ERROR] Must specify either --month or both --start-date and --end-date")
            return
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)

    print(f"\n{'='*80}")
    print(f"GENERATING MONTHLY SUMMARY PUBLICATIONS")
    print(f"{'='*80}")
    print(f"Countries: {', '.join(countries)}")
    print(f"Period: {start_date} to {end_date}")
    print(f"{'='*80}\n")

    # Process each country
    with get_session() as session:
        for country in countries:
            print(f"\nProcessing {country}...")

            # Get monthly summaries
            summaries = get_monthly_summaries(session, country, start_date, end_date)

            if not summaries:
                print(f"  [WARNING] No monthly summaries found for {country}")
                continue

            print(f"  Found {len(summaries)} monthly event summaries")

            # Format for publication
            publication = format_summary_for_publication(summaries, country, start_date, end_date)

            # Save to file
            filepath = save_publication(publication, args.output_dir)

            # Print statistics
            print_summary_statistics(publication)


if __name__ == '__main__':
    main()
