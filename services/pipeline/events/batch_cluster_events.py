"""
Batch Event Clustering Script

This script clusters event names by country and date using DBSCAN + embeddings.

**Clustering Strategy:**
- Clusters ALL events for a specific (country, date) together in one pass
- Uses embeddings to identify semantically similar events
- Organizes clusters into batches of ~50 events for later LLM deconfliction
- The batch_size parameter only affects how clusters are grouped for LLM processing,
  NOT the clustering itself

Usage:
    # Cluster events for a specific country and date
    python services/pipeline/events/batch_cluster_events.py --country China --date 2024-08-15

    # Cluster events for a date range
    python services/pipeline/events/batch_cluster_events.py --country China --start-date 2024-08-01 --end-date 2024-08-31

    # Cluster for all influencer countries (from config.yaml)
    python services/pipeline/events/batch_cluster_events.py --influencers --start-date 2024-08-01 --end-date 2024-08-31

    # Dry run (show what would be processed without saving)
    python services/pipeline/events/batch_cluster_events.py --country China --date 2024-08-15 --dry-run

    # Adjust clustering sensitivity (eps) and LLM batch size
    python services/pipeline/events/batch_cluster_events.py --country China --date 2024-08-15 --eps 0.20 --batch-size 100

Author: Event Pipeline
Date: 2025-10-22
"""

import argparse
import re
import yaml
from datetime import date, datetime, timedelta
from typing import List, Dict, Tuple
from collections import defaultdict
import numpy as np

from sqlalchemy import text
from sklearn.cluster import DBSCAN
from sentence_transformers import SentenceTransformer

from shared.database.database import get_session
from shared.models.models import EventCluster, RawEvent, Document, InitiatingCountry


def load_config(config_path: str = 'shared/config/config.yaml') -> dict:
    """Load configuration from config.yaml"""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return {
                'influencers': config.get('influencers', ['China', 'Russia', 'Iran', 'Turkey', 'United States']),
                'recipients': config.get('recipients', [
                    'Bahrain', 'Cyprus', 'Egypt', 'Iran', 'Iraq', 'Israel', 'Jordan',
                    'Kuwait', 'Lebanon', 'Libya', 'Oman', 'Palestine', 'Qatar',
                    'Saudi Arabia', 'Syria', 'Turkey', 'United Arab Emirates', 'UAE', 'Yemen'
                ])
            }
    except Exception as e:
        print(f"Warning: Could not load config.yaml: {e}")
        print("Using default values")
        return {
            'influencers': ['China', 'Russia', 'Iran', 'Turkey', 'United States'],
            'recipients': [
                'Bahrain', 'Cyprus', 'Egypt', 'Iran', 'Iraq', 'Israel', 'Jordan',
                'Kuwait', 'Lebanon', 'Libya', 'Oman', 'Palestine', 'Qatar',
                'Saudi Arabia', 'Syria', 'Turkey', 'United Arab Emirates', 'UAE', 'Yemen'
            ]
        }


def load_influencer_countries(config_path: str = 'shared/config/config.yaml') -> List[str]:
    """Load influencer countries from config.yaml (backward compatibility)"""
    config = load_config(config_path)
    return config['influencers']


class EventBatchClusterer:
    """
    Clusters event names in batches using DBSCAN + embeddings.
    Similar to news_event_tracker.py but processes in batches of ~50 events.
    """

    def __init__(self, batch_size: int = 50, eps: float = 0.15, recipient_countries: List[str] = None):
        """
        Initialize the batch clusterer.

        Args:
            batch_size: Number of events to process per batch
            eps: DBSCAN epsilon parameter (0.15 = strict, 0.30 = loose)
            recipient_countries: List of target recipient countries to filter for (from config.yaml)
        """
        self.batch_size = batch_size
        self.eps = eps
        self.recipient_countries = recipient_countries or []
        self.embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def normalize_event_name(self, name: str) -> str:
        """
        Normalize event name for better clustering.
        Same normalization as news_event_tracker.py
        """
        # Lowercase
        name = name.lower()
        # Remove punctuation except spaces
        name = re.sub(r'[^\w\s]', '', name)
        # Remove ordinals (1st, 2nd, etc.)
        name = re.sub(r'\b\d+(?:st|nd|rd|th)\b', '', name)
        # Remove generic words
        name = re.sub(r'\b(cooperation|forum|meeting|summit|conference)\b', '', name)
        # Collapse whitespace
        name = ' '.join(name.split())
        return name

    def get_events_for_date_country(
        self,
        session,
        country: str,
        target_date: date
    ) -> List[Dict]:
        """
        Get all events for a specific country and date.

        IMPORTANT Filters:
        1. Excludes documents where recipient country equals initiating country
        2. Only includes documents where recipient is in the target recipients list (config.yaml)

        Returns:
            List of dicts with keys: event_name, doc_id, date
        """
        # Build base query
        if self.recipient_countries:
            # Filter by target recipients from config
            query = text("""
                SELECT DISTINCT
                    re.event_name,
                    re.doc_id,
                    d.date
                FROM raw_events re
                JOIN documents d ON re.doc_id = d.doc_id
                JOIN initiating_countries ic ON d.doc_id = ic.doc_id
                WHERE ic.initiating_country = :country
                  AND d.date = :target_date
                  -- Must have at least one target recipient country
                  AND EXISTS (
                      SELECT 1
                      FROM recipient_countries rc
                      WHERE rc.doc_id = d.doc_id
                        AND rc.recipient_country = ANY(:recipients)
                  )
                  -- Exclude documents where recipient = initiator (not soft power)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM recipient_countries rc
                      WHERE rc.doc_id = d.doc_id
                        AND rc.recipient_country = ic.initiating_country
                  )
                ORDER BY re.event_name
            """)

            result = session.execute(query, {
                'country': country,
                'target_date': target_date,
                'recipients': self.recipient_countries
            })
        else:
            # No recipient filter, just exclude self-directed
            query = text("""
                SELECT DISTINCT
                    re.event_name,
                    re.doc_id,
                    d.date
                FROM raw_events re
                JOIN documents d ON re.doc_id = d.doc_id
                JOIN initiating_countries ic ON d.doc_id = ic.doc_id
                WHERE ic.initiating_country = :country
                  AND d.date = :target_date
                  -- Exclude documents where recipient = initiator (not soft power)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM recipient_countries rc
                      WHERE rc.doc_id = d.doc_id
                        AND rc.recipient_country = ic.initiating_country
                  )
                ORDER BY re.event_name
            """)

            result = session.execute(query, {
                'country': country,
                'target_date': target_date
            })

        events = []
        for row in result:
            events.append({
                'event_name': row.event_name,
                'doc_id': row.doc_id,
                'date': row.date
            })

        return events

    def cluster_batch(
        self,
        events: List[Dict]
    ) -> List[Tuple[int, List[Dict], List[float]]]:
        """
        Cluster a batch of events using DBSCAN.

        Args:
            events: List of event dicts

        Returns:
            List of tuples: (cluster_id, events_in_cluster, centroid_embedding)
        """
        if not events:
            return []

        # Normalize and generate embeddings
        event_names = [self.normalize_event_name(e['event_name']) for e in events]
        embeddings = self.embedding_model.encode(event_names, show_progress_bar=False)

        # Cluster using DBSCAN
        clustering = DBSCAN(
            metric='cosine',
            eps=self.eps,
            min_samples=1  # Allow singleton clusters
        )
        labels = clustering.fit_predict(embeddings)

        # Group by cluster label
        clusters_dict = defaultdict(list)
        embeddings_dict = defaultdict(list)

        for idx, label in enumerate(labels):
            clusters_dict[label].append(events[idx])
            embeddings_dict[label].append(embeddings[idx])

        # Calculate centroids
        results = []
        for cluster_id, cluster_events in clusters_dict.items():
            cluster_embeddings = np.array(embeddings_dict[cluster_id])
            centroid = np.mean(cluster_embeddings, axis=0).tolist()

            results.append((cluster_id, cluster_events, centroid))

        return results

    def find_representative_name(
        self,
        events: List[Dict],
        centroid: List[float]
    ) -> str:
        """
        Find the event name closest to the centroid.
        """
        if len(events) == 1:
            return events[0]['event_name']

        # Get embeddings for all event names
        event_names = [self.normalize_event_name(e['event_name']) for e in events]
        embeddings = self.embedding_model.encode(event_names, show_progress_bar=False)

        # Find closest to centroid
        centroid_array = np.array(centroid)
        distances = [np.linalg.norm(emb - centroid_array) for emb in embeddings]
        min_idx = np.argmin(distances)

        return events[min_idx]['event_name']

    def save_clusters(
        self,
        session,
        country: str,
        target_date: date,
        batch_number: int,
        clusters: List[Tuple[int, List[Dict], List[float]]]
    ):
        """
        Save clustered events to database.
        """
        for cluster_id, cluster_events, centroid in clusters:
            # Extract event names and doc IDs
            event_names = [e['event_name'] for e in cluster_events]
            doc_ids = list(set([e['doc_id'] for e in cluster_events]))

            # Find representative name
            representative_name = self.find_representative_name(cluster_events, centroid)

            # Create EventCluster record (convert numpy types to native Python)
            event_cluster = EventCluster(
                initiating_country=country,
                cluster_date=target_date,
                batch_number=int(batch_number),  # Ensure native Python int
                cluster_id=int(cluster_id),  # Convert from numpy.int64
                event_names=event_names,
                doc_ids=doc_ids,
                cluster_size=len(cluster_events),
                is_noise=bool(cluster_id == -1),  # DBSCAN noise label
                centroid_embedding=[float(x) for x in centroid],  # Convert from numpy.float32
                representative_name=representative_name,
                processed=False,
                llm_deconflicted=False,
                created_at=datetime.utcnow()
            )

            session.add(event_cluster)

    def process_date(
        self,
        session,
        country: str,
        target_date: date,
        dry_run: bool = False
    ) -> Dict:
        """
        Process all events for a specific country and date.

        NEW BEHAVIOR: Clusters ALL events for the day together (not in batches).
        The batch_size is only used for organizing clusters for later LLM processing.

        Returns:
            Stats dict with: total_events, num_batches, num_clusters
        """
        print(f"\n{'='*60}")
        print(f"Processing: {country} on {target_date}")
        print(f"{'='*60}")

        # Get all events for this country/date
        events = self.get_events_for_date_country(session, country, target_date)

        if not events:
            print(f"  No events found for {country} on {target_date}")
            return {
                'total_events': 0,
                'num_batches': 0,
                'num_clusters': 0
            }

        print(f"  Found {len(events)} events")
        print(f"  Clustering ALL {len(events)} events together...")
        print(f"    Generating embeddings...")
        print(f"    Running DBSCAN (eps={self.eps})...")

        # Cluster ALL events for this day at once
        clusters = self.cluster_batch(events)

        print(f"  [OK] Found {len(clusters)} clusters from {len(events)} events")

        # Show cluster summary
        print(f"\n  Cluster Summary:")
        # Sort clusters by size (largest first)
        sorted_clusters = sorted(clusters, key=lambda x: len(x[1]), reverse=True)

        for cluster_id, cluster_events, _ in sorted_clusters[:20]:  # Show top 20
            is_noise = (cluster_id == -1)
            noise_label = " [NOISE]" if is_noise else ""
            print(f"    Cluster {cluster_id}{noise_label}: {len(cluster_events)} events")

            # Show first 3 event names
            for i, event in enumerate(cluster_events[:3]):
                event_name = event['event_name'][:80].encode('ascii', 'replace').decode('ascii')
                print(f"      - {event_name}")
            if len(cluster_events) > 3:
                print(f"      ... and {len(cluster_events) - 3} more")

        if len(sorted_clusters) > 20:
            print(f"    ... and {len(sorted_clusters) - 20} more clusters")

        # Split clusters into batches for LLM processing later
        # Each batch should have roughly batch_size total events (not clusters)
        print(f"\n  Organizing clusters into batches of ~{self.batch_size} events for later LLM processing:")

        batched_clusters = self._organize_clusters_for_llm(clusters)

        for batch_num, batch_clusters in enumerate(batched_clusters):
            batch_event_count = sum(len(c[1]) for c in batch_clusters)
            print(f"    Batch {batch_num}: {len(batch_clusters)} clusters, {batch_event_count} events")

        # Save to database
        if not dry_run:
            total_saved = 0
            for batch_num, batch_clusters in enumerate(batched_clusters):
                self.save_clusters(
                    session,
                    country,
                    target_date,
                    batch_num,
                    batch_clusters
                )
                total_saved += len(batch_clusters)

            session.commit()
            print(f"\n  [OK] Saved {total_saved} clusters in {len(batched_clusters)} batch(es)")
            print(f"  [OK] Committed to database for {country} on {target_date}")
        else:
            print(f"\n  [DRY RUN] Would save {len(clusters)} clusters in {len(batched_clusters)} batch(es)")

        return {
            'total_events': len(events),
            'num_batches': len(batched_clusters),
            'num_clusters': len(clusters)
        }

    def _organize_clusters_for_llm(
        self,
        clusters: List[Tuple[int, List[Dict], List[float]]]
    ) -> List[List[Tuple[int, List[Dict], List[float]]]]:
        """
        Organize clusters into batches for LLM processing.
        Each batch should contain roughly batch_size events total.

        This ensures LLM processing later won't exceed token limits.
        """
        batches = []
        current_batch = []
        current_batch_size = 0

        # Sort clusters by size to distribute load better
        sorted_clusters = sorted(clusters, key=lambda x: len(x[1]), reverse=True)

        for cluster in sorted_clusters:
            cluster_size = len(cluster[1])

            # If adding this cluster would exceed batch_size, start a new batch
            if current_batch and (current_batch_size + cluster_size > self.batch_size):
                batches.append(current_batch)
                current_batch = []
                current_batch_size = 0

            current_batch.append(cluster)
            current_batch_size += cluster_size

        # Add the last batch if it has any clusters
        if current_batch:
            batches.append(current_batch)

        return batches


def get_available_countries(session) -> List[str]:
    """Get list of all unique initiating countries in the database."""
    query = text("SELECT DISTINCT initiating_country FROM initiating_countries ORDER BY initiating_country")
    result = session.execute(query)
    return [row.initiating_country for row in result]


def main():
    parser = argparse.ArgumentParser(
        description='Cluster events by country and date in batches',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single date and country
  python services/pipeline/events/batch_cluster_events.py --country China --date 2024-08-15

  # Date range for one country
  python services/pipeline/events/batch_cluster_events.py --country China --start-date 2024-08-01 --end-date 2024-08-31

  # All countries for a date range
  python services/pipeline/events/batch_cluster_events.py --start-date 2024-08-01 --end-date 2024-08-31 --all-countries

  # Adjust batch size and clustering sensitivity
  python services/pipeline/events/batch_cluster_events.py --country China --date 2024-08-15 --batch-size 30 --eps 0.20
        """
    )

    parser.add_argument('--country', type=str, help='Initiating country to process')
    parser.add_argument('--date', type=str, help='Single date to process (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, help='Start date for date range (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date for date range (YYYY-MM-DD)')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries from config.yaml (China, Russia, Iran, Turkey, United States)')
    parser.add_argument('--all-countries', action='store_true', help='Process ALL countries in database (not recommended - many spurious countries)')
    parser.add_argument('--batch-size', type=int, default=150, help='Events per batch for LLM processing (default: 150, does NOT affect clustering)')
    parser.add_argument('--eps', type=float, default=0.15, help='DBSCAN epsilon (default: 0.15, range: 0.10-0.30)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without saving')

    args = parser.parse_args()

    # Validate arguments
    if not args.all_countries and not args.influencers and not args.country:
        parser.error("Must specify either --country, --influencers, or --all-countries")

    if not args.date and not (args.start_date and args.end_date):
        parser.error("Must specify either --date or both --start-date and --end-date")

    if args.date and (args.start_date or args.end_date):
        parser.error("Cannot specify both --date and --start-date/--end-date")

    # Parse dates
    if args.date:
        start_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        end_date = start_date
    else:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    # Load config for recipient countries
    config = load_config()
    recipient_countries = config['recipients']

    # Initialize clusterer
    clusterer = EventBatchClusterer(
        batch_size=args.batch_size,
        eps=args.eps,
        recipient_countries=recipient_countries
    )

    print("\n" + "="*60)
    print("BATCH EVENT CLUSTERING")
    print("="*60)
    print(f"Date range: {start_date} to {end_date}")
    print(f"Batch size: {args.batch_size}")
    print(f"DBSCAN eps: {args.eps}")
    print(f"Recipient filter: {len(recipient_countries)} target countries from config.yaml")
    if args.dry_run:
        print("MODE: DRY RUN (no changes will be saved)")
    print("="*60)

    # Get countries to process
    with get_session() as session:
        if args.all_countries:
            countries = get_available_countries(session)
            print(f"\nProcessing ALL {len(countries)} countries in database")
            print(f"  Countries: {', '.join(countries[:10])}{'...' if len(countries) > 10 else ''}")
        elif args.influencers:
            countries = load_influencer_countries()
            print(f"\nProcessing {len(countries)} influencer countries from config.yaml:")
            print(f"  {', '.join(countries)}")
        else:
            countries = [args.country]
            print(f"\nProcessing single country: {args.country}")

    # Process each country and date
    overall_stats = {
        'total_events': 0,
        'total_batches': 0,
        'total_clusters': 0,
        'dates_processed': 0
    }

    with get_session() as session:
        current_date = start_date
        while current_date <= end_date:
            for country in countries:
                stats = clusterer.process_date(
                    session,
                    country,
                    current_date,
                    dry_run=args.dry_run
                )

                overall_stats['total_events'] += stats['total_events']
                overall_stats['total_batches'] += stats['num_batches']
                overall_stats['total_clusters'] += stats['num_clusters']
                if stats['total_events'] > 0:
                    overall_stats['dates_processed'] += 1

            current_date += timedelta(days=1)

    # Print summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Dates processed: {overall_stats['dates_processed']}")
    print(f"Total events: {overall_stats['total_events']}")
    print(f"Total batches: {overall_stats['total_batches']}")
    print(f"Total clusters: {overall_stats['total_clusters']}")
    if overall_stats['total_events'] > 0:
        avg_cluster_size = overall_stats['total_events'] / overall_stats['total_clusters']
        print(f"Average cluster size: {avg_cluster_size:.1f} events")
    print("="*60)

    if not args.dry_run:
        print("\n[OK] Clusters saved to event_clusters table")
        print("  Next step: Run LLM deconfliction on saved clusters")
    else:
        print("\n[DRY RUN COMPLETE] No changes were made to the database")


if __name__ == "__main__":
    main()
