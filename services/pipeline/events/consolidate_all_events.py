"""
Stage 2A: Comprehensive Canonical Event Consolidation

Part of the two-stage batch consolidation pipeline for event processing.

This script consolidates ALL canonical events by:
1. Loading all events for each country (not filtered by mention_date)
2. Using embedding similarity to identify related events across the entire dataset
3. Setting master_event_id to link related events to their primary event

This creates a master event hierarchy where:
- Master events have master_event_id = NULL
- Child events have master_event_id pointing to the master event ID

PIPELINE CONTEXT:
  - Stage 1: Daily clustering (batch_cluster_events.py + llm_deconflict_clusters.py)
  - Stage 2A: THIS SCRIPT - Groups events using embedding similarity
  - Stage 2B: llm_deconflict_canonical_events.py - LLM validates groupings
  - Stage 2C: merge_canonical_events.py - Consolidates daily mentions

Usage:
    # Consolidate all events for all influencer countries
    python consolidate_all_events.py --influencers

    # Consolidate for specific country
    python consolidate_all_events.py --country China

    # Dry run to see what would be consolidated
    python consolidate_all_events.py --influencers --dry-run

See EVENT_PROCESSING_ARCHITECTURE.md for complete pipeline documentation.
"""

import argparse
import yaml
import numpy as np
from typing import List, Dict
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


def load_all_canonical_events(
    session,
    country: str
) -> List[Dict]:
    """
    Load ALL canonical events for a specific country.
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
            SUM(dem.article_count) as total_articles
        FROM canonical_events ce
        LEFT JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
        WHERE ce.initiating_country = :country
          AND ce.master_event_id IS NULL
        GROUP BY ce.id
        ORDER BY total_articles DESC NULLS LAST
    '''), {
        'country': country
    }).fetchall()

    events = []
    skipped_no_embedding = 0

    for row in result:
        # Skip events without embeddings
        if row[3] is None:
            skipped_no_embedding += 1
            continue

        events.append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'embedding': np.array(row[3]),
            'alternative_names': row[4] or [],
            'master_event_id': row[5],
            'days_mentioned': row[6] or 0,
            'first_mention': row[7],
            'last_mention': row[8],
            'total_articles': row[9] or 0
        })

    if skipped_no_embedding > 0:
        print(f"  [WARNING] Skipped {skipped_no_embedding:,} events without embeddings")

    return events


def find_similar_events(
    events: List[Dict],
    similarity_threshold: float = 0.85,
    verbose: bool = True
) -> List[List[int]]:
    """
    Find groups of similar events using embedding cosine similarity.

    Args:
        events: List of event dicts with 'embedding' field
        similarity_threshold: Minimum cosine similarity to consider events related
        verbose: Print progress indicators

    Returns:
        List of event index groups (each group is a list of indices into events list)
    """
    if len(events) == 0:
        return []

    n = len(events)

    if verbose:
        print(f"  Building embedding matrix ({n:,} events)...")

    # Build embedding matrix
    embeddings = np.vstack([e['embedding'] for e in events])

    if verbose:
        matrix_size_mb = (n * n * 8) / (1024 * 1024)  # 8 bytes per float64
        print(f"  Computing similarity matrix ({n:,} x {n:,} = {matrix_size_mb:.1f} MB)...")
        print(f"  This may take several minutes for large datasets...")

    # Compute pairwise similarities
    similarities = cosine_similarity(embeddings)

    if verbose:
        print(f"  Finding connected components (threshold={similarity_threshold})...")

    # Find connected components using similarity threshold
    # Using iterative DFS to avoid recursion depth issues with large clusters
    visited = [False] * n
    groups = []

    # Progress tracking for large datasets
    progress_interval = max(1000, n // 10)  # Report every 10% or every 1000 events

    for i in range(n):
        if verbose and i > 0 and i % progress_interval == 0:
            progress_pct = (i / n) * 100
            print(f"    Progress: {i:,}/{n:,} events processed ({progress_pct:.1f}%), found {len(groups):,} groups so far")

        if not visited[i]:
            # Iterative DFS using a stack
            group = []
            stack = [i]

            while stack:
                idx = stack.pop()

                if visited[idx]:
                    continue

                visited[idx] = True
                group.append(idx)

                # Add unvisited similar events to stack
                for j in range(n):
                    if not visited[j] and similarities[idx][j] >= similarity_threshold:
                        stack.append(j)

            if len(group) > 1:  # Only include groups with multiple events
                groups.append(group)

    return groups


def consolidate_country(
    session,
    country: str,
    similarity_threshold: float = 0.85,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Consolidate all events for a specific country.

    Args:
        session: Database session
        country: Initiating country
        similarity_threshold: Cosine similarity threshold for merging events
        dry_run: If True, don't save changes to database
        verbose: Print progress

    Returns:
        Dict with statistics
    """
    if verbose:
        print(f"\n" + "=" * 80)
        print(f"Consolidating: {country}")
        print("=" * 80)

    # Load ALL canonical events for this country
    events = load_all_canonical_events(session, country)

    if len(events) == 0:
        if verbose:
            print(f"  No events found for {country}")
        return {'events': 0, 'groups': 0, 'consolidated': 0, 'updated': 0}

    if verbose:
        print(f"  Loaded {len(events)} canonical events")

    # Find similar event groups
    groups = find_similar_events(events, similarity_threshold)

    if verbose:
        print(f"  Identified {len(groups)} event groups to consolidate")

    if len(groups) == 0:
        return {'events': len(events), 'groups': 0, 'consolidated': 0, 'updated': 0}

    stats = {
        'events': len(events),
        'groups': len(groups),
        'consolidated': sum(len(g) for g in groups),
        'updated': 0
    }

    # Process each group
    for i, group_indices in enumerate(groups, 1):
        # Get events in this group
        group_events = [events[idx] for idx in group_indices]

        # Sort by total_articles (descending) to pick most mentioned event as master
        group_events.sort(key=lambda e: (e['total_articles'], e['days_mentioned']), reverse=True)

        master_event = group_events[0]
        child_events = group_events[1:]

        if verbose:
            print(f"\n  Group {i}: {len(group_events)} related events")
            safe_name = master_event['canonical_name'].encode('ascii', 'replace').decode('ascii')
            print(f"    Master Event: {safe_name} (ID: {master_event['id']})")
            print(f"      {master_event['days_mentioned']} days, {master_event['total_articles']} articles")
            if master_event['first_mention'] and master_event['last_mention']:
                print(f"      Dates: {master_event['first_mention']} to {master_event['last_mention']}")

        # Update child events to point to master
        if not dry_run:
            for child in child_events:
                session.execute(
                    text('UPDATE canonical_events SET master_event_id = :master_id WHERE id = :child_id'),
                    {'master_id': master_event['id'], 'child_id': child['id']}
                )
                stats['updated'] += 1

        if verbose and len(child_events) <= 10:
            # Show child events if not too many
            for child in child_events:
                safe_name = child['canonical_name'].encode('ascii', 'replace').decode('ascii')
                print(f"      - {safe_name} (ID: {child['id']})")
                print(f"        {child['days_mentioned']} days, {child['total_articles']} articles")
        elif verbose:
            print(f"    [UPDATED] Linked {len(child_events)} child events to master")

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
        description="Comprehensive Canonical Event Consolidation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries from config.yaml')

    # Consolidation parameters
    parser.add_argument('--similarity-threshold', type=float, default=0.85,
                       help='Cosine similarity threshold for merging events (0.0-1.0)')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Show what would be consolidated without saving')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print detailed progress')

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

    print("=" * 80)
    print("COMPREHENSIVE CANONICAL EVENT CONSOLIDATION")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    print(f"Similarity threshold: {args.similarity_threshold}")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    print("=" * 80)

    overall_stats = {
        'total_events': 0,
        'total_groups': 0,
        'total_consolidated': 0,
        'total_updated': 0
    }

    with get_session() as session:
        for country in countries:
            stats = consolidate_country(
                session,
                country,
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
