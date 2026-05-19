"""Proposition-level extraction models.

Parallel to the document-level pipeline: each document yields zero-or-more
DocumentProposition rows. Stage-2 consolidation rolls them up into
CanonicalProposition rows, mirroring the canonical_events pattern.
"""
import uuid
from datetime import datetime
from datetime import date as DateType
from typing import List, Dict, Optional

from sqlalchemy import (
    Integer, String, Text, Date, Float, DateTime, Boolean, ForeignKey, Index, Numeric,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from shared.database.database import Base


class DocumentProposition(Base):
    __tablename__ = "document_propositions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Source traceability
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey("documents.doc_id"), nullable=False, index=True)
    evidence_span: Mapped[Optional[Dict]] = mapped_column(JSONB)  # {"start": int, "end": int, "text": str}

    # Proposition structure
    proposition_text: Mapped[str] = mapped_column(Text, nullable=False)  # natural-language form
    subject: Mapped[Optional[str]] = mapped_column(Text)
    predicate: Mapped[Optional[str]] = mapped_column(Text)
    object: Mapped[Optional[str]] = mapped_column(Text)
    claim_type: Mapped[Optional[str]] = mapped_column(Text)   # action|commitment|statement|outcome|perception|capability
    tense: Mapped[Optional[str]] = mapped_column(String(16))  # past|present|future
    modality: Mapped[Optional[str]] = mapped_column(String(16))  # actual|planned|proposed|denied|speculative

    # Actors
    initiator_country: Mapped[Optional[str]] = mapped_column(Text, index=True)
    initiator_actor: Mapped[Optional[str]] = mapped_column(Text)
    initiator_actor_type: Mapped[Optional[str]] = mapped_column(Text)  # state|ministry|SOE|company|NGO|individual|multilateral
    recipient_country: Mapped[Optional[str]] = mapped_column(Text, index=True)
    recipient_actor: Mapped[Optional[str]] = mapped_column(Text)
    recipient_actor_type: Mapped[Optional[str]] = mapped_column(Text)
    third_parties: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), default=list)

    # Taxonomy (closed enums - see shared/utils/prompts_proposition.py for allowed values)
    sp_domain: Mapped[Optional[str]] = mapped_column(Text, index=True)  # economic_aid|investment|trade|diplomatic_engagement|cultural|educational|media_information|science_technology|health|humanitarian|security_military|governance|religious|other
    instrument_type: Mapped[Optional[str]] = mapped_column(Text)        # state_visit|bilateral_agreement|multilateral_forum|loan|grant|debt_relief|direct_investment|infrastructure_project|scholarship|exchange_program|cultural_event|language_institute|media_broadcast|joint_research|training_program|aid_delivery|statement|sanctions|other
    mechanism: Mapped[Optional[str]] = mapped_column(String(16))        # attraction|persuasion|inducement|coercion

    # Entities mentioned (persons, orgs, projects, locations)
    entities: Mapped[Optional[Dict]] = mapped_column(JSONB, default=dict)

    # Quantitative anchors
    monetary_value: Mapped[Optional[float]] = mapped_column(Numeric(precision=18, scale=2))
    currency: Mapped[Optional[str]] = mapped_column(String(8))
    monetary_value_usd: Mapped[Optional[float]] = mapped_column(Numeric(precision=18, scale=2))
    quantity: Mapped[Optional[float]] = mapped_column(Float)
    quantity_unit: Mapped[Optional[str]] = mapped_column(Text)
    timeframe: Mapped[Optional[str]] = mapped_column(Text)

    # Scoring
    valence: Mapped[Optional[float]] = mapped_column(Float)            # -1..+1 toward recipient
    salience_score: Mapped[Optional[float]] = mapped_column(Float)     # 0..1
    materiality_score: Mapped[Optional[float]] = mapped_column(Float)  # 0..1
    confidence: Mapped[Optional[float]] = mapped_column(Float)         # extractor self-reported 0..1

    # Temporal
    event_date: Mapped[Optional[DateType]] = mapped_column(Date, index=True)
    date_precision: Mapped[Optional[str]] = mapped_column(String(16))  # day|month|quarter|year|unknown

    # Geo
    location_name: Mapped[Optional[str]] = mapped_column(Text)
    lat_long: Mapped[Optional[str]] = mapped_column(Text)
    geo_scope: Mapped[Optional[str]] = mapped_column(String(16))  # bilateral|regional|multilateral|global

    # Linkage / dedup
    embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float))
    canonical_proposition_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_propositions.id"), nullable=True, index=True
    )
    linked_event_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_events.id"), nullable=True, index=True
    )

    # Extractor provenance
    extractor_model: Mapped[Optional[str]] = mapped_column(Text)
    extractor_version: Mapped[Optional[str]] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document")
    canonical_proposition = relationship("CanonicalProposition", back_populates="mentions")

    __table_args__ = (
        Index("ix_proposition_country_pair", "initiator_country", "recipient_country"),
        Index("ix_proposition_event_date_country", "event_date", "initiator_country"),
        Index("ix_proposition_sp_domain", "sp_domain"),
    )


class CanonicalProposition(Base):
    __tablename__ = "canonical_propositions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    canonical_text: Mapped[str] = mapped_column(Text, nullable=False)
    initiator_country: Mapped[Optional[str]] = mapped_column(Text, index=True)
    recipient_country: Mapped[Optional[str]] = mapped_column(Text, index=True)
    sp_domain: Mapped[Optional[str]] = mapped_column(Text)
    instrument_type: Mapped[Optional[str]] = mapped_column(Text)
    mechanism: Mapped[Optional[str]] = mapped_column(String(16))

    first_observed_date: Mapped[Optional[DateType]] = mapped_column(Date)
    last_observed_date: Mapped[Optional[DateType]] = mapped_column(Date)
    mention_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    centroid_embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float))
    llm_validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    mentions = relationship("DocumentProposition", back_populates="canonical_proposition")

    __table_args__ = (
        Index("ix_canonical_proposition_country_pair", "initiator_country", "recipient_country"),
        Index("ix_canonical_proposition_dates", "first_observed_date", "last_observed_date"),
    )
