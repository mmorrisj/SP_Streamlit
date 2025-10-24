"""
LLM Deconfliction for Event Clusters

This script processes event clusters from the event_clusters table and uses an LLM
to refine and validate cluster groupings. The LLM reviews each cluster to determine
if events truly represent the same real-world event or should be split.

Processing Strategy:
1. Load clusters by (country, date, batch_number) where llm_deconflicted = False
2. For each cluster, check if LLM review is needed (clusters with multiple unique event names)
3. Use LLM to verify if events in cluster represent the same real-world event
4. Save refined cluster groupings to refined_clusters JSONB field
5. Mark clusters as llm_deconflicted = True

Usage:
    # Process specific country and date
    python llm_deconflict_clusters.py --country China --date 2024-08-01

    # Process all unprocessed clusters for a country
    python llm_deconflict_clusters.py --country China

    # Process all unprocessed clusters (all countries)
    python llm_deconflict_clusters.py --all

    # Process specific date range
    python llm_deconflict_clusters.py --start-date 2024-08-01 --end-date 2024-08-31

    # Process from config.yaml influencers
    python llm_deconflict_clusters.py --influencers --start-date 2024-08-01 --end-date 2024-08-31

    # Dry run (no database writes)
    python llm_deconflict_clusters.py --country China --date 2024-08-01 --dry-run
"""

import argparse
import json
import yaml
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from collections import defaultdict
from sqlalchemy import text

from shared.database.database import get_session
from shared.models.models import EventCluster, CanonicalEvent, DailyEventMention, RawEvent
from shared.utils.utils import gai
from sentence_transformers import SentenceTransformer


class LLMClusterDeconfliction:
    """
    Handles LLM-based deconfliction of event clusters.
    """

    def __init__(self, dry_run: bool = False, verbose: bool = True):
        self.dry_run = dry_run
        self.verbose = verbose
        # Initialize embedding model for canonical events
        self.embedding_model = None

    def get_embedding_model(self):
        """Lazy load embedding model."""
        if self.embedding_model is None:
            if self.verbose:
                print("  Loading sentence transformer model...")
            self.embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
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
        target_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all unprocessed batches (country, date, batch_number combinations).

        Args:
            session: Database session
            country: Filter by specific country (optional)
            target_date: Filter by specific date (optional)

        Returns:
            List of dicts with keys: initiating_country, cluster_date, batch_number
        """
        query = """
            SELECT DISTINCT
                initiating_country,
                cluster_date,
                batch_number
            FROM event_clusters
            WHERE llm_deconflicted = FALSE
        """

        params = {}
        if country:
            query += " AND initiating_country = :country"
            params['country'] = country
        if target_date:
            query += " AND cluster_date = :target_date"
            params['target_date'] = target_date

        query += " ORDER BY initiating_country, cluster_date, batch_number"

        result = session.execute(text(query), params)
        batches = []
        for row in result:
            batches.append({
                'initiating_country': row[0],
                'cluster_date': row[1],
                'batch_number': row[2]
            })

        return batches

    def load_batch_clusters(
        self,
        session,
        country: str,
        target_date: date,
        batch_number: int
    ) -> List[EventCluster]:
        """
        Load all clusters for a specific batch.

        Args:
            session: Database session
            country: Initiating country
            target_date: Cluster date
            batch_number: Batch number

        Returns:
            List of EventCluster objects
        """
        clusters = session.query(EventCluster).filter(
            EventCluster.initiating_country == country,
            EventCluster.cluster_date == target_date,
            EventCluster.batch_number == batch_number,
            EventCluster.llm_deconflicted == False
        ).all()

        return clusters

    def needs_llm_review(self, cluster: EventCluster) -> bool:
        """
        Determine if a cluster needs LLM review.

        Criteria:
        - Skip if cluster is noise (cluster_id == -1)
        - Skip if all event names are identical (no ambiguity)
        - Review ALL clusters with 2+ unique event names (could be same event OR multiple events)

        Args:
            cluster: EventCluster object

        Returns:
            True if LLM review is needed, False otherwise
        """
        # Skip noise clusters
        if cluster.is_noise:
            return False

        # Get unique event names
        unique_names = list(set(cluster.event_names))

        # Skip if all same name (definitely one event)
        if len(unique_names) == 1:
            return False

        # Review ALL clusters with multiple unique names
        # Even 2 unique names could be either:
        #   - Same event: "Beijing Declaration" vs "Beijing Agreement"
        #   - Different events: "Belt and Road Initiative" vs "Beijing Declaration"
        return True

    def llm_review_cluster(self, cluster: EventCluster) -> Dict[str, Any]:
        """
        Use LLM to review and potentially split a cluster.

        Args:
            cluster: EventCluster object with multiple event names

        Returns:
            Dict with keys:
                - same_event: bool (True if all names refer to same event)
                - explanation: str (LLM's reasoning)
                - groups: List[List[int]] (if split, indices of event names grouped together)
                - refined_cluster_ids: List[int] (new cluster IDs if split)
        """
        unique_names = list(set(cluster.event_names))

        # Build prompt with numbered list of unique event names
        names_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(unique_names)])

        sys_prompt = """You are an expert at tracking events across their lifecycle in news coverage.

**CRITICAL UNDERSTANDING:**
Events evolve through stages over time. Your task is to group event names that refer to the SAME underlying event, EVEN IF they are at different stages.

**Event Lifecycle Stages:**
- ANNOUNCEMENT: "China announces Belt and Road Forum"
- PREPARATION: "China preparing for Belt and Road Forum"
- EXECUTION: "Belt and Road Forum begins in Beijing"
- CONTINUATION: "Belt and Road Forum continues with trade deals"
- AFTERMATH: "Belt and Road Forum concludes with 50 agreements"

**Your Task:**
Analyze the following list of event names that were clustered together. Identify which event names refer to the SAME underlying event across different stages, and which are DISTINCT events.

**Context:**
- These events all occurred on the same date
- They are all initiated by the same country
- The clustering algorithm grouped them based on semantic similarity
- The algorithm often groups topically related but DISTINCT events together

**Examples:**

✅ SAME EVENT - Group Together (same event at different stages):
- "China announces South-South Cooperation Forum"
- "Preparations underway for South-South Cooperation Forum"
- "South-South Cooperation Forum opens in Beijing"
- "South-South Cooperation Forum concludes with cooperation agreements"
→ All refer to same forum at different lifecycle stages

✅ SAME EVENT - Group Together (same event, different wording):
- "President Xi visits Egypt for bilateral talks"
- "Xi Jinping state visit to Egypt"
- "China-Egypt summit during Xi's Cairo visit"
→ All refer to same visit

✅ SAME EVENT - Group Together (same event, different aspects):
- "Beijing Declaration", "Beijing Agreement", "Beijing Summit Agreement"
→ All refer to same agreement
- "Arbaeen Pilgrimage", "Arbaeen Pilgrimage Support", "Arbaeen Healthcare Services"
→ All aspects of same pilgrimage event

❌ DIFFERENT EVENTS - Keep Separate (different instances):
- "First China-Arab States Cooperation Forum"
- "Second China-Arab States Cooperation Forum"
→ Different instances of the same type of event

❌ DIFFERENT EVENTS - Keep Separate (different topics with same partner):
- "China signs trade deal with Egypt"
- "China signs defense cooperation with Egypt"
→ Different agreements, even with same country

❌ DIFFERENT EVENTS - Keep Separate (same type, different partners):
- "China signs trade deal with Egypt"
- "China signs trade deal with UAE"
→ Different countries = different events

❌ DIFFERENT EVENTS - Keep Separate (topically related but distinct):
- "Belt and Road Initiative", "Beijing Declaration", "25-year Cooperation Plan"
→ Three separate diplomatic initiatives
- "Humanitarian Aid to Gaza", "Ceasefire Negotiations", "UN Security Council Meeting"
→ Related to same conflict but three distinct events

**Your Goal:**
- Group event names that refer to the SAME core event (even at different stages)
- Keep DISTINCT events in separate groups
- Err on the side of grouping if it's the same core event evolving over time"""

        user_prompt = f"""Event names from cluster (cluster_id={cluster.cluster_id}, size={cluster.cluster_size}):
{names_list}

**ANALYZE USING CHAIN-OF-THOUGHT:**

**STEP 1 - IDENTIFY CORE EVENTS:**
For each event name, extract the core event:
- What is the main activity? (summit, visit, agreement, project, announcement, etc.)
- Who are the key actors? (countries, organizations, leaders)
- What is the context? (location, initiative, purpose)

**STEP 2 - MATCH ACROSS STAGES:**
Group events that share the same core, even if they differ in:
- Stage indicators: "announces", "preparing", "begins", "ongoing", "concludes", "resulted in"
- Temporal markers: "upcoming", "scheduled", "started", "continuing", "ended"
- Outcome language: "will", "plans to", "is", "has", "completed"

**STEP 3 - DISTINGUISH TRULY DIFFERENT EVENTS:**
Keep events SEPARATE if they are:
- Different instances: "First meeting" vs "Second meeting"
- Different topics: "Trade agreement" vs "Defense cooperation" (both with same country)
- Different entities: "China-Egypt summit" vs "China-UAE summit"
- Different projects: "Port project in Egypt" vs "Railway project in Egypt"

**STEP 4 - VALIDATION:**
For each potential group, verify:
- If tracking this event's lifecycle, would all these headlines fit the same timeline?
- Could these be different news sources reporting the SAME event at different stages?
- Or are these genuinely DIFFERENT events (even if similar)?

---

**OUTPUT (JSON format):**
{{
    "reasoning": "Brief overview of your grouping strategy (2-3 sentences)",
    "same_event": true/false,  // true if ALL names refer to ONE event, false if multiple distinct events
    "groups": [[1,2,3], [4,5], [6]],  // group numbers by which events belong together
    "stages_identified": ["announcement", "execution", "aftermath"],  // lifecycle stages present (if applicable)
    "confidence": 0.95  // 0.0-1.0 confidence in your grouping
}}

**Examples:**
- If all {len(unique_names)} names refer to ONE event: {{"reasoning": "...", "same_event": true, "groups": [[{','.join(str(i+1) for i in range(len(unique_names)))}]], "stages_identified": ["execution"], "confidence": 0.95}}
- If there are TWO distinct events: {{"reasoning": "...", "same_event": false, "groups": [[1,2], [3,4,5]], "stages_identified": [], "confidence": 0.90}}
- If there are THREE distinct events: {{"reasoning": "...", "same_event": false, "groups": [[1,2], [3], [4,5,6]], "stages_identified": [], "confidence": 0.85}}

**IMPORTANT:**
- Every number from 1 to {len(unique_names)} must appear in exactly one group
- Create as many groups as there are distinct real-world events
- Group events that are the SAME core event at different lifecycle stages
- Only keep events separate if you're confident they're truly distinct events (confidence >= 0.80)"""

        try:
            if self.verbose:
                print(f"    Sending {len(unique_names)} event names to LLM for review...")

            # Use direct OpenAI call (bypassing FastAPI proxy to avoid recursion)
            # OPENAI_PROJ_API is already set in environment
            response = gai(sys_prompt, user_prompt, model="gpt-4o-mini", use_proxy=False)

            # Parse JSON response (handle both dict and string)
            if isinstance(response, str):
                # Try to extract JSON from markdown code blocks if present
                import re
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
                if json_match:
                    response = json.loads(json_match.group(1))
                else:
                    # Try to find any JSON object in the response
                    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
                    if json_match:
                        response = json.loads(json_match.group(0))
                    else:
                        response = json.loads(response)

            # Validate response structure
            if 'same_event' not in response or 'groups' not in response:
                raise ValueError(f"Invalid LLM response structure: {response}")

            result = {
                'same_event': response.get('same_event', True),
                'explanation': response.get('explanation', ''),
                'groups': response.get('groups', [[i+1 for i in range(len(unique_names))]]),
                'refined_cluster_ids': []
            }

            # If split into multiple groups, assign new cluster IDs
            if not result['same_event'] and len(result['groups']) > 1:
                # Keep first group with original cluster_id, assign new IDs to others
                result['refined_cluster_ids'] = [cluster.cluster_id] + \
                    [cluster.cluster_id + 1000 + i for i in range(len(result['groups']) - 1)]

            return result

        except Exception as e:
            if self.verbose:
                print(f"    Warning: LLM review failed: {e}. Keeping cluster intact.")

            # Return safe default (keep cluster as-is)
            return {
                'same_event': True,
                'explanation': f'LLM review failed: {str(e)}',
                'groups': [[i+1 for i in range(len(unique_names))]],
                'refined_cluster_ids': [cluster.cluster_id]
            }

    def save_deconfliction_result(
        self,
        session,
        cluster: EventCluster,
        llm_result: Dict[str, Any]
    ):
        """
        Save LLM deconfliction result to database.

        Updates the cluster record with:
        - refined_clusters: JSONB containing LLM analysis
        - llm_deconflicted: True

        Args:
            session: Database session
            cluster: EventCluster object
            llm_result: Dict returned from llm_review_cluster()
        """
        # Build refined_clusters JSONB
        unique_names = list(set(cluster.event_names))

        refined_data = {
            'same_event': llm_result['same_event'],
            'explanation': llm_result['explanation'],
            'original_cluster_size': cluster.cluster_size,
            'unique_event_names': len(unique_names),
            'groups': llm_result['groups'],
            'refined_cluster_ids': llm_result.get('refined_cluster_ids', [cluster.cluster_id]),
            'reviewed_at': datetime.utcnow().isoformat(),
            'unique_names_list': unique_names
        }

        # Update cluster
        cluster.refined_clusters = refined_data
        cluster.llm_deconflicted = True

        if self.verbose:
            if llm_result['same_event']:
                print(f"    [OK] Cluster {cluster.cluster_id}: Confirmed as single event")
            else:
                print(f"    [OK] Cluster {cluster.cluster_id}: Split into {len(llm_result['groups'])} sub-events")
                print(f"      Groups: {llm_result['groups']}")

    def create_canonical_events_from_cluster(
        self,
        session,
        cluster: EventCluster,
        llm_result: Optional[Dict[str, Any]] = None
    ) -> List[CanonicalEvent]:
        """
        Create CanonicalEvent and DailyEventMention records from a deconflicted cluster.

        This consolidates duplicate event name references into unified event objects
        that all relevant doc_ids reference.

        Args:
            session: Database session
            cluster: EventCluster with llm_deconflicted = True
            llm_result: Optional LLM result (if not provided, loads from cluster.refined_clusters)

        Returns:
            List of created CanonicalEvent objects
        """
        # Load LLM result from cluster if not provided
        if llm_result is None:
            if cluster.refined_clusters is None:
                raise ValueError(f"Cluster {cluster.cluster_id} has no refined_clusters data")
            llm_result = cluster.refined_clusters

        # Get unique event names
        unique_names = list(set(cluster.event_names))
        groups = llm_result.get('groups', [[i+1 for i in range(len(unique_names))]])

        # Create mapping of event name to doc_ids
        name_to_docs = defaultdict(list)
        for event_name, doc_id in zip(cluster.event_names, cluster.doc_ids):
            name_to_docs[event_name].append(doc_id)

        canonical_events = []

        # Process each group (each group represents one real-world event)
        for group_idx, group_indices in enumerate(groups):
            # Get event names in this group
            group_names = [unique_names[idx - 1] for idx in group_indices if 1 <= idx <= len(unique_names)]

            if not group_names:
                continue

            # Collect all doc_ids for this group
            group_doc_ids = []
            for name in group_names:
                group_doc_ids.extend(name_to_docs[name])

            # Remove duplicates while preserving order
            group_doc_ids = list(dict.fromkeys(group_doc_ids))

            # Choose canonical name (most frequent or first)
            canonical_name = max(group_names, key=group_names.count)

            # Generate embedding for canonical name
            model = self.get_embedding_model()
            embedding = model.encode(canonical_name).tolist()

            # Check if canonical event already exists
            existing_event = session.query(CanonicalEvent).filter(
                CanonicalEvent.canonical_name == canonical_name,
                CanonicalEvent.initiating_country == cluster.initiating_country,
                CanonicalEvent.first_mention_date <= cluster.cluster_date,
                CanonicalEvent.last_mention_date >= cluster.cluster_date
            ).first()

            if existing_event:
                # Update existing canonical event
                canonical_event = existing_event
                canonical_event.last_mention_date = max(canonical_event.last_mention_date, cluster.cluster_date)
                canonical_event.total_articles += len(group_doc_ids)

                # Add alternative names
                for name in group_names:
                    if name != canonical_name and name not in canonical_event.alternative_names:
                        canonical_event.alternative_names = canonical_event.alternative_names + [name]

                if self.verbose:
                    print(f"      Updated existing canonical event: {canonical_name}")

            else:
                # Create new canonical event
                canonical_event = CanonicalEvent(
                    canonical_name=canonical_name,
                    initiating_country=cluster.initiating_country,
                    first_mention_date=cluster.cluster_date,
                    last_mention_date=cluster.cluster_date,
                    total_mention_days=1,
                    total_articles=len(group_doc_ids),
                    story_phase="emerging",
                    days_since_last_mention=0,
                    unique_sources=[],
                    source_count=0,
                    peak_mention_date=cluster.cluster_date,
                    peak_daily_article_count=len(group_doc_ids),
                    embedding_vector=embedding,
                    alternative_names=[name for name in group_names if name != canonical_name],
                    primary_categories={},
                    primary_recipients={}
                )
                session.add(canonical_event)
                session.flush()  # Get the ID

                if self.verbose:
                    print(f"      Created canonical event: {canonical_name}")

            canonical_events.append(canonical_event)

            # Create or update DailyEventMention
            existing_mention = session.query(DailyEventMention).filter(
                DailyEventMention.canonical_event_id == canonical_event.id,
                DailyEventMention.mention_date == cluster.cluster_date
            ).first()

            if existing_mention:
                # Update existing mention
                existing_mention.article_count = len(group_doc_ids)
                existing_mention.doc_ids = group_doc_ids
                existing_mention.consolidated_headline = canonical_name

                if self.verbose:
                    print(f"        Updated daily mention: {len(group_doc_ids)} articles")

            else:
                # Create new daily mention
                daily_mention = DailyEventMention(
                    canonical_event_id=canonical_event.id,
                    initiating_country=cluster.initiating_country,
                    mention_date=cluster.cluster_date,
                    article_count=len(group_doc_ids),
                    consolidated_headline=canonical_name,
                    daily_summary=None,  # Could be generated by LLM in future
                    source_names=[],  # Could be populated from documents
                    source_diversity_score=0.0,
                    mention_context="execution",  # Default value
                    news_intensity="developing",  # Default value
                    doc_ids=group_doc_ids
                )
                session.add(daily_mention)

                if self.verbose:
                    print(f"        Created daily mention: {len(group_doc_ids)} articles on {cluster.cluster_date}")

        return canonical_events

    def process_batch(
        self,
        session,
        country: str,
        target_date: date,
        batch_number: int
    ) -> Dict[str, int]:
        """
        Process all clusters in a batch with LLM deconfliction.

        Args:
            session: Database session
            country: Initiating country
            target_date: Cluster date
            batch_number: Batch number

        Returns:
            Dict with statistics:
                - total_clusters: Total clusters in batch
                - skipped: Clusters that didn't need LLM review
                - reviewed: Clusters reviewed by LLM
                - confirmed: Clusters confirmed as single event
                - split: Clusters split into multiple events
        """
        stats = {
            'total_clusters': 0,
            'skipped': 0,
            'reviewed': 0,
            'confirmed': 0,
            'split': 0,
            'canonical_events_created': 0,
            'canonical_events_updated': 0,
            'daily_mentions_created': 0
        }

        # Load all clusters in this batch
        clusters = self.load_batch_clusters(session, country, target_date, batch_number)
        stats['total_clusters'] = len(clusters)

        if len(clusters) == 0:
            if self.verbose:
                print(f"  No unprocessed clusters found for batch {batch_number}")
            return stats

        if self.verbose:
            print(f"  Processing {len(clusters)} clusters in batch {batch_number}...")

        for cluster in clusters:
            llm_result = None

            # Check if LLM review is needed
            if not self.needs_llm_review(cluster):
                if self.verbose:
                    print(f"    Cluster {cluster.cluster_id}: Skipped (only {len(set(cluster.event_names))} unique names)")

                # Mark as processed without LLM review (unless dry run)
                if not self.dry_run:
                    llm_result = {
                        'same_event': True,
                        'explanation': 'Skipped LLM review - small cluster with few unique names',
                        'original_cluster_size': cluster.cluster_size,
                        'unique_event_names': len(set(cluster.event_names)),
                        'groups': [[i+1 for i in range(len(set(cluster.event_names)))]],
                        'refined_cluster_ids': [cluster.cluster_id],
                        'reviewed_at': datetime.utcnow().isoformat(),
                        'unique_names_list': list(set(cluster.event_names))
                    }
                    cluster.refined_clusters = llm_result
                    cluster.llm_deconflicted = True
                stats['skipped'] += 1

            else:
                # Perform LLM review
                llm_result = self.llm_review_cluster(cluster)
                stats['reviewed'] += 1

                if llm_result['same_event']:
                    stats['confirmed'] += 1
                else:
                    stats['split'] += 1

                # Save result (unless dry run)
                if not self.dry_run:
                    self.save_deconfliction_result(session, cluster, llm_result)

            # Create canonical events from deconflicted cluster (unless dry run)
            if not self.dry_run and llm_result is not None:
                canonical_events = self.create_canonical_events_from_cluster(session, cluster, llm_result)
                for ce in canonical_events:
                    if ce.total_mention_days == 1:
                        stats['canonical_events_created'] += 1
                    else:
                        stats['canonical_events_updated'] += 1
                    stats['daily_mentions_created'] += 1

        # Commit changes (unless dry run)
        if not self.dry_run:
            session.commit()
            if self.verbose:
                print(f"  [OK] Committed batch {batch_number} to database")
        else:
            if self.verbose:
                print(f"  [OK] Dry run - no changes committed")

        return stats

    def process_country_date(
        self,
        session,
        country: str,
        target_date: date
    ) -> Dict[str, Any]:
        """
        Process all batches for a specific country and date.

        Args:
            session: Database session
            country: Initiating country
            target_date: Cluster date

        Returns:
            Dict with overall statistics
        """
        print("=" * 60)
        print(f"Processing: {country} on {target_date}")
        print("=" * 60)

        # Get all unprocessed batches for this country/date
        batches = self.get_unprocessed_batches(session, country=country, target_date=target_date)

        if len(batches) == 0:
            print(f"  No unprocessed batches found for {country} on {target_date}")
            return {}

        overall_stats = {
            'total_batches': len(batches),
            'total_clusters': 0,
            'skipped': 0,
            'reviewed': 0,
            'confirmed': 0,
            'split': 0,
            'canonical_events_created': 0,
            'canonical_events_updated': 0,
            'daily_mentions_created': 0
        }

        for batch in batches:
            batch_stats = self.process_batch(
                session,
                country=batch['initiating_country'],
                target_date=batch['cluster_date'],
                batch_number=batch['batch_number']
            )

            # Aggregate statistics
            overall_stats['total_clusters'] += batch_stats['total_clusters']
            overall_stats['skipped'] += batch_stats['skipped']
            overall_stats['reviewed'] += batch_stats['reviewed']
            overall_stats['confirmed'] += batch_stats['confirmed']
            overall_stats['split'] += batch_stats['split']
            overall_stats['canonical_events_created'] += batch_stats.get('canonical_events_created', 0)
            overall_stats['canonical_events_updated'] += batch_stats.get('canonical_events_updated', 0)
            overall_stats['daily_mentions_created'] += batch_stats.get('daily_mentions_created', 0)

        # Print summary
        print(f"\n  Summary for {country} on {target_date}:")
        print(f"    Batches processed: {overall_stats['total_batches']}")
        print(f"    Total clusters: {overall_stats['total_clusters']}")
        print(f"    Skipped (no LLM needed): {overall_stats['skipped']}")
        print(f"    Reviewed by LLM: {overall_stats['reviewed']}")
        print(f"    Confirmed as single event: {overall_stats['confirmed']}")
        print(f"    Split into multiple events: {overall_stats['split']}")
        print(f"    Canonical events created: {overall_stats['canonical_events_created']}")
        print(f"    Canonical events updated: {overall_stats['canonical_events_updated']}")
        print(f"    Daily mentions created: {overall_stats['daily_mentions_created']}")

        return overall_stats


def main():
    parser = argparse.ArgumentParser(
        description="LLM Deconfliction for Event Clusters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Processing scope arguments
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--date', type=str, help='Process specific date (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, help='Start date for range processing (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date for range processing (YYYY-MM-DD)')
    parser.add_argument('--influencers', action='store_true',
                       help='Process all influencer countries from config.yaml')
    parser.add_argument('--all', action='store_true',
                       help='Process all unprocessed clusters (all countries and dates)')

    # Options
    parser.add_argument('--dry-run', action='store_true',
                       help='Run without saving changes to database')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Print detailed progress (default: True)')
    parser.add_argument('--quiet', action='store_true',
                       help='Suppress detailed output')

    args = parser.parse_args()

    # Handle verbosity
    verbose = args.verbose and not args.quiet

    # Initialize processor
    processor = LLMClusterDeconfliction(dry_run=args.dry_run, verbose=verbose)

    # Print header
    print("=" * 60)
    print("LLM EVENT CLUSTER DECONFLICTION")
    print("=" * 60)
    if args.dry_run:
        print("DRY RUN MODE - No database changes will be saved")
        print("=" * 60)

    with get_session() as session:
        # Determine processing scope
        if args.country and args.date:
            # Process specific country and date
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
            processor.process_country_date(session, args.country, target_date)

        elif args.influencers and args.start_date and args.end_date:
            # Process all influencer countries for date range
            config = processor.load_config()
            influencers = config['influencers']

            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

            print(f"Processing {len(influencers)} influencer countries from config.yaml:")
            print(f"  {', '.join(influencers)}")
            print(f"Date range: {start_date} to {end_date}")
            print("=" * 60)
            print()

            # Iterate over date range
            current_date = start_date
            from datetime import timedelta

            while current_date <= end_date:
                for country in influencers:
                    processor.process_country_date(session, country, current_date)

                current_date += timedelta(days=1)

        elif args.all:
            # Process all unprocessed batches
            print("Processing all unprocessed batches...")
            print("=" * 60)

            batches = processor.get_unprocessed_batches(session)
            print(f"Found {len(batches)} unprocessed batches")
            print()

            for batch in batches:
                processor.process_country_date(
                    session,
                    batch['initiating_country'],
                    batch['cluster_date']
                )

        else:
            # Invalid arguments
            print("Error: Must specify processing scope:")
            print("  --country COUNTRY --date DATE")
            print("  --influencers --start-date DATE --end-date DATE")
            print("  --all")
            parser.print_help()
            return

    print("=" * 60)
    print("[OK] LLM deconfliction completed")
    print("=" * 60)


if __name__ == "__main__":
    main()
