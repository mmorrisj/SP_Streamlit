"""
Store extracted entities to the database with deduplication.

This script takes JSON output from entity_extraction.py and stores entities
in the database, performing entity resolution/deduplication.

Features:
- Entity deduplication by name/type/country
- ON CONFLICT DO NOTHING for document_entities to prevent duplicates
- Tracks doc_id source for full traceability

Usage:
    python services/pipeline/entities/store_entities.py data/entity_extractions_China_20241208.json
    python services/pipeline/entities/store_entities.py data/entity_extractions_*.json --batch
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from pathlib import Path

sys.path.insert(0, '/home/user/SP_Streamlit')

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.database.database import get_session
from shared.models.models_entity import (
    Entity, DocumentEntity, EntityRelationship, EntityExtractionRun
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_existing_doc_entity_pairs(session) -> Set[tuple]:
    """
    Get set of (doc_id, entity_id) pairs that already exist in document_entities.
    Used to prevent duplicate inserts.
    """
    try:
        result = session.execute(text(
            "SELECT doc_id, entity_id::text FROM document_entities"
        ))
        return {(row[0], row[1]) for row in result.fetchall()}
    except Exception as e:
        logger.warning(f"Could not query existing doc-entity pairs: {e}")
        return set()


def get_existing_relationships(session) -> Set[tuple]:
    """
    Get set of (source_entity_id, target_entity_id, relationship_type, doc_id) tuples
    from existing relationships. Used to prevent duplicate doc contributions.

    Note: EntityRelationship model stores sample_doc_ids as an array of doc_ids
    that have contributed to this relationship. We expand this to track duplicates.
    """
    try:
        # Get all relationships with their sample_doc_ids
        result = session.execute(text(
            """
            SELECT source_entity_id::text, target_entity_id::text, relationship_type,
                   unnest(sample_doc_ids) as doc_id
            FROM entity_relationships
            WHERE sample_doc_ids IS NOT NULL AND array_length(sample_doc_ids, 1) > 0
            """
        ))
        return {(row[0], row[1], row[2], row[3]) for row in result.fetchall()}
    except Exception as e:
        logger.warning(f"Could not query existing relationships: {e}")
        return set()


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
    model_used: str,
    existing_pairs: Set[tuple] = None
) -> tuple[Optional[Entity], Optional[DocumentEntity], bool]:
    """
    Store an entity and its document link, with deduplication.

    Args:
        session: Database session
        entity_data: Extracted entity data
        doc_id: Source document ID
        doc_date: Source document date
        model_used: LLM model used for extraction
        existing_pairs: Set of (doc_id, entity_id) pairs already in database

    Returns:
        Tuple of (Entity, DocumentEntity, was_skipped)
        - was_skipped is True if this doc-entity pair already existed
    """
    name = entity_data.get("name", "").strip()
    entity_type = entity_data.get("entity_type", "UNKNOWN")
    country = entity_data.get("country")

    if not name:
        logger.warning(f"Empty entity name in doc {doc_id}, skipping")
        return None, None, True

    # Try to find existing entity
    entity = find_existing_entity(session, name, entity_type, country)

    if entity:
        # Check if this doc-entity pair already exists (ON CONFLICT IGNORE logic)
        if existing_pairs and (doc_id, str(entity.id)) in existing_pairs:
            logger.debug(f"Skipping duplicate: doc {doc_id[:8]}... already linked to entity {entity.canonical_name}")
            return entity, None, True

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

    # Create document-entity link with ON CONFLICT DO NOTHING via upsert
    # Using PostgreSQL INSERT ... ON CONFLICT DO NOTHING
    doc_entity_data = {
        "doc_id": doc_id,
        "entity_id": entity.id,
        "side": entity_data.get("side", "unknown"),
        "role_label": entity_data.get("role_label", "UNKNOWN"),
        "topic_label": entity_data.get("topic_label", "UNKNOWN"),
        "role_description": entity_data.get("role_description"),
        "title_in_context": entity_data.get("title"),
        "organization_in_context": entity_data.get("parent_organization"),
        "confidence": entity_data.get("confidence", 1.0),
        "extraction_method": "llm",
        "model_used": model_used
    }

    # Use raw SQL for ON CONFLICT DO NOTHING since SQLAlchemy ORM doesn't support it directly
    stmt = pg_insert(DocumentEntity.__table__).values(**doc_entity_data)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=['doc_id', 'entity_id']  # Requires unique constraint on (doc_id, entity_id)
    )

    try:
        result = session.execute(stmt)
        # Check if row was actually inserted (rowcount=1) or ignored (rowcount=0)
        if result.rowcount == 0:
            logger.debug(f"Duplicate doc-entity link ignored: {doc_id[:8]}... <-> {entity.canonical_name}")
            return entity, None, True

        # Add to existing_pairs set for future checks in this session
        if existing_pairs is not None:
            existing_pairs.add((doc_id, str(entity.id)))

        logger.debug(f"Created doc-entity link: {doc_id[:8]}... <-> {entity.canonical_name}")
        return entity, doc_entity_data, False

    except Exception as e:
        logger.error(f"Error creating doc-entity link: {e}")
        return entity, None, True


def store_relationship(
    session,
    rel_data: Dict[str, Any],
    doc_id: str,
    doc_date: Optional[str],
    entity_name_to_id: Dict[str, str],
    existing_rel_doc_pairs: Set[tuple]
) -> tuple[bool, bool]:
    """
    Store a relationship between two entities with aggregation.

    The EntityRelationship model aggregates observations across documents.
    Each unique (source, target, type) triple is one relationship with
    multiple observations.

    Args:
        session: Database session
        rel_data: Relationship data from extraction
        doc_id: Source document ID
        doc_date: Source document date
        entity_name_to_id: Mapping of entity names to their database IDs
        existing_rel_doc_pairs: Set of (source_id, target_id, type, doc_id) seen

    Returns:
        Tuple of (was_created_or_updated, was_skipped)
    """
    source_name = rel_data.get("source_entity", "")
    target_name = rel_data.get("target_entity", "")
    rel_type = rel_data.get("relationship_type", "")

    # Look up entity IDs
    source_id = entity_name_to_id.get(source_name)
    target_id = entity_name_to_id.get(target_name)

    if not source_id or not target_id:
        logger.warning(f"Cannot store relationship: entity not found for '{source_name}' or '{target_name}'")
        return False, True

    # Check if this doc has already contributed to this relationship
    rel_doc_key = (source_id, target_id, rel_type, doc_id)
    if rel_doc_key in existing_rel_doc_pairs:
        logger.debug(f"Skipping duplicate: doc {doc_id[:8]}... already contributed to {source_name} --[{rel_type}]--> {target_name}")
        return False, True

    # Parse monetary value if present
    monetary_value = rel_data.get("monetary_value")
    if monetary_value is not None:
        try:
            monetary_value = float(monetary_value)
        except (ValueError, TypeError):
            monetary_value = None

    # Map confidence string to float
    confidence_map = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.5}
    confidence = confidence_map.get(rel_data.get("confidence", "MEDIUM"), 0.7)

    # Parse observation date
    observation_date = datetime.utcnow().date()
    if doc_date:
        try:
            observation_date = datetime.strptime(doc_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    description = rel_data.get("relationship_description", "")

    try:
        # Try to find existing relationship
        existing = session.query(EntityRelationship).filter(
            EntityRelationship.source_entity_id == source_id,
            EntityRelationship.target_entity_id == target_id,
            EntityRelationship.relationship_type == rel_type
        ).first()

        if existing:
            # Update existing relationship with new observation
            existing.add_observation(
                doc_id=doc_id,
                description=description,
                observation_date=observation_date,
                confidence=confidence,
                value_usd=monetary_value
            )
            logger.debug(f"Updated relationship: {source_name} --[{rel_type}]--> {target_name} (now {existing.observation_count} observations)")
        else:
            # Create new relationship
            new_rel = EntityRelationship(
                source_entity_id=source_id,
                target_entity_id=target_id,
                relationship_type=rel_type,
                first_observed=observation_date,
                last_observed=observation_date,
                observation_count=1,
                document_count=1,
                sample_doc_ids=[doc_id],
                sample_descriptions=[description] if description else [],
                avg_confidence=confidence,
                total_value_usd=monetary_value
            )
            session.add(new_rel)
            logger.debug(f"Created relationship: {source_name} --[{rel_type}]--> {target_name}")

        # Track that this doc has contributed
        existing_rel_doc_pairs.add(rel_doc_key)
        return True, False

    except Exception as e:
        logger.error(f"Error storing relationship: {e}")
        return False, True


def process_extraction_file(file_path: str, dry_run: bool = False) -> Dict[str, int]:
    """
    Process a JSON file of entity extractions and store to database.

    Features:
    - Skips already-processed doc-entity pairs (ON CONFLICT IGNORE)
    - Tracks doc_id for full traceability
    - Entity deduplication by name/type/country
    - Stores entity relationships with deduplication

    Returns:
        Statistics dict
    """
    stats = {
        "documents_processed": 0,
        "documents_skipped": 0,
        "entities_created": 0,
        "entities_updated": 0,
        "document_links_created": 0,
        "document_links_skipped": 0,
        "relationships_created": 0,
        "relationships_skipped": 0,
        "errors": 0
    }

    with open(file_path, 'r') as f:
        data = json.load(f)

    extractions = data.get("extractions", [])
    model_used = data.get("stats", {}).get("model_used", "unknown")

    logger.info(f"Processing {len(extractions)} document extractions from {file_path}")

    with get_session() as session:
        # Get existing doc-entity pairs to skip duplicates
        existing_pairs = get_existing_doc_entity_pairs(session)
        logger.info(f"Found {len(existing_pairs)} existing doc-entity pairs in database")

        # Get existing (source, target, type, doc_id) tuples to skip duplicate doc contributions
        existing_rel_doc_pairs = get_existing_relationships(session)
        logger.info(f"Found {len(existing_rel_doc_pairs)} existing relationship-doc pairs in database")

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
            relationships = extraction.get("relationships", [])

            if not doc_id:
                logger.warning("Extraction missing doc_id, skipping")
                stats["errors"] += 1
                continue

            # Build name-to-ID mapping as we process entities
            entity_name_to_id = {}
            doc_had_new_links = False

            for entity_data in entities:
                try:
                    entity, doc_entity, was_skipped = store_entity(
                        session, entity_data, doc_id, doc_date, model_used,
                        existing_pairs=existing_pairs
                    )

                    # Track entity name -> ID mapping for relationship resolution
                    if entity and entity_data.get("name"):
                        entity_name_to_id[entity_data["name"]] = str(entity.id)

                    if was_skipped:
                        stats["document_links_skipped"] += 1
                    else:
                        stats["document_links_created"] += 1
                        doc_had_new_links = True

                except Exception as e:
                    logger.error(f"Error storing entity from doc {doc_id}: {e}")
                    stats["errors"] += 1

            # Process relationships after all entities are stored
            for rel_data in relationships:
                try:
                    was_created, was_skipped = store_relationship(
                        session, rel_data, doc_id, doc_date, entity_name_to_id,
                        existing_rel_doc_pairs
                    )

                    if was_created:
                        stats["relationships_created"] += 1
                    elif was_skipped:
                        stats["relationships_skipped"] += 1

                except Exception as e:
                    logger.error(f"Error storing relationship from doc {doc_id}: {e}")
                    stats["errors"] += 1

            if doc_had_new_links:
                stats["documents_processed"] += 1
            else:
                stats["documents_skipped"] += 1

        # Calculate new vs updated entities
        if not dry_run:
            new_entity_count = session.query(Entity).count()
            stats["entities_created"] = new_entity_count - existing_entity_count
            stats["entities_updated"] = max(0, stats["document_links_created"] - stats["entities_created"])

            # Update run record
            run.documents_processed = stats["documents_processed"]
            run.entities_extracted = stats["document_links_created"]
            run.relationships_extracted = stats["relationships_created"]
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
        "documents_skipped": 0,
        "entities_created": 0,
        "entities_updated": 0,
        "document_links_created": 0,
        "document_links_skipped": 0,
        "relationships_created": 0,
        "relationships_skipped": 0,
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
    print(f"Documents processed:      {total_stats['documents_processed']}")
    print(f"Documents skipped:        {total_stats['documents_skipped']} (already in DB)")
    print(f"New entities created:     {total_stats['entities_created']}")
    print(f"Existing entities updated:{total_stats['entities_updated']}")
    print(f"Document links created:   {total_stats['document_links_created']}")
    print(f"Document links skipped:   {total_stats['document_links_skipped']} (duplicates)")
    print(f"Relationships created:    {total_stats['relationships_created']}")
    print(f"Relationships skipped:    {total_stats['relationships_skipped']} (duplicates)")
    print(f"Errors:                   {total_stats['errors']}")
    print("="*50)


if __name__ == "__main__":
    main()
