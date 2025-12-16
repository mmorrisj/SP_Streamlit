"""
AI-powered summary generation for publications.

Uses GPT models to generate titles, consolidate events, and create
narrative summaries from event data and documents.
"""

import os
import json
from typing import List, Dict, Any, Optional
from datetime import date, datetime

from shared.utils.utils import gai, fetch_gai_content


class SummaryGenerator:
    """Generates AI-powered summaries for publications."""

    def __init__(self, model: str = "gpt-4"):
        """
        Initialize summary generator.

        Args:
            model: GPT model to use for generation
        """
        self.model = model

    def generate_publication_title(
        self,
        event_summaries: List[Dict[str, Any]],
        start_date: date,
        end_date: date,
        max_words: int = 10
    ) -> str:
        """
        Generate a descriptive title for the publication.

        Args:
            event_summaries: List of event summary dicts
            start_date: Start of period
            end_date: End of period
            max_words: Maximum words in title

        Returns:
            Generated title string
        """
        sys_prompt = f"""Review the following summaries and create an appropriate descriptive title that captures the relevant content.

Requirements:
- Maximum {max_words} words
- No subjective language or qualifiers
- Reference the date range: {self._format_date_range(start_date, end_date)}
- Focus on major themes and events

Return only the title, no quotes or formatting."""

        # Prepare condensed summary data
        condensed_summaries = [
            {
                "event": s.get("event_name", ""),
                "overview": s.get("overview", "")[:200],  # First 200 chars
                "category": s.get("category", "")
            }
            for s in event_summaries
        ]

        user_prompt = json.dumps(condensed_summaries, indent=2)

        try:
            response = gai(sys_prompt=sys_prompt, user_prompt=user_prompt, model=self.model)
            title = response.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            return title.strip('"\'')  # Remove any quotes
        except Exception as e:
            print(f"Error generating title: {e}")
            return f"Summary Report: {self._format_date_range(start_date, end_date)}"

    def consolidate_duplicate_events(
        self,
        event_summaries: List[Dict[str, Any]],
        categories: List[str]
    ) -> Dict[str, List[str]]:
        """
        Use AI to identify and consolidate duplicate or related events.

        Args:
            event_summaries: List of event summary dicts
            categories: List of category names

        Returns:
            Dict mapping category -> list of event IDs to keep
        """
        # Organize events by category
        events_by_category = {cat: [] for cat in categories}

        for event in event_summaries:
            cat = event.get('category', '')
            if cat in events_by_category:
                events_by_category[cat].append({
                    'id': event.get('id', ''),
                    'event_name': event.get('event_name', ''),
                    'overview': event.get('overview', '')[:300]
                })

        sys_prompt = """Analyze the following events within each category and identify duplicates or highly overlapping events that should be consolidated.

Return a JSON object where:
- Keys are category names
- Values are arrays of event IDs that should be KEPT (excluding duplicates)

Format:
{
  "Economic": ["id1", "id2", "id3"],
  "Diplomacy": ["id4", "id5"],
  ...
}

Only return the JSON, no other text."""

        user_prompt = json.dumps(events_by_category, indent=2)

        try:
            response = gai(sys_prompt=sys_prompt, user_prompt=user_prompt, model=self.model)
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')

            # Try to parse JSON from response
            # Remove markdown code fences if present
            content = content.strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            content = content.strip()

            result = json.loads(content)
            return result
        except Exception as e:
            print(f"Error consolidating events: {e}")
            # Return all events if consolidation fails
            return {
                cat: [e.get('id') for e in events]
                for cat, events in events_by_category.items()
            }

    def identify_source_documents(
        self,
        event_summary: Dict[str, Any],
        documents: List[Dict[str, Any]],
        summary_text: str,
        max_sources: int = 10
    ) -> List[str]:
        """
        Use AI to identify which documents best support a summary.

        Args:
            event_summary: Event summary dict
            documents: List of candidate document dicts
            summary_text: The summary text to source
            max_sources: Maximum number of sources to return

        Returns:
            List of doc_ids that support the summary
        """
        sys_prompt = f"""Review the summary text and the list of documents. Identify which documents (by doc_id) best support and provide evidence for the summary.

Return ONLY a JSON array of doc_ids, maximum {max_sources} documents.

Example: ["doc123", "doc456", "doc789"]

Consider:
- Relevance to the summary content
- Specificity and detail
- Chronological relevance
- Source credibility"""

        # Prepare document data
        doc_data = [
            {
                "doc_id": d.get("doc_id", ""),
                "title": d.get("title", "")[:150],
                "date": str(d.get("date", "")),
                "distilled_text": d.get("distilled_text", "")[:300]
            }
            for d in documents[:50]  # Limit to first 50 to avoid token limits
        ]

        user_prompt = f"""EVENT: {event_summary.get('event_name', '')}

SUMMARY TEXT:
{summary_text[:500]}

CANDIDATE DOCUMENTS:
{json.dumps(doc_data, indent=2)}"""

        try:
            response = gai(sys_prompt=sys_prompt, user_prompt=user_prompt, model=self.model)
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')

            # Try to parse JSON array
            content = content.strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            content = content.strip()

            doc_ids = json.loads(content)
            if isinstance(doc_ids, list):
                return [str(doc_id).strip() for doc_id in doc_ids[:max_sources]]
            else:
                return []
        except Exception as e:
            print(f"Error identifying sources: {e}")
            # Return top documents by default
            return [d.get("doc_id", "") for d in documents[:max_sources]]

    def generate_event_narrative(
        self,
        event_name: str,
        documents: List[Dict[str, Any]],
        category: str
    ) -> Dict[str, str]:
        """
        Generate overview and outcome narratives for an event.

        Args:
            event_name: Name of the event
            documents: List of related document dicts
            category: Event category

        Returns:
            Dict with 'overview' and 'outcome' keys
        """
        sys_prompt = f"""You are a diplomatic analyst summarizing soft power activities.

Create a brief summary for the following {category} event based on the provided documents.

Provide two sections:
1. **Overview**: A concise description of what happened (2-3 sentences)
2. **Outcomes**: The results, implications, or consequences (2-3 sentences)

Use an objective, journalistic tone. Focus on facts and verifiable information.

Return as JSON:
{{
  "overview": "...",
  "outcome": "..."
}}"""

        # Prepare document excerpts
        doc_excerpts = []
        for doc in documents[:20]:  # Limit to 20 documents
            excerpt = {
                "date": str(doc.get("date", "")),
                "title": doc.get("title", ""),
                "text": doc.get("distilled_text", "")[:400]
            }
            doc_excerpts.append(excerpt)

        user_prompt = f"""EVENT: {event_name}

RELATED DOCUMENTS:
{json.dumps(doc_excerpts, indent=2)}"""

        try:
            response = gai(sys_prompt=sys_prompt, user_prompt=user_prompt, model=self.model)
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')

            # Parse JSON
            content = content.strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            content = content.strip()

            result = json.loads(content)
            return {
                "overview": result.get("overview", "No overview available."),
                "outcome": result.get("outcome", "No outcomes available.")
            }
        except Exception as e:
            print(f"Error generating narrative: {e}")
            return {
                "overview": "Information not available.",
                "outcome": "Information not available."
            }

    @staticmethod
    def _format_date_range(start_date: date, end_date: date) -> str:
        """Format a date range for display."""
        start_str = start_date.strftime("%B %Y")
        end_str = end_date.strftime("%B %Y")

        if start_str == end_str:
            return start_str
        else:
            return f"{start_str} to {end_str}"

    @staticmethod
    def _format_full_date_range(start_date: date, end_date: date) -> str:
        """Format a full date range with days."""
        start_str = start_date.strftime("%d %B %Y")
        end_str = end_date.strftime("%d %B %Y")
        return f"{start_str} to {end_str}"
