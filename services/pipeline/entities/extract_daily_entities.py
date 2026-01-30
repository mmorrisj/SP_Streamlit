"""
Extract Daily Entities from Documents (Stage 1A)

Processes documents day-by-day to extract named entities:
- Persons (individuals with roles/titles)
- Organizations (government agencies, NGOs, international bodies)
- Companies (businesses, corporations, SOEs)
- Locations (cities, venues, facilities)

Input: Documents from database (documents.distilled_text)
Output: raw_entities table (entity mentions before clustering)

Usage:
    # Extract entities for China on a specific date
    python extract_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-08-31

    # Check status
    python extract_daily_entities.py --country China --status

    # Process with specific batch size
    python extract_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-08-31 --batch-size 100
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import json

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from shared.database.database import get_session
from shared.models.models import Document, RawEntity, EntityTypeEnum, InitiatingCountry, RecipientCountry, Category
from shared.utils.utils import Config, gai
from sqlalchemy import text, func, and_, select
from sqlalchemy.dialects.postgresql import insert


# ============================================================================
# LLM PROMPT FOR ENTITY EXTRACTION
# ============================================================================

ENTITY_EXTRACTION_PROMPT = """You are analyzing a diplomatic document to extract named entities.

Document Metadata:
- Date: {date}
- Initiating Country: {initiating_country}
- Recipient Countries: {recipient_countries}
- Categories: {categories}
- Source: {source_name}

Document Text:
{distilled_text}

Your task is to extract ALL named entities mentioned in this document.

Extract the following entity types:

1. **PERSONS** - Names of individuals mentioned
   - Include their role/title (e.g., "Foreign Minister", "CEO", "President")
   - Include country affiliation (which country they represent/work for)
   - Context: What are they doing in this document? (1-2 sentences)

2. **ORGANIZATIONS** - Government agencies, NGOs, international bodies, institutions
   - Include type (e.g., "Government Agency", "NGO", "International Organization")
   - Include country of origin
   - Role: What is their function in this context?

3. **COMPANIES** - Businesses, corporations, state-owned enterprises
   - Include sector (e.g., "Technology", "Energy", "Construction", "Finance")
   - Include country of origin
   - Role: What are they doing in this document?

4. **LOCATIONS** - Cities, venues, facilities, infrastructure projects
   - Include type (e.g., "City", "Venue", "Facility", "Infrastructure Project")
   - Include country
   - Significance: Why is this location mentioned?

CRITICAL GUIDELINES:
- Extract ONLY entities explicitly mentioned in the text
- For persons: Use the most complete name form (e.g., "Wang Yi" not just "Minister Wang")
- For organizations: Use official names (e.g., "Chinese Ministry of Foreign Affairs" not "MFA")
- For companies: Include full legal names when available
- Include context snippets that show HOW the entity is involved
- If the document doesn't mention any entities of a type, return an empty array for that type

Return ONLY a valid JSON object with this structure:
{{
  "persons": [
    {{
      "entity_name": "Wang Yi",
      "role": "Chinese Foreign Minister",
      "country_affiliation": "China",
      "context_snippet": "Wang Yi met with his Iraqi counterpart to discuss bilateral cooperation"
    }}
  ],
  "organizations": [
    {{
      "entity_name": "Iraqi Atomic Energy Commission",
      "role": "Government agency overseeing nuclear programs",
      "country_affiliation": "Iraq",
      "context_snippet": "The Iraqi Atomic Energy Commission signed the framework agreement"
    }}
  ],
  "companies": [
    {{
      "entity_name": "China Atomic Energy Company",
      "role": "State-owned nuclear energy contractor",
      "country_affiliation": "China",
      "context_snippet": "China Atomic Energy Company signed a contract to build Iraq's first nuclear training reactor"
    }}
  ],
  "locations": [
    {{
      "entity_name": "Al-Tuwaitha Complex",
      "role": "Nuclear research facility",
      "country_affiliation": "Iraq",
      "context_snippet": "The reactor will be built at the Al-Tuwaitha Complex near Baghdad"
    }}
  ]
}}
"""


# ============================================================================
# ENTITY EXTRACTION FUNCTIONS
# ============================================================================

def extract_entities_from_document(
    doc: Document,
    config: Config,
    initiating_countries: List[str],
    recipient_countries: List[str],
    categories: List[str]
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """
    Extract entities from a single document using LLM.

    Args:
        doc: Document object
        config: Configuration object
        initiating_countries: List of initiating countries
        recipient_countries: List of recipient countries
        categories: List of categories

    Returns:
        Dictionary with entity types as keys, lists of entities as values
    """
    if not doc.distilled_text or len(doc.distilled_text.strip()) < 50:
        return None

    # Build prompt
    prompt = ENTITY_EXTRACTION_PROMPT.format(
        date=doc.date.strftime("%Y-%m-%d") if doc.date else "Unknown",
        initiating_country=", ".join(initiating_countries) if initiating_countries else "Unknown",
        recipient_countries=", ".join(recipient_countries) if recipient_countries else "Unknown",
        categories=", ".join(categories) if categories else "Unknown",
        source_name=doc.source_name or "Unknown",
        distilled_text=doc.distilled_text[:4000]  # Limit to 4000 chars to manage token usage
    )

    try:
        sys_prompt = "You are an expert at named entity recognition, specializing in diplomatic and geopolitical documents. Extract entities with precise categorization and contextual information."

        response = gai(
            sys_prompt=sys_prompt,
            user_prompt=prompt,
            model=config.aws['default_model']
        )

        # Parse JSON response
        if isinstance(response, dict):
            entities = response
        elif isinstance(response, str):
            entities = json.loads(response.strip())
        else:
            print(f"    Warning: Unexpected response type: {type(response)}")
            return None

        # Validate structure
        if not isinstance(entities, dict):
            print(f"    Warning: Response is not a dictionary")
            return None

        # Ensure all entity types exist
        for entity_type in ['persons', 'organizations', 'companies', 'locations']:
            if entity_type not in entities:
                entities[entity_type] = []

        return entities

    except json.JSONDecodeError as e:
        print(f"    Error parsing LLM response: {e}")
        return None
    except Exception as e:
        print(f"    Error calling LLM: {e}")
        return None


def save_entities_to_database(
    session,
    doc_id: str,
    entities: Dict[str, List[Dict[str, Any]]]
) -> int:
    """
    Save extracted entities to raw_entities table.

    Args:
        session: Database session
        doc_id: Document ID
        entities: Dictionary of entity types and their entities

    Returns:
        Number of entities saved
    """
    entity_type_map = {
        'persons': EntityTypeEnum.PERSON,
        'organizations': EntityTypeEnum.ORGANIZATION,
        'companies': EntityTypeEnum.COMPANY,
        'locations': EntityTypeEnum.LOCATION
    }

    saved_count = 0

    for entity_list_key, entity_type in entity_type_map.items():
        entity_list = entities.get(entity_list_key, [])

        for entity in entity_list:
            entity_name = entity.get('entity_name', '').strip()

            if not entity_name:
                continue

            # Use PostgreSQL UPSERT to handle duplicates
            stmt = insert(RawEntity).values(
                doc_id=doc_id,
                entity_name=entity_name,
                entity_type=entity_type,
                role=entity.get('role'),
                country_affiliation=entity.get('country_affiliation'),
                context_snippet=entity.get('context_snippet')
            )

            # On conflict, update the fields
            stmt = stmt.on_conflict_do_update(
                index_elements=['doc_id', 'entity_name', 'entity_type'],
                set_={
                    'role': stmt.excluded.role,
                    'country_affiliation': stmt.excluded.country_affiliation,
                    'context_snippet': stmt.excluded.context_snippet
                }
            )

            session.execute(stmt)
            saved_count += 1

    return saved_count


def process_date_range(
    country: str,
    start_date: datetime,
    end_date: datetime,
    config: Config,
    batch_size: int = 50,
    force: bool = False
):
    """
    Process all documents in a date range for entity extraction.

    Args:
        country: Initiating country
        start_date: Start date
        end_date: End date
        config: Configuration object
        batch_size: Number of documents to process per commit
        force: If True, reprocess documents that already have entities
    """

    print(f"\n{'='*80}")
    print(f"Extracting Entities: {country}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Batch size: {batch_size}")
    if force:
        print(f"Mode: FORCE - will reprocess documents with existing entities")
    else:
        print(f"Mode: Skip documents with existing entities (use --force to reprocess)")
    print(f"{'='*80}\n")

    with get_session() as session:
        current_date = start_date
        total_docs_processed = 0
        total_entities_extracted = 0

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")

            # Query documents for this date and country
            query = session.query(Document).join(
                InitiatingCountry,
                Document.doc_id == InitiatingCountry.doc_id
            ).filter(
                and_(
                    InitiatingCountry.initiating_country == country,
                    Document.date == current_date.date()
                )
            )

            # If not force mode, exclude documents that already have entities
            if not force:
                # Get set of doc_ids that already have entities (most reliable approach)
                processed_doc_ids = {
                    row[0] for row in
                    session.query(RawEntity.doc_id).distinct().all()
                }

                # Count how many docs for this date already have entities
                docs_for_date = session.query(Document.doc_id).join(
                    InitiatingCountry
                ).filter(
                    and_(
                        InitiatingCountry.initiating_country == country,
                        Document.date == current_date.date()
                    )
                ).all()

                total_for_date = len(docs_for_date)
                already_done_for_date = sum(1 for (doc_id,) in docs_for_date if doc_id in processed_doc_ids)

                if processed_doc_ids:
                    query = query.filter(~Document.doc_id.in_(processed_doc_ids))

                print(f"  {date_str}: {already_done_for_date}/{total_for_date} docs already have entities")

            documents = query.all()

            if not documents:
                print(f"  {date_str}: No documents to process (all done)")
                current_date += timedelta(days=1)
                continue

            print(f"  {date_str}: Processing {len(documents)} remaining documents...")

            docs_processed_today = 0
            entities_extracted_today = 0

            for i, doc in enumerate(documents, 1):
                # Get related metadata
                initiating_countries = [ic.initiating_country for ic in doc.initiating_countries]
                recipient_countries = [rc.recipient_country for rc in doc.recipient_countries]
                categories = [cat.category for cat in doc.categories]

                # Extract entities
                entities = extract_entities_from_document(
                    doc,
                    config,
                    initiating_countries,
                    recipient_countries,
                    categories
                )

                if entities:
                    # Save to database
                    num_entities = save_entities_to_database(session, doc.doc_id, entities)
                    entities_extracted_today += num_entities
                    docs_processed_today += 1

                    if i % 10 == 0:
                        print(f"    Processed {i}/{len(documents)} docs, {entities_extracted_today} entities extracted")

                # Commit every batch_size documents
                if i % batch_size == 0:
                    session.commit()
                    print(f"    ✓ Committed batch at {i} documents")

            # Final commit for the day
            session.commit()

            print(f"  ✓ {date_str}: Processed {docs_processed_today} documents, extracted {entities_extracted_today} entities")

            total_docs_processed += docs_processed_today
            total_entities_extracted += entities_extracted_today

            current_date += timedelta(days=1)

        print(f"\n{'='*80}")
        print(f"✅ Entity Extraction Complete!")
        print(f"  Total documents processed: {total_docs_processed}")
        print(f"  Total entities extracted: {total_entities_extracted}")
        print(f"  Average entities per document: {total_entities_extracted / total_docs_processed if total_docs_processed > 0 else 0:.2f}")
        print(f"{'='*80}\n")


def show_status(country: str):
    """Show entity extraction status for a country."""

    print(f"\n{'='*80}")
    print(f"Entity Extraction Status: {country}")
    print(f"{'='*80}\n")

    with get_session() as session:
        # Count total documents
        total_docs = session.query(func.count(Document.doc_id)).join(
            InitiatingCountry
        ).filter(
            InitiatingCountry.initiating_country == country
        ).scalar()

        # Count documents with entities
        docs_with_entities = session.query(func.count(func.distinct(RawEntity.doc_id))).join(
            Document
        ).join(
            InitiatingCountry
        ).filter(
            InitiatingCountry.initiating_country == country
        ).scalar()

        # Count total entities by type
        entity_counts = session.query(
            RawEntity.entity_type,
            func.count(RawEntity.entity_name)
        ).join(
            Document
        ).join(
            InitiatingCountry
        ).filter(
            InitiatingCountry.initiating_country == country
        ).group_by(
            RawEntity.entity_type
        ).all()

        # Get date range
        date_range = session.query(
            func.min(Document.date),
            func.max(Document.date)
        ).join(
            InitiatingCountry
        ).filter(
            InitiatingCountry.initiating_country == country
        ).first()

        print(f"Total documents: {total_docs}")
        print(f"Documents with entities: {docs_with_entities}")
        print(f"Coverage: {docs_with_entities / total_docs * 100 if total_docs > 0 else 0:.1f}%")
        print(f"Date range: {date_range[0]} to {date_range[1]}")
        print(f"\nEntities by type:")

        for entity_type, count in entity_counts:
            print(f"  {entity_type.value}: {count}")

        total_entities = sum(count for _, count in entity_counts)
        print(f"\nTotal entities: {total_entities}")
        print(f"{'='*80}\n")


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract named entities from documents (Stage 1A)"
    )
    parser.add_argument(
        "--country",
        required=True,
        help="Initiating country to process"
    )
    parser.add_argument(
        "--start-date",
        help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date",
        help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of documents to process per commit (default: 50)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing of documents with existing entities"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show entity extraction status for the country"
    )

    args = parser.parse_args()

    # Show status mode
    if args.status:
        show_status(args.country)
        return

    # Require dates for processing
    if not args.start_date or not args.end_date:
        print("Error: --start-date and --end-date are required for processing")
        print("Use --status to check extraction status")
        sys.exit(1)

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        sys.exit(1)

    # Load config
    config_path = Path(__file__).parent.parent.parent.parent / 'shared' / 'config' / 'config.yaml'
    config = Config.from_yaml(config_path)

    # Process
    process_date_range(
        args.country,
        start_date,
        end_date,
        config,
        args.batch_size,
        args.force
    )


if __name__ == "__main__":
    main()
