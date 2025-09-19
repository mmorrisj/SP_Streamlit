from flask_sqlalchemy import SQLAlchemy
import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from backend.scripts.prompts import salience_prompt
from backend.extensions import db
from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger
from datetime import datetime
from sqlalchemy import Date, Text, Float, Integer, UniqueConstraint, Index

class Document(db.Model):
    __tablename__ = 'documents'
    __table_args__ = {'extend_existing': True}

    doc_id = db.Column(db.Text,primary_key=True)
    title = db.Column(db.Text)
    source_name = db.Column(db.Text)
    source_geofocus = db.Column(db.Text)
    source_consumption = db.Column(db.Text)
    source_description = db.Column(db.Text)
    source_medium = db.Column(db.Text)
    source_location = db.Column(db.Text)
    source_editorial = db.Column(db.Text)
    date = db.Column(db.Date)
    collection_name = db.Column(db.Text)
    gai_engine = db.Column(db.Text)
    gai_promptid = db.Column(db.Text)
    gai_promptversion = db.Column(db.Integer)
    salience_justification = db.Column(db.Text)
    salience_bool = db.Column(db.Text)
    category = db.Column(db.Text)
    category_justification = db.Column(db.Text)
    subcategory = db.Column(db.Text)
    initiating_country = db.Column(db.Text)
    recipient_country = db.Column(db.Text)
    projects = db.Column(db.Text)
    lat_long = db.Column(db.Text)
    location = db.Column(db.Text)
    monetary_commitment = db.Column(db.Text)
    distilled_text = db.Column(db.Text)
    event_name = db.Column(db.Text)


    categories = db.relationship("Category", backref="document", lazy="dynamic")
    subcategories = db.relationship("Subcategory", backref="document", lazy="dynamic")
    initiating_countries = db.relationship("InitiatingCountry", backref="document", lazy="dynamic")
    recipient_countries = db.relationship("RecipientCountry", backref="document", lazy="dynamic")
    proj = db.relationship("Project", backref="document", lazy="dynamic")
    
    events = db.relationship(
        "Event",
        secondary="event_sources",
        back_populates="documents",
        lazy="dynamic",
    )
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class Salience(db.Model):
    __tablename__ = 'salience'
    doc_id = db.Column(db.Text, primary_key=True)
    salience = db.Column(db.Text)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class Category(db.Model):
    __tablename__ = 'categories'
    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'))
    category = db.Column(db.Text)
    __table_args__ = (db.PrimaryKeyConstraint('doc_id', 'category'),)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
class Subcategory(db.Model):
    __tablename__ = 'subcategories'
    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'))
    subcategory = db.Column(db.Text)
    __table_args__ = (db.PrimaryKeyConstraint('doc_id', 'subcategory'),)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class InitiatingCountry(db.Model):
    __tablename__ = 'initiating_countries'
    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'))
    initiating_country = db.Column(db.Text)
    __table_args__ = (db.PrimaryKeyConstraint('doc_id', 'initiating_country'),)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class RecipientCountry(db.Model):
    __tablename__ = 'recipient_countries'
    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'))
    recipient_country = db.Column(db.Text)
    __table_args__ = (db.PrimaryKeyConstraint('doc_id', 'recipient_country'),)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
class Project(db.Model):
    __tablename__ = 'projects'

    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'))
    project = db.Column(db.Text)
    __table_args__ = (db.PrimaryKeyConstraint('doc_id', 'project'),)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_name = db.Column(db.Text, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)
    recipient_country = db.Column(db.Text, nullable=False)
    material_score = db.Column(db.Integer)
    material_score_justification = db.Column(db.Text)

    __table_args__ = (
        # preserve uniqueness but no longer as the PK
        db.UniqueConstraint(
            'event_name',
            'initiating_country',
            'recipient_country',
            name='uq_events_name_countries'
        ),
    )
    documents = db.relationship(
        "Document",
        secondary="event_sources",
        back_populates="events",
        lazy="dynamic",
    )
    
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class EventSources(db.Model):
    __tablename__ = 'event_sources'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'))
    __table_args__ = (
        UniqueConstraint(
            'event_id', 'doc_id', name='uq_event_source_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class RawEvent(db.Model):
    __tablename__ = 'raw_events'

    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'))
    event_name = db.Column(db.Text)
    __table_args__ = (db.PrimaryKeyConstraint('doc_id', 'event_name'),)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class Citation(db.Model):
    __tablename__ = 'citations'

    doc_id = db.Column(db.Text, db.ForeignKey('documents.doc_id'), primary_key=True)
    citation = db.Column(db.Text)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SoftPowerActivity(db.Model):
    __tablename__ = 'soft_power_activities'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date)
    initiating_country = db.Column(db.Text)
    recipient_country = db.Column(db.Text)
    category = db.Column(db.Text)
    subcategory = db.Column(db.Text)
    description = db.Column(db.Text)
    significance = db.Column(db.Text)
    entities = db.Column(db.Text)
    sources = db.Column(db.Text)
    event_name = db.Column(db.Text)
    lat_long = db.Column(db.Text)
    material_score = db.Column(db.Integer)
    material_score_justification = db.Column(db.Text)
    __table_args__ = (
        UniqueConstraint(
            'date', 'initiating_country', 'recipient_country', 'event_name',
            name='uq_activity_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
class SoftPowerActivitySource(db.Model):
    __tablename__ = 'softpower_activity_sources'

    sp_id = db.Column(db.Integer, db.ForeignKey('soft_power_activities.id'), primary_key=True)
    doc_id = db.Column(db.Text, primary_key=True)  # <- make this part of the primary key

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
        
class SoftPowerEntity(db.Model):
    __tablename__ = 'softpower_entities'

    sp_id = db.Column(db.Integer, db.ForeignKey('soft_power_activities.id'), primary_key=True)
    entity = db.Column(db.Text, primary_key=True)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SoftPowerActivityCategory(db.Model):
    __tablename__ = 'softpower_activity_categories'

    sp_id = db.Column(db.Integer, db.ForeignKey('soft_power_activities.id'), primary_key=True)
    category = db.Column(db.Text, primary_key=True)  # <-- make part of PK
    category_material_score = db.Column(db.Integer)
    category_score_justification = db.Column(db.Text)

    # UniqueConstraint is now redundant; remove it
    # __table_args__ = (... )  # delete this
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SoftPowerActivitySubcategory(db.Model):
    __tablename__ = 'softpower_activity_subcategories'
    sp_id = db.Column(db.Integer, db.ForeignKey('soft_power_activities.id'), primary_key=True)
    subcategory = db.Column(db.Text)
    __table_args__ = (
        UniqueConstraint(
            'sp_id', 'subcategory', name='uq_activity_subcategory_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class EventCluster(db.Model):
    __tablename__ = 'event_clusters'
    
    id = db.Column(db.Integer, primary_key=True)
    normalized_event_name = db.Column(db.String, nullable=False)
    country = db.Column(db.String, nullable=True)  # Optional
    created_at = db.Column(db.DateTime, default=db.func.now())
    # Event date range (based on linked docs)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    # Relationships
    original_names = db.relationship('EventClusterName', back_populates='cluster', cascade="all, delete-orphan")
    documents = db.relationship('EventClusterDocument', back_populates='cluster', cascade="all, delete-orphan")

class EventClusterName(db.Model):
    __tablename__ = 'event_cluster_names'

    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('event_clusters.id'), nullable=False)
    original_event_name = db.Column(db.String, nullable=False)

    cluster = db.relationship('EventCluster', back_populates='original_names')

class EventClusterDocument(db.Model):
    __tablename__ = 'event_cluster_documents'

    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('event_clusters.id'), nullable=False)
    doc_id = db.Column(db.String, nullable=False, index=True)
    publication_date = db.Column(db.Date, nullable=True)

    cluster = db.relationship('EventCluster', back_populates='documents')

class EventSummary(db.Model):
    __tablename__ = 'event_summaries'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    doc_ids = db.Column(db.Text)
    event_name = db.Column(db.Text)
    event_title = db.Column(db.Text)
    atom_start_date = db.Column(db.Date)
    atom_end_date = db.Column(db.Date)
    event_summary = db.Column(db.Text)
    event_latlong = db.Column(db.Text)
    event_location = db.Column(db.Text)
    monetary_value = db.Column(db.Text)  # JSON string of monetary values
    entities = db.Column(db.Text)
    commitments = db.Column(db.Text)  # JSON string of commitments
    metrics = db.Column(db.Text)
    status = db.Column(db.Text)
    status_date = db.Column(db.Date)
    __table_args__ = (
        UniqueConstraint(
            'event_id', 'event_name', name='uq_event_summary_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class EventEntities(db.Model):
    __tablename__ = 'event_entities'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    event_summary_id = db.Column(db.Integer, db.ForeignKey('event_summaries.id'))
    entity = db.Column(db.Text)
    __table_args__ = (
        UniqueConstraint(
            'event_id', 'entity', name='uq_event_entity_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
       
class Commitments(db.Model):
    __tablename__ = 'commitments'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    event_summary_id = db.Column(db.Integer, db.ForeignKey('event_summaries.id'))
    commitment_purpose = db.Column(db.Text)
    commitment_description = db.Column(db.Text)
    commitment_amount = db.Column(BigInteger)  # JSON string of monetary values
    commitment_status = db.Column(db.Text)
    __table_args__ = (
        UniqueConstraint(
            'event_id', 'commitment_purpose', name='uq_commitment_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class DailySummary(db.Model):
    __tablename__ = 'daily_summaries'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = db.Column(db.Date, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)

    # Flattened Lists
    recipient_countries = db.Column(JSONB, default=list)
    categories = db.Column(JSONB, default=list)
    subcategories = db.Column(JSONB, default=list)
    entities = db.Column(JSONB, default=list)

    # Aggregated Stats
    total_articles = db.Column(db.Integer, default=0)
    total_events = db.Column(db.Integer, default=0)
    total_sources = db.Column(db.Integer, default=0)
    symbolic_event_count = db.Column(db.Integer, default=0)
    material_event_count = db.Column(db.Integer, default=0)

    # Material Score Stats
    avg_material_score = db.Column(db.Float)
    median_material_score = db.Column(db.Float)
    material_score_stddev = db.Column(db.Float)

    # Detailed Counts and Breakdown
    count_by_category = db.Column(JSONB, default=dict)
    count_by_subcategory = db.Column(JSONB, default=dict)
    count_by_recipient = db.Column(JSONB, default=dict)
    count_by_entity = db.Column(JSONB, default=dict)
    material_score_by_category = db.Column(JSONB, default=dict)

    # Generated Summary Text
    aggregate_summary = db.Column(db.Text)

    # Optional: timestamps
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, onupdate=db.func.now())

    # Relationships (View-only to source events)
    daily_event_summaries = db.relationship(
        "DailyEventSummary",
        primaryjoin="and_(DailySummary.date==foreign(DailyEventSummary.report_date), "
                    "DailySummary.initiating_country==foreign(DailyEventSummary.initiating_country))",
        viewonly=True,
        lazy='dynamic'
    )

    # Relationships to flattened entity models
    flat_entities = db.relationship("DailySummaryEntity", backref="summary", cascade="all, delete-orphan")
    flat_recipients = db.relationship("DailySummaryRecipientCountry", backref="summary", cascade="all, delete-orphan")
    flat_categories = db.relationship("DailySummaryCategory", backref="summary", cascade="all, delete-orphan")
    flat_subcategories = db.relationship("DailySummarySubcategory", backref="summary", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('date', 'initiating_country', name='uq_daily_composite'),
        Index('ix_summary_date', 'date'),
        Index('ix_summary_initiating_country', 'initiating_country'),
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class DailySummaryEntity(db.Model):
    __tablename__ = 'daily_summary_entities'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = db.Column(db.Text, nullable=False)
    count = db.Column(db.Integer, default=1)

    __table_args__ = (
        Index('ix_entity_summary', 'summary_id'),
    )

class DailySummaryRecipientCountry(db.Model):
    __tablename__ = 'daily_summary_recipients'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = db.Column(db.Text, nullable=False)
    count = db.Column(db.Integer, default=1)

class DailySummaryCategory(db.Model):
    __tablename__ = 'daily_summary_categories'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = db.Column(db.Text, nullable=False)
    count = db.Column(db.Integer, default=1)
    avg_material_score = db.Column(db.Float)

class DailySummarySubcategory(db.Model):
    __tablename__ = 'daily_summary_subcategories'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id = db.Column(db.UUID(as_uuid=True), db.ForeignKey('daily_summaries.id', ondelete='CASCADE'))
    name = db.Column(db.Text, nullable=False)
    count = db.Column(db.Integer, default=1)

class EntitySummary(db.Model):
    __tablename__ = 'entities'
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    initiating_country = db.Column(db.Text)
    recipient_country = db.Column(db.Text)
    entity = db.Column(db.Text)
    entity_type = db.Column(db.Text)
    entity_summary = db.Column(db.Text)
    activity_ids = db.Column(db.Text)
    __table_args__ = (
        UniqueConstraint(
            'start_date','end_date','initiating_country','recipient_country','entity',
            name='uq_entity_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class CountrySummary(db.Model):
    __tablename__ = 'country_summary'
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.Text)
    key_event = db.Column(db.Text)
    start_date = db.Column(db.Text)
    end_date = db.Column(db.Text)
    category = db.Column(db.Text)
    overview = db.Column(db.Text)
    outcome = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint(
            'country', 'key_event', 'start_date', 'end_date', 'category',
            name='uq_country_event_window_category'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
class RecipientSummary(db.Model):
    __tablename__ = 'recipient_summary'
    id = db.Column(db.Integer)
    country = db.Column(db.Text,primary_key=True)
    recipient = db.Column(db.Text,primary_key=True)
    key_event = db.Column(db.Text,primary_key=True)
    start_date = db.Column(db.Text,primary_key=True)
    end_date = db.Column(db.Text,primary_key=True)
    category = db.Column(db.Text,primary_key=True)
    overview = db.Column(db.Text)
    outcome = db.Column(db.Text)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SummarySources(db.Model):
    __tablename__ = 'summary_sources'
    summary_id = db.Column(db.Integer, db.ForeignKey('country_summary.id'), primary_key=True)
    summary_type = db.Column(db.Text, primary_key=True)
    doc_id = db.Column(db.Text, primary_key=True)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class SummaryClaims(db.Model):
    id = db.Column(db.Integer)
    summary_id = db.Column(db.Integer, db.ForeignKey('country_summary.id'), primary_key=True)
    section = db.Column(db.Text)
    claim = db.Column(db.Text)
    doc_id = db.Column(db.Text, primary_key=True)
    citation = db.Column(db.Text)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class TokenizedDocuments(db.Model):
    __tablename__ = 'tokenized_documents'
    doc_id = db.Column(db.Text,primary_key=True)
    tokens = db.Column(db.Text)
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

class RecipientDaily(db.Model):
    __tablename__ = 'recipient_daily_summaries'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date)
    initiating_country = db.Column(db.Text)
    recipient_country = db.Column(db.Text)
    categories = db.Column(db.Text)
    subcategories = db.Column(db.Text)
    total_articles = db.Column(db.Integer)
    count_by_category = db.Column(db.Text)
    count_by_subcategory = db.Column(db.Text)
    count_by_recipient = db.Column(db.Text)
    aggregate_summary = db.Column(db.Text)
    __table_args__ = (
        UniqueConstraint(
            'date', 'initiating_country', 'recipient_country',
            name='uq_rec_daily_composite'
        ),
    )
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class DailyEvent(db.Model):
    __tablename__ = "daily_events"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_name = db.Column(db.Text, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)
    report_date = db.Column(db.Date, nullable=False)

    # relationship to sources
    sources = relationship(
        "DailyEventSource",
        back_populates="event",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<DailyEvent(id={self.id}, name={self.event_name})>"


class DailyEventSource(db.Model):
    __tablename__ = "daily_event_sources"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # foreign keys
    event_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("daily_events.id", ondelete="CASCADE"),
        nullable=False
    )
    doc_id = db.Column(
        db.String,
        db.ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False
    )

    # relationships
    event = relationship("DailyEvent", back_populates="sources")
    document = relationship("Document")

    __table_args__ = (
        UniqueConstraint("event_id", "doc_id", name="uq_event_doc"),
        db.Index("ix_event_id", "event_id"),
        db.Index("ix_doc_id", "doc_id"),
    )

    def __repr__(self):
        return f"<DailyEventSource(id={self.id}, event_id={self.event_id}, doc_id={self.doc_id})>"

class DailyEventSummary(db.Model):
    __tablename__ = "daily_event_summaries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key to the event this summary is based on
    event_id = db.Column(UUID(as_uuid=True), db.ForeignKey("daily_events.id", ondelete="CASCADE"), nullable=False)

    # Core metadata
    report_date = db.Column(db.Date, nullable=False)
    event_name = db.Column(db.Text, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)

    # Inferred or LLM-evaluated fields
    recipient_countries = db.Column(JSONB)  # List[str]
    categories = db.Column(JSONB)           # List[str]
    subcategories = db.Column(JSONB)        # List[str]
    entities = db.Column(JSONB)             # List[str]
    material_score = db.Column(db.Integer)
    material_score_justification = db.Column(db.Text)
    event_hyperlink = db.Column(db.Text)
    summary_text = db.Column(db.Text)

    # Source aggregation metadata
    document_count = db.Column(db.Integer)
    unique_source_count = db.Column(db.Integer)

    # Bookkeeping
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    categories_flat = db.relationship("DailyEventCategory", back_populates="summary", cascade="all, delete-orphan")
    subcategories_flat = db.relationship("DailyEventSubcategory", back_populates="summary", cascade="all, delete-orphan")
    recipient_countries_flat = db.relationship("DailyEventRecipientCountry", back_populates="summary", cascade="all, delete-orphan")
    entities_flat = db.relationship("DailyEventEntity", back_populates="summary", cascade="all, delete-orphan")
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
class DailyEventCategory(db.Model):
    __tablename__ = "daily_event_categories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = db.Column(UUID(as_uuid=True), db.ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    category = db.Column(db.Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="categories_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "category", name="uq_summary_category"),
    )


# Subcategory Link
class DailyEventSubcategory(db.Model):
    __tablename__ = "daily_event_subcategories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = db.Column(UUID(as_uuid=True), db.ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    subcategory = db.Column(db.Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="subcategories_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "subcategory", name="uq_summary_subcategory"),
    )


# Recipient Country Link
class DailyEventRecipientCountry(db.Model):
    __tablename__ = "daily_event_recipient_countries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = db.Column(UUID(as_uuid=True), db.ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    country = db.Column(db.Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="recipient_countries_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "country", name="uq_summary_recipient_country"),
    )


# Entity Link
class DailyEventEntity(db.Model):
    __tablename__ = "daily_event_entities"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    daily_event_summary_id = db.Column(UUID(as_uuid=True), db.ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)
    entity = db.Column(db.Text, nullable=False)

    summary = relationship("DailyEventSummary", back_populates="entities_flat")

    __table_args__ = (
        UniqueConstraint("daily_event_summary_id", "entity", name="uq_summary_entity"),
    )

class DailySummaryEventLink(db.Model):
    __tablename__ = "daily_summary_event_links"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    daily_summary_id = db.Column(UUID(as_uuid=True), db.ForeignKey("daily_summaries.id", ondelete="CASCADE"), nullable=False)
    event_summary_id = db.Column(UUID(as_uuid=True), db.ForeignKey("daily_event_summaries.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("daily_summary_id", "event_summary_id", name="uq_daily_summary_event"),
    )
    
class WeeklyEvent(db.Model):
    __tablename__ = "weekly_events"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Rollup window
    week_start = db.Column(db.Date, nullable=False)
    week_end   = db.Column(db.Date, nullable=False)

    # Core deduped event data
    event_name = db.Column(db.Text, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)
    first_observed_date = db.Column(db.Date, nullable=False)
    last_observed_date  = db.Column(db.Date, nullable=False)

    # Container link (to WeeklySummary)
    weekly_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
        nullable=True
    )
    weekly_summary = db.relationship("WeeklySummary", back_populates="events")

    # Relationships
    sources = db.relationship(
        "WeeklyEventLink",
        back_populates="event",
        cascade="all, delete-orphan"
    )
    summaries = db.relationship(
        "WeeklyEventSummary",
        back_populates="event",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "week_start", "week_end", "initiating_country", "event_name",
            name="uq_weekly_event"
        ),
    )


class WeeklySummary(db.Model):
    __tablename__ = "weekly_summaries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    week_start = db.Column(db.Date, nullable=False)
    week_end   = db.Column(db.Date, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)

    # Observed window
    first_observed_date = db.Column(db.Date, nullable=False)
    last_observed_date  = db.Column(db.Date, nullable=False)
    distinct_observed_dates = db.Column(ARRAY(db.Date))
    num_observed_days   = db.Column(db.Integer)

    # Aggregated prose (from LLM prompts)
    weekly_overview = db.Column(db.Text)
    weekly_outcome  = db.Column(db.Text)
    weekly_metrics  = db.Column(db.Text)

    # Aggregated metrics
    num_articles       = db.Column(db.Integer)
    num_unique_sources = db.Column(db.Integer)
    num_recipients     = db.Column(db.Integer)
    num_entities       = db.Column(db.Integer)
    num_weekly_events  = db.Column(db.Integer)

    avg_material_score    = db.Column(db.Float)
    median_material_score = db.Column(db.Float)
    material_score_stddev = db.Column(db.Float)

    count_by_category    = db.Column(JSONB)
    count_by_subcategory = db.Column(JSONB)
    count_by_recipient   = db.Column(JSONB)
    count_by_source      = db.Column(JSONB)

    avg_material_score_by_category    = db.Column(JSONB)
    avg_material_score_by_subcategory = db.Column(JSONB)
    score_distribution_by_category    = db.Column(JSONB)
    score_distribution_by_subcategory = db.Column(JSONB)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    events = db.relationship(
        "WeeklyEvent",
        back_populates="weekly_summary",
        cascade="all, delete-orphan"
    )
    links = db.relationship(
        "WeeklySummaryEventLink",
        back_populates="weekly_summary",
        cascade="all, delete-orphan"
    )
    # monthly_links = db.relationship(
    #     "MonthlySummaryWeeklyLink",
    #     back_populates="weekly_summary",
    #     cascade="all, delete-orphan"
    # )
    
    __table_args__ = (
        db.UniqueConstraint("week_start", "week_end", "initiating_country", name="uq_weekly_summary"),
    )


class WeeklyEventLink(db.Model):
    __tablename__ = "weekly_event_links"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_events.id", ondelete="CASCADE"),
        nullable=False
    )
    daily_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("daily_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )

    event = relationship("WeeklyEvent", back_populates="sources")
    daily_summary = relationship("DailyEventSummary")

    __table_args__ = (
        UniqueConstraint("event_id", "daily_summary_id", name="uq_weekly_event_daily_summary"),
    )


class WeeklyEventSummary(db.Model):
    __tablename__ = "weekly_event_summaries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_events.id", ondelete="CASCADE"),
        nullable=False
    )

    # Core metadata
    event_name = db.Column(db.Text, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)

    # Inferred or LLM-evaluated fields
    recipient_countries = db.Column(JSONB)
    categories          = db.Column(JSONB)
    subcategories       = db.Column(JSONB)
    entities            = db.Column(JSONB)
    material_score = db.Column(db.Integer)
    material_score_justification = db.Column(db.Text)
    event_hyperlink = db.Column(db.Text)
    summary_text = db.Column(db.Text)

    # Source aggregation metadata
    document_count = db.Column(db.Integer)
    unique_source_count = db.Column(db.Integer)

    # 🔢 Metrics rollup (per event, per week)
    num_articles       = db.Column(db.Integer)
    num_unique_sources = db.Column(db.Integer)
    num_recipients     = db.Column(db.Integer)
    num_entities       = db.Column(db.Integer)

    avg_material_score    = db.Column(db.Float)
    median_material_score = db.Column(db.Float)
    material_score_stddev = db.Column(db.Float)

    count_by_category    = db.Column(JSONB)
    count_by_subcategory = db.Column(JSONB)
    count_by_recipient   = db.Column(JSONB)
    count_by_source      = db.Column(JSONB)

    avg_material_score_by_category    = db.Column(JSONB)
    avg_material_score_by_subcategory = db.Column(JSONB)
    score_distribution_by_category    = db.Column(JSONB)
    score_distribution_by_subcategory = db.Column(JSONB)

    # Bookkeeping
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    categories_flat = db.relationship("WeeklyEventCategory", back_populates="summary", cascade="all, delete-orphan")
    subcategories_flat = db.relationship("WeeklyEventSubcategory", back_populates="summary", cascade="all, delete-orphan")
    recipient_countries_flat = db.relationship("WeeklyEventRecipientCountry", back_populates="summary", cascade="all, delete-orphan")
    entities_flat = db.relationship("WeeklyEventEntity", back_populates="summary", cascade="all, delete-orphan")

    event = db.relationship("WeeklyEvent", back_populates="summaries")
    monthly_links = relationship(
        "MonthlySummaryWeeklyLink",
        back_populates="weekly_event_summary",
        cascade="all, delete-orphan"
    )
class WeeklyEventCategory(db.Model):
    __tablename__ = "weekly_event_categories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    category = db.Column(db.Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="categories_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "category", name="uq_weekly_summary_category"),
    )


class WeeklyEventSubcategory(db.Model):
    __tablename__ = "weekly_event_subcategories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    subcategory = db.Column(db.Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="subcategories_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "subcategory", name="uq_weekly_summary_subcategory"),
    )


class WeeklyEventRecipientCountry(db.Model):
    __tablename__ = "weekly_event_recipient_countries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    country = db.Column(db.Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="recipient_countries_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "country", name="uq_weekly_summary_recipient_country"),
    )


class WeeklyEventEntity(db.Model):
    __tablename__ = "weekly_event_entities"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    entity = db.Column(db.Text, nullable=False)

    summary = relationship("WeeklyEventSummary", back_populates="entities_flat")

    __table_args__ = (
        UniqueConstraint("weekly_event_summary_id", "entity", name="uq_weekly_summary_entity"),
    )

class WeeklySummaryEventLink(db.Model):
    __tablename__ = "weekly_summary_event_links"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    weekly_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    daily_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("daily_summaries.id", ondelete="CASCADE"),
        nullable=False
    )

    weekly_summary = relationship("WeeklySummary", back_populates="links")
    daily_summary = relationship("DailySummary")

    __table_args__ = (
        UniqueConstraint("weekly_summary_id", "daily_summary_id", name="uq_weekly_summary_daily_summary"),
    )

class MonthlyEventLink(db.Model):
    __tablename__ = "monthly_event_links"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = db.Column(UUID(as_uuid=True), db.ForeignKey("monthly_events.id", ondelete="CASCADE"), nullable=False)
    weekly_event_id = db.Column(UUID(as_uuid=True), db.ForeignKey("weekly_events.id", ondelete="CASCADE"), nullable=False)

    event = db.relationship("MonthlyEvent", back_populates="sources")
    weekly_event = db.relationship("WeeklyEvent")

    __table_args__ = (
        db.UniqueConstraint("event_id", "weekly_event_id", name="uq_monthly_event_weekly_event"),
    )


# class MonthlySummaryWeeklyLink(db.Model):
#     __tablename__ = "monthly_summary_weekly_links"

#     id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

#     monthly_summary_id = db.Column(
#         UUID(as_uuid=True),
#         db.ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )
#     weekly_summary_id = db.Column(
#         UUID(as_uuid=True),
#         db.ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )

#     monthly_summary = db.relationship("MonthlySummary", back_populates="links")
#     weekly_summary = db.relationship("WeeklySummary", back_populates="monthly_links")

#     __table_args__ = (
#         db.UniqueConstraint("monthly_summary_id", "weekly_summary_id", name="uq_monthly_summary_weekly"),
#     )

class MonthlyEventSummary(db.Model):
    __tablename__ = "monthly_event_summaries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("monthly_events.id", ondelete="CASCADE"),
        nullable=False
    )

    # Core metadata
    event_name = db.Column(db.Text, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)

    # Inferred or LLM-evaluated fields
    recipient_countries = db.Column(JSONB)
    categories          = db.Column(JSONB)
    subcategories       = db.Column(JSONB)
    entities            = db.Column(JSONB)

    material_score = db.Column(db.Integer)
    material_score_justification = db.Column(db.Text)
    event_hyperlink = db.Column(db.Text)

    summary_text = db.Column(db.Text)   # overview paragraph
    outcome_text = db.Column(db.Text)   # outcome paragraph
    metrics_text = db.Column(db.Text)   # metrics paragraph

    # 🔢 Metrics rollup (per event, per month)
    num_articles       = db.Column(db.Integer)       # replaces document_count
    num_unique_sources = db.Column(db.Integer)       # replaces unique_source_count
    num_recipients     = db.Column(db.Integer)
    num_entities       = db.Column(db.Integer)

    avg_material_score    = db.Column(db.Float)
    median_material_score = db.Column(db.Float)
    material_score_stddev = db.Column(db.Float)

    count_by_category    = db.Column(JSONB)
    count_by_subcategory = db.Column(JSONB)
    count_by_recipient   = db.Column(JSONB)
    count_by_source      = db.Column(JSONB)

    avg_material_score_by_category    = db.Column(JSONB)
    avg_material_score_by_subcategory = db.Column(JSONB)
    score_distribution_by_category    = db.Column(JSONB)
    score_distribution_by_subcategory = db.Column(JSONB)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    categories_flat = db.relationship("MonthlyEventCategory", back_populates="summary", cascade="all, delete-orphan")
    subcategories_flat = db.relationship("MonthlyEventSubcategory", back_populates="summary", cascade="all, delete-orphan")
    recipient_countries_flat = db.relationship("MonthlyEventRecipientCountry", back_populates="summary", cascade="all, delete-orphan")
    entities_flat = db.relationship("MonthlyEventEntity", back_populates="summary", cascade="all, delete-orphan")

    # Parent event
    event = db.relationship("MonthlyEvent", back_populates="summaries")

    __table_args__ = (
        db.UniqueConstraint("event_id", name="uq_monthly_event_summary_event"),
    )
class MonthlySummary(db.Model):
    __tablename__ = "monthly_summaries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    month_start = db.Column(db.Date, nullable=False)
    month_end   = db.Column(db.Date, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)

    first_observed_date = db.Column(db.Date, nullable=False)
    last_observed_date  = db.Column(db.Date, nullable=False)
    distinct_observed_dates = db.Column(ARRAY(db.Date))
    num_observed_days   = db.Column(db.Integer)

    monthly_overview = db.Column(db.Text)
    monthly_outcome  = db.Column(db.Text)
    monthly_metrics  = db.Column(db.Text)

    num_articles       = db.Column(db.Integer)
    num_unique_sources = db.Column(db.Integer)
    num_recipients     = db.Column(db.Integer)
    num_entities       = db.Column(db.Integer)
    num_monthly_events = db.Column(db.Integer)

    avg_material_score    = db.Column(db.Float)
    median_material_score = db.Column(db.Float)
    material_score_stddev = db.Column(db.Float)

    count_by_category    = db.Column(JSONB)
    count_by_subcategory = db.Column(JSONB)
    count_by_recipient   = db.Column(JSONB)
    count_by_source      = db.Column(JSONB)

    avg_material_score_by_category    = db.Column(JSONB)
    avg_material_score_by_subcategory = db.Column(JSONB)
    score_distribution_by_category    = db.Column(JSONB)
    score_distribution_by_subcategory = db.Column(JSONB)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    events = db.relationship(
        "MonthlyEvent",
        back_populates="monthly_summary",
        cascade="all, delete-orphan"
    )

    weekly_links = db.relationship(
        "MonthlySummaryWeeklyLink",
        back_populates="monthly_summary",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("month_start", "month_end", "initiating_country", name="uq_monthly_summary"),
    )

class MonthlyEvent(db.Model):
    __tablename__ = "monthly_events"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    month_start = db.Column(db.Date, nullable=False)
    month_end   = db.Column(db.Date, nullable=False)

    event_name = db.Column(db.Text, nullable=False)
    initiating_country = db.Column(db.Text, nullable=False)
    first_observed_date = db.Column(db.Date, nullable=False)
    last_observed_date  = db.Column(db.Date, nullable=False)

    monthly_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
        nullable=True
    )
    monthly_summary = db.relationship("MonthlySummary", back_populates="events")

    sources = db.relationship(
        "MonthlyEventLink",
        back_populates="event",
        cascade="all, delete-orphan"
    )
    summaries = db.relationship(
        "MonthlyEventSummary",
        back_populates="event",
        cascade="all, delete-orphan"
    )
# class MonthlySummaryEventLink(db.Model):
#     __tablename__ = "monthly_summary_event_links"

#     id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#     monthly_summary_id = db.Column(
#         UUID(as_uuid=True),
#         db.ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )

#     weekly_summary_id = db.Column(
#         UUID(as_uuid=True),
#         db.ForeignKey("weekly_summaries.id", ondelete="CASCADE"),
#         nullable=False
#     )

#     monthly_summary = db.relationship("MonthlySummary", back_populates="event_links")
#     weekly_summary = relationship("WeeklySummary")

#     __table_args__ = (
#         UniqueConstraint("monthly_summary_id", "weekly_summary_id", name="uq_monthly_summary_weekly_summary"),
#     )

class MonthlySummaryWeeklyLink(db.Model):
    __tablename__ = "monthly_summary_weekly_links"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    monthly_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("monthly_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    weekly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("weekly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )

    monthly_summary = relationship("MonthlySummary", back_populates="weekly_links")
    weekly_event_summary = relationship("WeeklyEventSummary", back_populates="monthly_links")

    __table_args__ = (
        db.UniqueConstraint(
            "monthly_summary_id", "weekly_event_summary_id",
            name="uq_monthly_summary_weekly_event_summary"
        ),
    )

class MonthlyEventCategory(db.Model):
    __tablename__ = "monthly_event_categories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    category = db.Column(db.Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="categories_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "category", name="uq_monthly_summary_category"),
    )


class MonthlyEventSubcategory(db.Model):
    __tablename__ = "monthly_event_subcategories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    subcategory = db.Column(db.Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="subcategories_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "subcategory", name="uq_monthly_summary_subcategory"),
    )


class MonthlyEventRecipientCountry(db.Model):
    __tablename__ = "monthly_event_recipient_countries"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    country = db.Column(db.Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="recipient_countries_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "country", name="uq_monthly_summary_recipient_country"),
    )


class MonthlyEventEntity(db.Model):
    __tablename__ = "monthly_event_entities"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monthly_event_summary_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("monthly_event_summaries.id", ondelete="CASCADE"),
        nullable=False
    )
    entity = db.Column(db.Text, nullable=False)

    summary = relationship("MonthlyEventSummary", back_populates="entities_flat")

    __table_args__ = (
        UniqueConstraint("monthly_event_summary_id", "entity", name="uq_monthly_summary_entity"),
    )


class BayesianResult(db.Model):
    __tablename__ = "bayesian_results"

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    initiator = db.Column(db.Text, nullable=False)       # e.g. "China"
    recipient = db.Column(db.Text, nullable=False)       # e.g. "Egypt"
    category = db.Column(db.Text, nullable=False)        # e.g. "Economic"
    subcategory = db.Column(db.Text, nullable=True)      # e.g. "Tourism"

    # method encodes both inference type and metric, e.g. "advi_material_score"
    method = db.Column(db.Text, nullable=False)          

    prob_increase = db.Column(db.Float, nullable=True)   # P(beta > 0)
    mean = db.Column(JSONB, default=list)                # predictive mean series
    lower = db.Column(JSONB, default=list)               # lower bound (5th percentile)
    upper = db.Column(JSONB, default=list)               # upper bound (95th percentile)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # 🔑 New metadata column for jump flags, etc.
    meta = db.Column(JSONB, default=dict)

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