import uuid
from datetime import datetime, timezone
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
    salience_justification: Mapped[Optional[str]] = mapped_column(Text)
    salience_bool: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    category_justification: Mapped[Optional[str]] = mapped_column(Text)
    subcategory: Mapped[Optional[str]] = mapped_column(Text)

    # Geographic and relational data
    initiating_country: Mapped[Optional[str]] = mapped_column(Text)
    recipient_country: Mapped[Optional[str]] = mapped_column(Text)
    projects: Mapped[Optional[str]] = mapped_column(Text)
    lat_long: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)

    # Financial data
    monetary_commitment: Mapped[Optional[str]] = mapped_column(Text)

    # Content
    distilled_text: Mapped[Optional[str]] = mapped_column(Text)
    event_name: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    categories = relationship("Category", back_populates="document", lazy="dynamic")
    subcategories = relationship("Subcategory", back_populates="document", lazy="dynamic")
    initiating_countries = relationship("InitiatingCountry", back_populates="document", lazy="dynamic")
    recipient_countries = relationship("RecipientCountry", back_populates="document", lazy="dynamic")
    projects_rel = relationship("Project", back_populates="document", lazy="dynamic")
    raw_events = relationship("RawEvent", back_populates="document", lazy="dynamic")
    citations = relationship("Citation", back_populates="document", lazy="dynamic")

    events = relationship(
        "Event",
        secondary="event_sources",
        back_populates="documents",
        lazy="dynamic",
    )

    event_source_links = relationship("EventSourceLink", back_populates="document")

    def __repr__(self) -> str:
        return f"<Document(doc_id='{self.doc_id}', title='{self.title}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary for API serialization."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class Category(Base):
    """
    Document categories - many-to-many relationship with documents.
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
    
class Project(Base):
    """
    Projects associated with documents - many-to-many relationship.
    """
    __tablename__ = 'projects'

    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    project: Mapped[str] = mapped_column(Text, primary_key=True)

    # Bidirectional relationship for easier querying
    document = relationship("Document", back_populates="projects_rel")

    def __repr__(self) -> str:
        return f"<Project(doc_id='{self.doc_id}', project='{self.project}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
class Event(Base):
    """
    Events that link documents and provide event-level analysis.
    """
    __tablename__ = 'events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    initiating_country: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_country: Mapped[str] = mapped_column(Text, nullable=False)
    material_score: Mapped[Optional[int]] = mapped_column(Integer)
    material_score_justification: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            'event_name',
            'initiating_country',
            'recipient_country',
            name='uq_events_name_countries'
        ),
    )

    documents = relationship(
        "Document",
        secondary="event_sources",
        back_populates="events",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, name='{self.event_name}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class EventSources(Base):
    """
    Junction table linking events to their source documents.
    """
    __tablename__ = 'event_sources'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey('events.id'))
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'))

    __table_args__ = (
        UniqueConstraint(
            'event_id', 'doc_id', name='uq_event_source_composite'
        ),
    )

    def __repr__(self) -> str:
        return f"<EventSources(event_id={self.event_id}, doc_id='{self.doc_id}')>"

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

class Citation(Base):
    """
    Citations associated with documents.
    """
    __tablename__ = 'citations'

    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    citation: Mapped[Optional[str]] = mapped_column(Text)

    # Bidirectional relationship for easier querying
    document = relationship("Document", back_populates="citations")

    def __repr__(self) -> str:
        return f"<Citation(doc_id='{self.doc_id}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SoftPowerActivity(Base):
    """
    Soft Power Activities with comprehensive tracking.
    """
    __tablename__ = 'soft_power_activities'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[Optional[DateType]] = mapped_column(Date)
    initiating_country: Mapped[Optional[str]] = mapped_column(Text)
    recipient_country: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    subcategory: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    significance: Mapped[Optional[str]] = mapped_column(Text)
    entities: Mapped[Optional[str]] = mapped_column(Text)
    sources: Mapped[Optional[str]] = mapped_column(Text)
    event_name: Mapped[Optional[str]] = mapped_column(Text)
    lat_long: Mapped[Optional[str]] = mapped_column(Text)
    material_score: Mapped[Optional[int]] = mapped_column(Integer)
    material_score_justification: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            'date', 'initiating_country', 'recipient_country', 'event_name',
            name='uq_activity_composite'
        ),
    )

    def __repr__(self) -> str:
        return f"<SoftPowerActivity(id={self.id}, event='{self.event_name}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
class SoftPowerActivitySource(Base):
    __tablename__ = 'softpower_activity_sources'

    sp_id = mapped_column(Integer, ForeignKey('soft_power_activities.id'), primary_key=True)
    doc_id = mapped_column(Text, primary_key=True)  # <- make this part of the primary key

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
        
class SoftPowerEntity(Base):
    __tablename__ = 'softpower_entities'

    sp_id = mapped_column(Integer, ForeignKey('soft_power_activities.id'), primary_key=True)
    entity = mapped_column(Text, primary_key=True)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SoftPowerActivityCategory(Base):
    __tablename__ = 'softpower_activity_categories'

    sp_id = mapped_column(Integer, ForeignKey('soft_power_activities.id'), primary_key=True)
    category = mapped_column(Text, primary_key=True)  # <-- make part of PK
    category_material_score = mapped_column(Integer)
    category_score_justification = mapped_column(Text)

    # UniqueConstraint is now redundant; remove it
    # __table_args__ = (... )  # delete this
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SoftPowerActivitySubcategory(Base):
    __tablename__ = 'softpower_activity_subcategories'
    sp_id = mapped_column(Integer, ForeignKey('soft_power_activities.id'), primary_key=True)
    subcategory = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            'sp_id', 'subcategory', name='uq_activity_subcategory_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class EventCluster(Base):
    __tablename__ = 'event_clusters'
    
    id = mapped_column(Integer, primary_key=True)
    normalized_event_name = mapped_column(String, nullable=False)
    country = mapped_column(String, nullable=True)  # Optional
    created_at = mapped_column(DateTime, default=func.now())
    # Event date range (based on linked docs)
    start_date = mapped_column(Date, nullable=True)
    end_date = mapped_column(Date, nullable=True)
    # Relationships
    original_names = relationship('EventClusterName', back_populates='cluster', cascade="all, delete-orphan")
    documents = relationship('EventClusterDocument', back_populates='cluster', cascade="all, delete-orphan")

class EventClusterName(Base):
    __tablename__ = 'event_cluster_names'

    id = mapped_column(Integer, primary_key=True)
    cluster_id = mapped_column(Integer, ForeignKey('event_clusters.id'), nullable=False)
    original_event_name = mapped_column(String, nullable=False)

    cluster = relationship('EventCluster', back_populates='original_names')

class EventClusterDocument(Base):
    __tablename__ = 'event_cluster_documents'

    id = mapped_column(Integer, primary_key=True)
    cluster_id = mapped_column(Integer, ForeignKey('event_clusters.id'), nullable=False)
    doc_id = mapped_column(String, nullable=False, index=True)
    publication_date = mapped_column(Date, nullable=True)

    cluster = relationship('EventCluster', back_populates='documents')

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
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
        _ = key  # Mark parameter as intentionally unused
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
        self.deleted_at = datetime.now(timezone.utc)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

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
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    event_summary = relationship("EventSummary", back_populates="source_links")
    document = relationship("Document")

    __table_args__ = (
        UniqueConstraint("event_summary_id", "doc_id", name="uq_event_source_link"),
        Index("ix_event_source_event", "event_summary_id"),
        Index("ix_event_source_doc", "doc_id"),
    )

    def __repr__(self):
        return f"<EventSourceLink(event_summary_id={self.event_summary_id}, doc_id='{self.doc_id}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class EventEntities(Base):
    __tablename__ = 'event_entities'
    id = mapped_column(Integer, primary_key=True)
    event_id = mapped_column(Integer, ForeignKey('events.id'))
    event_summary_id = mapped_column(Integer, ForeignKey('event_summaries.id'))
    entity = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            'event_id', 'entity', name='uq_event_entity_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
       
class Commitments(Base):
    __tablename__ = 'commitments'
    id = mapped_column(Integer, primary_key=True)
    event_id = mapped_column(Integer, ForeignKey('events.id'))
    event_summary_id = mapped_column(Integer, ForeignKey('event_summaries.id'))
    commitment_purpose = mapped_column(Text)
    commitment_description = mapped_column(Text)
    commitment_amount = mapped_column(BigInteger)  # JSON string of monetary values
    commitment_status = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            'event_id', 'commitment_purpose', name='uq_commitment_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class DailySummary(Base):
    __tablename__ = 'daily_summaries'

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = mapped_column(Date, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)

    # Flattened Lists
    recipient_countries = mapped_column(JSONB, default=list)
    categories = mapped_column(JSONB, default=list)
    subcategories = mapped_column(JSONB, default=list)
    entities = mapped_column(JSONB, default=list)

    # Aggregated Stats
    total_articles = mapped_column(Integer, default=0)
    total_events = mapped_column(Integer, default=0)
    total_sources = mapped_column(Integer, default=0)
    symbolic_event_count = mapped_column(Integer, default=0)
    material_event_count = mapped_column(Integer, default=0)

    # Material Score Stats
    avg_material_score = mapped_column(Float)
    median_material_score = mapped_column(Float)
    material_score_stddev = mapped_column(Float)

    # Detailed Counts and Breakdown
    count_by_category = mapped_column(JSONB, default=dict)
    count_by_subcategory = mapped_column(JSONB, default=dict)
    count_by_recipient = mapped_column(JSONB, default=dict)
    count_by_entity = mapped_column(JSONB, default=dict)
    material_score_by_category = mapped_column(JSONB, default=dict)

    # Generated Summary Text
    aggregate_summary = mapped_column(Text)

    # Optional: timestamps
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, onupdate=func.now())

    # Relationships (View-only to source events)
    daily_event_summaries = relationship(
        "DailyEventSummary",
        primaryjoin="and_(DailySummary.date==foreign(DailyEventSummary.report_date), "
                    "DailySummary.initiating_country==foreign(DailyEventSummary.initiating_country))",
        viewonly=True,
        lazy='dynamic'
    )

    # Relationships to flattened entity models
    flat_entities = relationship("DailySummaryEntity", backref="summary", cascade="all, delete-orphan")
    flat_recipients = relationship("DailySummaryRecipientCountry", backref="summary", cascade="all, delete-orphan")
    flat_categories = relationship("DailySummaryCategory", backref="summary", cascade="all, delete-orphan")
    flat_subcategories = relationship("DailySummarySubcategory", backref="summary", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('date', 'initiating_country', name='uq_daily_composite'),
        Index('ix_summary_date', 'date'),
        Index('ix_summary_initiating_country', 'initiating_country'),
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class DailySummaryEntity(Base):
    __tablename__ = 'daily_summary_entities'
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = mapped_column(UUID(as_uuid=True), ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = mapped_column(Text, nullable=False)
    count = mapped_column(Integer, default=1)

    __table_args__ = (
        Index('ix_entity_summary', 'summary_id'),
    )

class DailySummaryRecipientCountry(Base):
    __tablename__ = 'daily_summary_recipients'
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = mapped_column(UUID(as_uuid=True), ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = mapped_column(Text, nullable=False)
    count = mapped_column(Integer, default=1)

class DailySummaryCategory(Base):
    __tablename__ = 'daily_summary_categories'
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = mapped_column(UUID(as_uuid=True), ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = mapped_column(Text, nullable=False)
    count = mapped_column(Integer, default=1)
    avg_material_score = mapped_column(Float)

class DailySummarySubcategory(Base):
    __tablename__ = 'daily_summary_subcategories'
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = mapped_column(UUID(as_uuid=True), ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = mapped_column(Text, nullable=False)
    count = mapped_column(Integer, default=1)

class EntitySummary(Base):
    __tablename__ = 'entities'
    id = mapped_column(Integer, primary_key=True)
    start_date = mapped_column(Date)
    end_date = mapped_column(Date)
    initiating_country = mapped_column(Text)
    recipient_country = mapped_column(Text)
    entity = mapped_column(Text)
    entity_type = mapped_column(Text)
    entity_summary = mapped_column(Text)
    activity_ids = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            'start_date','end_date','initiating_country','recipient_country','entity',
            name='uq_entity_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class CountrySummary(Base):
    __tablename__ = 'country_summary'
    id = mapped_column(Integer, primary_key=True)
    country = mapped_column(Text)
    key_event = mapped_column(Text)
    start_date = mapped_column(Text)
    end_date = mapped_column(Text)
    category = mapped_column(Text)
    overview = mapped_column(Text)
    outcome = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            'country', 'key_event', 'start_date', 'end_date', 'category',
            name='uq_country_event_window_category'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
class RecipientSummary(Base):
    __tablename__ = 'recipient_summary'
    id = mapped_column(Integer)
    country = mapped_column(Text,primary_key=True)
    recipient = mapped_column(Text,primary_key=True)
    key_event = mapped_column(Text,primary_key=True)
    start_date = mapped_column(Text,primary_key=True)
    end_date = mapped_column(Text,primary_key=True)
    category = mapped_column(Text,primary_key=True)
    overview = mapped_column(Text)
    outcome = mapped_column(Text)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SummarySources(Base):
    __tablename__ = 'summary_sources'
    summary_id = mapped_column(Integer, ForeignKey('country_summary.id'), primary_key=True)
    summary_type = mapped_column(Text, primary_key=True)
    doc_id = mapped_column(Text, primary_key=True)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SummaryClaims(Base):
    id = mapped_column(Integer)
    summary_id = mapped_column(Integer, ForeignKey('country_summary.id'), primary_key=True)
    section = mapped_column(Text)
    claim = mapped_column(Text)
    doc_id = mapped_column(Text, primary_key=True)
    citation = mapped_column(Text)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class TokenizedDocuments(Base):
    __tablename__ = 'tokenized_documents'
    doc_id = mapped_column(Text,primary_key=True)
    tokens = mapped_column(Text)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class RecipientDaily(Base):
    __tablename__ = 'recipient_daily_summaries'
    id = mapped_column(Integer, primary_key=True)
    date = mapped_column(Date)
    initiating_country = mapped_column(Text)
    recipient_country = mapped_column(Text)
    categories = mapped_column(Text)
    subcategories = mapped_column(Text)
    total_articles = mapped_column(Integer)
    count_by_category = mapped_column(Text)
    count_by_subcategory = mapped_column(Text)
    count_by_recipient = mapped_column(Text)
    aggregate_summary = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            'date', 'initiating_country', 'recipient_country',
            name='uq_rec_daily_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class DailyEvent(Base):
    __tablename__ = "daily_events"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_name = mapped_column(Text, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)
    report_date = mapped_column(Date, nullable=False)

    # relationship to sources
    sources = relationship(
        "DailyEventSource",
        back_populates="event",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<DailyEvent(id={self.id}, name={self.event_name})>"


class DailyEventSource(Base):
    __tablename__ = "daily_event_sources"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # foreign keys
    event_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("daily_events.id", ondelete="CASCADE"),
        nullable=False
    )
    doc_id = mapped_column(
        String,
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False
    )

    # relationships
    event = relationship("DailyEvent", back_populates="sources")
    document = relationship("Document")

    __table_args__ = (
        UniqueConstraint("event_id", "doc_id", name="uq_event_doc"),
        Index("ix_event_id", "event_id"),
        Index("ix_doc_id", "doc_id"),
    )

    def __repr__(self):
        return f"<DailyEventSource(id={self.id}, event_id={self.event_id}, doc_id={self.doc_id})>"

class DailyEventSummary(Base):
    __tablename__ = "daily_event_summaries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key to the event this summary is based on
    event_id = mapped_column(UUID(as_uuid=True), ForeignKey("daily_events.id", ondelete="CASCADE"), nullable=False)

    # Core metadata
    report_date = mapped_column(Date, nullable=False)
    event_name = mapped_column(Text, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)

    # Inferred or LLM-evaluated fields
    recipient_countries = mapped_column(JSONB)  # List[str]
    categories = mapped_column(JSONB)           # List[str]
    subcategories = mapped_column(JSONB)        # List[str]
    entities = mapped_column(JSONB)             # List[str]
    material_score = mapped_column(Integer)
    material_score_justification = mapped_column(Text)
    event_hyperlink = mapped_column(Text)
    summary_text = mapped_column(Text)

    # Source aggregation metadata
    document_count = mapped_column(Integer)
    unique_source_count = mapped_column(Integer)

    # Bookkeeping
    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    categories_flat = relationship("DailyEventCategory", back_populates="summary", cascade="all, delete-orphan")
    subcategories_flat = relationship("DailyEventSubcategory", back_populates="summary", cascade="all, delete-orphan")
    recipient_countries_flat = relationship("DailyEventRecipientCountry", back_populates="summary", cascade="all, delete-orphan")
    entities_flat = relationship("DailyEventEntity", back_populates="summary", cascade="all, delete-orphan")
    def to_dict(self):
        return {
            "id": str(self.id),
            "event_id": str(self.event_id),
            "report_date": self.report_date.isoformat(),
            "event_name": self.event_name,
            "initiating_country": self.initiating_country,
            "recipient_countries": self.recipient_countries,
            "categories": self.categories,
            "subcategories": self.subcategories,
            "entities": self.entities,
            "material_score": self.material_score,
            "material_score_justification": self.material_score_justification,
            "event_hyperlink": self.event_hyperlink,
            "summary_text": self.summary_text,
            "document_count": self.document_count,
            "unique_source_count": self.unique_source_count,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
# Category Link
class DailyEventCategory(Base):
    __tablename__ = "daily_event_categories"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = mapped_column(UUID(as_uuid=True), ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    category = mapped_column(Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="categories_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "category", name="uq_summary_category"),
    )


# Subcategory Link
class DailyEventSubcategory(Base):
    __tablename__ = "daily_event_subcategories"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = mapped_column(UUID(as_uuid=True), ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    subcategory = mapped_column(Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="subcategories_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "subcategory", name="uq_summary_subcategory"),
    )


# Recipient Country Link
class DailyEventRecipientCountry(Base):
    __tablename__ = "daily_event_recipient_countries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = mapped_column(UUID(as_uuid=True), ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    country = mapped_column(Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="recipient_countries_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "country", name="uq_summary_recipient_country"),
    )


# Entity Link
class DailyEventEntity(Base):
    __tablename__ = "daily_event_entities"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = mapped_column(UUID(as_uuid=True), ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    entity = mapped_column(Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="entities_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "entity", name="uq_summary_entity"),
    )

class DailySummaryEventLink(Base):
    __tablename__ = "daily_summary_event_links"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    daily_summary_id = mapped_column(UUID(as_uuid=True), ForeignKey("daily_summaries.id", ondelete="CASCADE"), nullable=False)
    event_summary_id = mapped_column(UUID(as_uuid=True), ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("daily_summary_id", "event_summary_id", name="uq_daily_summary_event"),
    )
    
class WeeklyEvent(Base):
    __tablename__ = "weekly_events"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Rollup window
    week_start = mapped_column(Date, nullable=False)
    week_end   = mapped_column(Date, nullable=False)

    # Core deduped event data
    event_name = mapped_column(Text, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)
    first_observed_date = mapped_column(Date, nullable=False)
    last_observed_date  = mapped_column(Date, nullable=False)

    # Container link (to WeeklySummary)
    weekly_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
        nullable=True
    )
    weekly_summary = relationship("WeeklySummary", back_populates="events")

    # Relationships
    sources = relationship(
        "WeeklyEventLink",
        back_populates="event",
        cascade="all, delete-orphan"
    )
    summaries = relationship(
        "WeeklyEventSummary",
        back_populates="event",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "week_start", "week_end", "initiating_country", "event_name",
            name="uq_weekly_event"
        ),
    )


class WeeklySummary(Base):
    __tablename__ = "weekly_summaries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    week_start = mapped_column(Date, nullable=False)
    week_end   = mapped_column(Date, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)

    # Observed window
    first_observed_date = mapped_column(Date, nullable=False)
    last_observed_date  = mapped_column(Date, nullable=False)
    distinct_observed_dates = mapped_column(ARRAY(Date))
    num_observed_days   = mapped_column(Integer)

    # Aggregated prose (from LLM prompts)
    weekly_overview = mapped_column(Text)
    weekly_outcome  = mapped_column(Text)
    weekly_metrics  = mapped_column(Text)

    # Aggregated metrics
    num_articles       = mapped_column(Integer)
    num_unique_sources = mapped_column(Integer)
    num_recipients     = mapped_column(Integer)
    num_entities       = mapped_column(Integer)
    num_weekly_events  = mapped_column(Integer)

    avg_material_score    = mapped_column(Float)
    median_material_score = mapped_column(Float)
    material_score_stddev = mapped_column(Float)

    count_by_category    = mapped_column(JSONB)
    count_by_subcategory = mapped_column(JSONB)
    count_by_recipient   = mapped_column(JSONB)
    count_by_source      = mapped_column(JSONB)

    avg_material_score_by_category    = mapped_column(JSONB)
    avg_material_score_by_subcategory = mapped_column(JSONB)
    score_distribution_by_category    = mapped_column(JSONB)
    score_distribution_by_subcategory = mapped_column(JSONB)

    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    events = relationship(
        "WeeklyEvent",
        back_populates="weekly_summary",
        cascade="all, delete-orphan"
    )
    links = relationship(
        "WeeklySummaryEventLink",
        back_populates="weekly_summary",
        cascade="all, delete-orphan"
    )
    # monthly_links = relationship(
    #     "MonthlySummaryWeeklyLink",
    #     back_populates="weekly_summary",
    #     cascade="all, delete-orphan"
    # )
    
    __table_args__ = (
        UniqueConstraint("week_start", "week_end", "initiating_country", name="uq_weekly_summary"),
    )


class WeeklyEventLink(Base):
    __tablename__ = "weekly_event_links"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_events.id", ondelete="CASCADE"),
        nullable=False
    )
    daily_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("daily_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )

    event = relationship("WeeklyEvent", back_populates="sources")
    daily_summary = relationship("DailyEventSummary")

    __table_args__ = (
        UniqueConstraint("event_id", "daily_summary_id", name="uq_weekly_event_daily_summary"),
    )


class WeeklyEventSummary(Base):
    __tablename__ = "weekly_event_summaries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_events.id", ondelete="CASCADE"),
        nullable=False
    )

    # Core metadata
    event_name = mapped_column(Text, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)

    # Inferred or LLM-evaluated fields
    recipient_countries = mapped_column(JSONB)
    categories          = mapped_column(JSONB)
    subcategories       = mapped_column(JSONB)
    entities            = mapped_column(JSONB)
    material_score = mapped_column(Integer)
    material_score_justification = mapped_column(Text)
    event_hyperlink = mapped_column(Text)
    summary_text = mapped_column(Text)

    # Source aggregation metadata
    document_count = mapped_column(Integer)
    unique_source_count = mapped_column(Integer)

    # 🔢 Metrics rollup (per event, per week)
    num_articles       = mapped_column(Integer)
    num_unique_sources = mapped_column(Integer)
    num_recipients     = mapped_column(Integer)
    num_entities       = mapped_column(Integer)

    avg_material_score    = mapped_column(Float)
    median_material_score = mapped_column(Float)
    material_score_stddev = mapped_column(Float)

    count_by_category    = mapped_column(JSONB)
    count_by_subcategory = mapped_column(JSONB)
    count_by_recipient   = mapped_column(JSONB)
    count_by_source      = mapped_column(JSONB)

    avg_material_score_by_category    = mapped_column(JSONB)
    avg_material_score_by_subcategory = mapped_column(JSONB)
    score_distribution_by_category    = mapped_column(JSONB)
    score_distribution_by_subcategory = mapped_column(JSONB)

    # Bookkeeping
    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    categories_flat = relationship("WeeklyEventCategory", back_populates="summary", cascade="all, delete-orphan")
    subcategories_flat = relationship("WeeklyEventSubcategory", back_populates="summary", cascade="all, delete-orphan")
    recipient_countries_flat = relationship("WeeklyEventRecipientCountry", back_populates="summary", cascade="all, delete-orphan")
    entities_flat = relationship("WeeklyEventEntity", back_populates="summary", cascade="all, delete-orphan")

    event = relationship("WeeklyEvent", back_populates="summaries")
    monthly_links = relationship(
        "MonthlySummaryWeeklyLink",
        back_populates="weekly_event_summary",
        cascade="all, delete-orphan"
    )
class WeeklyEventCategory(Base):
    __tablename__ = "weekly_event_categories"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    category = mapped_column(Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="categories_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "category", name="uq_weekly_summary_category"),
    )


class WeeklyEventSubcategory(Base):
    __tablename__ = "weekly_event_subcategories"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    subcategory = mapped_column(Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="subcategories_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "subcategory", name="uq_weekly_summary_subcategory"),
    )


class WeeklyEventRecipientCountry(Base):
    __tablename__ = "weekly_event_recipient_countries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    country = mapped_column(Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="recipient_countries_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "country", name="uq_weekly_summary_recipient_country"),
    )


class WeeklyEventEntity(Base):
    __tablename__ = "weekly_event_entities"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    entity = mapped_column(Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="entities_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "entity", name="uq_weekly_summary_entity"),
    )

class WeeklySummaryEventLink(Base):
    __tablename__ = "weekly_summary_event_links"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    weekly_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    daily_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("daily_summaries.id", ondelete="CASCADE"),
        nullable=False
    )

    weekly_summary = relationship("WeeklySummary", back_populates="links")
    daily_summary = relationship("DailySummary")

    __table_args__ = (
        UniqueConstraint("weekly_summary_id", "daily_summary_id", name="uq_weekly_summary_daily_summary"),
    )

class MonthlyEventLink(Base):
    __tablename__ = "monthly_event_links"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = mapped_column(UUID(as_uuid=True), ForeignKey("monthly_events.id", ondelete="CASCADE"), nullable=False)
    weekly_event_id = mapped_column(UUID(as_uuid=True), ForeignKey("weekly_events.id", ondelete="CASCADE"), nullable=False)

    event = relationship("MonthlyEvent", back_populates="sources")
    weekly_event = relationship("WeeklyEvent")

    __table_args__ = (
        UniqueConstraint("event_id", "weekly_event_id", name="uq_monthly_event_weekly_event"),
    )


# class MonthlySummaryWeeklyLink(Base):
#     __tablename__ = "monthly_summary_weekly_links"

#     id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

#     monthly_summary_id = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )
#     weekly_summary_id = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )

#     monthly_summary = relationship("MonthlySummary", back_populates="links")
#     weekly_summary = relationship("WeeklySummary", back_populates="monthly_links")

#     __table_args__ = (
#         UniqueConstraint("monthly_summary_id", "weekly_summary_id", name="uq_monthly_summary_weekly"),
#     )

class MonthlyEventSummary(Base):
    __tablename__ = "monthly_event_summaries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monthly_events.id", ondelete="CASCADE"),
        nullable=False
    )

    # Core metadata
    event_name = mapped_column(Text, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)

    # Inferred or LLM-evaluated fields
    recipient_countries = mapped_column(JSONB)
    categories          = mapped_column(JSONB)
    subcategories       = mapped_column(JSONB)
    entities            = mapped_column(JSONB)

    material_score = mapped_column(Integer)
    material_score_justification = mapped_column(Text)
    event_hyperlink = mapped_column(Text)

    summary_text = mapped_column(Text)   # overview paragraph
    outcome_text = mapped_column(Text)   # outcome paragraph
    metrics_text = mapped_column(Text)   # metrics paragraph

    # 🔢 Metrics rollup (per event, per month)
    num_articles       = mapped_column(Integer)       # replaces document_count
    num_unique_sources = mapped_column(Integer)       # replaces unique_source_count
    num_recipients     = mapped_column(Integer)
    num_entities       = mapped_column(Integer)

    avg_material_score    = mapped_column(Float)
    median_material_score = mapped_column(Float)
    material_score_stddev = mapped_column(Float)

    count_by_category    = mapped_column(JSONB)
    count_by_subcategory = mapped_column(JSONB)
    count_by_recipient   = mapped_column(JSONB)
    count_by_source      = mapped_column(JSONB)

    avg_material_score_by_category    = mapped_column(JSONB)
    avg_material_score_by_subcategory = mapped_column(JSONB)
    score_distribution_by_category    = mapped_column(JSONB)
    score_distribution_by_subcategory = mapped_column(JSONB)

    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    categories_flat = relationship("MonthlyEventCategory", back_populates="summary", cascade="all, delete-orphan")
    subcategories_flat = relationship("MonthlyEventSubcategory", back_populates="summary", cascade="all, delete-orphan")
    recipient_countries_flat = relationship("MonthlyEventRecipientCountry", back_populates="summary", cascade="all, delete-orphan")
    entities_flat = relationship("MonthlyEventEntity", back_populates="summary", cascade="all, delete-orphan")

    # Parent event
    event = relationship("MonthlyEvent", back_populates="summaries")

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_monthly_event_summary_event"),
    )
class MonthlySummary(Base):
    __tablename__ = "monthly_summaries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    month_start = mapped_column(Date, nullable=False)
    month_end   = mapped_column(Date, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)

    first_observed_date = mapped_column(Date, nullable=False)
    last_observed_date  = mapped_column(Date, nullable=False)
    distinct_observed_dates = mapped_column(ARRAY(Date))
    num_observed_days   = mapped_column(Integer)

    monthly_overview = mapped_column(Text)
    monthly_outcome  = mapped_column(Text)
    monthly_metrics  = mapped_column(Text)

    num_articles       = mapped_column(Integer)
    num_unique_sources = mapped_column(Integer)
    num_recipients     = mapped_column(Integer)
    num_entities       = mapped_column(Integer)
    num_monthly_events = mapped_column(Integer)

    avg_material_score    = mapped_column(Float)
    median_material_score = mapped_column(Float)
    material_score_stddev = mapped_column(Float)

    count_by_category    = mapped_column(JSONB)
    count_by_subcategory = mapped_column(JSONB)
    count_by_recipient   = mapped_column(JSONB)
    count_by_source      = mapped_column(JSONB)

    avg_material_score_by_category    = mapped_column(JSONB)
    avg_material_score_by_subcategory = mapped_column(JSONB)
    score_distribution_by_category    = mapped_column(JSONB)
    score_distribution_by_subcategory = mapped_column(JSONB)

    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    events = relationship(
        "MonthlyEvent",
        back_populates="monthly_summary",
        cascade="all, delete-orphan"
    )

    weekly_links = relationship(
        "MonthlySummaryWeeklyLink",
        back_populates="monthly_summary",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("month_start", "month_end", "initiating_country", name="uq_monthly_summary"),
    )

class MonthlyEvent(Base):
    __tablename__ = "monthly_events"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    month_start = mapped_column(Date, nullable=False)
    month_end   = mapped_column(Date, nullable=False)

    event_name = mapped_column(Text, nullable=False)
    initiating_country = mapped_column(Text, nullable=False)
    first_observed_date = mapped_column(Date, nullable=False)
    last_observed_date  = mapped_column(Date, nullable=False)

    monthly_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
        nullable=True
    )
    monthly_summary = relationship("MonthlySummary", back_populates="events")

    sources = relationship(
        "MonthlyEventLink",
        back_populates="event",
        cascade="all, delete-orphan"
    )
    summaries = relationship(
        "MonthlyEventSummary",
        back_populates="event",
        cascade="all, delete-orphan"
    )
# class MonthlySummaryEventLink(Base):
#     __tablename__ = "monthly_summary_event_links"

#     id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#     monthly_summary_id = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )

#     weekly_summary_id = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )

#     monthly_summary = relationship("MonthlySummary", back_populates="event_links")
#     weekly_summary = relationship("WeeklySummary")

#     __table_args__ = (
#         UniqueConstraint("monthly_summary_id", "weekly_summary_id", name="uq_monthly_summary_weekly_summary"),
#     )

class MonthlySummaryWeeklyLink(Base):
    __tablename__ = "monthly_summary_weekly_links"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    monthly_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    weekly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )

    monthly_summary = relationship("MonthlySummary", back_populates="weekly_links")
    weekly_event_summary = relationship("WeeklyEventSummary", back_populates="monthly_links")

    __table_args__ = (
        UniqueConstraint(
            "monthly_summary_id", "weekly_event_summary_id",
            name="uq_monthly_summary_weekly_event_summary"
        ),
    )

class MonthlyEventCategory(Base):
    __tablename__ = "monthly_event_categories"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    category = mapped_column(Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="categories_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "category", name="uq_monthly_summary_category"),
    )


class MonthlyEventSubcategory(Base):
    __tablename__ = "monthly_event_subcategories"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    subcategory = mapped_column(Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="subcategories_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "subcategory", name="uq_monthly_summary_subcategory"),
    )


class MonthlyEventRecipientCountry(Base):
    __tablename__ = "monthly_event_recipient_countries"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    country = mapped_column(Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="recipient_countries_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "country", name="uq_monthly_summary_recipient_country"),
    )


class MonthlyEventEntity(Base):
    __tablename__ = "monthly_event_entities"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    entity = mapped_column(Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="entities_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "entity", name="uq_monthly_summary_entity"),
    )


class BayesianResult(Base):
    __tablename__ = "bayesian_results"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    initiator = mapped_column(Text, nullable=False)       # e.g. "China"
    recipient = mapped_column(Text, nullable=False)       # e.g. "Egypt"
    category = mapped_column(Text, nullable=False)        # e.g. "Economic"
    subcategory = mapped_column(Text, nullable=True)      # e.g. "Tourism"

    # method encodes both inference type and metric, e.g. "advi_material_score"
    method = mapped_column(Text, nullable=False)          

    prob_increase = mapped_column(Float, nullable=True)   # P(beta > 0)
    mean = mapped_column(JSONB, default=list)                # predictive mean series
    lower = mapped_column(JSONB, default=list)               # lower bound (5th percentile)
    upper = mapped_column(JSONB, default=list)               # upper bound (95th percentile)

    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # 🔑 New metadata column for jump flags, etc.
    meta = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_bayes_lookup", "initiator", "recipient", "category", "subcategory", "method"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "initiator": self.initiator,
            "recipient": self.recipient,
            "category": self.category,
            "subcategory": self.subcategory,
            "method": self.method,
            "prob_increase": self.prob_increase,
            "mean": self.mean,
            "lower": self.lower,
            "upper": self.upper,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "meta": self.meta or {},
        }