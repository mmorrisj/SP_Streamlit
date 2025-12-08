"""
Score materiality of canonical events using LLM assessment.

This script assigns materiality scores (1-10) to canonical events (master events),
measuring the concrete/substantive nature of events versus symbolic/rhetorical gestures.

This allows tracking the materiality of specific initiatives over their entire lifecycle
across multiple days/weeks of mentions.

Usage:
    python score_canonical_event_materiality.py --country China
    python score_canonical_event_materiality.py --influencers
    python score_canonical_event_materiality.py --country Russia --rescore --dry-run
    python score_canonical_event_materiality.py --influencers --min-days 5
"""

import argparse
import json
import sys
from typing import List, Dict, Optional
from pathlib import Path

# Configure stdout encoding for Unicode support on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from sqlalchemy import text
from shared.database.database import get_session
from shared.utils.utils import Config, gai


# Materiality scoring prompt for canonical events
CANONICAL_EVENT_MATERIALITY_PROMPT = """You are an expert analyst assessing the material impact of soft power events.

**Event:** {event_name}
**Country:** {country}
**Time Period:** {first_mention} to {last_mention} ({total_days} days mentioned)
**Total Articles:** {total_articles}
**Primary Categories:** {categories}
**Primary Recipients:** {recipients}

**Event Description:**
{event_description}

**Key Facts:**
{key_facts}

**YOUR TASK:**
Assign a materiality score from 1.0 to 10.0 measuring the concrete/substantive nature of this event.

**Scoring Scale:**
- 1-3: Symbolic/rhetorical (statements, cultural events with no material commitments)
- 4-6: Mixed symbolic and material (agreements with unclear implementation, capacity building)
- 7-10: Highly material (concrete infrastructure, specific financial commitments, tangible deliverables)

**Consider:**
- Concrete commitments vs. symbolic gestures
- Specific financial amounts vs. vague promises
- Tangible deliverables vs. aspirational statements
- Implementation status vs. announcements only

**Output JSON format:**
{{
    "material_score": 7.5,
    "justification": "Brief explanation of the score"
}}

**Example 1 - Score 2.5:**
Event: Cultural Festival Participation
Description: Country representatives attended international cultural festival, delivered speeches on cultural cooperation.
Justification: "Purely symbolic participation with no concrete commitments or tangible outcomes beyond statements."

**Example 2 - Score 6.0:**
Event: Renewable Energy Cooperation Agreement
Description: Two countries signed MOU on renewable energy cooperation, established working group for future projects.
Justification: "Agreement shows intent but lacks specific projects, timelines, or financial commitments. Mixed symbolic/material."

**Example 3 - Score 9.0:**
Event: Nuclear Power Plant Construction
Description: Construction began on nuclear power plant with $25B confirmed financing, four reactors with 4,800 MW capacity, completion scheduled by 2030.
Justification: "Major infrastructure project with specific financial commitment ($25B), confirmed construction phase, and tangible deliverables (4,800 MW capacity)."

Respond with ONLY the JSON object.
"""


def load_canonical_events_to_score(
    session,
    country: str,
    rescore: bool = False,
    min_days: int = 1
) -> List[Dict]:
    """
    Load master canonical events that need materiality scoring.

    Args:
        session: Database session
        country: Initiating country
        rescore: If True, rescore all events. If False, only score unscored events.
        min_days: Minimum number of days mentioned (default: 1)

    Returns:
        List of canonical event dictionaries
    """
    score_filter = "" if rescore else "AND ce.material_score IS NULL"

    query = text(f"""
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.first_mention_date,
            ce.last_mention_date,
            ce.total_mention_days,
            ce.total_articles,
            ce.consolidated_description,
            ce.key_facts,
            ce.primary_categories,
            ce.primary_recipients,
            ce.material_score
        FROM canonical_events ce
        WHERE ce.initiating_country = :country
          AND ce.master_event_id IS NULL
          AND ce.total_mention_days >= :min_days
          {score_filter}
        ORDER BY ce.total_articles DESC NULLS LAST
    """)

    result = session.execute(query, {
        'country': country,
        'min_days': min_days
    }).fetchall()

    events = []
    for row in result:
        events.append({
            'id': str(row[0]),
            'canonical_name': row[1],
            'initiating_country': row[2],
            'first_mention_date': row[3],
            'last_mention_date': row[4],
            'total_mention_days': row[5] or 0,
            'total_articles': row[6] or 0,
            'consolidated_description': row[7] or '',
            'key_facts': row[8] or {},
            'primary_categories': row[9] or {},
            'primary_recipients': row[10] or {},
            'material_score': float(row[11]) if row[11] else None
        })

    return events


def format_canonical_event_for_scoring(event: Dict) -> Dict[str, str]:
    """Format canonical event data for LLM scoring prompt."""
    # Format categories
    categories = event.get('primary_categories', {})
    if isinstance(categories, dict):
        categories_list = [f"{k} ({v} docs)" for k, v in sorted(categories.items(), key=lambda x: -x[1])[:5]]
        categories_str = ', '.join(categories_list) if categories_list else 'None'
    else:
        categories_str = 'None'

    # Format recipients
    recipients = event.get('primary_recipients', {})
    if isinstance(recipients, dict):
        recipients_list = [f"{k} ({v} docs)" for k, v in sorted(recipients.items(), key=lambda x: -x[1])[:5]]
        recipients_str = ', '.join(recipients_list) if recipients_list else 'None'
    else:
        recipients_str = 'None'

    # Format key facts
    key_facts = event.get('key_facts', {})
    if isinstance(key_facts, dict) and key_facts:
        # Extract most relevant facts
        facts_list = []
        for key, value in list(key_facts.items())[:10]:  # Max 10 facts
            if isinstance(value, list):
                facts_list.append(f"- {key}: {', '.join(str(v) for v in value[:3])}")
            else:
                facts_list.append(f"- {key}: {value}")
        key_facts_str = '\n'.join(facts_list) if facts_list else 'None available'
    else:
        key_facts_str = 'None available'

    return {
        'event_name': event['canonical_name'],
        'country': event['initiating_country'],
        'first_mention': event['first_mention_date'].strftime('%Y-%m-%d') if event['first_mention_date'] else 'N/A',
        'last_mention': event['last_mention_date'].strftime('%Y-%m-%d') if event['last_mention_date'] else 'N/A',
        'total_days': event['total_mention_days'],
        'total_articles': event['total_articles'],
        'event_description': event.get('consolidated_description', 'No description available'),
        'categories': categories_str,
        'recipients': recipients_str,
        'key_facts': key_facts_str
    }


def score_canonical_event_materiality(
    event: Dict,
    use_proxy: bool = True
) -> Optional[Dict]:
    """
    Score canonical event materiality using LLM.

    Args:
        event: Canonical event dictionary
        use_proxy: Whether to use FastAPI proxy for LLM calls

    Returns:
        Dictionary with 'material_score' and 'justification', or None if failed
    """
    # Format event for scoring
    formatted = format_canonical_event_for_scoring(event)

    # Create prompt
    prompt = CANONICAL_EVENT_MATERIALITY_PROMPT.format(**formatted)

    # Call LLM
    try:
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


def update_canonical_event_materiality_score(
    session,
    event_id: str,
    material_score: float,
    justification: str
):
    """Update canonical event with materiality score."""
    query = text("""
        UPDATE canonical_events
        SET material_score = :material_score,
            material_justification = :justification
        WHERE id = :event_id
    """)

    session.execute(query, {
        'event_id': event_id,
        'material_score': material_score,
        'justification': justification
    })


def score_country_canonical_events(
    country: str,
    rescore: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
    min_days: int = 1
) -> Dict[str, int]:
    """
    Score materiality for all canonical events in a country.

    Returns:
        Statistics dictionary
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"CANONICAL EVENT MATERIALITY SCORING: {country}")
        print(f"{'='*80}")
        print(f"Rescore existing: {'Yes' if rescore else 'No'}")
        print(f"Minimum days mentioned: {min_days}")
        print(f"Dry run: {'Yes' if dry_run else 'No'}")

    with get_session() as session:
        # Load events
        events = load_canonical_events_to_score(
            session,
            country,
            rescore,
            min_days
        )

        if not events:
            if verbose:
                print(f"\n  [INFO] No events found to score")
            return {'total': 0, 'scored': 0, 'failed': 0}

        if verbose:
            print(f"  Found {len(events)} events to score")

        stats = {
            'total': len(events),
            'scored': 0,
            'failed': 0
        }

        # Score each event
        for i, event in enumerate(events, 1):
            event_name = event['canonical_name']
            safe_name = event_name.encode('ascii', 'replace').decode('ascii')

            if verbose:
                existing_score = f" (current: {event['material_score']:.1f})" if event['material_score'] else ""
                print(f"\n  [{i}/{len(events)}] {safe_name[:80]}{existing_score}")
                print(f"    Days: {event['total_mention_days']}, Articles: {event['total_articles']}")

            # Score the event
            if verbose:
                print(f"    [PROXY] Calling LLM for materiality assessment...")

            score_result = score_canonical_event_materiality(event, use_proxy=True)

            if score_result:
                score = score_result['material_score']
                justification = score_result['justification']

                if verbose:
                    print(f"    [SCORE] {score:.1f}/10.0")
                    print(f"    [REASON] {justification[:100]}...")

                if not dry_run:
                    update_canonical_event_materiality_score(
                        session,
                        event['id'],
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
            print(f"  Total events: {stats['total']}")
            print(f"  Successfully scored: {stats['scored']}")
            print(f"  Failed: {stats['failed']}")

        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Score materiality of canonical events'
    )

    # Country selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--country', type=str, help='Single country to process')
    group.add_argument('--influencers', action='store_true',
                      help='Process all influencer countries from config')

    # Options
    parser.add_argument('--rescore', action='store_true',
                       help='Rescore events that already have scores')
    parser.add_argument('--dry-run', action='store_true',
                       help='Test without updating database')
    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')
    parser.add_argument('--min-days', type=int, default=1,
                       help='Minimum number of days mentioned (default: 1)')

    args = parser.parse_args()

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
        stats = score_country_canonical_events(
            country=country,
            rescore=args.rescore,
            dry_run=args.dry_run,
            verbose=verbose,
            min_days=args.min_days
        )

        total_stats['total'] += stats['total']
        total_stats['scored'] += stats['scored']
        total_stats['failed'] += stats['failed']

    if len(countries) > 1 and verbose:
        print(f"\n{'='*80}")
        print(f"OVERALL SUMMARY ({len(countries)} countries)")
        print(f"{'='*80}")
        print(f"  Total events: {total_stats['total']}")
        print(f"  Successfully scored: {total_stats['scored']}")
        print(f"  Failed: {total_stats['failed']}")


if __name__ == '__main__':
    main()
