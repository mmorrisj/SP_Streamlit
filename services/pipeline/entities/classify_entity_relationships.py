"""
Stage 3D: Classify Entity Relationship Types

Takes entity_relationships rows created by build_entity_cooccurrence.py
(which uses the generic type 'co_occurrence') and uses an LLM to classify
each relationship into a specific type and write a description.

Relationship types:
  - works_with        : colleagues at the same level (person-person)
  - employed_by       : person works for an organization
  - leads             : person heads/directs an organization
  - represents        : person speaks for / is envoy of an entity
  - partnered_with    : organizations in a formal partnership/MOU
  - subsidiary_of     : organization is part of a parent organization
  - located_in        : organization/person is based in a location
  - visited           : person traveled to a location
  - signed_agreement_with : entities formally signed an agreement together
  - co_occurrence     : fallback if evidence is insufficient to classify

PIPELINE CONTEXT:
  - Stage 3A: link_entities_to_events.py - Entity-event linkage
  - Stage 3B: build_entity_cooccurrence.py - Builds co_occurrence edges
  - Stage 3C: generate_entity_descriptions.py - LLM entity profiles
  - Stage 3D: THIS SCRIPT - Classifies relationship edges

Usage:
    python classify_entity_relationships.py --country China
    python classify_entity_relationships.py --influencers
    python classify_entity_relationships.py --country Iran --force
    python classify_entity_relationships.py --influencers --min-cooccurrence 3
    python classify_entity_relationships.py --country China --dry-run
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
from typing import Dict, List, Optional
from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import gai


VALID_RELATIONSHIP_TYPES = {
    'works_with',
    'employed_by',
    'leads',
    'represents',
    'partnered_with',
    'subsidiary_of',
    'located_in',
    'visited',
    'signed_agreement_with',
    'co_occurrence',
}

SYS_PROMPT = (
    "You are an expert analyst of international relations and soft power diplomacy. "
    "Classify the relationship between two entities based only on the document evidence provided. "
    "Write descriptions in AP (Associated Press) style. Be specific and concrete — name the actual "
    "agreements, meetings, titles, or actions observed. Never use vague filler phrases. "
    "If the evidence is insufficient to determine a specific relationship type, use 'co_occurrence'."
)

RELATIONSHIP_TYPE_DEFINITIONS = """\
Valid relationship_type values (choose exactly one):
  works_with        - Colleagues operating at the same level (e.g., two ministers collaborating)
  employed_by       - Person works for / is a staff member of an organization
  leads             - Person heads, directs, or chairs an organization (CEO, minister, director)
  represents        - Person acts as envoy, spokesperson, or representative of an entity
  partnered_with    - Two organizations have a formal partnership, MOU, or joint initiative
  subsidiary_of     - Organization is a branch, division, or subsidiary of a parent organization
  located_in        - Organization or person is based in / headquartered in a location
  visited           - Person traveled to, attended an event in, or met counterparts in a location
  signed_agreement_with - Entities formally signed a treaty, contract, or agreement together
  co_occurrence     - Insufficient evidence to determine a specific relationship type"""


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


def load_doc_snippets(session, doc_ids: List[str], limit: int = 5) -> List[str]:
    """Load distilled_text snippets from documents for context."""
    if not doc_ids:
        return []
    rows = session.execute(text("""
        SELECT distilled_text FROM documents
        WHERE doc_id = ANY(:doc_ids)
          AND distilled_text IS NOT NULL
          AND distilled_text != ''
        LIMIT :lim
    """), {'doc_ids': doc_ids[:20], 'lim': limit}).fetchall()
    snippets = []
    for row in rows:
        text_val = row[0]
        if text_val:
            # Truncate long snippets
            snippets.append(text_val[:500])
    return snippets


def build_user_prompt(rel: dict) -> str:
    """Build the LLM prompt for relationship classification."""
    # Format categories
    cats = rel.get('primary_categories') or {}
    if isinstance(cats, str):
        try:
            cats = json.loads(cats)
        except (ValueError, TypeError):
            cats = {}
    if cats:
        sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]
        categories_str = ", ".join(f"{k} ({v})" for k, v in sorted_cats)
    else:
        categories_str = "N/A"

    # Format document snippets
    snippets = rel.get('doc_snippets', [])
    if snippets:
        snippet_lines = "\n".join(f"  {i+1}. {s[:400]}" for i, s in enumerate(snippets))
    else:
        snippet_lines = "  (no document excerpts available)"

    return f"""Classify the relationship between these two entities using ONLY the document evidence below.

**Entity A**: {rel['from_name']}
  Type: {rel['from_type']} | Role: {rel.get('from_role') or 'Unknown'} | Country: {rel['from_country']}

**Entity B**: {rel['to_name']}
  Type: {rel['to_type']} | Role: {rel.get('to_role') or 'Unknown'}

**Co-occurrence statistics**:
  Shared documents: {rel['co_occurrence_count']}
  Date range: {rel['first_co_occurrence']} to {rel['last_co_occurrence']}
  Top categories: {categories_str}

**Document evidence** (excerpts where both entities appear):
{snippet_lines}

{RELATIONSHIP_TYPE_DEFINITIONS}

Based ONLY on the evidence above, return a JSON object:
{{
    "relationship_type": "<one of the valid types above>",
    "relationship_description": "2-3 sentences. Name specific actions, titles, agreements, or meetings from the evidence. No filler phrases."
}}"""


def classify_relationships_for_country(
    session,
    country: str,
    batch_size: int = 20,
    min_cooccurrence: int = 2,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Classify entity relationship types for a specific country.

    Args:
        session: Database session
        country: Initiating country
        batch_size: Commit every N relationships (checkpoint)
        min_cooccurrence: Only classify relationships with at least this many shared docs
        force: If True, reclassify relationships that already have a specific type
        dry_run: If True, don't save changes
        verbose: Print progress

    Returns:
        Statistics dict
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"Classifying Entity Relationships: {country}")
        print('='*80)

    # Build filter: without force, only classify 'co_occurrence' rows
    type_filter = "" if force else "AND er.relationship_type = 'co_occurrence'"

    rows = session.execute(text(f"""
        SELECT
            er.id::text,
            er.entity_from_id::text,
            er.entity_to_id::text,
            er.co_occurrence_count,
            er.first_co_occurrence::text,
            er.last_co_occurrence::text,
            er.primary_categories,
            er.source_doc_ids,
            ef.canonical_name   AS from_name,
            ef.entity_type::text AS from_type,
            ef.primary_role::text AS from_role,
            ef.initiating_country AS from_country,
            et.canonical_name   AS to_name,
            et.entity_type::text AS to_type,
            et.primary_role::text AS to_role
        FROM entity_relationships er
        JOIN canonical_entities ef ON er.entity_from_id = ef.id
        JOIN canonical_entities et ON er.entity_to_id = et.id
        WHERE ef.initiating_country = :country
          AND ef.master_entity_id IS NULL
          AND et.master_entity_id IS NULL
          AND er.co_occurrence_count >= :min_coo
          {type_filter}
        ORDER BY er.co_occurrence_count DESC
    """), {'country': country, 'min_coo': min_cooccurrence}).fetchall()

    if not rows:
        mode = "all (force)" if force else "unclassified only"
        if verbose:
            print(f"  No relationships need classification ({mode}, min_cooccurrence={min_cooccurrence})")
        return {'total': 0, 'classified': 0, 'failed': 0}

    if verbose:
        mode = "all (force)" if force else "unclassified only"
        print(f"  Found {len(rows):,} relationships to classify ({mode})")

    if dry_run:
        if verbose:
            print(f"  [DRY RUN] Would classify {len(rows):,} relationships")
        return {'total': len(rows), 'classified': 0, 'failed': 0}

    stats = {'total': len(rows), 'classified': 0, 'failed': 0}
    since_commit = 0

    for i, row in enumerate(rows, 1):
        rel = {
            'id': row[0],
            'entity_from_id': row[1],
            'entity_to_id': row[2],
            'co_occurrence_count': row[3],
            'first_co_occurrence': row[4],
            'last_co_occurrence': row[5],
            'primary_categories': row[6],
            'source_doc_ids': row[7] or [],
            'from_name': row[8],
            'from_type': row[9],
            'from_role': row[10],
            'from_country': row[11],
            'to_name': row[12],
            'to_type': row[13],
            'to_role': row[14],
        }

        # Load document snippets for context
        rel['doc_snippets'] = load_doc_snippets(session, rel['source_doc_ids'], limit=5)

        user_prompt = build_user_prompt(rel)

        try:
            response = gai(SYS_PROMPT, user_prompt, model="gpt-4o-mini", use_proxy=True)

            # Parse response
            if isinstance(response, dict):
                result = response
            else:
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    result = json.loads(response)

            rel_type = result.get('relationship_type', 'co_occurrence').strip()
            description = result.get('relationship_description', '').strip()

            # Validate type
            if rel_type not in VALID_RELATIONSHIP_TYPES:
                rel_type = 'co_occurrence'

            if not description:
                raise ValueError("Empty relationship_description in response")

            # Update relationship
            session.execute(text("""
                UPDATE entity_relationships
                SET relationship_type = :rel_type,
                    relationship_description = :description,
                    updated_at = NOW()
                WHERE id = CAST(:rel_id AS uuid)
            """), {
                'rel_type': rel_type,
                'description': description,
                'rel_id': rel['id']
            })

            stats['classified'] += 1

            if verbose:
                from_safe = rel['from_name'].encode('ascii', 'replace').decode('ascii')[:25]
                to_safe = rel['to_name'].encode('ascii', 'replace').decode('ascii')[:25]
                print(f"  [{i}/{len(rows)}] {from_safe} --[{rel_type}]--> {to_safe}")

        except Exception as e:
            stats['failed'] += 1
            if verbose:
                from_safe = rel['from_name'].encode('ascii', 'replace').decode('ascii')[:25]
                print(f"  [{i}/{len(rows)}] FAILED {from_safe}: {str(e)[:80]}")

        since_commit += 1
        if since_commit >= batch_size:
            session.commit()
            if verbose:
                print(f"  [CHECKPOINT] Classified: {stats['classified']}, Failed: {stats['failed']}")
            since_commit = 0

        time.sleep(0.1)

    if since_commit > 0:
        session.commit()

    if verbose:
        print(f"\n  [DONE] Classified: {stats['classified']:,}, Failed: {stats['failed']:,}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Classify entity relationship types using LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
    parser.add_argument('--force', action='store_true',
                        help='Reclassify relationships that are already classified')
    parser.add_argument('--min-cooccurrence', type=int, default=2,
                        help='Only classify relationships with at least N shared documents (default: 2)')
    parser.add_argument('--batch-size', type=int, default=20,
                        help='Commit every N relationships (default: 20)')
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
    print("CLASSIFY ENTITY RELATIONSHIPS")
    print("=" * 80)
    print(f"Countries: {', '.join(countries)}")
    print(f"Min co-occurrences: {args.min_cooccurrence}")
    print(f"Batch size: {args.batch_size}")
    if args.dry_run:
        print("[DRY RUN MODE]")
    if args.force:
        print("[FORCE MODE] Reclassifying all relationships")
    print("=" * 80)

    overall = {'total': 0, 'classified': 0, 'failed': 0}

    with get_session() as session:
        for country in countries:
            stats = classify_relationships_for_country(
                session, country,
                batch_size=args.batch_size,
                min_cooccurrence=args.min_cooccurrence,
                force=args.force,
                dry_run=args.dry_run,
                verbose=args.verbose
            )
            overall['total'] += stats['total']
            overall['classified'] += stats['classified']
            overall['failed'] += stats['failed']

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total relationships processed: {overall['total']:,}")
    print(f"Relationships classified: {overall['classified']:,}")
    print(f"Failures: {overall['failed']:,}")
    print("=" * 80)


if __name__ == "__main__":
    main()
