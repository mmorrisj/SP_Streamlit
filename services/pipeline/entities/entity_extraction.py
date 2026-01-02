"""
Entity extraction pipeline for soft power network mapping.

Extracts organizations, companies, and key persons from document distilled_text,
capturing their roles, topics, and relationships in soft power transactions.

Usage:
    python services/pipeline/entities/entity_extraction.py --country China --limit 100
    python services/pipeline/entities/entity_extraction.py --country China --start-date 2024-01-01
    python services/pipeline/entities/entity_extraction.py --doc-id <specific_doc_id>
    python services/pipeline/entities/entity_extraction.py --dry-run --limit 10
    python services/pipeline/entities/entity_extraction.py --country China --reprocess  # Force reprocess
"""

import argparse
import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import text, and_, distinct
from sqlalchemy.dialects.postgresql import insert

from shared.database.database import get_session
from shared.models.models import Document
from shared.utils.prompts_entity import (
    entity_extraction_prompt,
    ROLE_LABELS,
    TOPIC_LABELS,
    ENTITY_TYPES,
    RELATIONSHIP_TYPES
)
from shared.utils.utils import gai, find_json_objects, cfg  # Import the already-loaded config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_processed_doc_ids(session) -> Set[str]:
    """
    Get set of doc_ids that have already been processed for entity extraction.

    Queries the document_entities table to find all unique doc_ids.

    Returns:
        Set of doc_id strings that have already been processed
    """
    try:
        # Check if table exists first
        result = session.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'document_entities')"
        )).scalar()

        if not result:
            logger.info("document_entities table does not exist yet - no documents processed")
            return set()

        # Get all unique doc_ids from document_entities
        result = session.execute(text("SELECT DISTINCT doc_id FROM document_entities"))
        processed_ids = {row[0] for row in result.fetchall()}
        logger.info(f"Found {len(processed_ids)} already-processed documents in document_entities table")
        return processed_ids

    except Exception as e:
        logger.warning(f"Could not query processed doc_ids: {e}")
        return set()


def extract_entities_from_document(
    doc: Document,
    model: str = "gpt-4o-mini"
) -> Dict[str, Any]:
    """
    Extract entities from a single document's distilled_text.

    Uses the gai() function from utils.py which handles API proxy and fallback logic.

    Args:
        doc: Document model instance
        model: Model to use for extraction

    Returns:
        Dict containing extracted entities and metadata
    """
    if not doc.distilled_text or len(doc.distilled_text.strip()) < 50:
        logger.warning(f"Document {doc.doc_id} has insufficient distilled_text")
        return {"entities": [], "entity_count": 0, "error": "insufficient_text"}

    # Format the prompt with document context
    user_prompt = entity_extraction_prompt.format(
        initiating_country=doc.initiating_country or "Unknown",
        recipient_country=doc.recipient_country or "Unknown",
        category=doc.category or "Unknown",
        subcategory=doc.subcategory or "Unknown",
        distilled_text=doc.distilled_text
    )

    sys_prompt = "You are an expert entity extractor for soft power analysis. Output only valid JSON."

    try:
        # Use gai() function from utils - handles API proxy and fallback
        result = gai(sys_prompt, user_prompt, model=model)

        # If gai returns a string, try to parse it
        if isinstance(result, str):
            # Try find_json_objects for robust parsing
            parsed = find_json_objects(result)
            if parsed and isinstance(parsed, list) and len(parsed) > 0:
                result = parsed[0]
            else:
                result = json.loads(result)

        # Ensure result is a dict
        if isinstance(result, list) and len(result) > 0:
            result = result[0]

        if not isinstance(result, dict):
            raise ValueError(f"Unexpected result type: {type(result)}")

        # Add document metadata
        result["doc_id"] = doc.doc_id
        result["source_name"] = doc.source_name
        result["date"] = doc.date.isoformat() if doc.date else None
        result["initiating_country"] = doc.initiating_country
        result["recipient_country"] = doc.recipient_country
        result["extraction_timestamp"] = datetime.utcnow().isoformat()
        result["model_used"] = model

        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for doc {doc.doc_id}: {e}")
        return {"entities": [], "entity_count": 0, "error": f"json_parse_error: {str(e)}"}
    except Exception as e:
        logger.error(f"Extraction error for doc {doc.doc_id}: {e}")
        return {"entities": [], "entity_count": 0, "error": str(e)}


def validate_entity(entity: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    Validate an extracted entity against the defined taxonomies.

    Returns:
        Tuple of (is_valid, list_of_warnings)
    """
    warnings = []

    # Check required fields
    required_fields = ["name", "entity_type", "side", "role_label", "topic_label"]
    for field in required_fields:
        if not entity.get(field):
            warnings.append(f"Missing required field: {field}")

    # Validate entity_type
    if entity.get("entity_type") and entity["entity_type"] not in ENTITY_TYPES:
        warnings.append(f"Invalid entity_type: {entity['entity_type']}")

    # Validate role_label
    if entity.get("role_label") and entity["role_label"] not in ROLE_LABELS:
        warnings.append(f"Invalid role_label: {entity['role_label']}")

    # Validate topic_label
    if entity.get("topic_label") and entity["topic_label"] not in TOPIC_LABELS:
        warnings.append(f"Invalid topic_label: {entity['topic_label']}")

    # Validate side
    valid_sides = ["initiating", "recipient", "third_party"]
    if entity.get("side") and entity["side"] not in valid_sides:
        warnings.append(f"Invalid side: {entity['side']}")

    is_valid = len([w for w in warnings if "Missing required" in w]) == 0
    return is_valid, warnings


def validate_relationship(
    relationship: Dict[str, Any],
    entity_names: Set[str]
) -> tuple[bool, List[str]]:
    """
    Validate an extracted relationship against defined types and entity names.

    Args:
        relationship: The relationship dict to validate
        entity_names: Set of valid entity names from extraction

    Returns:
        Tuple of (is_valid, list_of_warnings)
    """
    warnings = []

    # Check required fields
    required_fields = ["source_entity", "target_entity", "relationship_type"]
    for field in required_fields:
        if not relationship.get(field):
            warnings.append(f"Missing required field: {field}")

    # Validate relationship_type
    if relationship.get("relationship_type") and relationship["relationship_type"] not in RELATIONSHIP_TYPES:
        warnings.append(f"Invalid relationship_type: {relationship['relationship_type']}")

    # Validate source_entity exists in extracted entities
    if relationship.get("source_entity") and relationship["source_entity"] not in entity_names:
        warnings.append(f"source_entity '{relationship['source_entity']}' not in extracted entities")

    # Validate target_entity exists in extracted entities
    if relationship.get("target_entity") and relationship["target_entity"] not in entity_names:
        warnings.append(f"target_entity '{relationship['target_entity']}' not in extracted entities")

    # Validate confidence
    valid_confidence = ["HIGH", "MEDIUM", "LOW"]
    if relationship.get("confidence") and relationship["confidence"] not in valid_confidence:
        warnings.append(f"Invalid confidence: {relationship['confidence']}")

    is_valid = len([w for w in warnings if "Missing required" in w]) == 0
    return is_valid, warnings


def process_documents(
    country: str,
    limit: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    doc_ids: Optional[List[str]] = None,
    dry_run: bool = False,
    model: str = "gpt-4o-mini",
    reprocess: bool = False,
    parallel_workers: int = 1
) -> Dict[str, Any]:
    """
    Process documents and extract entities.

    Uses gai() from utils.py for LLM calls, which handles API proxy and fallback.
    Automatically skips documents that have already been processed (unless --reprocess).
    Supports parallel processing with multiple workers for faster extraction.

    Args:
        country: Initiating country to filter by
        limit: Maximum documents to process
        start_date: Filter documents from this date
        end_date: Filter documents until this date
        doc_ids: Specific document IDs to process
        dry_run: If True, don't save to database
        model: LLM model to use
        reprocess: If True, reprocess documents even if already extracted
        parallel_workers: Number of parallel workers (default 1 = sequential)

    Returns:
        Summary statistics of the extraction run
    """
    stats = {
        "documents_processed": 0,
        "documents_skipped": 0,
        "entities_extracted": 0,
        "relationships_extracted": 0,
        "errors": 0,
        "validation_warnings": 0,
        "relationship_warnings": 0,
        "start_time": datetime.utcnow().isoformat(),
        "model_used": model
    }

    with get_session() as session:
        # Get already-processed doc_ids to skip (unless reprocess=True)
        processed_doc_ids = set()
        if not reprocess:
            processed_doc_ids = get_processed_doc_ids(session)

        # Build query
        query = session.query(Document).filter(
            Document.salience_bool == "true",  # Lowercase to match database values
            Document.distilled_text.isnot(None),
            Document.distilled_text != ""
        )

        if country:
            query = query.filter(Document.initiating_country == country)

        if start_date:
            query = query.filter(Document.date >= start_date)

        if end_date:
            query = query.filter(Document.date <= end_date)

        if doc_ids:
            query = query.filter(Document.doc_id.in_(doc_ids))

        # CRITICAL FIX: Exclude already-processed documents BEFORE applying limit
        if processed_doc_ids and not reprocess:
            query = query.filter(~Document.doc_id.in_(processed_doc_ids))
            logger.info(f"Excluding {len(processed_doc_ids)} already-processed documents from query")

        # Order by date descending (most recent first)
        query = query.order_by(Document.date.desc())

        if limit:
            query = query.limit(limit)

        documents = query.all()
        total_docs = len(documents)
        stats["documents_skipped"] = len(processed_doc_ids) if processed_doc_ids else 0

        logger.info(f"Found {total_docs} unprocessed documents to process")

        logger.info(f"Processing {len(documents)} new documents with {parallel_workers} worker(s)")

        all_extractions = []

        # Helper function to process and validate a single document
        def process_single_doc(doc_tuple):
            i, doc = doc_tuple
            logger.info(f"Processing {i+1}/{len(documents)}: {doc.doc_id[:8]}... ({doc.date})")

            # Extract entities using gai() via extract_entities_from_document
            result = extract_entities_from_document(doc, model)

            if result.get("error"):
                return {"type": "error", "result": result}

            # Validate entities
            valid_entities = []
            entity_warnings = []
            for entity in result.get("entities", []):
                is_valid, warnings = validate_entity(entity)
                if warnings:
                    entity_warnings.extend(warnings)
                    for w in warnings:
                        logger.warning(f"  Entity '{entity.get('name', 'unknown')}': {w}")
                if is_valid:
                    valid_entities.append(entity)

            result["entities"] = valid_entities
            result["entity_count"] = len(valid_entities)

            # Create set of valid entity names for relationship validation
            entity_names = {ent.get("name") for ent in valid_entities if ent.get("name")}

            # Validate relationships
            valid_relationships = []
            rel_warnings = []
            for rel in result.get("relationships", []):
                is_valid, warnings = validate_relationship(rel, entity_names)
                if warnings:
                    rel_warnings.extend(warnings)
                    for w in warnings:
                        logger.warning(f"  Relationship '{rel.get('source_entity', '?')} -> {rel.get('target_entity', '?')}': {w}")
                if is_valid:
                    valid_relationships.append(rel)

            result["relationships"] = valid_relationships
            result["relationship_count"] = len(valid_relationships)

            # Log progress
            if valid_entities:
                logger.info(f"  Extracted {len(valid_entities)} entities, {len(valid_relationships)} relationships")
                for ent in valid_entities[:3]:  # Show first 3
                    logger.info(f"    - {ent.get('name')} ({ent.get('entity_type')}, {ent.get('role_label')})")
                if len(valid_entities) > 3:
                    logger.info(f"    ... and {len(valid_entities) - 3} more entities")
                if valid_relationships:
                    for rel in valid_relationships[:2]:  # Show first 2 relationships
                        logger.info(f"    ~ {rel.get('source_entity')} --[{rel.get('relationship_type')}]--> {rel.get('target_entity')}")
                    if len(valid_relationships) > 2:
                        logger.info(f"    ... and {len(valid_relationships) - 2} more relationships")

            return {
                "type": "success",
                "result": result,
                "entity_warnings": len(entity_warnings),
                "rel_warnings": len(rel_warnings)
            }

        # Process documents in parallel or sequential
        if parallel_workers > 1:
            # Parallel processing with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                # Submit all documents
                futures = {executor.submit(process_single_doc, (i, doc)): (i, doc)
                          for i, doc in enumerate(documents)}

                # Process results as they complete
                for future in as_completed(futures):
                    try:
                        result_data = future.result()

                        if result_data["type"] == "error":
                            stats["errors"] += 1
                        else:
                            stats["documents_processed"] += 1
                            stats["entities_extracted"] += result_data["result"]["entity_count"]
                            stats["relationships_extracted"] += result_data["result"]["relationship_count"]
                            stats["validation_warnings"] += result_data["entity_warnings"]
                            stats["relationship_warnings"] += result_data["rel_warnings"]
                            all_extractions.append(result_data["result"])

                    except Exception as e:
                        logger.error(f"Processing error: {e}")
                        stats["errors"] += 1
        else:
            # Sequential processing (original behavior)
            for i, doc in enumerate(documents):
                result_data = process_single_doc((i, doc))

                if result_data["type"] == "error":
                    stats["errors"] += 1
                else:
                    stats["documents_processed"] += 1
                    stats["entities_extracted"] += result_data["result"]["entity_count"]
                    stats["relationships_extracted"] += result_data["result"]["relationship_count"]
                    stats["validation_warnings"] += result_data["entity_warnings"]
                    stats["relationship_warnings"] += result_data["rel_warnings"]
                    all_extractions.append(result_data["result"])

                # Rate limiting for sequential processing
                time.sleep(0.5)

        stats["end_time"] = datetime.utcnow().isoformat()

        # Save results if not dry run
        if not dry_run and all_extractions:
            # Use relative path from project root
            output_dir = Path(__file__).parent.parent.parent / "data" / "entity_extractions"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"entity_extractions_{country}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            with open(output_path, 'w') as f:
                json.dump({
                    "stats": stats,
                    "extractions": all_extractions
                }, f, indent=2, default=str)
            logger.info(f"Saved extractions to {output_path}")
            stats["output_file"] = str(output_path)

        return stats


def main():
    parser = argparse.ArgumentParser(description="Extract entities from soft power documents")
    parser.add_argument("--country", type=str, help="Initiating country to filter by")
    parser.add_argument("--limit", type=int, help="Maximum documents to process")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--doc-id", type=str, action="append", help="Specific doc_id to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to database")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="LLM model to use")
    parser.add_argument("--reprocess", action="store_true",
                        help="Force reprocess documents even if already extracted")
    parser.add_argument("--parallel-workers", type=int, default=1,
                        help="Number of parallel workers for processing (default: 1 = sequential)")

    args = parser.parse_args()

    # Parse dates
    start_date = None
    end_date = None
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()

    logger.info("Starting entity extraction pipeline")
    logger.info(f"  Country: {args.country or 'All'}")
    logger.info(f"  Limit: {args.limit or 'None'}")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(f"  Model: {args.model}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  Reprocess: {args.reprocess}")
    logger.info(f"  Parallel workers: {args.parallel_workers}")

    stats = process_documents(
        country=args.country,
        limit=args.limit,
        start_date=start_date,
        end_date=end_date,
        doc_ids=args.doc_id,
        dry_run=args.dry_run,
        model=args.model,
        reprocess=args.reprocess,
        parallel_workers=args.parallel_workers
    )

    # Print summary
    print("\n" + "="*50)
    print("EXTRACTION SUMMARY")
    print("="*50)
    print(f"Documents skipped:      {stats.get('documents_skipped', 0)} (already processed)")
    print(f"Documents processed:    {stats['documents_processed']}")
    print(f"Entities extracted:     {stats['entities_extracted']}")
    print(f"Relationships extracted:{stats['relationships_extracted']}")
    print(f"Errors:                 {stats['errors']}")
    print(f"Entity warnings:        {stats['validation_warnings']}")
    print(f"Relationship warnings:  {stats['relationship_warnings']}")
    if stats.get("output_file"):
        print(f"Output file:            {stats['output_file']}")
    print("="*50)


if __name__ == "__main__":
    main()
