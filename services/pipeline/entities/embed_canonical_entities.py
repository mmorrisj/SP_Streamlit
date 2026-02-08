"""
Generate embeddings for canonical entities that are missing them.

This script finds all canonical entities where embedding_vector IS NULL
and generates embeddings using the same SentenceTransformer model used
during Stage 1C (llm_deconflict_entity_clusters.py).

Model: sentence-transformers/all-MiniLM-L6-v2

This is needed when canonical entities were created via a batch process
that skipped embedding generation, or when entities need re-embedding
after name changes from Stage 2B LLM deconfliction.

Usage:
    # Embed all entities missing embeddings for a specific country
    python embed_canonical_entities.py --country Iran

    # Embed for all influencer countries
    python embed_canonical_entities.py --influencers

    # Force re-embed ALL entities (even those with existing embeddings)
    python embed_canonical_entities.py --country Iran --force

    # Check status only (don't generate embeddings)
    python embed_canonical_entities.py --country Iran --status

    # Custom batch size
    python embed_canonical_entities.py --country Iran --batch-size 200

    # Dry run
    python embed_canonical_entities.py --country Iran --dry-run
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import yaml
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


def show_status(session, country: str) -> None:
    """Show embedding status for a country's canonical entities."""
    total = session.execute(text('''
        SELECT COUNT(*) FROM canonical_entities
        WHERE initiating_country = :country
    '''), {'country': country}).scalar()

    with_embeddings = session.execute(text('''
        SELECT COUNT(*) FROM canonical_entities
        WHERE initiating_country = :country
          AND embedding_vector IS NOT NULL
    '''), {'country': country}).scalar()

    without_embeddings = total - with_embeddings

    # Breakdown by entity type
    type_breakdown = session.execute(text('''
        SELECT
            entity_type,
            COUNT(*) as total,
            COUNT(embedding_vector) as with_embedding
        FROM canonical_entities
        WHERE initiating_country = :country
        GROUP BY entity_type
        ORDER BY entity_type
    '''), {'country': country}).fetchall()

    print(f"\n  {country}:")
    print(f"    Total canonical entities: {total:,}")
    print(f"    With embeddings:          {with_embeddings:,}")
    print(f"    Missing embeddings:       {without_embeddings:,}")
    if total > 0:
        print(f"    Coverage:                 {(with_embeddings/total)*100:.1f}%")

    if type_breakdown:
        print("\n    By entity type:")
        for etype, total_count, embed_count in type_breakdown:
            missing = total_count - embed_count
            print(f"      {etype}: {embed_count}/{total_count} embedded ({missing} missing)")


def embed_entities_for_country(
    session,
    country: str,
    batch_size: int = 100,
    dry_run: bool = False,
    verbose: bool = True,
    force: bool = False
) -> Dict[str, int]:
    """
    Generate embeddings for canonical entities missing them.

    Args:
        session: Database session
        country: Initiating country
        batch_size: Number of entities to encode at once
        dry_run: If True, don't save changes
        verbose: Print progress
        force: If True, re-embed all entities (not just missing)

    Returns:
        Dict with statistics
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Embedding Canonical Entities: {country}")
        print('='*80)

    # Load entities needing embeddings
    if force:
        query = '''
            SELECT id, canonical_name, entity_type
            FROM canonical_entities
            WHERE initiating_country = :country
            ORDER BY entity_type, canonical_name
        '''
    else:
        query = '''
            SELECT id, canonical_name, entity_type
            FROM canonical_entities
            WHERE initiating_country = :country
              AND embedding_vector IS NULL
            ORDER BY entity_type, canonical_name
        '''

    entities = session.execute(text(query), {'country': country}).fetchall()

    if not entities:
        if verbose:
            print(f"  No entities need embedding for {country}")
        return {'total': 0, 'embedded': 0}

    if verbose:
        mode = "all (force)" if force else "missing only"
        print(f"  Found {len(entities):,} entities to embed ({mode})")

    if dry_run:
        if verbose:
            print(f"  [DRY RUN] Would embed {len(entities):,} entities")
        return {'total': len(entities), 'embedded': 0}

    # Load the sentence transformer model
    if verbose:
        print("  Loading sentence transformer model (all-MiniLM-L6-v2)...")

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

    if verbose:
        print(f"  Model loaded. Generating embeddings in batches of {batch_size}...")

    stats = {'total': len(entities), 'embedded': 0}

    # Process in batches
    for batch_start in range(0, len(entities), batch_size):
        batch_end = min(batch_start + batch_size, len(entities))
        batch = entities[batch_start:batch_end]

        # Extract names for encoding
        names = [row[1] for row in batch]

        # Batch encode
        embeddings = model.encode(names)

        # Update each entity
        for idx, (entity_id, entity_name, entity_type) in enumerate(batch):
            embedding = embeddings[idx].tolist()

            session.execute(text('''
                UPDATE canonical_entities
                SET embedding_vector = :embedding
                WHERE id = :entity_id
            '''), {
                'embedding': embedding,
                'entity_id': entity_id
            })

            stats['embedded'] += 1

        # Commit after each batch
        session.commit()

        if verbose:
            progress = (batch_end / len(entities)) * 100
            print(f"    Batch {batch_start//batch_size + 1}: {batch_end:,}/{len(entities):,} entities ({progress:.0f}%)")

    if verbose:
        print(f"\n  [DONE] Embedded {stats['embedded']:,} entities")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Generate embeddings for canonical entities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')

    # Options
    parser.add_argument('--status', action='store_true', help='Show embedding status only')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be embedded without saving')
    parser.add_argument('--force', action='store_true', help='Re-embed all entities, not just missing')
    parser.add_argument('--batch-size', type=int, default=100, help='Entities per encoding batch (default: 100)')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print progress')

    args = parser.parse_args()

    # Get countries
    if args.influencers:
        config = load_config()
        countries = config['influencers']
    elif args.country:
        countries = [args.country]
    else:
        print("[ERROR] Must specify either --country or --influencers")
        return

    print("=" * 80)
    print("CANONICAL ENTITY EMBEDDING GENERATION")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    print("Model: sentence-transformers/all-MiniLM-L6-v2")
    if args.status:
        print("[STATUS MODE]")
    elif args.dry_run:
        print("[DRY RUN MODE]")
    elif args.force:
        print("[FORCE MODE] Re-embedding all entities")
    print("=" * 80)

    with get_session() as session:
        if args.status:
            for country in countries:
                show_status(session, country)
            print()
            return

        overall = {'total': 0, 'embedded': 0}

        for country in countries:
            stats = embed_entities_for_country(
                session,
                country,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                verbose=args.verbose,
                force=args.force
            )
            overall['total'] += stats['total']
            overall['embedded'] += stats['embedded']

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total entities needing embeddings: {overall['total']:,}")
    if not args.dry_run:
        print(f"Entities embedded: {overall['embedded']:,}")
    print("=" * 80)


if __name__ == "__main__":
    main()
