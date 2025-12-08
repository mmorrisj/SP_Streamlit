"""
Entity extraction pipeline for soft power network mapping.

This module provides tools for extracting organizations, companies, and key persons
from soft power documents and mapping their relationships.

Components:
    - entity_extraction.py: Extract entities from document distilled_text
    - store_entities.py: Store extracted entities with deduplication

Usage:
    python services/pipeline/entities/entity_extraction.py --country China --limit 100
    python services/pipeline/entities/store_entities.py data/entity_extractions_*.json
"""
