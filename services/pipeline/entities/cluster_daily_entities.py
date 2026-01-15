"""
Cluster Daily Entity Mentions (Stage 1B)

Groups similar entity mentions per day using DBSCAN clustering on embeddings.
Processes entities separately by type (person, organization, company, location).

Input: raw_entities table
Output: entity_clusters table

Usage:
    # Cluster entities for China on specific dates
    python cluster_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-08-31

    # Process specific entity type only
    python cluster_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-08-31 --entity-type person

    # Check clustering status
    python cluster_daily_entities.py --country China --status

    # Custom clustering parameters
    python cluster_daily_entities.py --country China --start-date 2024-08-01 --end-date 2024-08-31 --eps 0.12 --min-samples 1
"""

import os
import sys
import argparse
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from collections import defaultdict
import gc

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from shared.database.database import get_session
from shared.models.models import (
    Document, RawEntity, EntityCluster, EntityTypeEnum,
    InitiatingCountry
)
from shared.utils.utils import Config
from sqlalchemy import text, func, and_
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity
import uuid


# ============================================================================
# CLUSTERING CONFIGURATION
# ============================================================================

# Clustering parameters (tighter than events - entity names have less variation)
DEFAULT_EPS = 0.12  # Cosine distance threshold (vs 0.15 for events)
DEFAULT_MIN_SAMPLES = 1  # Minimum cluster size

# Batch size for organizing clusters for later LLM processing
CLUSTER_BATCH_SIZE = 150  # ~150 entities per batch for LLM


# ============================================================================
# EMBEDDING AND CLUSTERING FUNCTIONS
# ============================================================================

def load_embedding_model():
    """Load SentenceTransformer model for entity name embeddings."""
    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    print("✓ Model loaded\n")
    return model


def cluster_entities_for_date_and_type(
    session,
    country: str,
    date: datetime,
    entity_type: EntityTypeEnum,
    model: SentenceTransformer,
    eps: float = DEFAULT_EPS,
    min_samples: int = DEFAULT_MIN_SAMPLES
) -> int:
    """
    Cluster entity mentions for a specific date, country, and entity type.

    Args:
        session: Database session
        country: Initiating country
        date: Date to process
        entity_type: Type of entity to cluster
        model: SentenceTransformer model
        eps: DBSCAN epsilon (distance threshold)
        min_samples: Minimum samples for core points

    Returns:
        Number of clusters created
    """

    # Query all entity mentions for this date/country/type
    query = text("""
        SELECT DISTINCT
            re.entity_name,
            re.country_affiliation,
            re.role,
            ARRAY_AGG(DISTINCT re.doc_id) as doc_ids,
            COUNT(*) as mention_count
        FROM raw_entities re
        JOIN documents d ON re.doc_id = d.doc_id
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE ic.initiating_country = :country
          AND d.date = :date
          AND re.entity_type = :entity_type
        GROUP BY re.entity_name, re.country_affiliation, re.role
        ORDER BY mention_count DESC
    """)

    result = session.execute(
        query,
        {
            'country': country,
            'date': date.date(),
            'entity_type': entity_type.value
        }
    )

    entities = []
    for row in result:
        entities.append({
            'entity_name': row.entity_name,
            'country_affiliation': row.country_affiliation,
            'role': row.role,
            'doc_ids': row.doc_ids,
            'mention_count': row.mention_count
        })

    if not entities:
        return 0

    if len(entities) == 1:
        # Single entity - create a cluster for it
        _save_single_entity_cluster(
            session, country, date, entity_type,
            entities[0], model
        )
        return 1

    # Generate embeddings for entity names
    entity_names = [e['entity_name'] for e in entities]
    embeddings = model.encode(entity_names, convert_to_numpy=True)

    # Run DBSCAN clustering
    dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
    labels = dbscan.fit_predict(embeddings)

    # Get unique cluster labels
    unique_labels = set(labels)
    num_clusters = len(unique_labels)

    # Organize clusters into batches for later LLM processing
    clusters_by_label = defaultdict(list)
    for idx, label in enumerate(labels):
        clusters_by_label[label].append({
            'entity': entities[idx],
            'embedding': embeddings[idx]
        })

    # Calculate number of batches needed
    total_entities = len(entities)
    num_batches = (total_entities + CLUSTER_BATCH_SIZE - 1) // CLUSTER_BATCH_SIZE

    # Distribute clusters across batches
    batch_assignments = {}
    current_batch = 0
    entities_in_batch = 0

    for label in sorted(clusters_by_label.keys(), key=lambda x: len(clusters_by_label[x]), reverse=True):
        cluster_size = len(clusters_by_label[label])

        # Start new batch if current would overflow
        if entities_in_batch > 0 and entities_in_batch + cluster_size > CLUSTER_BATCH_SIZE:
            current_batch += 1
            entities_in_batch = 0

        batch_assignments[label] = current_batch
        entities_in_batch += cluster_size

    # Save clusters to database
    for label, cluster_items in clusters_by_label.items():
        batch_number = batch_assignments[label]

        # Collect cluster data
        cluster_entity_names = [item['entity']['entity_name'] for item in cluster_items]
        cluster_doc_ids = list(set(
            doc_id
            for item in cluster_items
            for doc_id in item['entity']['doc_ids']
        ))
        cluster_embeddings = [item['embedding'] for item in cluster_items]

        # Calculate centroid embedding
        centroid_embedding = np.mean(cluster_embeddings, axis=0).tolist()

        # Find most central entity name
        similarities = cosine_similarity([centroid_embedding], cluster_embeddings)[0]
        most_central_idx = np.argmax(similarities)
        representative_name = cluster_entity_names[most_central_idx]

        # Create EntityCluster record
        entity_cluster = EntityCluster(
            id=str(uuid.uuid4()),
            initiating_country=country,
            cluster_date=date.date(),
            entity_type=entity_type,
            batch_number=batch_number,
            cluster_id=int(label),
            entity_names=cluster_entity_names,
            doc_ids=cluster_doc_ids,
            cluster_size=len(cluster_items),
            is_noise=(label == -1),
            centroid_embedding=centroid_embedding,
            representative_name=representative_name,
            processed=False,
            llm_deconflicted=False
        )

        session.add(entity_cluster)

    return num_clusters


def _save_single_entity_cluster(
    session,
    country: str,
    date: datetime,
    entity_type: EntityTypeEnum,
    entity: Dict[str, Any],
    model: SentenceTransformer
):
    """Save a cluster for a single entity."""

    # Generate embedding
    embedding = model.encode([entity['entity_name']], convert_to_numpy=True)[0].tolist()

    entity_cluster = EntityCluster(
        id=str(uuid.uuid4()),
        initiating_country=country,
        cluster_date=date.date(),
        entity_type=entity_type,
        batch_number=0,
        cluster_id=0,
        entity_names=[entity['entity_name']],
        doc_ids=entity['doc_ids'],
        cluster_size=1,
        is_noise=False,
        centroid_embedding=embedding,
        representative_name=entity['entity_name'],
        processed=False,
        llm_deconflicted=False
    )

    session.add(entity_cluster)


def process_date_range(
    country: str,
    start_date: datetime,
    end_date: datetime,
    entity_types: List[EntityTypeEnum],
    eps: float = DEFAULT_EPS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    force: bool = False
):
    """
    Process entity clustering for a date range.

    Args:
        country: Initiating country
        start_date: Start date
        end_date: End date
        entity_types: List of entity types to process
        eps: DBSCAN epsilon
        min_samples: DBSCAN min_samples
        force: If True, delete existing clusters and reprocess
    """

    print(f"\n{'='*80}")
    print(f"Clustering Entities: {country}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Entity types: {[et.value for et in entity_types]}")
    print(f"Clustering parameters: eps={eps}, min_samples={min_samples}")
    if force:
        print(f"Mode: FORCE - will delete existing clusters and reprocess")
    else:
        print(f"Mode: Skip dates with existing clusters (use --force to reprocess)")
    print(f"{'='*80}\n")

    # Load embedding model
    model = load_embedding_model()

    with get_session() as session:
        current_date = start_date
        total_clusters_created = 0

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")

            for entity_type in entity_types:
                # Check if already processed
                if not force:
                    existing_count = session.query(func.count(EntityCluster.id)).filter(
                        and_(
                            EntityCluster.initiating_country == country,
                            EntityCluster.cluster_date == current_date.date(),
                            EntityCluster.entity_type == entity_type
                        )
                    ).scalar()

                    if existing_count > 0:
                        print(f"  {date_str} [{entity_type.value}]: Skipping (already has {existing_count} clusters)")
                        continue

                # Delete existing clusters if force mode
                if force:
                    session.query(EntityCluster).filter(
                        and_(
                            EntityCluster.initiating_country == country,
                            EntityCluster.cluster_date == current_date.date(),
                            EntityCluster.entity_type == entity_type
                        )
                    ).delete()

                # Cluster entities
                print(f"  {date_str} [{entity_type.value}]: Clustering...")
                num_clusters = cluster_entities_for_date_and_type(
                    session,
                    country,
                    current_date,
                    entity_type,
                    model,
                    eps,
                    min_samples
                )

                if num_clusters > 0:
                    session.commit()
                    print(f"  ✓ {date_str} [{entity_type.value}]: Created {num_clusters} clusters")
                    total_clusters_created += num_clusters
                else:
                    print(f"  {date_str} [{entity_type.value}]: No entities to cluster")

            current_date += timedelta(days=1)

        print(f"\n{'='*80}")
        print(f"✅ Clustering Complete!")
        print(f"  Total clusters created: {total_clusters_created}")
        print(f"{'='*80}\n")


def show_status(country: str):
    """Show entity clustering status for a country."""

    print(f"\n{'='*80}")
    print(f"Entity Clustering Status: {country}")
    print(f"{'='*80}\n")

    with get_session() as session:
        # Count clusters by type
        cluster_counts = session.query(
            EntityCluster.entity_type,
            func.count(EntityCluster.id),
            func.count(EntityCluster.id).filter(EntityCluster.llm_deconflicted == True)
        ).filter(
            EntityCluster.initiating_country == country
        ).group_by(
            EntityCluster.entity_type
        ).all()

        # Get date range
        date_range = session.query(
            func.min(EntityCluster.cluster_date),
            func.max(EntityCluster.cluster_date)
        ).filter(
            EntityCluster.initiating_country == country
        ).first()

        # Count total entities in clusters
        total_entities_result = session.execute(
            text("""
                SELECT entity_type, SUM(cluster_size) as total_entities
                FROM entity_clusters
                WHERE initiating_country = :country
                GROUP BY entity_type
            """),
            {'country': country}
        ).fetchall()

        print(f"Date range: {date_range[0]} to {date_range[1]}")
        print(f"\nClusters by type:")

        for entity_type, total_clusters, llm_processed in cluster_counts:
            print(f"  {entity_type.value}:")
            print(f"    Total clusters: {total_clusters}")
            print(f"    LLM processed: {llm_processed} ({llm_processed / total_clusters * 100 if total_clusters > 0 else 0:.1f}%)")

        print(f"\nEntities in clusters:")
        for row in total_entities_result:
            print(f"  {row.entity_type}: {row.total_entities}")

        print(f"{'='*80}\n")


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Cluster entity mentions per day (Stage 1B)"
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
        "--entity-type",
        choices=['person', 'organization', 'company', 'location', 'all'],
        default='all',
        help="Entity type to process (default: all)"
    )
    parser.add_argument(
        "--eps",
        type=float,
        default=DEFAULT_EPS,
        help=f"DBSCAN epsilon (default: {DEFAULT_EPS})"
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help=f"DBSCAN min_samples (default: {DEFAULT_MIN_SAMPLES})"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing (delete existing clusters)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show clustering status for the country"
    )

    args = parser.parse_args()

    # Show status mode
    if args.status:
        show_status(args.country)
        return

    # Require dates for processing
    if not args.start_date or not args.end_date:
        print("Error: --start-date and --end-date are required for processing")
        print("Use --status to check clustering status")
        sys.exit(1)

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
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

    # Process
    process_date_range(
        args.country,
        start_date,
        end_date,
        entity_types,
        args.eps,
        args.min_samples,
        args.force
    )


if __name__ == "__main__":
    main()
