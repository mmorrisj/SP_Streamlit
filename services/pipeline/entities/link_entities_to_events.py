"""
Stage 3A: Link Entities to Events via Shared Document IDs

Populates the entity-event linkage by joining on overlapping doc_ids arrays:
- daily_entity_mentions.associated_event_ids  (per-day linkage)
- canonical_entities.associated_events         (aggregate linkage)

Logic:
  For each daily_entity_mention, find canonical_events whose daily_event_mentions
  share doc_ids using PostgreSQL's && (array overlap) operator.

Filters:
  - Only master events (master_event_id IS NULL)
  - Same initiating_country
  - No recipient country filter (track but don't filter)

PIPELINE CONTEXT:
  - Stage 1-2: Entity extraction, clustering, consolidation, merge
  - Stage 3A: THIS SCRIPT - Links entities to events
  - Stage 3B: build_entity_cooccurrence.py - Entity co-occurrence network
  - Stage 3C: generate_entity_descriptions.py - LLM entity profiles

Usage:
    python link_entities_to_events.py --influencers
    python link_entities_to_events.py --country Iran
    python link_entities_to_events.py --influencers --dry-run
    python link_entities_to_events.py --country China --force
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


def link_entities_for_country(
    session,
    country: str,
    dry_run: bool = False,
    verbose: bool = True,
    force: bool = False,
    batch_size: int = 500
) -> Dict[str, int]:
    """
    Link entities to events for a specific country via shared doc_ids.

    Args:
        session: Database session
        country: Initiating country
        dry_run: If True, don't save changes
        verbose: Print progress
        force: If True, clear existing linkages first
        batch_size: Commit every N mentions

    Returns:
        Statistics dict
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Linking Entities to Events: {country}")
        print('='*80)

    # Force mode: clear existing linkages
    if force and not dry_run:
        if verbose:
            print("  [FORCE] Clearing existing entity-event linkages...")
        session.execute(text('''
            UPDATE daily_entity_mentions
            SET associated_event_ids = '{}'
            WHERE initiating_country = :country
        '''), {'country': country})
        session.execute(text('''
            UPDATE canonical_entities
            SET associated_events = '{}'
            WHERE initiating_country = :country
              AND master_entity_id IS NULL
        '''), {'country': country})
        session.commit()

    # Load daily_entity_mentions needing linkage
    mentions = session.execute(text('''
        SELECT dem.id, dem.canonical_entity_id, dem.mention_date, dem.doc_ids
        FROM daily_entity_mentions dem
        WHERE dem.initiating_country = :country
          AND (dem.associated_event_ids IS NULL
               OR cardinality(dem.associated_event_ids) = 0)
          AND dem.doc_ids IS NOT NULL
          AND cardinality(dem.doc_ids) > 0
        ORDER BY dem.mention_date
    '''), {'country': country}).fetchall()

    if not mentions:
        if verbose:
            print("  No unlinked daily entity mentions found")
        return {'mentions_processed': 0, 'mentions_linked': 0, 'total_event_links': 0}

    if verbose:
        print(f"  Found {len(mentions):,} daily entity mentions to process")

    # Check how many master events exist for this country
    event_count = session.execute(text('''
        SELECT COUNT(*) FROM canonical_events
        WHERE initiating_country = :country
          AND master_event_id IS NULL
    '''), {'country': country}).scalar()

    if verbose:
        print(f"  Master canonical events available: {event_count:,}")

    if event_count == 0:
        if verbose:
            print("  No master events to link against")
        return {'mentions_processed': 0, 'mentions_linked': 0, 'total_event_links': 0}

    stats = {
        'mentions_processed': 0,
        'mentions_linked': 0,
        'total_event_links': 0
    }

    mentions_since_commit = 0

    for i, (mention_id, entity_id, mention_date, doc_ids) in enumerate(mentions, 1):
        # Find canonical events whose daily_event_mentions share doc_ids
        matched_events = session.execute(text('''
            SELECT DISTINCT ce.id::text
            FROM daily_event_mentions dvm
            JOIN canonical_events ce ON dvm.canonical_event_id = ce.id
            WHERE dvm.initiating_country = :country
              AND dvm.doc_ids && :entity_doc_ids
              AND ce.master_event_id IS NULL
        '''), {
            'country': country,
            'entity_doc_ids': doc_ids
        }).fetchall()

        event_ids = [row[0] for row in matched_events]

        stats['mentions_processed'] += 1

        if event_ids:
            stats['mentions_linked'] += 1
            stats['total_event_links'] += len(event_ids)

            if not dry_run:
                session.execute(text('''
                    UPDATE daily_entity_mentions
                    SET associated_event_ids = :event_ids
                    WHERE id = :mention_id
                '''), {
                    'event_ids': event_ids,
                    'mention_id': mention_id
                })

        mentions_since_commit += 1

        # Checkpoint
        if not dry_run and mentions_since_commit >= batch_size:
            session.commit()
            if verbose:
                print(f"    [CHECKPOINT] {i:,}/{len(mentions):,} mentions processed "
                      f"({stats['mentions_linked']:,} linked, {stats['total_event_links']:,} event links)")
            mentions_since_commit = 0

        # Progress update
        elif verbose and i % 1000 == 0:
            print(f"    Progress: {i:,}/{len(mentions):,} mentions...")

    # Final commit for mentions
    if not dry_run and mentions_since_commit > 0:
        session.commit()

    if verbose:
        print(f"\n  Mentions processed: {stats['mentions_processed']:,}")
        print(f"  Mentions with event links: {stats['mentions_linked']:,}")
        print(f"  Total event associations: {stats['total_event_links']:,}")

    # Aggregate to canonical_entities.associated_events
    if not dry_run and stats['mentions_linked'] > 0:
        if verbose:
            print("\n  Aggregating event links to canonical entities...")

        session.execute(text('''
            UPDATE canonical_entities ce
            SET associated_events = sub.all_events
            FROM (
                SELECT
                    dem.canonical_entity_id,
                    array_agg(DISTINCT unnest_val) as all_events
                FROM daily_entity_mentions dem,
                     unnest(dem.associated_event_ids) as unnest_val
                WHERE dem.initiating_country = :country
                  AND dem.associated_event_ids IS NOT NULL
                  AND cardinality(dem.associated_event_ids) > 0
                GROUP BY dem.canonical_entity_id
            ) sub
            WHERE ce.id = sub.canonical_entity_id
              AND ce.master_entity_id IS NULL
        '''), {'country': country})

        session.commit()

        # Count entities with events
        entities_with_events = session.execute(text('''
            SELECT COUNT(*) FROM canonical_entities
            WHERE initiating_country = :country
              AND master_entity_id IS NULL
              AND associated_events IS NOT NULL
              AND cardinality(associated_events) > 0
        '''), {'country': country}).scalar()

        if verbose:
            print(f"  Entities with associated events: {entities_with_events:,}")

    elif dry_run and verbose:
        print(f"\n  [DRY RUN] Would link {stats['mentions_linked']:,} mentions to events")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Link entities to events via shared document IDs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
    parser.add_argument('--force', action='store_true', help='Clear existing linkages before re-running')
    parser.add_argument('--batch-size', type=int, default=500, help='Commit every N mentions (default: 500)')
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
    print("LINK ENTITIES TO EVENTS")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    if args.dry_run:
        print("[DRY RUN MODE]")
    if args.force:
        print("[FORCE MODE] Clearing existing linkages")
    print("=" * 80)

    overall = {
        'total_mentions_processed': 0,
        'total_mentions_linked': 0,
        'total_event_links': 0
    }

    with get_session() as session:
        for country in countries:
            stats = link_entities_for_country(
                session, country,
                dry_run=args.dry_run,
                verbose=args.verbose,
                force=args.force,
                batch_size=args.batch_size
            )
            overall['total_mentions_processed'] += stats['mentions_processed']
            overall['total_mentions_linked'] += stats['mentions_linked']
            overall['total_event_links'] += stats['total_event_links']

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total mentions processed: {overall['total_mentions_processed']:,}")
    print(f"Mentions with event links: {overall['total_mentions_linked']:,}")
    print(f"Total event associations: {overall['total_event_links']:,}")
    print("=" * 80)


if __name__ == "__main__":
    main()
