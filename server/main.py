import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query, HTTPException, File, UploadFile, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from sqlalchemy import func
from pathlib import Path
import yaml
import json
import tempfile
import boto3
from botocore.exceptions import ClientError
import pyarrow.parquet as pq
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

from shared.database.database import get_session
from shared.models.models import (
    Document, EventSummary, CanonicalEvent,
    Category, Subcategory, InitiatingCountry, RecipientCountry,
    User, UserRole
)
from server.auth import (
    hash_password, verify_password, create_access_token,
    verify_token, get_token_from_header
)

app = FastAPI(title="Soft Power API", version="1.0.0")

STATIC_DIR = Path(__file__).parent.parent / "client" / "dist"

# Load config.yaml for influencers and recipients lists
CONFIG_PATH = Path(__file__).parent.parent / "shared" / "config" / "config.yaml"
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

INFLUENCERS = CONFIG.get('influencers', [])
RECIPIENTS = CONFIG.get('recipients', [])

# S3 client for proxy endpoints (used by Docker containers)
s3_client = boto3.client('s3')

# Import utility functions for LLM calls
try:
    from shared.utils.utils import gai, fetch_gai_content, fetch_gai_response
except ImportError:
    gai = None
    fetch_gai_content = None
    fetch_gai_response = None

# Hardcoded mapping of subcategories to their parent categories
# This is necessary because the database stores them separately without a direct link
SUBCATEGORY_TO_CATEGORY = {
    # Economic
    'Trade': 'Economic',
    'Infrastructure': 'Economic',
    'Food': 'Economic',
    'Technology': 'Economic',
    'Tourism': 'Economic',
    'Industrial': 'Economic',
    'Raw Materials': 'Economic',
    'Energy': 'Economic',
    'Finance': 'Economic',

    # Social
    'Culture': 'Social',
    'Education': 'Social',
    'Healthcare': 'Social',
    'Housing': 'Social',
    'Media': 'Social',
    'Politics': 'Social',
    'Religious': 'Social',
    'Cultural': 'Social',
    'Diaspora Engagement': 'Social',

    # Military
    'Sales': 'Military',
    'Joint Exercises': 'Military',
    'Training': 'Military',

    # Diplomacy
    'Bilateral/Multilateral Agreements': 'Diplomacy',
    'Multilateral/Bilateral Commitments': 'Diplomacy',
    'Conflict Resolution': 'Diplomacy',
    'Global Governance Participation': 'Diplomacy',
    'Conferences': 'Diplomacy',
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DocumentStats(BaseModel):
    total_documents: int
    total_events: int  # New: total canonical events
    documents_by_week: list
    documents_by_week_by_influencer: dict  # New: per-influencer weekly data
    documents_by_week_by_recipient: dict  # New: per-recipient weekly data
    top_countries: list
    top_recipients: list  # New: top recipient countries
    category_distribution: list
    subcategory_distribution: list  # New: subcategory breakdown

class DocumentResponse(BaseModel):
    documents: list
    total: int
    page: int
    limit: int

class EventsResponse(BaseModel):
    events: list

class SummariesResponse(BaseModel):
    summaries: list

class BilateralResponse(BaseModel):
    relationships: list

class CategoriesResponse(BaseModel):
    categories: list
    subcategories: list

class FiltersResponse(BaseModel):
    countries: list
    recipients: list
    categories: list
    subcategories: list
    date_range: dict


# ===== AUTHENTICATION MODELS =====

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    display_name: Optional[str] = None
    force_password_change: bool = True

class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    force_password_change: Optional[bool] = None

class ResetPasswordRequest(BaseModel):
    new_password: str

class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    display_name: Optional[str]
    is_active: bool
    force_password_change: bool
    created_at: Optional[str]
    last_login: Optional[str]


# ===== AUTHENTICATION DEPENDENCIES =====

def get_current_user(authorization: str = Header(None)) -> dict:
    """Dependency to get current user from JWT token."""
    token = get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload

def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency to require admin role."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def require_analyst_or_above(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency to require analyst or admin role."""
    if current_user.get("role") not in ["admin", "analyst"]:
        raise HTTPException(status_code=403, detail="Analyst access required")
    return current_user


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/documents/stats", response_model=DocumentStats)
def get_document_stats(
    country: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    influencer_country: Optional[str] = None,
    recipient_country: Optional[str] = None
):
    with get_session() as session:
        # Base query for total count - filter by influencers and recipients
        base_query = session.query(Document.doc_id).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            # Only influencers as initiating countries
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            # Only recipients as recipient countries
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            # Exclude same-country relationships (Iran-Iran, etc.)
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        )

        # Apply user filters
        if country and country != 'ALL':
            base_query = base_query.filter(
                InitiatingCountry.initiating_country == country
            )
        if influencer_country and influencer_country != 'ALL':
            base_query = base_query.filter(
                InitiatingCountry.initiating_country == influencer_country
            )
        if recipient_country and recipient_country != 'ALL':
            base_query = base_query.filter(
                RecipientCountry.recipient_country == recipient_country
            )
        if category and category != 'ALL':
            base_query = base_query.join(Category).filter(
                Category.category == category
            )

        total = base_query.distinct().count()

        # Count total canonical events (master events only) with same filters
        # Use the primary_recipients JSONB field for recipient filtering

        events_query = session.query(CanonicalEvent.id).filter(
            CanonicalEvent.master_event_id.is_(None),
            CanonicalEvent.initiating_country.in_(INFLUENCERS)
        )

        # Apply influencer filter
        if country and country != 'ALL':
            events_query = events_query.filter(CanonicalEvent.initiating_country == country)
        if influencer_country and influencer_country != 'ALL':
            events_query = events_query.filter(CanonicalEvent.initiating_country == influencer_country)

        # Apply recipient filter using JSONB key existence check
        if recipient_country and recipient_country != 'ALL':
            # Check if recipient_country exists as a key in primary_recipients JSONB
            events_query = events_query.filter(
                CanonicalEvent.primary_recipients.has_key(recipient_country)
            )

        total_events = events_query.count()

        # Documents by week - with same filtering
        week_query = session.query(
            func.date_trunc('week', Document.date).label('week'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            Document.date.isnot(None),
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        )

        if country and country != 'ALL':
            week_query = week_query.filter(
                InitiatingCountry.initiating_country == country
            )
        if category and category != 'ALL':
            week_query = week_query.join(Category).filter(
                Category.category == category
            )
        if start_date:
            week_query = week_query.filter(Document.date >= start_date)
        if end_date:
            week_query = week_query.filter(Document.date <= end_date)

        docs_by_week = week_query.group_by('week').order_by('week').all()

        # Documents by week by influencer - for toggle functionality
        docs_by_week_by_influencer = {}
        for influencer in INFLUENCERS:
            influencer_week_query = session.query(
                func.date_trunc('week', Document.date).label('week'),
                func.count(func.distinct(Document.doc_id)).label('count')
            ).join(InitiatingCountry).join(
                RecipientCountry,
                RecipientCountry.doc_id == Document.doc_id
            ).filter(
                Document.date.isnot(None),
                InitiatingCountry.initiating_country == influencer,
                RecipientCountry.recipient_country.in_(RECIPIENTS),
                InitiatingCountry.initiating_country != RecipientCountry.recipient_country
            )

            if category and category != 'ALL':
                influencer_week_query = influencer_week_query.join(Category).filter(
                    Category.category == category
                )
            if start_date:
                influencer_week_query = influencer_week_query.filter(Document.date >= start_date)
            if end_date:
                influencer_week_query = influencer_week_query.filter(Document.date <= end_date)

            influencer_weeks = influencer_week_query.group_by('week').order_by('week').all()
            docs_by_week_by_influencer[influencer] = [
                {"week": str(row.week)[:10] if row.week else "", "count": row.count}
                for row in influencer_weeks
            ]

        # Documents by week by recipient - OPTIMIZED single query approach
        # Single query gets all recipient/week/influencer combinations at once
        recipient_week_query = session.query(
            func.date_trunc('week', Document.date).label('week'),
            RecipientCountry.recipient_country.label('recipient'),
            InitiatingCountry.initiating_country.label('influencer'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(RecipientCountry).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Document.doc_id
        ).filter(
            Document.date.isnot(None),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        )

        if category and category != 'ALL':
            recipient_week_query = recipient_week_query.join(Category).filter(
                Category.category == category
            )
        if start_date:
            recipient_week_query = recipient_week_query.filter(Document.date >= start_date)
        if end_date:
            recipient_week_query = recipient_week_query.filter(Document.date <= end_date)

        # Execute single query
        all_recipient_weeks = recipient_week_query.group_by('week', 'recipient', 'influencer').all()

        # Group results by recipient, then by week
        docs_by_week_by_recipient = {}
        for row in all_recipient_weeks:
            recipient = row.recipient
            week_str = str(row.week)[:10] if row.week else ""

            if recipient not in docs_by_week_by_recipient:
                docs_by_week_by_recipient[recipient] = {}

            if week_str not in docs_by_week_by_recipient[recipient]:
                docs_by_week_by_recipient[recipient][week_str] = {"week": week_str, "by_influencer": {}}

            docs_by_week_by_recipient[recipient][week_str]["by_influencer"][row.influencer] = row.count

        # Convert week maps to sorted lists
        for recipient in docs_by_week_by_recipient:
            docs_by_week_by_recipient[recipient] = sorted(
                docs_by_week_by_recipient[recipient].values(),
                key=lambda x: x["week"]
            )

        # Top countries - only from influencers list
        countries_query = session.query(
            InitiatingCountry.initiating_country.label('country'),
            func.count(func.distinct(InitiatingCountry.doc_id)).label('count')
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == InitiatingCountry.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        )

        if category and category != 'ALL':
            countries_query = countries_query.join(
                Category,
                Category.doc_id == InitiatingCountry.doc_id
            ).filter(Category.category == category)

        top_countries = countries_query.group_by(
            InitiatingCountry.initiating_country
        ).order_by(func.count(func.distinct(InitiatingCountry.doc_id)).desc()).limit(10).all()

        # Top recipients - only from recipients list, filter by influencers
        recipients_query = session.query(
            RecipientCountry.recipient_country.label('country'),
            func.count(func.distinct(RecipientCountry.doc_id)).label('count')
        ).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == RecipientCountry.doc_id
        ).filter(
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        )

        if category and category != 'ALL':
            recipients_query = recipients_query.join(
                Category,
                Category.doc_id == RecipientCountry.doc_id
            ).filter(Category.category == category)

        top_recipients = recipients_query.group_by(
            RecipientCountry.recipient_country
        ).order_by(func.count(func.distinct(RecipientCountry.doc_id)).desc()).limit(10).all()

        # Category distribution - with same filtering
        cat_query = session.query(
            Category.category.label('category'),
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Category.doc_id
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        )

        if country and country != 'ALL':
            cat_query = cat_query.filter(
                InitiatingCountry.initiating_country == country
            )

        category_dist = cat_query.group_by(Category.category).order_by(
            func.count(func.distinct(Category.doc_id)).desc()
        ).all()

        # Subcategory distribution - with same filtering
        subcat_query = session.query(
            Subcategory.subcategory.label('subcategory'),
            func.count(func.distinct(Subcategory.doc_id)).label('count')
        ).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Subcategory.doc_id
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Subcategory.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        )

        if country and country != 'ALL':
            subcat_query = subcat_query.filter(
                InitiatingCountry.initiating_country == country
            )

        subcategory_dist = subcat_query.group_by(Subcategory.subcategory).order_by(
            func.count(func.distinct(Subcategory.doc_id)).desc()
        ).limit(10).all()

        return DocumentStats(
            total_documents=total,
            total_events=total_events,
            documents_by_week=[
                {"week": str(row.week)[:10] if row.week else "", "count": row.count}
                for row in docs_by_week
            ],
            documents_by_week_by_influencer=docs_by_week_by_influencer,
            documents_by_week_by_recipient=docs_by_week_by_recipient,
            top_countries=[
                {"country": row.country, "count": row.count}
                for row in top_countries
            ],
            top_recipients=[
                {"country": row.country, "count": row.count}
                for row in top_recipients
            ],
            category_distribution=[
                {"category": row.category, "count": row.count}
                for row in category_dist
            ],
            subcategory_distribution=[
                {"subcategory": row.subcategory, "count": row.count}
                for row in subcategory_dist
            ]
        )

@app.get("/api/documents", response_model=DocumentResponse)
def get_documents(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    country: Optional[str] = None,
    category: Optional[str] = None
):
    with get_session() as session:
        # Build base query with proper joins for filtering
        query = session.query(Document)

        if search:
            query = query.filter(Document.title.ilike(f'%{search}%'))
        if country and country != 'ALL':
            query = query.join(InitiatingCountry).filter(
                InitiatingCountry.initiating_country == country
            )
        if category and category != 'ALL':
            query = query.join(Category).filter(
                Category.category == category
            )

        total = query.distinct().count()
        offset = (page - 1) * limit
        docs = query.distinct().order_by(Document.date.desc()).offset(offset).limit(limit).all()

        # Build response with normalized data
        documents = []
        for doc in docs:
            # Get categories from normalized table
            categories = [c.category for c in session.query(Category).filter(
                Category.doc_id == doc.doc_id
            ).all()]

            # Get subcategories from normalized table
            subcategories = [s.subcategory for s in session.query(Subcategory).filter(
                Subcategory.doc_id == doc.doc_id
            ).all()]

            # Get initiating countries from normalized table
            init_countries = [ic.initiating_country for ic in session.query(InitiatingCountry).filter(
                InitiatingCountry.doc_id == doc.doc_id
            ).all()]

            # Get recipient countries from normalized table
            recip_countries = [rc.recipient_country for rc in session.query(RecipientCountry).filter(
                RecipientCountry.doc_id == doc.doc_id
            ).all()]

            documents.append({
                "id": doc.doc_id,
                "atom_id": doc.doc_id,
                "title": doc.title,
                "source_name": doc.source_name,
                "source_date": str(doc.date) if doc.date else None,
                "category": "; ".join(categories) if categories else None,
                "subcategory": "; ".join(subcategories) if subcategories else None,
                "initiating_country": "; ".join(init_countries) if init_countries else None,
                "recipient_country": "; ".join(recip_countries) if recip_countries else None,
            })

        return DocumentResponse(
            documents=documents,
            total=total,
            page=page,
            limit=limit
        )

@app.get("/api/events", response_model=EventsResponse)
def get_events(
    country: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    with get_session() as session:
        query = session.query(
            CanonicalEvent.id,
            CanonicalEvent.canonical_name,
            CanonicalEvent.first_mention_date,
            CanonicalEvent.initiating_country,
            CanonicalEvent.story_phase,
            CanonicalEvent.consolidated_description
        )

        if country and country != 'ALL':
            query = query.filter(CanonicalEvent.initiating_country == country)

        events = query.order_by(CanonicalEvent.first_mention_date.desc()).limit(limit).all()

        return EventsResponse(
            events=[
                {
                    "id": str(event.id),
                    "event_name": event.canonical_name or "",
                    "event_date": str(event.first_mention_date) if event.first_mention_date else None,
                    "initiating_country": event.initiating_country or "",
                    "recipient_country": "",
                    "category": event.story_phase or "",
                    "description": event.consolidated_description or "",
                }
                for event in events
            ]
        )

@app.get("/api/summaries", response_model=SummariesResponse)
def get_summaries(
    type: str = Query("daily", description="Summary type: daily, weekly, or monthly"),
    country: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    with get_session() as session:
        query = session.query(
            EventSummary.id,
            EventSummary.period_type,
            EventSummary.period_start,
            EventSummary.period_end,
            EventSummary.event_name,
            EventSummary.initiating_country
        )

        if country and country != 'ALL':
            query = query.filter(EventSummary.initiating_country == country)

        summaries = query.order_by(EventSummary.period_start.desc()).limit(limit).all()

        return SummariesResponse(
            summaries=[
                {
                    "id": str(summary.id),
                    "summary_type": summary.period_type.value if summary.period_type else type,
                    "period_start": str(summary.period_start) if summary.period_start else None,
                    "period_end": str(summary.period_end) if summary.period_end else None,
                    "content": summary.event_name or "",
                    "country": summary.initiating_country or "",
                }
                for summary in summaries
            ]
        )

@app.get("/api/bilateral", response_model=BilateralResponse)
def get_bilateral_relationships():
    with get_session() as session:
        # Query from normalized tables for accurate bilateral relationships
        # Filter: only influencers → recipients, exclude same-country (Iran-Iran)
        relationships = session.query(
            InitiatingCountry.initiating_country,
            RecipientCountry.recipient_country,
            func.count(func.distinct(InitiatingCountry.doc_id)).label('count')
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == InitiatingCountry.doc_id
        ).filter(
            # Only influencers as initiating countries
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            # Only recipients as recipient countries
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            # Exclude same-country relationships
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(
            InitiatingCountry.initiating_country,
            RecipientCountry.recipient_country
        ).order_by(func.count(func.distinct(InitiatingCountry.doc_id)).desc()).limit(30).all()

        return BilateralResponse(
            relationships=[
                {
                    "initiating_country": row.initiating_country,
                    "recipient_country": row.recipient_country,
                    "count": row.count
                }
                for row in relationships
            ]
        )

@app.get("/api/categories", response_model=CategoriesResponse)
def get_categories():
    with get_session() as session:
        # Query from normalized Category table - filter by influencers/recipients
        categories = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Category.doc_id
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Category.category
        ).order_by(func.count(func.distinct(Category.doc_id)).desc()).all()

        # Query from normalized Subcategory table - filter by influencers/recipients
        subcategories = session.query(
            Subcategory.subcategory,
            func.count(func.distinct(Subcategory.doc_id)).label('count')
        ).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Subcategory.doc_id
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Subcategory.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Subcategory.subcategory
        ).order_by(func.count(func.distinct(Subcategory.doc_id)).desc()).limit(20).all()

        return CategoriesResponse(
            categories=[
                {"category": row.category, "count": row.count}
                for row in categories
            ],
            subcategories=[
                {"subcategory": row.subcategory, "count": row.count}
                for row in subcategories
            ]
        )

@app.get("/api/bilateral-map-data")
def get_bilateral_map_data(influencer: Optional[str] = Query(None, description="Influencer country or ALL")):
    """Get bilateral relationship data for map visualization."""
    with get_session() as session:
        # If influencer is ALL or None, aggregate across all influencers
        if not influencer or influencer == 'ALL':
            # Get data for all recipients across all influencers
            recipient_data = session.query(
                RecipientCountry.recipient_country.label('recipient'),
                func.count(func.distinct(RecipientCountry.doc_id)).label('document_count')
            ).join(
                InitiatingCountry,
                InitiatingCountry.doc_id == RecipientCountry.doc_id
            ).filter(
                RecipientCountry.recipient_country.in_(RECIPIENTS),
                InitiatingCountry.initiating_country.in_(INFLUENCERS),
                InitiatingCountry.initiating_country != RecipientCountry.recipient_country
            ).group_by(RecipientCountry.recipient_country).all()

            # Get event counts per recipient (from canonical_events)
            event_counts = {}
            for recipient in RECIPIENTS:
                # Count master canonical events that mention this recipient
                # This is approximate - we'd need to parse the recipient data from canonical_events
                event_count = session.query(func.count(CanonicalEvent.id)).filter(
                    CanonicalEvent.master_event_id.is_(None)
                ).scalar() or 0
                event_counts[recipient] = 0  # Placeholder for now

            return {
                "influencer": "ALL",
                "recipients": [
                    {
                        "country": row.recipient,
                        "document_count": row.document_count,
                        "event_count": event_counts.get(row.recipient, 0),
                        "avg_materiality": 0.0  # Placeholder
                    }
                    for row in recipient_data
                ]
            }
        else:
            # Get data for specific influencer
            if influencer not in INFLUENCERS:
                return {"error": f"{influencer} is not a recognized influencer"}

            recipient_data = session.query(
                RecipientCountry.recipient_country.label('recipient'),
                func.count(func.distinct(RecipientCountry.doc_id)).label('document_count')
            ).join(
                InitiatingCountry,
                InitiatingCountry.doc_id == RecipientCountry.doc_id
            ).filter(
                InitiatingCountry.initiating_country == influencer,
                RecipientCountry.recipient_country.in_(RECIPIENTS),
                InitiatingCountry.initiating_country != RecipientCountry.recipient_country
            ).group_by(RecipientCountry.recipient_country).all()

            # Get event counts for this influencer
            event_counts_query = session.query(
                CanonicalEvent.id
            ).filter(
                CanonicalEvent.initiating_country == influencer,
                CanonicalEvent.master_event_id.is_(None)
            ).all()

            return {
                "influencer": influencer,
                "recipients": [
                    {
                        "country": row.recipient,
                        "document_count": row.document_count,
                        "event_count": 0,  # Placeholder - would need to parse event recipients
                        "avg_materiality": 0.0  # Placeholder
                    }
                    for row in recipient_data
                ]
            }

@app.get("/api/filters", response_model=FiltersResponse)
def get_filter_options():
    with get_session() as session:
        # Return only influencers from config as filter options
        # (These are the only countries we show data for)
        countries = INFLUENCERS

        # Get distinct categories from filtered data
        categories = session.query(
            Category.category
        ).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Category.doc_id
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).distinct().all()

        # Get distinct subcategories from filtered data
        subcategories = session.query(
            Subcategory.subcategory
        ).join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Subcategory.doc_id
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Subcategory.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).distinct().all()

        # Date range from filtered documents
        date_range = session.query(
            func.min(Document.date).label('min'),
            func.max(Document.date).label('max')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).first()

        return FiltersResponse(
            countries=sorted(countries),  # From config, not database
            recipients=sorted(RECIPIENTS),  # From config, not database
            categories=sorted([c[0] for c in categories if c[0]]),
            subcategories=sorted([c[0] for c in subcategories if c[0]]),
            date_range={
                "min": str(date_range.min) if date_range and date_range.min else None,
                "max": str(date_range.max) if date_range and date_range.max else None
            }
        )

# ===== INFLUENCER-SPECIFIC ENDPOINTS =====

class InfluencerOverview(BaseModel):
    country: str
    total_documents: int
    total_recipients: int
    top_categories: list
    recent_activity_trend: list
    top_recipients: list

class RecentActivity(BaseModel):
    activities: list
    total: int

class InfluencerEventsResponse(BaseModel):
    events: list

@app.get("/api/influencer/{country}/overview", response_model=InfluencerOverview)
def get_influencer_overview(country: str):
    """Get overview statistics for a specific influencer country."""
    with get_session() as session:
        # Validate country is an influencer
        if country not in INFLUENCERS:
            return {"error": f"{country} is not a recognized influencer"}

        # Total documents for this influencer
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).scalar() or 0

        # Count unique recipients
        total_recipients = session.query(
            func.count(func.distinct(RecipientCountry.recipient_country))
        ).join(InitiatingCountry, InitiatingCountry.doc_id == RecipientCountry.doc_id).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).scalar() or 0

        # Top categories
        top_categories = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Category.category).order_by(func.count(func.distinct(Category.doc_id)).desc()).limit(5).all()

        # Recent activity trend (last 8 weeks)
        activity_trend = session.query(
            func.date_trunc('week', Document.date).label('week'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.date.isnot(None)
        ).group_by(func.date_trunc('week', Document.date)).order_by(func.date_trunc('week', Document.date).desc()).limit(8).all()

        # Top recipients for this influencer
        top_recipients = session.query(
            RecipientCountry.recipient_country,
            func.count(func.distinct(RecipientCountry.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == RecipientCountry.doc_id).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(RecipientCountry.recipient_country).order_by(func.count(func.distinct(RecipientCountry.doc_id)).desc()).limit(10).all()

        return InfluencerOverview(
            country=country,
            total_documents=total_docs,
            total_recipients=total_recipients,
            top_categories=[{"category": cat, "count": count} for cat, count in top_categories],
            recent_activity_trend=[{"week": str(week.date()) if week else None, "count": count} for week, count in reversed(activity_trend)],
            top_recipients=[{"country": recipient, "count": count} for recipient, count in top_recipients]
        )

@app.get("/api/influencer/{country}/recent-activities", response_model=RecentActivity)
def get_influencer_recent_activities(
    country: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Get recent documents with distilled text for a specific influencer."""
    with get_session() as session:
        if country not in INFLUENCERS:
            return {"error": f"{country} is not a recognized influencer"}

        # Get recent documents with distilled_text
        documents = session.query(
            Document.doc_id,
            Document.title,
            Document.date,
            Document.distilled_text,
            Document.event_name,
            Document.salience_justification,
            RecipientCountry.recipient_country
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.distilled_text.isnot(None),
            Document.date.isnot(None)
        ).order_by(Document.date.desc()).limit(limit).offset(offset).all()

        # Get total count
        total = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.distilled_text.isnot(None)
        ).scalar() or 0

        activities = []
        for doc in documents:
            activities.append({
                "doc_id": doc.doc_id,
                "title": doc.title,
                "date": str(doc.date) if doc.date else None,
                "distilled_text": doc.distilled_text,
                "event_name": doc.event_name,
                "salience_justification": doc.salience_justification,
                "recipient_country": doc.recipient_country
            })

        return RecentActivity(
            activities=activities,
            total=total
        )

@app.get("/api/influencer/{country}/events", response_model=InfluencerEventsResponse)
def get_influencer_events(country: str, limit: int = Query(default=10, ge=1, le=50)):
    """Get recent master event summaries for a specific influencer (consolidated events only)."""
    with get_session() as session:
        if country not in INFLUENCERS:
            return {"error": f"{country} is not a recognized influencer"}

        # Get MASTER canonical events only (master_event_id IS NULL)
        # These represent consolidated events that may span multiple days
        events = session.query(CanonicalEvent).filter(
            CanonicalEvent.initiating_country == country,
            CanonicalEvent.master_event_id.is_(None)  # Only master events
        ).order_by(CanonicalEvent.last_mention_date.desc()).limit(limit).all()

        event_list = []
        for event in events:
            event_list.append({
                "id": str(event.id),
                "event_name": event.canonical_name,
                "event_date": str(event.last_mention_date) if event.last_mention_date else None,
                "summary": event.consolidated_description,
                "initiating_country": event.initiating_country,
                "total_mentions": event.total_articles
            })

        return InfluencerEventsResponse(events=event_list)

# ===== COMPREHENSIVE METRICS ENDPOINTS =====

class OverallMetrics(BaseModel):
    total_documents: int
    total_relationships: int
    active_influencers: int
    active_recipients: int
    category_breakdown: list
    subcategory_breakdown: list
    influencer_comparison: list
    monthly_trend: list
    category_by_influencer: list

class InfluencerMetrics(BaseModel):
    influencer: str
    total_documents: int
    category_breakdown: list
    subcategory_breakdown: list
    recipient_breakdown: list
    monthly_trend: list
    source_breakdown: list

class BilateralMetrics(BaseModel):
    influencer: str
    recipient: str
    total_documents: int
    category_breakdown: list
    subcategory_breakdown: list
    monthly_trend: list
    source_breakdown: list
    recent_highlights: list

class RecipientMetrics(BaseModel):
    recipient: str
    total_documents: int
    influencer_breakdown: list
    category_breakdown: list
    subcategory_breakdown: list
    monthly_trend: list
    source_breakdown: list
    recent_events: list

@app.get("/api/metrics/overall", response_model=OverallMetrics)
def get_overall_metrics():
    """Get comprehensive overall metrics across all influencers and recipients."""
    with get_session() as session:
        # Total documents
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).scalar() or 0

        # Total relationships
        total_relationships = session.query(
            func.count(func.distinct(
                func.concat(InitiatingCountry.initiating_country, '|', RecipientCountry.recipient_country)
            ))
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == InitiatingCountry.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).scalar() or 0

        # Active influencers (with at least 1 document)
        active_influencers = len(INFLUENCERS)  # All have data in your case

        # Active recipients
        active_recipients = session.query(
            func.count(func.distinct(RecipientCountry.recipient_country))
        ).join(InitiatingCountry, InitiatingCountry.doc_id == RecipientCountry.doc_id).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).scalar() or 0

        # Category breakdown
        category_breakdown = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Category.category).order_by(
            func.count(func.distinct(Category.doc_id)).desc()
        ).all()

        # Subcategory breakdown (top 20)
        subcategory_breakdown = session.query(
            Subcategory.subcategory,
            func.count(func.distinct(Subcategory.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Subcategory.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Subcategory.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Subcategory.subcategory).order_by(
            func.count(func.distinct(Subcategory.doc_id)).desc()
        ).limit(20).all()

        # Influencer comparison (document count per influencer)
        influencer_comparison = session.query(
            InitiatingCountry.initiating_country,
            func.count(func.distinct(InitiatingCountry.doc_id)).label('count')
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == InitiatingCountry.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(InitiatingCountry.initiating_country).order_by(
            func.count(func.distinct(InitiatingCountry.doc_id)).desc()
        ).all()

        # Monthly trend (last 12 months)
        monthly_trend = session.query(
            func.date_trunc('month', Document.date).label('month'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.date.isnot(None)
        ).group_by(func.date_trunc('month', Document.date)).order_by(
            func.date_trunc('month', Document.date).desc()
        ).limit(12).all()

        # Category by influencer (matrix data)
        category_by_influencer_raw = session.query(
            InitiatingCountry.initiating_country,
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(
            InitiatingCountry.initiating_country,
            Category.category
        ).all()

        # Format category by influencer as list of dicts
        category_by_influencer = [
            {"influencer": row[0], "category": row[1], "count": row[2]}
            for row in category_by_influencer_raw
        ]

        return OverallMetrics(
            total_documents=total_docs,
            total_relationships=total_relationships,
            active_influencers=active_influencers,
            active_recipients=active_recipients,
            category_breakdown=[{"category": cat, "count": count} for cat, count in category_breakdown],
            subcategory_breakdown=[{"subcategory": subcat, "count": count} for subcat, count in subcategory_breakdown],
            influencer_comparison=[{"influencer": inf, "count": count} for inf, count in influencer_comparison],
            monthly_trend=[{"month": str(month.date()) if month else None, "count": count} for month, count in reversed(monthly_trend)],
            category_by_influencer=category_by_influencer
        )

@app.get("/api/metrics/influencer/{country}", response_model=InfluencerMetrics)
def get_influencer_metrics(country: str):
    """Get comprehensive metrics for a specific influencer with category/subcategory breakdowns."""
    with get_session() as session:
        if country not in INFLUENCERS:
            return {"error": f"{country} is not a recognized influencer"}

        # Total documents
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).scalar() or 0

        # Category breakdown
        category_breakdown = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Category.category).order_by(
            func.count(func.distinct(Category.doc_id)).desc()
        ).all()

        # Subcategory breakdown (all)
        subcategory_breakdown = session.query(
            Subcategory.subcategory,
            func.count(func.distinct(Subcategory.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Subcategory.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Subcategory.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Subcategory.subcategory).order_by(
            func.count(func.distinct(Subcategory.doc_id)).desc()
        ).all()

        # Recipient breakdown
        recipient_breakdown = session.query(
            RecipientCountry.recipient_country,
            func.count(func.distinct(RecipientCountry.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == RecipientCountry.doc_id).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(RecipientCountry.recipient_country).order_by(
            func.count(func.distinct(RecipientCountry.doc_id)).desc()
        ).all()

        # Monthly trend
        monthly_trend = session.query(
            func.date_trunc('month', Document.date).label('month'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.date.isnot(None)
        ).group_by(func.date_trunc('month', Document.date)).order_by(
            func.date_trunc('month', Document.date).desc()
        ).limit(12).all()

        # Source breakdown (top 20 news sources)
        source_breakdown = session.query(
            Document.source_name,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.source_name.isnot(None)
        ).group_by(Document.source_name).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).limit(20).all()

        return InfluencerMetrics(
            influencer=country,
            total_documents=total_docs,
            category_breakdown=[{"category": cat, "count": count} for cat, count in category_breakdown],
            subcategory_breakdown=[{"subcategory": subcat, "count": count} for subcat, count in subcategory_breakdown],
            recipient_breakdown=[{"recipient": recip, "count": count} for recip, count in recipient_breakdown],
            monthly_trend=[{"month": str(month.date()) if month else None, "count": count} for month, count in reversed(monthly_trend)],
            source_breakdown=[{"source": source, "count": count} for source, count in source_breakdown]
        )

@app.get("/api/metrics/bilateral/{influencer}/{recipient}", response_model=BilateralMetrics)
def get_bilateral_metrics(influencer: str, recipient: str):
    """Get comprehensive bilateral metrics with category and subcategory breakdowns."""
    with get_session() as session:
        if influencer not in INFLUENCERS:
            return {"error": f"{influencer} is not a recognized influencer"}
        if recipient not in RECIPIENTS:
            return {"error": f"{recipient} is not a recognized recipient"}

        # Total documents
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).scalar() or 0

        # Category breakdown
        category_breakdown = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).group_by(Category.category).order_by(
            func.count(func.distinct(Category.doc_id)).desc()
        ).all()

        # Subcategory breakdown (all)
        subcategory_breakdown = session.query(
            Subcategory.subcategory,
            func.count(func.distinct(Subcategory.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Subcategory.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Subcategory.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).group_by(Subcategory.subcategory).order_by(
            func.count(func.distinct(Subcategory.doc_id)).desc()
        ).all()

        # Monthly trend
        monthly_trend = session.query(
            func.date_trunc('month', Document.date).label('month'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.date.isnot(None)
        ).group_by(func.date_trunc('month', Document.date)).order_by(
            func.date_trunc('month', Document.date).desc()
        ).limit(12).all()

        # Source breakdown (top 20 news sources)
        source_breakdown = session.query(
            Document.source_name,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.source_name.isnot(None)
        ).group_by(Document.source_name).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).limit(20).all()

        # Recent highlights (top 5 documents with highest salience scores or most recent)
        recent_highlights = session.query(
            Document.doc_id,
            Document.title,
            Document.date,
            Document.distilled_text,
            Document.salience_justification,
            Category.category,
            Subcategory.subcategory
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).join(
            Category,
            Category.doc_id == Document.doc_id,
            isouter=True
        ).join(
            Subcategory,
            Subcategory.doc_id == Document.doc_id,
            isouter=True
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.distilled_text.isnot(None)
        ).order_by(Document.date.desc()).limit(5).all()

        highlights = []
        for doc in recent_highlights:
            highlights.append({
                "doc_id": doc.doc_id,
                "title": doc.title,
                "date": str(doc.date) if doc.date else None,
                "distilled_text": doc.distilled_text,
                "salience_justification": doc.salience_justification,
                "category": doc.category,
                "subcategory": doc.subcategory
            })

        return BilateralMetrics(
            influencer=influencer,
            recipient=recipient,
            total_documents=total_docs,
            category_breakdown=[{"category": cat, "count": count} for cat, count in category_breakdown],
            subcategory_breakdown=[{"subcategory": subcat, "count": count} for subcat, count in subcategory_breakdown],
            monthly_trend=[{"month": str(month.date()) if month else None, "count": count} for month, count in reversed(monthly_trend)],
            source_breakdown=[{"source": source, "count": count} for source, count in source_breakdown],
            recent_highlights=highlights
        )

@app.get("/api/metrics/recipient/{country}", response_model=RecipientMetrics)
def get_recipient_metrics(country: str):
    """Get comprehensive metrics for a specific recipient across all influencers."""
    with get_session() as session:
        if country not in RECIPIENTS:
            return {"error": f"{country} is not a recognized recipient"}

        # Total documents for this recipient from all influencers
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            RecipientCountry.recipient_country == country,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).scalar() or 0

        # Influencer breakdown (which influencers engage with this recipient)
        influencer_breakdown = session.query(
            InitiatingCountry.initiating_country,
            func.count(func.distinct(InitiatingCountry.doc_id)).label('count')
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == InitiatingCountry.doc_id
        ).filter(
            RecipientCountry.recipient_country == country,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(InitiatingCountry.initiating_country).order_by(
            func.count(func.distinct(InitiatingCountry.doc_id)).desc()
        ).all()

        # Category breakdown
        category_breakdown = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            RecipientCountry.recipient_country == country,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Category.category).order_by(
            func.count(func.distinct(Category.doc_id)).desc()
        ).all()

        # Subcategory breakdown (all)
        subcategory_breakdown = session.query(
            Subcategory.subcategory,
            func.count(func.distinct(Subcategory.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Subcategory.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Subcategory.doc_id
        ).filter(
            RecipientCountry.recipient_country == country,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(Subcategory.subcategory).order_by(
            func.count(func.distinct(Subcategory.doc_id)).desc()
        ).all()

        # Monthly trend
        monthly_trend = session.query(
            func.date_trunc('month', Document.date).label('month'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            RecipientCountry.recipient_country == country,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.date.isnot(None)
        ).group_by(func.date_trunc('month', Document.date)).order_by(
            func.date_trunc('month', Document.date).desc()
        ).limit(12).all()

        # Source breakdown (top 20 news sources)
        source_breakdown = session.query(
            Document.source_name,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            RecipientCountry.recipient_country == country,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
            Document.source_name.isnot(None)
        ).group_by(Document.source_name).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).limit(20).all()

        # Recent events involving this recipient (from all influencers)
        # Get doc_ids for this recipient
        recipient_doc_ids = session.query(
            Document.doc_id
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            RecipientCountry.recipient_country == country,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).subquery()

        # Get events mentioned in those documents
        from shared.models.models import DailyEventMention

        # Get list of doc_ids to check against
        recipient_doc_id_list = [row[0] for row in session.query(recipient_doc_ids).all()]

        recipient_events = session.query(
            CanonicalEvent.id,
            CanonicalEvent.canonical_name,
            CanonicalEvent.last_mention_date,
            CanonicalEvent.consolidated_description,
            CanonicalEvent.initiating_country,
            CanonicalEvent.total_articles
        ).join(
            DailyEventMention,
            DailyEventMention.canonical_event_id == CanonicalEvent.id
        ).filter(
            DailyEventMention.doc_ids.op('&&')(recipient_doc_id_list),
            CanonicalEvent.master_event_id.is_(None)  # Only master events
        ).distinct().order_by(CanonicalEvent.last_mention_date.desc()).limit(10).all()

        events = []
        for event in recipient_events:
            events.append({
                "id": str(event.id),
                "event_name": event.canonical_name,
                "event_date": str(event.last_mention_date) if event.last_mention_date else None,
                "summary": event.consolidated_description,
                "influencer": event.initiating_country,
                "total_mentions": event.total_articles
            })

        return RecipientMetrics(
            recipient=country,
            total_documents=total_docs,
            influencer_breakdown=[{"influencer": inf, "count": count} for inf, count in influencer_breakdown],
            category_breakdown=[{"category": cat, "count": count} for cat, count in category_breakdown],
            subcategory_breakdown=[{"subcategory": subcat, "count": count} for subcat, count in subcategory_breakdown],
            monthly_trend=[{"month": str(month.date()) if month else None, "count": count} for month, count in reversed(monthly_trend)],
            source_breakdown=[{"source": source, "count": count} for source, count in source_breakdown],
            recent_events=events
        )

# ===== BILATERAL RELATIONSHIP ENDPOINTS =====

class BilateralOverview(BaseModel):
    influencer: str
    recipient: str
    total_documents: int
    top_categories: list
    activity_trend: list
    recent_activities: list
    recent_events: list

@app.get("/api/bilateral/{influencer}/{recipient}", response_model=BilateralOverview)
def get_bilateral_overview(influencer: str, recipient: str):
    """Get comprehensive bilateral relationship data for a specific influencer-recipient pair."""
    with get_session() as session:
        # Validate countries
        if influencer not in INFLUENCERS:
            return {"error": f"{influencer} is not a recognized influencer"}
        if recipient not in RECIPIENTS:
            return {"error": f"{recipient} is not a recognized recipient"}

        # Total documents for this bilateral relationship
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).scalar() or 0

        # Top categories for this relationship
        top_categories = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry,
            RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).group_by(Category.category).order_by(func.count(func.distinct(Category.doc_id)).desc()).limit(5).all()

        # Activity trend (last 12 weeks)
        activity_trend = session.query(
            func.date_trunc('week', Document.date).label('week'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.date.isnot(None)
        ).group_by(func.date_trunc('week', Document.date)).order_by(func.date_trunc('week', Document.date).desc()).limit(12).all()

        # Recent activities with distilled text (top 10)
        recent_docs = session.query(
            Document.doc_id,
            Document.title,
            Document.date,
            Document.distilled_text,
            Document.event_name,
            Document.salience_justification
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.distilled_text.isnot(None),
            Document.date.isnot(None)
        ).order_by(Document.date.desc()).limit(10).all()

        activities = []
        for doc in recent_docs:
            activities.append({
                "doc_id": doc.doc_id,
                "title": doc.title,
                "date": str(doc.date) if doc.date else None,
                "distilled_text": doc.distilled_text,
                "event_name": doc.event_name,
                "salience_justification": doc.salience_justification
            })

        # Recent master events for this bilateral relationship
        # Note: CanonicalEvent doesn't have recipient_country, so we need to join through daily_event_mentions
        # For simplicity, we'll get all master events for the influencer and filter later in the frontend
        # Or we can use a more complex query - let's use a subquery approach

        # Get doc_ids for this bilateral relationship
        bilateral_doc_ids = session.query(
            Document.doc_id
        ).join(InitiatingCountry).join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).subquery()

        # Get events mentioned in those documents
        # This requires joining through DailyEventMention table
        from shared.models.models import DailyEventMention

        # Get list of doc_ids to check against
        bilateral_doc_id_list = [row[0] for row in session.query(bilateral_doc_ids).all()]

        bilateral_events = session.query(
            CanonicalEvent.id,
            CanonicalEvent.canonical_name,
            CanonicalEvent.last_mention_date,
            CanonicalEvent.consolidated_description,
            CanonicalEvent.total_articles
        ).join(
            DailyEventMention,
            DailyEventMention.canonical_event_id == CanonicalEvent.id
        ).filter(
            DailyEventMention.doc_ids.op('&&')(bilateral_doc_id_list),
            CanonicalEvent.master_event_id.is_(None)  # Only master events
        ).distinct().order_by(CanonicalEvent.last_mention_date.desc()).limit(5).all()

        events = []
        for event in bilateral_events:
            events.append({
                "id": str(event.id),
                "event_name": event.canonical_name,
                "event_date": str(event.last_mention_date) if event.last_mention_date else None,
                "summary": event.consolidated_description,
                "total_mentions": event.total_articles
            })

        return BilateralOverview(
            influencer=influencer,
            recipient=recipient,
            total_documents=total_docs,
            top_categories=[{"category": cat, "count": count} for cat, count in top_categories],
            activity_trend=[{"week": str(week.date()) if week else None, "count": count} for week, count in reversed(activity_trend)],
            recent_activities=activities,
            recent_events=events
        )

# ===== DOCUMENT-BASED SUMMARY ENDPOINTS =====

PUBLICATIONS_DIR = Path(__file__).parent.parent / "publications"
EVENTS_DIR = Path(__file__).parent.parent / "publications" / "events"

class SummaryListResponse(BaseModel):
    summaries: list
    influencer: str
    recipient: Optional[str]

class SummaryDetailResponse(BaseModel):
    summary: dict

@app.get("/api/document-summaries/list")
def list_document_summaries(
    influencer: str = Query(..., description="Influencer country"),
    recipient: Optional[str] = Query(None, description="Optional recipient country"),
    level: str = Query("daily", description="Summary level: daily, weekly, monthly, or overall")
):
    """List available document-based summaries for an influencer (and optionally recipient)."""
    import json

    summaries = []

    # Build base path
    if recipient:
        base_path = PUBLICATIONS_DIR / influencer / recipient
    else:
        base_path = PUBLICATIONS_DIR / influencer

    if not base_path.exists():
        return SummaryListResponse(summaries=[], influencer=influencer, recipient=recipient)

    # Handle different levels
    if level == "overall":
        # Overall summaries are individual files at the base level
        for file in base_path.glob("overall_*.json"):
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                summaries.append({
                    "filename": file.name,
                    "period_start": data.get('period_start'),
                    "period_end": data.get('period_end'),
                    "influencer": data.get('influencer'),
                    "recipient": data.get('recipient'),
                    "total_documents": data.get('metrics', {}).get('total_documents', 0)
                })
    else:
        # Daily, weekly, monthly are in subdirectories
        summary_path = base_path / level
        if summary_path.exists():
            for file in sorted(summary_path.glob("*.json"), reverse=True):
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    summaries.append({
                        "filename": file.name,
                        "date": data.get('date'),  # Daily
                        "period_start": data.get('period_start'),  # Weekly/Monthly
                        "period_end": data.get('period_end'),  # Weekly/Monthly
                        "influencer": data.get('influencer'),
                        "recipient": data.get('recipient'),
                        "total_documents": data.get('metrics', {}).get('total_documents', 0)
                    })

    return SummaryListResponse(summaries=summaries, influencer=influencer, recipient=recipient)

@app.get("/api/document-summaries/detail")
def get_document_summary_detail(
    influencer: str = Query(..., description="Influencer country"),
    filename: str = Query(..., description="Summary filename"),
    recipient: Optional[str] = Query(None, description="Optional recipient country")
):
    """Get the full detail of a specific document-based summary."""
    import json

    # Build path based on bilateral or all-recipients
    if recipient:
        base_path = PUBLICATIONS_DIR / influencer / recipient
    else:
        base_path = PUBLICATIONS_DIR / influencer

    # Determine which subdirectory based on filename pattern
    if filename.startswith("overall_"):
        file_path = base_path / filename
    elif "_to_" in filename:
        # Weekly or monthly with period range
        if len(filename.split("_to_")[0].split("-")) == 3:  # YYYY-MM-DD format = weekly
            file_path = base_path / "weekly" / filename
        else:  # YYYY-MM format = monthly
            file_path = base_path / "monthly" / filename
    else:
        # Determine if it's monthly (YYYY-MM.json) or daily (YYYY-MM-DD.json)
        name_without_ext = filename.replace('.json', '')
        parts = name_without_ext.split('-')

        if len(parts) == 2:  # YYYY-MM format = monthly
            file_path = base_path / "monthly" / filename
        else:  # YYYY-MM-DD format = daily
            file_path = base_path / "daily" / filename

    if not file_path.exists():
        return {"error": "Summary not found"}

    with open(file_path, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)

    return SummaryDetailResponse(summary=summary_data)

@app.get("/api/document-summaries/available-influencers")
def get_available_summary_influencers():
    """Get list of influencers that have document summaries."""
    if not PUBLICATIONS_DIR.exists():
        return {"influencers": []}

    influencers = [d.name for d in PUBLICATIONS_DIR.iterdir() if d.is_dir()]
    return {"influencers": sorted(influencers)}

@app.get("/api/document-summaries/available-recipients")
def get_available_summary_recipients(influencer: str):
    """Get list of recipients that have summaries for a specific influencer."""
    influencer_path = PUBLICATIONS_DIR / influencer
    if not influencer_path.exists():
        return {"recipients": []}

    recipients = [d.name for d in influencer_path.iterdir() if d.is_dir()]
    return {"recipients": sorted(recipients)}

# ===== BILATERAL SUMMARY ENDPOINTS =====

# ===== EVENT TIMELINE ENDPOINTS =====

class EventTimelineResponse(BaseModel):
    events: list
    country: str
    date_range: dict

@app.get("/api/test-debug")
def test_debug():
    """Test endpoint to verify server is running updated code."""
    from pathlib import Path
    events_dir = Path(__file__).parent.parent / "publications" / "events"
    china_monthly = events_dir / "China" / "monthly"
    import json

    files = list(china_monthly.glob("*.json")) if china_monthly.exists() else []
    events_count = 0
    if files:
        with open(files[0], 'r') as f:
            data = json.load(f)
            events_count = len(data.get('events', []))

    return {
        "message": "Debug endpoint working!",
        "events_dir_exists": events_dir.exists(),
        "china_monthly_exists": china_monthly.exists(),
        "files_found": len(files),
        "events_in_first_file": events_count,
        "code_version": "2026-01-09-debug-v2"
    }

@app.get("/api/events/timeline", response_model=EventTimelineResponse)
def get_event_timeline(
    country: str = Query(..., description="Country name"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    level: str = Query("monthly", description="Consolidation level: daily, weekly, monthly, or overall")
):
    """Get event timeline with daily article density for Gantt chart visualization."""
    import json
    from datetime import datetime
    import sys

    print(f"DEBUG: get_event_timeline called with country={country}, level={level}", file=sys.stderr, flush=True)

    events_country_dir = EVENTS_DIR / country
    print(f"DEBUG: EVENTS_DIR={EVENTS_DIR}, events_country_dir={events_country_dir}", file=sys.stderr, flush=True)

    if not events_country_dir.exists():
        return EventTimelineResponse(
            events=[],
            country=country,
            date_range={"start": start_date, "end": end_date}
        )

    # Load events based on level
    events_data = []

    if level == "overall":
        # Load overall file
        overall_files = list(events_country_dir.glob("overall_*_events.json"))
        for overall_file in overall_files:
            try:
                with open(overall_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    events_data.extend(data.get('events', []))
            except Exception as e:
                print(f"Error reading {overall_file}: {e}")

    elif level == "monthly":
        # Load monthly files in date range
        monthly_dir = events_country_dir / "monthly"
        if monthly_dir.exists():
            for monthly_file in sorted(monthly_dir.glob("*_events.json")):
                try:
                    with open(monthly_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        events_data.extend(data.get('events', []))
                except Exception as e:
                    print(f"Error reading {monthly_file}: {e}")

    elif level == "weekly":
        # Load weekly files in date range
        weekly_dir = events_country_dir / "weekly"
        if weekly_dir.exists():
            for weekly_file in sorted(weekly_dir.glob("*_events.json")):
                try:
                    with open(weekly_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        events_data.extend(data.get('events', []))
                except Exception as e:
                    print(f"Error reading {weekly_file}: {e}")

    elif level == "daily":
        # Load daily files in date range
        daily_dir = events_country_dir / "daily"
        if daily_dir.exists():
            for daily_file in sorted(daily_dir.glob("*_events.json")):
                try:
                    with open(daily_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        events_data.extend(data.get('events', []))
                except Exception as e:
                    print(f"Error reading {daily_file}: {e}")

    # Process events to calculate daily article counts
    # For consolidated events, we need to trace back to daily sources
    processed_events = []

    print(f"DEBUG: Loaded {len(events_data)} events from files")
    print(f"DEBUG: First event keys: {list(events_data[0].keys()) if events_data else 'No events'}")

    for event in events_data:
        # Get date range
        date_range = event.get('date_range', {})
        first_mention = date_range.get('first_mention', 'Unknown')
        last_mention = date_range.get('last_mention', 'Unknown')

        # Get sources to determine dates
        daily_sources = event.get('daily_sources', [])
        weekly_sources = event.get('weekly_sources', [])
        source_doc_ids = event.get('source_doc_ids', [])
        total_docs = len(source_doc_ids)

        # If dates are Unknown, try to infer from daily_sources or weekly_sources
        if first_mention == 'Unknown' or last_mention == 'Unknown':
            if daily_sources:
                # Use first and last dates from daily_sources
                sorted_dates = sorted(daily_sources)
                if first_mention == 'Unknown':
                    first_mention = sorted_dates[0]
                if last_mention == 'Unknown':
                    last_mention = sorted_dates[-1]
            elif weekly_sources:
                # Convert week IDs to dates (e.g., "2025-W26" -> "2025-06-23")
                week_dates = []
                for week_id in weekly_sources:
                    try:
                        year, week = week_id.split('-W')
                        # ISO week date calculation
                        from datetime import datetime, timedelta
                        jan4 = datetime(int(year), 1, 4)
                        week_start = jan4 + timedelta(days=-jan4.weekday(), weeks=int(week)-1)
                        week_dates.append(week_start.strftime("%Y-%m-%d"))
                    except:
                        pass
                if week_dates:
                    sorted_dates = sorted(week_dates)
                    if first_mention == 'Unknown':
                        first_mention = sorted_dates[0]
                    if last_mention == 'Unknown':
                        # Week end is 6 days after start
                        from datetime import datetime, timedelta
                        last_week_start = datetime.strptime(sorted_dates[-1], "%Y-%m-%d")
                        last_week_end = last_week_start + timedelta(days=6)
                        last_mention = last_week_end.strftime("%Y-%m-%d")

        # Skip events that still have unknown dates after attempting to infer
        if first_mention == 'Unknown' and last_mention == 'Unknown':
            continue

        # Calculate daily article counts from source_doc_ids
        # For now, we'll distribute articles evenly across daily_sources

        daily_article_counts = {}
        if daily_sources:
            # Distribute documents across dates
            docs_per_day = total_docs / len(daily_sources)
            for date_str in daily_sources:
                daily_article_counts[date_str] = int(docs_per_day)

            # Add remainder to first day
            remainder = total_docs - (int(docs_per_day) * len(daily_sources))
            if remainder > 0 and daily_sources:
                daily_article_counts[daily_sources[0]] += remainder
        elif first_mention != 'Unknown':
            # If no daily_sources, put all docs on first_mention date
            daily_article_counts[first_mention] = total_docs

        # Get materiality score
        materiality_obj = event.get('materiality', {})
        if isinstance(materiality_obj, dict):
            materiality_score = materiality_obj.get('score', 0.0)
        else:
            materiality_score = float(materiality_obj) if materiality_obj else 0.0

        processed_event = {
            "event_name": event.get('event_name', 'Unnamed Event'),
            "event_summary": event.get('event_summary', ''),
            "date_range": {
                "first": first_mention,
                "last": last_mention
            },
            "daily_article_counts": daily_article_counts,
            "materiality": materiality_score,
            "category": event.get('category', 'Unknown'),
            "recipients": event.get('recipients', []),
            "source_doc_ids": source_doc_ids,
            "atom_search_url": event.get('atom_search_url', '')
        }

        processed_events.append(processed_event)

    # Sort events by first_mention date (most recent first)
    processed_events.sort(
        key=lambda x: x['date_range']['first'] if x['date_range']['first'] != 'Unknown' else '1900-01-01',
        reverse=True
    )

    return EventTimelineResponse(
        events=processed_events,
        country=country,
        date_range={"start": start_date, "end": end_date}
    )

@app.get("/api/bilateral-summaries/list")
def list_bilateral_summaries(
    influencer: str = Query(..., description="Influencer country"),
    month: Optional[str] = Query(None, description="Optional month filter (YYYY-MM)"),
    recipient: Optional[str] = Query(None, description="Optional recipient filter"),
    category: Optional[str] = Query(None, description="Optional category filter")
):
    """List available bilateral summaries with optional filters."""
    import json
    import re

    bilateral_path = PUBLICATIONS_DIR / influencer / "bilateral"
    if not bilateral_path.exists():
        return {"summaries": []}

    summaries = []

    # Pattern to match bilateral summary filenames
    # Examples: Egypt-Economic_2024-08.json, Egypt_2024-08.json, overall_2024-06-01_to_2024-12-31.json
    for file in sorted(bilateral_path.glob("*.json"), reverse=True):
        filename = file.name

        # Skip overall files in list view
        if filename.startswith("overall_"):
            continue

        # Parse filename
        # Format: {recipient}-{category}_{YYYY-MM}.json or {recipient}_{YYYY-MM}.json
        match_with_category = re.match(r'([^-]+)-([^_]+)_(\d{4}-\d{2})\.json', filename)
        match_without_category = re.match(r'([^_]+)_(\d{4}-\d{2})\.json', filename)

        if match_with_category:
            recip, cat, mon = match_with_category.groups()
        elif match_without_category:
            recip, mon = match_without_category.groups()
            cat = None
        else:
            continue

        # Apply filters
        if month and mon != month:
            continue
        if recipient and recip != recipient:
            continue
        if category and cat != category:
            continue

        # Load summary data with error handling for malformed JSON
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Warning: Skipping malformed JSON file {filename}: {e}")
            continue
        except Exception as e:
            print(f"Warning: Error reading {filename}: {e}")
            continue

        summaries.append({
            "filename": filename,
            "recipient": data.get('recipient'),
            "category": data.get('category'),
            "month": mon,
            "month_name": data.get('month_name'),
            "total_documents": data.get('metrics', {}).get('total_documents', 0)
        })

    return {"summaries": summaries, "influencer": influencer}

@app.get("/api/bilateral-summaries/detail")
def get_bilateral_summary_detail(
    influencer: str = Query(..., description="Influencer country"),
    filename: str = Query(..., description="Summary filename")
):
    """Get the full detail of a specific bilateral summary."""
    import json

    bilateral_path = PUBLICATIONS_DIR / influencer / "bilateral"
    file_path = bilateral_path / filename

    if not file_path.exists():
        return {"error": "Summary not found"}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
    except json.JSONDecodeError as e:
        return {"error": f"Malformed JSON in file {filename}: {str(e)}"}
    except Exception as e:
        return {"error": f"Error reading file {filename}: {str(e)}"}

    return {"summary": summary_data}

@app.get("/api/bilateral-summaries/overall")
def get_bilateral_overall_summary(
    influencer: str = Query(..., description="Influencer country"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)")
):
    """Get the bilateral overall rollup summary."""
    import json

    bilateral_path = PUBLICATIONS_DIR / influencer / "bilateral"
    filename = f"overall_{start_date}_to_{end_date}.json"
    file_path = bilateral_path / filename

    if not file_path.exists():
        return {"error": "Overall summary not found"}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
    except json.JSONDecodeError as e:
        return {"error": f"Malformed JSON in overall summary: {str(e)}"}
    except Exception as e:
        return {"error": f"Error reading overall summary: {str(e)}"}

    return {"summary": summary_data}

@app.get("/api/bilateral-summaries/available-months")
def get_available_bilateral_months(influencer: str):
    """Get list of months that have bilateral summaries."""
    import re

    bilateral_path = PUBLICATIONS_DIR / influencer / "bilateral"
    if not bilateral_path.exists():
        return {"months": []}

    months = set()
    for file in bilateral_path.glob("*.json"):
        if file.name.startswith("overall_"):
            continue

        # Extract month from filename
        match = re.search(r'_(\d{4}-\d{2})\.json', file.name)
        if match:
            months.add(match.group(1))

    return {"months": sorted(list(months), reverse=True)}


# ============================================================
# Report / Publication endpoints
# ============================================================

class ReportConfigResponse(BaseModel):
    influencers: list
    recipients: list
    categories: list
    date_range: dict

class ReportRequest(BaseModel):
    country: str
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    recipient: str = "All"
    top_events: int = 10
    model: str = "gpt-4o-mini"

@app.get("/api/report/config", response_model=ReportConfigResponse)
def get_report_config():
    """Return configuration options for the report generation form."""
    with get_session() as session:
        date_range_result = session.query(
            func.min(Document.date).label('min_date'),
            func.max(Document.date).label('max_date')
        ).join(InitiatingCountry).filter(
            InitiatingCountry.initiating_country.in_(INFLUENCERS)
        ).first()

        return ReportConfigResponse(
            influencers=sorted(INFLUENCERS),
            recipients=["All"] + sorted(RECIPIENTS),
            categories=CONFIG.get('categories', []),
            date_range={
                "min": str(date_range_result.min_date) if date_range_result and date_range_result.min_date else "2024-08-01",
                "max": str(date_range_result.max_date) if date_range_result and date_range_result.max_date else "2026-01-01"
            }
        )

@app.post("/api/report/generate")
def generate_report_endpoint(request: ReportRequest):
    """
    Generate a full publication report with LLM narratives, metrics, and citations.
    This is a long-running endpoint (30-60s due to LLM calls).
    """
    from server.report_generator import generate_report

    if request.country not in INFLUENCERS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"{request.country} is not a recognized influencer")

    recipient = None if request.recipient == "All" else request.recipient
    if recipient and recipient not in RECIPIENTS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"{request.recipient} is not a recognized recipient")

    result = generate_report(
        country=request.country,
        start_date_str=request.start_date,
        end_date_str=request.end_date,
        recipient=recipient,
        top_n=request.top_events,
        model=request.model
    )
    return result


@app.post("/api/report/stream")
def generate_report_stream_endpoint(request: ReportRequest):
    """
    SSE streaming version of report generation.
    Yields Server-Sent Events as report sections complete progressively.
    """
    import json
    from server.report_generator import generate_report_stream

    if request.country not in INFLUENCERS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"{request.country} is not a recognized influencer")

    recipient = None if request.recipient == "All" else request.recipient
    if recipient and recipient not in RECIPIENTS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"{request.recipient} is not a recognized recipient")

    def event_generator():
        try:
            for event in generate_report_stream(
                country=request.country,
                start_date_str=request.start_date,
                end_date_str=request.end_date,
                recipient=recipient,
                top_n=request.top_events,
                model=request.model
            ):
                event_type = event.get("type", "unknown")
                payload = json.dumps(event.get("payload", {}))
                yield f"event: {event_type}\ndata: {payload}\n\n"
        except GeneratorExit:
            print("[Report SSE] Client disconnected")
        except Exception as e:
            error_payload = json.dumps({"error": str(e)})
            yield f"event: error\ndata: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/report/export")
def export_report_endpoint(report_data: dict):
    """Export a completed report as a formatted Word document (.docx)."""
    from server.report_exporter import export_report_to_docx

    docx_bytes = export_report_to_docx(report_data)

    country = report_data.get('country', 'Report')
    period_start = report_data.get('period_start', '')
    filename = f"{country}_Report_{period_start}.docx"

    return StreamingResponse(
        docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ===== S3/BATCH/LLM PROXY ENDPOINTS =====
# These endpoints allow Docker containers to access S3 and OpenAI APIs
# through this host-based server (for credential/authority proxying)

# S3 Request/Response models
class S3DownloadRequest(BaseModel):
    bucket: str
    key: str

class S3ListRequest(BaseModel):
    bucket: str
    prefix: Optional[str] = ""
    max_keys: Optional[int] = 1000

class S3UploadRequest(BaseModel):
    bucket: str
    key: str
    content: str

class QueryInput(BaseModel):
    model: str = "gpt-4.1"
    sys_prompt: str
    prompt: str

class BatchCreateRequest(BaseModel):
    input_file_id: str
    endpoint: str = "/v1/chat/completions"
    completion_window: str = "24h"

class BatchStatusRequest(BaseModel):
    batch_id: str

class ParquetListRequest(BaseModel):
    bucket: str
    prefix: str = "embeddings/"
    max_keys: int = 1000

class ParquetDownloadRequest(BaseModel):
    bucket: str
    key: str
    num_rows: Optional[int] = None

class JsonListRequest(BaseModel):
    bucket: str
    prefix: str = "dsr_extracts/"
    max_keys: int = 1000

class JsonBatchRequest(BaseModel):
    bucket: str
    keys: List[str]

class ParquetBatchRequest(BaseModel):
    bucket: str
    keys: List[str]


# ----- LLM Query Endpoints -----

@app.post("/query")
def query_gai(input: QueryInput):
    """Simple LLM query endpoint."""
    if gai is None:
        raise HTTPException(status_code=500, detail="LLM utilities not available")
    response = gai(sys_prompt='', user_prompt=input.prompt, model=input.model)
    return fetch_gai_content(response)

@app.post("/material_query")
def material_gai_query(input: QueryInput):
    """
    LLM query endpoint with environment-based routing.
    Priority: LITELLM > Azure (production) > OpenAI (development)
    """
    # Check for LITELLM configuration first
    litellm_url = os.getenv('LITELLM_URL', '').strip()
    litellm_key = os.getenv('LITELLM_API_KEY', '').strip()
    litellm_model = os.getenv('LITELLM_MODEL', input.model).strip()

    if litellm_url and litellm_key and gai:
        try:
            content = gai(input.sys_prompt, input.prompt, litellm_model, source="litellm")
            return {"response": content}
        except Exception as e:
            print(f"LiteLLM call failed: {e}, falling back...")

    env = os.getenv('ENV', 'development').lower()

    if env == 'production' and gai:
        model = input.model if input.model != "gpt-4.1" else "gpt-4.1-mini"
        content = gai(input.sys_prompt, input.prompt, model, source="azure")
        return {"response": content}
    else:
        from openai import OpenAI
        api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="No OpenAI API key configured")

        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=input.model,
            messages=[
                {"role": "system", "content": input.sys_prompt},
                {"role": "user", "content": input.prompt},
            ],
            temperature=0.7,
        )
        content = completion.choices[0].message.content
        try:
            return {"response": json.loads(content)}
        except json.JSONDecodeError:
            return {"response": content}


# ----- OpenAI Batch API Proxy -----

@app.post("/batch/upload_file")
async def upload_batch_file(file: UploadFile = File(...)):
    """Proxy endpoint to upload JSONL file to OpenAI for batch processing."""
    from openai import OpenAI
    import httpx

    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    try:
        content = await file.read()
        file_size_mb = len(content) / (1024 * 1024)

        if file_size_mb > 100:
            raise HTTPException(status_code=413, detail=f"File too large: {file_size_mb:.2f} MB (max 100 MB)")

        with tempfile.NamedTemporaryFile(mode='wb', suffix='.jsonl', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            client = OpenAI(api_key=api_key, timeout=httpx.Timeout(600.0, connect=60.0), max_retries=2)
            with open(tmp_path, 'rb') as f:
                batch_file = client.files.create(file=f, purpose="batch")

            return {
                "file_id": batch_file.id,
                "filename": batch_file.filename,
                "bytes": batch_file.bytes,
                "created_at": batch_file.created_at,
                "status": batch_file.status
            }
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

@app.post("/batch/create")
async def create_batch(request: BatchCreateRequest):
    """Create batch job with OpenAI."""
    from openai import OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    try:
        client = OpenAI(api_key=api_key)
        batch = client.batches.create(
            input_file_id=request.input_file_id,
            endpoint=request.endpoint,
            completion_window=request.completion_window
        )
        return {
            "id": batch.id,
            "status": batch.status,
            "created_at": batch.created_at,
            "input_file_id": batch.input_file_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch creation failed: {str(e)}")

@app.post("/batch/status")
async def get_batch_status(request: BatchStatusRequest):
    """Check batch status with OpenAI."""
    from openai import OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    try:
        client = OpenAI(api_key=api_key)
        batch = client.batches.retrieve(request.batch_id)
        return {
            "id": batch.id,
            "status": batch.status,
            "created_at": batch.created_at,
            "completed_at": getattr(batch, 'completed_at', None),
            "failed_at": getattr(batch, 'failed_at', None),
            "output_file_id": batch.output_file_id,
            "error_file_id": batch.error_file_id,
            "request_counts": getattr(batch, 'request_counts', None)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch status check failed: {str(e)}")

@app.post("/batch/download_results")
async def download_batch_results(request: BatchStatusRequest):
    """Download batch results from OpenAI."""
    from openai import OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    try:
        client = OpenAI(api_key=api_key)
        batch = client.batches.retrieve(request.batch_id)

        if not batch.output_file_id:
            raise HTTPException(status_code=400, detail="Batch has no output file yet")

        file_content = client.files.content(batch.output_file_id)
        return {
            "batch_id": batch.id,
            "output_file_id": batch.output_file_id,
            "content": file_content.text,
            "status": batch.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Results download failed: {str(e)}")


# ----- S3 Endpoints -----

@app.post("/s3/download")
async def download_s3_file(request: S3DownloadRequest):
    """Download file from S3 and return content."""
    try:
        response = s3_client.get_object(Bucket=request.bucket, Key=request.key)
        content = response['Body'].read()
        return {
            "bucket": request.bucket,
            "key": request.key,
            "size": len(content),
            "content": content.decode('utf-8') if request.key.endswith(('.txt', '.json', '.csv')) else None,
            "content_type": response['ContentType']
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.post("/s3/list")
async def list_s3_files(request: S3ListRequest):
    """List files in S3 bucket with optional prefix."""
    try:
        response = s3_client.list_objects_v2(
            Bucket=request.bucket,
            Prefix=request.prefix,
            MaxKeys=request.max_keys
        )
        files = [{
            "key": obj['Key'],
            "size": obj['Size'],
            "last_modified": obj['LastModified'].isoformat()
        } for obj in response.get('Contents', [])]
        return {"bucket": request.bucket, "prefix": request.prefix, "count": len(files), "files": files}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.post("/s3/upload")
async def upload_s3_content(request: S3UploadRequest):
    """Upload content to S3."""
    try:
        s3_client.put_object(
            Bucket=request.bucket,
            Key=request.key,
            Body=request.content.encode('utf-8'),
            ContentType='application/json'
        )
        return {"bucket": request.bucket, "key": request.key, "status": "uploaded"}
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")


# ----- S3 Parquet Endpoints -----

@app.post("/s3/parquet/list")
async def list_parquet_files(request: ParquetListRequest):
    """List parquet files in S3 prefix."""
    try:
        s3_prefix = request.prefix.rstrip('/') + '/'
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=request.bucket, Prefix=s3_prefix, PaginationConfig={'MaxItems': request.max_keys})

        parquet_files = []
        for page in pages:
            for obj in page.get('Contents', []):
                if obj['Key'].endswith('.parquet'):
                    parquet_files.append({
                        'key': obj['Key'],
                        'filename': obj['Key'].split('/')[-1],
                        'size': obj['Size'],
                        'size_mb': round(obj['Size'] / (1024 * 1024), 2),
                        'last_modified': obj['LastModified'].isoformat()
                    })
        return {'bucket': request.bucket, 'prefix': request.prefix, 'count': len(parquet_files), 'files': parquet_files}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.post("/s3/parquet/metadata")
async def get_parquet_metadata(request: S3DownloadRequest):
    """Get metadata from parquet file without downloading full data."""
    temp_path = None
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.parquet')
        temp_path = temp_file.name
        temp_file.close()
        s3_client.download_file(request.bucket, request.key, temp_path)

        parquet_file = pq.ParquetFile(temp_path)
        metadata = parquet_file.metadata
        return {
            'filename': request.key.split('/')[-1],
            'num_rows': metadata.num_rows,
            'num_columns': metadata.num_columns,
            'columns': [{'name': parquet_file.schema[i].name, 'type': str(parquet_file.schema[i].physical_type)} for i in range(len(parquet_file.schema))]
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@app.get("/s3/parquet/download-binary")
async def download_parquet_binary(bucket: str, key: str):
    """Download parquet file as binary data."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return StreamingResponse(
            response['Body'],
            media_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{key.split("/")[-1]}"'}
        )
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


# ----- S3 JSON Endpoints -----

@app.post("/s3/json/list")
async def list_json_files(request: JsonListRequest):
    """List JSON files in S3 prefix."""
    try:
        s3_prefix = request.prefix.rstrip('/') + '/'
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=request.bucket, Prefix=s3_prefix, PaginationConfig={'MaxItems': request.max_keys})

        json_files = []
        for page in pages:
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.endswith('.json') and 'errors' not in key and 'processed_files.json' not in key:
                    json_files.append({
                        'key': key,
                        'filename': key.split('/')[-1],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat()
                    })
        return {'bucket': request.bucket, 'prefix': request.prefix, 'count': len(json_files), 'files': json_files}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.post("/s3/json/download")
async def download_json_file(request: S3DownloadRequest):
    """Download and parse a JSON file from S3."""
    try:
        response = s3_client.get_object(Bucket=request.bucket, Key=request.key)
        content = response['Body'].read().decode('utf-8')
        data = json.loads(content)
        return {'filename': request.key.split('/')[-1], 's3_key': request.key, 'data': data}
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

@app.post("/s3/json/batch-download")
async def batch_download_json(request: JsonBatchRequest):
    """Download multiple JSON files from S3."""
    results = {'bucket': request.bucket, 'successful': 0, 'failed': 0, 'files': []}
    for s3_key in request.keys:
        try:
            response = s3_client.get_object(Bucket=request.bucket, Key=s3_key)
            content = response['Body'].read().decode('utf-8')
            data = json.loads(content)
            results['successful'] += 1
            results['files'].append({'filename': s3_key.split('/')[-1], 's3_key': s3_key, 'status': 'success', 'data': data})
        except Exception as e:
            results['failed'] += 1
            results['files'].append({'filename': s3_key.split('/')[-1], 's3_key': s3_key, 'status': 'failed', 'error': str(e)})
    return results


# ===== CHAT/RAG ENDPOINTS =====

class ChatRequest(BaseModel):
    message: str
    influencer: Optional[str] = None
    recipient: Optional[str] = None
    category: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class ChatExportRequest(BaseModel):
    messages: list
    format: str = "markdown"  # markdown, json, txt

@app.post("/api/chat")
async def chat_query(request: ChatRequest):
    """
    Send a chat message and get a response with sources.
    Non-streaming version for simple integrations.

    Supports intelligent query analysis - temporal keywords like "recently"
    will automatically filter to recent documents, and country/category
    references will apply appropriate filters.

    Includes entity-aware search with soft boosting for documents
    mentioning matched entities.
    """
    from services.chat.rag_service import intelligent_search, generate_response

    # Perform intelligent semantic search with automatic filter inference and entity boost
    sources, search_metadata = intelligent_search(
        query=request.message,
        k=10,
        influencer=request.influencer,
        recipient=request.recipient,
        category=request.category,
        start_date=request.start_date,
        end_date=request.end_date,
        apply_intelligence=True,
        enable_entity_boost=True
    )

    # Get matched entities for context injection
    matched_entities = search_metadata.get("_matched_entities_full", [])

    # Generate response with entity context injection
    response_text = generate_response(request.message, sources, matched_entities=matched_entities)

    return {
        "response": response_text,
        "sources": sources,
        "filters_applied": search_metadata["applied_filters"],
        "filters_inferred": search_metadata["inferred_filters"],
        "inference_notes": search_metadata["confidence_notes"],
        "matched_entities": search_metadata.get("matched_entities", [])
    }

@app.post("/api/chat/stream")
async def chat_query_stream(request: ChatRequest):
    """
    Send a chat message and get a streaming response.
    Uses Server-Sent Events (SSE) for real-time streaming.

    Supports intelligent query analysis - temporal keywords like "recently"
    will automatically filter to recent documents, and country/category
    references will apply appropriate filters.

    Includes entity-aware search with soft boosting for documents
    mentioning matched entities, and entity context injection.
    """
    from services.chat.rag_service import intelligent_search, generate_response_stream
    import json

    # Perform intelligent semantic search with automatic filter inference and entity boost
    sources, search_metadata = intelligent_search(
        query=request.message,
        k=10,
        influencer=request.influencer,
        recipient=request.recipient,
        category=request.category,
        start_date=request.start_date,
        end_date=request.end_date,
        apply_intelligence=True,
        enable_entity_boost=True
    )

    # Get matched entities for context injection
    matched_entities = search_metadata.get("_matched_entities_full", [])

    async def event_generator():
        # First, send search metadata (applied filters, inferences, matched entities)
        metadata_payload = {
            'type': 'metadata',
            'applied_filters': search_metadata['applied_filters'],
            'inferred_filters': search_metadata['inferred_filters'],
            'inference_notes': search_metadata['confidence_notes'],
            'matched_entities': search_metadata.get('matched_entities', [])
        }
        yield f"data: {json.dumps(metadata_payload)}\n\n"

        # Then send the sources
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        # Then stream the response with entity context injection
        for chunk in generate_response_stream(request.message, sources, matched_entities=matched_entities):
            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

        # Signal completion
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@app.post("/api/chat/export")
async def export_chat(request: ChatExportRequest):
    """
    Export chat messages in various formats.
    """
    from services.chat.rag_service import format_export

    exported = format_export(request.messages, request.format)

    # Set appropriate content type
    content_types = {
        "markdown": "text/markdown",
        "json": "application/json",
        "txt": "text/plain"
    }

    return StreamingResponse(
        iter([exported]),
        media_type=content_types.get(request.format, "text/plain"),
        headers={
            "Content-Disposition": f"attachment; filename=chat_export.{request.format if request.format != 'markdown' else 'md'}"
        }
    )

@app.get("/api/chat/filters")
async def get_chat_filters():
    """
    Get available filter options for chat (from config.yaml).
    """
    with get_session() as session:
        # Get categories from database
        categories = session.query(Category.category).distinct().all()
        category_list = sorted([c[0] for c in categories if c[0]])

    return {
        "influencers": INFLUENCERS,
        "recipients": RECIPIENTS,
        "categories": category_list
    }


# ===== AUTHENTICATION ENDPOINTS =====

@app.post("/api/auth/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """Authenticate user and return JWT token."""
    with get_session() as session:
        user = session.query(User).filter(
            User.username == request.username,
            User.is_active == True,
            User.is_deleted == False
        ).first()

        if not user or not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        # Update last login
        user.last_login = datetime.utcnow()
        session.commit()

        # Create token
        token = create_access_token(
            user_id=str(user.id),
            username=user.username,
            role=user.role.value
        )

        return LoginResponse(
            access_token=token,
            user={
                "id": str(user.id),
                "username": user.username,
                "role": user.role.value,
                "display_name": user.display_name,
                "force_password_change": user.force_password_change
            }
        )

@app.get("/api/auth/verify")
def verify_auth(current_user: dict = Depends(get_current_user)):
    """Verify current token and return user info."""
    with get_session() as session:
        user = session.query(User).filter(
            User.id == current_user["user_id"],
            User.is_active == True,
            User.is_deleted == False
        ).first()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return {
            "id": str(user.id),
            "username": user.username,
            "role": user.role.value,
            "display_name": user.display_name,
            "force_password_change": user.force_password_change
        }

@app.post("/api/auth/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """Change user's own password."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user["user_id"]).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not verify_password(request.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

        user.password_hash = hash_password(request.new_password)
        user.force_password_change = False
        user.updated_at = datetime.utcnow()
        session.commit()

        return {"message": "Password changed successfully"}


# ===== ADMIN USER MANAGEMENT ENDPOINTS =====

@app.get("/api/admin/users")
def list_users(current_user: dict = Depends(require_admin)):
    """List all users (admin only)."""
    with get_session() as session:
        users = session.query(User).filter(User.is_deleted == False).all()
        return {"users": [u.to_dict() for u in users]}

@app.post("/api/admin/users")
def create_user(
    request: UserCreateRequest,
    current_user: dict = Depends(require_admin)
):
    """Create a new user (admin only)."""
    with get_session() as session:
        # Check if username exists
        existing = session.query(User).filter(User.username == request.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")

        # Validate role
        try:
            role = UserRole(request.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {request.role}")

        user = User(
            username=request.username,
            password_hash=hash_password(request.password),
            role=role,
            display_name=request.display_name,
            force_password_change=request.force_password_change,
            created_by=current_user["user_id"]
        )
        session.add(user)
        session.commit()

        return {"message": "User created", "user": user.to_dict()}

@app.put("/api/admin/users/{user_id}")
def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: dict = Depends(require_admin)
):
    """Update a user (admin only)."""
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id, User.is_deleted == False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if request.role is not None:
            try:
                user.role = UserRole(request.role)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid role: {request.role}")

        if request.display_name is not None:
            user.display_name = request.display_name
        if request.is_active is not None:
            user.is_active = request.is_active
        if request.force_password_change is not None:
            user.force_password_change = request.force_password_change

        user.updated_at = datetime.utcnow()
        session.commit()

        return {"message": "User updated", "user": user.to_dict()}

@app.post("/api/admin/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    request: ResetPasswordRequest,
    current_user: dict = Depends(require_admin)
):
    """Reset a user's password (admin only)."""
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id, User.is_deleted == False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.password_hash = hash_password(request.new_password)
        user.force_password_change = True
        user.updated_at = datetime.utcnow()
        session.commit()

        return {"message": "Password reset successfully"}

@app.delete("/api/admin/users/{user_id}")
def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """Soft delete a user (admin only)."""
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id, User.is_deleted == False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Prevent self-deletion
        if str(user.id) == current_user["user_id"]:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")

        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        session.commit()

        return {"message": "User deleted"}


# Static file serving for React SPA
# IMPORTANT: This must come AFTER all @app.get() API route definitions
# so that API routes take precedence over the catch-all
if STATIC_DIR.exists():
    # Mount static assets directory
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    # Serve index.html for root path
    @app.get("/", include_in_schema=False)
    async def serve_root():
        return FileResponse(STATIC_DIR / "index.html")

    # Catch-all for SPA routing - MUST exclude /api/* paths
    # FastAPI routes are matched in order, but catch-all patterns can override
    # So we explicitly check and reject API paths
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Skip if this is an API path - let FastAPI's 404 handler take over
        if full_path.startswith("api"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")

        # Try to serve static file if it exists
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

        # Otherwise serve index.html for SPA routing
        return FileResponse(STATIC_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)
