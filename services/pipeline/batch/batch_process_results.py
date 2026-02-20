"""
Stage 4: Process batch results and update database.

Parses results JSONL from OpenAI Batch API and updates the database
using existing deconfliction logic from sync scripts.

Usage:
    python batch_process_results.py --batch-job-id <UUID>

    # Custom checkpoint frequency
    python batch_process_results.py --batch-job-id <UUID> --checkpoint-frequency 50

    # Dry run (preview without database updates)
    python batch_process_results.py --batch-job-id <UUID> --dry-run
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import (
    EventCluster, CanonicalEvent, Document, RawEntity,
    EntityTypeEnum, EntityCluster, CanonicalEntity, DailyEntityMention, EntityRoleEnum,
    EventSourceLink
)
from services.pipeline.batch.batch_config import (
    JOB_TYPE_CLUSTER_DECONFLICT,
    JOB_TYPE_CANONICAL_DECONFLICT,
    JOB_TYPE_ENTITY_EXTRACT,
    JOB_TYPE_SCORE_MATERIALITY,
    JOB_TYPE_DAILY_ENTITY_EXTRACT,
    JOB_TYPE_ENTITY_DECONFLICT,
    JOB_TYPE_CANONICAL_ENTITY_DECONFLICT,
    JOB_TYPE_GENERATE_DAILY_SUMMARY,
    JOB_TYPE_GENERATE_WEEKLY_SUMMARY,
    JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
    JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS,
    JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
    DEFAULT_CHECKPOINT_FREQUENCY
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.custom_id import parse_custom_id
from services.pipeline.batch.utils.jsonl_utils import read_jsonl
from shared.models.models import BatchJobStatus

# Import deconfliction logic from existing sync scripts
from services.pipeline.events.llm_deconflict_clusters import LLMClusterDeconfliction
from sqlalchemy import text


def process_cluster_result(
    session,
    cluster_id: str,
    llm_response: Dict[str, Any],
    deconfliction_processor: LLMClusterDeconfliction,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process cluster deconfliction result from batch API.

    Uses existing logic from llm_deconflict_clusters.py to maintain consistency.

    Args:
        session: Database session
        cluster_id: EventCluster UUID
        llm_response: Parsed LLM response from batch result
        deconfliction_processor: Instance of LLMClusterDeconfliction
        verbose: Print progress

    Returns:
        Statistics dict with created/updated counts
    """
    stats = {
        'canonical_events_created': 0,
        'canonical_events_updated': 0,
        'daily_mentions_created': 0,
        'errors': 0
    }

    try:
        # Load cluster
        cluster = session.get(EventCluster, cluster_id)
        if not cluster:
            if verbose:
                print(f"  Warning: Cluster {cluster_id} not found, skipping")
            stats['errors'] += 1
            return stats

        # Check if already processed
        if cluster.llm_deconflicted:
            if verbose:
                print(f"  Cluster {cluster_id}: Already processed, skipping")
            return stats

        # Save deconfliction result to cluster
        deconfliction_processor.save_deconfliction_result(session, cluster, llm_response)

        if verbose:
            print(f"  Cluster {cluster_id}: Saved LLM result")

        # Create canonical events and daily mentions
        try:
            canonical_events = deconfliction_processor.create_canonical_events_from_cluster(
                session,
                cluster,
                llm_response
            )

            # Count created vs updated
            for ce in canonical_events:
                if ce.total_mention_days == 1:
                    stats['canonical_events_created'] += 1
                else:
                    stats['canonical_events_updated'] += 1
                stats['daily_mentions_created'] += 1

            if verbose:
                print(f"  Cluster {cluster_id}: Created {len(canonical_events)} canonical events")

        except Exception as e:
            if verbose:
                print(f"  Warning: Failed to create canonical events for cluster {cluster_id}: {e}")
            stats['errors'] += 1

        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing cluster {cluster_id}: {e}")
        stats['errors'] += 1
        raise


def process_canonical_result(
    session,
    master_event_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process canonical event deconfliction result from batch API.

    Uses logic from llm_deconflict_canonical_events.py for consistency.

    Args:
        session: Database session
        master_event_id: Master event UUID
        llm_response: Parsed LLM response from batch result
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'validated': 0,
        'renamed': 0,
        'split': 0,
        'errors': 0
    }

    try:
        # Load master event
        master_event = session.get(CanonicalEvent, master_event_id)
        if not master_event:
            if verbose:
                print(f"  Warning: Master event {master_event_id} not found, skipping")
            stats['errors'] += 1
            return stats

        # Check if already validated
        if master_event.llm_validated:
            if verbose:
                print(f"  Master event {master_event_id}: Already validated, skipping")
            return stats

        # Process LLM response
        same_event = llm_response.get('same_event', True)
        should_split = llm_response.get('should_split', False)
        best_canonical_name = llm_response.get('best_canonical_name')

        # Handle splitting
        if should_split and llm_response.get('split_groups'):
            if verbose:
                print(f"  Master event {master_event_id}: Splitting into {len(llm_response['split_groups'])} groups")

            # Load child events
            child_events = session.query(CanonicalEvent).filter(
                CanonicalEvent.master_event_id == master_event_id
            ).all()

            # Create map of event IDs to events
            all_events = [master_event] + child_events
            event_map = {i+1: event for i, event in enumerate(all_events)}

            # Process each split group
            for subgroup in llm_response['split_groups']:
                indices = subgroup.get('indices', [])
                new_canonical_name = subgroup.get('canonical_name')

                if not indices or not new_canonical_name:
                    continue

                # Get events in this subgroup
                subgroup_events = [event_map[idx] for idx in indices if idx in event_map]

                if not subgroup_events:
                    continue

                # Find best event or create new master
                best_event = next((e for e in subgroup_events if e.canonical_name == new_canonical_name), None)
                if not best_event:
                    best_event = max(subgroup_events, key=lambda e: e.total_articles)

                # Make this event the new master
                best_event.master_event_id = None
                best_event.llm_validated = True
                best_event.llm_validated_at = datetime.utcnow()

                # Point other events to this master
                for event in subgroup_events:
                    if event.id != best_event.id:
                        event.master_event_id = best_event.id

            stats['split'] += 1

        # Handle renaming
        elif same_event and best_canonical_name:
            current_name = master_event.canonical_name

            if best_canonical_name != current_name:
                # Find event with best name in the group
                all_events_in_group = session.query(CanonicalEvent).filter(
                    (CanonicalEvent.id == master_event_id) |
                    (CanonicalEvent.master_event_id == master_event_id)
                ).all()

                best_event = next((e for e in all_events_in_group if e.canonical_name == best_canonical_name), None)

                if best_event and best_event.id != master_event_id:
                    # Swap master
                    old_master_id = master_event_id
                    new_master_id = best_event.id

                    # Set old master to point to new master
                    master_event.master_event_id = new_master_id

                    # Update all children to point to new master
                    session.execute(
                        text('UPDATE canonical_events SET master_event_id = :new_master WHERE master_event_id = :old_master'),
                        {'new_master': new_master_id, 'old_master': old_master_id}
                    )

                    # Set new master's fields
                    best_event.master_event_id = None
                    best_event.llm_validated = True
                    best_event.llm_validated_at = datetime.utcnow()

                    if verbose:
                        print(f"  Master event {master_event_id}: Renamed via swap to {best_canonical_name}")

                    stats['renamed'] += 1
                else:
                    # Just mark as validated
                    master_event.llm_validated = True
                    master_event.llm_validated_at = datetime.utcnow()
            else:
                # No change needed, just validate
                master_event.llm_validated = True
                master_event.llm_validated_at = datetime.utcnow()

        else:
            # No changes, just validate
            master_event.llm_validated = True
            master_event.llm_validated_at = datetime.utcnow()

        stats['validated'] += 1
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing master event {master_event_id}: {e}")
        stats['errors'] += 1
        raise


def process_entity_extract_result(
    session,
    event_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process entity extraction result from batch API.

    Updates canonical_events.entities_mentioned with extracted entities.

    Args:
        session: Database session
        event_id: Canonical event UUID
        llm_response: Parsed LLM response from batch result
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'entities_extracted': 0,
        'errors': 0
    }

    try:
        # Load canonical event
        event = session.get(CanonicalEvent, event_id)
        if not event:
            if verbose:
                print(f"  Warning: Event {event_id} not found, skipping")
            stats['errors'] += 1
            return stats

        # Check if already processed (unless force=True was used)
        if event.entities_mentioned:
            if verbose:
                print(f"  Event {event_id}: Already has entities, skipping")
            return stats

        # Extract entities from LLM response
        entities = {
            'persons': llm_response.get('persons', []),
            'organizations': llm_response.get('organizations', []),
            'companies': llm_response.get('companies', []),
            'locations': llm_response.get('locations', [])
        }

        # Update event
        event.entities_mentioned = entities
        event.updated_at = datetime.utcnow()

        if verbose:
            total_entities = sum(len(v) for v in entities.values())
            print(f"  Event {event_id}: Extracted {total_entities} entities")

        stats['entities_extracted'] += 1
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing event {event_id}: {e}")
        stats['errors'] += 1
        raise


def process_materiality_score_result(
    session,
    event_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process materiality scoring result from batch API.

    Updates canonical_events.material_score with LLM score.

    Args:
        session: Database session
        event_id: Canonical event UUID
        llm_response: Parsed LLM response from batch result
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'events_scored': 0,
        'errors': 0
    }

    try:
        # Load canonical event
        event = session.get(CanonicalEvent, event_id)
        if not event:
            if verbose:
                print(f"  Warning: Event {event_id} not found, skipping")
            stats['errors'] += 1
            return stats

        # Check if already scored (unless rescore=True was used)
        if event.material_score is not None:
            if verbose:
                print(f"  Event {event_id}: Already scored, skipping")
            return stats

        # Extract score from LLM response
        # Prompt uses "material_score" but also accept "materiality_score" for robustness
        score = llm_response.get('material_score') or llm_response.get('materiality_score')
        justification = llm_response.get('justification', '')

        if score is None:
            if verbose:
                print(f"  Warning: Event {event_id}: No materiality_score in response")
            stats['errors'] += 1
            return stats

        # Validate score is in range 1.0-10.0
        try:
            score = float(score)
            if not (1.0 <= score <= 10.0):
                if verbose:
                    print(f"  Warning: Event {event_id}: Score {score} out of range [1.0, 10.0]")
                stats['errors'] += 1
                return stats
        except (ValueError, TypeError):
            if verbose:
                print(f"  Warning: Event {event_id}: Invalid score format: {score}")
            stats['errors'] += 1
            return stats

        # Update event
        event.material_score = score
        event.updated_at = datetime.utcnow()

        if verbose:
            print(f"  Event {event_id}: Scored {score:.1f}/10.0")

        stats['events_scored'] += 1
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing event {event_id}: {e}")
        stats['errors'] += 1
        raise


def process_daily_entity_extract_result(
    session,
    doc_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process entity extraction result from batch API.

    Saves extracted entities to raw_entities table.

    Args:
        session: Database session
        doc_id: Document ID
        llm_response: Parsed LLM response from batch result
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'entities_extracted': 0,
        'errors': 0
    }

    try:
        # Load document
        doc = session.get(Document, doc_id)
        if not doc:
            if verbose:
                print(f"  Warning: Document {doc_id} not found, skipping")
            stats['errors'] += 1
            return stats

        # Check if document already has entities (unless force mode)
        existing_count = session.query(RawEntity).filter(RawEntity.doc_id == doc_id).count()
        if existing_count > 0:
            if verbose:
                print(f"  Document {doc_id}: Already has {existing_count} entities, skipping")
            return stats

        # Extract entities from response, deduplicating by (entity_name, entity_type)
        # The LLM can return the same entity multiple times with different context snippets
        entity_count = 0
        seen_keys = set()

        type_map = {
            'persons': EntityTypeEnum.PERSON,
            'organizations': EntityTypeEnum.ORGANIZATION,
            'companies': EntityTypeEnum.COMPANY,
            'locations': EntityTypeEnum.LOCATION,
        }

        for category, entity_type in type_map.items():
            for item in llm_response.get(category, []):
                name = item.get('entity_name')
                if not name:
                    continue

                # Deduplicate by (entity_name, entity_type)
                dedup_key = (name, entity_type.value)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                entity = RawEntity(
                    doc_id=doc_id,
                    entity_name=name,
                    entity_type=entity_type,
                    role=item.get('role'),
                    country_affiliation=item.get('country_affiliation'),
                    context_snippet=item.get('context_snippet')
                )
                session.add(entity)
                entity_count += 1

        if verbose:
            print(f"  Document {doc_id}: Extracted {entity_count} entities")

        stats['entities_extracted'] += entity_count
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing document {doc_id}: {e}")
        stats['errors'] += 1
        raise


def process_entity_deconflict_result(
    session,
    cluster_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process entity cluster deconfliction result from batch API.

    Updates EntityCluster.refined_clusters and creates CanonicalEntity
    and DailyEntityMention records.

    Adapted from llm_deconflict_entity_clusters.py:save_deconfliction_result()
    and create_canonical_entities_from_cluster().

    Args:
        session: Database session
        cluster_id: EntityCluster UUID
        llm_response: Parsed LLM response from batch result
        verbose: Print progress

    Returns:
        Statistics dict
    """
    from sqlalchemy import text
    from collections import defaultdict

    stats = {
        'canonical_entities_created': 0,
        'canonical_entities_updated': 0,
        'daily_mentions_created': 0,
        'confirmed': 0,
        'split': 0,
        'errors': 0
    }

    try:
        # Load cluster
        cluster = session.get(EntityCluster, cluster_id)
        if not cluster:
            if verbose:
                print(f"  Warning: EntityCluster {cluster_id} not found, skipping")
            stats['errors'] += 1
            return stats

        if cluster.llm_deconflicted:
            if verbose:
                print(f"  Cluster {cluster_id}: Already deconflicted, skipping")
            return stats

        # Extract LLM result fields
        same_entity = llm_response.get('same_entity', True)
        explanation = llm_response.get('explanation', '')
        canonical_name = llm_response.get('canonical_name', '')
        primary_role_str = llm_response.get('primary_role', 'other')
        country_affiliation = llm_response.get('country_affiliation')
        unique_names = list(set(cluster.entity_names))
        groups = llm_response.get('groups', [[i+1 for i in range(len(unique_names))]])

        # Save refined_clusters to the cluster record
        refined_data = {
            'same_entity': same_entity,
            'explanation': explanation,
            'canonical_name': canonical_name or unique_names[0],
            'primary_role': primary_role_str,
            'country_affiliation': country_affiliation,
            'original_cluster_size': cluster.cluster_size,
            'unique_entity_names': len(unique_names),
            'groups': groups,
            'reviewed_at': datetime.utcnow().isoformat(),
            'unique_names_list': unique_names
        }
        cluster.refined_clusters = refined_data
        cluster.llm_deconflicted = True

        if same_entity:
            stats['confirmed'] += 1
        else:
            stats['split'] += 1

        # Create canonical entities and daily mentions for each group
        name_to_docs = defaultdict(list)
        for entity_name, doc_id in zip(cluster.entity_names, cluster.doc_ids):
            name_to_docs[entity_name].append(doc_id)

        for group_indices in groups:
            group_names = [unique_names[idx - 1] for idx in group_indices if 1 <= idx <= len(unique_names)]
            if not group_names:
                continue

            # Collect doc_ids for this group
            group_doc_ids = []
            for name in group_names:
                group_doc_ids.extend(name_to_docs[name])
            group_doc_ids = list(dict.fromkeys(group_doc_ids))

            if not group_doc_ids:
                continue

            # Choose canonical name
            if same_entity and canonical_name:
                group_canonical_name = canonical_name
            else:
                group_canonical_name = max(group_names, key=group_names.count)

            # Map role to enum
            try:
                primary_role = EntityRoleEnum(primary_role_str)
            except ValueError:
                primary_role = EntityRoleEnum.OTHER

            # Query recipient countries from linked documents
            recipients_query = session.execute(text("""
                SELECT rc.recipient_country, COUNT(*) as count
                FROM recipient_countries rc
                WHERE rc.doc_id = ANY(:doc_ids)
                GROUP BY rc.recipient_country
            """), {"doc_ids": group_doc_ids}).fetchall()
            primary_recipients = {row[0]: row[1] for row in recipients_query}

            # Query categories from linked documents
            categories_query = session.execute(text("""
                SELECT c.category, COUNT(*) as count
                FROM categories c
                WHERE c.doc_id = ANY(:doc_ids)
                GROUP BY c.category
            """), {"doc_ids": group_doc_ids}).fetchall()
            primary_categories = {row[0]: row[1] for row in categories_query}

            # Get country affiliations from raw entities
            affiliations_query = session.execute(text("""
                SELECT DISTINCT country_affiliation
                FROM raw_entities
                WHERE doc_id = ANY(:doc_ids)
                  AND entity_name = ANY(:entity_names)
                  AND country_affiliation IS NOT NULL
            """), {"doc_ids": group_doc_ids, "entity_names": group_names}).fetchall()
            country_affiliations = [row[0] for row in affiliations_query if row[0]]

            # Check if canonical entity already exists
            existing_entity = session.query(CanonicalEntity).filter(
                CanonicalEntity.canonical_name == group_canonical_name,
                CanonicalEntity.entity_type == cluster.entity_type,
                CanonicalEntity.initiating_country == cluster.initiating_country
            ).first()

            savepoint = session.begin_nested()
            try:
                if existing_entity:
                    canonical_entity = existing_entity
                    canonical_entity.last_mention_date = max(
                        canonical_entity.last_mention_date, cluster.cluster_date
                    )
                    canonical_entity.total_documents += len(group_doc_ids)

                    for name in group_names:
                        if name != group_canonical_name and name not in canonical_entity.alternative_names:
                            canonical_entity.alternative_names = canonical_entity.alternative_names + [name]

                    for aff in country_affiliations:
                        if aff not in canonical_entity.country_affiliations:
                            canonical_entity.country_affiliations = canonical_entity.country_affiliations + [aff]

                    stats['canonical_entities_updated'] += 1
                else:
                    canonical_entity = CanonicalEntity(
                        canonical_name=group_canonical_name,
                        entity_type=cluster.entity_type,
                        initiating_country=cluster.initiating_country,
                        primary_role=primary_role,
                        country_affiliations=country_affiliations,
                        alternative_names=[n for n in group_names if n != group_canonical_name],
                        first_mention_date=cluster.cluster_date,
                        last_mention_date=cluster.cluster_date,
                        total_mention_days=1,
                        total_documents=len(group_doc_ids),
                        primary_categories=primary_categories,
                        primary_recipients=primary_recipients,
                        associated_events=[]
                    )
                    session.add(canonical_entity)
                    session.flush()
                    stats['canonical_entities_created'] += 1

                # Create or update DailyEntityMention
                existing_mention = session.query(DailyEntityMention).filter(
                    DailyEntityMention.canonical_entity_id == canonical_entity.id,
                    DailyEntityMention.mention_date == cluster.cluster_date
                ).first()

                if existing_mention:
                    existing_mention.document_count = len(group_doc_ids)
                    existing_mention.doc_ids = group_doc_ids
                else:
                    daily_mention = DailyEntityMention(
                        canonical_entity_id=canonical_entity.id,
                        initiating_country=cluster.initiating_country,
                        mention_date=cluster.cluster_date,
                        document_count=len(group_doc_ids),
                        primary_role_this_day=primary_role_str,
                        doc_ids=group_doc_ids,
                        associated_event_ids=[]
                    )
                    session.add(daily_mention)
                    session.flush()
                    stats['daily_mentions_created'] += 1

                savepoint.commit()

            except Exception as e:
                savepoint.rollback()
                if verbose:
                    safe_name = group_canonical_name.encode('ascii', 'replace').decode('ascii')[:60]
                    print(f"  Error creating canonical entity '{safe_name}': {e}")
                stats['errors'] += 1

        if verbose:
            action = "Confirmed" if same_entity else f"Split into {len(groups)} groups"
            print(f"  Cluster {cluster_id}: {action}")

        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing cluster {cluster_id}: {e}")
        stats['errors'] += 1
        raise


VALID_ENTITY_ROLES = [
    "government_official", "diplomat", "business_leader", "cultural_figure",
    "military_official", "academic", "media_figure", "civil_society",
    "implementing_organization", "funding_organization", "recipient_institution",
    "infrastructure_project", "venue", "other"
]


def process_canonical_entity_deconflict_result(
    session,
    master_entity_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process canonical entity group deconfliction result from batch API.

    Adapted from llm_deconflict_canonical_entities.py:process_country()

    Handles:
    - Splitting groups into subgroups with new masters
    - Renaming (swapping master when best name is on a child)
    - Role updates
    - Marking master as llm_validated=True

    Args:
        session: Database session
        master_entity_id: Master entity UUID
        llm_response: Parsed LLM response from batch result
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'validated': 0,
        'renamed': 0,
        'split': 0,
        'errors': 0
    }

    try:
        # Load master entity
        master_entity = session.get(CanonicalEntity, master_entity_id)
        if not master_entity:
            if verbose:
                print(f"  Warning: Master entity {master_entity_id} not found, skipping")
            stats['errors'] += 1
            return stats

        if master_entity.llm_validated:
            if verbose:
                print(f"  Master entity {master_entity_id}: Already validated, skipping")
            return stats

        # Load child entities
        child_entities = session.query(CanonicalEntity).filter(
            CanonicalEntity.master_entity_id == master_entity_id
        ).all()

        # Build ordered entity list (master first, then children)
        all_entities = [master_entity] + child_entities

        # Extract LLM response fields
        same_entity = llm_response.get('same_entity', True)
        should_split = llm_response.get('should_split', False)
        best_canonical_name = llm_response.get('best_canonical_name')
        best_role = llm_response.get('best_primary_role')

        # Validate role
        if best_role and best_role not in VALID_ENTITY_ROLES:
            best_role = 'other'

        # Handle splitting
        if should_split and llm_response.get('split_groups'):
            if verbose:
                print(f"  Master entity {master_entity_id}: Splitting into {len(llm_response['split_groups'])} groups")
            stats['split'] += 1

            for subgroup in llm_response['split_groups']:
                indices = subgroup.get('indices', [])
                new_canonical_name = subgroup.get('canonical_name')
                new_role = subgroup.get('primary_role')

                if not indices or not new_canonical_name:
                    continue

                # Get entities in this subgroup (1-indexed)
                subgroup_entities = [all_entities[idx-1] for idx in indices
                                     if 0 < idx <= len(all_entities)]

                if len(subgroup_entities) == 0:
                    continue

                # Find the entity with this name, or use highest doc count
                best_entity = next((e for e in subgroup_entities
                                    if e.canonical_name == new_canonical_name), None)
                if not best_entity:
                    best_entity = max(subgroup_entities,
                                      key=lambda e: e.total_documents or 0)

                new_master_id = best_entity.id

                # Set the new master: clear master_entity_id, mark validated
                best_entity.master_entity_id = None
                best_entity.llm_validated = True
                best_entity.llm_validated_at = datetime.utcnow()

                if new_role and new_role in VALID_ENTITY_ROLES:
                    try:
                        best_entity.primary_role = EntityRoleEnum(new_role)
                    except ValueError:
                        pass

                # Point all other entities in this subgroup to the new master
                for entity in subgroup_entities:
                    if entity.id != new_master_id:
                        entity.master_entity_id = new_master_id

        # Handle rename / role update
        elif same_entity and best_canonical_name:
            current_master_name = master_entity.canonical_name

            if best_canonical_name != current_master_name:
                stats['renamed'] += 1

                # Find the entity with the best name
                best_entity = next((e for e in all_entities
                                    if e.canonical_name == best_canonical_name), None)

                if best_entity and best_entity.id != master_entity.id:
                    old_master_id = master_entity.id
                    new_master_id = best_entity.id

                    # Set old master to point to new master
                    master_entity.master_entity_id = new_master_id

                    # Update all other children to point to new master
                    session.execute(
                        text('UPDATE canonical_entities SET master_entity_id = :new_master WHERE master_entity_id = :old_master'),
                        {'new_master': new_master_id, 'old_master': old_master_id}
                    )

                    # Set new master's fields
                    best_entity.master_entity_id = None
                    best_entity.llm_validated = True
                    best_entity.llm_validated_at = datetime.utcnow()

                    if best_role and best_role in VALID_ENTITY_ROLES:
                        try:
                            best_entity.primary_role = EntityRoleEnum(best_role)
                        except ValueError:
                            pass

                    if verbose:
                        print(f"  Master entity {master_entity_id}: Swapped master to {best_canonical_name}")
                else:
                    # Name not found in group or already master, just validate
                    master_entity.llm_validated = True
                    master_entity.llm_validated_at = datetime.utcnow()

                    if best_role and best_role in VALID_ENTITY_ROLES:
                        try:
                            master_entity.primary_role = EntityRoleEnum(best_role)
                        except ValueError:
                            pass
            else:
                # No name change, update role and validate
                master_entity.llm_validated = True
                master_entity.llm_validated_at = datetime.utcnow()

                if best_role and best_role in VALID_ENTITY_ROLES:
                    try:
                        master_entity.primary_role = EntityRoleEnum(best_role)
                    except ValueError:
                        pass
        else:
            # No changes needed, just mark as validated
            master_entity.llm_validated = True
            master_entity.llm_validated_at = datetime.utcnow()

        stats['validated'] += 1
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing master entity {master_entity_id}: {e}")
        stats['errors'] += 1
        raise


def process_daily_summary_result(
    session,
    master_event_id: str,
    llm_response: Dict[str, Any],
    date_str: str,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process daily summary generation result from batch API.

    Re-queries the database for event metadata and doc_ids, then creates
    EventSummary and EventSourceLink records.

    Adapted from generate_daily_summaries.py:generate_daily_summary_for_event()

    Args:
        session: Database session
        master_event_id: Master canonical event UUID
        llm_response: Parsed LLM response with 'overview' and 'outcomes'
        date_str: Date string (YYYY-MM-DD) from custom_id suffix
        verbose: Print progress

    Returns:
        Statistics dict
    """
    from shared.utils.citation_utils import build_hyperlink, get_citations_for_doc_ids
    from sqlalchemy import select

    stats = {
        'summaries_created': 0,
        'source_links_created': 0,
        'errors': 0
    }

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Load master event
        master_event = session.get(CanonicalEvent, master_event_id)
        if not master_event:
            if verbose:
                print(f"  Warning: Master event {master_event_id} not found, skipping")
            stats['errors'] += 1
            return stats

        country = master_event.initiating_country
        canonical_name = master_event.canonical_name

        # Check if summary already exists (use raw SQL to avoid model/DB column mismatch)
        existing = session.execute(text("""
            SELECT 1 FROM event_summaries
            WHERE period_type = :period_type
              AND period_start = :period_start
              AND period_end = :period_end
              AND initiating_country = :country
              AND event_name = :event_name
            LIMIT 1
        """), {
            'period_type': 'DAILY',
            'period_start': date,
            'period_end': date,
            'country': country,
            'event_name': canonical_name
        }).fetchone()

        if existing:
            if verbose:
                print(f"  Summary already exists for {canonical_name} on {date_str}, skipping")
            return stats

        # Validate LLM response
        overview = llm_response.get('overview')
        outcomes = llm_response.get('outcomes')
        if not overview or not outcomes:
            if verbose:
                print(f"  Warning: Missing overview/outcomes in response for {master_event_id} on {date_str}")
            stats['errors'] += 1
            return stats

        # Re-query doc_ids for this event on this date
        doc_query = text("""
            WITH event_family AS (
                SELECT ce.id as canonical_event_id
                FROM canonical_events ce
                WHERE ce.id = :master_id OR ce.master_event_id = :master_id
            ),
            daily_mentions AS (
                SELECT dem.doc_ids
                FROM daily_event_mentions dem
                WHERE dem.canonical_event_id IN (SELECT canonical_event_id FROM event_family)
                  AND dem.mention_date = :date
            )
            SELECT COALESCE(
                array_agg(DISTINCT unnested_doc) FILTER (WHERE unnested_doc IS NOT NULL),
                ARRAY[]::text[]
            ) as doc_ids
            FROM daily_mentions dm
            LEFT JOIN LATERAL unnest(dm.doc_ids) unnested_doc ON true
        """)

        doc_result = session.execute(
            doc_query, {"master_id": master_event_id, "date": date}
        ).fetchone()

        doc_ids = list(doc_result.doc_ids) if doc_result and doc_result.doc_ids else []
        valid_doc_ids = [d for d in doc_ids if d is not None]

        if not valid_doc_ids:
            if verbose:
                print(f"  Warning: No doc_ids found for {master_event_id} on {date_str}")
            stats['errors'] += 1
            return stats

        # Get representative docs for weighting
        stmt = (
            select(Document)
            .where(Document.doc_id.in_(valid_doc_ids))
            .order_by(Document.date.desc())
            .limit(5)
        )
        representative_docs = list(session.execute(stmt).scalars().all())
        representative_doc_ids = {d.doc_id for d in representative_docs}

        # Build hyperlink and citations
        source_link = build_hyperlink(valid_doc_ids)
        citations = get_citations_for_doc_ids(valid_doc_ids[:10])

        # Get categories and recipients from master event
        primary_categories = master_event.primary_categories or {}
        primary_recipients = master_event.primary_recipients or {}

        # Create EventSummary via raw SQL (model has columns not yet in DB)
        import uuid as _uuid
        summary_id = str(_uuid.uuid4())
        narrative = json.dumps({
            'overview': overview,
            'outcomes': outcomes,
            'source_link': source_link,
            'source_count': len(valid_doc_ids),
            'citations': citations
        })
        cat_json = json.dumps(primary_categories)
        recip_json = json.dumps(primary_recipients)

        session.execute(text("""
            INSERT INTO event_summaries (
                id, period_type, period_start, period_end,
                event_name, initiating_country,
                first_observed_date, last_observed_date,
                status, created_at, updated_at, is_deleted,
                category_count, subcategory_count, recipient_count, source_count,
                total_documents_across_categories, total_documents_across_subcategories,
                total_documents_across_recipients, total_documents_across_sources,
                count_by_category, count_by_subcategory, count_by_recipient, count_by_source,
                narrative_summary
            ) VALUES (
                :id, :period_type, :period_start, :period_end,
                :event_name, :country,
                :first_observed, :last_observed,
                'ACTIVE', NOW(), NOW(), false,
                0, 0, 0, 0,
                0, 0,
                0, :total_docs,
                CAST(:categories AS jsonb), '{}'::jsonb, CAST(:recipients AS jsonb), '{}'::jsonb,
                CAST(:narrative AS jsonb)
            )
        """), {
            'id': summary_id,
            'period_type': 'DAILY',
            'period_start': date,
            'period_end': date,
            'event_name': canonical_name,
            'country': country,
            'first_observed': date,
            'last_observed': date,
            'narrative': narrative,
            'categories': cat_json,
            'recipients': recip_json,
            'total_docs': len(valid_doc_ids)
        })

        stats['summaries_created'] += 1

        # Create EventSourceLink records
        for doc_id in valid_doc_ids:
            weight = 1.0 if doc_id in representative_doc_ids else 0.5
            link = EventSourceLink(
                event_summary_id=summary_id,
                doc_id=doc_id,
                contribution_weight=weight
            )
            session.add(link)
            stats['source_links_created'] += 1

        if verbose:
            print(f"  Created summary for {canonical_name} on {date_str} "
                  f"({len(valid_doc_ids)} docs, {stats['source_links_created']} links)")

        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing daily summary {master_event_id} on {date_str}: {e}")
        stats['errors'] += 1
        raise


def process_weekly_summary_result(
    session,
    canonical_event_id: str,
    llm_response: Dict[str, Any],
    week_str: str,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process weekly summary generation result from batch API.

    Re-queries daily summaries for this event+week, collects source doc_ids,
    and creates EventSummary and EventSourceLink records.

    Adapted from generate_weekly_summaries.py:generate_weekly_summary()

    Args:
        session: Database session
        canonical_event_id: Master canonical event UUID
        llm_response: Parsed LLM response with 'overview', 'outcomes', 'progression'
        week_str: Week string from custom_id suffix (e.g., "2024-09-02_2024-09-08")
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'summaries_created': 0,
        'source_links_created': 0,
        'errors': 0
    }

    try:
        # Parse week_start and week_end from suffix
        # Suffix format: "2024-09-02_2024-09-08" → 2 date strings when split by _
        week_parts = week_str.split('_')
        if len(week_parts) != 2:
            if verbose:
                print(f"  Warning: Invalid week suffix format: {week_str}")
            stats['errors'] += 1
            return stats

        week_start_str = week_parts[0]
        week_end_str = week_parts[1]
        week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        week_end = datetime.strptime(week_end_str, '%Y-%m-%d').date()

        # Load master event
        master_event = session.get(CanonicalEvent, canonical_event_id)
        if not master_event:
            if verbose:
                print(f"  Warning: Master event {canonical_event_id} not found, skipping")
            stats['errors'] += 1
            return stats

        country = master_event.initiating_country
        canonical_name = master_event.canonical_name

        # Check if weekly summary already exists
        existing = session.execute(text("""
            SELECT 1 FROM event_summaries
            WHERE period_type = :period_type
              AND period_start = :period_start
              AND period_end = :period_end
              AND initiating_country = :country
              AND event_name = :event_name
            LIMIT 1
        """), {
            'period_type': 'WEEKLY',
            'period_start': week_start,
            'period_end': week_end,
            'country': country,
            'event_name': canonical_name
        }).fetchone()

        if existing:
            if verbose:
                print(f"  Weekly summary already exists for {canonical_name} ({week_start_str} to {week_end_str}), skipping")
            return stats

        # Validate LLM response
        overview = llm_response.get('overview')
        outcomes = llm_response.get('outcomes')
        progression = llm_response.get('progression')
        if not overview or not outcomes or not progression:
            if verbose:
                print(f"  Warning: Missing overview/outcomes/progression in response for {canonical_event_id}")
            stats['errors'] += 1
            return stats

        # Get daily summaries for this event+week to find date range and source docs
        daily_result = session.execute(text('''
            SELECT
                es.id as summary_id,
                es.period_start,
                es.period_end
            FROM event_summaries es
            JOIN canonical_events ce ON es.event_name = ce.canonical_name
            WHERE es.initiating_country = :country
              AND es.period_type = 'DAILY'
              AND es.period_start >= :week_start
              AND es.period_end <= :week_end
              AND ce.master_event_id IS NULL
              AND ce.id = :canonical_event_id
              AND es.status = 'ACTIVE'
            ORDER BY es.period_start
        '''), {
            'country': country,
            'week_start': week_start,
            'week_end': week_end,
            'canonical_event_id': canonical_event_id
        }).fetchall()

        if not daily_result:
            if verbose:
                print(f"  Warning: No daily summaries found for {canonical_name} week {week_start_str}")
            stats['errors'] += 1
            return stats

        # Get first/last observed dates from daily summaries
        first_observed = min(row[1] for row in daily_result)
        last_observed = max(row[2] for row in daily_result)

        # Collect all doc_ids from constituent daily summaries via event_source_links
        daily_summary_ids = [str(row[0]) for row in daily_result]
        doc_ids = set()
        for sid in daily_summary_ids:
            links = session.execute(text('''
                SELECT doc_id FROM event_source_links
                WHERE event_summary_id = :summary_id
            '''), {'summary_id': sid}).fetchall()
            doc_ids.update(row[0] for row in links)

        valid_doc_ids = [d for d in doc_ids if d is not None]

        # Create EventSummary via raw SQL INSERT (same pattern as daily)
        import uuid as _uuid
        summary_id = str(_uuid.uuid4())
        narrative = json.dumps({
            'overview': overview,
            'outcomes': outcomes,
            'progression': progression
        })

        session.execute(text("""
            INSERT INTO event_summaries (
                id, period_type, period_start, period_end,
                event_name, initiating_country,
                first_observed_date, last_observed_date,
                status, created_at, updated_at, is_deleted,
                category_count, subcategory_count, recipient_count, source_count,
                total_documents_across_categories, total_documents_across_subcategories,
                total_documents_across_recipients, total_documents_across_sources,
                count_by_category, count_by_subcategory, count_by_recipient, count_by_source,
                narrative_summary
            ) VALUES (
                :id, :period_type, :period_start, :period_end,
                :event_name, :country,
                :first_observed, :last_observed,
                'ACTIVE', NOW(), NOW(), false,
                0, 0, 0, 0,
                0, 0,
                0, :total_docs,
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                CAST(:narrative AS jsonb)
            )
        """), {
            'id': summary_id,
            'period_type': 'WEEKLY',
            'period_start': week_start,
            'period_end': week_end,
            'event_name': canonical_name,
            'country': country,
            'first_observed': first_observed,
            'last_observed': last_observed,
            'narrative': narrative,
            'total_docs': len(valid_doc_ids)
        })

        stats['summaries_created'] += 1

        # Create EventSourceLink records
        for doc_id in valid_doc_ids:
            link = EventSourceLink(
                event_summary_id=summary_id,
                doc_id=doc_id
            )
            session.add(link)
            stats['source_links_created'] += 1

        if verbose:
            print(f"  Created weekly summary for {canonical_name} ({week_start_str} to {week_end_str}) "
                  f"({len(valid_doc_ids)} docs, {stats['source_links_created']} links)")

        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing weekly summary {canonical_event_id} for {week_str}: {e}")
        stats['errors'] += 1
        raise


def process_monthly_summary_result(
    session,
    canonical_event_id: str,
    llm_response: Dict[str, Any],
    month_str: str,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process monthly summary generation result from batch API.

    Re-queries weekly summaries for this event+month, collects source doc_ids,
    and creates EventSummary and EventSourceLink records.

    Adapted from generate_monthly_summaries.py:generate_monthly_summary()

    Args:
        session: Database session
        canonical_event_id: Master canonical event UUID
        llm_response: Parsed LLM response with 'monthly_overview', 'key_outcomes', 'strategic_significance'
        month_str: Month string from custom_id suffix (e.g., "2024-09-01_2024-09-30")
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'summaries_created': 0,
        'source_links_created': 0,
        'errors': 0
    }

    try:
        # Parse month_start and month_end from suffix
        # Suffix format: "2024-09-01_2024-09-30" → 2 date strings when split by _
        month_parts = month_str.split('_')
        if len(month_parts) != 2:
            if verbose:
                print(f"  Warning: Invalid month suffix format: {month_str}")
            stats['errors'] += 1
            return stats

        month_start_str = month_parts[0]
        month_end_str = month_parts[1]
        month_start = datetime.strptime(month_start_str, '%Y-%m-%d').date()
        month_end = datetime.strptime(month_end_str, '%Y-%m-%d').date()

        # Load master event
        master_event = session.get(CanonicalEvent, canonical_event_id)
        if not master_event:
            if verbose:
                print(f"  Warning: Master event {canonical_event_id} not found, skipping")
            stats['errors'] += 1
            return stats

        country = master_event.initiating_country
        canonical_name = master_event.canonical_name

        # Check if monthly summary already exists
        existing = session.execute(text("""
            SELECT 1 FROM event_summaries
            WHERE period_type = :period_type
              AND period_start = :period_start
              AND period_end = :period_end
              AND initiating_country = :country
              AND event_name = :event_name
            LIMIT 1
        """), {
            'period_type': 'MONTHLY',
            'period_start': month_start,
            'period_end': month_end,
            'country': country,
            'event_name': canonical_name
        }).fetchone()

        if existing:
            if verbose:
                print(f"  Monthly summary already exists for {canonical_name} ({month_start_str} to {month_end_str}), skipping")
            return stats

        # Validate LLM response
        monthly_overview = llm_response.get('monthly_overview')
        key_outcomes = llm_response.get('key_outcomes')
        strategic_significance = llm_response.get('strategic_significance')
        if not monthly_overview or not key_outcomes or not strategic_significance:
            if verbose:
                print(f"  Warning: Missing required fields in response for {canonical_event_id}")
            stats['errors'] += 1
            return stats

        # Get weekly summaries for this event+month to find date range and source docs
        weekly_result = session.execute(text('''
            SELECT
                es.id as summary_id,
                es.period_start,
                es.period_end
            FROM event_summaries es
            JOIN canonical_events ce ON es.event_name = ce.canonical_name
            WHERE es.initiating_country = :country
              AND es.period_type = 'WEEKLY'
              AND es.period_start >= :month_start
              AND es.period_end <= :month_end
              AND ce.master_event_id IS NULL
              AND ce.id = :canonical_event_id
              AND es.status = 'ACTIVE'
            ORDER BY es.period_start
        '''), {
            'country': country,
            'month_start': month_start,
            'month_end': month_end,
            'canonical_event_id': canonical_event_id
        }).fetchall()

        if not weekly_result:
            if verbose:
                print(f"  Warning: No weekly summaries found for {canonical_name} month {month_start_str}")
            stats['errors'] += 1
            return stats

        # Get first/last observed dates from weekly summaries
        first_observed = min(row[1] for row in weekly_result)
        last_observed = max(row[2] for row in weekly_result)

        # Collect all doc_ids from constituent weekly summaries via event_source_links
        weekly_summary_ids = [str(row[0]) for row in weekly_result]
        doc_ids = set()
        for sid in weekly_summary_ids:
            links = session.execute(text('''
                SELECT doc_id FROM event_source_links
                WHERE event_summary_id = :summary_id
            '''), {'summary_id': sid}).fetchall()
            doc_ids.update(row[0] for row in links)

        valid_doc_ids = [d for d in doc_ids if d is not None]

        # Create EventSummary via raw SQL INSERT
        import uuid as _uuid
        summary_id = str(_uuid.uuid4())
        narrative = json.dumps({
            'monthly_overview': monthly_overview,
            'key_outcomes': key_outcomes,
            'strategic_significance': strategic_significance
        })

        session.execute(text("""
            INSERT INTO event_summaries (
                id, period_type, period_start, period_end,
                event_name, initiating_country,
                first_observed_date, last_observed_date,
                status, created_at, updated_at, is_deleted,
                category_count, subcategory_count, recipient_count, source_count,
                total_documents_across_categories, total_documents_across_subcategories,
                total_documents_across_recipients, total_documents_across_sources,
                count_by_category, count_by_subcategory, count_by_recipient, count_by_source,
                narrative_summary
            ) VALUES (
                :id, :period_type, :period_start, :period_end,
                :event_name, :country,
                :first_observed, :last_observed,
                'ACTIVE', NOW(), NOW(), false,
                0, 0, 0, 0,
                0, 0,
                0, :total_docs,
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                CAST(:narrative AS jsonb)
            )
        """), {
            'id': summary_id,
            'period_type': 'MONTHLY',
            'period_start': month_start,
            'period_end': month_end,
            'event_name': canonical_name,
            'country': country,
            'first_observed': first_observed,
            'last_observed': last_observed,
            'narrative': narrative,
            'total_docs': len(valid_doc_ids)
        })

        stats['summaries_created'] += 1

        # Create EventSourceLink records
        for doc_id in valid_doc_ids:
            link = EventSourceLink(
                event_summary_id=summary_id,
                doc_id=doc_id
            )
            session.add(link)
            stats['source_links_created'] += 1

        if verbose:
            print(f"  Created monthly summary for {canonical_name} ({month_start_str} to {month_end_str}) "
                  f"({len(valid_doc_ids)} docs, {stats['source_links_created']} links)")

        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing monthly summary {canonical_event_id} for {month_str}: {e}")
        stats['errors'] += 1
        raise


def process_summary_materiality_result(
    session,
    summary_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process materiality scoring result for an event summary.

    Updates event_summaries.material_score and material_justification.

    Args:
        session: Database session
        summary_id: Event summary UUID
        llm_response: Parsed LLM response with 'material_score' and 'justification'
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'summaries_scored': 0,
        'errors': 0
    }

    try:
        # Validate score from LLM response
        score = llm_response.get('material_score') or llm_response.get('materiality_score')
        justification = llm_response.get('justification', '')

        if score is None:
            if verbose:
                print(f"  Warning: Summary {summary_id}: No material_score in response")
            stats['errors'] += 1
            return stats

        try:
            score = float(score)
            if not (1.0 <= score <= 10.0):
                if verbose:
                    print(f"  Warning: Summary {summary_id}: Score {score} out of range [1.0, 10.0]")
                stats['errors'] += 1
                return stats
        except (ValueError, TypeError):
            if verbose:
                print(f"  Warning: Summary {summary_id}: Invalid score format: {score}")
            stats['errors'] += 1
            return stats

        # Check if summary exists and isn't already scored
        existing = session.execute(text("""
            SELECT material_score FROM event_summaries
            WHERE id = :summary_id AND is_deleted = false
        """), {'summary_id': summary_id}).fetchone()

        if not existing:
            if verbose:
                print(f"  Warning: Summary {summary_id} not found, skipping")
            stats['errors'] += 1
            return stats

        if existing[0] is not None:
            if verbose:
                print(f"  Summary {summary_id}: Already scored ({float(existing[0]):.1f}), skipping")
            return stats

        # Update summary with materiality score
        session.execute(text("""
            UPDATE event_summaries
            SET material_score = :material_score,
                material_justification = :justification,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :summary_id
        """), {
            'summary_id': summary_id,
            'material_score': score,
            'justification': justification
        })

        if verbose:
            print(f"  Summary {summary_id}: Scored {score:.1f}/10.0")

        stats['summaries_scored'] += 1
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error scoring summary {summary_id}: {e}")
        stats['errors'] += 1
        raise


def process_entity_description_result(
    session,
    entity_id: str,
    llm_response: Dict[str, Any],
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process entity description generation result.

    Updates canonical_entities.entity_description and key_activities.

    Args:
        session: Database session
        entity_id: Canonical entity UUID
        llm_response: Parsed LLM response with 'entity_description' and 'key_activities'
        verbose: Print progress

    Returns:
        Statistics dict
    """
    stats = {
        'entities_described': 0,
        'errors': 0
    }

    try:
        description = llm_response.get('entity_description', '')
        key_activities = llm_response.get('key_activities', {})

        if not description:
            if verbose:
                print(f"  Warning: Entity {entity_id}: Empty entity_description in response")
            stats['errors'] += 1
            return stats

        # Check entity exists and isn't already described
        existing = session.execute(text("""
            SELECT entity_description FROM canonical_entities
            WHERE id = CAST(:entity_id AS uuid)
              AND master_entity_id IS NULL
        """), {'entity_id': entity_id}).fetchone()

        if not existing:
            if verbose:
                print(f"  Warning: Entity {entity_id} not found or is a child entity, skipping")
            stats['errors'] += 1
            return stats

        # Update entity with description and key_activities (overwrites existing if --force was used at prepare time)
        session.execute(text("""
            UPDATE canonical_entities
            SET entity_description = :description,
                key_activities = :key_activities,
                updated_at = NOW()
            WHERE id = CAST(:entity_id AS uuid)
        """), {
            'entity_id': entity_id,
            'description': description,
            'key_activities': json.dumps(key_activities) if key_activities else None
        })

        if verbose:
            print(f"  Entity {entity_id}: description={len(description)} chars")

        stats['entities_described'] += 1
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing entity {entity_id}: {e}")
        stats['errors'] += 1
        raise


def process_bilateral_summary_result(
    session,
    record_id: str,
    llm_response: Dict[str, Any],
    suffix: str,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Process bilateral relationship summary result.

    Re-gathers fresh statistics and combines with LLM-generated summary
    to create/update BilateralRelationshipSummary records.

    Args:
        session: Database session
        record_id: Deterministic UUID (from country pair)
        llm_response: Parsed LLM response with relationship analysis
        suffix: Country pair encoded as "InitCountry--RecipCountry"
        verbose: Print progress

    Returns:
        Statistics dict
    """
    from datetime import datetime as _dt
    from services.pipeline.summaries.generate_bilateral_summaries import gather_bilateral_data

    stats = {
        'bilateral_summaries_generated': 0,
        'errors': 0
    }

    try:
        # Parse country pair from suffix
        if '--' not in suffix:
            if verbose:
                print(f"  Warning: Invalid suffix format '{suffix}', expected 'Init--Recip'")
            stats['errors'] += 1
            return stats

        parts = suffix.split('--', 1)
        initiating_country = parts[0]
        recipient_country = parts[1]

        # Validate LLM response has required fields
        overview = llm_response.get('overview', '')
        if not overview:
            if verbose:
                print(f"  Warning: {initiating_country} -> {recipient_country}: Empty overview in response")
            stats['errors'] += 1
            return stats

        # Extract material assessment
        material_assessment = llm_response.get('material_assessment', {})
        material_score = material_assessment.get('score')
        material_justification = material_assessment.get('justification')

        # Re-gather fresh statistics
        data = gather_bilateral_data(session, initiating_country, recipient_country)

        if data['total_documents'] == 0:
            if verbose:
                print(f"  Warning: {initiating_country} -> {recipient_country}: No documents found")
            stats['errors'] += 1
            return stats

        # Look up existing summary
        existing = session.execute(text("""
            SELECT id, version FROM bilateral_relationship_summaries
            WHERE initiating_country = :init_country
              AND recipient_country = :recip_country
              AND is_deleted = false
        """), {
            'init_country': initiating_country,
            'recip_country': recipient_country
        }).fetchone()

        if existing:
            # Update existing record
            new_version = (existing[1] or 1) + 1
            session.execute(text("""
                UPDATE bilateral_relationship_summaries
                SET last_interaction_date = :last_date,
                    analysis_generated_at = NOW(),
                    total_documents = :total_docs,
                    total_daily_events = :daily_events,
                    total_weekly_events = :weekly_events,
                    total_monthly_events = :monthly_events,
                    count_by_category = :count_by_category,
                    count_by_subcategory = :count_by_subcategory,
                    count_by_source = :count_by_source,
                    activity_by_month = :activity_by_month,
                    relationship_summary = :relationship_summary,
                    material_score = :material_score,
                    material_justification = :material_justification,
                    material_score_histogram = :material_histogram,
                    material_score_avg = :material_avg,
                    material_score_median = :material_median,
                    updated_at = NOW(),
                    version = :version
                WHERE id = :summary_id
            """), {
                'summary_id': existing[0],
                'last_date': data['last_date'],
                'total_docs': data['total_documents'],
                'daily_events': data['daily_events'],
                'weekly_events': data['weekly_events'],
                'monthly_events': data['monthly_events'],
                'count_by_category': json.dumps(data['category_counts']),
                'count_by_subcategory': json.dumps(data['subcategory_counts']),
                'count_by_source': json.dumps(data['source_counts']),
                'activity_by_month': json.dumps(data['monthly_activity']),
                'relationship_summary': json.dumps(llm_response),
                'material_score': material_score,
                'material_justification': material_justification,
                'material_histogram': json.dumps(data.get('material_histogram', {})),
                'material_avg': data.get('material_avg'),
                'material_median': data.get('material_median'),
                'version': new_version
            })

            if verbose:
                print(f"  {initiating_country} -> {recipient_country}: Updated (v{new_version})")

        else:
            # Create new record
            import uuid as _uuid
            session.execute(text("""
                INSERT INTO bilateral_relationship_summaries (
                    id, initiating_country, recipient_country,
                    first_interaction_date, last_interaction_date,
                    analysis_generated_at,
                    total_documents, total_daily_events, total_weekly_events, total_monthly_events,
                    count_by_category, count_by_subcategory, count_by_source,
                    activity_by_month, relationship_summary,
                    material_score, material_justification,
                    material_score_histogram, material_score_avg, material_score_median,
                    created_at, created_by, version, is_deleted
                ) VALUES (
                    :id, :init_country, :recip_country,
                    :first_date, :last_date,
                    NOW(),
                    :total_docs, :daily_events, :weekly_events, :monthly_events,
                    :count_by_category, :count_by_subcategory, :count_by_source,
                    :activity_by_month, :relationship_summary,
                    :material_score, :material_justification,
                    :material_histogram, :material_avg, :material_median,
                    NOW(), :created_by, 1, false
                )
            """), {
                'id': str(_uuid.uuid4()),
                'init_country': initiating_country,
                'recip_country': recipient_country,
                'first_date': data['first_date'],
                'last_date': data['last_date'],
                'total_docs': data['total_documents'],
                'daily_events': data['daily_events'],
                'weekly_events': data['weekly_events'],
                'monthly_events': data['monthly_events'],
                'count_by_category': json.dumps(data['category_counts']),
                'count_by_subcategory': json.dumps(data['subcategory_counts']),
                'count_by_source': json.dumps(data['source_counts']),
                'activity_by_month': json.dumps(data['monthly_activity']),
                'relationship_summary': json.dumps(llm_response),
                'material_score': material_score,
                'material_justification': material_justification,
                'material_histogram': json.dumps(data.get('material_histogram', {})),
                'material_avg': data.get('material_avg'),
                'material_median': data.get('material_median'),
                'created_by': 'batch_pipeline'
            })

            if verbose:
                print(f"  {initiating_country} -> {recipient_country}: Created new ({data['total_documents']:,} docs)")

        stats['bilateral_summaries_generated'] += 1
        return stats

    except Exception as e:
        if verbose:
            print(f"  Error processing bilateral summary {suffix}: {e}")
        stats['errors'] += 1
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Stage 4: Process batch results and update database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--batch-job-id', required=True, type=str,
                       help='Batch job UUID from Stage 1 (batch_prepare.py)')
    parser.add_argument('--checkpoint-frequency', type=int, default=DEFAULT_CHECKPOINT_FREQUENCY,
                       help=f'Commit every N processed results (default: {DEFAULT_CHECKPOINT_FREQUENCY})')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without updating database')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Verbose output')

    args = parser.parse_args()

    print("=" * 80)
    print("BATCH PROCESS RESULTS - Stage 4: Update Database")
    print("=" * 80)
    print(f"Batch Job ID: {args.batch_job_id}")
    print(f"Checkpoint frequency: {args.checkpoint_frequency}")
    if args.dry_run:
        print("[DRY RUN MODE] No database updates will be made")
    print("=" * 80)
    print()

    with get_session() as session:
        with BatchJobTracker(session) as tracker:
            # Load batch job
            print("Loading batch job from database...")
            batch_job = tracker.get_batch_job(args.batch_job_id)

            if not batch_job:
                print(f"Error: Batch job not found: {args.batch_job_id}")
                return

            if not batch_job.output_file_path:
                print("Error: No output file path in batch job. Was Stage 3 (monitor) completed?")
                return

            print("✓ Loaded batch job")
            print(f"  Job type: {batch_job.job_type}")
            print(f"  Status: {batch_job.status}")
            print(f"  Output file: {batch_job.output_file_path}")
            print()

            # Verify output file exists
            if not Path(batch_job.output_file_path).exists():
                print(f"Error: Output file not found: {batch_job.output_file_path}")
                return

            # Update status
            if not args.dry_run:
                tracker.update_status(batch_job.id, BatchJobStatus.PROCESSING_RESULTS)

            # Initialize deconfliction processor for cluster jobs
            deconfliction_processor = None
            if batch_job.job_type == JOB_TYPE_CLUSTER_DECONFLICT:
                deconfliction_processor = LLMClusterDeconfliction(
                    dry_run=args.dry_run,
                    verbose=False  # We'll handle verbosity here
                )

            # Process results
            print(f"Processing results from: {batch_job.output_file_path}")
            print()

            overall_stats = {
                'total_processed': 0,
                'total_errors': 0,
                'canonical_events_created': 0,
                'canonical_events_updated': 0,
                'daily_mentions_created': 0,
                'validated': 0,
                'renamed': 0,
                'split': 0,
                'entities_extracted': 0,
                'events_scored': 0,
                'summaries_created': 0,
                'source_links_created': 0
            }

            processed_count = 0

            for result in read_jsonl(batch_job.output_file_path):
                processed_count += 1

                # Parse custom_id
                custom_id = result.get('custom_id')
                if not custom_id:
                    print("  Warning: Result missing custom_id, skipping")
                    overall_stats['total_errors'] += 1
                    continue

                try:
                    custom_id_parts = parse_custom_id(custom_id)
                    record_id = str(custom_id_parts['record_id'])
                    job_type = custom_id_parts['job_type']

                    # Extract LLM response
                    response_body = result.get('response', {}).get('body', {})
                    choices = response_body.get('choices', [])

                    if not choices:
                        print(f"  Warning: No choices in response for {custom_id}, skipping")
                        overall_stats['total_errors'] += 1
                        continue

                    content = choices[0].get('message', {}).get('content', '')

                    # Parse JSON response
                    try:
                        llm_response = json.loads(content)
                    except json.JSONDecodeError:
                        # Try to extract JSON from markdown
                        import re
                        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                        if json_match:
                            llm_response = json.loads(json_match.group(0))
                        else:
                            print(f"  Warning: Could not parse JSON response for {custom_id}")
                            overall_stats['total_errors'] += 1
                            continue

                    # Normalize field names (batch prompt uses "reasoning" but code expects "explanation")
                    if job_type == JOB_TYPE_CLUSTER_DECONFLICT:
                        if 'reasoning' in llm_response and 'explanation' not in llm_response:
                            llm_response['explanation'] = llm_response['reasoning']

                    # Route to appropriate handler using savepoint for isolation
                    if args.dry_run:
                        print(f"  [DRY RUN] Would process {job_type} record {record_id}")
                        overall_stats['total_processed'] += 1
                    else:
                        savepoint = session.begin_nested()
                        try:
                            if job_type == JOB_TYPE_CLUSTER_DECONFLICT:
                                stats = process_cluster_result(
                                    session, record_id, llm_response,
                                    deconfliction_processor, verbose=args.verbose
                                )
                            elif job_type == JOB_TYPE_CANONICAL_DECONFLICT:
                                stats = process_canonical_result(
                                    session, record_id, llm_response, verbose=args.verbose
                                )
                            elif job_type == JOB_TYPE_ENTITY_EXTRACT:
                                stats = process_entity_extract_result(
                                    session, record_id, llm_response, verbose=args.verbose
                                )
                            elif job_type == JOB_TYPE_SCORE_MATERIALITY:
                                stats = process_materiality_score_result(
                                    session, record_id, llm_response, verbose=args.verbose
                                )
                            elif job_type == JOB_TYPE_DAILY_ENTITY_EXTRACT:
                                stats = process_daily_entity_extract_result(
                                    session, record_id, llm_response, verbose=args.verbose
                                )
                            elif job_type == JOB_TYPE_ENTITY_DECONFLICT:
                                stats = process_entity_deconflict_result(
                                    session, record_id, llm_response, verbose=args.verbose
                                )
                            elif job_type == JOB_TYPE_CANONICAL_ENTITY_DECONFLICT:
                                stats = process_canonical_entity_deconflict_result(
                                    session, record_id, llm_response, verbose=args.verbose
                                )
                            elif job_type == JOB_TYPE_GENERATE_DAILY_SUMMARY:
                                date_suffix = custom_id_parts.get('suffix')
                                if not date_suffix:
                                    print(f"  Warning: No date suffix in custom_id {custom_id}")
                                    overall_stats['total_errors'] += 1
                                    savepoint.rollback()
                                    continue
                                stats = process_daily_summary_result(
                                    session, record_id, llm_response,
                                    date_str=date_suffix, verbose=args.verbose
                                )
                            else:
                                savepoint.rollback()
                                print(f"  Warning: Unknown job type '{job_type}' for {custom_id}")
                                overall_stats['total_errors'] += 1
                                continue

                            savepoint.commit()
                            overall_stats['total_processed'] += 1
                            overall_stats['total_errors'] += stats.get('errors', 0)

                            # Merge type-specific stats
                            for key in stats:
                                if key != 'errors' and key in overall_stats:
                                    overall_stats[key] += stats[key]

                        except Exception as e:
                            savepoint.rollback()
                            print(f"  Error processing {job_type} {record_id}: {e}")
                            overall_stats['total_errors'] += 1

                    # Checkpoint commit
                    if not args.dry_run and processed_count % args.checkpoint_frequency == 0:
                        session.commit()
                        print(f"\n[CHECKPOINT] Committed after {processed_count} results")
                        print(f"  Progress: {overall_stats['total_processed']} processed, {overall_stats['total_errors']} errors\n")

                except Exception as e:
                    print(f"  Error processing result {custom_id}: {e}")
                    overall_stats['total_errors'] += 1
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    continue

            # Final commit
            if not args.dry_run:
                session.commit()
                print("\n[COMMITTED] Final batch")

                # Update batch job status
                tracker.update_status(batch_job.id, BatchJobStatus.COMPLETED)
                print("✓ Updated batch_job status to 'completed'")

            print()
            print("=" * 80)
            print("PROCESSING COMPLETE")
            print("=" * 80)
            print(f"Total processed: {overall_stats['total_processed']}")
            print(f"Total errors: {overall_stats['total_errors']}")

            if batch_job.job_type == JOB_TYPE_CLUSTER_DECONFLICT:
                print(f"Canonical events created: {overall_stats['canonical_events_created']}")
                print(f"Canonical events updated: {overall_stats['canonical_events_updated']}")
                print(f"Daily mentions created: {overall_stats['daily_mentions_created']}")
            elif batch_job.job_type == JOB_TYPE_CANONICAL_DECONFLICT:
                print(f"Events validated: {overall_stats['validated']}")
                print(f"Events renamed: {overall_stats['renamed']}")
                print(f"Event groups split: {overall_stats['split']}")
            elif batch_job.job_type == JOB_TYPE_ENTITY_EXTRACT:
                print(f"Entities extracted: {overall_stats['entities_extracted']}")
            elif batch_job.job_type == JOB_TYPE_SCORE_MATERIALITY:
                print(f"Events scored: {overall_stats['events_scored']}")
            elif batch_job.job_type == JOB_TYPE_DAILY_ENTITY_EXTRACT:
                print(f"Entities extracted: {overall_stats.get('entities_extracted', 0)}")
            elif batch_job.job_type == JOB_TYPE_GENERATE_DAILY_SUMMARY:
                print(f"Summaries created: {overall_stats.get('summaries_created', 0)}")
                print(f"Source links created: {overall_stats.get('source_links_created', 0)}")

            print("=" * 80)

            if not args.dry_run:
                print()
                print("Next step: Cleanup (optional)")
                print(f"  python batch_cleanup.py --batch-job-id {batch_job.id}")
            print()


if __name__ == "__main__":
    main()
