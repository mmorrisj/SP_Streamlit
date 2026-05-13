"""
Stage 2A: Comprehensive Canonical Event Consolidation

Part of the two-stage batch consolidation pipeline for event processing.

This script proposes CANDIDATE event groupings using HDBSCAN over a composite
distance (name embedding + recipient overlap + temporal proximity) with a hard
temporal gate. Groupings are written via master_event_id but are NOT considered
final until llm_deconflict_canonical_events.py marks the master as
llm_validated=TRUE. Only LLM-validated groupings are merged downstream by
merge_canonical_events.py.

ALGORITHM (replaces previous connected-components approach which suffered from
single-linkage chaining — a chain of pairwise-similar events across many months
could collapse into one giant cluster):

  distance(A,B) = alpha * (1 - cosine(name_emb_A, name_emb_B))
                + beta  * (1 - jaccard(recipients_A, recipients_B))
                + gamma * min(|dates_A - dates_B| / max_days, 1.0)

  Hard gate: any pair more than `max_days` apart gets distance=1.0
  (cluster-breaking), independent of how similar names/recipients are.

  HDBSCAN with metric='precomputed' then clusters; noise (-1) stays as
  unmerged singletons.

PIPELINE CONTEXT:
  - Stage 1: Daily clustering (batch_cluster_events.py + llm_deconflict_clusters.py)
  - Stage 2A: THIS SCRIPT - Proposes candidate groupings (HDBSCAN + composite dist)
  - Stage 2B: llm_deconflict_canonical_events.py - LLM is FINAL JUDGE (validates,
              splits, picks best canonical name)
  - Stage 2C: merge_canonical_events.py - Consolidates daily mentions for
              LLM-validated masters only

Usage:
    # Consolidate all events for all influencer countries
    python consolidate_all_events.py --influencers

    # Consolidate for specific country
    python consolidate_all_events.py --country China

    # Dry run to see what would be consolidated
    python consolidate_all_events.py --influencers --dry-run

    # Force re-consolidation (resets existing consolidations first)
    python consolidate_all_events.py --country China --force

    # Override clustering weights
    python consolidate_all_events.py --country Iran --alpha 0.4 --beta 0.2 --gamma 0.4

IMPORTANT: Running multiple times without --force will skip already-consolidated events
to prevent accumulation. Use --force to reset and re-run with different parameters.

See EVENT_PROCESSING_ARCHITECTURE.md for complete pipeline documentation.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
import yaml
import numpy as np
import gc
from datetime import date
from typing import List, Dict
from sklearn.cluster import HDBSCAN
from sqlalchemy import text

from shared.database.database import get_session


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
            SUM(dem.article_count) as total_articles,
            ce.primary_recipients,
            ce.first_mention_date
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
    skipped_no_date = 0

    for row in result:
        # Skip events without embeddings
        if row[3] is None:
            skipped_no_embedding += 1
            continue
        # Skip events without a first_mention_date — required for temporal gate
        if row[11] is None:
            skipped_no_date += 1
            continue

        recipients = row[10]
        if isinstance(recipients, str):
            try:
                recipients = json.loads(recipients)
            except (ValueError, TypeError):
                recipients = {}
        if isinstance(recipients, dict):
            recipient_set = frozenset(recipients.keys())
        elif isinstance(recipients, list):
            recipient_set = frozenset(recipients)
        else:
            recipient_set = frozenset()

        events.append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'embedding': np.array(row[3], dtype=np.float32),
            'alternative_names': row[4] or [],
            'master_event_id': row[5],
            'days_mentioned': row[6] or 0,
            'first_mention': row[7],
            'last_mention': row[8],
            'total_articles': row[9] or 0,
            'recipients': recipient_set,
            'first_mention_date': row[11]
        })

    if skipped_no_date > 0:
        print(f"  [WARNING] Skipped {skipped_no_date:,} events without first_mention_date")

    if skipped_no_embedding > 0:
        print(f"  [WARNING] Skipped {skipped_no_embedding:,} events without embeddings")

    return events


def find_similar_events(
    events: List[Dict],
    alpha: float = 0.4,
    beta: float = 0.2,
    gamma: float = 0.4,
    max_days_gate: int = 30,
    min_cluster_size: int = 2,
    verbose: bool = True
) -> List[List[int]]:
    """
    Find candidate groups of related events using HDBSCAN over a composite
    distance with a hard temporal gate.

    distance(A,B) = alpha * (1 - cosine(name_emb))
                  + beta  * (1 - jaccard(recipients))
                  + gamma * min(|date_diff_days| / max_days_gate, 1.0)

    Hard gate: any pair with |date_diff_days| > max_days_gate is forced to
    distance=1.0, preventing cross-month cluster collapse regardless of how
    similar names or recipients are.

    This replaces the prior connected-components approach which suffered from
    single-linkage chaining (e.g., 5,421 Iran events collapsing into one cluster).

    Args:
        events: List of event dicts with 'embedding', 'recipients',
                'first_mention_date' fields
        alpha: weight for name-embedding cosine distance (default 0.4)
        beta: weight for recipient Jaccard distance (default 0.2)
        gamma: weight for normalized temporal distance (default 0.4)
        max_days_gate: pairs more than this many days apart get distance=1.0
                       (cluster-breaking). Default 30.
        min_cluster_size: HDBSCAN min cluster size (default 2)
        verbose: Print progress indicators

    Returns:
        List of event index groups (each group is a list of indices into events list).
        Groups have size >= 2; singletons (HDBSCAN noise) are excluded.
    """
    if len(events) == 0:
        return []

    n = len(events)

    if verbose:
        print(f"  Building feature arrays ({n:,} events)...")

    # Name embeddings: normalize for cosine via dot product
    embeddings = np.vstack([e['embedding'] for e in events]).astype(np.float32)
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9

    # Build recipient occurrence matrix for vectorized Jaccard
    all_recipients = sorted({r for e in events for r in e['recipients']})
    rec_idx = {r: i for i, r in enumerate(all_recipients)}
    if len(all_recipients) > 0:
        R = np.zeros((n, len(all_recipients)), dtype=np.float32)
        for i, e in enumerate(events):
            for r in e['recipients']:
                R[i, rec_idx[r]] = 1.0
        rec_count = R.sum(axis=1)
    else:
        R = None
        rec_count = None

    # Dates as integer day offsets
    epoch = date(2024, 1, 1)
    dates = np.array([(e['first_mention_date'] - epoch).days for e in events], dtype=np.int32)

    if verbose:
        matrix_size_mb = (n * n * 4) / (1024 * 1024)  # float32
        print(f"  Computing composite distance matrix ({n:,} x {n:,} = {matrix_size_mb:.1f} MB)...")

    # Name distance: 1 - cosine(name)
    name_sim = embeddings @ embeddings.T
    name_dist = (1.0 - name_sim).clip(min=0.0, max=2.0).astype(np.float32)
    del name_sim

    # Recipient distance: 1 - Jaccard
    if R is not None:
        intersect = R @ R.T
        union = rec_count[:, None] + rec_count[None, :] - intersect
        with np.errstate(divide='ignore', invalid='ignore'):
            rec_dist = np.where(union > 0, 1.0 - intersect / union, 1.0).astype(np.float32)
        del intersect, union
    else:
        rec_dist = np.ones((n, n), dtype=np.float32)

    # Temporal distance: |delta| / max_days, clipped to 1.0
    time_diff_days = np.abs(dates[:, None] - dates[None, :]).astype(np.int32)
    time_dist = np.minimum(time_diff_days.astype(np.float32) / float(max_days_gate), 1.0)

    # Composite distance
    D = (alpha * name_dist + beta * rec_dist + gamma * time_dist).astype(np.float64)
    del name_dist, rec_dist, time_dist

    # Hard temporal gate — any pair more than max_days_gate apart cannot cluster
    gate_mask = time_diff_days > max_days_gate
    n_gated_pairs = int(gate_mask.sum() // 2)
    D[gate_mask] = 1.0
    np.fill_diagonal(D, 0.0)
    del gate_mask, time_diff_days

    if verbose:
        print(f"  Running HDBSCAN (alpha={alpha}, beta={beta}, gamma={gamma}, "
              f"max_days_gate={max_days_gate}, min_cluster_size={min_cluster_size})")
        print(f"    Pairs gated by temporal threshold: {n_gated_pairs:,}")

    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        metric='precomputed',
        copy=True,
    )
    labels = clusterer.fit_predict(D)
    del D

    # Collect indices per cluster; -1 is noise (singletons, intentionally excluded)
    groups_map: Dict[int, List[int]] = {}
    for i, c in enumerate(labels):
        c = int(c)
        if c == -1:
            continue
        groups_map.setdefault(c, []).append(i)

    groups = [g for g in groups_map.values() if len(g) > 1]

    if verbose:
        noise_count = int((labels == -1).sum())
        print(f"    Found {len(groups):,} candidate groups; "
              f"{noise_count:,} events ({100 * noise_count / n:.0f}%) remained singleton")

    del embeddings, labels
    gc.collect()

    return groups


def consolidate_country(
    session,
    country: str,
    alpha: float = 0.4,
    beta: float = 0.2,
    gamma: float = 0.4,
    max_days_gate: int = 30,
    min_cluster_size: int = 2,
    dry_run: bool = False,
    verbose: bool = True,
    force: bool = False
) -> Dict[str, int]:
    """
    Consolidate all events for a specific country.

    Args:
        session: Database session
        country: Initiating country
        alpha: weight for name embedding cosine distance
        beta: weight for recipient Jaccard distance
        gamma: weight for normalized temporal distance
        max_days_gate: pairs > this many days apart cannot cluster
        min_cluster_size: HDBSCAN min cluster size
        dry_run: If True, don't save changes to database
        verbose: Print progress
        force: If True, reset existing consolidations before running

    Returns:
        Dict with statistics
    """
    if verbose:
        print("\n" + "=" * 80)
        print(f"Consolidating: {country}")
        print("=" * 80)

    # Check if consolidation already exists
    existing_consolidations = session.execute(text('''
        SELECT COUNT(*)
        FROM canonical_events
        WHERE initiating_country = :country
        AND master_event_id IS NOT NULL
    '''), {'country': country}).scalar()

    if existing_consolidations > 0 and not force and not dry_run:
        print(f"\n  [WARNING] {existing_consolidations} events already consolidated for {country}")
        print("  To prevent accumulation of multiple consolidation runs:")
        print("    - Use --force to reset and re-consolidate")
        print(f"    - Or manually reset: UPDATE canonical_events SET master_event_id = NULL WHERE initiating_country = '{country}'")
        return {'events': 0, 'groups': 0, 'consolidated': 0, 'updated': 0, 'skipped': True}

    if force and not dry_run:
        if verbose:
            print(f"  [FORCE MODE] Resetting {existing_consolidations} existing consolidations...")
        session.execute(text('''
            UPDATE canonical_events
            SET master_event_id = NULL
            WHERE initiating_country = :country
        '''), {'country': country})
        session.commit()

    # Load ALL canonical events for this country
    events = load_all_canonical_events(session, country)

    if len(events) == 0:
        if verbose:
            print(f"  No events found for {country}")
        return {'events': 0, 'groups': 0, 'consolidated': 0, 'updated': 0}

    if verbose:
        print(f"  Loaded {len(events)} canonical events")

    # Find similar event groups (candidates — LLM validation is the final judge)
    groups = find_similar_events(
        events,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        max_days_gate=max_days_gate,
        min_cluster_size=min_cluster_size,
        verbose=verbose,
    )

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

    # Clean up event data before returning
    del events
    del groups
    gc.collect()

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

    # Composite distance weights (Config D from offline experiment)
    parser.add_argument('--alpha', type=float, default=0.4,
                       help='Weight for name-embedding cosine distance (default 0.4)')
    parser.add_argument('--beta', type=float, default=0.2,
                       help='Weight for recipient Jaccard distance (default 0.2)')
    parser.add_argument('--gamma', type=float, default=0.4,
                       help='Weight for normalized temporal distance (default 0.4)')
    parser.add_argument('--max-days-gate', type=int, default=30,
                       help='Hard temporal gate — pairs further apart cannot cluster (default 30)')
    parser.add_argument('--min-cluster-size', type=int, default=2,
                       help='HDBSCAN min_cluster_size (default 2)')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Show what would be consolidated without saving')
    parser.add_argument('--force', action='store_true', help='Reset existing consolidations before running (prevents accumulation)')
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
    print("COMPREHENSIVE CANONICAL EVENT CONSOLIDATION (HDBSCAN + composite distance)")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    print(f"Weights: alpha={args.alpha} (name), beta={args.beta} (recipient), gamma={args.gamma} (time)")
    print(f"Temporal gate: {args.max_days_gate} days  |  min_cluster_size: {args.min_cluster_size}")
    print("Output: CANDIDATE groupings — final acceptance requires llm_deconflict_canonical_events.py")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    if args.force:
        print("[FORCE MODE] Resetting existing consolidations before running")
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
                alpha=args.alpha,
                beta=args.beta,
                gamma=args.gamma,
                max_days_gate=args.max_days_gate,
                min_cluster_size=args.min_cluster_size,
                dry_run=args.dry_run,
                verbose=args.verbose,
                force=args.force,
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
