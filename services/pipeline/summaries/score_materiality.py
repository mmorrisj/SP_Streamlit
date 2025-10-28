"""
Score materiality of event summaries using LLM assessment.

This script assigns materiality scores (1-10) to event summaries, measuring
the concrete/substantive nature of events versus symbolic/rhetorical gestures.

Usage:
    python score_materiality.py --country China --start-date 2024-08-01 --end-date 2024-09-30
    python score_materiality.py --influencers --start-date 2024-08-01 --end-date 2024-09-30
    python score_materiality.py --country Russia --period-type MONTHLY --dry-run
"""

import argparse
import json
import sys
from datetime import date, datetime
from typing import List, Dict, Optional
from pathlib import Path

from sqlalchemy import text
from shared.database.database import get_session
from shared.utils.utils import Config, gai
from services.pipeline.summaries.summary_prompts import MATERIALITY_SCORE_PROMPT


def load_summaries_to_score(
    session,
    country: str,
    start_date: date,
    end_date: date,
    period_type: str = 'DAILY',
    rescore: bool = False
) -> List[Dict]:
    """
    Load event summaries that need materiality scoring.

    Args:
        session: Database session
        country: Initiating country
        start_date: Start date
        end_date: End date
        period_type: DAILY, WEEKLY, or MONTHLY
        rescore: If True, rescore all events. If False, only score unscored events.

    Returns:
        List of summary dictionaries
    """
    score_filter = "" if rescore else "AND es.material_score IS NULL"

    query = text(f"""
        SELECT
            es.id,
            es.event_name,
            es.initiating_country,
            es.period_type,
            es.period_start,
            es.period_end,
            es.narrative_summary,
            es.count_by_category,
            es.count_by_recipient,
            es.total_documents_across_sources,
            es.material_score
        FROM event_summaries es
        WHERE es.initiating_country = :country
          AND es.period_type = :period_type
          AND es.period_start >= :start_date
          AND es.period_end <= :end_date
          AND es.is_deleted = false
          {score_filter}
        ORDER BY es.period_start DESC, es.event_name
    """)

    result = session.execute(query, {
        'country': country,
        'period_type': period_type,
        'start_date': start_date,
        'end_date': end_date
    }).fetchall()

    summaries = []
    for row in result:
        summaries.append({
            'id': str(row[0]),
            'event_name': row[1],
            'initiating_country': row[2],
            'period_type': row[3],
            'period_start': row[4],
            'period_end': row[5],
            'narrative_summary': row[6],
            'count_by_category': row[7] or {},
            'count_by_recipient': row[8] or {},
            'total_documents': row[9] or 0,
            'material_score': float(row[10]) if row[10] else None
        })

    return summaries


def format_event_summary_for_scoring(summary: Dict) -> str:
    """Format event summary into text for LLM scoring."""
    narrative = summary['narrative_summary']

    # Extract relevant narrative fields based on period type
    if summary['period_type'] == 'DAILY':
        summary_text = f"{narrative.get('overview', '')}\n\n{narrative.get('outcomes', '')}"
    elif summary['period_type'] == 'WEEKLY':
        summary_text = f"{narrative.get('overview', '')}\n\n{narrative.get('outcomes', '')}\n\n{narrative.get('progression', '')}"
    else:  # MONTHLY
        summary_text = f"{narrative.get('monthly_overview', '')}\n\n{narrative.get('key_outcomes', '')}\n\n{narrative.get('strategic_significance', '')}"

    return summary_text.strip()


def score_event_materiality(
    summary: Dict,
    use_proxy: bool = True
) -> Optional[Dict]:
    """
    Score event materiality using LLM.

    Args:
        summary: Event summary dictionary
        use_proxy: Whether to use FastAPI proxy for LLM calls

    Returns:
        Dictionary with 'material_score' and 'justification', or None if failed
    """
    # Format summary for scoring
    event_summary = format_event_summary_for_scoring(summary)

    # Format categories and recipients
    categories_list = list(summary['count_by_category'].keys()) if summary['count_by_category'] else []
    recipients_list = list(summary['count_by_recipient'].keys()) if summary['count_by_recipient'] else []

    categories_str = ', '.join(categories_list[:5]) if categories_list else 'None'
    recipients_str = ', '.join(recipients_list[:5]) if recipients_list else 'None'

    # Create prompt
    prompt = MATERIALITY_SCORE_PROMPT.format(
        country=summary['initiating_country'],
        event_name=summary['event_name'],
        period_type=summary['period_type'],
        period_start=summary['period_start'].strftime('%Y-%m-%d'),
        period_end=summary['period_end'].strftime('%Y-%m-%d'),
        event_summary=event_summary,
        categories=categories_str,
        recipients=recipients_str,
        total_documents=summary['total_documents']
    )

    # Call LLM
    try:
        # System prompt for materiality assessment
        sys_prompt = "You are an expert analyst assessing the materiality of soft power events. You assign scores from 1-10 measuring concrete/substantive nature versus symbolic/rhetorical gestures."

        response = gai(sys_prompt, prompt, use_proxy=use_proxy)

        # Parse response
        if isinstance(response, dict):
            score_data = response
        else:
            try:
                score_data = json.loads(response)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"    [ERROR] Failed to parse LLM response: {e}")
                return None

        # Validate score
        if 'material_score' not in score_data:
            print(f"    [ERROR] No material_score in response")
            return None

        score = float(score_data['material_score'])
        if not (1.0 <= score <= 10.0):
            print(f"    [ERROR] Score out of range: {score}")
            return None

        return {
            'material_score': score,
            'justification': score_data.get('justification', '')
        }

    except Exception as e:
        print(f"    [ERROR] LLM call failed: {e}")
        return None


def update_materiality_score(
    session,
    summary_id: str,
    material_score: float,
    justification: str
):
    """Update event summary with materiality score."""
    query = text("""
        UPDATE event_summaries
        SET material_score = :material_score,
            material_justification = :justification,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :summary_id
    """)

    session.execute(query, {
        'summary_id': summary_id,
        'material_score': material_score,
        'justification': justification
    })


def score_country_summaries(
    country: str,
    start_date: date,
    end_date: date,
    period_type: str = 'DAILY',
    rescore: bool = False,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Score materiality for all event summaries in a country/period.

    Returns:
        Statistics dictionary
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"MATERIALITY SCORING: {country} ({period_type})")
        print(f"{'='*80}")
        print(f"Date range: {start_date} to {end_date}")
        print(f"Rescore existing: {'Yes' if rescore else 'No'}")
        print(f"Dry run: {'Yes' if dry_run else 'No'}")

    with get_session() as session:
        # Load summaries
        summaries = load_summaries_to_score(
            session,
            country,
            start_date,
            end_date,
            period_type,
            rescore
        )

        if not summaries:
            if verbose:
                print(f"\n  [INFO] No summaries found to score")
            return {'total': 0, 'scored': 0, 'failed': 0}

        if verbose:
            print(f"  Found {len(summaries)} summaries to score")

        stats = {
            'total': len(summaries),
            'scored': 0,
            'failed': 0
        }

        # Score each summary
        for i, summary in enumerate(summaries, 1):
            event_name = summary['event_name']
            safe_name = event_name.encode('ascii', 'replace').decode('ascii')

            if verbose:
                existing_score = f" (current: {summary['material_score']:.1f})" if summary['material_score'] else ""
                print(f"\n  [{i}/{len(summaries)}] {safe_name}{existing_score}")

            # Score the event
            if verbose:
                print(f"    [PROXY] Calling LLM for materiality assessment...")

            score_result = score_event_materiality(summary, use_proxy=True)

            if score_result:
                score = score_result['material_score']
                justification = score_result['justification']

                if verbose:
                    print(f"    [SCORE] {score:.1f}/10.0")
                    print(f"    [REASON] {justification[:100]}...")

                if not dry_run:
                    update_materiality_score(
                        session,
                        summary['id'],
                        score,
                        justification
                    )
                    session.commit()
                    if verbose:
                        print(f"    [SAVED] Material score updated")

                stats['scored'] += 1
            else:
                if verbose:
                    print(f"    [FAILED] Could not score this event")
                stats['failed'] += 1

        if verbose:
            print(f"\n{'='*80}")
            print(f"SUMMARY")
            print(f"{'='*80}")
            print(f"  Total summaries: {stats['total']}")
            print(f"  Successfully scored: {stats['scored']}")
            print(f"  Failed: {stats['failed']}")

        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Score materiality of event summaries'
    )

    # Country selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--country', type=str, help='Single country to process')
    group.add_argument('--influencers', action='store_true',
                      help='Process all influencer countries from config')

    # Date range
    parser.add_argument('--start-date', type=str, required=True,
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True,
                       help='End date (YYYY-MM-DD)')

    # Period type
    parser.add_argument('--period-type', type=str, default='DAILY',
                       choices=['DAILY', 'WEEKLY', 'MONTHLY'],
                       help='Period type to score')

    # Options
    parser.add_argument('--rescore', action='store_true',
                       help='Rescore events that already have scores')
    parser.add_argument('--dry-run', action='store_true',
                       help='Test without updating database')
    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    # Get countries to process
    if args.influencers:
        cfg = Config.from_yaml('shared/config/config.yaml')
        countries = cfg.influencers
    else:
        countries = [args.country]

    verbose = not args.quiet

    # Process each country
    total_stats = {'total': 0, 'scored': 0, 'failed': 0}

    for country in countries:
        stats = score_country_summaries(
            country=country,
            start_date=start_date,
            end_date=end_date,
            period_type=args.period_type,
            rescore=args.rescore,
            dry_run=args.dry_run,
            verbose=verbose
        )

        total_stats['total'] += stats['total']
        total_stats['scored'] += stats['scored']
        total_stats['failed'] += stats['failed']

    if len(countries) > 1 and verbose:
        print(f"\n{'='*80}")
        print(f"OVERALL SUMMARY ({len(countries)} countries)")
        print(f"{'='*80}")
        print(f"  Total summaries: {total_stats['total']}")
        print(f"  Successfully scored: {total_stats['scored']}")
        print(f"  Failed: {total_stats['failed']}")


if __name__ == '__main__':
    main()
