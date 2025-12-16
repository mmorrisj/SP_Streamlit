"""
Generate EventSummary records from processed documents and events.

This pipeline creates the EventSummary records needed for publication generation by:
1. Clustering documents by event, date, and country
2. Generating AI narratives (overview and outcome)
3. Creating EventSourceLink relationships
4. Populating aggregated statistics

Usage:
    python services/pipeline/events/generate_event_summaries.py --start 2024-10-01 --end 2024-10-31 --country China
    python services/pipeline/events/generate_event_summaries.py --start 2024-10-01 --end 2024-10-31  # All countries
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from pathlib import Path
import uuid

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import func, and_, text
from sqlalchemy.orm import Session

from shared.database.database import get_session
from shared.models.models import (
    Document,
    Category,
    Subcategory,
    InitiatingCountry,
    RecipientCountry,
    RawEvent,
    EventSummary,
    EventSourceLink,
    PeriodSummary,
    PeriodType,
    EventStatus
)
from shared.utils.utils import Config, gai, fetch_gai_content
from shared.utils.prompts import event_summary_prompt


class EventSummaryGenerator:
    """Generates EventSummary records from documents."""

    def __init__(self, session: Session, config: Config):
        self.session = session
        self.config = config

    def generate_event_summaries(
        self,
        start_date: date,
        end_date: date,
        country: str,
        period_type: PeriodType = PeriodType.MONTHLY,
        min_docs_per_event: int = 2
    ) -> List[EventSummary]:
        """
        Generate EventSummary records for a date range and country.

        Args:
            start_date: Start of period
            end_date: End of period
            country: Initiating country
            period_type: Period type (daily, weekly, monthly, yearly)
            min_docs_per_event: Minimum documents to create an event summary

        Returns:
            List of created EventSummary objects
        """
        print(f"\n{'='*80}")
        print(f"GENERATING EVENT SUMMARIES")
        print(f"{'='*80}")
        print(f"Country: {country}")
        print(f"Period: {start_date} to {end_date}")
        print(f"Period Type: {period_type.value}")
        print(f"Min docs per event: {min_docs_per_event}")
        print(f"{'='*80}\n")

        # Step 1: Get all events with documents for this period
        event_clusters = self._cluster_events_by_name(
            start_date,
            end_date,
            country,
            min_docs_per_event
        )

        if not event_clusters:
            print("⚠️  No events found with sufficient documents")
            return []

        print(f"Found {len(event_clusters)} events with sufficient documents\n")

        # Step 2: Create EventSummary for each cluster
        event_summaries = []
        for i, (event_name, doc_ids) in enumerate(event_clusters.items(), 1):
            print(f"[{i}/{len(event_clusters)}] Processing: {event_name}")
            print(f"  Documents: {len(doc_ids)}")

            try:
                event_summary = self._create_event_summary(
                    event_name=event_name,
                    doc_ids=doc_ids,
                    start_date=start_date,
                    end_date=end_date,
                    country=country,
                    period_type=period_type
                )

                if event_summary:
                    event_summaries.append(event_summary)
                    print(f"  ✅ EventSummary created: {event_summary.id}")
                else:
                    print(f"  ⚠️  Skipped (already exists or error)")

            except Exception as e:
                print(f"  ❌ Error: {e}")
                continue

        # Commit all
        self.session.commit()

        print(f"\n{'='*80}")
        print(f"✅ COMPLETED: Created {len(event_summaries)} event summaries")
        print(f"{'='*80}\n")

        return event_summaries

    def _cluster_events_by_name(
        self,
        start_date: date,
        end_date: date,
        country: str,
        min_docs: int
    ) -> Dict[str, List[str]]:
        """
        Cluster documents by event name.

        Returns:
            Dict mapping event_name -> list of doc_ids
        """
        print("Clustering documents by event name...")

        # Query: Get all documents with event names for this period/country
        query = self.session.query(
            RawEvent.event_name,
            Document.doc_id
        ).join(
            Document, RawEvent.doc_id == Document.doc_id
        ).join(
            InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id
        ).filter(
            Document.date.between(start_date, end_date),
            InitiatingCountry.initiating_country == country,
            RawEvent.event_name.isnot(None),
            RawEvent.event_name != ''
        )

        results = query.all()

        # Cluster by event name
        clusters = defaultdict(list)
        for event_name, doc_id in results:
            # Normalize event name
            normalized = event_name.strip()
            clusters[normalized].append(doc_id)

        # Filter by minimum document count
        filtered_clusters = {
            event_name: list(set(doc_ids))  # Deduplicate
            for event_name, doc_ids in clusters.items()
            if len(set(doc_ids)) >= min_docs
        }

        print(f"  Found {len(results)} document-event pairs")
        print(f"  Clustered into {len(clusters)} unique events")
        print(f"  After filtering (min {min_docs} docs): {len(filtered_clusters)} events\n")

        return filtered_clusters

    def _create_event_summary(
        self,
        event_name: str,
        doc_ids: List[str],
        start_date: date,
        end_date: date,
        country: str,
        period_type: PeriodType
    ) -> Optional[EventSummary]:
        """
        Create an EventSummary record for a single event.

        Returns:
            EventSummary object or None if already exists/error
        """
        # Check if already exists
        existing = self.session.query(EventSummary).filter(
            EventSummary.event_name == event_name,
            EventSummary.initiating_country == country,
            EventSummary.period_type == period_type,
            EventSummary.period_start == start_date,
            EventSummary.period_end == end_date
        ).first()

        if existing:
            print(f"  ℹ️  EventSummary already exists: {existing.id}")
            return None

        # Fetch documents
        documents = self.session.query(Document).filter(
            Document.doc_id.in_(doc_ids)
        ).all()

        if not documents:
            print(f"  ⚠️  No documents found")
            return None

        # Get date range from documents
        doc_dates = [d.date for d in documents if d.date]
        first_date = min(doc_dates) if doc_dates else start_date
        last_date = max(doc_dates) if doc_dates else end_date

        # Calculate aggregated statistics
        stats = self._calculate_event_statistics(documents)

        # Generate AI narrative
        narrative = self._generate_event_narrative(
            event_name,
            documents,
            stats['primary_category']
        )

        # Create EventSummary
        event_summary = EventSummary(
            id=str(uuid.uuid4()),
            period_type=period_type,
            period_start=start_date,
            period_end=end_date,
            event_name=event_name,
            initiating_country=country,
            first_observed_date=first_date,
            last_observed_date=last_date,
            status=EventStatus.ACTIVE,
            narrative_summary=narrative,
            count_by_category=stats['count_by_category'],
            count_by_subcategory=stats['count_by_subcategory'],
            count_by_recipient=stats['count_by_recipient'],
            count_by_source=stats['count_by_source']
        )

        # Update counts
        event_summary.update_basic_counts()

        # Add to session
        self.session.add(event_summary)
        self.session.flush()  # Get the ID

        # Create EventSourceLink records
        self._create_source_links(event_summary.id, doc_ids)

        return event_summary

    def _calculate_event_statistics(
        self,
        documents: List[Document]
    ) -> Dict[str, Any]:
        """Calculate aggregated statistics for an event."""
        stats = {
            'count_by_category': {},
            'count_by_subcategory': {},
            'count_by_recipient': {},
            'count_by_source': {},
            'primary_category': None
        }

        doc_ids = [d.doc_id for d in documents]

        # Categories
        categories = self.session.query(
            Category.category,
            func.count(Category.doc_id).label('count')
        ).filter(
            Category.doc_id.in_(doc_ids)
        ).group_by(Category.category).all()

        for cat, count in categories:
            stats['count_by_category'][cat] = count

        # Determine primary category
        if categories:
            stats['primary_category'] = max(categories, key=lambda x: x[1])[0]

        # Subcategories
        subcategories = self.session.query(
            Subcategory.subcategory,
            func.count(Subcategory.doc_id).label('count')
        ).filter(
            Subcategory.doc_id.in_(doc_ids)
        ).group_by(Subcategory.subcategory).all()

        for subcat, count in subcategories:
            stats['count_by_subcategory'][subcat] = count

        # Recipients
        recipients = self.session.query(
            RecipientCountry.recipient_country,
            func.count(RecipientCountry.doc_id).label('count')
        ).filter(
            RecipientCountry.doc_id.in_(doc_ids)
        ).group_by(RecipientCountry.recipient_country).all()

        for recipient, count in recipients:
            stats['count_by_recipient'][recipient] = count

        # Sources
        for doc in documents:
            if doc.source_name:
                stats['count_by_source'][doc.source_name] = \
                    stats['count_by_source'].get(doc.source_name, 0) + 1

        return stats

    def _generate_event_narrative(
        self,
        event_name: str,
        documents: List[Document],
        category: str
    ) -> Dict[str, str]:
        """
        Generate overview and outcome narratives using AI.

        Returns:
            Dict with 'overview' and 'outcome' keys
        """
        print(f"  Generating AI narrative...")

        # Prepare document excerpts
        doc_excerpts = []
        for doc in documents[:20]:  # Limit to 20 documents
            excerpt = {
                "date": str(doc.date) if doc.date else "Unknown",
                "title": doc.title or "No title",
                "text": (doc.distilled_text or "")[:400]  # First 400 chars
            }
            doc_excerpts.append(excerpt)

        sys_prompt = f"""You are a diplomatic analyst summarizing soft power activities.

Create a brief summary for the following {category} event based on the provided documents.

Provide two sections:
1. **Overview**: A concise description of what happened (2-3 sentences)
2. **Outcome**: The results, implications, or consequences (2-3 sentences)

Use an objective, journalistic tone. Focus on facts and verifiable information.

Return as JSON:
{{
  "overview": "...",
  "outcome": "..."
}}"""

        user_prompt = f"""EVENT: {event_name}

RELATED DOCUMENTS:
{doc_excerpts}"""

        try:
            response = gai(sys_prompt=sys_prompt, user_prompt=str(doc_excerpts), model="gpt-4")
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')

            # Parse JSON
            content = content.strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            content = content.strip()

            import json
            result = json.loads(content)

            narrative = {
                "overview": result.get("overview", "Information not available."),
                "outcome": result.get("outcome", "Information not available.")
            }

            print(f"  ✅ Narrative generated")
            return narrative

        except Exception as e:
            print(f"  ⚠️  AI generation failed: {e}")
            return {
                "overview": f"Event involving {event_name}.",
                "outcome": "Further analysis required."
            }

    def _create_source_links(
        self,
        event_summary_id: str,
        doc_ids: List[str]
    ):
        """Create EventSourceLink records."""
        for doc_id in doc_ids:
            link = EventSourceLink(
                id=str(uuid.uuid4()),
                event_summary_id=event_summary_id,
                doc_id=doc_id
            )
            self.session.add(link)


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def main():
    parser = argparse.ArgumentParser(
        description="Generate EventSummary records for publications",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--start',
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end',
        required=True,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--country',
        help='Specific country to process (optional, processes all if not specified)'
    )
    parser.add_argument(
        '--period-type',
        default='monthly',
        choices=['daily', 'weekly', 'monthly', 'yearly'],
        help='Period aggregation type (default: monthly)'
    )
    parser.add_argument(
        '--min-docs',
        type=int,
        default=2,
        help='Minimum documents per event (default: 2)'
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = parse_date(args.start)
        end_date = parse_date(args.end)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Validate
    if start_date > end_date:
        print("Error: Start date must be before or equal to end date")
        sys.exit(1)

    # Parse period type
    period_type_map = {
        'daily': PeriodType.DAILY,
        'weekly': PeriodType.WEEKLY,
        'monthly': PeriodType.MONTHLY,
        'yearly': PeriodType.YEARLY
    }
    period_type = period_type_map[args.period_type]

    # Load config
    config = Config.from_yaml()

    # Determine countries
    if args.country:
        if args.country not in config.influencers:
            print(f"Error: Country '{args.country}' not in config")
            print(f"Available: {', '.join(config.influencers)}")
            sys.exit(1)
        countries = [args.country]
    else:
        countries = config.influencers

    # Process each country
    total_summaries = 0

    with get_session() as session:
        generator = EventSummaryGenerator(session, config)

        for country in countries:
            summaries = generator.generate_event_summaries(
                start_date=start_date,
                end_date=end_date,
                country=country,
                period_type=period_type,
                min_docs_per_event=args.min_docs
            )
            total_summaries += len(summaries)

    print(f"\n{'='*80}")
    print(f"✅ PIPELINE COMPLETED")
    print(f"{'='*80}")
    print(f"Total EventSummary records created: {total_summaries}")
    print(f"Countries processed: {', '.join(countries)}")
    print(f"\nYou can now run the publication generation:")
    print(f"  python services/publication/generate_publication.py \\")
    print(f"    --country {countries[0]} \\")
    print(f"    --start {args.start} \\")
    print(f"    --end {args.end}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
