"""
Stage 2A: Comprehensive Canonical Entity Consolidation

Part of the two-stage batch consolidation pipeline for entity processing.

This script consolidates ALL canonical entities by:
1. Loading all entities for each country, grouped by entity_type
2. Using embedding similarity to identify related entities across the entire dataset
3. Setting master_entity_id to link related entities to their primary entity

IMPORTANT: Entities are only compared within the SAME entity_type.
  - PERSON only groups with PERSON
  - ORGANIZATION only groups with ORGANIZATION
  - etc.

This creates a master entity hierarchy where:
- Master entities have master_entity_id = NULL
- Child entities have master_entity_id pointing to the master entity ID

PIPELINE CONTEXT:
  - Stage 1A: extract_daily_entities.py - Extracts raw entities from documents
  - Stage 1B: cluster_daily_entities.py - Clusters entities per day using DBSCAN
  - Stage 1C: llm_deconflict_entity_clusters.py - LLM validates clusters, creates canonical entities
  - Stage 2A: THIS SCRIPT - Groups entities using embedding similarity (within same type)
  - Stage 2B: llm_deconflict_canonical_entities.py - LLM validates groupings
  - Stage 2C: merge_canonical_entities.py - Consolidates daily mentions

Usage:
    # Consolidate all entities for all influencer countries
    python consolidate_all_entities.py --influencers

    # Consolidate for specific country
    python consolidate_all_entities.py --country China

    # Dry run to see what would be consolidated
    python consolidate_all_entities.py --influencers --dry-run

    # Force re-consolidation (resets existing consolidations first)
    python consolidate_all_entities.py --country China --force

    # Custom similarity threshold (default: 0.88, stricter than events' 0.85)
    python consolidate_all_entities.py --country Iran --similarity-threshold 0.90

IMPORTANT: Running multiple times without --force will skip already-consolidated entities
to prevent accumulation. Use --force to reset and re-run with different parameters.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import yaml
import numpy as np
import gc
from typing import List, Dict
from sklearn.metrics.pairwise import cosine_similarity
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


def load_all_canonical_entities(
    session,
    country: str,
    entity_type: str
) -> List[Dict]:
    """
    Load ALL canonical entities for a specific country and entity type.
    Only loads entities that don't already have a master_entity_id set.

    Args:
        session: Database session
        country: Initiating country
        entity_type: Entity type to load (e.g., 'person', 'organization')

    Returns:
        List of dicts with canonical entity info plus aggregated mention stats
    """
    result = session.execute(text('''
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.entity_type,
            ce.primary_role,
            ce.embedding_vector,
            ce.alternative_names,
            ce.country_affiliations,
            ce.master_entity_id,
            COUNT(DISTINCT dem.mention_date) as days_mentioned,
            MIN(dem.mention_date) as first_mention,
            MAX(dem.mention_date) as last_mention,
            COALESCE(SUM(dem.document_count), 0) as total_documents
        FROM canonical_entities ce
        LEFT JOIN daily_entity_mentions dem ON ce.id = dem.canonical_entity_id
        WHERE ce.initiating_country = :country
          AND ce.entity_type = :entity_type
          AND ce.master_entity_id IS NULL
        GROUP BY ce.id
        ORDER BY total_documents DESC NULLS LAST
    '''), {
        'country': country,
        'entity_type': entity_type
    }).fetchall()

    entities = []
    skipped_no_embedding = 0

    for row in result:
        # Skip entities without embeddings
        if row[5] is None:
            skipped_no_embedding += 1
            continue

        entities.append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'entity_type': row[3],
            'primary_role': row[4],
            'embedding': np.array(row[5]),
            'alternative_names': row[6] or [],
            'country_affiliations': row[7] or [],
            'master_entity_id': row[8],
            'days_mentioned': row[9] or 0,
            'first_mention': row[10],
            'last_mention': row[11],
            'total_documents': row[12] or 0
        })

    if skipped_no_embedding > 0:
        print(f"    [WARNING] Skipped {skipped_no_embedding:,} entities without embeddings")

    return entities


def find_similar_entities(
    entities: List[Dict],
    similarity_threshold: float = 0.88,
    verbose: bool = True
) -> List[List[int]]:
    """
    Find groups of similar entities using embedding cosine similarity.

    Args:
        entities: List of entity dicts with 'embedding' field
        similarity_threshold: Minimum cosine similarity to consider entities related
        verbose: Print progress indicators

    Returns:
        List of entity index groups (each group is a list of indices into entities list)
    """
    if len(entities) == 0:
        return []

    n = len(entities)

    if verbose:
        print(f"    Building embedding matrix ({n:,} entities)...")

    # Build embedding matrix
    embeddings = np.vstack([e['embedding'] for e in entities])

    if verbose:
        matrix_size_mb = (n * n * 4) / (1024 * 1024)  # 4 bytes per float32
        print(f"    Computing similarity matrix ({n:,} x {n:,} = {matrix_size_mb:.1f} MB)...")

    # Compute pairwise similarities in chunks to avoid memory issues
    chunk_size = 1000
    similarities = np.zeros((n, n), dtype=np.float32)

    for start_idx in range(0, n, chunk_size):
        end_idx = min(start_idx + chunk_size, n)
        chunk = embeddings[start_idx:end_idx]
        similarities[start_idx:end_idx] = cosine_similarity(chunk, embeddings).astype(np.float32)

        if verbose and start_idx > 0 and start_idx % (chunk_size * 5) == 0:
            progress = (end_idx / n) * 100
            print(f"      Similarity computation: {progress:.1f}% complete ({end_idx:,}/{n:,})")

        del chunk
        gc.collect()

    if verbose:
        print(f"    Finding connected components (threshold={similarity_threshold})...")

    # Find connected components using iterative DFS
    visited = [False] * n
    groups = []

    progress_interval = max(1000, n // 10)

    for i in range(n):
        if verbose and i > 0 and i % progress_interval == 0:
            progress_pct = (i / n) * 100
            print(f"      Progress: {i:,}/{n:,} entities processed ({progress_pct:.1f}%), found {len(groups):,} groups so far")

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

                # Add unvisited similar entities to stack
                for j in range(n):
                    if not visited[j] and similarities[idx][j] >= similarity_threshold:
                        stack.append(j)

            if len(group) > 1:  # Only include groups with multiple entities
                groups.append(group)

    # Clean up large matrices
    del embeddings
    del similarities
    del visited
    gc.collect()

    return groups


def consolidate_country(
    session,
    country: str,
    similarity_threshold: float = 0.88,
    dry_run: bool = False,
    verbose: bool = True,
    force: bool = False
) -> Dict[str, int]:
    """
    Consolidate all entities for a specific country, processing each entity type separately.

    Args:
        session: Database session
        country: Initiating country
        similarity_threshold: Cosine similarity threshold for merging entities
        dry_run: If True, don't save changes to database
        verbose: Print progress
        force: If True, reset existing consolidations before running

    Returns:
        Dict with statistics
    """
    if verbose:
        print("\n" + "=" * 80)
        print(f"Consolidating Entities: {country}")
        print("=" * 80)

    # Check if consolidation already exists
    existing_consolidations = session.execute(text('''
        SELECT COUNT(*)
        FROM canonical_entities
        WHERE initiating_country = :country
        AND master_entity_id IS NOT NULL
    '''), {'country': country}).scalar()

    if existing_consolidations > 0 and not force and not dry_run:
        print(f"\n  [WARNING] {existing_consolidations} entities already consolidated for {country}")
        print("  To prevent accumulation of multiple consolidation runs:")
        print("    - Use --force to reset and re-consolidate")
        print(f"    - Or manually reset: UPDATE canonical_entities SET master_entity_id = NULL WHERE initiating_country = '{country}'")
        return {'entities': 0, 'groups': 0, 'consolidated': 0, 'updated': 0, 'skipped': True}

    if force and not dry_run:
        if verbose:
            print(f"  [FORCE MODE] Resetting {existing_consolidations} existing consolidations...")
        session.execute(text('''
            UPDATE canonical_entities
            SET master_entity_id = NULL
            WHERE initiating_country = :country
        '''), {'country': country})
        session.commit()

    # Get entity types present for this country
    entity_types = session.execute(text('''
        SELECT DISTINCT entity_type
        FROM canonical_entities
        WHERE initiating_country = :country
          AND master_entity_id IS NULL
        ORDER BY entity_type
    '''), {'country': country}).fetchall()

    entity_types = [row[0] for row in entity_types]

    if not entity_types:
        if verbose:
            print(f"  No entities found for {country}")
        return {'entities': 0, 'groups': 0, 'consolidated': 0, 'updated': 0}

    if verbose:
        print(f"  Entity types to process: {', '.join(str(t) for t in entity_types)}")

    stats = {
        'entities': 0,
        'groups': 0,
        'consolidated': 0,
        'updated': 0
    }

    # Process each entity type separately
    for entity_type in entity_types:
        if verbose:
            print(f"\n  --- Processing entity type: {entity_type} ---")

        # Load entities for this type
        entities = load_all_canonical_entities(session, country, str(entity_type))

        if len(entities) == 0:
            if verbose:
                print(f"    No entities found for type {entity_type}")
            continue

        stats['entities'] += len(entities)

        if verbose:
            print(f"    Loaded {len(entities)} canonical entities")

        # Find similar entity groups within this type
        groups = find_similar_entities(entities, similarity_threshold, verbose)

        if verbose:
            print(f"    Identified {len(groups)} entity groups to consolidate")

        if len(groups) == 0:
            del entities
            gc.collect()
            continue

        stats['groups'] += len(groups)
        stats['consolidated'] += sum(len(g) for g in groups)

        # Process each group
        for i, group_indices in enumerate(groups, 1):
            group_entities = [entities[idx] for idx in group_indices]

            # Sort by total_documents (descending) to pick most referenced entity as master
            group_entities.sort(key=lambda e: (e['total_documents'], e['days_mentioned']), reverse=True)

            master_entity = group_entities[0]
            child_entities = group_entities[1:]

            if verbose:
                print(f"\n    Group {i}: {len(group_entities)} related entities")
                safe_name = master_entity['canonical_name'].encode('ascii', 'replace').decode('ascii')
                print(f"      Master: {safe_name} (ID: {master_entity['id']})")
                print(f"        {master_entity['days_mentioned']} days, {master_entity['total_documents']} documents")
                if master_entity['primary_role']:
                    print(f"        Role: {master_entity['primary_role']}")

            # Update child entities to point to master
            if not dry_run:
                for child in child_entities:
                    session.execute(
                        text('UPDATE canonical_entities SET master_entity_id = :master_id WHERE id = :child_id'),
                        {'master_id': master_entity['id'], 'child_id': child['id']}
                    )
                    stats['updated'] += 1

            if verbose and len(child_entities) <= 10:
                for child in child_entities:
                    safe_name = child['canonical_name'].encode('ascii', 'replace').decode('ascii')
                    print(f"        - {safe_name} (ID: {child['id']})")
                    print(f"          {child['days_mentioned']} days, {child['total_documents']} documents")
            elif verbose:
                print(f"      [UPDATED] Linked {len(child_entities)} child entities to master")

        # Clean up before next entity type
        del entities
        del groups
        gc.collect()

    # Commit changes if not dry run
    if not dry_run and stats['updated'] > 0:
        session.commit()
        if verbose:
            print(f"\n  [COMMITTED] Updated {stats['updated']} canonical entities")
    elif dry_run and verbose:
        print(f"\n  [DRY RUN] Would update {stats['consolidated'] - stats['groups']} canonical entities")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive Canonical Entity Consolidation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries from config.yaml')

    # Consolidation parameters
    parser.add_argument('--similarity-threshold', type=float, default=0.88,
                       help='Cosine similarity threshold for merging entities (0.0-1.0, default: 0.88)')

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
    print("COMPREHENSIVE CANONICAL ENTITY CONSOLIDATION")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    print(f"Similarity threshold: {args.similarity_threshold}")
    print("NOTE: Entities are only compared within the SAME entity_type")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    if args.force:
        print("[FORCE MODE] Resetting existing consolidations before running")
    print("=" * 80)

    overall_stats = {
        'total_entities': 0,
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
                args.verbose,
                args.force
            )

            overall_stats['total_entities'] += stats['entities']
            overall_stats['total_groups'] += stats['groups']
            overall_stats['total_consolidated'] += stats['consolidated']
            overall_stats['total_updated'] += stats['updated']

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total entities processed: {overall_stats['total_entities']}")
    print(f"Entity groups identified: {overall_stats['total_groups']}")
    print(f"Entities that can be consolidated: {overall_stats['total_consolidated']}")
    if not args.dry_run:
        print(f"Database records updated: {overall_stats['total_updated']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
