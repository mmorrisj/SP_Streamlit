"""
Canonical Event Consolidation Script

This script consolidates canonical events by:
1. Grouping events by country and time period
2. Using embedding similarity to identify related events
3. Setting master_event_id to link related events to their primary event

This creates a master event hierarchy where:
- Master events have master_event_id = NULL
- Child events have master_event_id pointing to the master event ID

Usage:
    # Consolidate by month
    python consolidate_canonical_events.py --country China --start-date 2024-08-01 --end-date 2024-09-30 --period month

    # Consolidate all influencer countries
    python consolidate_canonical_events.py --influencers --start-date 2024-08-01 --end-date 2024-09-30 --period month

    # Dry run to see what would be consolidated
    python consolidate_canonical_events.py --country China --start-date 2024-08-01 --end-date 2024-09-30 --period month --dry-run
"""

import argparse
import yaml
import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple
from collections import defaultdict
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text

from shared.database.database import get_session
from shared.models.models import CanonicalEvent


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


def get_date_ranges(start_date: date, end_date: date, period: str) -> List[Tuple[date, date]]:
    """
    Split date range into weekly or monthly periods.

    Args:
        start_date: Start date
        end_date: End date
        period: 'week' or 'month'

    Returns:
        List of (period_start, period_end) tuples
    """
    ranges = []
    current = start_date

    if period == 'week':
        # Align to Monday (start of week)
        current = current - timedelta(days=current.weekday())

        while current <= end_date:
            period_end = min(current + timedelta(days=6), end_date)
            if period_end >= start_date:
                ranges.append((max(current, start_date), period_end))
            current += timedelta(days=7)

    elif period == 'month':
        # Start at beginning of month
        current = date(current.year, current.month, 1)

        while current <= end_date:
            # Get last day of month
            if current.month == 12:
                next_month = date(current.year + 1, 1, 1)
            else:
                next_month = date(current.year, current.month + 1, 1)

            period_end = min(next_month - timedelta(days=1), end_date)
            if period_end >= start_date:
                ranges.append((max(current, start_date), period_end))

            current = next_month

    return ranges


def load_canonical_events_for_period(
    session,
    country: str,
    start_date: date,
    end_date: date
) -> List[Dict]:
    """
    Load canonical events and their mentions for a specific country and date range.
    Only loads events that don't already have a master_event_id set.

    Returns:
        List of dicts with canonical event info plus aggregated mention stats
    """
    result = session.execute(text('''
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.embedding_vector,
            ce.alternative_names,
            ce.master_event_id,
            COUNT(DISTINCT dem.mention_date) as days_mentioned,
            MIN(dem.mention_date) as first_mention,
            MAX(dem.mention_date) as last_mention,
            SUM(dem.article_count) as total_articles,
            ARRAY_AGG(DISTINCT dem.mention_date ORDER BY dem.mention_date) as mention_dates,
            ARRAY_AGG(dem.id) as mention_ids
        FROM canonical_events ce
        JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
        WHERE ce.initiating_country = :country
          AND dem.mention_date >= :start_date
          AND dem.mention_date <= :end_date
          AND ce.master_event_id IS NULL
        GROUP BY ce.id
        ORDER BY total_articles DESC
    '''), {
        'country': country,
        'start_date': start_date,
        'end_date': end_date
    }).fetchall()

    events = []
    for row in result:
        events.append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'embedding': np.array(row[3]),
            'alternative_names': row[4] or [],
            'master_event_id': row[5],
            'days_mentioned': row[6],
            'first_mention': row[7],
            'last_mention': row[8],
            'total_articles': row[9],
            'mention_dates': row[10],
            'mention_ids': row[11]
        })

    return events


def find_similar_events(
    events: List[Dict],
    similarity_threshold: float = 0.85
) -> List[List[int]]:
    """
    Find groups of similar events using embedding cosine similarity.

    Args:
        events: List of event dicts with 'embedding' field
        similarity_threshold: Minimum cosine similarity to consider events related

    Returns:
        List of event index groups (each group is a list of indices into events list)
    """
    if len(events) == 0:
        return []

    # Build embedding matrix
    embeddings = np.vstack([e['embedding'] for e in events])

    # Compute pairwise similarities
    similarities = cosine_similarity(embeddings)

    # Find connected components using similarity threshold
    n = len(events)
    visited = [False] * n
    groups = []

    def dfs(idx, group):
        """Depth-first search to find connected events"""
        visited[idx] = True
        group.append(idx)

        for j in range(n):
            if not visited[j] and similarities[idx][j] >= similarity_threshold:
                dfs(j, group)

    for i in range(n):
        if not visited[i]:
            group = []
            dfs(i, group)
            if len(group) > 1:  # Only include groups with multiple events
                groups.append(group)

    return groups


def consolidate_period(
    session,
    country: str,
    period_start: date,
    period_end: date,
    period_type: str,
    similarity_threshold: float = 0.85,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Consolidate events for a specific country and time period.

    Args:
        session: Database session
        country: Initiating country
        period_start: Start of period
        period_end: End of period
        period_type: 'week' or 'month'
        similarity_threshold: Cosine similarity threshold for merging events
        dry_run: If True, don't save changes to database
        verbose: Print progress

    Returns:
        Dict with statistics
    """
    if verbose:
        print(f"=" * 80)
        print(f"Consolidating: {country} | {period_start} to {period_end} ({period_type})")
        print(f"=" * 80)

    # Load canonical events for this period
    events = load_canonical_events_for_period(session, country, period_start, period_end)

    if len(events) == 0:
        if verbose:
            print(f"  No events found for this period")
        return {'events': 0, 'groups': 0, 'consolidated': 0, 'updated': 0}

    if verbose:
        print(f"  Found {len(events)} canonical events")

    # Find similar event groups
    groups = find_similar_events(events, similarity_threshold)

    if verbose:
        print(f"  Identified {len(groups)} event groups to consolidate")

    stats = {
        'events': len(events),
        'groups': len(groups),
        'consolidated': sum(len(g) for g in groups),
        'updated': 0
    }

    # Process consolidated groups
    for group_idx, group in enumerate(groups):
        # Sort by total articles (most prominent first)
        group_events = sorted([events[i] for i in group], key=lambda e: e['total_articles'], reverse=True)

        # Primary event (most articles) becomes the master
        master_event = group_events[0]
        master_id = master_event['id']

        if verbose:
            # Encode event names to handle Unicode characters
            master_name = master_event['canonical_name'].encode('ascii', 'replace').decode('ascii')
            print(f"\n  Group {group_idx + 1}: {len(group)} related events")
            print(f"    Master Event: {master_name} (ID: {master_id})")
            print(f"      {master_event['days_mentioned']} days, {master_event['total_articles']} articles")
            print(f"      Dates: {master_event['first_mention']} to {master_event['last_mention']}")

        # Update child events to point to master
        if len(group_events) > 1 and not dry_run:
            child_ids = [evt['id'] for evt in group_events[1:]]

            # Update master_event_id for all child events
            session.execute(
                text('''
                    UPDATE canonical_events
                    SET master_event_id = :master_id
                    WHERE id = ANY(:child_ids)
                '''),
                {
                    'master_id': master_id,
                    'child_ids': child_ids
                }
            )

            stats['updated'] += len(child_ids)

            if verbose:
                print(f"    [UPDATED] Linked {len(child_ids)} child events to master")

        elif len(group_events) > 1 and dry_run and verbose:
            print(f"    [DRY RUN] Would link {len(group_events) - 1} child events:")
            for evt in group_events[1:]:
                evt_name = evt['canonical_name'].encode('ascii', 'replace').decode('ascii')
                print(f"      - {evt_name} (ID: {evt['id']})")
                print(f"        {evt['days_mentioned']} days, {evt['total_articles']} articles")

    # Commit changes if not dry run
    if not dry_run and stats['updated'] > 0:
        session.commit()
        if verbose:
            print(f"\n  [COMMITTED] Updated {stats['updated']} canonical events")
    elif dry_run and verbose:
        print(f"\n  [DRY RUN] Would update {stats['consolidated'] - stats['groups']} canonical events")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Canonical Event Consolidation",
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
    parser.add_argument('--period', type=str, choices=['week', 'month'], default='month',
                       help='Consolidation period (week or month)')
    parser.add_argument('--similarity-threshold', type=float, default=0.85,
                       help='Cosine similarity threshold for merging events (0.0-1.0)')

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
        print("[ERROR] Must specify either --country or --influencers")
        return

    # Get date ranges for period
    date_ranges = get_date_ranges(start_date, end_date, args.period)

    print("=" * 80)
    print("CANONICAL EVENT CONSOLIDATION")
    print("=" * 80)
    print(f"Period: {args.period}")
    print(f"Date range: {start_date} to {end_date} ({len(date_ranges)} {args.period}s)")
    print(f"Countries: {', '.join(countries)}")
    print(f"Similarity threshold: {args.similarity_threshold}")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    print("=" * 80)
    print()

    overall_stats = {
        'total_events': 0,
        'total_groups': 0,
        'total_consolidated': 0,
        'total_updated': 0
    }

    with get_session() as session:
        for country in countries:
            for period_start, period_end in date_ranges:
                stats = consolidate_period(
                    session,
                    country,
                    period_start,
                    period_end,
                    args.period,
                    args.similarity_threshold,
                    args.dry_run,
                    args.verbose
                )

                overall_stats['total_events'] += stats['events']
                overall_stats['total_groups'] += stats['groups']
                overall_stats['total_consolidated'] += stats['consolidated']
                overall_stats['total_updated'] += stats['updated']

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total events processed: {overall_stats['total_events']}")
    print(f"Event groups identified: {overall_stats['total_groups']}")
    print(f"Events that can be consolidated: {overall_stats['total_consolidated']}")
    if not args.dry_run:
        print(f"Database records updated: {overall_stats['total_updated']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
