"""
Entity models for soft power network mapping.

These models support extraction and storage of organizations, companies, and key persons
involved in soft power transactions, along with their relationships.
"""

import uuid
from datetime import datetime
from datetime import date as DateType
from typing import List, Dict, Optional, Any
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Text, Date, Float,
    DateTime, Boolean, ForeignKey, UniqueConstraint, Index,
    func, Enum, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from shared.database.database import Base


# ============================================================================
# Enums
# ============================================================================

class EntityType(PyEnum):
    """Types of entities that can be extracted"""
    PERSON = "PERSON"
    GOVERNMENT_AGENCY = "GOVERNMENT_AGENCY"
    STATE_OWNED_ENTERPRISE = "STATE_OWNED_ENTERPRISE"
    PRIVATE_COMPANY = "PRIVATE_COMPANY"
    MULTILATERAL_ORG = "MULTILATERAL_ORG"
    NGO = "NGO"
    EDUCATIONAL_INSTITUTION = "EDUCATIONAL_INSTITUTION"
    FINANCIAL_INSTITUTION = "FINANCIAL_INSTITUTION"
    MILITARY_UNIT = "MILITARY_UNIT"
    MEDIA_ORGANIZATION = "MEDIA_ORGANIZATION"
    RELIGIOUS_ORGANIZATION = "RELIGIOUS_ORGANIZATION"


class EntitySide(PyEnum):
    """Which side of a soft power transaction the entity is on"""
    INITIATING = "initiating"
    RECIPIENT = "recipient"
    THIRD_PARTY = "third_party"


class RelationshipType(PyEnum):
    """Types of relationships between entities"""
    FUNDS = "FUNDS"
    INVESTS_IN = "INVESTS_IN"
    CONTRACTS_WITH = "CONTRACTS_WITH"
    PARTNERS_WITH = "PARTNERS_WITH"
    SIGNS_AGREEMENT = "SIGNS_AGREEMENT"
    MEETS_WITH = "MEETS_WITH"
    EMPLOYS = "EMPLOYS"
    OWNS = "OWNS"
    REPRESENTS = "REPRESENTS"
    HOSTS = "HOSTS"
    TRAINS = "TRAINS"
    SUPPLIES = "SUPPLIES"
    MEDIATES = "MEDIATES"
    ANNOUNCES = "ANNOUNCES"
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    MEMBER_OF = "MEMBER_OF"


# ============================================================================
# Core Entity Model
# ============================================================================

class Entity(Base):
    """
    Canonical entity representing an organization, company, or person.

    This is the deduplicated, resolved entity that multiple document mentions
    may reference.
    """
    __tablename__ = 'entities'

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Core identity
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Country affiliation
    country: Mapped[Optional[str]] = mapped_column(Text)  # Primary country

    # For persons - title and organization
    title: Mapped[Optional[str]] = mapped_column(Text)  # "Foreign Minister", "CEO"
    parent_organization_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('entities.id'),
        nullable=True
    )

    # Deduplication support
    aliases: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list)
    embedding_vector: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float))

    # Tracking
    first_seen_date: Mapped[Optional[DateType]] = mapped_column(Date)
    last_seen_date: Mapped[Optional[DateType]] = mapped_column(Date)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)

    # Primary domains this entity operates in (aggregated from mentions)
    primary_topics: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict)  # topic -> count
    primary_roles: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict)   # role -> count

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=datetime.utcnow)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # Human verified
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    document_mentions = relationship("DocumentEntity", back_populates="entity")
    parent_organization = relationship("Entity", remote_side=[id], backref="subsidiaries")

    # Relationships where this entity is the source
    outgoing_relationships = relationship(
        "EntityRelationship",
        foreign_keys="EntityRelationship.source_entity_id",
        back_populates="source_entity"
    )

    # Relationships where this entity is the target
    incoming_relationships = relationship(
        "EntityRelationship",
        foreign_keys="EntityRelationship.target_entity_id",
        back_populates="target_entity"
    )

    __table_args__ = (
        Index("ix_entity_canonical_name", "canonical_name"),
        Index("ix_entity_type", "entity_type"),
        Index("ix_entity_country", "country"),
        Index("ix_entity_mention_count", "mention_count"),
        # GIN index for alias search
        Index("ix_entity_aliases", "aliases", postgresql_using="gin"),
    )

    @property
    def is_person(self) -> bool:
        return self.entity_type == EntityType.PERSON.value

    @property
    def is_organization(self) -> bool:
        return self.entity_type != EntityType.PERSON.value

    @property
    def top_topic(self) -> Optional[str]:
        """Get the most common topic for this entity"""
        if not self.primary_topics:
            return None
        return max(self.primary_topics, key=self.primary_topics.get)

    @property
    def top_role(self) -> Optional[str]:
        """Get the most common role for this entity"""
        if not self.primary_roles:
            return None
        return max(self.primary_roles, key=self.primary_roles.get)

    def add_alias(self, alias: str):
        """Add a new alias if not already present"""
        if alias and alias not in self.aliases and alias != self.canonical_name:
            self.aliases = self.aliases + [alias]

    def update_topic_count(self, topic: str, increment: int = 1):
        """Update the count for a topic"""
        if not self.primary_topics:
            self.primary_topics = {}
        self.primary_topics[topic] = self.primary_topics.get(topic, 0) + increment

    def update_role_count(self, role: str, increment: int = 1):
        """Update the count for a role"""
        if not self.primary_roles:
            self.primary_roles = {}
        self.primary_roles[role] = self.primary_roles.get(role, 0) + increment

    def __repr__(self):
        return f"<Entity(id={self.id}, name='{self.canonical_name}', type={self.entity_type})>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "country": self.country,
            "title": self.title,
            "aliases": self.aliases,
            "mention_count": self.mention_count,
            "primary_topics": self.primary_topics,
            "primary_roles": self.primary_roles,
            "first_seen_date": self.first_seen_date.isoformat() if self.first_seen_date else None,
            "last_seen_date": self.last_seen_date.isoformat() if self.last_seen_date else None,
        }


# ============================================================================
# Document-Entity Link
# ============================================================================

class DocumentEntity(Base):
    """
    Links a document to entities mentioned in it, with context about their role.

    This is the raw extraction output - one entry per entity mention per document.
    """
    __tablename__ = 'document_entities'

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Links
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), nullable=False)
    entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('entities.id'),
        nullable=False
    )

    # Context in this document
    side: Mapped[str] = mapped_column(String(20), nullable=False)  # initiating, recipient, third_party
    role_label: Mapped[str] = mapped_column(String(50), nullable=False)
    topic_label: Mapped[str] = mapped_column(String(50), nullable=False)
    role_description: Mapped[Optional[str]] = mapped_column(Text)

    # For persons - their title/position in this context
    title_in_context: Mapped[Optional[str]] = mapped_column(Text)
    organization_in_context: Mapped[Optional[str]] = mapped_column(Text)

    # Extraction metadata
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    extraction_method: Mapped[str] = mapped_column(String(50), default="llm")  # llm, ner, manual
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    model_used: Mapped[Optional[str]] = mapped_column(String(100))

    # Relationships
    entity = relationship("Entity", back_populates="document_mentions")
    document = relationship("Document", backref="entity_mentions")

    __table_args__ = (
        Index("ix_doc_entity_doc_id", "doc_id"),
        Index("ix_doc_entity_entity_id", "entity_id"),
        Index("ix_doc_entity_side", "side"),
        Index("ix_doc_entity_role", "role_label"),
        Index("ix_doc_entity_topic", "topic_label"),
    )

    def __repr__(self):
        return f"<DocumentEntity(doc_id='{self.doc_id[:8]}...', entity_id={self.entity_id}, role={self.role_label})>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "doc_id": self.doc_id,
            "entity_id": str(self.entity_id),
            "side": self.side,
            "role_label": self.role_label,
            "topic_label": self.topic_label,
            "role_description": self.role_description,
            "confidence": self.confidence,
        }


# ============================================================================
# Entity Relationships
# ============================================================================

class EntityRelationship(Base):
    """
    Tracks relationships between entities observed across documents.

    Aggregates relationship observations over time.
    """
    __tablename__ = 'entity_relationships'

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Entities involved
    source_entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('entities.id'),
        nullable=False
    )
    target_entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('entities.id'),
        nullable=False
    )

    # Relationship classification
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Aggregated from observations
    first_observed: Mapped[DateType] = mapped_column(Date, nullable=False)
    last_observed: Mapped[DateType] = mapped_column(Date, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, default=1)
    document_count: Mapped[int] = mapped_column(Integer, default=1)

    # Financial aggregation (for monetary relationships)
    total_value_usd: Mapped[Optional[float]] = mapped_column(Float)

    # Sample evidence
    sample_doc_ids: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list)
    sample_descriptions: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list)

    # Confidence
    avg_confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    source_entity = relationship(
        "Entity",
        foreign_keys=[source_entity_id],
        back_populates="outgoing_relationships"
    )
    target_entity = relationship(
        "Entity",
        foreign_keys=[target_entity_id],
        back_populates="incoming_relationships"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_entity_id", "target_entity_id", "relationship_type",
            name="uq_entity_relationship"
        ),
        Index("ix_relationship_source", "source_entity_id"),
        Index("ix_relationship_target", "target_entity_id"),
        Index("ix_relationship_type", "relationship_type"),
        Index("ix_relationship_dates", "first_observed", "last_observed"),
    )

    def add_observation(
        self,
        doc_id: str,
        description: str,
        observation_date: DateType,
        confidence: float = 1.0,
        value_usd: Optional[float] = None
    ):
        """Add a new observation of this relationship"""
        self.observation_count += 1

        # Update dates
        if observation_date < self.first_observed:
            self.first_observed = observation_date
        if observation_date > self.last_observed:
            self.last_observed = observation_date

        # Update sample evidence (keep last 10)
        if doc_id not in self.sample_doc_ids:
            self.document_count += 1
            self.sample_doc_ids = (self.sample_doc_ids + [doc_id])[-10:]
            self.sample_descriptions = (self.sample_descriptions + [description])[-10:]

        # Update confidence (running average)
        self.avg_confidence = (
            (self.avg_confidence * (self.observation_count - 1) + confidence)
            / self.observation_count
        )

        # Aggregate monetary value
        if value_usd:
            self.total_value_usd = (self.total_value_usd or 0) + value_usd

    def __repr__(self):
        return f"<EntityRelationship({self.source_entity_id} -> {self.target_entity_id}, type={self.relationship_type})>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "source_entity_id": str(self.source_entity_id),
            "target_entity_id": str(self.target_entity_id),
            "relationship_type": self.relationship_type,
            "first_observed": self.first_observed.isoformat() if self.first_observed else None,
            "last_observed": self.last_observed.isoformat() if self.last_observed else None,
            "observation_count": self.observation_count,
            "document_count": self.document_count,
            "total_value_usd": self.total_value_usd,
        }


# ============================================================================
# Raw Extraction Storage (for debugging/reprocessing)
# ============================================================================

class EntityExtractionRun(Base):
    """
    Tracks entity extraction pipeline runs for auditing and debugging.
    """
    __tablename__ = 'entity_extraction_runs'

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Run parameters
    initiating_country: Mapped[Optional[str]] = mapped_column(Text)
    start_date: Mapped[Optional[DateType]] = mapped_column(Date)
    end_date: Mapped[Optional[DateType]] = mapped_column(Date)
    model_used: Mapped[str] = mapped_column(String(100))

    # Results
    documents_processed: Mapped[int] = mapped_column(Integer, default=0)
    entities_extracted: Mapped[int] = mapped_column(Integer, default=0)
    relationships_extracted: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Status
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, completed, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self):
        return f"<EntityExtractionRun(id={self.id}, status={self.status}, entities={self.entities_extracted})>"
