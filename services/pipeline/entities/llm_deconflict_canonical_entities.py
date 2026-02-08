"""
Stage 2B: LLM Validation of Canonical Entity Consolidation

Part of the two-stage batch consolidation pipeline for entity processing.

This script processes consolidated canonical entity groups and uses an LLM to:
1. Validate that entities in each group truly represent the same real-world entity
2. Pick the best canonical name from the group
3. Pick the best primary_role for the entity
4. Split groups that were incorrectly merged by embedding similarity

PIPELINE CONTEXT:
  - Stage 1A: extract_daily_entities.py - Extracts raw entities from documents
  - Stage 1B: cluster_daily_entities.py - Clusters entities per day using DBSCAN
  - Stage 1C: llm_deconflict_entity_clusters.py - LLM validates clusters, creates canonical entities
  - Stage 2A: consolidate_all_entities.py - Groups entities using embedding similarity
  - Stage 2B: THIS SCRIPT - LLM validates groupings, picks best names/roles, splits if needed
  - Stage 2C: merge_canonical_entities.py - Consolidates daily mentions

Processing Strategy:
1. Load all entity groups (canonical entities with same master_entity_id)
2. For each group, send entity info to LLM for review (name, type, role, affiliations)
3. LLM validates grouping and selects best canonical name and primary role
4. If group contains multiple distinct entities, split into subgroups
5. Update database with LLM recommendations

Usage:
    # Process specific country
    python llm_deconflict_canonical_entities.py --country China

    # Process all influencers
    python llm_deconflict_canonical_entities.py --influencers

    # Process all countries with consolidated entities
    python llm_deconflict_canonical_entities.py --all

    # Resume from last checkpoint (skip already-validated groups)
    python llm_deconflict_canonical_entities.py --influencers --resume

    # Force reprocessing of all groups (even if already validated)
    python llm_deconflict_canonical_entities.py --country China --force

    # Custom batch size for more frequent checkpointing
    python llm_deconflict_canonical_entities.py --country China --batch-size 5

    # Dry run
    python llm_deconflict_canonical_entities.py --all --dry-run

Checkpoint/Resume:
    The script commits progress every --batch-size groups (default: 10) and marks
    each master entity as llm_validated=True after processing. If interrupted, use the
    --resume flag to skip already-validated groups and continue where you left off.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
import re
import yaml
from typing import List, Dict, Optional
from collections import defaultdict
from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import gai


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


def load_entity_groups(
    session,
    country: Optional[str] = None,
    resume: bool = False,
    force: bool = False
) -> Dict[str, List[Dict]]:
    """
    Load all consolidated entity groups.

    Args:
        session: Database session
        country: Filter by specific country (optional)
        resume: If True, skip groups that have already been validated by LLM
        force: If True, process all groups regardless of validation status (overrides resume)

    Returns:
        Dict mapping master_entity_id to list of entities in that group
    """
    # Load child entities (those with master_entity_id set)
    query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.entity_type,
            ce.primary_role,
            ce.master_entity_id,
            ce.alternative_names,
            ce.country_affiliations,
            ce.entity_description,
            COALESCE(SUM(dem.document_count), 0) as total_documents,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM canonical_entities ce
        LEFT JOIN daily_entity_mentions dem ON ce.id = dem.canonical_entity_id
        WHERE ce.master_entity_id IS NOT NULL
    """

    params = {}
    if country:
        query += " AND ce.initiating_country = :country"
        params['country'] = country

    # If resume mode (and not force), exclude groups where master is already validated
    if resume and not force:
        query += """
            AND ce.master_entity_id IN (
                SELECT id FROM canonical_entities
                WHERE master_entity_id IS NULL
                AND (llm_validated = FALSE OR llm_validated IS NULL)
            )
        """

    query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.entity_type,
                 ce.primary_role, ce.master_entity_id, ce.alternative_names,
                 ce.country_affiliations, ce.entity_description
        ORDER BY ce.master_entity_id, total_documents DESC
    """

    result = session.execute(text(query), params).fetchall()

    # Group by master_entity_id
    groups = defaultdict(list)
    for row in result:
        master_id = str(row[5])
        groups[master_id].append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'entity_type': str(row[3]) if row[3] else None,
            'primary_role': str(row[4]) if row[4] else None,
            'master_entity_id': row[5],
            'alternative_names': row[6] or [],
            'country_affiliations': row[7] or [],
            'entity_description': row[8],
            'total_documents': row[9],
            'days_mentioned': row[10]
        })

    # Also load the master entities themselves
    master_query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.entity_type,
            ce.primary_role,
            ce.alternative_names,
            ce.country_affiliations,
            ce.entity_description,
            COALESCE(SUM(dem.document_count), 0) as total_documents,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM canonical_entities ce
        LEFT JOIN daily_entity_mentions dem ON ce.id = dem.canonical_entity_id
        WHERE ce.master_entity_id IS NULL
          AND EXISTS (
              SELECT 1 FROM canonical_entities child
              WHERE child.master_entity_id = ce.id
          )
    """

    if country:
        master_query += " AND ce.initiating_country = :country"

    if resume and not force:
        master_query += " AND (ce.llm_validated = FALSE OR ce.llm_validated IS NULL)"

    master_query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.entity_type,
                 ce.primary_role, ce.alternative_names, ce.country_affiliations,
                 ce.entity_description
    """

    master_result = session.execute(text(master_query), params).fetchall()

    for row in master_result:
        master_id = str(row[0])
        if master_id in groups:
            groups[master_id].insert(0, {
                'id': row[0],
                'canonical_name': row[1],
                'initiating_country': row[2],
                'entity_type': str(row[3]) if row[3] else None,
                'primary_role': str(row[4]) if row[4] else None,
                'master_entity_id': None,
                'alternative_names': row[5] or [],
                'country_affiliations': row[6] or [],
                'entity_description': row[7],
                'total_documents': row[8],
                'days_mentioned': row[9]
            })

    return groups


VALID_ROLES = [
    "government_official", "diplomat", "business_leader", "cultural_figure",
    "military_official", "academic", "media_figure", "civil_society",
    "implementing_organization", "funding_organization", "recipient_institution",
    "infrastructure_project", "venue", "other"
]


def llm_review_group(entities: List[Dict], verbose: bool = True) -> Dict:
    """
    Use LLM to review an entity group and select the best canonical name and role.

    Returns:
        Dict with:
        - same_entity: bool (whether all entities represent the same real-world entity)
        - best_canonical_name: str (best name to use)
        - best_primary_role: str (best role from EntityRoleEnum values)
        - reasoning: str (explanation)
        - should_split: bool (whether group should be split)
        - split_groups: list of lists (if should_split=True)
    """
    # Build entity info list with rich context
    entity_lines = []
    for i, e in enumerate(entities):
        line = f"{i+1}. \"{e['canonical_name']}\""
        line += f" ({e['total_documents']} docs, {e['days_mentioned']} days)"
        if e.get('primary_role'):
            line += f" [role: {e['primary_role']}]"
        if e.get('country_affiliations'):
            line += f" [affiliations: {', '.join(e['country_affiliations'][:5])}]"
        if e.get('alternative_names'):
            line += f" [aliases: {', '.join(e['alternative_names'][:3])}]"
        if e.get('entity_description'):
            desc = e['entity_description'][:100]
            line += f" [desc: {desc}]"
        entity_lines.append(line)

    names_list = "\n".join(entity_lines)
    entity_type = entities[0].get('entity_type', 'unknown')

    sys_prompt = f"""You are an expert at analyzing entity names to determine if they represent the same real-world {entity_type}.

**Your Task:**
1. Determine if all entity names refer to the SAME real-world {entity_type} (even if spelled differently or using aliases)
2. If they are the same entity, pick the BEST canonical name
3. Pick the best primary_role from the allowed values
4. If they are different entities that were incorrectly grouped, identify how to split them

**Guidelines for "Same Entity":**
For PERSON type:
  - Same person, different name forms: "Xi Jinping" vs "President Xi" vs "Xi"
  - Same person, different transliterations: "Mohammed bin Salman" vs "MBS" vs "Muhammad bin Salman"
  - Different people with same/similar name: SPLIT these (e.g., "Wang Wei" the diplomat vs "Wang Wei" the artist)

For ORGANIZATION type:
  - Same org, different abbreviations: "United Nations" vs "UN"
  - Same org, different branches: Consider if they function as one entity or distinct units
  - Different orgs with similar names: SPLIT these

For COMPANY type:
  - Same company, different name forms: "Huawei Technologies" vs "Huawei"
  - Parent vs subsidiary: Generally SPLIT unless they're commonly referred to interchangeably

**Guidelines for Picking Best Name:**
1. Prefer full formal name over abbreviations: "Xi Jinping" > "Xi"
2. Prefer widely recognized form: "Huawei" > "Huawei Technologies Co., Ltd."
3. Prefer standard English transliteration for non-English names
4. Consider document count - higher coverage often indicates more standard naming

**Allowed primary_role values:**
{', '.join(VALID_ROLES)}"""

    user_prompt = f"""Entity group to analyze:
{names_list}

**Entity Type:** {entity_type}
**Country:** {entities[0]['initiating_country']}
**Group size:** {len(entities)} entities

**Analyze:**
1. Do all these entity names refer to the SAME real-world {entity_type}?
2. If yes, which name is the best canonical name?
3. What is the best primary_role for this entity?
4. If no, how should this group be split?

**Output JSON format:**
{{
    "same_entity": true/false,
    "best_canonical_name": "The best name from the list (if same_entity=true)",
    "best_primary_role": "one of the allowed role values",
    "reasoning": "2-3 sentence explanation of your decision",
    "should_split": true/false,
    "split_groups": [
        {{"indices": [1,2], "canonical_name": "Best name for subgroup", "primary_role": "role"}},
        {{"indices": [3,4,5], "canonical_name": "Best name for subgroup", "primary_role": "role"}}
    ]
}}

Now analyze the entity group above and return your assessment as JSON."""

    try:
        if verbose:
            print(f"    [LLM] Reviewing {len(entities)} entities...")

        response = gai(sys_prompt, user_prompt, model="gpt-4o-mini", use_proxy=True)

        # Parse JSON response
        if isinstance(response, dict):
            result = response
        else:
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
            else:
                result = json.loads(response)

        if 'same_entity' not in result:
            raise ValueError("Invalid LLM response: missing 'same_entity' field")

        # Validate primary_role
        if result.get('best_primary_role') and result['best_primary_role'] not in VALID_ROLES:
            result['best_primary_role'] = 'other'

        return result

    except Exception as e:
        if verbose:
            print(f"    [WARNING] LLM review failed: {e}")

        return {
            'same_entity': True,
            'best_canonical_name': entities[0]['canonical_name'],
            'best_primary_role': entities[0].get('primary_role', 'other'),
            'reasoning': f'LLM review failed: {str(e)}. Defaulting to highest document count.',
            'should_split': False,
            'split_groups': []
        }


def process_country(
    session,
    country: str,
    dry_run: bool = False,
    verbose: bool = True,
    resume: bool = False,
    force: bool = False,
    batch_size: int = 10
) -> Dict[str, int]:
    """
    Process all entity groups for a specific country.

    Args:
        session: Database session
        country: Country to process
        dry_run: If True, don't save changes
        verbose: If True, print progress
        resume: If True, skip already-validated groups
        force: If True, reprocess all groups regardless of validation status
        batch_size: Commit every N groups (for checkpointing)

    Returns:
        Statistics dict
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"LLM Deconfliction (Entities): {country}")
        if force:
            print("  [FORCE MODE] Reprocessing all groups (ignoring validation status)")
        elif resume:
            print("  [RESUME MODE] Skipping already-validated groups")
        print(f"{'='*80}")

    # Load entity groups
    groups = load_entity_groups(session, country, resume=resume, force=force)

    if len(groups) == 0:
        if verbose:
            print("  No consolidated entity groups found")
        return {'groups': 0, 'validated': 0, 'split': 0, 'renamed': 0, 'skipped': 0}

    if verbose:
        print(f"  Found {len(groups)} consolidated entity groups to process")

    stats = {
        'groups': len(groups),
        'validated': 0,
        'split': 0,
        'renamed': 0,
        'skipped': 0
    }

    groups_since_commit = 0

    for i, (master_id, group_entities) in enumerate(groups.items(), 1):
        if verbose and i % 10 == 0:
            print(f"  Progress: {i}/{len(groups)} groups processed...")

        # Skip single-entity groups
        if len(group_entities) <= 1:
            stats['skipped'] += 1

            if not dry_run:
                session.execute(
                    text("""UPDATE canonical_entities
                           SET llm_validated = TRUE, llm_validated_at = NOW()
                           WHERE id = :master_id"""),
                    {'master_id': master_id}
                )
            continue

        # Get LLM review
        review = llm_review_group(group_entities, verbose=False)

        if verbose:
            best_name_raw = review.get('best_canonical_name')
            safe_name = best_name_raw.encode('ascii', 'replace').decode('ascii') if best_name_raw else 'N/A'
            print(f"\n  Group {i}/{len(groups)}: {len(group_entities)} entities ({group_entities[0].get('entity_type', '?')})")
            print(f"    Current master: {group_entities[0]['canonical_name'].encode('ascii', 'replace').decode('ascii')}")
            print(f"    LLM decision: same_entity={review.get('same_entity')}, should_split={review.get('should_split', False)}")
            if review.get('same_entity') and best_name_raw:
                print(f"    Best name: {safe_name}")
            if review.get('best_primary_role'):
                print(f"    Best role: {review['best_primary_role']}")
            print(f"    Reasoning: {review.get('reasoning', 'N/A')[:100]}...")

        # Handle splitting
        if review.get('should_split') and review.get('split_groups'):
            if verbose:
                print(f"    [SPLIT] Group should be split into {len(review['split_groups'])} subgroups")
            stats['split'] += 1

            if not dry_run:
                for subgroup_idx, subgroup in enumerate(review['split_groups']):
                    indices = subgroup.get('indices', [])
                    new_canonical_name = subgroup.get('canonical_name')
                    new_role = subgroup.get('primary_role')

                    if not indices or not new_canonical_name:
                        continue

                    # Get entities in this subgroup (convert 1-indexed to 0-indexed)
                    subgroup_entities = [group_entities[idx-1] for idx in indices if 0 < idx <= len(group_entities)]

                    if len(subgroup_entities) == 0:
                        continue

                    # Find the entity with this name, or use highest doc count
                    best_entity = next((e for e in subgroup_entities if e['canonical_name'] == new_canonical_name), None)
                    if not best_entity:
                        best_entity = max(subgroup_entities, key=lambda e: e['total_documents'])

                    new_master_id = best_entity['id']

                    # Build update for the new master
                    update_sql = """UPDATE canonical_entities
                                   SET master_entity_id = NULL,
                                       llm_validated = TRUE,
                                       llm_validated_at = NOW()"""
                    update_params = {'new_master': new_master_id}

                    if new_role and new_role in VALID_ROLES:
                        update_sql += ", primary_role = :new_role"
                        update_params['new_role'] = new_role

                    update_sql += " WHERE id = :new_master"

                    session.execute(text(update_sql), update_params)

                    # Point all other entities in this subgroup to the new master
                    for entity in subgroup_entities:
                        if entity['id'] != new_master_id:
                            session.execute(
                                text('UPDATE canonical_entities SET master_entity_id = :new_master WHERE id = :child_id'),
                                {'new_master': new_master_id, 'child_id': entity['id']}
                            )

                    if verbose:
                        print(f"      Created subgroup with master: {new_canonical_name}")

        # Handle rename / role update
        elif review.get('same_entity') and review.get('best_canonical_name'):
            best_name = review['best_canonical_name']
            best_role = review.get('best_primary_role')
            current_master_name = group_entities[0]['canonical_name']

            if best_name != current_master_name:
                if verbose:
                    print("    [RENAME] Master entity name should change")
                stats['renamed'] += 1

                if not dry_run:
                    # Find the entity with this name in the group
                    best_entity = next((e for e in group_entities if e['canonical_name'] == best_name), None)

                    if best_entity and best_entity['id'] != group_entities[0]['id']:
                        old_master_id = group_entities[0]['id']
                        new_master_id = best_entity['id']

                        # Set old master to point to new master
                        session.execute(
                            text('UPDATE canonical_entities SET master_entity_id = :new_master WHERE id = :old_master'),
                            {'new_master': new_master_id, 'old_master': old_master_id}
                        )

                        # Update all other children to point to new master
                        session.execute(
                            text('UPDATE canonical_entities SET master_entity_id = :new_master WHERE master_entity_id = :old_master'),
                            {'new_master': new_master_id, 'old_master': old_master_id}
                        )

                        # Set new master's master_entity_id to NULL and mark as validated
                        update_sql = """UPDATE canonical_entities
                                       SET master_entity_id = NULL,
                                           llm_validated = TRUE,
                                           llm_validated_at = NOW()"""
                        update_params = {'new_master': new_master_id}

                        if best_role and best_role in VALID_ROLES:
                            update_sql += ", primary_role = :new_role"
                            update_params['new_role'] = best_role

                        update_sql += " WHERE id = :new_master"
                        session.execute(text(update_sql), update_params)

                        if verbose:
                            print("    [UPDATED] Swapped master entity")
                    else:
                        # Mark current master as validated, update role if needed
                        update_sql = """UPDATE canonical_entities
                                       SET llm_validated = TRUE,
                                           llm_validated_at = NOW()"""
                        update_params = {'master_id': group_entities[0]['id']}

                        if best_role and best_role in VALID_ROLES:
                            update_sql += ", primary_role = :new_role"
                            update_params['new_role'] = best_role

                        update_sql += " WHERE id = :master_id"
                        session.execute(text(update_sql), update_params)
            else:
                # No name change needed, but maybe update role
                if not dry_run:
                    update_sql = """UPDATE canonical_entities
                                   SET llm_validated = TRUE,
                                       llm_validated_at = NOW()"""
                    update_params = {'master_id': master_id}

                    if best_role and best_role in VALID_ROLES:
                        update_sql += ", primary_role = :new_role"
                        update_params['new_role'] = best_role

                    update_sql += " WHERE id = :master_id"
                    session.execute(text(update_sql), update_params)
        else:
            # No changes needed, just mark as validated
            if not dry_run:
                session.execute(
                    text("""UPDATE canonical_entities
                           SET llm_validated = TRUE,
                                llm_validated_at = NOW()
                           WHERE id = :master_id"""),
                    {'master_id': master_id}
                )

        stats['validated'] += 1
        groups_since_commit += 1

        # Commit every batch_size groups for checkpoint/resume
        if not dry_run and groups_since_commit >= batch_size:
            session.commit()
            if verbose:
                print(f"  [CHECKPOINT] Committed progress ({i}/{len(groups)} groups)")
            groups_since_commit = 0

    # Final commit
    if not dry_run and groups_since_commit > 0:
        session.commit()
        if verbose:
            print("\n  [COMMITTED] Final batch")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="LLM Deconfliction for Consolidated Canonical Entities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')
    parser.add_argument('--all', action='store_true', help='Process all countries')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving to database')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print detailed progress')
    parser.add_argument('--resume', action='store_true', help='Resume from last checkpoint (skip already-validated groups)')
    parser.add_argument('--force', action='store_true', help='Force reprocessing of all groups, even if already validated')
    parser.add_argument('--batch-size', type=int, default=10, help='Commit every N groups (default: 10, for checkpointing)')

    args = parser.parse_args()

    # Get countries to process
    if args.influencers:
        config = load_config()
        countries = config['influencers']
    elif args.country:
        countries = [args.country]
    elif args.all:
        countries = None
    else:
        print("[ERROR] Must specify --country, --influencers, or --all")
        return

    print("="*80)
    print("LLM DECONFLICTION FOR CONSOLIDATED CANONICAL ENTITIES")
    print("="*80)
    if countries:
        print(f"Countries: {', '.join(countries)}")
    else:
        print("Countries: All")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    if args.resume:
        print("[RESUME MODE] Skipping already-validated groups")
    if args.force:
        print("[FORCE MODE] Reprocessing all groups")
    print(f"Batch size: {args.batch_size} (commit every N groups)")
    print("="*80)

    overall_stats = {
        'total_groups': 0,
        'total_validated': 0,
        'total_split': 0,
        'total_renamed': 0,
        'total_skipped': 0
    }

    with get_session() as session:
        if countries is None:
            result = session.execute(text('''
                SELECT DISTINCT initiating_country
                FROM canonical_entities
                WHERE master_entity_id IS NOT NULL
                ORDER BY initiating_country
            ''')).fetchall()
            countries = [row[0] for row in result]

        for country in countries:
            stats = process_country(
                session,
                country,
                dry_run=args.dry_run,
                verbose=args.verbose,
                resume=args.resume,
                force=args.force,
                batch_size=args.batch_size
            )
            overall_stats['total_groups'] += stats['groups']
            overall_stats['total_validated'] += stats['validated']
            overall_stats['total_split'] += stats['split']
            overall_stats['total_renamed'] += stats['renamed']
            overall_stats['total_skipped'] += stats.get('skipped', 0)

    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total entity groups: {overall_stats['total_groups']}")
    print(f"Groups validated: {overall_stats['total_validated']}")
    print(f"Groups split: {overall_stats['total_split']}")
    print(f"Groups renamed: {overall_stats['total_renamed']}")
    print(f"Groups skipped (single-entity): {overall_stats['total_skipped']}")
    if args.force:
        print("\n[FORCE MODE] All groups were reprocessed")
    elif args.resume:
        print("\n[RESUME MODE] Already-validated groups were skipped")
    print("="*80)


if __name__ == "__main__":
    main()
