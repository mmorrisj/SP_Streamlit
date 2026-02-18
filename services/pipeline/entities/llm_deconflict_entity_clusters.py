"""
LLM Deconfliction for Entity Clusters (Stage 1C)

This script processes entity clusters from the entity_clusters table and uses an LLM
to validate and refine cluster groupings. The LLM reviews each cluster to determine
if entity names truly represent the same real-world entity or should be split.

Processing Strategy:
1. Load clusters by (country, date, entity_type, batch_number) where llm_deconflicted = False
2. For each cluster, check if LLM review is needed (clusters with multiple unique entity names)
3. Use LLM to verify if entities in cluster represent the same real-world entity
4. Create CanonicalEntity records for each unique entity
5. Create DailyEntityMention records linking entities to source documents
6. Mark clusters as llm_deconflicted = True

Usage:
    # Process specific country and date
    python llm_deconflict_entity_clusters.py --country China --start-date 2025-06-01 --end-date 2025-06-30

    # Process specific entity type only
    python llm_deconflict_entity_clusters.py --country China --start-date 2025-06-01 --end-date 2025-06-30 --entity-type person

    # Process all unprocessed clusters for a country
    python llm_deconflict_entity_clusters.py --country China

    # Custom checkpoint frequency for more frequent commits
    python llm_deconflict_entity_clusters.py --country China --checkpoint-frequency 5

    # Dry run (no database writes)
    python llm_deconflict_entity_clusters.py --country China --start-date 2025-06-01 --end-date 2025-06-30 --dry-run

Checkpoint/Resume:
    The script automatically resumes from where it left off by only processing clusters where
    llm_deconflicted=False. Progress is committed every --checkpoint-frequency clusters (default: 10)
    within each batch. If interrupted, simply re-run the same command to continue.
"""

import os
import sys
import argparse
import json
import yaml
import re
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from collections import defaultdict
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from shared.database.database import get_session
from shared.models.models import (
    EntityCluster, CanonicalEntity, DailyEntityMention, EntityTypeEnum, EntityRoleEnum
)
from shared.utils.utils import gai
from sentence_transformers import SentenceTransformer


class LLMEntityDeconfliction:
    """
    Handles LLM-based deconfliction of entity clusters.
    """

    def __init__(self, dry_run: bool = False, verbose: bool = True):
        self.dry_run = dry_run
        self.verbose = verbose
        # Initialize embedding model for canonical entities
        self.embedding_model = None

    def get_embedding_model(self):
        """Lazy load embedding model."""
        if self.embedding_model is None:
            if self.verbose:
                print("  Loading sentence transformer model...")
            from shared.utils.model_cache import load_embedding_model
            self.embedding_model = load_embedding_model()
        return self.embedding_model

    def load_config(self, config_path: str = 'shared/config/config.yaml') -> dict:
        """Load configuration from config.yaml"""
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return {
                    'influencers': config.get('influencers', ['China', 'Russia', 'Iran', 'Turkey', 'United States'])
                }
        except Exception as e:
            print(f"Warning: Could not load config.yaml: {e}")
            return {'influencers': ['China', 'Russia', 'Iran', 'Turkey', 'United States']}

    def get_unprocessed_batches(
        self,
        session,
        country: Optional[str] = None,
        entity_type: Optional[EntityTypeEnum] = None,
        target_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all unprocessed batches (country, date, entity_type, batch_number combinations).

        Args:
            session: Database session
            country: Filter by specific country (optional)
            entity_type: Filter by specific entity type (optional)
            target_date: Filter by specific date (optional)

        Returns:
            List of dicts with keys: initiating_country, cluster_date, entity_type, batch_number
        """
        from sqlalchemy import and_

        # Use ORM query to properly handle enum types
        query = (
            session.query(
                EntityCluster.initiating_country,
                EntityCluster.cluster_date,
                EntityCluster.entity_type,
                EntityCluster.batch_number
            )
            .filter(EntityCluster.llm_deconflicted == False)
            .distinct()
        )

        # Add filters
        filters = []
        if country:
            filters.append(EntityCluster.initiating_country == country)
        if entity_type:
            filters.append(EntityCluster.entity_type == entity_type)
        if target_date:
            filters.append(EntityCluster.cluster_date == target_date)

        if filters:
            query = query.filter(and_(*filters))

        query = query.order_by(
            EntityCluster.initiating_country,
            EntityCluster.cluster_date,
            EntityCluster.entity_type,
            EntityCluster.batch_number
        )

        batches = []
        for row in query.all():
            batches.append({
                'initiating_country': row.initiating_country,
                'cluster_date': row.cluster_date,
                'entity_type': row.entity_type,  # Already an enum
                'batch_number': row.batch_number
            })

        return batches

    def load_batch_clusters(
        self,
        session,
        country: str,
        target_date: date,
        entity_type: EntityTypeEnum,
        batch_number: int
    ) -> List[EntityCluster]:
        """
        Load all clusters for a specific batch.

        Args:
            session: Database session
            country: Initiating country
            target_date: Cluster date
            entity_type: Entity type
            batch_number: Batch number

        Returns:
            List of EntityCluster objects
        """
        clusters = session.query(EntityCluster).filter(
            EntityCluster.initiating_country == country,
            EntityCluster.cluster_date == target_date,
            EntityCluster.entity_type == entity_type,
            EntityCluster.batch_number == batch_number,
            EntityCluster.llm_deconflicted == False
        ).all()

        return clusters

    def needs_llm_review(self, cluster: EntityCluster) -> bool:
        """
        Determine if a cluster needs LLM review.

        Criteria:
        - Skip if cluster is noise (cluster_id == -1)
        - Skip if all entity names are identical (no ambiguity)
        - Review ALL clusters with 2+ unique entity names

        Args:
            cluster: EntityCluster object

        Returns:
            True if LLM review is needed, False otherwise
        """
        # Skip noise clusters
        if cluster.is_noise:
            return False

        # Get unique entity names
        unique_names = list(set(cluster.entity_names))

        # Skip if all same name (definitely one entity)
        if len(unique_names) == 1:
            return False

        # Review ALL clusters with multiple unique names
        return True

    def llm_review_cluster(self, cluster: EntityCluster) -> Dict[str, Any]:
        """
        Use LLM to review and potentially split a cluster.

        Args:
            cluster: EntityCluster object with multiple entity names

        Returns:
            Dict with keys:
                - same_entity: bool (True if all names refer to same entity)
                - explanation: str (LLM's reasoning)
                - canonical_name: str (best canonical name for the entity)
                - primary_role: str (primary role from EntityRoleEnum)
                - country_affiliation: str (primary country affiliation)
                - groups: List[List[int]] (if split, indices of entity names grouped together)
        """
        unique_names = list(set(cluster.entity_names))

        # Build prompt with numbered list of unique entity names
        names_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(unique_names)])

        # Get entity type for context
        entity_type_label = cluster.entity_type.value.upper()

        sys_prompt = f"""You are an expert at entity resolution and disambiguation for {entity_type_label} entities.

**CRITICAL UNDERSTANDING:**
Your task is to determine if the following entity names refer to the SAME real-world entity, or if they are DIFFERENT entities that were incorrectly clustered together.

**Context:**
- Entity type: {entity_type_label}
- These entities were mentioned on the same date
- They are all associated with the same country
- The clustering algorithm grouped them based on semantic similarity
- Names may vary due to: titles, abbreviations, alternative spellings, or contexts

**Guidelines for {entity_type_label.upper()}S:**

{"**PERSONS:**" if cluster.entity_type == EntityTypeEnum.PERSON else ""}
{"- Same person: 'Wang Yi', 'Chinese FM Wang Yi', 'Foreign Minister Wang Yi', 'FM Wang'" if cluster.entity_type == EntityTypeEnum.PERSON else ""}
{"- Same person: 'Xi Jinping', 'President Xi', 'Chinese President Xi Jinping'" if cluster.entity_type == EntityTypeEnum.PERSON else ""}
{"- Different persons: 'Wang Yi' vs 'Wang Li' (different people with same surname)" if cluster.entity_type == EntityTypeEnum.PERSON else ""}
{"- Different persons: 'President Xi' vs 'Premier Li' (different officials)" if cluster.entity_type == EntityTypeEnum.PERSON else ""}

{"**ORGANIZATIONS:**" if cluster.entity_type == EntityTypeEnum.ORGANIZATION else ""}
{"- Same org: 'Ministry of Foreign Affairs', 'MFA', 'Chinese Foreign Ministry'" if cluster.entity_type == EntityTypeEnum.ORGANIZATION else ""}
{"- Same org: 'Shanghai Cooperation Organization', 'SCO'" if cluster.entity_type == EntityTypeEnum.ORGANIZATION else ""}
{"- Different orgs: 'Ministry of Foreign Affairs' vs 'Ministry of Defense' (different ministries)" if cluster.entity_type == EntityTypeEnum.ORGANIZATION else ""}

{"**COMPANIES:**" if cluster.entity_type == EntityTypeEnum.COMPANY else ""}
{"- Same company: 'CNOOC', 'China National Offshore Oil Corporation'" if cluster.entity_type == EntityTypeEnum.COMPANY else ""}
{"- Same company: 'Huawei', 'Huawei Technologies Co.'" if cluster.entity_type == EntityTypeEnum.COMPANY else ""}
{"- Different companies: 'CNOOC' vs 'Sinopec' (different oil companies)" if cluster.entity_type == EntityTypeEnum.COMPANY else ""}

{"**LOCATIONS:**" if cluster.entity_type == EntityTypeEnum.LOCATION else ""}
{"- Same location: 'Beijing', 'China's capital', 'Beijing, China'" if cluster.entity_type == EntityTypeEnum.LOCATION else ""}
{"- Same location: 'Middle East', 'Middle Eastern region'" if cluster.entity_type == EntityTypeEnum.LOCATION else ""}
{"- Different locations: 'Beijing' vs 'Shanghai' (different cities)" if cluster.entity_type == EntityTypeEnum.LOCATION else ""}

**Your Goal:**
- Group names that refer to the SAME real-world entity
- Keep DISTINCT entities in separate groups
- Choose the best canonical name (most complete, professional, commonly used)
- Identify the primary role/function of the entity
- Identify the primary country affiliation"""

        user_prompt = f"""Entity names from cluster (type={entity_type_label}, size={cluster.cluster_size}):
{names_list}

**ANALYZE USING CHAIN-OF-THOUGHT:**

**STEP 1 - IDENTIFY CORE ENTITY:**
For each name, extract:
- Who/what is this? (full name, title, abbreviation)
- What roles/titles are mentioned?
- What country affiliations are mentioned?

**STEP 2 - CHECK IF SAME ENTITY:**
Do these names refer to the SAME real-world {entity_type_label}?
- Look for: name variations, abbreviations, title differences
- Check for: same person/org with different titles/contexts
- Distinguish: truly different entities with similar names

**STEP 3 - PROVIDE DECISION:**
Return a JSON object with:
{{
  "same_entity": true/false,
  "explanation": "Brief reasoning for your decision",
  "canonical_name": "Best canonical name for this entity" (if same_entity=true),
  "primary_role": "One of: government_official, diplomat, business_leader, cultural_figure, military_official, academic, media_figure, civil_society, implementing_organization, funding_organization, recipient_institution, infrastructure_project, venue, other",
  "country_affiliation": "Primary country affiliation",
  "groups": [[list of indices that belong to same entity], [another group if split]]
}}

**IMPORTANT:**
- If same_entity=true: all names go in one group, provide canonical_name
- If same_entity=false: split into multiple groups
- Groups use 1-based indices (1, 2, 3, etc.)

Return ONLY the JSON object, no additional text."""

        try:
            # Call LLM
            response = gai(user_prompt, system_prompt=sys_prompt)

            # Parse JSON response
            try:
                response = json.loads(response)
            except json.JSONDecodeError:
                # Try to extract JSON from response
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
                if json_match:
                    response = json.loads(json_match.group(0))
                else:
                    response = json.loads(response)

            # Validate response structure
            if 'same_entity' not in response or 'groups' not in response:
                raise ValueError(f"Invalid LLM response structure: {response}")

            result = {
                'same_entity': response.get('same_entity', True),
                'explanation': response.get('explanation', ''),
                'canonical_name': response.get('canonical_name', unique_names[0]),
                'primary_role': response.get('primary_role', 'other'),
                'country_affiliation': response.get('country_affiliation', None),
                'groups': response.get('groups', [[i+1 for i in range(len(unique_names))]])
            }

            return result

        except Exception as e:
            if self.verbose:
                print(f"    Warning: LLM review failed: {e}. Keeping cluster intact.")

            # Return safe default (keep cluster as-is)
            return {
                'same_entity': True,
                'explanation': f'LLM review failed: {str(e)}',
                'canonical_name': unique_names[0],
                'primary_role': 'other',
                'country_affiliation': None,
                'groups': [[i+1 for i in range(len(unique_names))]]
            }

    def save_deconfliction_result(
        self,
        session,
        cluster: EntityCluster,
        llm_result: Dict[str, Any]
    ):
        """
        Save LLM deconfliction result to database.

        Updates the cluster record with:
        - refined_clusters: JSONB containing LLM analysis
        - llm_deconflicted: True

        Args:
            session: Database session
            cluster: EntityCluster object
            llm_result: Dict returned from llm_review_cluster()
        """
        # Build refined_clusters JSONB
        unique_names = list(set(cluster.entity_names))

        refined_data = {
            'same_entity': llm_result['same_entity'],
            'explanation': llm_result['explanation'],
            'canonical_name': llm_result['canonical_name'],
            'primary_role': llm_result['primary_role'],
            'country_affiliation': llm_result['country_affiliation'],
            'original_cluster_size': cluster.cluster_size,
            'unique_entity_names': len(unique_names),
            'groups': llm_result['groups'],
            'reviewed_at': datetime.utcnow().isoformat(),
            'unique_names_list': unique_names
        }

        # Update cluster
        cluster.refined_clusters = refined_data
        cluster.llm_deconflicted = True

        if self.verbose:
            if llm_result['same_entity']:
                print(f"    [OK] Cluster {cluster.cluster_id}: Confirmed as single entity")
            else:
                print(f"    [OK] Cluster {cluster.cluster_id}: Split into {len(llm_result['groups'])} entities")
                print(f"      Groups: {llm_result['groups']}")

    def create_canonical_entities_from_cluster(
        self,
        session,
        cluster: EntityCluster,
        llm_result: Optional[Dict[str, Any]] = None
    ) -> List[CanonicalEntity]:
        """
        Create CanonicalEntity and DailyEntityMention records from a deconflicted cluster.

        CRITICAL: This function ensures that canonical_entities and daily_entity_mentions
        are created together atomically. If daily_entity_mention creation fails, the
        entire operation is rolled back to prevent orphaned canonical_entities.

        Args:
            session: Database session
            cluster: EntityCluster with llm_deconflicted = True
            llm_result: Optional LLM result (if not provided, loads from cluster.refined_clusters)

        Returns:
            List of created CanonicalEntity objects

        Raises:
            Exception: If daily_entity_mention creation fails, rolls back the transaction
        """
        # Load LLM result from cluster if not provided
        if llm_result is None:
            if cluster.refined_clusters is None:
                raise ValueError(f"Cluster {cluster.cluster_id} has no refined_clusters data")
            llm_result = cluster.refined_clusters

        # Get unique entity names
        unique_names = list(set(cluster.entity_names))
        groups = llm_result.get('groups', [[i+1 for i in range(len(unique_names))]])

        # Create mapping of entity name to doc_ids
        name_to_docs = defaultdict(list)
        for entity_name, doc_id in zip(cluster.entity_names, cluster.doc_ids):
            name_to_docs[entity_name].append(doc_id)

        canonical_entities = []

        # Process each group (each group represents one real-world entity)
        for group_idx, group_indices in enumerate(groups):
            # Get entity names in this group
            group_names = [unique_names[idx - 1] for idx in group_indices if 1 <= idx <= len(unique_names)]

            if not group_names:
                continue

            # Collect all doc_ids for this group
            group_doc_ids = []
            for name in group_names:
                group_doc_ids.extend(name_to_docs[name])

            # Remove duplicates while preserving order
            group_doc_ids = list(dict.fromkeys(group_doc_ids))

            # Validate doc_ids before proceeding
            if not group_doc_ids:
                print(f"      WARNING: No doc_ids for group {group_idx+1} in cluster {cluster.cluster_id}, skipping")
                continue

            # Query recipient countries and categories from these documents
            recipients_query = session.execute(text("""
                SELECT rc.recipient_country, COUNT(*) as count
                FROM recipient_countries rc
                WHERE rc.doc_id = ANY(:doc_ids)
                GROUP BY rc.recipient_country
            """), {"doc_ids": group_doc_ids}).fetchall()
            primary_recipients = {row[0]: row[1] for row in recipients_query}

            # Get categories with counts
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

            # Choose canonical name (from LLM result or most frequent)
            if llm_result.get('same_entity') and llm_result.get('canonical_name'):
                canonical_name = llm_result['canonical_name']
            else:
                canonical_name = max(group_names, key=group_names.count)

            # Map primary_role to EntityRoleEnum
            role_str = llm_result.get('primary_role', 'other')
            try:
                primary_role = EntityRoleEnum(role_str)
            except ValueError:
                primary_role = EntityRoleEnum.OTHER

            # Generate embedding for canonical name
            model = self.get_embedding_model()
            embedding = model.encode(canonical_name).tolist()

            # Check if canonical entity already exists
            existing_entity = session.query(CanonicalEntity).filter(
                CanonicalEntity.canonical_name == canonical_name,
                CanonicalEntity.entity_type == cluster.entity_type,
                CanonicalEntity.initiating_country == cluster.initiating_country
            ).first()

            # BEGIN ATOMIC OPERATION: canonical_entity + daily_entity_mention
            savepoint = session.begin_nested()

            try:
                if existing_entity:
                    # Update existing canonical entity
                    canonical_entity = existing_entity
                    canonical_entity.last_mention_date = max(canonical_entity.last_mention_date, cluster.cluster_date)
                    canonical_entity.total_documents += len(group_doc_ids)

                    # Add alternative names
                    for name in group_names:
                        if name != canonical_name and name not in canonical_entity.alternative_names:
                            canonical_entity.alternative_names = canonical_entity.alternative_names + [name]

                    # Merge country affiliations
                    for affiliation in country_affiliations:
                        if affiliation not in canonical_entity.country_affiliations:
                            canonical_entity.country_affiliations = canonical_entity.country_affiliations + [affiliation]

                    if self.verbose:
                        safe_name = canonical_name.encode('ascii', 'replace').decode('ascii')
                        print(f"      Updated existing canonical entity: {safe_name}")

                else:
                    # Create new canonical entity
                    canonical_entity = CanonicalEntity(
                        canonical_name=canonical_name,
                        entity_type=cluster.entity_type,
                        initiating_country=cluster.initiating_country,
                        primary_role=primary_role,
                        country_affiliations=country_affiliations,
                        alternative_names=[name for name in group_names if name != canonical_name],
                        first_mention_date=cluster.cluster_date,
                        last_mention_date=cluster.cluster_date,
                        total_mention_days=1,
                        total_documents=len(group_doc_ids),
                        primary_categories=primary_categories,
                        primary_recipients=primary_recipients,
                        embedding_vector=embedding,
                        associated_events=[]
                    )
                    session.add(canonical_entity)
                    session.flush()  # Get the ID immediately

                    if self.verbose:
                        safe_name = canonical_name.encode('ascii', 'replace').decode('ascii')
                        print(f"      Created canonical entity: {safe_name}")

                # CRITICAL: Create or update DailyEntityMention
                existing_mention = session.query(DailyEntityMention).filter(
                    DailyEntityMention.canonical_entity_id == canonical_entity.id,
                    DailyEntityMention.mention_date == cluster.cluster_date
                ).first()

                if existing_mention:
                    # Update existing mention
                    existing_mention.document_count = len(group_doc_ids)
                    existing_mention.doc_ids = group_doc_ids

                    if self.verbose:
                        print(f"        Updated daily mention: {len(group_doc_ids)} documents")

                else:
                    # Create new daily mention
                    daily_mention = DailyEntityMention(
                        canonical_entity_id=canonical_entity.id,
                        initiating_country=cluster.initiating_country,
                        mention_date=cluster.cluster_date,
                        document_count=len(group_doc_ids),
                        primary_role_this_day=role_str,
                        activities_this_day=None,  # Could be generated by LLM in future
                        doc_ids=group_doc_ids,
                        associated_event_ids=[]
                    )
                    session.add(daily_mention)
                    session.flush()  # Force immediate write to catch constraint violations

                    if self.verbose:
                        print(f"        Created daily mention: {len(group_doc_ids)} documents on {cluster.cluster_date}")

                # Commit the savepoint - both canonical_entity and daily_entity_mention succeeded
                savepoint.commit()
                canonical_entities.append(canonical_entity)

            except Exception as e:
                # CRITICAL ERROR: daily_entity_mention creation failed
                savepoint.rollback()

                safe_name = canonical_name.encode('ascii', 'replace').decode('ascii')[:60]
                print(f"\n      🔴 ERROR: Failed to create daily_entity_mention for '{safe_name}'")
                print(f"         Cluster: {cluster.cluster_id}, Date: {cluster.cluster_date}")
                print(f"         Error: {str(e)}")
                print("         Rolled back savepoint to prevent orphaned canonical_entity")

                # Re-raise to signal failure to caller
                raise Exception(
                    f"Failed to create daily_entity_mention for canonical_entity '{canonical_name}' "
                    f"(cluster {cluster.cluster_id}): {str(e)}"
                )

        return canonical_entities

    def process_batch(
        self,
        session,
        country: str,
        target_date: date,
        entity_type: EntityTypeEnum,
        batch_number: int,
        checkpoint_frequency: int = 10
    ) -> Dict[str, int]:
        """
        Process all clusters in a batch with LLM deconfliction.

        Args:
            session: Database session
            country: Initiating country
            target_date: Cluster date
            entity_type: Entity type
            batch_number: Batch number
            checkpoint_frequency: Commit every N clusters for checkpointing (default: 10)

        Returns:
            Dict with statistics
        """
        stats = {
            'total_clusters': 0,
            'skipped': 0,
            'reviewed': 0,
            'confirmed': 0,
            'split': 0,
            'canonical_entities_created': 0,
            'daily_mentions_created': 0
        }

        # Load all clusters in this batch
        clusters = self.load_batch_clusters(session, country, target_date, entity_type, batch_number)
        stats['total_clusters'] = len(clusters)

        if len(clusters) == 0:
            if self.verbose:
                print(f"  No unprocessed clusters found for batch {batch_number}")
            return stats

        if self.verbose:
            print(f"  Processing {len(clusters)} clusters in batch {batch_number}...")

        clusters_since_commit = 0

        for i, cluster in enumerate(clusters, 1):
            llm_result = None

            # Check if LLM review is needed
            if not self.needs_llm_review(cluster):
                # No LLM review needed - mark as processed with default result
                unique_names = list(set(cluster.entity_names))
                llm_result = {
                    'same_entity': True,
                    'explanation': 'All entity names identical - no LLM review needed',
                    'canonical_name': unique_names[0],
                    'primary_role': 'other',
                    'country_affiliation': None,
                    'groups': [[1]]
                }
                stats['skipped'] += 1

                if self.verbose:
                    print(f"  [{i}/{len(clusters)}] Cluster {cluster.cluster_id}: Skipped (all names identical)")

            else:
                # LLM review needed
                if self.verbose:
                    print(f"  [{i}/{len(clusters)}] Cluster {cluster.cluster_id}: Reviewing with LLM...")

                llm_result = self.llm_review_cluster(cluster)
                stats['reviewed'] += 1

                if llm_result['same_entity']:
                    stats['confirmed'] += 1
                else:
                    stats['split'] += 1

            # Save deconfliction result to cluster
            if not self.dry_run:
                self.save_deconfliction_result(session, cluster, llm_result)

                # Create canonical entities and daily mentions
                try:
                    canonical_entities = self.create_canonical_entities_from_cluster(
                        session, cluster, llm_result
                    )
                    stats['canonical_entities_created'] += len(canonical_entities)
                    stats['daily_mentions_created'] += len(canonical_entities)

                except Exception as e:
                    print(f"    ERROR: Failed to create canonical entities for cluster {cluster.cluster_id}: {e}")
                    # Continue to next cluster instead of failing entire batch
                    continue

            clusters_since_commit += 1

            # Checkpoint: commit every N clusters
            if not self.dry_run and clusters_since_commit >= checkpoint_frequency:
                session.commit()
                if self.verbose:
                    print(f"    ✓ Checkpoint: Committed {clusters_since_commit} clusters")
                clusters_since_commit = 0

        # Final commit for remaining clusters
        if not self.dry_run and clusters_since_commit > 0:
            session.commit()
            if self.verbose:
                print(f"    ✓ Final commit: {clusters_since_commit} clusters")

        return stats

    def process_date_range(
        self,
        country: str,
        start_date: date,
        end_date: date,
        entity_types: Optional[List[EntityTypeEnum]] = None,
        checkpoint_frequency: int = 10
    ):
        """
        Process all unprocessed clusters for a country and date range.

        Args:
            country: Initiating country
            start_date: Start date
            end_date: End date
            entity_types: List of entity types to process (optional, defaults to all)
            checkpoint_frequency: Commit frequency
        """
        print(f"\n{'='*80}")
        print(f"LLM Entity Deconfliction: {country}")
        print(f"Date range: {start_date} to {end_date}")
        if entity_types:
            print(f"Entity types: {[et.value for et in entity_types]}")
        print(f"Checkpoint frequency: every {checkpoint_frequency} clusters")
        if self.dry_run:
            print("MODE: DRY RUN (no database writes)")
        print(f"{'='*80}\n")

        total_stats = {
            'total_batches': 0,
            'total_clusters': 0,
            'skipped': 0,
            'reviewed': 0,
            'confirmed': 0,
            'split': 0,
            'canonical_entities_created': 0,
            'daily_mentions_created': 0
        }

        with get_session() as session:
            # Get all unprocessed batches
            batches = self.get_unprocessed_batches(
                session,
                country=country,
                entity_type=None
            )

            # Filter by date range and entity types
            batches = [
                b for b in batches
                if start_date <= b['cluster_date'] <= end_date
                and (entity_types is None or b['entity_type'] in entity_types)
            ]

            if not batches:
                print("No unprocessed batches found for the specified criteria.")
                return

            print(f"Found {len(batches)} unprocessed batches\n")
            total_stats['total_batches'] = len(batches)

            for i, batch in enumerate(batches, 1):
                print(f"\nBatch {i}/{len(batches)}: {batch['cluster_date']} - {batch['entity_type'].value}")
                print("-" * 80)

                batch_stats = self.process_batch(
                    session,
                    batch['initiating_country'],
                    batch['cluster_date'],
                    batch['entity_type'],
                    batch['batch_number'],
                    checkpoint_frequency
                )

                # Aggregate stats
                for key in ['total_clusters', 'skipped', 'reviewed', 'confirmed', 'split',
                           'canonical_entities_created', 'daily_mentions_created']:
                    total_stats[key] += batch_stats.get(key, 0)

        # Print summary
        print(f"\n{'='*80}")
        print("✅ LLM Deconfliction Complete!")
        print(f"{'='*80}")
        print(f"Total batches processed: {total_stats['total_batches']}")
        print(f"Total clusters processed: {total_stats['total_clusters']}")
        print(f"  - Skipped (no review needed): {total_stats['skipped']}")
        print(f"  - Reviewed by LLM: {total_stats['reviewed']}")
        print(f"    - Confirmed as single entity: {total_stats['confirmed']}")
        print(f"    - Split into multiple entities: {total_stats['split']}")
        print(f"Canonical entities created: {total_stats['canonical_entities_created']}")
        print(f"Daily mentions created: {total_stats['daily_mentions_created']}")
        print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="LLM deconfliction for entity clusters (Stage 1C)"
    )
    parser.add_argument(
        "--country",
        required=True,
        help="Initiating country to process"
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--entity-type",
        choices=['person', 'organization', 'company', 'location', 'all'],
        default='all',
        help="Entity type to process (default: all)"
    )
    parser.add_argument(
        "--checkpoint-frequency",
        type=int,
        default=10,
        help="Commit every N clusters (default: 10)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (no database writes)"
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        sys.exit(1)

    # Determine entity types to process
    if args.entity_type == 'all':
        entity_types = [
            EntityTypeEnum.PERSON,
            EntityTypeEnum.ORGANIZATION,
            EntityTypeEnum.COMPANY,
            EntityTypeEnum.LOCATION
        ]
    else:
        entity_type_map = {
            'person': EntityTypeEnum.PERSON,
            'organization': EntityTypeEnum.ORGANIZATION,
            'company': EntityTypeEnum.COMPANY,
            'location': EntityTypeEnum.LOCATION
        }
        entity_types = [entity_type_map[args.entity_type]]

    # Run deconfliction
    processor = LLMEntityDeconfliction(
        dry_run=args.dry_run,
        verbose=True
    )

    processor.process_date_range(
        args.country,
        start_date,
        end_date,
        entity_types,
        args.checkpoint_frequency
    )


if __name__ == "__main__":
    main()
