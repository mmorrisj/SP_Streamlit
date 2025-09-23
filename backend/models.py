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
    date: Mapped[Optional[date]] = mapped_column(Date)
    
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
    projects: Mapped[Optional[str]] = mapped_column(Text)
    lat_long: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)
    
    # Financial data
    monetary_commitment: Mapped[Optional[str]] = mapped_column(Text)
    
    # Content
    distilled_text: Mapped[Optional[str]] = mapped_column(Text)
    event_name: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships - Add as we convert each model
    # Removed salience_score relationship - field moved directly into Document
    categories = relationship("Category", back_populates="document", lazy="dynamic")
    subcategories = relationship("Subcategory", back_populates="document", lazy="dynamic")
    initiating_countries = relationship("InitiatingCountry", back_populates="document", lazy="dynamic")
    recipient_countries = relationship("RecipientCountry", back_populates="document", lazy="dynamic")
    projects_rel = relationship("Project", back_populates="document", lazy="dynamic")
    raw_events = relationship("RawEvent", back_populates="document", lazy="dynamic")
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
    
    Another single-field table that could potentially be consolidated
    into Document, similar to the Salience issue we fixed earlier.
    """
    __tablename__ = 'citations'
    
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey('documents.doc_id'), primary_key=True)
    citation: Mapped[Optional[str]] = mapped_column(Text)
    
    def __repr__(self) -> str:
        return f"<Citation(doc_id='{self.doc_id}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}