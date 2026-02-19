"""
Stage 3C: Generate LLM Entity Descriptions and Key Activities

Generates entity profiles for canonical_entities using LLM:
- entity_description: 2-3 sentence AP-style profile
- key_activities: Structured JSONB with primary function, notable actions, etc.

Context sources:
- Entity metadata: name, type, role, affiliations, categories, recipients
- Activity metrics: total_documents, date range, total_mention_days
- Associated events: from Stage 3A link_entities_to_events.py (if available)

PIPELINE CONTEXT:
  - Stage 1-2: Entity extraction, clustering, consolidation, merge
  - Stage 3A: link_entities_to_events.py - Entity-event linkage
  - Stage 3B: build_entity_cooccurrence.py - Entity co-occurrence network
  - Stage 3C: THIS SCRIPT - LLM entity profiles

Usage:
    python generate_entity_descriptions.py --influencers
    python generate_entity_descriptions.py --country Iran
    python generate_entity_descriptions.py --influencers --min-docs 5
    python generate_entity_descriptions.py --country China --force
    python generate_entity_descriptions.py --influencers --resume
    python generate_entity_descriptions.py --country Iran --dry-run
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
import re
import time
import yaml
from typing import Dict
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


SYS_PROMPT = """You are an expert analyst specializing in international relations and soft power. \
Generate concise, factual entity profiles based on the provided data. \
Use AP (Associated Press) style. Be specific and concrete, avoid generic characterizations. \
Focus on what this entity actually does based on the document evidence provided."""


def build_user_prompt(entity: dict, event_names: list) -> str:
    """Build the LLM prompt for entity description generation."""
    # Format categories and recipients as readable strings
    categories_str = "N/A"
    if entity.get('primary_categories'):
        cats = entity['primary_categories']
        if isinstance(cats, str):
            try:
                cats = json.loads(cats)
            except (json.JSONDecodeError, TypeError):
                cats = {}
        if isinstance(cats, dict) and cats:
            sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]
            categories_str = ", ".join(f"{k} ({v})" for k, v in sorted_cats)

    recipients_str = "N/A"
    if entity.get('primary_recipients'):
        recips = entity['primary_recipients']
        if isinstance(recips, str):
            try:
                recips = json.loads(recips)
            except (json.JSONDecodeError, TypeError):
                recips = {}
        if isinstance(recips, dict) and recips:
            sorted_recips = sorted(recips.items(), key=lambda x: x[1], reverse=True)[:5]
            recipients_str = ", ".join(f"{k} ({v})" for k, v in sorted_recips)

    alt_names_str = ", ".join(entity.get('alternative_names', [])[:5]) or "None"
    affiliations_str = ", ".join(entity.get('country_affiliations', [])[:5]) or "None"
    events_str = ", ".join(event_names[:5]) or "None linked"

    return f"""Generate a profile for this entity based on its activity in diplomatic/soft power documents.

Entity: {entity['canonical_name']}
Type: {entity['entity_type']}
Role: {entity.get('primary_role') or 'Unknown'}
Country context: {entity['initiating_country']}
Country affiliations: {affiliations_str}
Also known as: {alt_names_str}
Active period: {entity['first_mention_date']} to {entity['last_mention_date']} ({entity.get('total_mention_days', 0)} days)
Total documents: {entity['total_documents']}
Top categories: {categories_str}
Top recipient countries: {recipients_str}
Associated events: {events_str}

Return ONLY a JSON object with no additional text:
{{
    "entity_description": "2-3 sentence profile describing who/what this entity is and their role in soft power activities. Be specific about their actions and significance based on the data above.",
    "key_activities": {{
        "primary_function": "One sentence on primary function/role",
        "notable_actions": ["action1", "action2", "action3"],
        "key_relationships": ["relationship1", "relationship2"],
        "geographic_focus": ["country1", "country2"]
    }}
}}"""


def generate_descriptions_for_country(
    session,
    country: str,
    batch_size: int = 20,
    min_docs: int = 3,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Generate LLM descriptions for entities in a specific country.

    Args:
        session: Database session
        country: Initiating country
        batch_size: Commit every N entities (checkpoint)
        min_docs: Only describe entities with at least this many documents
        force: If True, regenerate descriptions even for entities that have them
        dry_run: If True, don't save changes
        verbose: Print progress

    Returns:
        Statistics dict
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Generating Entity Descriptions: {country}")
        print('='*80)

    # Load candidate entities
    filter_clause = ""
    if not force:
        filter_clause = "AND (ce.entity_description IS NULL OR ce.entity_description = '')"

    entities = session.execute(text(f'''
        SELECT
            ce.id::text,
            ce.canonical_name,
            ce.entity_type,
            ce.primary_role,
            ce.initiating_country,
            ce.country_affiliations,
            ce.alternative_names,
            ce.primary_categories,
            ce.primary_recipients,
            ce.total_documents,
            ce.total_mention_days,
            ce.first_mention_date::text,
            ce.last_mention_date::text,
            ce.associated_events
        FROM canonical_entities ce
        WHERE ce.initiating_country = :country
          AND ce.master_entity_id IS NULL
          AND ce.total_documents >= :min_docs
          {filter_clause}
        ORDER BY ce.total_documents DESC
    '''), {'country': country, 'min_docs': min_docs}).fetchall()

    if not entities:
        if verbose:
            print(f"  No entities need descriptions (min_docs={min_docs})")
        return {'total': 0, 'generated': 0, 'failed': 0}

    if verbose:
        mode = "all (force)" if force else "missing only"
        print(f"  Found {len(entities):,} entities to process ({mode})")

    if dry_run:
        if verbose:
            print(f"  [DRY RUN] Would generate descriptions for {len(entities):,} entities")
        return {'total': len(entities), 'generated': 0, 'failed': 0}

    stats = {'total': len(entities), 'generated': 0, 'failed': 0}
    entities_since_commit = 0

    for i, row in enumerate(entities, 1):
        entity = {
            'id': row[0],
            'canonical_name': row[1],
            'entity_type': str(row[2]) if row[2] else 'unknown',
            'primary_role': str(row[3]) if row[3] else None,
            'initiating_country': row[4],
            'country_affiliations': row[5] or [],
            'alternative_names': row[6] or [],
            'primary_categories': row[7],
            'primary_recipients': row[8],
            'total_documents': row[9],
            'total_mention_days': row[10],
            'first_mention_date': row[11],
            'last_mention_date': row[12],
            'associated_events': row[13] or []
        }

        # Load event names if associated_events available
        event_names = []
        if entity['associated_events']:
            event_ids = entity['associated_events'][:5]
            event_rows = session.execute(text('''
                SELECT canonical_name FROM canonical_events
                WHERE id::text = ANY(:event_ids)
                  AND master_event_id IS NULL
                LIMIT 5
            '''), {'event_ids': event_ids}).fetchall()
            event_names = [r[0] for r in event_rows]

        # Build prompt and call LLM
        user_prompt = build_user_prompt(entity, event_names)

        try:
            response = gai(SYS_PROMPT, user_prompt, model="gpt-4o-mini", use_proxy=True)

            # Parse response
            if isinstance(response, dict):
                result = response
            else:
                # Try to extract JSON from response
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    result = json.loads(response)

            description = result.get('entity_description', '')
            key_activities = result.get('key_activities', {})

            if not description:
                raise ValueError("Empty entity_description in response")

            # Update entity
            session.execute(text('''
                UPDATE canonical_entities
                SET entity_description = :description,
                    key_activities = :key_activities,
                    updated_at = NOW()
                WHERE id = :entity_id::uuid
            '''), {
                'description': description,
                'key_activities': json.dumps(key_activities) if key_activities else None,
                'entity_id': entity['id']
            })

            stats['generated'] += 1

            if verbose:
                safe_name = entity['canonical_name'].encode('ascii', 'replace').decode('ascii')[:50]
                print(f"  [{i}/{len(entities)}] {safe_name}: {len(description)} chars")

        except Exception as e:
            stats['failed'] += 1
            if verbose:
                safe_name = entity['canonical_name'].encode('ascii', 'replace').decode('ascii')[:50]
                print(f"  [{i}/{len(entities)}] FAILED {safe_name}: {str(e)[:80]}")

        entities_since_commit += 1

        # Checkpoint
        if entities_since_commit >= batch_size:
            session.commit()
            if verbose:
                print(f"  [CHECKPOINT] Committed {stats['generated']} descriptions, {stats['failed']} failures")
            entities_since_commit = 0

        # Brief delay to avoid rate limiting
        time.sleep(0.1)

    # Final commit
    if entities_since_commit > 0:
        session.commit()

    if verbose:
        print(f"\n  [DONE] Generated: {stats['generated']:,}, Failed: {stats['failed']:,}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Generate LLM entity descriptions and key activities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
    parser.add_argument('--force', action='store_true', help='Regenerate descriptions even for entities that have them')
    parser.add_argument('--resume', action='store_true', default=True,
                       help='Skip entities that already have descriptions (default behavior)')
    parser.add_argument('--batch-size', type=int, default=20, help='Commit every N entities (default: 20)')
    parser.add_argument('--min-docs', type=int, default=3,
                       help='Only describe entities with at least N documents (default: 3)')
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
    print("GENERATE ENTITY DESCRIPTIONS")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    print(f"Min documents: {args.min_docs}")
    print(f"Batch size: {args.batch_size}")
    if args.dry_run:
        print("[DRY RUN MODE]")
    if args.force:
        print("[FORCE MODE] Regenerating all descriptions")
    print("=" * 80)

    overall = {'total': 0, 'generated': 0, 'failed': 0}

    with get_session() as session:
        for country in countries:
            stats = generate_descriptions_for_country(
                session, country,
                batch_size=args.batch_size,
                min_docs=args.min_docs,
                force=args.force,
                dry_run=args.dry_run,
                verbose=args.verbose
            )
            overall['total'] += stats['total']
            overall['generated'] += stats['generated']
            overall['failed'] += stats['failed']

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total entities processed: {overall['total']:,}")
    print(f"Descriptions generated: {overall['generated']:,}")
    print(f"Failures: {overall['failed']:,}")
    print("=" * 80)


if __name__ == "__main__":
    main()
