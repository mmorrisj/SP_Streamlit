# backend/scripts/news_event_tracker.py

from datetime import date, timedelta
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
import numpy as np
from sqlalchemy import select, and_
from backend.database import get_session
from backend.models import Document, RawEvent, CanonicalEvent, DailyEventMention
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
import re
import json

class NewsEventTracker:
    """
    Two-stage event tracking optimized for news article feeds.
    
    Stage 1 (Daily): Consolidate same-day mentions across sources
    Stage 2 (Temporal): Link daily mentions across time to canonical events
    """
    
    def __init__(self, session):
        self.session = session

        # Initialize embedding model (shared across all methods)
        self.embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

        # Temporal window for checking previous events
        # Shorter for breaking news, longer for recurring events
        self.lookback_windows = {
            'breaking': 3,      # Check last 3 days for breaking news
            'developing': 14,   # Check last 2 weeks for developing stories
            'recurring': 90     # Check last 3 months for recurring events
        }

        # Similarity thresholds by context
        self.similarity_thresholds = {
            'same_day': 0.70,      # Within-day clustering (lower = more grouping)
            'recent': 0.80,        # Last 3 days (high confidence needed)
            'temporal_gap': 0.85,  # After gap in coverage (very high confidence)
            'recurring': 0.75      # Recurring events (moderate)
        }
    
    # ==================== STAGE 1: DAILY CONSOLIDATION ====================
    
    def process_daily_articles(
        self, 
        target_date: date,
        country: str
    ) -> List[DailyEventMention]:
        """
        Stage 1: Your existing daily consolidation process.
        
        Process:
        1. Get all articles for the day
        2. Cluster similar event mentions (your existing HDBSCAN)
        3. LLM deduplication within clusters (your 2-layer approach)
        4. Create DailyEventMention for each unique event on this day
        5. Link to canonical events (Stage 2)
        """
        
        # Step 1-3: Your existing daily process
        raw_events = self._get_daily_raw_events(target_date, country)
        
        if not raw_events:
            return []
        
        # Cluster same-day mentions (your existing clustering)
        daily_clusters = self._cluster_daily_events(raw_events)
        
        # LLM dedupe within clusters (your existing 2-layer approach)
        deduplicated_clusters = self._llm_deduplicate_clusters(daily_clusters)
        
        # Step 4-5: Create daily mentions and link to canonical
        daily_mentions = []
        for cluster in deduplicated_clusters:
            daily_mention = self._create_or_link_daily_mention(
                cluster,
                target_date,
                country
            )
            daily_mentions.append(daily_mention)
        
        return daily_mentions
    
    def _cluster_daily_events(self, raw_events: List[Dict]) -> List[List[Dict]]:
        """
        Cluster same-day events using embeddings + DBSCAN.
        Groups articles mentioning similar events together.
        """
        if not raw_events:
            return []

        # Extract event names and normalize
        event_names = [self._normalize_event_name(e['event_name']) for e in raw_events]

        # Generate embeddings
        print(f"  Generating embeddings for {len(event_names)} events...")
        embeddings = self.embedding_model.encode(event_names, show_progress_bar=False)

        # Cluster using DBSCAN (cosine distance)
        print(f"  Clustering events...")
        clustering = DBSCAN(
            metric='cosine',
            eps=0.15,  # Lower = stricter clustering (same-day should be similar)
            min_samples=1  # Allow single-article events
        )
        labels = clustering.fit_predict(embeddings)

        # Group events by cluster label
        clusters_dict = defaultdict(list)
        for idx, label in enumerate(labels):
            clusters_dict[label].append(raw_events[idx])

        clusters = list(clusters_dict.values())
        print(f"  Found {len(clusters)} clusters from {len(raw_events)} events")

        return clusters

    def _normalize_event_name(self, name: str) -> str:
        """Normalize event name for better clustering."""
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
    
    def _llm_deduplicate_clusters(
        self,
        clusters: List[List[Dict]]
    ) -> List[List[Dict]]:
        """
        LLM-based deduplication to refine clusters.
        Handles edge cases where clustering grouped different events.
        """
        refined_clusters = []

        for cluster in clusters:
            # Only apply LLM if cluster has multiple distinct event names
            unique_names = list(set(e['event_name'] for e in cluster))

            if len(unique_names) == 1:
                # All same name, no need for LLM
                refined_clusters.append(cluster)
                continue

            if len(unique_names) <= 3:
                # Small cluster with few names - probably same event
                refined_clusters.append(cluster)
                continue

            # For larger clusters with many names, use LLM to verify
            print(f"    LLM deduplication for cluster with {len(unique_names)} unique names...")
            sub_clusters = self._llm_split_cluster(cluster, unique_names)
            refined_clusters.extend(sub_clusters)

        return refined_clusters

    def _llm_split_cluster(self, cluster: List[Dict], unique_names: List[str]) -> List[List[Dict]]:
        """
        Use LLM to determine if a cluster should be split.
        """
        from backend.scripts.utils import gai

        # Build prompt
        names_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(unique_names[:10])])  # Limit to 10

        sys_prompt = """You are an expert at identifying whether news article headlines refer to the same event or different events.
Analyze the following list of event names that were clustered together.
Determine if they all refer to the SAME event, or if there are MULTIPLE distinct events."""

        user_prompt = f"""Event names:
{names_list}

Are all these referring to the SAME event?

Respond in JSON format:
{{
    "same_event": true/false,
    "explanation": "brief explanation",
    "groups": [[1,2,3], [4,5]] // if different events, group the numbers
}}

If same_event is true, just return {{"same_event": true, "explanation": "...", "groups": [[1,2,3,...]]}}.
If different events, split into groups."""

        try:
            response = gai(sys_prompt, user_prompt)

            if isinstance(response, str):
                response = json.loads(response)

            if response.get('same_event', True):
                # Keep as one cluster
                return [cluster]
            else:
                # Split into sub-clusters
                groups = response.get('groups', [])
                name_to_group = {}
                for group_idx, indices in enumerate(groups):
                    for idx in indices:
                        if 1 <= idx <= len(unique_names):
                            name = unique_names[idx - 1]
                            name_to_group[name] = group_idx

                # Group events by their assigned group
                sub_clusters_dict = defaultdict(list)
                for event in cluster:
                    group = name_to_group.get(event['event_name'], 0)
                    sub_clusters_dict[group].append(event)

                return list(sub_clusters_dict.values())

        except Exception as e:
            print(f"    Warning: LLM deduplication failed: {e}. Keeping cluster intact.")
            return [cluster]
    
    # ==================== STAGE 2: TEMPORAL LINKING ====================
    
    def _create_or_link_daily_mention(
        self,
        cluster: List[Dict],
        target_date: date,
        country: str
    ) -> DailyEventMention:
        """
        Core temporal linking logic.
        Determine if this daily cluster matches an existing canonical event.
        """
        
        # Create daily mention object first
        daily_mention = self._create_daily_mention_record(cluster, target_date, country)

        # Determine mention context (helps with temporal matching)
        mention_context = self._classify_mention_context(cluster)
        daily_mention.mention_context = mention_context

        # Find candidate canonical events based on context-aware window
        lookback_days = self._get_lookback_window(mention_context, target_date)
        candidates = self._get_candidate_canonical_events(
            country,
            target_date,
            lookback_days
        )
        
        if not candidates:
            # No previous events - create new canonical event
            canonical_event = self._create_new_canonical_event(
                daily_mention,
                country
            )
            daily_mention.canonical_event_id = canonical_event.id

            # Add to session after canonical_event_id is set
            self.session.add(daily_mention)

            return daily_mention
        
        # Score candidates
        best_match, best_score = self._find_best_canonical_match(
            daily_mention,
            candidates,
            target_date
        )
        
        # Decision logic based on temporal gap
        if best_match:
            days_gap = (target_date - best_match.last_mention_date).days
            threshold = self._get_similarity_threshold(days_gap, mention_context)
            
            if best_score >= threshold:
                # Strong match - link to existing
                canonical_event = best_match
                self._update_canonical_event(canonical_event, daily_mention)
            
            elif best_score >= (threshold - 0.10) and days_gap <= 7:
                # Ambiguous but recent - use LLM
                canonical_event = self._llm_temporal_resolution(
                    daily_mention,
                    best_match,
                    best_score,
                    days_gap
                )
            
            else:
                # Too dissimilar or gap too large - new event
                canonical_event = self._create_new_canonical_event(
                    daily_mention,
                    country
                )
        else:
            # No candidates found
            canonical_event = self._create_new_canonical_event(
                daily_mention,
                country
            )
        
        daily_mention.canonical_event_id = canonical_event.id

        # Add to session after canonical_event_id is set
        self.session.add(daily_mention)

        return daily_mention
    
    def _classify_mention_context(self, cluster: List[Dict]) -> str:
        """
        Classify what type of news mention this is.
        Uses keywords and patterns in article text.
        """
        # Combine all distilled texts
        texts = ' '.join([e.get('distilled_text', '') for e in cluster]).lower()
        
        # Keyword patterns for different contexts
        if any(word in texts for word in ['announced', 'will', 'plans to', 'scheduled']):
            return 'announcement'
        elif any(word in texts for word in ['preparing', 'ahead of', 'in preparation']):
            return 'preparation'
        elif any(word in texts for word in ['began', 'started', 'opened', 'launched']):
            return 'execution'
        elif any(word in texts for word in ['concluded', 'ended', 'resulted in', 'outcome']):
            return 'aftermath'
        elif any(word in texts for word in ['ongoing', 'continues', 'still']):
            return 'continuation'
        else:
            return 'general'
    
    def _get_lookback_window(self, mention_context: str, target_date: date) -> int:
        """
        Context-aware lookback window.
        Announcements need longer window, execution needs shorter.
        """
        # Base lookback by context
        context_windows = {
            'announcement': 60,    # Announcements can precede events by months
            'preparation': 45,     # Preparation usually 1-2 months before
            'execution': 14,       # Execution should be recent
            'aftermath': 30,       # Aftermath within a month
            'continuation': 7,     # Continuation should be very recent
            'general': 30          # Default
        }
        
        return context_windows.get(mention_context, 30)
    
    def _get_similarity_threshold(self, days_gap: int, mention_context: str) -> float:
        """
        Adaptive threshold based on temporal gap and context.
        Longer gaps require higher similarity to match.
        """
        base_threshold = 0.75
        
        # Context adjustments
        context_adjustments = {
            'continuation': -0.05,   # Lower threshold (likely same event)
            'execution': 0.00,       # Normal threshold
            'aftermath': 0.05,       # Higher threshold (might be different)
            'announcement': 0.10     # Much higher (long gaps are expected)
        }
        
        context_adj = context_adjustments.get(mention_context, 0.0)
        
        # Temporal decay: require higher similarity for larger gaps
        if days_gap <= 3:
            temporal_adj = 0.00      # Very recent
        elif days_gap <= 7:
            temporal_adj = 0.05      # Last week
        elif days_gap <= 14:
            temporal_adj = 0.10      # Last 2 weeks
        elif days_gap <= 30:
            temporal_adj = 0.15      # Last month
        else:
            temporal_adj = 0.20      # Older
        
        return min(base_threshold + context_adj + temporal_adj, 0.95)
    
    def _get_candidate_canonical_events(
        self,
        country: str,
        target_date: date,
        lookback_days: int
    ) -> List[CanonicalEvent]:
        """
        Get candidate canonical events within temporal window.
        Filters by story phase to avoid matching dormant events.
        """
        window_start = target_date - timedelta(days=lookback_days)
        
        stmt = (
            select(CanonicalEvent)
            .where(
                and_(
                    CanonicalEvent.initiating_country == country,
                    CanonicalEvent.last_mention_date >= window_start,
                    # Exclude dormant events beyond their natural lifetime
                    CanonicalEvent.story_phase != 'dormant'
                )
            )
            .order_by(CanonicalEvent.last_mention_date.desc())
        )
        
        return list(self.session.scalars(stmt).all())
    
    def _find_best_canonical_match(
        self,
        daily_mention: DailyEventMention,
        candidates: List[CanonicalEvent],
        target_date: date
    ) -> Tuple[Optional[CanonicalEvent], float]:
        """
        Score all candidates and return best match.
        Uses news-specific signals.
        """
        best_match = None
        best_score = 0.0
        
        for candidate in candidates:
            score = self._calculate_news_similarity(
                daily_mention,
                candidate,
                target_date
            )
            
            if score > best_score:
                best_score = score
                best_match = candidate
        
        return best_match, best_score
    
    def _calculate_news_similarity(
        self,
        daily_mention: DailyEventMention,
        canonical_event: CanonicalEvent,
        target_date: date
    ) -> float:
        """
        News-specific similarity scoring.
        
        Factors:
        1. Semantic similarity (headline/content)
        2. Temporal pattern (burst vs steady coverage)
        3. Source overlap (same sources covering it?)
        4. Entity consistency (same actors/locations)
        5. Story arc coherence (does context make sense?)
        """
        
        # 1. Semantic similarity
        semantic_score = self._semantic_similarity_news(
            daily_mention,
            canonical_event
        )
        
        # 2. Temporal pattern scoring
        temporal_score = self._temporal_pattern_score(
            daily_mention,
            canonical_event,
            target_date
        )
        
        # 3. Source overlap (news-specific)
        source_score = self._source_overlap_score(
            daily_mention,
            canonical_event
        )
        
        # 4. Entity consistency
        entity_score = self._entity_consistency_score(
            daily_mention,
            canonical_event
        )
        
        # 5. Story arc coherence
        arc_score = self._story_arc_coherence(
            daily_mention,
            canonical_event
        )
        
        # Weighted combination
        weights = {
            'semantic': 0.30,
            'temporal': 0.20,
            'source': 0.15,
            'entity': 0.20,
            'arc': 0.15
        }
        
        total_score = (
            weights['semantic'] * semantic_score +
            weights['temporal'] * temporal_score +
            weights['source'] * source_score +
            weights['entity'] * entity_score +
            weights['arc'] * arc_score
        )
        
        return total_score
    
    def _source_overlap_score(
        self,
        daily_mention: DailyEventMention,
        canonical_event: CanonicalEvent
    ) -> float:
        """
        Score based on news source overlap.
        If same sources covered both, likely same event.
        """
        current_sources = set(daily_mention.source_names)
        previous_sources = set(canonical_event.unique_sources)
        
        if not current_sources or not previous_sources:
            return 0.5  # Neutral
        
        # Jaccard similarity
        overlap = len(current_sources & previous_sources)
        union = len(current_sources | previous_sources)
        
        return overlap / union if union > 0 else 0.0
    
    def _temporal_pattern_score(
        self,
        daily_mention: DailyEventMention,
        canonical_event: CanonicalEvent,
        target_date: date
    ) -> float:
        """
        Score based on news coverage patterns.
        Events have typical coverage patterns: burst → silence → burst
        """
        days_gap = (target_date - canonical_event.last_mention_date).days
        
        # Expected gaps by story phase
        expected_gaps = {
            'emerging': (0, 3),      # Continuous coverage
            'developing': (1, 7),    # Weekly updates
            'peak': (0, 2),          # Very frequent
            'fading': (3, 14),       # Occasional mentions
            'dormant': (14, 90)      # Rare updates
        }
        
        min_gap, max_gap = expected_gaps.get(
            canonical_event.story_phase,
            (0, 30)
        )
        
        # Score based on how "expected" this gap is
        if min_gap <= days_gap <= max_gap:
            return 1.0  # Expected gap
        elif days_gap < min_gap:
            return 0.9  # More frequent than expected (still good)
        elif days_gap <= max_gap * 2:
            return 0.7  # Longer gap but reasonable
        else:
            return 0.3  # Very long gap, less likely same event
    
    def _story_arc_coherence(
        self,
        daily_mention: DailyEventMention,
        canonical_event: CanonicalEvent
    ) -> float:
        """
        Check if mention context makes sense given event history.
        Example: 'aftermath' mention shouldn't come before 'execution'
        """
        current_context = daily_mention.mention_context
        
        # Get previous contexts from event history
        previous_contexts = self._get_event_contexts(canonical_event)
        
        # Story arc progression rules
        valid_progressions = {
            'announcement': {'preparation', 'execution', 'announcement', 'general'},
            'preparation': {'execution', 'preparation', 'announcement', 'general'},
            'execution': {'continuation', 'aftermath', 'execution', 'general'},
            'continuation': {'continuation', 'aftermath', 'execution', 'general'},
            'aftermath': {'aftermath', 'general'},
            'general': {'announcement', 'preparation', 'execution', 'continuation', 'aftermath', 'general'}
        }
        
        # If we have previous contexts, check progression validity
        if previous_contexts:
            last_context = previous_contexts[-1]
            
            allowed_next = valid_progressions.get(last_context, set())
            if current_context in allowed_next:
                return 1.0
            else:
                return 0.3  # Invalid progression suggests different event
        
        return 0.8  # Neutral if no history
    
    def _llm_temporal_resolution(
        self,
        daily_mention: DailyEventMention,
        candidate_event: CanonicalEvent,
        similarity_score: float,
        days_gap: int
    ) -> CanonicalEvent:
        """
        LLM-assisted decision for ambiguous temporal matches.
        Specifically designed for news article context.
        """
        
        # Get recent history of candidate event
        recent_mentions = self._get_recent_mentions(candidate_event, limit=5)
        
        prompt = f"""
        You are analyzing whether a news article cluster is about the same event as a previously tracked event.
        
        **TODAY'S NEWS COVERAGE ({daily_mention.mention_date}):**
        Headline: {daily_mention.consolidated_headline}
        Summary: {daily_mention.daily_summary}
        Sources: {', '.join(daily_mention.source_names[:5])}
        Article Count: {daily_mention.article_count}
        Context: {daily_mention.mention_context}
        
        **EXISTING EVENT IN DATABASE:**
        Name: {candidate_event.canonical_name}
        First Mentioned: {candidate_event.first_mention_date}
        Last Mentioned: {candidate_event.last_mention_date} ({days_gap} days ago)
        Total Mentions: {candidate_event.total_mention_days} days of coverage
        Story Phase: {candidate_event.story_phase}
        
        **Recent Coverage History:**
        {self._format_recent_mentions(recent_mentions)}
        
        **Similarity Analysis:**
        - Semantic similarity: {similarity_score:.2f}
        - Time gap: {days_gap} days (threshold: ambiguous)
        - Today's context: {daily_mention.mention_context}
        
        **Question:** Is today's news coverage about the SAME EVENT as the existing tracked event?
        
        **Consider:**
        1. News patterns: Events often have gaps in coverage (announced → silent → execution → silent → aftermath)
        2. Story arc: Does today's context fit the progression? (e.g., "aftermath" after "execution" is natural)
        3. Temporal coherence: Is this gap normal for this type of event?
        4. Entity consistency: Same actors/locations mentioned?
        
        **Respond in JSON:**
        {{
            "is_same_event": true/false,
            "confidence": 0.0-1.0,
            "explanation": "Why these are/aren't the same event",
            "relationship": "continuation|follow-up|distinct|related",
            "suggested_action": "link|create_new|needs_manual_review"
        }}
        """
        
        # Call LLM
        llm_response = self._call_llm(prompt)
        
        if llm_response['is_same_event'] and llm_response['confidence'] >= 0.7:
            # Link to existing
            canonical_event = candidate_event
            self._update_canonical_event(canonical_event, daily_mention)
        else:
            # Create new canonical event
            canonical_event = self._create_new_canonical_event(
                daily_mention,
                candidate_event.initiating_country
            )
        
        return canonical_event
    
    def _create_new_canonical_event(
        self,
        daily_mention: DailyEventMention,
        country: str
    ) -> CanonicalEvent:
        """Create new canonical event from first daily mention."""
        
        canonical_event = CanonicalEvent(
            canonical_name=daily_mention.consolidated_headline,
            initiating_country=country,
            first_mention_date=daily_mention.mention_date,
            last_mention_date=daily_mention.mention_date,
            total_mention_days=1,
            total_articles=daily_mention.article_count,
            story_phase='emerging',
            days_since_last_mention=0,
            unique_sources=daily_mention.source_names,
            source_count=len(daily_mention.source_names),
            peak_mention_date=daily_mention.mention_date,
            peak_daily_article_count=daily_mention.article_count,
            alternative_names=[daily_mention.consolidated_headline]
        )
        
        self.session.add(canonical_event)
        self.session.flush()
        
        return canonical_event
    
    def _update_canonical_event(
        self,
        canonical_event: CanonicalEvent,
        daily_mention: DailyEventMention
    ):
        """Update canonical event with new daily mention."""
        
        # Update temporal tracking
        canonical_event.last_mention_date = daily_mention.mention_date
        canonical_event.total_mention_days += 1
        canonical_event.total_articles += daily_mention.article_count
        canonical_event.days_since_last_mention = 0
        
        # Track peak coverage
        if daily_mention.article_count > canonical_event.peak_daily_article_count:
            canonical_event.peak_mention_date = daily_mention.mention_date
            canonical_event.peak_daily_article_count = daily_mention.article_count
        
        # Update sources
        existing_sources = set(canonical_event.unique_sources or [])
        new_sources = set(daily_mention.source_names)
        all_sources = existing_sources | new_sources
        canonical_event.unique_sources = list(all_sources)
        canonical_event.source_count = len(all_sources)
        
        # Add alternative name if different
        if daily_mention.consolidated_headline not in canonical_event.alternative_names:
            canonical_event.alternative_names.append(daily_mention.consolidated_headline)
        
        # Update story phase
        canonical_event.story_phase = self._determine_story_phase(canonical_event)
    
    def _determine_story_phase(self, canonical_event: CanonicalEvent) -> str:
        """Determine story phase based on coverage patterns."""
        
        # Get recent activity
        total_days = (canonical_event.last_mention_date - canonical_event.first_mention_date).days + 1
        mention_frequency = canonical_event.total_mention_days / max(total_days, 1)
        
        # Recent intensity (last 7 days)
        recent_mentions = self._count_recent_mentions(canonical_event, days=7)
        
        if recent_mentions >= 4:
            return 'peak'  # Very active
        elif recent_mentions >= 2:
            return 'developing'  # Steady coverage
        elif canonical_event.total_mention_days <= 2:
            return 'emerging'  # Just appeared
        elif canonical_event.days_since_last_mention <= 14:
            return 'active'  # Regular mentions
        elif canonical_event.days_since_last_mention <= 30:
            return 'fading'  # Less frequent
        else:
            return 'dormant'  # No recent coverage
    
    # Helper methods
    def _get_daily_raw_events(self, target_date: date, country: str) -> List[Dict]:
        """Get raw events from documents for specific date."""
        stmt = (
            select(Document, RawEvent)
            .join(RawEvent, RawEvent.doc_id == Document.doc_id)
            .where(
                and_(
                    Document.date == target_date,
                    Document.initiating_country == country
                )
            )
        )
        
        results = self.session.execute(stmt).all()
        return [
            {
                'doc_id': doc.doc_id,
                'event_name': raw_event.event_name,
                'distilled_text': doc.distilled_text,
                'source_name': doc.source_name,
                'date': doc.date,
                'category': doc.category,
                'recipient_country': doc.recipient_country
            }
            for doc, raw_event in results
        ]
    
    def _create_daily_mention_record(
        self,
        cluster: List[Dict],
        target_date: date,
        country: str
    ) -> DailyEventMention:
        """Create daily mention record from cluster."""

        # Get most representative headline
        event_names = [e['event_name'] for e in cluster]
        consolidated_headline = max(set(event_names), key=event_names.count)

        # Get unique sources
        sources = list(set(e['source_name'] for e in cluster if e.get('source_name')))

        # Get doc IDs
        doc_ids = [e['doc_id'] for e in cluster]

        daily_mention = DailyEventMention(
            mention_date=target_date,
            initiating_country=country,
            article_count=len(cluster),
            consolidated_headline=consolidated_headline,
            source_names=sources,
            source_diversity_score=len(sources) / len(cluster),
            doc_ids=doc_ids
        )

        return daily_mention
    
    def _get_event_contexts(self, canonical_event: CanonicalEvent) -> List[str]:
        """Get historical contexts for an event."""
        stmt = (
            select(DailyEventMention.mention_context)
            .where(DailyEventMention.canonical_event_id == canonical_event.id)
            .order_by(DailyEventMention.mention_date)
        )
        return list(self.session.scalars(stmt).all())
    
    def _semantic_similarity_news(
        self,
        daily_mention: DailyEventMention,
        canonical_event: CanonicalEvent
    ) -> float:
        """
        Calculate semantic similarity using embeddings (cosine similarity).
        """
        # Normalize both texts
        text1 = self._normalize_event_name(daily_mention.consolidated_headline)
        text2 = self._normalize_event_name(canonical_event.canonical_name)

        # Generate embeddings
        emb1 = self.embedding_model.encode([text1])[0]
        emb2 = self.embedding_model.encode([text2])[0]

        # Calculate cosine similarity
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

        # Convert to 0-1 range (cosine similarity is -1 to 1)
        similarity = (similarity + 1) / 2

        return float(similarity)

    def _entity_consistency_score(
        self,
        daily_mention: DailyEventMention,
        canonical_event: CanonicalEvent
    ) -> float:
        """
        Score based on entity consistency (countries, actors, locations).
        Uses simple keyword matching and named entity overlap.
        """
        score = 0.0
        weights_sum = 0.0

        # 1. Country consistency (weight: 0.4)
        if daily_mention.initiating_country == canonical_event.initiating_country:
            score += 0.4
        weights_sum += 0.4

        # 2. Extract and compare named entities from text (weight: 0.6)
        mention_entities = self._extract_entities(daily_mention.consolidated_headline)
        event_entities = self._extract_entities(canonical_event.canonical_name)

        # Also check alternative names
        for alt_name in canonical_event.alternative_names:
            alt_entities = self._extract_entities(alt_name)
            event_entities.update(alt_entities)

        # Calculate Jaccard similarity of entities
        if mention_entities or event_entities:
            overlap = len(mention_entities & event_entities)
            union = len(mention_entities | event_entities)
            entity_sim = overlap / union if union > 0 else 0.0
            score += 0.6 * entity_sim
        else:
            score += 0.3  # Neutral if no entities
        weights_sum += 0.6

        return score / weights_sum if weights_sum > 0 else 0.5

    def _extract_entities(self, text: str) -> Set[str]:
        """
        Extract named entities using simple keyword matching.
        In production, replace with proper NER (spaCy, etc.)
        """
        entities = set()

        # Normalize text
        text = text.lower()

        # Extract country names (simple approach)
        countries = [
            'china', 'russia', 'iran', 'india', 'pakistan', 'egypt',
            'saudi arabia', 'uae', 'turkey', 'brazil', 'iraq', 'syria',
            'afghanistan', 'israel', 'palestine', 'jordan', 'lebanon',
            'yemen', 'oman', 'qatar', 'bahrain', 'kuwait', 'ethiopia',
            'somalia', 'kenya', 'sudan', 'libya', 'algeria', 'morocco'
        ]

        for country in countries:
            if country in text:
                entities.add(country)

        # Extract project/initiative names
        initiatives = [
            'belt and road', 'bri', 'brics', 'sco', 'shanghai cooperation',
            'quad', 'aukus', 'asean', 'opec', 'g7', 'g20', 'nato',
            'african union', 'arab league', 'gcc', 'oic'
        ]

        for initiative in initiatives:
            if initiative in text:
                entities.add(initiative)

        # Extract city names (major capitals/cities)
        cities = [
            'beijing', 'moscow', 'tehran', 'delhi', 'islamabad',
            'cairo', 'riyadh', 'dubai', 'ankara', 'brasilia',
            'baghdad', 'damascus', 'kabul', 'jerusalem', 'amman'
        ]

        for city in cities:
            if city in text:
                entities.add(city)

        return entities

    def _count_recent_mentions(self, canonical_event: CanonicalEvent, days: int) -> int:
        """Count mentions in the last N days."""
        from datetime import timedelta

        cutoff_date = canonical_event.last_mention_date - timedelta(days=days)

        stmt = (
            select(DailyEventMention)
            .where(
                and_(
                    DailyEventMention.canonical_event_id == canonical_event.id,
                    DailyEventMention.mention_date >= cutoff_date
                )
            )
        )

        mentions = list(self.session.scalars(stmt).all())
        return len(mentions)

    def _get_recent_mentions(self, canonical_event: CanonicalEvent, limit: int = 5) -> List[DailyEventMention]:
        """Get recent daily mentions for an event."""
        stmt = (
            select(DailyEventMention)
            .where(DailyEventMention.canonical_event_id == canonical_event.id)
            .order_by(DailyEventMention.mention_date.desc())
            .limit(limit)
        )

        return list(self.session.scalars(stmt).all())

    def _format_recent_mentions(self, mentions: List[DailyEventMention]) -> str:
        """Format recent mentions for LLM prompt."""
        if not mentions:
            return "No recent mentions"

        lines = []
        for mention in mentions:
            lines.append(f"- {mention.mention_date}: {mention.consolidated_headline} ({mention.article_count} articles)")

        return "\n".join(lines)

    def _call_llm(self, prompt: str) -> Dict:
        """
        Call LLM for temporal resolution (ambiguous cases).
        """
        from backend.scripts.utils import gai

        sys_prompt = """You are an expert news analyst determining if two news mentions refer to the same event.
Analyze temporal patterns, story progression, and contextual coherence.
Be conservative: if there's significant doubt, treat as separate events."""

        try:
            response = gai(sys_prompt, prompt)

            # Parse response
            if isinstance(response, str):
                response = json.loads(response)

            # Validate required fields
            required_fields = ['is_same_event', 'confidence', 'explanation', 'relationship', 'suggested_action']
            for field in required_fields:
                if field not in response:
                    # Fill in defaults
                    if field == 'is_same_event':
                        response[field] = False
                    elif field == 'confidence':
                        response[field] = 0.5
                    elif field == 'explanation':
                        response[field] = 'Missing field'
                    elif field == 'relationship':
                        response[field] = 'distinct'
                    elif field == 'suggested_action':
                        response[field] = 'create_new'

            return response

        except Exception as e:
            print(f"    Warning: LLM call failed: {e}. Defaulting to separate events.")
            return {
                'is_same_event': False,
                'confidence': 0.0,
                'explanation': f'LLM error: {str(e)}',
                'relationship': 'distinct',
                'suggested_action': 'create_new'
            }