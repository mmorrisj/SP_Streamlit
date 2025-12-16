"""
Main publication service orchestrator.

Coordinates database queries, AI summary generation, and document building
to create comprehensive publication reports.
"""

import os
from datetime import date
from typing import List, Dict, Any, Optional
from pathlib import Path
from sqlalchemy.orm import Session

from shared.models.models import PeriodType
from shared.database.database import get_session
from services.publication.query_builder import PublicationQueryBuilder
from services.publication.summary_generator import SummaryGenerator
from services.publication.document_builder import DocumentBuilder


class PublicationService:
    """
    Main service for generating publication reports.

    This service:
    1. Queries event summaries and documents from the database
    2. Uses AI to consolidate events and generate narratives
    3. Identifies source documents for each section
    4. Builds both reviewer and summary Word documents
    """

    def __init__(
        self,
        session: Session,
        template_path: str,
        output_dir: str,
        image_path: Optional[str] = None,
        model: str = "gpt-4"
    ):
        """
        Initialize publication service.

        Args:
            session: Database session
            template_path: Path to Word template file
            output_dir: Directory for output files
            image_path: Optional path to atom.png for hyperlinks
            model: GPT model for AI generation
        """
        self.session = session
        self.query_builder = PublicationQueryBuilder(session)
        self.summary_generator = SummaryGenerator(model=model)
        self.document_builder = DocumentBuilder(template_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.image_path = image_path

    def generate_publication(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        categories: List[str],
        recipient_countries: Optional[List[str]] = None,
        period_type: PeriodType = PeriodType.MONTHLY,
        use_existing_summaries: bool = True,
        max_sources_per_section: int = 10
    ) -> Dict[str, str]:
        """
        Generate a complete publication report.

        Args:
            initiating_country: Country initiating activities
            start_date: Start of period
            end_date: End of period
            categories: List of categories to include
            recipient_countries: Optional list of recipient countries to filter
            period_type: Type of period aggregation
            use_existing_summaries: Use existing EventSummary data if available
            max_sources_per_section: Maximum source documents per section

        Returns:
            Dict with paths to generated files:
            {
                'reviewer_version': '/path/to/reviewer.docx',
                'summary_version': '/path/to/summary.docx',
                'metadata': '/path/to/metadata.json'
            }
        """
        print(f"Generating publication for {initiating_country}: {start_date} to {end_date}")

        # Step 1: Fetch event summaries from database
        print("Fetching event summaries...")
        event_summaries = self._fetch_event_summaries(
            initiating_country,
            start_date,
            end_date,
            categories,
            period_type,
            use_existing_summaries
        )

        if not event_summaries:
            print("No event summaries found. Consider generating EventSummary data first.")
            return {}

        print(f"Found {len(event_summaries)} event summaries")

        # Step 2: Organize events by category
        events_by_category = self._organize_events_by_category(event_summaries, categories)

        # Step 3: Consolidate duplicate events (optional)
        print("Consolidating duplicate events...")
        consolidated_events = self.summary_generator.consolidate_duplicate_events(
            event_summaries,
            categories
        )

        # Filter events based on consolidation
        events_by_category = self._filter_consolidated_events(
            events_by_category,
            consolidated_events
        )

        # Step 4: Fetch and attach source documents for each event
        print("Fetching source documents...")
        events_by_category = self._attach_source_documents(
            events_by_category,
            max_sources_per_section
        )

        # Step 5: Generate publication title
        print("Generating publication title...")
        all_events = []
        for events in events_by_category.values():
            all_events.extend(events)

        title = self.summary_generator.generate_publication_title(
            all_events,
            start_date,
            end_date
        )

        # Step 6: Build documents
        print("Building Word documents...")
        filename_base = f"{initiating_country}_{start_date}_{end_date}"

        reviewer_path = str(self.output_dir / f"{filename_base}_Reviewer.docx")
        summary_path = str(self.output_dir / f"{filename_base}_Summary.docx")

        # Build reviewer version
        print("Creating reviewer version...")
        self.document_builder.build_reviewer_version(
            output_path=reviewer_path,
            country=initiating_country,
            start_date=start_date,
            end_date=end_date,
            title=title,
            events_by_category=events_by_category,
            categories=categories,
            image_path=self.image_path
        )

        # Build summary version
        print("Creating summary version...")
        self.document_builder.build_summary_version(
            output_path=summary_path,
            country=initiating_country,
            start_date=start_date,
            end_date=end_date,
            title=title,
            events_by_category=events_by_category,
            categories=categories
        )

        print(f"✅ Publication generated successfully!")
        print(f"   Reviewer version: {reviewer_path}")
        print(f"   Summary version: {summary_path}")

        return {
            'reviewer_version': reviewer_path,
            'summary_version': summary_path,
            'title': title
        }

    def _fetch_event_summaries(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        categories: List[str],
        period_type: PeriodType,
        use_existing: bool
    ) -> List[Dict[str, Any]]:
        """Fetch event summaries from database or generate new ones."""
        event_summaries = []

        if use_existing:
            # Try to fetch existing EventSummary records
            db_summaries = self.query_builder.get_event_summaries(
                initiating_country=initiating_country,
                start_date=start_date,
                end_date=end_date,
                period_type=period_type,
                categories=categories
            )

            for es in db_summaries:
                # Extract category from count_by_category (get primary category)
                primary_category = None
                if es.count_by_category:
                    primary_category = max(
                        es.count_by_category.items(),
                        key=lambda x: x[1]
                    )[0]

                event_dict = {
                    'id': str(es.id),
                    'event_name': es.event_name,
                    'category': primary_category or 'Unknown',
                    'overview': es.narrative_summary.get('overview', '') if es.narrative_summary else '',
                    'outcome': es.narrative_summary.get('outcome', '') if es.narrative_summary else '',
                    'period_start': es.period_start,
                    'period_end': es.period_end,
                    'total_documents': es.total_unique_documents,
                    'overview_sources': [],
                    'outcome_sources': [],
                    'overview_citations': [],
                    'outcome_citations': []
                }
                event_summaries.append(event_dict)

        return event_summaries

    def _organize_events_by_category(
        self,
        event_summaries: List[Dict[str, Any]],
        categories: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Organize events by category."""
        events_by_category = {cat: [] for cat in categories}

        for event in event_summaries:
            category = event.get('category', 'Unknown')
            if category in events_by_category:
                events_by_category[category].append(event)

        return events_by_category

    def _filter_consolidated_events(
        self,
        events_by_category: Dict[str, List[Dict[str, Any]]],
        consolidated_events: Dict[str, List[str]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Filter events based on consolidation results."""
        filtered = {}

        for category, events in events_by_category.items():
            keep_ids = set(consolidated_events.get(category, []))
            if keep_ids:
                # Keep only events in the keep_ids set
                filtered[category] = [
                    e for e in events if e.get('id') in keep_ids
                ]
            else:
                # If no consolidation info, keep all
                filtered[category] = events

        return filtered

    def _attach_source_documents(
        self,
        events_by_category: Dict[str, List[Dict[str, Any]]],
        max_sources: int
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch and attach source documents to each event."""
        for category, events in events_by_category.items():
            for event in events:
                event_id = event.get('id')
                if not event_id:
                    continue

                # Fetch source documents
                documents = self.query_builder.get_documents_for_event(
                    event_summary_id=event_id,
                    limit=50  # Get more than needed for AI selection
                )

                doc_dicts = [
                    {
                        'doc_id': d.doc_id,
                        'title': d.title,
                        'date': d.date,
                        'distilled_text': d.distilled_text,
                        'source_name': d.source_name
                    }
                    for d in documents
                ]

                # Use AI to identify sources for overview
                overview_text = event.get('overview', '')
                if overview_text:
                    overview_doc_ids = self.summary_generator.identify_source_documents(
                        event_summary=event,
                        documents=doc_dicts,
                        summary_text=overview_text,
                        max_sources=max_sources
                    )
                    event['overview_sources'] = overview_doc_ids
                    event['overview_citations'] = self._format_citations(
                        overview_doc_ids,
                        doc_dicts
                    )
                    event['overview_hyperlink'] = DocumentBuilder.build_hyperlink(
                        overview_doc_ids
                    )

                # Use AI to identify sources for outcome
                outcome_text = event.get('outcome', '')
                if outcome_text:
                    outcome_doc_ids = self.summary_generator.identify_source_documents(
                        event_summary=event,
                        documents=doc_dicts,
                        summary_text=outcome_text,
                        max_sources=max_sources
                    )
                    event['outcome_sources'] = outcome_doc_ids
                    event['outcome_citations'] = self._format_citations(
                        outcome_doc_ids,
                        doc_dicts
                    )
                    event['outcome_hyperlink'] = DocumentBuilder.build_hyperlink(
                        outcome_doc_ids
                    )

        return events_by_category

    @staticmethod
    def _format_citations(doc_ids: List[str], documents: List[Dict[str, Any]]) -> List[str]:
        """Format document citations for display."""
        citations = []

        # Create lookup dict
        doc_lookup = {d['doc_id']: d for d in documents}

        for doc_id in doc_ids:
            doc = doc_lookup.get(doc_id)
            if doc:
                # Format: [doc_id] Title - Source, Date
                citation = f"[{doc_id}] {doc.get('title', 'No title')} - {doc.get('source_name', 'Unknown')}, {doc.get('date', 'Unknown date')}"
                citations.append(citation)
            else:
                citations.append(f"[{doc_id}] Document not found")

        return citations


def create_publication_service(
    template_path: str,
    output_dir: str,
    image_path: Optional[str] = None,
    model: str = "gpt-4"
) -> PublicationService:
    """
    Factory function to create a PublicationService with a database session.

    Args:
        template_path: Path to Word template
        output_dir: Directory for output files
        image_path: Optional path to atom.png
        model: GPT model for AI generation

    Returns:
        Configured PublicationService instance
    """
    session = next(get_session())
    return PublicationService(
        session=session,
        template_path=template_path,
        output_dir=output_dir,
        image_path=image_path,
        model=model
    )
