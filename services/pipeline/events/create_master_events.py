"""
Master Event Consolidation Script

This script creates "master events" that track the same real-world event across multiple days/weeks.
It uses embedding similarity to identify related canonical events and links them via master_event_id.

Key concepts:
- Canonical events remain unchanged (daily granularity preserved)
- Master events aggregate information from multiple canonical events
- Uses embedding similarity + temporal proximity to identify related events
- Master event inherits the canonical name from the most prominent child event

Usage:
    # Create master events for specific country and date range
    python create_master_events.py --country "United States" --start-date 2024-08-01 --end-date 2024-08-31

    # Create master events for all influencers
    python create_master_events.py --influencers --start-date 2024-08-01 --end-date 2024-08-31

    # Adjust similarity threshold (default 0.85)
    python create_master_events.py --country "United States" --start-date 2024-08-01 --end-date 2024-08-31 --similarity-threshold 0.80

    # Dry run to see what would be consolidated
    python create_master_events.py --country "United States" --start-date 2024-08-01 --end-date 2024-08-31 --dry-run
"""

import argparse
import yaml
import uuid
import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text

from shared.database.database import get_session
from shared.models.models import CanonicalEvent, DailyEventMention


def load_config(config_path: str = 'shared/config/config.yaml') -> dict:
    """Load configuration from config.yaml"""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return {
                'influencers': config.get('influencers', ['China', 'Russia', 'Iran', 'Turkey', 'United States'])
            }
    except Exception as e:
        print(f"Warning: Could not load config.yaml: {e}")
        return {'influencers': ['China', 'Russia', 'Iran', 'Turkey', 'United States']}


def load_canonical_events(
    session,
    country: str,
    start_date: date,
    end_date: date
) -> List[Dict]:
    """
    Load canonical events for a specific country and date range.

    Returns:
        List of dicts with canonical event info
    """
    result = session.execute(text('''
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.embedding_vector,
            ce.alternative_names,
            ce.first_mention_date,
            ce.last_mention_date,
            ce.total_mention_days,
            ce.total_articles,
            ce.master_event_id,
            ce.primary_categories,
            ce.primary_recipients
        FROM canonical_events ce
        WHERE ce.initiating_country = :country
          AND ce.first_mention_date >= :start_date
          AND ce.first_mention_date <= :end_date
          AND ce.master_event_id IS NULL  -- Only process events not yet linked to a master
        ORDER BY ce.total_articles DESC
    '''), {
        'country': country,
        'start_date': start_date,
        'end_date': end_date
    }).fetchall()

    events = []
    for row in result:
        events.append({
            'id': str(row[0]),
            'canonical_name': row[1],
            'initiating_country': row[2],
            'embedding': np.array(row[3]) if row[3] else None,
            'alternative_names': row[4] or [],
            'first_mention_date': row[5],
            'last_mention_date': row[6],
            'total_mention_days': row[7],
            'total_articles': row[8],
            'master_event_id': row[9],
            'primary_categories': row[10] or {},
            'primary_recipients': row[11] or {}
        })

    return events


def find_temporal_event_groups(
    events: List[Dict],
    similarity_threshold: float = 0.85,
    max_day_gap: int = 7
) -> List[List[int]]:
    """
    Find groups of related events using embedding similarity and temporal proximity.

    Args:
        events: List of event dicts with 'embedding' and 'first_mention_date' fields
        similarity_threshold: Minimum cosine similarity to consider events related
        max_day_gap: Maximum days between events to consider them part of same story

    Returns:
        List of event index groups (each group represents one master event)
    """
    if len(events) == 0:
        return []

    # Filter out events without embeddings
    valid_events = [(i, e) for i, e in enumerate(events) if e['embedding'] is not None]

    if len(valid_events) == 0:
        return []

    valid_indices = [i for i, _ in valid_events]
    embeddings = np.vstack([e['embedding'] for _, e in valid_events])

    # Compute pairwise similarities
    similarities = cosine_similarity(embeddings)

    # Build adjacency matrix with both similarity and temporal constraints
    n = len(valid_events)
    visited = [False] * n
    groups = []

    def is_temporally_close(date1: date, date2: date) -> bool:
        """Check if two dates are within max_day_gap days"""
        return abs((date1 - date2).days) <= max_day_gap

    def dfs(idx, group):
        """Depth-first search to find connected events"""
        visited[idx] = True
        group.append(valid_indices[idx])

        event_i = valid_events[idx][1]

        for j in range(n):
            if not visited[j]:
                event_j = valid_events[j][1]

                # Check both similarity and temporal proximity
                if (similarities[idx][j] >= similarity_threshold and
                    is_temporally_close(event_i['first_mention_date'], event_j['first_mention_date'])):
                    dfs(j, group)

    for i in range(n):
        if not visited[i]:
            group = []
            dfs(i, group)
            if len(group) > 1:  # Only include groups with multiple events
                groups.append(group)

    return groups


def create_master_event(
    session,
    group_events: List[Dict],
    dry_run: bool = False
) -> Optional[str]:
    """
    Create a master event from a group of related canonical events.

    The master event aggregates information from all child events.

    Args:
        session: Database session
        group_events: List of canonical event dicts to consolidate
        dry_run: If True, don't save to database

    Returns:
        Master event ID (UUID string) or None if dry_run
    """
    # Sort by total_articles to find most prominent event
    group_events = sorted(group_events, key=lambda e: e['total_articles'], reverse=True)

    primary_event = group_events[0]

    # Aggregate stats
    total_articles = sum(e['total_articles'] for e in group_events)
    first_mention = min(e['first_mention_date'] for e in group_events)
    last_mention = max(e['last_mention_date'] for e in group_events)
    total_days = sum(e['total_mention_days'] for e in group_events)

    # Merge categories (sum counts)
    merged_categories = defaultdict(int)
    for event in group_events:
        for cat, count in event['primary_categories'].items():
            merged_categories[cat] += count

    # Merge recipients (sum counts)
    merged_recipients = defaultdict(int)
    for event in group_events:
        for recipient, count in event['primary_recipients'].items():
            merged_recipients[recipient] += count

    # Collect alternative names
    all_alternative_names = []
    for event in group_events:
        if event['canonical_name'] != primary_event['canonical_name']:
            all_alternative_names.append(event['canonical_name'])
        all_alternative_names.extend(event['alternative_names'])

    # Remove duplicates
    all_alternative_names = list(dict.fromkeys(all_alternative_names))

    if dry_run:
        return None

    # Create master event
    master_event = CanonicalEvent(
        id=uuid.uuid4(),
        canonical_name=primary_event['canonical_name'],
        initiating_country=primary_event['initiating_country'],
        first_mention_date=first_mention,
        last_mention_date=last_mention,
        total_mention_days=total_days,
        total_articles=total_articles,
        story_phase="developing",  # Master events are by definition multi-day stories
        days_since_last_mention=0,
        unique_sources=[],
        source_count=0,
        peak_mention_date=primary_event['first_mention_date'],  # Use primary event's date
        peak_daily_article_count=primary_event['total_articles'],
        embedding_vector=primary_event['embedding'].tolist() if primary_event['embedding'] is not None else None,
        alternative_names=all_alternative_names,
        primary_categories=dict(merged_categories),
        primary_recipients=dict(merged_recipients),
        master_event_id=None  # Master events don't have a parent
    )

    session.add(master_event)
    session.flush()  # Get the ID

    # Link child events to master
    for event in group_events:
        session.execute(
            text("UPDATE canonical_events SET master_event_id = :master_id WHERE id = :event_id"),
            {'master_id': str(master_event.id), 'event_id': event['id']}
        )

    return str(master_event.id)


def consolidate_country_period(
    session,
    country: str,
    start_date: date,
    end_date: date,
    similarity_threshold: float = 0.85,
    max_day_gap: int = 7,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Consolidate events for a specific country and time period into master events.

    Args:
        session: Database session
        country: Initiating country
        start_date: Start of period
        end_date: End of period
        similarity_threshold: Cosine similarity threshold for merging events
        max_day_gap: Maximum days between events to consider them related
        dry_run: If True, don't save changes to database
        verbose: Print progress

    Returns:
        Dict with statistics
    """
    if verbose:
        print(f"=" * 80)
        print(f"Processing: {country} | {start_date} to {end_date}")
        print(f"=" * 80)

    # Load canonical events for this period
    events = load_canonical_events(session, country, start_date, end_date)

    if len(events) == 0:
        if verbose:
            print(f"  No events found (or all already linked to master events)")
        return {'events': 0, 'groups': 0, 'master_events_created': 0}

    if verbose:
        print(f"  Found {len(events)} canonical events to process")

    # Find related event groups
    groups = find_temporal_event_groups(events, similarity_threshold, max_day_gap)

    if verbose:
        print(f"  Identified {len(groups)} master event groups")

    stats = {
        'events': len(events),
        'groups': len(groups),
        'master_events_created': 0,
        'events_linked': 0
    }

    # Create master events
    for group_idx, group_indices in enumerate(groups):
        group_events = [events[i] for i in group_indices]

        # Sort by total articles
        group_events = sorted(group_events, key=lambda e: e['total_articles'], reverse=True)

        if verbose:
            print(f"\n  Master Event {group_idx + 1}: '{group_events[0]['canonical_name']}'")
            print(f"    Consolidates {len(group_events)} canonical events:")

            for evt in group_events[:5]:  # Show top 5
                date_range = f"{evt['first_mention_date']}"
                if evt['first_mention_date'] != evt['last_mention_date']:
                    date_range += f" to {evt['last_mention_date']}"
                print(f"      - {evt['canonical_name']}")
                print(f"        {date_range}, {evt['total_articles']} articles")

            if len(group_events) > 5:
                print(f"      ... and {len(group_events) - 5} more")

            total_articles = sum(e['total_articles'] for e in group_events)
            date_span = (max(e['last_mention_date'] for e in group_events) -
                        min(e['first_mention_date'] for e in group_events)).days + 1
            print(f"    Total: {total_articles} articles across {date_span} days")

        # Create master event
        master_id = create_master_event(session, group_events, dry_run)

        if master_id:
            stats['master_events_created'] += 1
            stats['events_linked'] += len(group_events)

    if not dry_run:
        session.commit()
        if verbose:
            print(f"\n  ✓ Created {stats['master_events_created']} master events")
    else:
        if verbose:
            print(f"\n  ✓ Dry run complete (no changes saved)")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Master Event Consolidation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries from config.yaml')

    # Date range
    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='End date (YYYY-MM-DD)')

    # Consolidation parameters
    parser.add_argument('--similarity-threshold', type=float, default=0.85,
                       help='Cosine similarity threshold for merging events (0.0-1.0)')
    parser.add_argument('--max-day-gap', type=int, default=7,
                       help='Maximum days between events to consider them related')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Show what would be consolidated without saving')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print detailed progress')

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
        print("Error: Must specify either --country or --influencers")
        return

    print("=" * 80)
    print("MASTER EVENT CONSOLIDATION")
    print("=" * 80)
    print(f"Date range: {start_date} to {end_date}")
    print(f"Countries: {', '.join(countries)}")
    print(f"Similarity threshold: {args.similarity_threshold}")
    print(f"Max day gap: {args.max_day_gap} days")
    if args.dry_run:
        print("DRY RUN MODE - No changes will be saved")
    print("=" * 80)
    print()

    overall_stats = {
        'total_events': 0,
        'total_groups': 0,
        'total_master_events': 0,
        'total_events_linked': 0
    }

    with get_session() as session:
        for country in countries:
            stats = consolidate_country_period(
                session,
                country,
                start_date,
                end_date,
                args.similarity_threshold,
                args.max_day_gap,
                args.dry_run,
                args.verbose
            )

            overall_stats['total_events'] += stats['events']
            overall_stats['total_groups'] += stats['groups']
            overall_stats['total_master_events'] += stats.get('master_events_created', 0)
            overall_stats['total_events_linked'] += stats.get('events_linked', 0)

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Canonical events processed: {overall_stats['total_events']}")
    print(f"Master event groups identified: {overall_stats['total_groups']}")
    print(f"Master events created: {overall_stats['total_master_events']}")
    print(f"Canonical events linked to masters: {overall_stats['total_events_linked']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
