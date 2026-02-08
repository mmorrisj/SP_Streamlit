"""
Extract Named Entities from Canonical Events

Processes consolidated canonical events to extract and aggregate named entities:
- Persons (individuals with roles/titles)
- Organizations (government agencies, NGOs, international bodies)
- Companies (businesses, corporations, SOEs)
- Locations (cities, venues, facilities, infrastructure projects)

This script works at the EVENT level (not document level):
1. Reads master canonical_events (where master_event_id IS NULL)
2. Extracts entities from the consolidated_description and key_facts
3. Optionally aggregates entities from linked source documents
4. Stores entities in canonical_events.entities_mentioned (JSONB)

Usage:
    # Extract entities for China events
    python extract_canonical_event_entities.py --country China

    # Extract for all influencers
    python extract_canonical_event_entities.py --influencers

    # Only process events with 5+ articles
    python extract_canonical_event_entities.py --country China --min-articles 5

    # Force re-extraction (override existing entities)
    python extract_canonical_event_entities.py --country China --force

    # Dry run (test without saving)
    python extract_canonical_event_entities.py --country China --dry-run
"""

import argparse
import json
import sys
from typing import List, Dict, Optional
from pathlib import Path

# Configure stdout encoding for Unicode support on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_session
from shared.utils.utils import Config, gai


# ============================================================================
# LLM PROMPT FOR EVENT-LEVEL ENTITY EXTRACTION
# ============================================================================

EVENT_ENTITY_EXTRACTION_PROMPT = """You are analyzing a consolidated soft power event to extract ALL named entities.

Event: {event_name}
Initiating Country: {initiating_country}
Recipient Countries: {recipient_countries}
Categories: {categories}
Date Range: {first_mention_date} to {last_mention_date}
Total Articles: {total_articles}

Event Description:
{consolidated_description}

Key Facts:
{key_facts}

Your task is to extract ALL named entities mentioned in this event.

Extract the following entity types:

1. **PERSONS** - Names of individuals mentioned
   - Include their role/title (e.g., "Foreign Minister", "CEO", "President")
   - Include country affiliation
   - Context: What is their role in this event?

2. **ORGANIZATIONS** - Government agencies, NGOs, international bodies, institutions
   - Include type (e.g., "Government Agency", "NGO", "International Organization")
   - Include country of origin
   - Role: What is their function in this event?

3. **COMPANIES** - Businesses, corporations, state-owned enterprises
   - Include sector (e.g., "Technology", "Energy", "Construction", "Finance")
   - Include country of origin
   - Role: What are they doing in this event?

4. **LOCATIONS** - Cities, venues, facilities, infrastructure projects
   - Include type (e.g., "City", "Venue", "Facility", "Infrastructure Project")
   - Include country
   - Significance: Why is this location important to the event?

CRITICAL GUIDELINES:
- Extract ONLY entities explicitly mentioned in the description and key facts
- Use the most complete name form (e.g., "Wang Yi" not just "Minister Wang")
- Use official names for organizations and companies
- Include context that shows HOW the entity is involved in the event
- If the event doesn't mention any entities of a type, return an empty array

Return ONLY a valid JSON object with this structure:
{{
  "persons": [
    {{
      "entity_name": "Wang Yi",
      "role": "Chinese Foreign Minister",
      "country_affiliation": "China",
      "context_snippet": "Led negotiations for the bilateral agreement"
    }}
  ],
  "organizations": [
    {{
      "entity_name": "Iraqi Ministry of Foreign Affairs",
      "type": "Government Agency",
      "country_affiliation": "Iraq",
      "context_snippet": "Signed the cooperation framework"
    }}
  ],
  "companies": [
    {{
      "entity_name": "China State Construction Engineering Corporation",
      "sector": "Construction",
      "country_affiliation": "China",
      "context_snippet": "Awarded contract for infrastructure project"
    }}
  ],
  "locations": [
    {{
      "entity_name": "Baghdad",
      "type": "City",
      "country_affiliation": "Iraq",
      "context_snippet": "Venue for summit meetings"
    }}
  ]
}}

Respond with ONLY the JSON object.
"""


# ============================================================================
# ENTITY EXTRACTION FUNCTIONS
# ============================================================================

def load_canonical_events_to_process(
    session,
    country: str,
    force: bool = False,
    min_articles: int = 1
) -> List[Dict]:
    """
    Load master canonical events that need entity extraction.

    Args:
        session: Database session
        country: Initiating country
        force: If True, reprocess all events. If False, only process events without entities.
        min_articles: Minimum number of articles (default: 1)

    Returns:
        List of canonical event dictionaries
    """
    # Filter: skip events that already have entities (unless force=True)
    entity_filter = "" if force else "AND (ce.entities_mentioned IS NULL OR ce.entities_mentioned = '{}'::jsonb)"

    query = text(f"""
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.first_mention_date,
            ce.last_mention_date,
            ce.total_mention_days,
            ce.total_articles,
            ce.consolidated_description,
            ce.key_facts,
            ce.primary_categories,
            ce.primary_recipients,
            ce.entities_mentioned
        FROM canonical_events ce
        WHERE ce.initiating_country = :country
          AND ce.master_event_id IS NULL
          AND ce.total_articles >= :min_articles
          {entity_filter}
        ORDER BY ce.total_articles DESC NULLS LAST
    """)

    result = session.execute(query, {
        'country': country,
        'min_articles': min_articles
    }).fetchall()

    events = []
    for row in result:
        events.append({
            'id': str(row[0]),
            'canonical_name': row[1],
            'initiating_country': row[2],
            'first_mention_date': row[3],
            'last_mention_date': row[4],
            'total_mention_days': row[5] or 0,
            'total_articles': row[6] or 0,
            'consolidated_description': row[7] or '',
            'key_facts': row[8] or {},
            'primary_categories': row[9] or {},
            'primary_recipients': row[10] or {},
            'entities_mentioned': row[11] or {}
        })

    return events


def format_event_for_extraction(event: Dict) -> Dict[str, str]:
    """Format canonical event data for LLM extraction prompt."""
    # Format categories
    categories = event.get('primary_categories', {})
    if isinstance(categories, dict):
        categories_list = [f"{k} ({v} docs)" for k, v in sorted(categories.items(), key=lambda x: -x[1])[:5]]
        categories_str = ', '.join(categories_list) if categories_list else 'None'
    else:
        categories_str = 'None'

    # Format recipients
    recipients = event.get('primary_recipients', {})
    if isinstance(recipients, dict):
        recipients_list = [f"{k} ({v} docs)" for k, v in sorted(recipients.items(), key=lambda x: -x[1])[:5]]
        recipients_str = ', '.join(recipients_list) if recipients_list else 'None'
    else:
        recipients_str = 'None'

    # Format key facts
    key_facts = event.get('key_facts', {})
    if isinstance(key_facts, dict) and key_facts:
        facts_list = []
        for key, value in list(key_facts.items())[:10]:  # Max 10 facts
            if isinstance(value, list):
                facts_list.append(f"- {key}: {', '.join(str(v) for v in value[:3])}")
            else:
                facts_list.append(f"- {key}: {value}")
        key_facts_str = '\n'.join(facts_list) if facts_list else 'None available'
    else:
        key_facts_str = 'None available'

    return {
        'event_name': event['canonical_name'],
        'initiating_country': event['initiating_country'],
        'recipient_countries': recipients_str,
        'categories': categories_str,
        'first_mention_date': event['first_mention_date'].strftime('%Y-%m-%d') if event['first_mention_date'] else 'N/A',
        'last_mention_date': event['last_mention_date'].strftime('%Y-%m-%d') if event['last_mention_date'] else 'N/A',
        'total_articles': event['total_articles'],
        'consolidated_description': event.get('consolidated_description', 'No description available'),
        'key_facts': key_facts_str
    }


def extract_event_entities(
    event: Dict,
    use_proxy: bool = True
) -> Optional[Dict]:
    """
    Extract entities from canonical event using LLM.

    Args:
        event: Canonical event dictionary
        use_proxy: Whether to use FastAPI proxy for LLM calls

    Returns:
        Dictionary with entity lists by type, or None if failed
    """
    # Format event for extraction
    formatted = format_event_for_extraction(event)

    # Create prompt
    prompt = EVENT_ENTITY_EXTRACTION_PROMPT.format(**formatted)

    # Call LLM
    try:
        sys_prompt = "You are an expert analyst extracting named entities from diplomatic event descriptions. You identify persons, organizations, companies, and locations with their context."

        response = gai(sys_prompt, prompt, use_proxy=use_proxy)

        # Parse response
        if isinstance(response, dict):
            entities_data = response
        else:
            try:
                entities_data = json.loads(response)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"    [ERROR] Failed to parse LLM response: {e}")
                return None

        # Validate structure
        required_keys = ['persons', 'organizations', 'companies', 'locations']
        if not all(key in entities_data for key in required_keys):
            print("    [ERROR] Missing required entity types in response")
            return None

        # Ensure all are lists
        for key in required_keys:
            if not isinstance(entities_data[key], list):
                entities_data[key] = []

        return entities_data

    except Exception as e:
        print(f"    [ERROR] LLM call failed: {e}")
        return None


def update_canonical_event_entities(
    session,
    event_id: str,
    entities: Dict
):
    """Update canonical event with extracted entities."""
    query = text("""
        UPDATE canonical_events
        SET entities_mentioned = :entities,
            updated_at = NOW()
        WHERE id = :event_id
    """)

    session.execute(query, {
        'event_id': event_id,
        'entities': json.dumps(entities)
    })


def extract_country_event_entities(
    country: str,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
    min_articles: int = 1
) -> Dict[str, int]:
    """
    Extract entities for all canonical events in a country.

    Returns:
        Statistics dictionary
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"CANONICAL EVENT ENTITY EXTRACTION: {country}")
        print(f"{'='*80}")
        print(f"Force reprocessing: {'Yes' if force else 'No'}")
        print(f"Minimum articles: {min_articles}")
        print(f"Dry run: {'Yes' if dry_run else 'No'}")

    with get_session() as session:
        # Load events
        events = load_canonical_events_to_process(
            session,
            country,
            force,
            min_articles
        )

        if not events:
            if verbose:
                print("\n  [INFO] No events found to process")
            return {'total': 0, 'extracted': 0, 'failed': 0}

        if verbose:
            print(f"  Found {len(events)} events to process")

        stats = {
            'total': len(events),
            'extracted': 0,
            'failed': 0
        }

        # Extract entities for each event
        for i, event in enumerate(events, 1):
            event_name = event['canonical_name']
            safe_name = event_name.encode('ascii', 'replace').decode('ascii')

            if verbose:
                existing_entities = event.get('entities_mentioned', {})
                entity_count = sum(len(entities) for entities in existing_entities.values()) if existing_entities else 0
                existing_str = f" (current: {entity_count} entities)" if entity_count else ""
                print(f"\n  [{i}/{len(events)}] {safe_name[:80]}{existing_str}")
                print(f"    Articles: {event['total_articles']}, Days: {event['total_mention_days']}")

            # Extract entities
            if verbose:
                print("    [PROXY] Calling LLM for entity extraction...")

            entities = extract_event_entities(event, use_proxy=True)

            if entities:
                # Count total entities
                total_entities = sum(len(entity_list) for entity_list in entities.values())

                if verbose:
                    print(f"    [EXTRACTED] {total_entities} entities")
                    for entity_type, entity_list in entities.items():
                        if entity_list:
                            print(f"      - {entity_type}: {len(entity_list)}")

                if not dry_run:
                    update_canonical_event_entities(
                        session,
                        event['id'],
                        entities
                    )
                    session.commit()
                    if verbose:
                        print("    [SAVED] Entities updated")

                stats['extracted'] += 1
            else:
                if verbose:
                    print("    [FAILED] Could not extract entities")
                stats['failed'] += 1

        if verbose:
            print(f"\n{'='*80}")
            print("SUMMARY")
            print(f"{'='*80}")
            print(f"  Total events: {stats['total']}")
            print(f"  Successfully extracted: {stats['extracted']}")
            print(f"  Failed: {stats['failed']}")

        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Extract named entities from canonical events'
    )

    # Country selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--country', type=str, help='Single country to process')
    group.add_argument('--influencers', action='store_true',
                      help='Process all influencer countries from config')

    # Options
    parser.add_argument('--force', action='store_true',
                       help='Force reprocessing of events that already have entities')
    parser.add_argument('--dry-run', action='store_true',
                       help='Test without updating database')
    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')
    parser.add_argument('--min-articles', type=int, default=1,
                       help='Minimum number of articles (default: 1)')

    args = parser.parse_args()

    # Get countries to process
    if args.influencers:
        cfg = Config.from_yaml('shared/config/config.yaml')
        countries = cfg.influencers
    else:
        countries = [args.country]

    verbose = not args.quiet

    # Process each country
    total_stats = {'total': 0, 'extracted': 0, 'failed': 0}

    for country in countries:
        stats = extract_country_event_entities(
            country=country,
            force=args.force,
            dry_run=args.dry_run,
            verbose=verbose,
            min_articles=args.min_articles
        )

        total_stats['total'] += stats['total']
        total_stats['extracted'] += stats['extracted']
        total_stats['failed'] += stats['failed']

    if len(countries) > 1 and verbose:
        print(f"\n{'='*80}")
        print(f"OVERALL SUMMARY ({len(countries)} countries)")
        print(f"{'='*80}")
        print(f"  Total events: {total_stats['total']}")
        print(f"  Successfully extracted: {total_stats['extracted']}")
        print(f"  Failed: {total_stats['failed']}")


if __name__ == '__main__':
    main()
