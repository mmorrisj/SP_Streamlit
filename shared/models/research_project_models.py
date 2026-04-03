"""
Research project models for document collection and project-scoped analysis.

Analysts collect specific source documents from chat/RAG queries into
research projects, then generate reports or chat with only those sources.
"""
import uuid
from datetime import datetime
from datetime import date as DateType
from typing import List, Dict, Optional, Any
from enum import Enum as PyEnum

from sqlalchemy import (
    String, Text, Date, DateTime, Boolean, ForeignKey,
    UniqueConstraint, Index, Enum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from shared.database.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProjectStatus(PyEnum):
    """Research project lifecycle status."""
    ACTIVE = "active"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ResearchProject(Base):
    """
    A user's research project — a curated collection of source documents
    assembled across multiple chat/RAG queries for focused analysis.
    """
    __tablename__ = "research_projects"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), default=ProjectStatus.ACTIVE, nullable=False
    )

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=datetime.utcnow
    )

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    user = relationship("User")
    documents = relationship(
        "ProjectDocument",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectDocument.added_at.desc()",
    )

    __table_args__ = (
        Index("ix_research_project_user", "user_id"),
        Index("ix_research_project_status", "status", "is_deleted"),
    )

    def __repr__(self) -> str:
        return f"<ResearchProject(id='{self.id}', name='{self.name}')>"

    def to_dict(self, include_documents: bool = False) -> Dict[str, Any]:
        result = {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "document_count": len(self.documents) if self.documents else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_documents:
            result["documents"] = [d.to_dict() for d in (self.documents or [])]
        return result


class ProjectDocument(Base):
    """
    A source document collected into a research project.

    Caches key metadata from the original Document so the drawer can
    render without re-querying the documents table.
    """
    __tablename__ = "project_documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Cached metadata (snapshot at collection time)
    title: Mapped[Optional[str]] = mapped_column(Text)
    source_name: Mapped[Optional[str]] = mapped_column(Text)
    date: Mapped[Optional[DateType]] = mapped_column(Date)
    initiating_country: Mapped[Optional[str]] = mapped_column(Text)
    recipient_country: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    excerpt: Mapped[Optional[str]] = mapped_column(Text)

    # Context of how this doc was found
    source_query: Mapped[Optional[str]] = mapped_column(Text)

    # Analyst annotation
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Timestamp
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationship
    project = relationship("ResearchProject", back_populates="documents")

    __table_args__ = (
        UniqueConstraint("project_id", "doc_id", name="uq_project_doc"),
        Index("ix_project_doc_project", "project_id"),
        Index("ix_project_doc_docid", "doc_id"),
    )

    def __repr__(self) -> str:
        return f"<ProjectDocument(project='{self.project_id}', doc='{self.doc_id}')>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "doc_id": self.doc_id,
            "title": self.title,
            "source_name": self.source_name,
            "date": str(self.date) if self.date else None,
            "initiating_country": self.initiating_country,
            "recipient_country": self.recipient_country,
            "category": self.category,
            "excerpt": self.excerpt,
            "source_query": self.source_query,
            "notes": self.notes,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }
