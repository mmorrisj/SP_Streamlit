"""
Store extracted entities to the database with deduplication.

This script takes JSON output from entity_extraction.py and stores entities
in the database, performing entity resolution/deduplication.

Usage:
    python services/pipeline/entities/store_entities.py data/entity_extractions_China_20241208.json
    python services/pipeline/entities/store_entities.py data/entity_extractions_*.json --batch
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

sys.path.insert(0, '/home/user/SP_Streamlit')

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from shared.database.database import get_session
from shared.models.models_entity import (
    Entity, DocumentEntity, EntityRelationship, EntityExtractionRun
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def normalize_entity_name(name: str) -> str:
    """Normalize entity name for matching"""
    if not name:
        return ""
    # Basic normalization - lowercase, strip, remove extra spaces
    normalized = " ".join(name.lower().strip().split())
    return normalized


def find_existing_entity(
    session,
    name: str,
    entity_type: str,
    country: Optional[str] = None
) -> Optional[Entity]:
    """
    Find an existing entity by name, type, and country.
    Checks canonical_name and aliases.
    """
    normalized_name = normalize_entity_name(name)

    # First try exact canonical name match
    entity = session.query(Entity).filter(
        func.lower(Entity.canonical_name) == normalized_name,
        Entity.entity_type == entity_type
    ).first()

    if entity:
        return entity

    # Check aliases
    entity = session.query(Entity).filter(
        Entity.entity_type == entity_type,
        func.lower(func.array_to_string(Entity.aliases, '||')).contains(normalized_name)
    ).first()

    if entity:
        return entity

    # For persons with same name and country, likely same person
    if entity_type == "PERSON" and country:
        entity = session.query(Entity).filter(
            func.lower(Entity.canonical_name) == normalized_name,
            Entity.entity_type == "PERSON",
            Entity.country == country
        ).first()
        if entity:
            return entity

    return None


def store_entity(
    session,
    entity_data: Dict[str, Any],
    doc_id: str,
    doc_date: Optional[str],
    model_used: str
) -> tuple[Entity, DocumentEntity]:
    """
    Store an entity and its document link, with deduplication.

    Returns:
        Tuple of (Entity, DocumentEntity)
    """
    name = entity_data.get("name", "").strip()
    entity_type = entity_data.get("entity_type", "UNKNOWN")
    country = entity_data.get("country")

    # Try to find existing entity
    entity = find_existing_entity(session, name, entity_type, country)

    if entity:
        # Update existing entity
        entity.mention_count += 1

        # Add alias if this is a new variation
        entity.add_alias(name)

        # Update date tracking
        if doc_date:
            try:
                date_obj = datetime.strptime(doc_date, "%Y-%m-%d").date()
                if not entity.first_seen_date or date_obj < entity.first_seen_date:
                    entity.first_seen_date = date_obj
                if not entity.last_seen_date or date_obj > entity.last_seen_date:
                    entity.last_seen_date = date_obj
            except ValueError:
                pass

        # Update topic and role counts
        if entity_data.get("topic_label"):
            entity.update_topic_count(entity_data["topic_label"])
        if entity_data.get("role_label"):
            entity.update_role_count(entity_data["role_label"])

        logger.debug(f"Updated existing entity: {entity.canonical_name}")

    else:
        # Create new entity
        date_obj = None
        if doc_date:
            try:
                date_obj = datetime.strptime(doc_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        entity = Entity(
            canonical_name=name,
            entity_type=entity_type,
            country=country,
            title=entity_data.get("title"),
            aliases=[],
            mention_count=1,
            first_seen_date=date_obj,
            last_seen_date=date_obj,
            primary_topics={entity_data.get("topic_label", "UNKNOWN"): 1} if entity_data.get("topic_label") else {},
            primary_roles={entity_data.get("role_label", "UNKNOWN"): 1} if entity_data.get("role_label") else {},
        )
        session.add(entity)
        session.flush()  # Get the ID
        logger.debug(f"Created new entity: {entity.canonical_name}")

    # Create document-entity link
    doc_entity = DocumentEntity(
        doc_id=doc_id,
        entity_id=entity.id,
        side=entity_data.get("side", "unknown"),
        role_label=entity_data.get("role_label", "UNKNOWN"),
        topic_label=entity_data.get("topic_label", "UNKNOWN"),
        role_description=entity_data.get("role_description"),
        title_in_context=entity_data.get("title"),
        organization_in_context=entity_data.get("parent_organization"),
        confidence=entity_data.get("confidence", 1.0),
        extraction_method="llm",
        model_used=model_used
    )
    session.add(doc_entity)

    return entity, doc_entity


def process_extraction_file(file_path: str, dry_run: bool = False) -> Dict[str, int]:
    """
    Process a JSON file of entity extractions and store to database.

    Returns:
        Statistics dict
    """
    stats = {
        "documents_processed": 0,
        "entities_created": 0,
        "entities_updated": 0,
        "document_links_created": 0,
        "errors": 0
    }

    with open(file_path, 'r') as f:
        data = json.load(f)

    extractions = data.get("extractions", [])
    model_used = data.get("stats", {}).get("model_used", "unknown")

    logger.info(f"Processing {len(extractions)} document extractions from {file_path}")

    with get_session() as session:
        # Create extraction run record
        run = EntityExtractionRun(
            model_used=model_used,
            status="running"
        )
        if not dry_run:
            session.add(run)
            session.flush()

        existing_entity_count = session.query(Entity).count()

        for extraction in extractions:
            doc_id = extraction.get("doc_id")
            doc_date = extraction.get("date")
            entities = extraction.get("entities", [])

            if not doc_id:
                logger.warning("Extraction missing doc_id, skipping")
                stats["errors"] += 1
                continue

            for entity_data in entities:
                try:
                    entity, doc_entity = store_entity(
                        session, entity_data, doc_id, doc_date, model_used
                    )
                    stats["document_links_created"] += 1

                except Exception as e:
                    logger.error(f"Error storing entity from doc {doc_id}: {e}")
                    stats["errors"] += 1

            stats["documents_processed"] += 1

        # Calculate new vs updated
        if not dry_run:
            new_entity_count = session.query(Entity).count()
            stats["entities_created"] = new_entity_count - existing_entity_count
            stats["entities_updated"] = stats["document_links_created"] - stats["entities_created"]

            # Update run record
            run.documents_processed = stats["documents_processed"]
            run.entities_extracted = stats["document_links_created"]
            run.errors = stats["errors"]
            run.completed_at = datetime.utcnow()
            run.status = "completed"

            session.commit()
            logger.info("Changes committed to database")
        else:
            logger.info("DRY RUN - no changes committed")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Store extracted entities to database")
    parser.add_argument("files", nargs="+", help="JSON file(s) to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't commit to database")
    parser.add_argument("--batch", action="store_true", help="Process multiple files")

    args = parser.parse_args()

    total_stats = {
        "documents_processed": 0,
        "entities_created": 0,
        "entities_updated": 0,
        "document_links_created": 0,
        "errors": 0
    }

    for file_path in args.files:
        # Handle glob patterns
        if '*' in file_path:
            import glob
            files = glob.glob(file_path)
        else:
            files = [file_path]

        for f in files:
            if not Path(f).exists():
                logger.error(f"File not found: {f}")
                continue

            logger.info(f"\nProcessing: {f}")
            stats = process_extraction_file(f, dry_run=args.dry_run)

            for key in total_stats:
                total_stats[key] += stats.get(key, 0)

    # Print summary
    print("\n" + "="*50)
    print("STORAGE SUMMARY")
    print("="*50)
    print(f"Documents processed:    {total_stats['documents_processed']}")
    print(f"New entities created:   {total_stats['entities_created']}")
    print(f"Existing entities updated: {total_stats['entities_updated']}")
    print(f"Document links created: {total_stats['document_links_created']}")
    print(f"Errors:                 {total_stats['errors']}")
    print("="*50)


if __name__ == "__main__":
    main()
