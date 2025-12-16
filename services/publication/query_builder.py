"""
Database query builder for publication generation.

Uses current database models (EventSummary, PeriodSummary, Document, etc.)
to fetch data needed for summary publications.
"""

from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import Session, joinedload

from shared.models.models import (
    Document,
    Category,
    Subcategory,
    InitiatingCountry,
    RecipientCountry,
    EventSummary,
    PeriodSummary,
    EventSourceLink,
    PeriodType,
    EventStatus
)


class PublicationQueryBuilder:
    """Builds queries for publication generation."""

    def __init__(self, session: Session):
        self.session = session

    def get_event_summaries(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        period_type: PeriodType = PeriodType.MONTHLY,
        categories: Optional[List[str]] = None
    ) -> List[EventSummary]:
        """
        Get event summaries for a specific country and date range.

        Args:
            initiating_country: Country initiating the activities
            start_date: Start of date range
            end_date: End of date range
            period_type: Type of period (daily, weekly, monthly, yearly)
            categories: Optional list of categories to filter by

        Returns:
            List of EventSummary objects
        """
        query = self.session.query(EventSummary).filter(
            EventSummary.initiating_country == initiating_country,
            EventSummary.period_type == period_type,
            EventSummary.period_start >= start_date,
            EventSummary.period_end <= end_date,
            EventSummary.status == EventStatus.ACTIVE,
            EventSummary.is_deleted == False
        )

        # Filter by categories if specified
        if categories:
            # Use JSONB containment check
            category_filters = []
            for category in categories:
                category_filters.append(
                    EventSummary.count_by_category[category].astext.cast(text('integer')) > 0
                )
            query = query.filter(or_(*category_filters))

        return query.order_by(
            EventSummary.period_start,
            EventSummary.total_documents_across_categories.desc()
        ).all()

    def get_period_summary(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        period_type: PeriodType = PeriodType.MONTHLY
    ) -> Optional[PeriodSummary]:
        """
        Get the period summary for a specific country and date range.

        Returns:
            PeriodSummary object or None if not found
        """
        return self.session.query(PeriodSummary).filter(
            PeriodSummary.initiating_country == initiating_country,
            PeriodSummary.period_type == period_type,
            PeriodSummary.period_start == start_date,
            PeriodSummary.period_end == end_date
        ).first()

    def get_documents_for_event(
        self,
        event_summary_id: str,
        limit: Optional[int] = None
    ) -> List[Document]:
        """
        Get source documents linked to an event summary.

        Args:
            event_summary_id: UUID of the event summary
            limit: Optional limit on number of documents

        Returns:
            List of Document objects with their metadata
        """
        query = self.session.query(Document).join(
            EventSourceLink,
            EventSourceLink.doc_id == Document.doc_id
        ).filter(
            EventSourceLink.event_summary_id == event_summary_id
        ).order_by(
            EventSourceLink.contribution_weight.desc().nullslast(),
            Document.date.desc()
        )

        if limit:
            query = query.limit(limit)

        return query.all()

    def get_documents_with_relationships(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        category: Optional[str] = None,
        recipient_countries: Optional[List[str]] = None
    ) -> List[Tuple]:
        """
        Get documents with their categories, countries, and other metadata.

        Returns:
            List of tuples: (Document, categories, initiating_countries, recipient_countries)
        """
        query = self.session.query(
            Document.doc_id,
            Document.date,
            Document.title,
            Document.distilled_text,
            Document.salience_justification,
            Document.source_name,
            Category.category
        ).join(
            Category, Document.doc_id == Category.doc_id
        ).join(
            InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id
        ).join(
            RecipientCountry, Document.doc_id == RecipientCountry.doc_id
        ).filter(
            Document.date.between(start_date, end_date),
            InitiatingCountry.initiating_country == initiating_country
        )

        if category:
            query = query.filter(Category.category == category)

        if recipient_countries:
            query = query.filter(RecipientCountry.recipient_country.in_(recipient_countries))

        return query.all()

    def get_metrics_by_country(
        self,
        start_date: date,
        end_date: date,
        category: Optional[str] = None,
        recipient_countries: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get document counts grouped by initiating country.

        Returns:
            List of dicts with initiating_country and num_docs
        """
        query = self.session.query(
            InitiatingCountry.initiating_country,
            func.count(func.distinct(Document.doc_id)).label("num_docs")
        ).join(
            Document, InitiatingCountry.doc_id == Document.doc_id
        ).filter(
            Document.date.between(start_date, end_date)
        )

        if category or recipient_countries:
            if category:
                query = query.join(
                    Category, Document.doc_id == Category.doc_id
                ).filter(Category.category == category)

            if recipient_countries:
                query = query.join(
                    RecipientCountry, Document.doc_id == RecipientCountry.doc_id
                ).filter(RecipientCountry.recipient_country.in_(recipient_countries))

        results = query.group_by(
            InitiatingCountry.initiating_country
        ).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).all()

        return [
            {"initiating_country": country, "num_docs": count}
            for country, count in results
        ]

    def get_metrics_by_recipient(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get document counts grouped by recipient country.

        Returns:
            List of dicts with recipient_country and num_docs
        """
        query = self.session.query(
            RecipientCountry.recipient_country,
            func.count(func.distinct(Document.doc_id)).label("num_docs")
        ).join(
            Document, RecipientCountry.doc_id == Document.doc_id
        ).join(
            InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id
        ).filter(
            Document.date.between(start_date, end_date),
            InitiatingCountry.initiating_country == initiating_country
        )

        if category:
            query = query.join(
                Category, Document.doc_id == Category.doc_id
            ).filter(Category.category == category)

        results = query.group_by(
            RecipientCountry.recipient_country
        ).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).all()

        return [
            {"recipient_country": country, "num_docs": count}
            for country, count in results
        ]

    def get_metrics_by_category(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        recipient_countries: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get document counts grouped by category.

        Returns:
            List of dicts with category and num_docs
        """
        query = self.session.query(
            Category.category,
            func.count(func.distinct(Document.doc_id)).label("num_docs")
        ).join(
            Document, Category.doc_id == Document.doc_id
        ).join(
            InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id
        ).filter(
            Document.date.between(start_date, end_date),
            InitiatingCountry.initiating_country == initiating_country
        )

        if recipient_countries:
            query = query.join(
                RecipientCountry, Document.doc_id == RecipientCountry.doc_id
            ).filter(RecipientCountry.recipient_country.in_(recipient_countries))

        results = query.group_by(
            Category.category
        ).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).all()

        return [
            {"category": category, "num_docs": count}
            for category, count in results
        ]

    def get_metrics_by_subcategory(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        category: Optional[str] = None,
        recipient_countries: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get document counts grouped by subcategory.

        Returns:
            List of dicts with subcategory and num_docs
        """
        query = self.session.query(
            Subcategory.subcategory,
            func.count(func.distinct(Document.doc_id)).label("num_docs")
        ).join(
            Document, Subcategory.doc_id == Document.doc_id
        ).join(
            InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id
        ).filter(
            Document.date.between(start_date, end_date),
            InitiatingCountry.initiating_country == initiating_country
        )

        if category:
            query = query.join(
                Category, Document.doc_id == Category.doc_id
            ).filter(Category.category == category)

        if recipient_countries:
            query = query.join(
                RecipientCountry, Document.doc_id == RecipientCountry.doc_id
            ).filter(RecipientCountry.recipient_country.in_(recipient_countries))

        results = query.group_by(
            Subcategory.subcategory
        ).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).all()

        return [
            {"subcategory": subcategory, "num_docs": count}
            for subcategory, count in results
        ]

    def get_weekly_metrics(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        category: Optional[str] = None,
        recipient_countries: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get document counts grouped by week.

        Returns:
            List of dicts with week_start and num_docs
        """
        query = self.session.query(
            func.date_trunc('week', Document.date).label("week_start"),
            func.count(func.distinct(Document.doc_id)).label("num_docs")
        ).join(
            InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
        ).filter(
            Document.date.between(start_date, end_date),
            InitiatingCountry.initiating_country == initiating_country
        )

        if category:
            query = query.join(
                Category, Document.doc_id == Category.doc_id
            ).filter(Category.category == category)

        if recipient_countries:
            query = query.join(
                RecipientCountry, Document.doc_id == RecipientCountry.doc_id
            ).filter(RecipientCountry.recipient_country.in_(recipient_countries))

        results = query.group_by("week_start").order_by("week_start").all()

        return [
            {"week_start": str(week_start), "num_docs": count}
            for week_start, count in results
        ]

    def get_daily_metrics(
        self,
        initiating_country: str,
        start_date: date,
        end_date: date,
        category: Optional[str] = None,
        recipient_countries: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get document counts grouped by day.

        Returns:
            List of dicts with day and num_docs
        """
        query = self.session.query(
            Document.date.label("day"),
            func.count(Document.doc_id).label("num_docs")
        ).join(
            InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
        ).filter(
            Document.date.between(start_date, end_date),
            InitiatingCountry.initiating_country == initiating_country
        )

        if category:
            query = query.join(
                Category, Document.doc_id == Category.doc_id
            ).filter(Category.category == category)

        if recipient_countries:
            query = query.join(
                RecipientCountry, Document.doc_id == RecipientCountry.doc_id
            ).filter(RecipientCountry.recipient_country.in_(recipient_countries))

        results = query.group_by(Document.date).order_by(Document.date).all()

        return [
            {"day": str(day), "num_docs": count}
            for day, count in results
        ]
