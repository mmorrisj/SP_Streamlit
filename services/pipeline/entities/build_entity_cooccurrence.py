"""
Stage 3B: Build Entity Co-occurrence Relationships

Populates the entity_relationships table with co-occurrence data derived from
shared doc_ids between entity pairs.

Logic:
  1. Build inverted index: doc_id -> Set[entity_id] from daily_entity_mentions
  2. For each doc with 2+ entities, generate all pairs
  3. Use entity_from_id < entity_to_id ordering to avoid duplicate rows
  4. Filter pairs by min co-occurrence threshold
  5. Collect date range and categories from source documents
  6. Insert/upsert into entity_relationships

Powers the Entity_Network.py dashboard page which queries EntityRelationship.

Recipient country approach: Track but don't filter. Recipient context is available
via the source documents' categories/recipients but doesn't restrict which pairs
get linked.

PIPELINE CONTEXT:
  - Stage 1-2: Entity extraction, clustering, consolidation, merge
  - Stage 3A: link_entities_to_events.py - Entity-event linkage
  - Stage 3B: THIS SCRIPT - Entity co-occurrence network
  - Stage 3C: generate_entity_descriptions.py - LLM entity profiles

Usage:
    python build_entity_cooccurrence.py --influencers
    python build_entity_cooccurrence.py --country Iran
    python build_entity_cooccurrence.py --influencers --min-cooccurrence 3
    python build_entity_cooccurrence.py --country China --force --dry-run
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import yaml
from collections import defaultdict
from itertools import combinations
from typing import Dict
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


def build_cooccurrence_for_country(
    session,
    country: str,
    min_cooccurrence: int = 2,
    dry_run: bool = False,
    verbose: bool = True,
    force: bool = False,
    batch_size: int = 500
) -> Dict[str, int]:
    """
    Build entity co-occurrence relationships for a specific country.

    Args:
        session: Database session
        country: Initiating country
        min_cooccurrence: Minimum shared docs to create a relationship
        dry_run: If True, don't save changes
        verbose: Print progress
        force: If True, delete existing co_occurrence relationships first
        batch_size: Commit every N relationships inserted

    Returns:
        Statistics dict
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Building Entity Co-occurrence: {country}")
        print('='*80)

    # Force mode: delete existing co_occurrence relationships for this country
    if force and not dry_run:
        deleted = session.execute(text('''
            DELETE FROM entity_relationships
            WHERE relationship_type = 'co_occurrence'
              AND entity_from_id IN (
                  SELECT id FROM canonical_entities
                  WHERE initiating_country = :country AND master_entity_id IS NULL
              )
        '''), {'country': country}).rowcount
        session.commit()
        if verbose:
            print(f"  [FORCE] Deleted {deleted:,} existing co_occurrence relationships")

    # Check if relationships already exist (skip if not force)
    if not force:
        existing = session.execute(text('''
            SELECT COUNT(*) FROM entity_relationships er
            JOIN canonical_entities ce ON er.entity_from_id = ce.id
            WHERE ce.initiating_country = :country
              AND er.relationship_type = 'co_occurrence'
        '''), {'country': country}).scalar()

        if existing > 0:
            if verbose:
                print(f"  [SKIP] {existing:,} co_occurrence relationships already exist for {country}")
                print("  Use --force to rebuild")
            return {'pairs_found': 0, 'pairs_above_threshold': 0, 'relationships_created': 0, 'skipped': True}

    # Step 1: Build inverted index doc_id -> Set[entity_id]
    if verbose:
        print("  Building doc-to-entity inverted index...")

    doc_entity_rows = session.execute(text('''
        SELECT unnest(dem.doc_ids) as doc_id, dem.canonical_entity_id::text
        FROM daily_entity_mentions dem
        JOIN canonical_entities ce ON dem.canonical_entity_id = ce.id
        WHERE ce.initiating_country = :country
          AND ce.master_entity_id IS NULL
          AND dem.doc_ids IS NOT NULL
    '''), {'country': country}).fetchall()

    if not doc_entity_rows:
        if verbose:
            print("  No doc-entity data found")
        return {'pairs_found': 0, 'pairs_above_threshold': 0, 'relationships_created': 0}

    # Build inverted index
    doc_to_entities = defaultdict(set)
    for doc_id, entity_id in doc_entity_rows:
        doc_to_entities[doc_id].add(entity_id)

    if verbose:
        print(f"  Inverted index: {len(doc_to_entities):,} documents, {len(doc_entity_rows):,} doc-entity pairs")

    # Step 2: Build pair counts from inverted index
    if verbose:
        print("  Computing entity pair co-occurrences...")

    pair_data = defaultdict(lambda: {'count': 0, 'doc_ids': []})

    docs_with_multiple = 0
    for doc_id, entity_ids in doc_to_entities.items():
        if len(entity_ids) < 2:
            continue
        docs_with_multiple += 1

        # Generate all pairs, using sorted UUIDs for canonical ordering
        entity_list = sorted(entity_ids)
        for e1, e2 in combinations(entity_list, 2):
            key = (e1, e2)  # Already sorted
            pair_data[key]['count'] += 1
            pair_data[key]['doc_ids'].append(doc_id)

    if verbose:
        print(f"  Documents with 2+ entities: {docs_with_multiple:,}")
        print(f"  Total unique entity pairs: {len(pair_data):,}")

    # Step 3: Filter by minimum co-occurrence
    qualifying_pairs = {k: v for k, v in pair_data.items() if v['count'] >= min_cooccurrence}

    if verbose:
        print(f"  Pairs with >= {min_cooccurrence} co-occurrences: {len(qualifying_pairs):,}")

    stats = {
        'pairs_found': len(pair_data),
        'pairs_above_threshold': len(qualifying_pairs),
        'relationships_created': 0
    }

    if not qualifying_pairs:
        return stats

    if dry_run:
        if verbose:
            # Show top pairs
            top_pairs = sorted(qualifying_pairs.items(), key=lambda x: x[1]['count'], reverse=True)[:10]
            print(f"\n  [DRY RUN] Top 10 co-occurring pairs:")
            # Load entity names for display
            all_entity_ids = set()
            for (e1, e2), _ in top_pairs:
                all_entity_ids.add(e1)
                all_entity_ids.add(e2)

            entity_names = {}
            if all_entity_ids:
                name_rows = session.execute(text('''
                    SELECT id::text, canonical_name FROM canonical_entities
                    WHERE id::text = ANY(:ids)
                '''), {'ids': list(all_entity_ids)}).fetchall()
                entity_names = {row[0]: row[1] for row in name_rows}

            for (e1, e2), data in top_pairs:
                n1 = entity_names.get(e1, e1[:8]).encode('ascii', 'replace').decode('ascii')[:30]
                n2 = entity_names.get(e2, e2[:8]).encode('ascii', 'replace').decode('ascii')[:30]
                print(f"    {n1} <-> {n2}: {data['count']} shared docs")

            print(f"\n  [DRY RUN] Would create {len(qualifying_pairs):,} relationships")
        return stats

    # Step 4: Pre-load document dates and categories for enrichment
    if verbose:
        print("\n  Loading document metadata for enrichment...")

    all_doc_ids = set()
    for data in qualifying_pairs.values():
        all_doc_ids.update(data['doc_ids'][:100])  # Cap per-pair, but collect all unique

    # Load dates in bulk
    doc_dates = {}
    if all_doc_ids:
        # Process in chunks to avoid query size limits
        doc_id_list = list(all_doc_ids)
        for chunk_start in range(0, len(doc_id_list), 5000):
            chunk = doc_id_list[chunk_start:chunk_start + 5000]
            date_rows = session.execute(text('''
                SELECT doc_id, date FROM documents
                WHERE doc_id = ANY(:doc_ids)
            '''), {'doc_ids': chunk}).fetchall()
            for doc_id, doc_date in date_rows:
                doc_dates[doc_id] = doc_date

    # Load categories in bulk
    doc_categories = defaultdict(list)
    if all_doc_ids:
        doc_id_list = list(all_doc_ids)
        for chunk_start in range(0, len(doc_id_list), 5000):
            chunk = doc_id_list[chunk_start:chunk_start + 5000]
            cat_rows = session.execute(text('''
                SELECT doc_id, category FROM categories
                WHERE doc_id = ANY(:doc_ids)
            '''), {'doc_ids': chunk}).fetchall()
            for doc_id, category in cat_rows:
                doc_categories[doc_id].append(category)

    if verbose:
        print(f"  Loaded dates for {len(doc_dates):,} docs, categories for {len(doc_categories):,} docs")

    # Step 5: Insert relationships
    if verbose:
        print(f"\n  Inserting {len(qualifying_pairs):,} relationships...")

    inserts_since_commit = 0

    for (e1, e2), data in qualifying_pairs.items():
        shared_doc_ids = data['doc_ids'][:100]  # Cap at 100

        # Get date range
        dates = [doc_dates[d] for d in shared_doc_ids if d in doc_dates]
        first_date = min(dates) if dates else None
        last_date = max(dates) if dates else None

        # Get category breakdown
        cat_counts = defaultdict(int)
        for doc_id in shared_doc_ids:
            for cat in doc_categories.get(doc_id, []):
                cat_counts[cat] += 1

        if not first_date or not last_date:
            continue

        session.execute(text('''
            INSERT INTO entity_relationships (
                id, entity_from_id, entity_to_id, relationship_type,
                co_occurrence_count, first_co_occurrence, last_co_occurrence,
                primary_categories, source_doc_ids, created_at
            ) VALUES (
                gen_random_uuid(), :from_id::uuid, :to_id::uuid, 'co_occurrence',
                :count, :first_date, :last_date,
                :categories::jsonb, :doc_ids, NOW()
            )
            ON CONFLICT ON CONSTRAINT uq_entity_relationship
            DO UPDATE SET
                co_occurrence_count = EXCLUDED.co_occurrence_count,
                first_co_occurrence = EXCLUDED.first_co_occurrence,
                last_co_occurrence = EXCLUDED.last_co_occurrence,
                primary_categories = EXCLUDED.primary_categories,
                source_doc_ids = EXCLUDED.source_doc_ids,
                updated_at = NOW()
        '''), {
            'from_id': e1,
            'to_id': e2,
            'count': data['count'],
            'first_date': first_date,
            'last_date': last_date,
            'categories': str(dict(cat_counts)).replace("'", '"') if cat_counts else '{}',
            'doc_ids': shared_doc_ids
        })

        stats['relationships_created'] += 1
        inserts_since_commit += 1

        if inserts_since_commit >= batch_size:
            session.commit()
            if verbose:
                print(f"    [CHECKPOINT] {stats['relationships_created']:,}/{len(qualifying_pairs):,} relationships inserted")
            inserts_since_commit = 0

    # Final commit
    if inserts_since_commit > 0:
        session.commit()

    if verbose:
        print(f"\n  [DONE] Created {stats['relationships_created']:,} co-occurrence relationships")

    # Clean up
    del doc_to_entities
    del pair_data
    del qualifying_pairs

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Build entity co-occurrence relationships from shared document IDs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
    parser.add_argument('--force', action='store_true', help='Delete existing relationships before rebuilding')
    parser.add_argument('--min-cooccurrence', type=int, default=2,
                       help='Minimum shared documents to create relationship (default: 2)')
    parser.add_argument('--batch-size', type=int, default=500, help='Commit every N inserts (default: 500)')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print progress')

    args = parser.parse_args()

    if args.influencers:
        config = load_config()
        countries = config['influencers']
    elif args.country:
        countries = [args.country]
    else:
        print("[ERROR] Must specify either --country or --influencers")
        return

    print("=" * 80)
    print("BUILD ENTITY CO-OCCURRENCE RELATIONSHIPS")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    print(f"Min co-occurrence: {args.min_cooccurrence} shared documents")
    if args.dry_run:
        print("[DRY RUN MODE]")
    if args.force:
        print("[FORCE MODE] Rebuilding existing relationships")
    print("=" * 80)

    overall = {
        'total_pairs': 0,
        'total_above_threshold': 0,
        'total_created': 0
    }

    with get_session() as session:
        for country in countries:
            stats = build_cooccurrence_for_country(
                session, country,
                min_cooccurrence=args.min_cooccurrence,
                dry_run=args.dry_run,
                verbose=args.verbose,
                force=args.force,
                batch_size=args.batch_size
            )
            overall['total_pairs'] += stats['pairs_found']
            overall['total_above_threshold'] += stats['pairs_above_threshold']
            overall['total_created'] += stats['relationships_created']

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total unique entity pairs found: {overall['total_pairs']:,}")
    print(f"Pairs above threshold: {overall['total_above_threshold']:,}")
    if not args.dry_run:
        print(f"Relationships created: {overall['total_created']:,}")
    print("=" * 80)


if __name__ == "__main__":
    main()
