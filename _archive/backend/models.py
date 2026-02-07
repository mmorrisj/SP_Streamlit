import uuid
from datetime import datetime
from datetime import date as DateType
from typing import List, Dict, Optional, Any
from enum import Enum as PyEnum

# Core SQLAlchemy imports
from sqlalchemy import (
    Column, Integer, String, Text, Date, Float, BigInteger, 
    DateTime, Boolean, ForeignKey, UniqueConstraint, Index,
    PrimaryKeyConstraint, func, Enum, CheckConstraint
)

# PostgreSQL-specific types
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB

# Modern SQLAlchemy 2.0 ORM imports
from sqlalchemy.orm import relationship, Mapped, mapped_column, validates

# Import Base from your database module
from backend.database import Base

# Enums for the consolidated EventSummary model
class PeriodType(PyEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"

class EventStatus(PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"

class Document(Base):
    """
    Core document model - converted from Flask-SQLAlchemy to pure SQLAlchemy.
    
    Changes made:
    - Replaced db.Model with Base
    - Added type hints with Mapped[]
    - Used mapped_column() instead of db.Column()
    - Added proper __repr__ method
    - Added relationship to Salience
    """
    __tablename__ = 'documents'
    
    # Primary key
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    
    # Core document metadata  
    title: Mapped[Optional[str]] = mapped_column(Text)
    source_name: Mapped[Optional[str]] = mapped_column(Text)
    source_geofocus: Mapped[Optional[str]] = mapped_column(Text)
    source_consumption: Mapped[Optional[str]] = mapped_column(Text)
    source_description: Mapped[Optional[str]] = mapped_column(Text)
    source_medium: Mapped[Optional[str]] = mapped_column(Text)
    source_location: Mapped[Optional[str]] = mapped_column(Text)
    source_editorial: Mapped[Optional[str]] = mapped_column(Text)
    
    # Temporal data
    date: Mapped[Optional[DateType]] = mapped_column(Date)
    
    # Processing metadata
    collection_name: Mapped[Optional[str]] = mapped_column(Text)
    gai_engine: Mapped[Optional[str]] = mapped_column(Text)
    gai_promptid: Mapped[Optional[str]] = mapped_column(Text)
    gai_promptversion: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Analysis results 
    salience: Mapped[Optional[str]] = mapped_column(Text)
    salience_justification: Mapped[Optional[str]] = mapped_column(Text)
    salience_bool: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    category_justification: Mapped[Optional[str]] = mapped_column(Text)
    subcategory: Mapped[Optional[str]] = mapped_column(Text)
    
    # Geographic and relational data
    initiating_country: Mapped[Optional[str]] = mapped_column(Text)
    recipient_country: Mapped[Optional[str]] = mapped_column(Text)
    _projects: Mapped[Optional[str]] = mapped_column(Text)
    lat_long: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)
    
    # Financial data
    monetary_commitment: Mapped[Optional[str]] = mapped_column(Text)
    
    # Content
    distilled_text: Mapped[Optional[str]] = mapped_column(Text)
    event_name: Mapped[Optional[str]] = mapped_column(Text)
    project_name: Mapped[Optional[str]] = mapped_column(Text)  # Legacy field from old schema, consolidates into event_name

    # Relationships - Add as we convert each model
    # Removed salience_score relationship - field moved directly into Document
    categories = relationship("Category", back_populates="document", lazy="dynamic")
    subcategories = relationship("Subcategory", back_populates="document", lazy="dynamic")
    initiating_countries = relationship("InitiatingCountry", back_populates="document", lazy="dynamic")
    recipient_countries = relationship("RecipientCountry", back_populates="document", lazy="dynamic")
    raw_events = relationship("RawEvent", back_populates="document", lazy="dynamic")

    # Link to event summaries through EventSourceLink
    event_source_links = relationship("EventSourceLink", back_populates="document", lazy="dynamic")

    @property
    def projects(self) -> str:
        """
        Return projects value. This is now stored separately from event_name.
        """
        return getattr(self, '_projects', '') or ''

    @projects.setter
    def projects(self, value: str):
        """Store the projects value separately."""
        self._projects = value

    def __repr__(self) -> str:
        return f"<Document(doc_id='{self.doc_id}', title='{self.title}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary for API serialization."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

# Normalized relationship tables for DSR flattening process
class Category(Base):
    """
    Document categories - many-to-many relationship with documents.
    
    Proper design: Separate table needed because documents can have multiple categories
    and categories can apply to multiple documents.
    
    Changes from Flask-SQLAlchemy:
    - Explicit composite primary key definition
    - Proper relationship with back_populates
    - Type hints for all fields
    """
    __tablename__ = 'categories'
    
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    category: Mapped[str] = mapped_column(Text, primary_key=True)
    
    # Bidirectional relationship for easier querying
    document = relationship("Document", back_populates="categories")
    
    def __repr__(self) -> str:
        return f"<Category(doc_id='{self.doc_id}', category='{self.category}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class Subcategory(Base):
    """
    Document subcategories - many-to-many relationship with documents.
    """
    __tablename__ = 'subcategories'
    
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    subcategory: Mapped[str] = mapped_column(Text, primary_key=True)
    
    # Bidirectional relationship for easier querying
    document = relationship("Document", back_populates="subcategories")
    
    def __repr__(self) -> str:
        return f"<Subcategory(doc_id='{self.doc_id}', subcategory='{self.subcategory}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class InitiatingCountry(Base):
    """
    Countries that initiate soft power activities - many-to-many with documents.
    """
    __tablename__ = 'initiating_countries'
    
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    initiating_country: Mapped[str] = mapped_column(Text, primary_key=True)
    
    # Bidirectional relationship for easier querying
    document = relationship("Document", back_populates="initiating_countries")
    
    def __repr__(self) -> str:
        return f"<InitiatingCountry(doc_id='{self.doc_id}', country='{self.initiating_country}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class RecipientCountry(Base):
    """
    Countries that receive soft power activities - many-to-many with documents.
    """
    __tablename__ = 'recipient_countries'
    
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    recipient_country: Mapped[str] = mapped_column(Text, primary_key=True)
    
    # Bidirectional relationship for easier querying
    document = relationship("Document", back_populates="recipient_countries")
    
    def __repr__(self) -> str:
        return f"<RecipientCountry(doc_id='{self.doc_id}', country='{self.recipient_country}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class RawEvent(Base):
    """
    Raw events associated with documents - many-to-many relationship.

    This model handles the flattening of event_name fields that can contain multiple
    semicolon-separated values in a single document.
    """
    __tablename__ = 'raw_events'

    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    event_name: Mapped[str] = mapped_column(Text, primary_key=True)

    # Bidirectional relationship for easier querying
    document = relationship("Document", back_populates="raw_events")

    def __repr__(self) -> str:
        return f"<RawEvent(doc_id='{self.doc_id}', event_name='{self.event_name}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}



class EventSummary(Base):
    """
    Replaces separate Daily/Weekly/Monthly/YearlyEvent tables.
    Consolidated event summary model with period-based aggregation.
    """
    __tablename__ = "event_summaries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Time period classification
    period_type: Mapped[PeriodType] = mapped_column(Enum(PeriodType), nullable=False)
    period_start: Mapped[DateType] = mapped_column(Date, nullable=False)
    period_end: Mapped[DateType] = mapped_column(Date, nullable=False)

    # Core event data
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    initiating_country: Mapped[str] = mapped_column(Text, nullable=False)
    first_observed_date: Mapped[DateType] = mapped_column(Date, nullable=False)
    last_observed_date: Mapped[DateType] = mapped_column(Date, nullable=False)

    # Status and lifecycle
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.ACTIVE, nullable=False)

    # Link to parent period summary
    period_summary_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("period_summaries.id", ondelete="CASCADE"),
        nullable=True
    )

    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by: Mapped[Optional[str]] = mapped_column(String(255))

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Count columns for fast queries
    category_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subcategory_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Total document counts across dimensions
    total_documents_across_categories: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_documents_across_subcategories: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_documents_across_recipients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_documents_across_sources: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # JSONB columns for detailed breakdowns
    count_by_category: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    count_by_subcategory: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    count_by_recipient: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    count_by_source: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    period_summary = relationship("PeriodSummary", back_populates="events")
    source_links = relationship(
        "EventSourceLink",
        back_populates="event_summary",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Unique constraint prevents duplicates within time periods
        UniqueConstraint(
            "period_type", "period_start", "period_end",
            "initiating_country", "event_name",
            name="uq_event_summary_period"
        ),
        # Performance indexes for common queries
        Index("ix_event_summary_country_period", "initiating_country", "period_type", "period_start"),
        Index("ix_event_summary_name", "event_name"),
        Index("ix_event_summary_dates", "first_observed_date", "last_observed_date"),
        Index("ix_event_summary_status", "status", "is_deleted"),
        # JSONB indexes for efficient queries
        Index("ix_event_summary_category_jsonb", "count_by_category", postgresql_using="gin"),
        Index("ix_event_summary_source_jsonb", "count_by_source", postgresql_using="gin"),
        # Ensure logical date consistency
        CheckConstraint("period_start <= period_end", name="ck_valid_period"),
        CheckConstraint("first_observed_date <= last_observed_date", name="ck_valid_observation"),
        # Ensure count consistency
        CheckConstraint("category_count >= 0", name="ck_positive_category_count"),
        CheckConstraint("source_count >= 0", name="ck_positive_source_count"),
    )

    @validates('event_name')
    def validate_event_name(self, key, value):
        if not value or len(value.strip()) < 3:
            raise ValueError("Event name must be at least 3 characters")
        return value.strip()

    @property
    def categories_list(self) -> List[str]:
        """Get list of categories from JSONB"""
        return list(self.count_by_category.keys()) if self.count_by_category else []

    @property
    def subcategories_list(self) -> List[str]:
        """Get list of subcategories from JSONB"""
        return list(self.count_by_subcategory.keys()) if self.count_by_subcategory else []

    @property
    def recipients_list(self) -> List[str]:
        """Get list of recipient countries from JSONB"""
        return list(self.count_by_recipient.keys()) if self.count_by_recipient else []

    @property
    def sources_list(self) -> List[str]:
        """Get list of news sources from JSONB"""
        return list(self.count_by_source.keys()) if self.count_by_source else []

    @property
    def is_active(self) -> bool:
        """Check if event is active and not deleted"""
        return self.status == EventStatus.ACTIVE and not self.is_deleted

    @property
    def total_unique_documents(self) -> int:
        """
        Get the maximum document count across all dimensions
        (since a document can be in multiple categories but should only be counted once)
        """
        return max(
            self.total_documents_across_categories,
            self.total_documents_across_subcategories,
            self.total_documents_across_recipients,
            self.total_documents_across_sources,
            0
        )

    def update_basic_counts(self):
        """Update simple count fields from existing JSONB data"""
        # Categories
        if self.count_by_category:
            self.category_count = len(self.count_by_category)
            self.total_documents_across_categories = sum(
                count for count in self.count_by_category.values()
                if isinstance(count, int)
            )
        else:
            self.category_count = 0
            self.total_documents_across_categories = 0

        # Subcategories
        if self.count_by_subcategory:
            self.subcategory_count = len(self.count_by_subcategory)
            self.total_documents_across_subcategories = sum(
                count for count in self.count_by_subcategory.values()
                if isinstance(count, int)
            )
        else:
            self.subcategory_count = 0
            self.total_documents_across_subcategories = 0

        # Recipients
        if self.count_by_recipient:
            self.recipient_count = len(self.count_by_recipient)
            self.total_documents_across_recipients = sum(
                count for count in self.count_by_recipient.values()
                if isinstance(count, int)
            )
        else:
            self.recipient_count = 0
            self.total_documents_across_recipients = 0

        # Sources
        if self.count_by_source:
            self.source_count = len(self.count_by_source)
            self.total_documents_across_sources = sum(
                count for count in self.count_by_source.values()
                if isinstance(count, int)
            )
        else:
            self.source_count = 0
            self.total_documents_across_sources = 0

    def get_category_percentage_breakdown(self) -> dict:
        """Get percentage breakdown of documents by category"""
        if not self.count_by_category or self.total_documents_across_categories == 0:
            return {}

        return {
            category: round((count / self.total_documents_across_categories) * 100, 1)
            for category, count in self.count_by_category.items()
        }

    def get_top_sources(self, limit: int = 5) -> List[tuple]:
        """Get top N sources by document count"""
        if not self.count_by_source:
            return []

        return sorted(
            self.count_by_source.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]

    def soft_delete(self, deleted_by: Optional[str] = None):
        """Soft delete the event and related data"""
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()
        if deleted_by:
            self.created_by = deleted_by  # Track who deleted it

    def __repr__(self):
        return f"<EventSummary(id={self.id}, event_name='{self.event_name}', period_type={self.period_type}, country='{self.initiating_country}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class PeriodSummary(Base):
    """
    Aggregated summaries for time periods across all events.
    """
    __tablename__ = "period_summaries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_type: Mapped[PeriodType] = mapped_column(Enum(PeriodType), nullable=False)
    period_start: Mapped[DateType] = mapped_column(Date, nullable=False)
    period_end: Mapped[DateType] = mapped_column(Date, nullable=False)
    initiating_country: Mapped[str] = mapped_column(Text, nullable=False)

    # Aggregated text summaries
    overview: Mapped[Optional[str]] = mapped_column(Text)
    outcome: Mapped[Optional[str]] = mapped_column(Text)
    metrics: Mapped[Optional[str]] = mapped_column(Text)

    # Aggregated counts
    total_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_sources: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # JSONB aggregations
    aggregated_categories: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    aggregated_recipients: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    aggregated_sources: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    events = relationship("EventSummary", back_populates="period_summary")

    __table_args__ = (
        UniqueConstraint(
            "period_type", "period_start", "period_end", "initiating_country",
            name="uq_period_summary"
        ),
        Index("ix_period_summary_country_period", "initiating_country", "period_type", "period_start"),
        CheckConstraint("period_start <= period_end", name="ck_valid_period_summary"),
        CheckConstraint("total_events >= 0", name="ck_positive_event_count"),
    )

    def __repr__(self):
        return f"<PeriodSummary(id={self.id}, period_type={self.period_type}, country='{self.initiating_country}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class EventSourceLink(Base):
    """
    Links EventSummary to source documents for traceability.
    """
    __tablename__ = "event_source_links"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_summary_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    doc_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False
    )

    # Link metadata
    contribution_weight: Mapped[Optional[float]] = mapped_column(Float)  # How much this doc contributed to the summary
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    event_summary = relationship("EventSummary", back_populates="source_links")
    document = relationship("Document", back_populates="event_source_links")

    __table_args__ = (
        UniqueConstraint("event_summary_id", "doc_id", name="uq_event_source_link"),
        Index("ix_event_source_event", "event_summary_id"),
        Index("ix_event_source_doc", "doc_id"),
    )

    def __repr__(self):
        return f"<EventSourceLink(event_summary_id={self.event_summary_id}, doc_id='{self.doc_id}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

# Add to backend/models.py

class CanonicalEvent(Base):
    """Canonical event tracked across news mentions over time."""
    __tablename__ = "canonical_events"
    
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Core identity
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    initiating_country: Mapped[str] = mapped_column(Text, nullable=False)
    
    # News mention tracking (key for news feeds)
    first_mention_date: Mapped[DateType] = mapped_column(Date, nullable=False)
    last_mention_date: Mapped[DateType] = mapped_column(Date, nullable=False)
    total_mention_days: Mapped[int] = mapped_column(Integer, default=1)  # Days with mentions
    total_articles: Mapped[int] = mapped_column(Integer, default=0)
    
    # Story arc tracking
    story_phase: Mapped[str] = mapped_column(String(50))  # "emerging", "developing", "peak", "fading", "dormant"
    days_since_last_mention: Mapped[int] = mapped_column(Integer, default=0)
    
    # News source diversity
    unique_sources: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Peak coverage tracking
    peak_mention_date: Mapped[Optional[DateType]] = mapped_column(Date)
    peak_daily_article_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Aggregated information (builds over time as articles mention different details)
    consolidated_description: Mapped[Optional[str]] = mapped_column(Text)
    key_facts: Mapped[Dict[str, str]] = mapped_column(JSONB, default=dict)  # Facts extracted from articles
    
    # For matching
    embedding_vector: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float))
    alternative_names: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list)  # Different headlines for same event
    
    # Metadata
    primary_categories: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict)
    primary_recipients: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict)
    
    # Relationships
    daily_mentions = relationship("DailyEventMention", back_populates="canonical_event")
    
    __table_args__ = (
        Index("ix_canonical_event_country_dates", "initiating_country", "first_mention_date", "last_mention_date"),
        Index("ix_canonical_event_story_phase", "story_phase"),
        Index("ix_canonical_event_days_since", "days_since_last_mention"),
    )

class DailyEventMention(Base):
    """
    Represents all articles about an event on a specific day.
    This is your daily consolidation output.
    """
    __tablename__ = "daily_event_mentions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    canonical_event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_events.id", ondelete="CASCADE"),
        nullable=False
    )

    # Country field for efficient filtering and data integrity
    initiating_country: Mapped[str] = mapped_column(Text, nullable=False)

    mention_date: Mapped[DateType] = mapped_column(Date, nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Consolidation metadata (from your daily clustering + LLM)
    consolidated_headline: Mapped[str] = mapped_column(Text)  # Best representation of event on this day
    daily_summary: Mapped[Optional[str]] = mapped_column(Text)  # What was new this day
    
    # Source tracking
    source_names: Mapped[List[str]] = mapped_column(ARRAY(Text))
    source_diversity_score: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Signals for temporal matching
    mention_context: Mapped[str] = mapped_column(Text)  # "announcement", "preparation", "execution", "aftermath"
    news_intensity: Mapped[str] = mapped_column(String(20))  # "breaking", "developing", "follow-up", "recap"
    
    # Links to source documents
    doc_ids: Mapped[List[str]] = mapped_column(ARRAY(Text))
    
    # Relationships
    canonical_event = relationship("CanonicalEvent", back_populates="daily_mentions")
    
    __table_args__ = (
        UniqueConstraint("canonical_event_id", "mention_date", name="uq_daily_mention"),
        Index("ix_daily_mention_date", "mention_date"),
        Index("ix_daily_mention_context", "mention_context"),
        Index("ix_daily_mention_country_date", "initiating_country", "mention_date"),
    )