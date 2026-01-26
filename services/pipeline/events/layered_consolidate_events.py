"""
Layered event consolidation using time-windowed hierarchical clustering.

This script addresses computational feasibility by:
1. Processing events in monthly time windows
2. Consolidating within each month first
3. Then consolidating across months for cross-boundary events
4. Maintaining doc_ids traceability at every level
5. Preserving LLM validation work

Architecture:
    Level 1: Within-month clustering (e.g., all June events)
    Level 2: Cross-month clustering (e.g., June-July boundary events)
    Level 3: Final deduplication pass

Usage:
    python services/pipeline/events/layered_consolidate_events.py \
        --country China \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --similarity-threshold 0.80 \
        --dry-run
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Set, Tuple
from collections import defaultdict
import numpy as np
from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import Config


def get_monthly_windows(start_date: datetime, end_date: datetime) -> List[Tuple[datetime, datetime]]:
    """Split date range into monthly windows."""
    windows = []
    current = start_date.replace(day=1)

    while current <= end_date:
        # Get last day of month
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1)
        else:
            next_month = current.replace(month=current.month + 1)

        window_end = next_month - timedelta(days=1)
        if window_end > end_date:
            window_end = end_date

        windows.append((current, window_end))
        current = next_month

    return windows


def get_events_in_window(
    session,
    country: str,
    start_date: datetime,
    end_date: datetime,
    only_masters: bool = True
) -> List[Dict]:
    """Get canonical events within a time window."""

    master_filter = "AND ce.master_event_id IS NULL" if only_masters else ""

    query = text(f"""
        SELECT
            ce.id,
            ce.canonical_name,
            ce.consolidated_description,
            ce.first_mention_date,
            ce.last_mention_date,
            ce.total_articles,
            ce.total_mention_days,
            ce.embedding_vector,
            ce.llm_validated,
            ce.master_event_id
        FROM canonical_events ce
        WHERE ce.initiating_country = :country
            AND ce.first_mention_date <= :end_date
            AND ce.last_mention_date >= :start_date
            {master_filter}
        ORDER BY ce.first_mention_date, ce.id
    """)

    result = session.execute(query, {
        'country': country,
        'start_date': start_date,
        'end_date': end_date
    })

    events = []
    for row in result:
        events.append({
            'id': row.id,
            'name': row.canonical_name,
            'description': row.consolidated_description,
            'first_date': row.first_mention_date,
            'last_date': row.last_mention_date,
            'article_count': row.total_articles,
            'mention_days': row.total_mention_days,
            'embedding': np.array(row.embedding_vector) if row.embedding_vector else None,
            'llm_validated': row.llm_validated,
            'master_event_id': row.master_event_id
        })

    return events


def compute_similarity_matrix(events: List[Dict], threshold: float) -> Dict[int, Set[int]]:
    """
    Compute cosine similarity between all event pairs.
    Returns dict mapping event_id -> set of similar event_ids.
    """
    n = len(events)
    similarity_groups = defaultdict(set)

    # Create mapping of list index to event id
    id_to_idx = {event['id']: idx for idx, event in enumerate(events)}
    idx_to_id = {idx: event['id'] for idx, event in enumerate(events)}

    # Build embedding matrix
    embeddings = []
    valid_indices = []
    for idx, event in enumerate(events):
        if event['embedding'] is not None:
            embeddings.append(event['embedding'])
            valid_indices.append(idx)

    if len(embeddings) == 0:
        print("⚠️  No embeddings found for events in this window")
        return similarity_groups

    embeddings = np.array(embeddings)

    # Normalize embeddings for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings_normalized = embeddings / (norms + 1e-10)

    # Compute similarity matrix
    similarity_matrix = np.dot(embeddings_normalized, embeddings_normalized.T)

    # Find pairs above threshold
    for i, idx_i in enumerate(valid_indices):
        for j, idx_j in enumerate(valid_indices):
            if i < j and similarity_matrix[i, j] >= threshold:
                event_id_i = idx_to_id[idx_i]
                event_id_j = idx_to_id[idx_j]
                similarity_groups[event_id_i].add(event_id_j)
                similarity_groups[event_id_j].add(event_id_i)

    return similarity_groups


def merge_similarity_groups(similarity_groups: Dict[int, Set[int]]) -> List[Set[int]]:
    """
    Merge overlapping similarity groups into consolidated clusters.
    If events A and B are similar, and B and C are similar, they all merge into one cluster.
    """
    visited = set()
    clusters = []

    def dfs(event_id: int, cluster: Set[int]):
        """Depth-first search to find all connected events."""
        if event_id in visited:
            return
        visited.add(event_id)
        cluster.add(event_id)

        for similar_id in similarity_groups.get(event_id, set()):
            dfs(similar_id, cluster)

    # Find all connected components
    for event_id in similarity_groups.keys():
        if event_id not in visited:
            cluster = set()
            dfs(event_id, cluster)
            if len(cluster) > 1:  # Only keep clusters with multiple events
                clusters.append(cluster)

    return clusters


def consolidate_within_window(
    session,
    country: str,
    window_start: datetime,
    window_end: datetime,
    threshold: float,
    dry_run: bool = True
) -> Tuple[int, int]:
    """
    Consolidate events within a single time window.
    Returns (num_clusters, num_events_consolidated).
    """
    print(f"\n{'='*60}")
    print(f"Processing window: {window_start.date()} to {window_end.date()}")
    print(f"{'='*60}")

    # Get events in this window
    events = get_events_in_window(session, country, window_start, window_end, only_masters=True)

    if len(events) == 0:
        print("No events found in this window")
        return 0, 0

    print(f"Found {len(events)} events in window")

    # Filter events with embeddings
    events_with_embeddings = [e for e in events if e['embedding'] is not None]
    print(f"Events with embeddings: {len(events_with_embeddings)}")

    if len(events_with_embeddings) < 2:
        print("Not enough events with embeddings to cluster")
        return 0, 0

    # Compute similarities
    print(f"Computing similarities with threshold {threshold}...")
    similarity_groups = compute_similarity_matrix(events_with_embeddings, threshold)

    # Merge into clusters
    clusters = merge_similarity_groups(similarity_groups)
    print(f"Found {len(clusters)} clusters")

    if len(clusters) == 0:
        return 0, 0

    # Show cluster statistics
    cluster_sizes = [len(c) for c in clusters]
    print(f"Cluster size distribution:")
    print(f"  Min: {min(cluster_sizes)}, Max: {max(cluster_sizes)}, Avg: {np.mean(cluster_sizes):.1f}")

    # Show sample clusters
    events_by_id = {e['id']: e for e in events}
    print(f"\nSample clusters (top 3 by size):")
    for i, cluster in enumerate(sorted(clusters, key=len, reverse=True)[:3]):
        print(f"\n  Cluster {i+1} ({len(cluster)} events):")
        for event_id in list(cluster)[:5]:  # Show first 5 events
            event = events_by_id[event_id]
            print(f"    - {event['name'][:80]} ({event['article_count']} articles)")
        if len(cluster) > 5:
            print(f"    ... and {len(cluster) - 5} more events")

    if dry_run:
        print("\n⚠️  DRY RUN - No database changes made")
        return len(clusters), sum(len(c) - 1 for c in clusters)

    # Apply consolidation
    events_consolidated = 0
    for cluster in clusters:
        # Pick master event (highest article count, preserve LLM validated if possible)
        cluster_events = [events_by_id[eid] for eid in cluster]

        # Prefer LLM validated events as masters
        llm_validated_events = [e for e in cluster_events if e['llm_validated']]
        if llm_validated_events:
            master_event = max(llm_validated_events, key=lambda e: e['article_count'])
        else:
            master_event = max(cluster_events, key=lambda e: e['article_count'])

        master_id = master_event['id']
        child_ids = [e['id'] for e in cluster_events if e['id'] != master_id]

        if len(child_ids) > 0:
            # Update child events to point to master
            update_query = text("""
                UPDATE canonical_events
                SET master_event_id = :master_id
                WHERE id = ANY(:child_ids)
            """)
            session.execute(update_query, {
                'master_id': master_id,
                'child_ids': child_ids
            })
            events_consolidated += len(child_ids)

    session.commit()
    print(f"\n✅ Consolidated {events_consolidated} events into {len(clusters)} clusters")

    return len(clusters), events_consolidated


def consolidate_cross_boundary(
    session,
    country: str,
    start_date: datetime,
    end_date: datetime,
    threshold: float,
    boundary_days: int = 7,
    dry_run: bool = True
) -> Tuple[int, int]:
    """
    Consolidate events that span across month boundaries.
    Looks at events within boundary_days of month transitions.
    """
    print(f"\n{'='*60}")
    print(f"Processing cross-boundary events (±{boundary_days} days from month boundaries)")
    print(f"{'='*60}")

    windows = get_monthly_windows(start_date, end_date)
    boundary_events = []

    # Collect events near boundaries
    for i in range(len(windows) - 1):
        _, window1_end = windows[i]
        window2_start, _ = windows[i + 1]

        # Get events that end near the boundary or start near the boundary
        boundary_start = window1_end - timedelta(days=boundary_days)
        boundary_end = window2_start + timedelta(days=boundary_days)

        events = get_events_in_window(session, country, boundary_start, boundary_end, only_masters=True)

        # Filter to events that actually span the boundary
        boundary_events.extend([
            e for e in events
            if e['first_date'] <= window1_end and e['last_date'] >= window2_start
        ])

    # Remove duplicates
    seen_ids = set()
    unique_boundary_events = []
    for event in boundary_events:
        if event['id'] not in seen_ids:
            seen_ids.add(event['id'])
            unique_boundary_events.append(event)

    print(f"Found {len(unique_boundary_events)} events near month boundaries")

    if len(unique_boundary_events) < 2:
        print("Not enough boundary events to cluster")
        return 0, 0

    # Compute similarities
    events_with_embeddings = [e for e in unique_boundary_events if e['embedding'] is not None]
    print(f"Events with embeddings: {len(events_with_embeddings)}")

    similarity_groups = compute_similarity_matrix(events_with_embeddings, threshold)
    clusters = merge_similarity_groups(similarity_groups)

    print(f"Found {len(clusters)} cross-boundary clusters")

    if len(clusters) == 0:
        return 0, 0

    # Show sample clusters
    events_by_id = {e['id']: e for e in unique_boundary_events}
    print(f"\nSample cross-boundary clusters (top 3 by size):")
    for i, cluster in enumerate(sorted(clusters, key=len, reverse=True)[:3]):
        print(f"\n  Cluster {i+1} ({len(cluster)} events):")
        for event_id in list(cluster)[:5]:
            event = events_by_id[event_id]
            date_range = f"{event['first_date'].date()} to {event['last_date'].date()}"
            print(f"    - {event['name'][:80]} ({date_range})")

    if dry_run:
        print("\n⚠️  DRY RUN - No database changes made")
        return len(clusters), sum(len(c) - 1 for c in clusters)

    # Apply consolidation (same logic as within-window)
    events_consolidated = 0
    for cluster in clusters:
        cluster_events = [events_by_id[eid] for eid in cluster]

        # Prefer LLM validated, highest article count
        llm_validated_events = [e for e in cluster_events if e['llm_validated']]
        if llm_validated_events:
            master_event = max(llm_validated_events, key=lambda e: e['article_count'])
        else:
            master_event = max(cluster_events, key=lambda e: e['article_count'])

        master_id = master_event['id']
        child_ids = [e['id'] for e in cluster_events if e['id'] != master_id]

        if len(child_ids) > 0:
            update_query = text("""
                UPDATE canonical_events
                SET master_event_id = :master_id
                WHERE id = ANY(:child_ids)
            """)
            session.execute(update_query, {
                'master_id': master_id,
                'child_ids': child_ids
            })
            events_consolidated += len(child_ids)

    session.commit()
    print(f"\n✅ Consolidated {events_consolidated} cross-boundary events into {len(clusters)} clusters")

    return len(clusters), events_consolidated


def main():
    parser = argparse.ArgumentParser(
        description='Layered event consolidation using time-windowed hierarchical clustering'
    )
    parser.add_argument(
        '--country',
        required=True,
        help='Initiating country (e.g., China)'
    )
    parser.add_argument(
        '--start-date',
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        required=True,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--similarity-threshold',
        type=float,
        default=0.80,
        help='Cosine similarity threshold (default: 0.80)'
    )
    parser.add_argument(
        '--boundary-days',
        type=int,
        default=7,
        help='Days around month boundaries to check for cross-boundary events (default: 7)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be consolidated without making changes'
    )
    parser.add_argument(
        '--skip-within-month',
        action='store_true',
        help='Skip within-month consolidation (only do cross-boundary)'
    )
    parser.add_argument(
        '--skip-cross-boundary',
        action='store_true',
        help='Skip cross-boundary consolidation (only do within-month)'
    )

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')

    print("="*60)
    print("LAYERED EVENT CONSOLIDATION")
    print("="*60)
    print(f"Country: {args.country}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Similarity threshold: {args.similarity_threshold}")
    print(f"Boundary window: ±{args.boundary_days} days")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("="*60)

    with get_session() as session:
        total_clusters = 0
        total_consolidated = 0

        # Level 1: Within-month consolidation
        if not args.skip_within_month:
            windows = get_monthly_windows(start_date, end_date)
            print(f"\nLevel 1: Within-month consolidation ({len(windows)} windows)")

            for window_start, window_end in windows:
                clusters, consolidated = consolidate_within_window(
                    session,
                    args.country,
                    window_start,
                    window_end,
                    args.similarity_threshold,
                    args.dry_run
                )
                total_clusters += clusters
                total_consolidated += consolidated

        # Level 2: Cross-boundary consolidation
        if not args.skip_cross_boundary:
            print(f"\nLevel 2: Cross-boundary consolidation")
            clusters, consolidated = consolidate_cross_boundary(
                session,
                args.country,
                start_date,
                end_date,
                args.similarity_threshold,
                args.boundary_days,
                args.dry_run
            )
            total_clusters += clusters
            total_consolidated += consolidated

        # Summary
        print(f"\n{'='*60}")
        print("CONSOLIDATION COMPLETE")
        print(f"{'='*60}")
        print(f"Total clusters created: {total_clusters}")
        print(f"Total events consolidated: {total_consolidated}")

        if args.dry_run:
            print("\n⚠️  This was a DRY RUN - no database changes were made")
            print("Run without --dry-run to apply consolidation")
        else:
            print("\n✅ Database updated successfully")
            print("\nNext steps:")
            print("1. Run LLM deconfliction: python services/pipeline/events/llm_deconflict_canonical_events.py")
            print("2. Merge daily mentions: python services/pipeline/events/merge_canonical_events.py")
            print("3. Generate metrics: python publications/scripts/generate_metrics_snapshot.py")


if __name__ == '__main__':
    main()
