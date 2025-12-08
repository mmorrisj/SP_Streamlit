"""
RAG Query Engine for Soft Power Analytics

This module provides semantic search and retrieval capabilities across:
- Event summaries (daily, weekly, monthly)
- Source documents
- Bilateral relationship summaries
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, date
import numpy as np
from sqlalchemy import text
from sentence_transformers import SentenceTransformer

from shared.database.database import get_session
from shared.models.models import EventSummary, Document, PeriodType
from services.pipeline.embeddings.embedding_vectorstore import get_vectorstore


class QueryEngine:
    """RAG query engine for semantic search across soft power data."""

    def __init__(self):
        """Initialize the query engine with embedding model and vector stores."""
        self.embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

        # Get vector stores for different collections
        self.chunk_store, self.summary_store, self.daily_store, self.weekly_store, self.monthly_store, self.yearly_store = get_vectorstore()

    def embed_query(self, query: str) -> np.ndarray:
        """
        Generate embedding for a query string.

        Args:
            query: Query text

        Returns:
            384-dimensional embedding vector
        """
        return self.embedding_model.encode(query)

    def search_event_summaries(
        self,
        query: str,
        period_type: Optional[str] = None,
        country: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Semantic search across event summaries.

        Args:
            query: Natural language query
            period_type: Filter by period (daily, weekly, monthly, yearly)
            country: Filter by initiating country
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum results to return

        Returns:
            List of matching event summaries with relevance scores
        """
        # Select appropriate vector store based on period type
        if period_type == 'daily':
            store = self.daily_store
        elif period_type == 'weekly':
            store = self.weekly_store
        elif period_type == 'monthly':
            store = self.monthly_store
        elif period_type == 'yearly':
            store = self.yearly_store
        else:
            # Default to daily store for general queries
            store = self.daily_store

        # Perform similarity search
        results = store.similarity_search_with_score(query, k=limit)

        # Format results
        formatted_results = []
        for doc, score in results:
            metadata = doc.metadata

            # Apply filters
            if country and metadata.get('country') != country:
                continue
            if start_date and metadata.get('period_start') and datetime.fromisoformat(metadata['period_start']).date() < start_date:
                continue
            if end_date and metadata.get('period_end') and datetime.fromisoformat(metadata['period_end']).date() > end_date:
                continue

            formatted_results.append({
                'event_id': metadata.get('event_id'),
                'event_name': metadata.get('event_name'),
                'country': metadata.get('country'),
                'period_start': metadata.get('period_start'),
                'period_end': metadata.get('period_end'),
                'content': doc.page_content,
                'relevance_score': float(score),
                'period_type': period_type or 'daily'
            })

        return formatted_results[:limit]

    def search_documents(
        self,
        query: str,
        country: Optional[str] = None,
        category: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Semantic search across source documents.

        Args:
            query: Natural language query
            country: Filter by initiating country
            category: Filter by category
            start_date: Filter by document date
            end_date: Filter by document date
            limit: Maximum results to return

        Returns:
            List of matching documents with relevance scores
        """
        # Perform similarity search on chunk embeddings
        results = self.chunk_store.similarity_search_with_score(query, k=limit * 2)

        # Format and filter results
        formatted_results = []
        seen_docs = set()

        for doc, score in results:
            metadata = doc.metadata
            doc_id = metadata.get('doc_id')

            # Skip duplicate documents
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)

            # Apply filters
            if country and metadata.get('initiating_country') != country:
                continue
            if start_date and metadata.get('date') and datetime.fromisoformat(metadata['date']).date() < start_date:
                continue
            if end_date and metadata.get('date') and datetime.fromisoformat(metadata['date']).date() > end_date:
                continue

            formatted_results.append({
                'doc_id': doc_id,
                'title': metadata.get('title'),
                'source': metadata.get('source_name'),
                'date': metadata.get('date'),
                'country': metadata.get('initiating_country'),
                'content': doc.page_content,
                'relevance_score': float(score)
            })

            if len(formatted_results) >= limit:
                break

        return formatted_results

    def get_event_context(
        self,
        event_id: str,
        include_sources: bool = True,
        include_related: bool = True
    ) -> Dict:
        """
        Retrieve full context for a specific event.

        Args:
            event_id: Event summary ID
            include_sources: Include source documents
            include_related: Include related events

        Returns:
            Comprehensive event context
        """
        with get_session() as session:
            # Get primary event
            event = session.get(EventSummary, event_id)
            if not event:
                return {}

            context = {
                'event_id': str(event.id),
                'event_name': event.event_name,
                'country': event.initiating_country,
                'period_type': event.period_type.value,
                'period_start': event.period_start.isoformat(),
                'period_end': event.period_end.isoformat(),
                'narrative_summary': event.narrative_summary,
                'count_by_category': event.count_by_category,
                'count_by_recipient': event.count_by_recipient,
                'total_documents': event.total_documents_across_sources
            }

            # Get source documents
            if include_sources:
                source_links = session.execute(
                    text("""
                        SELECT d.doc_id, d.title, d.source_name, d.date, d.url
                        FROM event_source_links esl
                        JOIN documents d ON esl.doc_id = d.doc_id
                        WHERE esl.event_summary_id = :event_id
                        ORDER BY esl.contribution_weight DESC
                        LIMIT 10
                    """),
                    {'event_id': event_id}
                ).fetchall()

                context['source_documents'] = [
                    {
                        'doc_id': row[0],
                        'title': row[1],
                        'source': row[2],
                        'date': row[3].isoformat() if row[3] else None,
                        'url': row[4]
                    }
                    for row in source_links
                ]

            # Get related events (same event name, different time periods)
            if include_related:
                related = session.execute(
                    text("""
                        SELECT id, period_type, period_start, period_end, total_documents_across_sources
                        FROM event_summaries
                        WHERE event_name = :event_name
                          AND initiating_country = :country
                          AND id != :event_id
                        ORDER BY period_start DESC
                        LIMIT 5
                    """),
                    {
                        'event_name': event.event_name,
                        'country': event.initiating_country,
                        'event_id': event_id
                    }
                ).fetchall()

                context['related_events'] = [
                    {
                        'event_id': str(row[0]),
                        'period_type': row[1],
                        'period_start': row[2].isoformat(),
                        'period_end': row[3].isoformat(),
                        'total_documents': row[4]
                    }
                    for row in related
                ]

            return context

    def hybrid_search(
        self,
        query: str,
        search_events: bool = True,
        search_documents: bool = True,
        limit: int = 10,
        **filters
    ) -> Dict[str, List[Dict]]:
        """
        Perform hybrid search across both events and documents.

        Args:
            query: Natural language query
            search_events: Include event summaries in search
            search_documents: Include source documents in search
            limit: Maximum results per category
            **filters: Additional filters (country, start_date, end_date, etc.)

        Returns:
            Dictionary with separate lists for events and documents
        """
        results = {}

        if search_events:
            # Search across all event types
            event_results = []
            for period_type in ['daily', 'weekly', 'monthly']:
                period_results = self.search_event_summaries(
                    query,
                    period_type=period_type,
                    limit=limit // 3,
                    **filters
                )
                event_results.extend(period_results)

            # Sort by relevance
            event_results.sort(key=lambda x: x['relevance_score'])
            results['events'] = event_results[:limit]

        if search_documents:
            results['documents'] = self.search_documents(query, limit=limit, **filters)

        return results
