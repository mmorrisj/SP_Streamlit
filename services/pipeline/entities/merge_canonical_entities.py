"""
Stage 2C: Merge Fragmented Canonical Entities into Multi-Day Entities

Part of the two-stage batch consolidation pipeline for entity processing.

PIPELINE CONTEXT:
  - Stage 1A: extract_daily_entities.py - Extracts raw entities from documents
  - Stage 1B: cluster_daily_entities.py - Clusters entities per day using DBSCAN
  - Stage 1C: llm_deconflict_entity_clusters.py - LLM validates clusters, creates canonical entities
  - Stage 2A: consolidate_all_entities.py - Groups entities using embedding similarity
  - Stage 2B: llm_deconflict_canonical_entities.py - LLM validates groupings
  - Stage 2C: THIS SCRIPT - Consolidates daily_entity_mentions into multi-day entities

WHAT THIS SCRIPT DOES:
  1. For each LLM-validated master entity (master_entity_id IS NULL AND llm_validated = TRUE)
  2. Find all child entities for that master (master_entity_id = master.id)
  3. Reassign all daily_entity_mentions from children to master
  4. Handle date conflicts by merging doc_ids arrays and summing document_count
  5. Merge metadata arrays/dicts from children into master (alternative_names,
     country_affiliations, primary_categories, primary_recipients)
  6. Delete the now-empty child canonical entities

IMPORTANT: Only processes validated masters to prevent over-consolidation errors from Stage 2A

RESULT:
  - Master entities have MULTIPLE days of daily_entity_mentions
  - True multi-day entity tracking across the dataset
  - Full traceability from master entities -> daily mentions -> source documents

Usage:
    python merge_canonical_entities.py --influencers
    python merge_canonical_entities.py --country China
    python merge_canonical_entities.py --influencers --dry-run
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
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


def merge_jsonb_dicts(master_dict: dict, child_dict: dict) -> dict:
    """
    Merge two JSONB dicts by summing their counts.
    E.g., master: {"Economic": 5, "Cultural": 3} + child: {"Economic": 2, "Military": 1}
       -> {"Economic": 7, "Cultural": 3, "Military": 1}
    """
    if not master_dict:
        master_dict = {}
    if not child_dict:
        return master_dict

    merged = dict(master_dict)
    for key, value in child_dict.items():
        if key in merged:
            merged[key] = merged[key] + value
        else:
            merged[key] = value
    return merged


def merge_arrays(master_arr: list, child_arr: list) -> list:
    """
    Merge two arrays, deduplicating while preserving order.
    """
    if not master_arr:
        master_arr = []
    if not child_arr:
        return master_arr

    seen = set(master_arr)
    merged = list(master_arr)
    for item in child_arr:
        if item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


def merge_canonical_entities_for_country(
    session,
    country: str,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Merge fragmented canonical entities into multi-day entities for a specific country.

    Args:
        session: Database session
        country: Initiating country
        dry_run: If True, don't save changes to database
        verbose: Print progress

    Returns:
        Dict with statistics
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Merging Canonical Entities: {country}")
        print('='*80)

    # Get all LLM-validated master entities for this country
    master_entities = session.execute(text('''
        SELECT id, canonical_name, entity_type, primary_role,
               alternative_names, country_affiliations,
               primary_categories, primary_recipients, associated_events
        FROM canonical_entities
        WHERE initiating_country = :country
          AND master_entity_id IS NULL
          AND llm_validated = TRUE
        ORDER BY canonical_name
    '''), {'country': country}).fetchall()

    if not master_entities:
        if verbose:
            print(f"  No validated master entities found for {country}")
        return {'master_entities': 0, 'child_entities': 0, 'mentions_reassigned': 0, 'entities_deleted': 0}

    if verbose:
        print(f"  Found {len(master_entities)} validated master entities")

    stats = {
        'master_entities': len(master_entities),
        'child_entities': 0,
        'mentions_reassigned': 0,
        'entities_deleted': 0
    }

    for (master_id, master_name, master_type, master_role,
         master_alt_names, master_affiliations,
         master_categories, master_recipients, master_events) in master_entities:

        # Find all child entities for this validated master
        child_entities = session.execute(text('''
            SELECT id, canonical_name, alternative_names, country_affiliations,
                   primary_categories, primary_recipients, associated_events
            FROM canonical_entities
            WHERE master_entity_id = :master_id
        '''), {'master_id': master_id}).fetchall()

        if not child_entities:
            continue

        stats['child_entities'] += len(child_entities)

        if verbose:
            safe_name = master_name.encode('ascii', 'replace').decode('ascii')[:60]
            print(f"\n  Master: {safe_name} ({master_type})")
            print(f"    Found {len(child_entities)} child entities to merge")

        # Track metadata to merge into master
        merged_alt_names = list(master_alt_names or [])
        merged_affiliations = list(master_affiliations or [])
        merged_categories = dict(master_categories or {})
        merged_recipients = dict(master_recipients or {})
        merged_events = list(master_events or [])

        # For each child entity, reassign its daily_entity_mentions to the master
        for (child_id, child_name, child_alt_names, child_affiliations,
             child_categories, child_recipients, child_events) in child_entities:

            # Check how many daily_entity_mentions this child has
            mention_count = session.execute(text('''
                SELECT COUNT(*) FROM daily_entity_mentions
                WHERE canonical_entity_id = :child_id
            '''), {'child_id': child_id}).scalar()

            if mention_count > 0:
                if verbose:
                    safe_child = child_name.encode('ascii', 'replace').decode('ascii')[:50]
                    print(f"      Merging {mention_count} mentions from: {safe_child}")

                stats['mentions_reassigned'] += mention_count

                if not dry_run:
                    # Get all mentions from child
                    child_mentions = session.execute(text('''
                        SELECT id, mention_date, document_count, doc_ids,
                               primary_role_this_day, activities_this_day,
                               associated_event_ids
                        FROM daily_entity_mentions
                        WHERE canonical_entity_id = :child_id
                    '''), {'child_id': child_id}).fetchall()

                    for (mention_id, mention_date, doc_count, doc_ids,
                         role_this_day, activities, event_ids) in child_mentions:
                        # Check if master already has a mention for this date
                        existing = session.execute(text('''
                            SELECT id, document_count, doc_ids, associated_event_ids
                            FROM daily_entity_mentions
                            WHERE canonical_entity_id = :master_id
                              AND mention_date = :mention_date
                        '''), {'master_id': master_id, 'mention_date': mention_date}).fetchone()

                        if existing:
                            # Master already has mention for this date - merge
                            existing_id, existing_count, existing_docs, existing_events = existing
                            new_count = (existing_count or 0) + (doc_count or 0)

                            # Merge doc_ids arrays
                            merged_docs = merge_arrays(existing_docs or [], doc_ids or [])

                            # Merge event_ids arrays
                            merged_evt_ids = merge_arrays(existing_events or [], event_ids or [])

                            session.execute(text('''
                                UPDATE daily_entity_mentions
                                SET document_count = :new_count,
                                    doc_ids = :merged_docs,
                                    associated_event_ids = :merged_events
                                WHERE id = :existing_id
                            '''), {
                                'new_count': new_count,
                                'merged_docs': merged_docs,
                                'merged_events': merged_evt_ids,
                                'existing_id': existing_id
                            })

                            # Delete the child's mention
                            session.execute(text('''
                                DELETE FROM daily_entity_mentions
                                WHERE id = :mention_id
                            '''), {'mention_id': mention_id})
                        else:
                            # No conflict - just reassign to master
                            session.execute(text('''
                                UPDATE daily_entity_mentions
                                SET canonical_entity_id = :master_id
                                WHERE id = :mention_id
                            '''), {'master_id': master_id, 'mention_id': mention_id})

            # Collect metadata from child for merging into master
            # Add child's canonical_name as an alternative name
            if child_name and child_name != master_name:
                merged_alt_names = merge_arrays(merged_alt_names, [child_name])
            merged_alt_names = merge_arrays(merged_alt_names, child_alt_names or [])
            merged_affiliations = merge_arrays(merged_affiliations, child_affiliations or [])
            merged_categories = merge_jsonb_dicts(merged_categories, child_categories or {})
            merged_recipients = merge_jsonb_dicts(merged_recipients, child_recipients or {})
            merged_events = merge_arrays(merged_events, child_events or [])

        # Delete all child entities (they're now empty)
        if not dry_run and len(child_entities) > 0:
            child_ids = [child_id for child_id, *_ in child_entities]

            for child_id in child_ids:
                session.execute(text('''
                    DELETE FROM canonical_entities
                    WHERE id = :child_id
                '''), {'child_id': child_id})

            stats['entities_deleted'] += len(child_ids)

            # Update master entity with merged metadata
            session.execute(text('''
                UPDATE canonical_entities
                SET alternative_names = :alt_names,
                    country_affiliations = :affiliations,
                    primary_categories = :categories,
                    primary_recipients = :recipients,
                    associated_events = :events
                WHERE id = :master_id
            '''), {
                'alt_names': merged_alt_names,
                'affiliations': merged_affiliations,
                'categories': json.dumps(merged_categories),
                'recipients': json.dumps(merged_recipients),
                'events': merged_events,
                'master_id': master_id
            })

            # Update master entity date/count metadata from reassigned mentions
            session.execute(text('''
                UPDATE canonical_entities ce
                SET
                    total_mention_days = sub.mention_days,
                    first_mention_date = sub.earliest_date,
                    last_mention_date = sub.latest_date,
                    total_documents = sub.total_documents
                FROM (
                    SELECT
                        dem.canonical_entity_id,
                        COUNT(DISTINCT dem.mention_date) as mention_days,
                        MIN(dem.mention_date) as earliest_date,
                        MAX(dem.mention_date) as latest_date,
                        SUM(dem.document_count) as total_documents
                    FROM daily_entity_mentions dem
                    WHERE dem.canonical_entity_id = :master_id
                    GROUP BY dem.canonical_entity_id
                ) sub
                WHERE ce.id = sub.canonical_entity_id
            '''), {'master_id': master_id})

    # Commit changes
    if not dry_run and stats['entities_deleted'] > 0:
        session.commit()
        if verbose:
            print(f"\n  [COMMITTED] Reassigned {stats['mentions_reassigned']} mentions")
            print(f"  [COMMITTED] Deleted {stats['entities_deleted']} child entities")
            print("  [COMMITTED] Updated master entity metadata (dates, mentions, categories, recipients)")
    elif dry_run and verbose:
        print(f"\n  [DRY RUN] Would reassign {stats['mentions_reassigned']} mentions")
        print(f"  [DRY RUN] Would delete {stats['entities_deleted']} child entities")

    return stats


def verify_multi_day_entities(
    session,
    country: str,
    verbose: bool = True
) -> None:
    """
    Verify that we now have multi-day entities after merging.
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Verification: Multi-Day Entities for {country}")
        print('='*80)

    multi_day = session.execute(text('''
        SELECT
            ce.canonical_name,
            ce.entity_type,
            COUNT(DISTINCT dem.mention_date) as days,
            MIN(dem.mention_date) as first_date,
            MAX(dem.mention_date) as last_date,
            SUM(dem.document_count) as total_documents
        FROM canonical_entities ce
        JOIN daily_entity_mentions dem ON ce.id = dem.canonical_entity_id
        WHERE ce.initiating_country = :country
          AND ce.master_entity_id IS NULL
        GROUP BY ce.id, ce.canonical_name, ce.entity_type
        HAVING COUNT(DISTINCT dem.mention_date) > 1
        ORDER BY COUNT(DISTINCT dem.mention_date) DESC
        LIMIT 10
    '''), {'country': country}).fetchall()

    if multi_day:
        print(f"  Found {len(multi_day)} multi-day entities (showing top 10):")
        print()
        for name, etype, days, first, last, docs in multi_day:
            safe_name = name.encode('ascii', 'replace').decode('ascii')[:60]
            print(f"  {safe_name} ({etype})")
            print(f"    {days} days: {first} to {last} | {docs:,} total documents")
    else:
        print(f"  WARNING: No multi-day entities found for {country}")


def main():
    parser = argparse.ArgumentParser(
        description="Merge fragmented canonical entities into multi-day entities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true',
                       help='Process all influencer countries from config.yaml')

    # Options
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be merged without saving to database')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Print detailed progress')

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

    print("="*80)
    print("MERGE FRAGMENTED CANONICAL ENTITIES")
    print("="*80)
    print(f"Countries: {', '.join(countries)}")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    print("="*80)

    overall_stats = {
        'total_master_entities': 0,
        'total_child_entities': 0,
        'total_mentions_reassigned': 0,
        'total_entities_deleted': 0
    }

    with get_session() as session:
        for country in countries:
            stats = merge_canonical_entities_for_country(
                session,
                country,
                args.dry_run,
                args.verbose
            )

            overall_stats['total_master_entities'] += stats['master_entities']
            overall_stats['total_child_entities'] += stats['child_entities']
            overall_stats['total_mentions_reassigned'] += stats['mentions_reassigned']
            overall_stats['total_entities_deleted'] += stats['entities_deleted']

            # Verify results
            if not args.dry_run:
                verify_multi_day_entities(session, country, args.verbose)

    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total master entities processed: {overall_stats['total_master_entities']}")
    print(f"Total child entities found: {overall_stats['total_child_entities']}")
    print(f"Daily mentions reassigned: {overall_stats['total_mentions_reassigned']}")
    if not args.dry_run:
        print(f"Child entities deleted: {overall_stats['total_entities_deleted']}")
    print("="*80)


if __name__ == "__main__":
    main()
