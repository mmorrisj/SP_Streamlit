"""
Entity extraction pipeline for soft power network mapping.

This module provides a two-stage pipeline for extracting organizations, companies,
and key persons from soft power documents and mapping their relationships.

Two-Stage Pipeline:

    Stage 1: Daily Entity Extraction
        1A. extract_daily_entities.py - Extract raw entity mentions
        1B. cluster_daily_entities.py - Cluster by similarity (DBSCAN)
        1C. llm_deconflict_entity_clusters.py - LLM validates clusters

    Stage 2: Batch Consolidation
        2A. consolidate_all_entities.py - Cross-date entity resolution
        2B. llm_deconflict_canonical_entities.py - LLM validates groupings
        2C. merge_canonical_entities.py - Merge to master entities

Usage:
    python services/pipeline/entities/extract_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-08-31
    python services/pipeline/entities/cluster_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-08-31

See README.md for full documentation.
"""
