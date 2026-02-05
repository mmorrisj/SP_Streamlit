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
    EventCluster, CanonicalEvent, DailyEventMention, Document, RawEntity,
    EntityTypeEnum, EntityCluster, CanonicalEntity, DailyEntityMention, EntityRoleEnum
)
from services.pipeline.batch.batch_config import (
    JOB_TYPE_CLUSTER_DECONFLICT,
    JOB_TYPE_CANONICAL_DECONFLICT,
    JOB_TYPE_ENTITY_EXTRACT,
    JOB_TYPE_SCORE_MATERIALITY,
    JOB_TYPE_DAILY_ENTITY_EXTRACT,
    JOB_TYPE_ENTITY_DECONFLICT,
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
                print(f"Error: No output file path in batch job. Was Stage 3 (monitor) completed?")
                return

            print(f"✓ Loaded batch job")
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
                'events_scored': 0
            }

            processed_count = 0

            for result in read_jsonl(batch_job.output_file_path):
                processed_count += 1

                # Parse custom_id
                custom_id = result.get('custom_id')
                if not custom_id:
                    print(f"  Warning: Result missing custom_id, skipping")
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
                print(f"\n[COMMITTED] Final batch")

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

            print("=" * 80)

            if not args.dry_run:
                print()
                print("Next step: Cleanup (optional)")
                print(f"  python batch_cleanup.py --batch-job-id {batch_job.id}")
            print()


if __name__ == "__main__":
    main()
