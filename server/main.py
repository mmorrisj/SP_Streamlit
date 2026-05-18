import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query, HTTPException, File, UploadFile, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
from sqlalchemy import func, Text
from pathlib import Path
import yaml
import json
import uuid
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
from shared.cache.redis_cache import cache, init_cache, get_cache
from shared.models.models import (
    Document, EventSummary, CanonicalEvent, DailyEventMention,
    Category, Subcategory, InitiatingCountry, RecipientCountry,
    User, UserRole, PeriodType, EventSourceLink,
    CanonicalEntity, BilateralRelationshipSummary, CountryCategorySummary,
    EntityRelationship, DailyEntityMention,
)
from shared.models.alert_models import (
    AlertRule, AlertHistory, AlertConditionType, AlertSeverity,
)
from shared.models.research_project_models import (
    ResearchProject, ProjectDocument, ProjectStatus,
)
from server.auth import (
    verify_enterprise_token, extract_user_info, get_dev_user_info,
    ENTERPRISE_JWT_HEADER, DEV_AUTH_BYPASS, DEV_AUTH_ROLE
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

# Agent module: isolated runtime for the OSINT-style agent page.
# Guarded so a broken agent import cannot take down the foundational API.
try:
    from agent.router import router as agent_router
    app.include_router(agent_router)
except Exception as _agent_err:  # pragma: no cover - defensive
    import logging as _logging
    _logging.getLogger(__name__).warning("agent router not loaded: %s", _agent_err)

def _get_narrative_for_events(session, event_names: list, country: str) -> dict:
    """
    Batch-load the most recent EventSummary narrative for each event name.
    Returns {event_name: {overview, outcomes, source_link, source_count, citations}}.
    """
    if not event_names:
        return {}

    from sqlalchemy import text as sql_text
    rows = session.execute(sql_text("""
        SELECT DISTINCT ON (event_name)
            event_name,
            narrative_summary,
            material_score,
            material_justification
        FROM event_summaries
        WHERE initiating_country = :country
          AND event_name = ANY(:names)
          AND is_deleted = false
        ORDER BY event_name, period_start DESC
    """), {"country": country, "names": event_names}).fetchall()

    result = {}
    for row in rows:
        ns = row.narrative_summary or {}
        result[row.event_name] = {
            "overview": ns.get("overview"),
            "outcomes": ns.get("outcomes"),
            "source_link": ns.get("source_link"),
            "source_count": ns.get("source_count"),
            "citations": ns.get("citations", []),
        }
    return result


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
    total: Optional[int] = None

class SummariesResponse(BaseModel):
    summaries: list
    total: Optional[int] = None

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

class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    display_name: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    id: str
    username: str
    enterprise_id: Optional[str]
    role: str
    display_name: Optional[str]
    is_active: bool
    created_at: Optional[str]
    last_login: Optional[str]


# ===== AUTHENTICATION DEPENDENCIES =====

def get_current_user(request: Request) -> dict:
    """
    Dependency to get current user from enterprise JWT gateway.

    The enterprise platform provides a JWT in the 'x-kiosk-gateway-jwt' header
    on every request. This dependency validates it and auto-provisions users.

    For local development, set DEV_AUTH_BYPASS=true in .env to skip JWT
    validation entirely.  MUST be unset/false in production.
    """
    if DEV_AUTH_BYPASS:
        # Local dev mode – skip JWT validation, use synthetic dev user
        user_info = get_dev_user_info()
    else:
        token = request.headers.get(ENTERPRISE_JWT_HEADER)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated - missing enterprise JWT header")

        payload = verify_enterprise_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired enterprise token")

        # Extract user info from enterprise JWT claims
        user_info = extract_user_info(payload)

    # Auto-provision or update user in local database
    with get_session() as session:
        user = None
        # Look up by enterprise_id first, then by username
        if user_info["enterprise_id"]:
            user = session.query(User).filter(
                User.enterprise_id == user_info["enterprise_id"],
                User.is_deleted == False
            ).first()

        if not user:
            user = session.query(User).filter(
                User.username == user_info["username"],
                User.is_deleted == False
            ).first()

        if user:
            # Update last login and sync enterprise_id if needed
            user.last_login = datetime.now(timezone.utc)
            if user_info["enterprise_id"] and not user.enterprise_id:
                user.enterprise_id = user_info["enterprise_id"]
            if user_info["display_name"] and not user.display_name:
                user.display_name = user_info["display_name"]
            if not user.is_active:
                raise HTTPException(status_code=403, detail="Account is deactivated")
        else:
            # Auto-provision new user
            # Dev bypass gets DEV_AUTH_ROLE; enterprise users get default viewer
            default_role = UserRole(DEV_AUTH_ROLE) if DEV_AUTH_BYPASS else UserRole.VIEWER
            user = User(
                enterprise_id=user_info["enterprise_id"],
                username=user_info["username"],
                display_name=user_info["display_name"],
                role=default_role,
            )
            session.add(user)

        session.commit()
        # Refresh to get the committed state
        session.refresh(user)

        return {
            "user_id": str(user.id),
            "username": user.username,
            "role": user.role.value,
            "display_name": user.display_name,
            "enterprise_id": user.enterprise_id,
        }

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


@app.on_event("startup")
def startup_event():
    init_cache()  # Graceful: logs warning and continues if Redis unavailable
    # Start background alert evaluation scheduler
    from server.alert_evaluator import start_alert_scheduler
    start_alert_scheduler()


@app.on_event("shutdown")
def shutdown_event():
    from server.alert_evaluator import stop_alert_scheduler
    stop_alert_scheduler()


@app.get("/api/health")
def health_check():
    rc = get_cache()
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache": "redis" if rc.available else "disabled",
    }


@app.post("/api/cache/clear")
def clear_cache(current_user: dict = Depends(require_admin)):
    """Admin-only: flush all cached API responses."""
    rc = get_cache()
    if not rc.available:
        return {"status": "cache_disabled", "cleared": 0}
    count = rc.delete_pattern("api:*")
    return {"status": "ok", "cleared": count}


@app.get("/api/documents/stats", response_model=DocumentStats)
@cache(ttl=300, prefix="doc_stats")
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
    category: Optional[str] = None,
    doc_ids: Optional[str] = None,
):
    with get_session() as session:
        # Build base query with proper joins for filtering
        query = session.query(Document)

        if doc_ids:
            # Comma-separated list of doc_id UUIDs. Used by the agent report
            # page to jump from cite chips into the documents view.
            id_list = [d.strip() for d in doc_ids.split(',') if d.strip()]
            if id_list:
                query = query.filter(Document.doc_id.in_(id_list))

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
    story_phase: Optional[str] = None,
    sort_by: str = Query(default="recency", pattern="^(recency|articles|materiality)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    with get_session() as session:
        query = session.query(CanonicalEvent).filter(
            CanonicalEvent.master_event_id.is_(None)
        )

        if country and country != 'ALL':
            query = query.filter(CanonicalEvent.initiating_country == country)

        if story_phase and story_phase != 'ALL':
            query = query.filter(CanonicalEvent.story_phase == story_phase)

        total = query.count()

        if sort_by == "articles":
            query = query.order_by(CanonicalEvent.total_articles.desc())
        elif sort_by == "materiality":
            query = query.order_by(CanonicalEvent.material_score.desc().nullslast())
        else:
            query = query.order_by(CanonicalEvent.last_mention_date.desc())

        events = query.offset(offset).limit(limit).all()

        # Batch load narrative enrichment
        event_names = [e.canonical_name for e in events if e.canonical_name]
        countries_set = set(e.initiating_country for e in events if e.initiating_country)
        narratives = {}
        for c in countries_set:
            names_for_c = [e.canonical_name for e in events if e.initiating_country == c]
            narratives.update({f"{c}::{n}": v for n, v in _get_narrative_for_events(session, names_for_c, c).items()})

        event_list = []
        for event in events:
            narr = narratives.get(f"{event.initiating_country}::{event.canonical_name}", {})
            top_cats = event.primary_categories or {}
            top_recips = event.primary_recipients or {}
            top_cat = max(top_cats, key=top_cats.get) if top_cats else None
            event_list.append({
                "id": str(event.id),
                "event_name": event.canonical_name or "",
                "event_date": str(event.first_mention_date) if event.first_mention_date else None,
                "initiating_country": event.initiating_country or "",
                "recipient_country": ", ".join(list(top_recips.keys())[:3]) if top_recips else "",
                "category": top_cat or "",
                "description": event.consolidated_description or "",
                "last_mention_date": str(event.last_mention_date) if event.last_mention_date else None,
                "total_articles": event.total_articles or 0,
                "total_mention_days": event.total_mention_days or 0,
                "story_phase": event.story_phase,
                "material_score": float(event.material_score) if event.material_score else None,
                "source_count": event.source_count or 0,
                "primary_categories": top_cats,
                "primary_recipients": top_recips,
                "narrative_overview": narr.get("overview"),
                "narrative_outcomes": narr.get("outcomes"),
                "source_link": narr.get("source_link"),
            })

        return EventsResponse(events=event_list, total=total)

@app.get("/api/events/{event_id:uuid}")
def get_event_detail(event_id: uuid.UUID):
    """Get full detail for a single event, combining CanonicalEvent + EventSummary data."""
    with get_session() as session:
        event = session.query(CanonicalEvent).filter(
            CanonicalEvent.id == event_id
        ).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        # Get narrative from EventSummary
        narr = _get_narrative_for_events(
            session, [event.canonical_name], event.initiating_country
        ).get(event.canonical_name, {})

        # Get daily mentions timeline
        mentions = session.query(DailyEventMention).filter(
            DailyEventMention.canonical_event_id == event.id
        ).order_by(DailyEventMention.mention_date.desc()).all()

        mention_list = []
        for m in mentions:
            mention_list.append({
                "date": str(m.mention_date) if m.mention_date else None,
                "headline": m.consolidated_headline,
                "summary": m.daily_summary,
                "article_count": m.article_count,
                "news_intensity": m.news_intensity,
                "mention_context": m.mention_context,
                "source_names": m.source_names or [],
            })

        # Fallback description: if no consolidated_description, build from
        # linked documents' distilled text
        description = event.consolidated_description
        if not description:
            # Get distilled text from linked documents via daily mentions
            all_doc_ids = []
            for m in mentions:
                if m.doc_ids:
                    all_doc_ids.extend(m.doc_ids[:5])  # Cap per mention
            if all_doc_ids:
                from sqlalchemy import text as sql_text
                docs = session.execute(
                    sql_text("SELECT distilled_text FROM documents WHERE doc_id = ANY(:ids) LIMIT 3"),
                    {"ids": all_doc_ids[:10]}
                ).fetchall()
                if docs:
                    description = "\n\n".join(d.distilled_text for d in docs if d.distilled_text)

        # Fallback narrative: if no EventSummary exists, use description
        narrative_overview = narr.get("overview") or description

        return {
            "id": str(event.id),
            "event_name": event.canonical_name,
            "description": description,
            "initiating_country": event.initiating_country,
            "first_mention_date": str(event.first_mention_date) if event.first_mention_date else None,
            "last_mention_date": str(event.last_mention_date) if event.last_mention_date else None,
            "total_articles": event.total_articles,
            "total_mention_days": event.total_mention_days,
            "story_phase": event.story_phase,
            "material_score": float(event.material_score) if event.material_score else None,
            "material_justification": event.material_justification,
            "peak_mention_date": str(event.peak_mention_date) if event.peak_mention_date else None,
            "peak_daily_article_count": event.peak_daily_article_count,
            "source_count": event.source_count,
            "primary_categories": event.primary_categories or {},
            "primary_recipients": event.primary_recipients or {},
            "alternative_names": event.alternative_names or [],
            "narrative_overview": narrative_overview,
            "narrative_outcomes": narr.get("outcomes"),
            "source_link": narr.get("source_link"),
            "source_count_from_summary": narr.get("source_count"),
            "citations": narr.get("citations", []),
            "daily_mentions": mention_list,
        }


@app.get("/api/summaries", response_model=SummariesResponse)
def get_summaries(
    type: str = Query("daily", description="Summary type: daily, weekly, monthly, or yearly"),
    country: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    with get_session() as session:
        # Map type string to PeriodType enum
        period_map = {
            "daily": PeriodType.DAILY,
            "weekly": PeriodType.WEEKLY,
            "monthly": PeriodType.MONTHLY,
            "yearly": PeriodType.YEARLY,
        }
        period_type = period_map.get(type, PeriodType.DAILY)

        query = session.query(EventSummary).filter(
            EventSummary.period_type == period_type,
            EventSummary.is_deleted == False
        )

        if country and country != 'ALL':
            query = query.filter(EventSummary.initiating_country == country)

        total = query.count()
        summaries = query.order_by(EventSummary.period_start.desc()).offset(offset).limit(limit).all()

        ns_list = []
        for s in summaries:
            ns = s.narrative_summary or {}

            # Normalize narrative keys across period types
            # Daily: overview, outcomes, citations, source_link, source_count
            # Weekly: overview, outcomes, progression
            # Monthly: monthly_overview, key_outcomes, strategic_significance
            # Yearly: yearly_overview, major_developments, annual_outcomes, strategic_assessment
            overview = ns.get("overview") or ns.get("monthly_overview") or ns.get("yearly_overview") or ""
            outcomes = ns.get("outcomes") or ns.get("key_outcomes") or ns.get("annual_outcomes") or ""
            progression = ns.get("progression") or ns.get("major_developments") or ""
            strategic = ns.get("strategic_significance") or ns.get("strategic_assessment") or ""

            ns_list.append({
                "id": str(s.id),
                "summary_type": s.period_type.value if s.period_type else type,
                "period_start": str(s.period_start) if s.period_start else None,
                "period_end": str(s.period_end) if s.period_end else None,
                "content": s.event_name or "",
                "country": s.initiating_country or "",
                "overview": overview,
                "outcomes": outcomes,
                "progression": progression,
                "strategic": strategic,
                "source_link": ns.get("source_link"),
                "source_count": ns.get("source_count"),
                "citations": ns.get("citations", []),
                "count_by_category": s.count_by_category or {},
                "count_by_subcategory": s.count_by_subcategory or {},
                "count_by_recipient": s.count_by_recipient or {},
                "count_by_source": s.count_by_source or {},
                "material_score": float(s.material_score) if s.material_score else None,
                "material_justification": s.material_justification,
                "canonical_event_id": str(s.canonical_event_id) if s.canonical_event_id else None,
                "first_observed_date": str(s.first_observed_date) if s.first_observed_date else None,
                "last_observed_date": str(s.last_observed_date) if s.last_observed_date else None,
                "total_documents": s.total_documents_across_categories or 0,
            })

        return SummariesResponse(summaries=ns_list, total=total)


# ===== DASHBOARD INTELLIGENCE ENDPOINT =====

@app.get("/api/dashboard/intelligence")
@cache(ttl=600, prefix="dashboard_intel")
def get_dashboard_intelligence():
    """Get recent weekly/monthly event summaries for the dashboard intelligence section."""
    with get_session() as session:
        result = {"weekly": [], "monthly": []}

        for period_type, key in [(PeriodType.WEEKLY, "weekly"), (PeriodType.MONTHLY, "monthly")]:
            summaries = session.query(EventSummary).filter(
                EventSummary.period_type == period_type,
                EventSummary.is_deleted == False
            ).order_by(EventSummary.period_start.desc()).limit(10).all()

            for s in summaries:
                ns = s.narrative_summary or {}
                overview = ns.get("overview") or ns.get("monthly_overview") or ""
                result[key].append({
                    "id": str(s.id),
                    "event_name": s.event_name,
                    "country": s.initiating_country,
                    "period_start": str(s.period_start) if s.period_start else None,
                    "period_end": str(s.period_end) if s.period_end else None,
                    "overview": overview,
                    "material_score": float(s.material_score) if s.material_score else None,
                    "count_by_category": s.count_by_category or {},
                    "count_by_recipient": s.count_by_recipient or {},
                    "canonical_event_id": str(s.canonical_event_id) if s.canonical_event_id else None,
                })

        # Period-over-period comparison: count events by period
        from sqlalchemy import text as sql_text
        period_counts = session.execute(sql_text("""
            SELECT initiating_country, period_type::text,
                   COUNT(*) as event_count,
                   AVG(CASE WHEN material_score IS NOT NULL THEN material_score END) as avg_materiality
            FROM event_summaries
            WHERE is_deleted = false
            GROUP BY initiating_country, period_type
            ORDER BY initiating_country, period_type
        """)).fetchall()

        result["period_stats"] = [
            {
                "country": row.initiating_country,
                "period_type": row.period_type,
                "event_count": row.event_count,
                "avg_materiality": round(float(row.avg_materiality), 2) if row.avg_materiality else None,
            }
            for row in period_counts
        ]

        return result


# ===== CROSS-PERIOD EVENT VIEW =====

@app.get("/api/events/{event_id:uuid}/across-periods")
def get_event_across_periods(event_id: str):
    """Show how a single event's narrative evolves across daily/weekly/monthly/yearly summaries."""
    with get_session() as session:
        # Get the canonical event
        event = session.query(CanonicalEvent).filter(
            CanonicalEvent.id == event_id
        ).first()

        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        # Find all EventSummary records that reference this canonical event
        summaries = session.query(EventSummary).filter(
            EventSummary.canonical_event_id == event.id,
            EventSummary.is_deleted == False
        ).order_by(EventSummary.period_type, EventSummary.period_start.desc()).all()

        # Also search by event name for summaries that might not have canonical_event_id set
        name_summaries = session.query(EventSummary).filter(
            EventSummary.event_name == event.canonical_name,
            EventSummary.initiating_country == event.initiating_country,
            EventSummary.is_deleted == False,
            EventSummary.canonical_event_id.is_(None)
        ).order_by(EventSummary.period_type, EventSummary.period_start.desc()).all()

        # Combine and deduplicate
        seen_ids = set(str(s.id) for s in summaries)
        all_summaries = list(summaries)
        for s in name_summaries:
            if str(s.id) not in seen_ids:
                all_summaries.append(s)

        # Group by period type
        periods = {"daily": [], "weekly": [], "monthly": [], "yearly": []}
        for s in all_summaries:
            ns = s.narrative_summary or {}
            overview = ns.get("overview") or ns.get("monthly_overview") or ns.get("yearly_overview") or ""
            outcomes = ns.get("outcomes") or ns.get("key_outcomes") or ns.get("annual_outcomes") or ""
            progression = ns.get("progression") or ns.get("major_developments") or ""
            strategic = ns.get("strategic_significance") or ns.get("strategic_assessment") or ""

            entry = {
                "id": str(s.id),
                "period_start": str(s.period_start) if s.period_start else None,
                "period_end": str(s.period_end) if s.period_end else None,
                "overview": overview,
                "outcomes": outcomes,
                "progression": progression,
                "strategic": strategic,
                "material_score": float(s.material_score) if s.material_score else None,
                "count_by_category": s.count_by_category or {},
                "count_by_recipient": s.count_by_recipient or {},
                "source_link": ns.get("source_link"),
                "source_count": ns.get("source_count"),
                "citations": ns.get("citations", []),
            }
            period_key = s.period_type.value if s.period_type else "daily"
            if period_key in periods:
                periods[period_key].append(entry)

        return {
            "event_id": str(event.id),
            "event_name": event.canonical_name,
            "initiating_country": event.initiating_country,
            "story_phase": event.story_phase,
            "material_score": float(event.material_score) if event.material_score else None,
            "total_articles": event.total_articles,
            "first_mention_date": str(event.first_mention_date) if event.first_mention_date else None,
            "last_mention_date": str(event.last_mention_date) if event.last_mention_date else None,
            "periods": periods,
        }


# ===== COUNTRY COMPARISON =====

@app.get("/api/events/comparison")
@cache(ttl=600, prefix="event_comparison")
def get_event_comparison(
    limit: int = Query(20, ge=1, le=100)
):
    """Find events tracked across multiple countries for comparison."""
    with get_session() as session:
        from sqlalchemy import text as sql_text

        # Find event names that appear under multiple initiating countries
        rows = session.execute(sql_text("""
            SELECT event_name,
                   array_agg(DISTINCT initiating_country) as countries,
                   COUNT(DISTINCT initiating_country) as country_count,
                   MAX(period_start) as latest_date,
                   AVG(CASE WHEN material_score IS NOT NULL THEN material_score END) as avg_materiality
            FROM event_summaries
            WHERE is_deleted = false
              AND period_type = 'DAILY'
            GROUP BY event_name
            HAVING COUNT(DISTINCT initiating_country) >= 2
            ORDER BY country_count DESC, latest_date DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        comparisons = []
        for row in rows:
            # Get the narrative from each country
            country_narratives = {}
            for country in row.countries:
                summary = session.query(EventSummary).filter(
                    EventSummary.event_name == row.event_name,
                    EventSummary.initiating_country == country,
                    EventSummary.is_deleted == False
                ).order_by(EventSummary.period_start.desc()).first()

                if summary:
                    ns = summary.narrative_summary or {}
                    country_narratives[country] = {
                        "overview": ns.get("overview") or ns.get("monthly_overview") or "",
                        "outcomes": ns.get("outcomes") or ns.get("key_outcomes") or "",
                        "material_score": float(summary.material_score) if summary.material_score else None,
                        "count_by_category": summary.count_by_category or {},
                        "period_start": str(summary.period_start) if summary.period_start else None,
                    }

            comparisons.append({
                "event_name": row.event_name,
                "countries": row.countries,
                "country_count": row.country_count,
                "latest_date": str(row.latest_date) if row.latest_date else None,
                "avg_materiality": round(float(row.avg_materiality), 2) if row.avg_materiality else None,
                "country_narratives": country_narratives,
            })

        return {"comparisons": comparisons}


# ===== MATERIALITY HEATMAP =====

@app.get("/api/events/materiality-heatmap")
@cache(ttl=600, prefix="materiality_heatmap")
def get_materiality_heatmap():
    """Get materiality data for calendar heatmap visualization."""
    with get_session() as session:
        from sqlalchemy import text as sql_text

        # Get daily materiality by country
        rows = session.execute(sql_text("""
            SELECT initiating_country,
                   period_start as date,
                   COUNT(*) as event_count,
                   AVG(CASE WHEN material_score IS NOT NULL THEN material_score END) as avg_materiality,
                   MAX(material_score) as max_materiality,
                   SUM(total_documents_across_categories) as total_docs
            FROM event_summaries
            WHERE is_deleted = false
              AND period_type = 'DAILY'
              AND period_start >= CURRENT_DATE - INTERVAL '365 days'
            GROUP BY initiating_country, period_start
            ORDER BY initiating_country, period_start
        """)).fetchall()

        # Group by country
        heatmap = {}
        for row in rows:
            country = row.initiating_country
            if country not in heatmap:
                heatmap[country] = []
            heatmap[country].append({
                "date": str(row.date),
                "event_count": row.event_count,
                "avg_materiality": round(float(row.avg_materiality), 2) if row.avg_materiality else None,
                "max_materiality": round(float(row.max_materiality), 2) if row.max_materiality else None,
                "total_docs": row.total_docs or 0,
            })

        # Also get monthly aggregated data for the matrix view
        monthly_rows = session.execute(sql_text("""
            SELECT initiating_country,
                   TO_CHAR(period_start, 'YYYY-MM') as month,
                   COUNT(*) as event_count,
                   AVG(CASE WHEN material_score IS NOT NULL THEN material_score END) as avg_materiality,
                   SUM(total_documents_across_categories) as total_docs
            FROM event_summaries
            WHERE is_deleted = false
              AND period_type = 'MONTHLY'
            GROUP BY initiating_country, TO_CHAR(period_start, 'YYYY-MM')
            ORDER BY month, initiating_country
        """)).fetchall()

        monthly = []
        for row in monthly_rows:
            monthly.append({
                "country": row.initiating_country,
                "month": row.month,
                "event_count": row.event_count,
                "avg_materiality": round(float(row.avg_materiality), 2) if row.avg_materiality else None,
                "total_docs": row.total_docs or 0,
            })

        return {"daily_heatmap": heatmap, "monthly_matrix": monthly}


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
@cache(ttl=3600, prefix="filters")
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
    total_events: int
    total_entities: int
    avg_material_score: Optional[float]
    top_categories: list
    recent_activity_trend: list
    top_recipients: list
    source_breakdown: list

class RecentActivity(BaseModel):
    activities: list
    total: int

class InfluencerEventsResponse(BaseModel):
    events: list
    total: int

class InfluencerEntitiesResponse(BaseModel):
    entities: list
    total: int

class InfluencerBilateralSummariesResponse(BaseModel):
    summaries: list

@app.get("/api/influencer/{country}/overview", response_model=InfluencerOverview)
@cache(ttl=600, prefix="influencer_overview")
def get_influencer_overview(country: str):
    """Get overview statistics for a specific influencer country."""
    with get_session() as session:
        # Validate country is an influencer
        if country not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{country} is not a recognized influencer")

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

        # Total master events
        total_events = session.query(func.count(CanonicalEvent.id)).filter(
            CanonicalEvent.initiating_country == country,
            CanonicalEvent.master_event_id.is_(None)
        ).scalar() or 0

        # Total master entities
        total_entities = session.query(func.count(CanonicalEntity.id)).filter(
            CanonicalEntity.initiating_country == country,
            CanonicalEntity.master_entity_id.is_(None)
        ).scalar() or 0

        # Average material score
        from sqlalchemy import cast, Float as SQLFloat
        avg_material = session.query(func.avg(CanonicalEvent.material_score)).filter(
            CanonicalEvent.initiating_country == country,
            CanonicalEvent.master_event_id.is_(None),
            CanonicalEvent.material_score.isnot(None)
        ).scalar()
        avg_material_score = round(float(avg_material), 1) if avg_material else None

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
        ).group_by(Category.category).order_by(func.count(func.distinct(Category.doc_id)).desc()).limit(6).all()

        # Recent activity trend (last 12 weeks)
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
        ).group_by(func.date_trunc('week', Document.date)).order_by(func.date_trunc('week', Document.date).desc()).limit(12).all()

        # Top recipients for this influencer
        top_recipients = session.query(
            RecipientCountry.recipient_country,
            func.count(func.distinct(RecipientCountry.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == RecipientCountry.doc_id).filter(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country
        ).group_by(RecipientCountry.recipient_country).order_by(func.count(func.distinct(RecipientCountry.doc_id)).desc()).limit(10).all()

        # Source breakdown (top 10)
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
        ).group_by(Document.source_name).order_by(func.count(func.distinct(Document.doc_id)).desc()).limit(10).all()

        return InfluencerOverview(
            country=country,
            total_documents=total_docs,
            total_recipients=total_recipients,
            total_events=total_events,
            total_entities=total_entities,
            avg_material_score=avg_material_score,
            top_categories=[{"category": cat, "count": count} for cat, count in top_categories],
            recent_activity_trend=[{"week": str(week.date()) if week else None, "count": count} for week, count in reversed(activity_trend)],
            top_recipients=[{"country": recipient, "count": count} for recipient, count in top_recipients],
            source_breakdown=[{"source": src, "count": count} for src, count in source_breakdown]
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
def get_influencer_events(
    country: str,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="recency", pattern="^(recency|articles|materiality)$")
):
    """Get rich master event data for a specific influencer."""
    with get_session() as session:
        if country not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{country} is not a recognized influencer")

        # Base query for master events only
        base_query = session.query(CanonicalEvent).filter(
            CanonicalEvent.initiating_country == country,
            CanonicalEvent.master_event_id.is_(None)
        )

        # Total count
        total = base_query.count()

        # Sort
        if sort_by == "articles":
            base_query = base_query.order_by(CanonicalEvent.total_articles.desc())
        elif sort_by == "materiality":
            base_query = base_query.order_by(CanonicalEvent.material_score.desc().nullslast())
        else:
            base_query = base_query.order_by(CanonicalEvent.last_mention_date.desc())

        events = base_query.offset(offset).limit(limit).all()

        # Batch-load EventSummary narratives for these events
        event_names = [e.canonical_name for e in events if e.canonical_name]
        narratives = _get_narrative_for_events(session, event_names, country)

        event_list = []
        for event in events:
            narr = narratives.get(event.canonical_name, {})
            event_list.append({
                "id": str(event.id),
                "event_name": event.canonical_name,
                "description": narr.get("overview") or event.consolidated_description,
                "initiating_country": event.initiating_country,
                "first_mention_date": str(event.first_mention_date) if event.first_mention_date else None,
                "last_mention_date": str(event.last_mention_date) if event.last_mention_date else None,
                "total_articles": event.total_articles,
                "total_mention_days": event.total_mention_days,
                "story_phase": event.story_phase,
                "material_score": float(event.material_score) if event.material_score else None,
                "material_justification": event.material_justification,
                "peak_mention_date": str(event.peak_mention_date) if event.peak_mention_date else None,
                "peak_daily_article_count": event.peak_daily_article_count,
                "source_count": event.source_count,
                "primary_categories": event.primary_categories or {},
                "primary_recipients": event.primary_recipients or {},
                "narrative_overview": narr.get("overview"),
                "narrative_outcomes": narr.get("outcomes"),
                "source_link": narr.get("source_link"),
            })

        return InfluencerEventsResponse(events=event_list, total=total)


@app.get("/api/influencer/{country}/entities", response_model=InfluencerEntitiesResponse)
def get_influencer_entities(
    country: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    entity_type: Optional[str] = Query(default=None),
    sort_by: str = Query(default="documents", pattern="^(documents|recency)$")
):
    """Get key actors and entities associated with an influencer country."""
    with get_session() as session:
        if country not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{country} is not a recognized influencer")

        # Master entities only
        base_query = session.query(CanonicalEntity).filter(
            CanonicalEntity.initiating_country == country,
            CanonicalEntity.master_entity_id.is_(None)
        )

        # Filter by entity type
        if entity_type:
            base_query = base_query.filter(CanonicalEntity.entity_type == entity_type)

        total = base_query.count()

        # Sort
        if sort_by == "recency":
            base_query = base_query.order_by(CanonicalEntity.last_mention_date.desc())
        else:
            base_query = base_query.order_by(CanonicalEntity.total_documents.desc())

        entities = base_query.offset(offset).limit(limit).all()

        entity_list = []
        for entity in entities:
            entity_list.append({
                "id": str(entity.id),
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type.value if entity.entity_type else None,
                "primary_role": entity.primary_role.value if entity.primary_role else None,
                "entity_description": entity.entity_description,
                "total_documents": entity.total_documents,
                "total_mention_days": entity.total_mention_days,
                "first_mention_date": str(entity.first_mention_date) if entity.first_mention_date else None,
                "last_mention_date": str(entity.last_mention_date) if entity.last_mention_date else None,
                "primary_categories": entity.primary_categories or {},
                "primary_recipients": entity.primary_recipients or {},
            })

        return InfluencerEntitiesResponse(entities=entity_list, total=total)


@app.get("/api/influencer/{country}/bilateral-summaries", response_model=InfluencerBilateralSummariesResponse)
def get_influencer_bilateral_summaries(country: str):
    """Get bilateral relationship summaries for all recipients of an influencer."""
    with get_session() as session:
        if country not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{country} is not a recognized influencer")

        summaries = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.initiating_country == country
        ).order_by(BilateralRelationshipSummary.total_documents.desc()).all()

        summary_list = []
        for s in summaries:
            rel_summary = s.relationship_summary or {}
            summary_list.append({
                "recipient_country": s.recipient_country,
                "total_documents": s.total_documents,
                "total_daily_events": s.total_daily_events,
                "first_interaction_date": str(s.first_interaction_date) if s.first_interaction_date else None,
                "last_interaction_date": str(s.last_interaction_date) if s.last_interaction_date else None,
                "count_by_category": s.count_by_category or {},
                "overview": rel_summary.get("overview", ""),
                "key_themes": rel_summary.get("key_themes", []),
                "current_status": rel_summary.get("current_status", ""),
                "material_score_avg": float(s.material_score_avg) if hasattr(s, 'material_score_avg') and s.material_score_avg else None,
            })

        return InfluencerBilateralSummariesResponse(summaries=summary_list)


class InfluencerCategorySummariesResponse(BaseModel):
    summaries: list

class InfluencerSourcesResponse(BaseModel):
    sources: list
    total_sources: int
    top_geofocus: list
    top_medium: list

class InfluencerTimelineResponse(BaseModel):
    items: list
    total: int


@app.get("/api/influencer/{country}/category-summaries", response_model=InfluencerCategorySummariesResponse)
def get_influencer_category_summaries(country: str):
    """Get category strategy summaries for an influencer country."""
    with get_session() as session:
        if country not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{country} is not a recognized influencer")

        summaries = session.query(CountryCategorySummary).filter(
            CountryCategorySummary.initiating_country == country
        ).order_by(CountryCategorySummary.total_documents.desc()).all()

        summary_list = []
        for s in summaries:
            cat_summary = s.category_summary or {}
            summary_list.append({
                "category": s.category,
                "total_documents": s.total_documents,
                "total_daily_events": s.total_daily_events,
                "count_by_recipient": s.count_by_recipient or {},
                "count_by_subcategory": s.count_by_subcategory or {},
                "activity_by_month": s.activity_by_month or {},
                "overview": cat_summary.get("overview", ""),
                "key_strategies": cat_summary.get("key_strategies", []),
                "trend_analysis": cat_summary.get("trend_analysis", ""),
                "top_recipients": cat_summary.get("top_recipients", []),
                "major_initiatives": cat_summary.get("major_initiatives", []),
                "material_score_avg": float(s.material_score_avg) if s.material_score_avg else None,
            })

        return InfluencerCategorySummariesResponse(summaries=summary_list)


@app.get("/api/influencer/{country}/sources", response_model=InfluencerSourcesResponse)
def get_influencer_sources(country: str, limit: int = Query(default=25, ge=1, le=100)):
    """Get detailed source intelligence for an influencer country."""
    with get_session() as session:
        if country not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{country} is not a recognized influencer")

        # Base filter for this influencer
        base_filter = [
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(RECIPIENTS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
        ]

        # Top sources with document count
        sources = session.query(
            Document.source_name,
            func.count(func.distinct(Document.doc_id)).label('doc_count'),
            func.min(Document.date).label('first_date'),
            func.max(Document.date).label('last_date')
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            *base_filter,
            Document.source_name.isnot(None)
        ).group_by(Document.source_name).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).limit(limit).all()

        # Total unique sources
        total_sources = session.query(
            func.count(func.distinct(Document.source_name))
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(*base_filter, Document.source_name.isnot(None)).scalar() or 0

        # Geofocus distribution
        geofocus = session.query(
            Document.source_geofocus,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            *base_filter,
            Document.source_geofocus.isnot(None)
        ).group_by(Document.source_geofocus).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).limit(15).all()

        # Medium distribution
        medium = session.query(
            Document.source_medium,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            *base_filter,
            Document.source_medium.isnot(None)
        ).group_by(Document.source_medium).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).limit(10).all()

        return InfluencerSourcesResponse(
            sources=[{
                "source_name": s.source_name,
                "doc_count": s.doc_count,
                "first_date": str(s.first_date) if s.first_date else None,
                "last_date": str(s.last_date) if s.last_date else None,
            } for s in sources],
            total_sources=total_sources,
            top_geofocus=[{"geofocus": g.source_geofocus, "count": g.count} for g in geofocus],
            top_medium=[{"medium": m.source_medium, "count": m.count} for m in medium],
        )


@app.get("/api/influencer/{country}/timeline", response_model=InfluencerTimelineResponse)
def get_influencer_timeline(
    country: str,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    """Get a unified activity timeline combining event mentions and key documents."""
    with get_session() as session:
        if country not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{country} is not a recognized influencer")

        # Get daily event mentions with their canonical event names
        mentions = session.query(
            DailyEventMention.mention_date,
            DailyEventMention.consolidated_headline,
            DailyEventMention.daily_summary,
            DailyEventMention.article_count,
            DailyEventMention.news_intensity,
            DailyEventMention.mention_context,
            DailyEventMention.source_names,
            CanonicalEvent.canonical_name,
            CanonicalEvent.story_phase,
            CanonicalEvent.material_score,
            CanonicalEvent.primary_categories,
            CanonicalEvent.primary_recipients,
        ).join(
            CanonicalEvent,
            DailyEventMention.canonical_event_id == CanonicalEvent.id
        ).filter(
            DailyEventMention.initiating_country == country,
            CanonicalEvent.master_event_id.is_(None)  # Only master events
        ).order_by(
            DailyEventMention.mention_date.desc()
        )

        total = mentions.count()
        results = mentions.offset(offset).limit(limit).all()

        # Batch-load daily EventSummary narratives for these timeline items
        event_names = list(set(m.canonical_name for m in results if m.canonical_name))
        narratives = _get_narrative_for_events(session, event_names, country)

        items = []
        for m in results:
            top_cats = []
            if m.primary_categories:
                top_cats = sorted(m.primary_categories.items(), key=lambda x: x[1], reverse=True)[:2]
                top_cats = [c[0] for c in top_cats]

            top_recs = []
            if m.primary_recipients:
                top_recs = sorted(m.primary_recipients.items(), key=lambda x: x[1], reverse=True)[:2]
                top_recs = [r[0] for r in top_recs]

            narr = narratives.get(m.canonical_name, {})
            # Prefer EventSummary narrative over raw daily_summary
            summary_text = narr.get("overview") or m.daily_summary

            items.append({
                "date": str(m.mention_date) if m.mention_date else None,
                "event_name": m.canonical_name,
                "headline": m.consolidated_headline,
                "summary": summary_text,
                "article_count": m.article_count,
                "news_intensity": m.news_intensity,
                "mention_context": m.mention_context,
                "story_phase": m.story_phase,
                "material_score": float(m.material_score) if m.material_score else None,
                "source_count": len(m.source_names) if m.source_names else 0,
                "categories": top_cats,
                "recipients": top_recs,
                "source_link": narr.get("source_link"),
            })

        return InfluencerTimelineResponse(items=items, total=total)


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
@cache(ttl=600, prefix="metrics_overall")
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
@cache(ttl=600, prefix="metrics_influencer")
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
@cache(ttl=600, prefix="metrics_bilateral")
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
@cache(ttl=600, prefix="metrics_recipient")
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

# --- Pydantic models for bilateral page ---

class BilateralEnhancedOverviewResponse(BaseModel):
    influencer: str
    recipient: str
    total_documents: int
    total_events: int
    total_entities: int
    avg_material_score: Optional[float]
    first_interaction_date: Optional[str]
    last_interaction_date: Optional[str]
    weekly_average: float
    top_categories: list
    activity_trend: list
    source_breakdown: list

class BilateralRelationshipProfileResponse(BaseModel):
    overview: str
    key_themes: list
    major_initiatives: list
    trend_analysis: str
    current_status: str
    notable_developments: list
    material_assessment: Optional[dict]
    count_by_category: dict
    count_by_subcategory: dict
    activity_by_month: dict
    material_score_histogram: Optional[dict]
    material_score_avg: Optional[float]
    material_score_median: Optional[float]

class BilateralCategorySummariesResponse(BaseModel):
    summaries: list

class BilateralEventsResponse(BaseModel):
    events: list
    total: int

class BilateralEntitiesResponse(BaseModel):
    entities: list
    total: int

class BilateralSourcesResponse(BaseModel):
    sources: list
    total_sources: int


# --- Bilateral sub-endpoints (must be before the catch-all /{influencer}/{recipient}) ---

@app.get("/api/bilateral/{influencer}/{recipient}/enhanced-overview", response_model=BilateralEnhancedOverviewResponse)
@cache(ttl=600, prefix="bilateral_overview")
def get_bilateral_enhanced_overview(influencer: str, recipient: str):
    """Enhanced overview with richer KPIs for bilateral page."""
    with get_session() as session:
        if influencer not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{influencer} is not a recognized influencer")
        if recipient not in RECIPIENTS:
            raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

        # Total documents
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).scalar() or 0

        # Get bilateral doc IDs for event/entity queries
        bilateral_doc_ids = [row[0] for row in session.query(Document.doc_id).join(
            InitiatingCountry
        ).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).all()]

        # Total events relevant to this bilateral pair
        total_events = 0
        if bilateral_doc_ids:
            total_events = session.query(func.count(func.distinct(CanonicalEvent.id))).join(
                DailyEventMention, DailyEventMention.canonical_event_id == CanonicalEvent.id
            ).filter(
                DailyEventMention.doc_ids.op('&&')(bilateral_doc_ids),
                CanonicalEvent.master_event_id.is_(None)
            ).scalar() or 0

        # Total entities (those whose primary_recipients include this recipient)
        total_entities = session.query(func.count(CanonicalEntity.id)).filter(
            CanonicalEntity.initiating_country == influencer,
            CanonicalEntity.master_entity_id.is_(None),
            func.cast(CanonicalEntity.primary_recipients, Text).contains(recipient)
        ).scalar() or 0

        # Avg material score from BilateralRelationshipSummary
        bilat_summary = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.initiating_country == influencer,
            BilateralRelationshipSummary.recipient_country == recipient
        ).first()

        avg_material = float(bilat_summary.material_score_avg) if bilat_summary and bilat_summary.material_score_avg else None
        first_date = str(bilat_summary.first_interaction_date) if bilat_summary and bilat_summary.first_interaction_date else None
        last_date = str(bilat_summary.last_interaction_date) if bilat_summary and bilat_summary.last_interaction_date else None

        # Top categories
        top_categories = session.query(
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(InitiatingCountry, InitiatingCountry.doc_id == Category.doc_id).join(
            RecipientCountry, RecipientCountry.doc_id == Category.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).group_by(Category.category).order_by(func.count(func.distinct(Category.doc_id)).desc()).limit(10).all()

        # Activity trend (last 12 weeks)
        activity_trend = session.query(
            func.date_trunc('week', Document.date).label('week'),
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.date.isnot(None)
        ).group_by(func.date_trunc('week', Document.date)).order_by(
            func.date_trunc('week', Document.date).desc()
        ).limit(12).all()

        weekly_avg = sum(c for _, c in activity_trend) / max(len(activity_trend), 1)

        # Source breakdown (top 15)
        source_breakdown = session.query(
            Document.source_name,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.source_name.isnot(None)
        ).group_by(Document.source_name).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).limit(15).all()

        return BilateralEnhancedOverviewResponse(
            influencer=influencer,
            recipient=recipient,
            total_documents=total_docs,
            total_events=total_events,
            total_entities=total_entities,
            avg_material_score=avg_material,
            first_interaction_date=first_date,
            last_interaction_date=last_date,
            weekly_average=round(weekly_avg, 1),
            top_categories=[{"category": cat, "count": count} for cat, count in top_categories],
            activity_trend=[{"week": str(week.date()) if week else None, "count": count} for week, count in reversed(activity_trend)],
            source_breakdown=[{"source": source, "count": count} for source, count in source_breakdown],
        )


@app.get("/api/bilateral/{influencer}/{recipient}/relationship-profile", response_model=BilateralRelationshipProfileResponse)
@cache(ttl=900, prefix="bilateral_profile")
def get_bilateral_relationship_profile(influencer: str, recipient: str):
    """Get AI-generated relationship profile from BilateralRelationshipSummary."""
    with get_session() as session:
        if influencer not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{influencer} is not a recognized influencer")
        if recipient not in RECIPIENTS:
            raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

        summary = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.initiating_country == influencer,
            BilateralRelationshipSummary.recipient_country == recipient
        ).first()

        if not summary:
            raise HTTPException(status_code=404, detail=f"No relationship summary found for {influencer} → {recipient}")

        rel = summary.relationship_summary or {}

        return BilateralRelationshipProfileResponse(
            overview=rel.get("overview", ""),
            key_themes=rel.get("key_themes", []),
            major_initiatives=rel.get("major_initiatives", []),
            trend_analysis=rel.get("trend_analysis", ""),
            current_status=rel.get("current_status", ""),
            notable_developments=rel.get("notable_developments", []),
            material_assessment=rel.get("material_assessment"),
            count_by_category=summary.count_by_category or {},
            count_by_subcategory=summary.count_by_subcategory or {},
            activity_by_month=summary.activity_by_month or {},
            material_score_histogram=summary.material_score_histogram,
            material_score_avg=float(summary.material_score_avg) if summary.material_score_avg else None,
            material_score_median=float(summary.material_score_median) if summary.material_score_median else None,
        )


@app.get("/api/bilateral/{influencer}/{recipient}/category-summaries", response_model=BilateralCategorySummariesResponse)
def get_bilateral_category_summaries(influencer: str, recipient: str):
    """Get per-category deep-dive analysis for this bilateral pair."""
    from shared.models.models import BilateralCategorySummary as BCS
    with get_session() as session:
        if influencer not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{influencer} is not a recognized influencer")
        if recipient not in RECIPIENTS:
            raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

        summaries = session.query(BCS).filter(
            BCS.initiating_country == influencer,
            BCS.recipient_country == recipient
        ).order_by(BCS.total_documents.desc()).all()

        summary_list = []
        for s in summaries:
            cat_summary = s.category_summary or {}
            summary_list.append({
                "category": s.category,
                "total_documents": s.total_documents,
                "total_daily_events": s.total_daily_events,
                "first_interaction_date": str(s.first_interaction_date) if s.first_interaction_date else None,
                "last_interaction_date": str(s.last_interaction_date) if s.last_interaction_date else None,
                "count_by_subcategory": s.count_by_subcategory or {},
                "count_by_source": s.count_by_source or {},
                "activity_by_month": s.activity_by_month or {},
                "overview": cat_summary.get("overview", ""),
                "key_focus_areas": cat_summary.get("key_focus_areas", []),
                "major_initiatives": cat_summary.get("major_initiatives", []),
                "interaction_patterns": cat_summary.get("interaction_patterns", ""),
                "trend_analysis": cat_summary.get("trend_analysis", ""),
                "impact_assessment": cat_summary.get("impact_assessment", ""),
                "material_assessment": cat_summary.get("material_assessment"),
                "material_score_avg": float(s.material_score_avg) if s.material_score_avg else None,
            })

        return BilateralCategorySummariesResponse(summaries=summary_list)


@app.get("/api/bilateral/{influencer}/{recipient}/events", response_model=BilateralEventsResponse)
def get_bilateral_events(
    influencer: str,
    recipient: str,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="recency", pattern="^(recency|articles|materiality)$")
):
    """Get rich event data relevant to this bilateral pair."""
    with get_session() as session:
        if influencer not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{influencer} is not a recognized influencer")
        if recipient not in RECIPIENTS:
            raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

        # Get bilateral doc IDs
        bilateral_doc_ids = [row[0] for row in session.query(Document.doc_id).join(
            InitiatingCountry
        ).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient
        ).all()]

        if not bilateral_doc_ids:
            return BilateralEventsResponse(events=[], total=0)

        # Get master event IDs that have mentions in bilateral docs
        event_ids_subq = session.query(func.distinct(CanonicalEvent.id)).join(
            DailyEventMention, DailyEventMention.canonical_event_id == CanonicalEvent.id
        ).filter(
            DailyEventMention.doc_ids.op('&&')(bilateral_doc_ids),
            CanonicalEvent.master_event_id.is_(None)
        ).subquery()

        base_query = session.query(CanonicalEvent).filter(
            CanonicalEvent.id.in_(session.query(event_ids_subq))
        )

        total = base_query.count()

        # Sort
        if sort_by == "articles":
            base_query = base_query.order_by(CanonicalEvent.total_articles.desc())
        elif sort_by == "materiality":
            base_query = base_query.order_by(CanonicalEvent.material_score.desc().nullslast())
        else:
            base_query = base_query.order_by(CanonicalEvent.last_mention_date.desc())

        events = base_query.offset(offset).limit(limit).all()

        # Batch-load EventSummary narratives for these events
        event_names = [e.canonical_name for e in events if e.canonical_name]
        narratives = _get_narrative_for_events(session, event_names, influencer)

        event_list = []
        for event in events:
            narr = narratives.get(event.canonical_name, {})
            event_list.append({
                "id": str(event.id),
                "event_name": event.canonical_name,
                "description": narr.get("overview") or event.consolidated_description,
                "initiating_country": event.initiating_country,
                "first_mention_date": str(event.first_mention_date) if event.first_mention_date else None,
                "last_mention_date": str(event.last_mention_date) if event.last_mention_date else None,
                "total_articles": event.total_articles,
                "total_mention_days": event.total_mention_days,
                "story_phase": event.story_phase,
                "material_score": float(event.material_score) if event.material_score else None,
                "material_justification": event.material_justification,
                "peak_mention_date": str(event.peak_mention_date) if event.peak_mention_date else None,
                "peak_daily_article_count": event.peak_daily_article_count,
                "source_count": event.source_count,
                "primary_categories": event.primary_categories or {},
                "primary_recipients": event.primary_recipients or {},
                "narrative_overview": narr.get("overview"),
                "narrative_outcomes": narr.get("outcomes"),
                "source_link": narr.get("source_link"),
            })

        return BilateralEventsResponse(events=event_list, total=total)


@app.get("/api/bilateral/{influencer}/{recipient}/entities", response_model=BilateralEntitiesResponse)
def get_bilateral_entities(
    influencer: str,
    recipient: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    entity_type: Optional[str] = Query(default=None),
    sort_by: str = Query(default="documents", pattern="^(documents|recency)$")
):
    """Get key actors/entities relevant to this bilateral pair."""
    with get_session() as session:
        if influencer not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{influencer} is not a recognized influencer")
        if recipient not in RECIPIENTS:
            raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

        # Filter entities for this influencer whose primary_recipients includes this recipient
        base_query = session.query(CanonicalEntity).filter(
            CanonicalEntity.initiating_country == influencer,
            CanonicalEntity.master_entity_id.is_(None),
            func.cast(CanonicalEntity.primary_recipients, Text).contains(recipient)
        )

        if entity_type:
            base_query = base_query.filter(CanonicalEntity.entity_type == entity_type)

        total = base_query.count()

        if sort_by == "recency":
            base_query = base_query.order_by(CanonicalEntity.last_mention_date.desc())
        else:
            base_query = base_query.order_by(CanonicalEntity.total_documents.desc())

        entities = base_query.offset(offset).limit(limit).all()

        entity_list = []
        for entity in entities:
            entity_list.append({
                "id": str(entity.id),
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type.value if entity.entity_type else None,
                "primary_role": entity.primary_role.value if entity.primary_role else None,
                "entity_description": entity.entity_description,
                "total_documents": entity.total_documents,
                "total_mention_days": entity.total_mention_days,
                "first_mention_date": str(entity.first_mention_date) if entity.first_mention_date else None,
                "last_mention_date": str(entity.last_mention_date) if entity.last_mention_date else None,
                "primary_categories": entity.primary_categories or {},
                "primary_recipients": entity.primary_recipients or {},
            })

        return BilateralEntitiesResponse(entities=entity_list, total=total)


@app.get("/api/bilateral/{influencer}/{recipient}/sources", response_model=BilateralSourcesResponse)
def get_bilateral_sources(influencer: str, recipient: str):
    """Get source intelligence for this bilateral pair."""
    with get_session() as session:
        if influencer not in INFLUENCERS:
            raise HTTPException(status_code=404, detail=f"{influencer} is not a recognized influencer")
        if recipient not in RECIPIENTS:
            raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

        sources = session.query(
            Document.source_name,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            InitiatingCountry.initiating_country == influencer,
            RecipientCountry.recipient_country == recipient,
            Document.source_name.isnot(None)
        ).group_by(Document.source_name).order_by(
            func.count(func.distinct(Document.doc_id)).desc()
        ).all()

        return BilateralSourcesResponse(
            sources=[{"source": name, "count": count} for name, count in sources],
            total_sources=len(sources),
        )


# --- Legacy bilateral overview (keep for backward compatibility) ---

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
    quarterly: bool = False
    # Section toggles (all default true)
    include_events: bool = True
    include_entities: bool = True
    include_metrics: bool = True
    include_persons: bool = True

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
        model=request.model,
        quarterly=request.quarterly,
        include_events=request.include_events,
        include_entities=request.include_entities,
        include_metrics=request.include_metrics,
        include_persons=request.include_persons,
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
                model=request.model,
                quarterly=request.quarterly,
                include_events=request.include_events,
                include_entities=request.include_entities,
                include_metrics=request.include_metrics,
                include_persons=request.include_persons,
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


@app.post("/api/report/export/reviewer")
def export_reviewer_endpoint(report_data: dict):
    """Export a reviewer validation copy with inline source links."""
    from server.report_exporter import export_reviewer_to_docx

    docx_bytes = export_reviewer_to_docx(report_data)

    country = report_data.get('country', 'Report')
    period_start = report_data.get('period_start', '')
    filename = f"{country}_Report_{period_start}_reviewer.docx"

    return StreamingResponse(
        docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.post("/api/report/validate/stream")
async def validate_report_stream_endpoint(request: Request):
    """
    SSE streaming validation of a completed report.
    Validates that LLM-generated narratives are properly supported by cited sources.

    Yields Server-Sent Events:
    - validation_start: {total_sections: int}
    - section_validated: {section_id, status, claims_validated, uncited_claims, issues, summary}
    - validation_complete: {overall_status, validated_at}
    """
    import json
    from server.report_validator import validate_report_stream

    body = await request.json()
    report = body.get("report", {})
    model = body.get("model", "gpt-4o-mini")

    def event_generator():
        try:
            for event in validate_report_stream(report, model):
                event_type = event.get("type", "unknown")
                payload = json.dumps(event.get("payload", {}))
                yield f"event: {event_type}\ndata: {payload}\n\n"
        except GeneratorExit:
            print("[Validation SSE] Client disconnected")
        except Exception as e:
            error_payload = json.dumps({"error": str(e)})
            yield f"event: error\ndata: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
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

@app.post("/proxy_query")
@app.post("/material_query")  # backward-compat alias
def proxy_gai_query(input: QueryInput):
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
        # gpt-5 family only supports temperature=1; use 0.4 for older models
        extra_params = {}
        if not input.model.startswith("gpt-5"):
            extra_params["temperature"] = 0.4
        completion = client.chat.completions.create(
            model=input.model,
            messages=[
                {"role": "system", "content": input.sys_prompt},
                {"role": "user", "content": input.prompt},
            ],
            **extra_params,
        )
        content = completion.choices[0].message.content
        try:
            return {"response": json.loads(content)}
        except json.JSONDecodeError:
            return {"response": content}


class StreamQueryInput(BaseModel):
    model: str = "gpt-4o-mini"
    sys_prompt: str
    prompt: str
    temperature: float = 0.4
    max_tokens: int = 4000


@app.post("/proxy_query_stream")
def proxy_gai_query_stream(input: StreamQueryInput):
    """
    Streaming LLM query endpoint. Same routing logic as /proxy_query
    but returns Server-Sent Events for real-time streaming.
    """
    from openai import AzureOpenAI as _AzureOpenAI, OpenAI as _OpenAI

    messages = [
        {"role": "system", "content": input.sys_prompt},
        {"role": "user", "content": input.prompt},
    ]

    def _get_stream():
        # LiteLLM
        litellm_url = os.getenv('LITELLM_URL', '').strip()
        litellm_key = os.getenv('LITELLM_API_KEY', '').strip()
        litellm_model = os.getenv('LITELLM_MODEL', input.model).strip()

        if litellm_url and litellm_key:
            client = _OpenAI(base_url=litellm_url, api_key=litellm_key)
            return client.chat.completions.create(
                model=litellm_model, messages=messages, stream=True,
                temperature=input.temperature, max_tokens=input.max_tokens
            )

        env = os.getenv('ENV', 'development').lower()

        # Azure (production)
        if env == 'production':
            azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '').strip()
            azure_key = os.getenv('AZURE_OPENAI_API_KEY', '').strip()
            if azure_endpoint and azure_key:
                client = _AzureOpenAI(
                    azure_endpoint=azure_endpoint, api_key=azure_key,
                    api_version="2024-08-01-preview"
                )
                deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', input.model)
                return client.chat.completions.create(
                    model=deployment, messages=messages, stream=True,
                    temperature=input.temperature, max_tokens=input.max_tokens
                )

        # OpenAI (fallback)
        api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="No OpenAI API key configured")

        client = _OpenAI(api_key=api_key)
        extra_params = {}
        if not input.model.startswith("gpt-5"):
            extra_params["temperature"] = input.temperature
        return client.chat.completions.create(
            model=input.model, messages=messages, stream=True,
            max_tokens=input.max_tokens, **extra_params
        )

    def event_generator():
        try:
            stream = _get_stream()
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'content': content})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ----- OpenAI Batch API Proxy -----

@app.post("/batch/upload_file")
async def upload_batch_file(file: UploadFile = File(...)):
    """Proxy endpoint to upload JSONL file to OpenAI for batch processing."""
    from openai import OpenAI, APIError, AuthenticationError, RateLimitError, APIConnectionError
    import httpx

    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    content = await file.read()
    file_size_mb = len(content) / (1024 * 1024)
    print(f"[BATCH UPLOAD] Received file: {file.filename}, size: {file_size_mb:.2f} MB")

    if file_size_mb > 100:
        raise HTTPException(status_code=413, detail=f"File too large: {file_size_mb:.2f} MB (max 100 MB)")

    # Validate JSONL content
    line_count = content.count(b'\n')
    if line_count == 0:
        raise HTTPException(status_code=400, detail="File appears empty or not valid JSONL")
    print(f"[BATCH UPLOAD] JSONL lines: ~{line_count}")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.jsonl', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        client = OpenAI(api_key=api_key, timeout=httpx.Timeout(600.0, connect=60.0), max_retries=2)
        with open(tmp_path, 'rb') as f:
            batch_file = client.files.create(file=f, purpose="batch")

        print(f"[BATCH UPLOAD] Success: file_id={batch_file.id}")
        return {
            "file_id": batch_file.id,
            "filename": batch_file.filename,
            "bytes": batch_file.bytes,
            "created_at": batch_file.created_at,
            "status": batch_file.status
        }

    except AuthenticationError as e:
        print(f"[BATCH UPLOAD] Authentication failed: {e}")
        raise HTTPException(status_code=401, detail=f"OpenAI authentication failed: {str(e)}")
    except RateLimitError as e:
        print(f"[BATCH UPLOAD] Rate limit hit: {e}")
        raise HTTPException(status_code=429, detail=f"OpenAI rate limit exceeded: {str(e)}")
    except APIConnectionError as e:
        print(f"[BATCH UPLOAD] Connection error: {e}")
        raise HTTPException(status_code=502, detail=f"Cannot connect to OpenAI API: {str(e)}")
    except APIError as e:
        print(f"[BATCH UPLOAD] OpenAI API error (status={e.status_code}): {e.message}")
        raise HTTPException(status_code=e.status_code or 500, detail=f"OpenAI API error: {e.message}")
    except Exception as e:
        print(f"[BATCH UPLOAD] Unexpected error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"File upload failed: {type(e).__name__}: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

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

@app.post("/batch/cancel")
async def cancel_batch(request: BatchStatusRequest):
    """Cancel an in-progress batch job on OpenAI."""
    from openai import OpenAI
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")

    try:
        client = OpenAI(api_key=api_key)
        batch = client.batches.cancel(request.batch_id)
        return {
            "batch_id": batch.id,
            "status": batch.status,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch cancel failed: {str(e)}")


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

    # Get RAG config values
    rag_config = CONFIG.get('rag', {})
    chat_doc_limit = rag_config.get('chat_document_limit', 50)

    # Perform intelligent semantic search with automatic filter inference and entity boost
    sources, search_metadata = intelligent_search(
        query=request.message,
        k=chat_doc_limit,
        influencer=request.influencer,
        recipient=request.recipient,
        category=request.category,
        start_date=request.start_date,
        end_date=request.end_date,
        apply_intelligence=True,
        enable_entity_boost=True
    )

    # Get layered context from search metadata
    matched_entities = search_metadata.get("_matched_entities_full", [])
    strategic_context = search_metadata.get("_strategic_context")
    event_context = search_metadata.get("_event_context")

    # Generate response with layered context injection
    response_text = generate_response(
        request.message, sources,
        matched_entities=matched_entities,
        strategic_context=strategic_context,
        event_context=event_context,
    )

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

    # Get RAG config values
    rag_config = CONFIG.get('rag', {})
    chat_doc_limit = rag_config.get('chat_document_limit', 50)

    # Perform intelligent semantic search with automatic filter inference and entity boost
    sources, search_metadata = intelligent_search(
        query=request.message,
        k=chat_doc_limit,
        influencer=request.influencer,
        recipient=request.recipient,
        category=request.category,
        start_date=request.start_date,
        end_date=request.end_date,
        apply_intelligence=True,
        enable_entity_boost=True
    )

    # Get layered context from search metadata
    matched_entities = search_metadata.get("_matched_entities_full", [])
    strategic_context = search_metadata.get("_strategic_context")
    event_context = search_metadata.get("_event_context")

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

        # Then stream the response with layered context injection
        for chunk in generate_response_stream(
            request.message, sources,
            matched_entities=matched_entities,
            strategic_context=strategic_context,
            event_context=event_context,
        ):
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

@app.get("/api/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """
    Return the current user's info based on the enterprise JWT.

    The get_current_user dependency handles JWT validation and auto-provisioning,
    so this endpoint simply returns the result.
    """
    return {
        "id": current_user["user_id"],
        "username": current_user["username"],
        "role": current_user["role"],
        "display_name": current_user["display_name"],
    }


# ===== ADMIN USER MANAGEMENT ENDPOINTS =====

@app.get("/api/admin/users")
def list_users(current_user: dict = Depends(require_admin)):
    """List all users (admin only)."""
    with get_session() as session:
        users = session.query(User).filter(User.is_deleted == False).all()
        return {"users": [u.to_dict() for u in users]}

@app.put("/api/admin/users/{user_id}")
def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: dict = Depends(require_admin)
):
    """Update a user's role or status (admin only)."""
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

        user.updated_at = datetime.now(timezone.utc)
        session.commit()

        return {"message": "User updated", "user": user.to_dict()}

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
        user.deleted_at = datetime.now(timezone.utc)
        session.commit()

        return {"message": "User deleted"}


# ----- Chart Drilldown Endpoint -----

class DrilldownQueryContext(BaseModel):
    initiating_country: Optional[str] = None
    recipient_country: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    page_source: Optional[str] = None

class DrilldownChartSelection(BaseModel):
    dimension: str  # category, subcategory, recipient_country, initiating_country, month, source
    value: str
    chart_type: Optional[str] = None

class DrilldownRequest(BaseModel):
    query_context: DrilldownQueryContext
    chart_selection: DrilldownChartSelection
    include_narrative: Optional[bool] = True

@app.post("/api/drilldown")
def chart_drilldown(request: DrilldownRequest):
    """
    On-demand drilldown for chart click interactions.
    Returns SQL-computed metrics (always accurate, no context limits)
    plus an optional LLM narrative from a representative sample.
    """
    from sqlalchemy import text as sql_text

    ctx = request.query_context
    sel = request.chart_selection

    with get_session() as session:
        # ── Build filter conditions ──
        conditions = []
        params: dict = {}

        # Always restrict to known influencers/recipients
        conditions.append("ic.initiating_country = ANY(:influencers)")
        params["influencers"] = INFLUENCERS
        conditions.append("rc.recipient_country = ANY(:recipients)")
        params["recipients"] = RECIPIENTS
        conditions.append("ic.initiating_country != rc.recipient_country")

        # Original query context filters
        if ctx.initiating_country and ctx.initiating_country != 'ALL':
            conditions.append("ic.initiating_country = :ctx_init")
            params["ctx_init"] = ctx.initiating_country
        if ctx.recipient_country and ctx.recipient_country != 'ALL':
            conditions.append("rc.recipient_country = :ctx_recip")
            params["ctx_recip"] = ctx.recipient_country
        if ctx.category and ctx.category != 'ALL':
            conditions.append("cat.category = :ctx_cat")
            params["ctx_cat"] = ctx.category
        if ctx.subcategory and ctx.subcategory != 'ALL':
            conditions.append("sub.subcategory = :ctx_subcat")
            params["ctx_subcat"] = ctx.subcategory
        if ctx.start_date:
            conditions.append("d.date >= :ctx_start")
            params["ctx_start"] = ctx.start_date
        if ctx.end_date:
            conditions.append("d.date <= :ctx_end")
            params["ctx_end"] = ctx.end_date

        # Chart selection filter (the clicked dimension)
        dim_map = {
            "category": ("cat.category", "sel_val"),
            "subcategory": ("sub.subcategory", "sel_val"),
            "recipient_country": ("rc.recipient_country", "sel_val"),
            "initiating_country": ("ic.initiating_country", "sel_val"),
            "source": ("d.source_name", "sel_val"),
        }

        need_cat_join = ctx.category or sel.dimension == "category"
        need_sub_join = ctx.subcategory or sel.dimension == "subcategory"

        if sel.dimension == "month":
            # Month selection: filter to that month
            conditions.append("to_char(d.date, 'YYYY-MM') = :sel_val")
            params["sel_val"] = sel.value
        elif sel.dimension in dim_map:
            col, param = dim_map[sel.dimension]
            conditions.append(f"{col} = :{param}")
            params[param] = sel.value
        else:
            raise HTTPException(status_code=400, detail=f"Unknown dimension: {sel.dimension}")

        # ── Build FROM clause ──
        from_clause = """
            documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        """
        if need_cat_join:
            from_clause += " JOIN categories cat ON d.doc_id = cat.doc_id"
        if need_sub_join:
            from_clause += " JOIN subcategories sub ON d.doc_id = sub.doc_id"

        where_clause = " AND ".join(conditions)

        # ── 1. Total document count ──
        count_sql = f"SELECT COUNT(DISTINCT d.doc_id) FROM {from_clause} WHERE {where_clause}"
        total_documents = session.execute(sql_text(count_sql), params).scalar() or 0

        # ── 2. Date range ──
        date_sql = f"SELECT MIN(d.date), MAX(d.date) FROM {from_clause} WHERE {where_clause}"
        date_row = session.execute(sql_text(date_sql), params).fetchone()
        date_min = str(date_row[0]) if date_row and date_row[0] else None
        date_max = str(date_row[1]) if date_row and date_row[1] else None

        # ── 3. Category distribution ──
        cat_dist_sql = f"""
            SELECT cat2.category, COUNT(DISTINCT d.doc_id) as cnt
            FROM {from_clause}
            JOIN categories cat2 ON d.doc_id = cat2.doc_id
            WHERE {where_clause}
            GROUP BY cat2.category ORDER BY cnt DESC
        """
        cat_dist = [{"category": r[0], "count": r[1]}
                    for r in session.execute(sql_text(cat_dist_sql), params).fetchall()]

        # ── 4. Subcategory distribution ──
        sub_dist_sql = f"""
            SELECT sub2.subcategory, COUNT(DISTINCT d.doc_id) as cnt
            FROM {from_clause}
            JOIN subcategories sub2 ON d.doc_id = sub2.doc_id
            WHERE {where_clause}
            GROUP BY sub2.subcategory ORDER BY cnt DESC
        """
        sub_dist = [{"subcategory": r[0], "count": r[1]}
                    for r in session.execute(sql_text(sub_dist_sql), params).fetchall()]

        # ── 5. Recipient distribution ──
        recip_dist_sql = f"""
            SELECT rc2.recipient_country, COUNT(DISTINCT d.doc_id) as cnt
            FROM {from_clause}
            JOIN recipient_countries rc2 ON d.doc_id = rc2.doc_id
            WHERE {where_clause}
              AND rc2.recipient_country = ANY(:recipients)
            GROUP BY rc2.recipient_country ORDER BY cnt DESC
        """
        recip_dist = [{"recipient": r[0], "count": r[1]}
                      for r in session.execute(sql_text(recip_dist_sql), params).fetchall()]

        # ── 6. Initiator distribution ──
        init_dist_sql = f"""
            SELECT ic2.initiating_country, COUNT(DISTINCT d.doc_id) as cnt
            FROM {from_clause}
            JOIN initiating_countries ic2 ON d.doc_id = ic2.doc_id
            WHERE {where_clause}
              AND ic2.initiating_country = ANY(:influencers)
            GROUP BY ic2.initiating_country ORDER BY cnt DESC
        """
        init_dist = [{"initiator": r[0], "count": r[1]}
                     for r in session.execute(sql_text(init_dist_sql), params).fetchall()]

        # ── 7. Monthly trend ──
        trend_sql = f"""
            SELECT to_char(d.date, 'YYYY-MM') as month, COUNT(DISTINCT d.doc_id) as cnt
            FROM {from_clause}
            WHERE {where_clause} AND d.date IS NOT NULL
            GROUP BY month ORDER BY month
        """
        monthly_trend = [{"month": r[0], "count": r[1]}
                         for r in session.execute(sql_text(trend_sql), params).fetchall()]

        # ── 8. Top sources ──
        source_sql = f"""
            SELECT d.source_name, COUNT(DISTINCT d.doc_id) as cnt
            FROM {from_clause}
            WHERE {where_clause} AND d.source_name IS NOT NULL
            GROUP BY d.source_name ORDER BY cnt DESC LIMIT 15
        """
        top_sources = [{"source": r[0], "count": r[1]}
                       for r in session.execute(sql_text(source_sql), params).fetchall()]

        # ── 9. Material score stats ──
        # Material score lives on EventSummary, not Document.
        # Use a lightweight average from event_summaries matching our filters.
        avg_material = None
        material_dist = []

        # ── 10. Sample documents (top 20 by date desc) ──
        sample_sql = f"""
            SELECT DISTINCT d.doc_id, d.title, d.date, d.source_name,
                   d.category, d.subcategory,
                   d.initiating_country, d.recipient_country,
                   d.distilled_text
            FROM {from_clause}
            WHERE {where_clause} AND d.date IS NOT NULL
            ORDER BY d.date DESC
            LIMIT 20
        """
        sample_rows = session.execute(sql_text(sample_sql), params).fetchall()
        sample_documents = [
            {
                "doc_id": r[0],
                "title": r[1],
                "date": str(r[2]) if r[2] else None,
                "source_name": r[3],
                "category": r[4],
                "subcategory": r[5],
                "initiating_country": r[6],
                "recipient_country": r[7],
                "material_score": None,
                "distilled_text": (r[8][:500] + "...") if r[8] and len(r[8]) > 500 else r[8],
            }
            for r in sample_rows
        ]

        # ── 11. LLM Narrative (optional) ──
        narrative = None
        narrative_model = None

        if request.include_narrative and total_documents > 0 and gai is not None:
            # Build a context-aware prompt that references the original query
            context_parts = []
            if ctx.initiating_country and ctx.initiating_country != 'ALL':
                context_parts.append(f"initiating country: {ctx.initiating_country}")
            if ctx.recipient_country and ctx.recipient_country != 'ALL':
                context_parts.append(f"recipient country: {ctx.recipient_country}")
            if ctx.start_date:
                context_parts.append(f"from {ctx.start_date}")
            if ctx.end_date:
                context_parts.append(f"to {ctx.end_date}")

            original_query_desc = ", ".join(context_parts) if context_parts else "all countries and dates"

            selection_desc = f"{sel.dimension.replace('_', ' ')}: {sel.value}"

            # Prepare document excerpts for the LLM
            doc_excerpts = []
            for doc in sample_documents:
                excerpt = f"- [{doc['date']}] {doc['title'] or 'Untitled'}"
                if doc['distilled_text']:
                    excerpt += f": {doc['distilled_text'][:300]}"
                doc_excerpts.append(excerpt)

            doc_text = "\n".join(doc_excerpts[:15])  # Cap at 15 for token budget

            # Build distribution context for the LLM
            top_cats = ", ".join([f"{c['category']} ({c['count']})" for c in cat_dist[:5]])
            top_recips = ", ".join([f"{r['recipient']} ({r['count']})" for r in recip_dist[:5]])
            top_subs = ", ".join([f"{s['subcategory']} ({s['count']})" for s in sub_dist[:5]])

            sys_prompt = (
                "You are an analyst specializing in international relations and soft power. "
                "Write in AP style. Be specific and concrete — avoid generic characterizations. "
                "Ground your analysis in the data provided."
            )

            user_prompt = f"""The user was analyzing data for: {original_query_desc}.
They selected {selection_desc} from a chart, revealing {total_documents} documents spanning {date_min} to {date_max}.

IMPORTANT: Frame your analysis around the original query context ({original_query_desc}), not just the selected slice. The user wants to understand how "{sel.value}" relates to their original analytical focus.

Dataset statistics for this slice:
- Total documents: {total_documents}
- Categories: {top_cats}
- Subcategories: {top_subs}
- Recipients: {top_recips}
- Date range: {date_min} to {date_max}

Representative sample of {len(sample_documents)} most recent documents (of {total_documents} total):
{doc_text}

Provide a concise analytical summary (3-5 paragraphs) that:
1. Contextualizes this selection within the original query scope
2. Identifies key patterns and notable findings in this slice
3. Highlights any significant concentrations or trends
4. Notes anything unexpected or noteworthy about the distribution"""

            try:
                narrative_model = "gpt-4.1-mini"
                response = gai(sys_prompt, user_prompt, narrative_model)
                # gai() already extracts content; only use fetch_gai_content for raw API responses
                narrative = response if isinstance(response, str) else str(response)
            except Exception as e:
                print(f"[Drilldown] LLM narrative failed: {e}")
                narrative = None

        # ── Build response ──
        return {
            "query_context": ctx.dict(),
            "chart_selection": sel.dict(),
            "metrics": {
                "total_documents": total_documents,
                "date_range": {"min": date_min, "max": date_max},
                "category_distribution": cat_dist,
                "subcategory_distribution": sub_dist,
                "recipient_distribution": recip_dist,
                "initiator_distribution": init_dist,
                "monthly_trend": monthly_trend,
                "top_sources": top_sources,
                "avg_material_score": avg_material,
                "material_score_distribution": material_dist,
            },
            "narrative": narrative,
            "narrative_model": narrative_model,
            "sample_documents": sample_documents,
            "total_documents": total_documents,
        }


# ============================================================================
# Entity Profile endpoints
# ============================================================================

@app.get("/api/entity/{entity_id}")
@cache(ttl=600, prefix="entity_profile")
def get_entity_profile(entity_id: str, current_user: dict = Depends(get_current_user)):
    """Full entity profile with relationships, events, and activity timeline."""
    with get_session() as session:
        entity = session.query(CanonicalEntity).filter(
            CanonicalEntity.id == entity_id
        ).first()
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        # Base profile
        profile = {
            "id": str(entity.id),
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type.value if entity.entity_type else None,
            "primary_role": entity.primary_role.value if entity.primary_role else None,
            "entity_description": entity.entity_description,
            "initiating_country": entity.initiating_country,
            "country_affiliations": entity.country_affiliations or [],
            "alternative_names": entity.alternative_names or [],
            "total_documents": entity.total_documents,
            "total_mention_days": entity.total_mention_days,
            "first_mention_date": str(entity.first_mention_date) if entity.first_mention_date else None,
            "last_mention_date": str(entity.last_mention_date) if entity.last_mention_date else None,
            "primary_categories": entity.primary_categories or {},
            "primary_recipients": entity.primary_recipients or {},
            "key_activities": entity.key_activities,
        }

        # Relationships (both directions)
        relationships = []

        outgoing = (
            session.query(EntityRelationship, CanonicalEntity)
            .join(CanonicalEntity, CanonicalEntity.id == EntityRelationship.entity_to_id)
            .filter(EntityRelationship.entity_from_id == entity_id)
            .order_by(EntityRelationship.co_occurrence_count.desc())
            .limit(20)
            .all()
        )
        for rel, related in outgoing:
            relationships.append({
                "related_entity_id": str(related.id),
                "related_entity_name": related.canonical_name,
                "related_entity_type": related.entity_type.value if related.entity_type else None,
                "relationship_type": rel.relationship_type,
                "direction": "outgoing",
                "co_occurrence_count": rel.co_occurrence_count,
                "first_co_occurrence": str(rel.first_co_occurrence) if rel.first_co_occurrence else None,
                "last_co_occurrence": str(rel.last_co_occurrence) if rel.last_co_occurrence else None,
                "relationship_description": rel.relationship_description,
            })

        incoming = (
            session.query(EntityRelationship, CanonicalEntity)
            .join(CanonicalEntity, CanonicalEntity.id == EntityRelationship.entity_from_id)
            .filter(EntityRelationship.entity_to_id == entity_id)
            .order_by(EntityRelationship.co_occurrence_count.desc())
            .limit(20)
            .all()
        )
        for rel, related in incoming:
            relationships.append({
                "related_entity_id": str(related.id),
                "related_entity_name": related.canonical_name,
                "related_entity_type": related.entity_type.value if related.entity_type else None,
                "relationship_type": rel.relationship_type,
                "direction": "incoming",
                "co_occurrence_count": rel.co_occurrence_count,
                "first_co_occurrence": str(rel.first_co_occurrence) if rel.first_co_occurrence else None,
                "last_co_occurrence": str(rel.last_co_occurrence) if rel.last_co_occurrence else None,
                "relationship_description": rel.relationship_description,
            })

        profile["relationships"] = relationships

        # Associated events
        event_ids = entity.associated_events or []
        associated_events = []
        if event_ids:
            events = (
                session.query(CanonicalEvent)
                .filter(CanonicalEvent.id.in_(event_ids[:20]))
                .order_by(CanonicalEvent.last_mention_date.desc())
                .all()
            )
            for ev in events:
                associated_events.append({
                    "id": str(ev.id),
                    "event_name": ev.canonical_name,
                    "date": str(ev.last_mention_date) if ev.last_mention_date else None,
                    "material_score": float(ev.material_score) if ev.material_score else None,
                    "story_phase": ev.story_phase,
                    "initiating_country": ev.initiating_country,
                })
        profile["associated_events"] = associated_events

        # Monthly activity timeline (from DailyEntityMention)
        monthly_raw = (
            session.query(
                func.date_trunc('month', DailyEntityMention.mention_date).label('month'),
                func.sum(DailyEntityMention.document_count).label('count'),
            )
            .filter(DailyEntityMention.canonical_entity_id == entity_id)
            .group_by(func.date_trunc('month', DailyEntityMention.mention_date))
            .order_by(func.date_trunc('month', DailyEntityMention.mention_date))
            .all()
        )
        profile["monthly_activity"] = [
            {"month": str(m.date()) if m else None, "count": int(c)}
            for m, c in monthly_raw
        ]

        return profile


@app.post("/api/entity/{entity_id}/assessment")
async def generate_entity_assessment(
    entity_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Stream a RAG-powered assessment of an entity's influence and activities."""
    from services.chat.rag_service import (
        intelligent_search, get_entity_doc_ids,
        generate_entity_assessment_stream,
    )
    import json as _json

    with get_session() as session:
        entity = session.query(CanonicalEntity).filter(
            CanonicalEntity.id == entity_id
        ).first()
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        entity_name = entity.canonical_name
        entity_data = {
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type.value if entity.entity_type else "unknown",
            "primary_role": entity.primary_role.value if entity.primary_role else "unknown",
            "initiating_country": entity.initiating_country,
            "first_mention_date": str(entity.first_mention_date) if entity.first_mention_date else "N/A",
            "last_mention_date": str(entity.last_mention_date) if entity.last_mention_date else "N/A",
            "total_mention_days": entity.total_mention_days,
            "total_documents": entity.total_documents,
            "primary_categories": entity.primary_categories or {},
            "primary_recipients": entity.primary_recipients or {},
        }

        # Get entity's doc_ids for scoped search
        doc_ids = get_entity_doc_ids([str(entity.id)], limit=200)

        # Get relationships for context
        rels = (
            session.query(EntityRelationship, CanonicalEntity)
            .join(CanonicalEntity, CanonicalEntity.id == EntityRelationship.entity_to_id)
            .filter(EntityRelationship.entity_from_id == entity_id)
            .order_by(EntityRelationship.co_occurrence_count.desc())
            .limit(10)
            .all()
        )
        rel_summaries = [
            f"{r.canonical_name} ({r.entity_type.value}) — {rel.relationship_type} ({rel.co_occurrence_count} co-occurrences)"
            for rel, r in rels
        ]

    # Build metrics context
    cat_lines = "\n".join(
        f"  {cat}: {count} mentions"
        for cat, count in sorted(entity_data["primary_categories"].items(), key=lambda x: -x[1])
    )
    rec_lines = "\n".join(
        f"  {rec}: {count} mentions"
        for rec, count in sorted(entity_data["primary_recipients"].items(), key=lambda x: -x[1])[:10]
    )
    rel_lines = "\n".join(f"  - {r}" for r in rel_summaries) if rel_summaries else "  None tracked"

    metrics_context = f"""Name: {entity_data['canonical_name']}
Type: {entity_data['entity_type']} | Role: {entity_data['primary_role']}
Country: {entity_data['initiating_country']}
Active: {entity_data['first_mention_date']} to {entity_data['last_mention_date']} ({entity_data['total_mention_days']} days)
Documents: {entity_data['total_documents']}

Category Activity:
{cat_lines}

Recipient Engagement:
{rec_lines}

Key Relationships:
{rel_lines}"""

    # RAG search scoped to entity's documents
    sources, search_metadata = intelligent_search(
        query=f"{entity_name} activities influence role soft power",
        k=min(30, len(doc_ids)) if doc_ids else 30,
        apply_intelligence=False,
        enable_entity_boost=False,
        doc_id_filter=doc_ids if doc_ids else None,
    )

    matched_entities = search_metadata.get("_matched_entities_full", [])
    strategic_ctx = search_metadata.get("_strategic_context")
    event_ctx = search_metadata.get("_event_context")

    async def event_generator():
        yield f"data: {_json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        for chunk in generate_entity_assessment_stream(
            entity_name=entity_name,
            documents=sources,
            metrics_context=metrics_context,
            matched_entities=matched_entities,
            strategic_context=strategic_ctx,
            event_context=event_ctx,
        ):
            yield f"data: {_json.dumps({'type': 'content', 'content': chunk})}\n\n"

        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ============================================================================
# Research Project endpoints
# ============================================================================

@app.get("/api/projects")
def list_projects(current_user: dict = Depends(get_current_user)):
    """List the current user's research projects."""
    with get_session() as session:
        projects = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .order_by(ResearchProject.created_at.desc())
            .all()
        )
        return {"projects": [p.to_dict() for p in projects]}


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None

@app.post("/api/projects")
def create_project(
    body: CreateProjectRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new research project."""
    with get_session() as session:
        project = ResearchProject(
            user_id=current_user["user_id"],
            name=body.name,
            description=body.description,
        )
        session.add(project)
        session.flush()
        return project.to_dict()


@app.get("/api/projects/{project_id}")
def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """Get a project with its collected documents."""
    with get_session() as session:
        project = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.to_dict(include_documents=True)


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

@app.put("/api/projects/{project_id}")
def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update project name/description."""
    with get_session() as session:
        project = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if body.name is not None:
            project.name = body.name
        if body.description is not None:
            project.description = body.description
        if body.status is not None:
            project.status = ProjectStatus(body.status)

        session.flush()
        return project.to_dict()


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """Soft-delete a research project."""
    with get_session() as session:
        project = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        project.is_deleted = True
        project.deleted_at = datetime.now(timezone.utc)
        return {"status": "deleted"}


class AddProjectDocumentRequest(BaseModel):
    doc_id: str
    title: Optional[str] = None
    source_name: Optional[str] = None
    date: Optional[str] = None
    initiating_country: Optional[str] = None
    recipient_country: Optional[str] = None
    category: Optional[str] = None
    excerpt: Optional[str] = None
    source_query: Optional[str] = None
    notes: Optional[str] = None

@app.post("/api/projects/{project_id}/documents")
def add_project_document(
    project_id: str,
    body: AddProjectDocumentRequest,
    current_user: dict = Depends(get_current_user),
):
    """Add a source document to a research project."""
    with get_session() as session:
        project = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check if already collected
        existing = (
            session.query(ProjectDocument)
            .filter(
                ProjectDocument.project_id == project_id,
                ProjectDocument.doc_id == body.doc_id,
            )
            .first()
        )
        if existing:
            return existing.to_dict()

        doc = ProjectDocument(
            project_id=project_id,
            doc_id=body.doc_id,
            title=body.title,
            source_name=body.source_name,
            date=body.date,
            initiating_country=body.initiating_country,
            recipient_country=body.recipient_country,
            category=body.category,
            excerpt=body.excerpt,
            source_query=body.source_query,
            notes=body.notes,
        )
        session.add(doc)
        session.flush()
        return doc.to_dict()


@app.delete("/api/projects/{project_id}/documents/{doc_id}")
def remove_project_document(
    project_id: str,
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a document from a research project."""
    with get_session() as session:
        project = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        doc = (
            session.query(ProjectDocument)
            .filter(
                ProjectDocument.project_id == project_id,
                ProjectDocument.doc_id == doc_id,
            )
            .first()
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Document not in project")

        session.delete(doc)
        return {"status": "removed"}


class UpdateDocNotesRequest(BaseModel):
    notes: Optional[str] = None

@app.put("/api/projects/{project_id}/documents/{doc_id}")
def update_project_document_notes(
    project_id: str,
    doc_id: str,
    body: UpdateDocNotesRequest,
    current_user: dict = Depends(get_current_user),
):

    with get_session() as session:
        project = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        doc = (
            session.query(ProjectDocument)
            .filter(
                ProjectDocument.project_id == project_id,
                ProjectDocument.doc_id == doc_id,
            )
            .first()
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Document not in project")

        if body.notes is not None:
            doc.notes = body.notes
        session.flush()
        return doc.to_dict()


@app.post("/api/projects/{project_id}/chat/stream")
async def project_chat_stream(project_id: str, request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Chat with RAG scoped to a project's collected documents."""
    from services.chat.rag_service import intelligent_search, generate_response_stream
    import json as _json

    with get_session() as session:
        project = (
            session.query(ResearchProject)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.user_id == current_user["user_id"],
                ResearchProject.is_deleted == False,
            )
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        doc_ids = [d.doc_id for d in project.documents]

    if not doc_ids:
        raise HTTPException(status_code=400, detail="Project has no collected documents")

    rag_config = CONFIG.get('rag', {})
    chat_doc_limit = rag_config.get('chat_document_limit', 50)

    sources, search_metadata = intelligent_search(
        query=request.message,
        k=min(chat_doc_limit, len(doc_ids)),
        influencer=request.influencer,
        recipient=request.recipient,
        category=request.category,
        start_date=request.start_date,
        end_date=request.end_date,
        apply_intelligence=True,
        enable_entity_boost=True,
        doc_id_filter=doc_ids,
    )

    matched_entities = search_metadata.get("_matched_entities_full", [])
    strategic_context = search_metadata.get("_strategic_context")
    event_context = search_metadata.get("_event_context")

    async def event_generator():
        metadata_payload = {
            'type': 'metadata',
            'applied_filters': search_metadata['applied_filters'],
            'inferred_filters': search_metadata['inferred_filters'],
            'inference_notes': search_metadata['confidence_notes'],
            'matched_entities': search_metadata.get('matched_entities', []),
        }
        yield f"data: {_json.dumps(metadata_payload)}\n\n"
        yield f"data: {_json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        for chunk in generate_response_stream(
            request.message, sources,
            matched_entities=matched_entities,
            strategic_context=strategic_context,
            event_context=event_context,
        ):
            yield f"data: {_json.dumps({'type': 'content', 'content': chunk})}\n\n"

        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ============================================================================
# Competing Influence Overlay
# ============================================================================

@app.get("/api/competing-influence/{recipient}")
@cache(ttl=600, prefix="competing_influence")
def get_competing_influence(
    recipient: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """All 5 influencers' activity for a single recipient — timeline, categories, events."""
    with get_session() as session:
        if recipient not in RECIPIENTS:
            raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

        # Base filters reused across queries
        base_filters = [
            RecipientCountry.recipient_country == recipient,
            InitiatingCountry.initiating_country.in_(INFLUENCERS),
            InitiatingCountry.initiating_country != RecipientCountry.recipient_country,
        ]

        date_filters = []
        if start_date:
            date_filters.append(Document.date >= start_date)
        if end_date:
            date_filters.append(Document.date <= end_date)

        # 1. Total documents
        total_docs = session.query(
            func.count(func.distinct(Document.doc_id))
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(*base_filters, *date_filters).scalar() or 0

        # 2. Influencer summary — doc count per influencer
        inf_docs = session.query(
            InitiatingCountry.initiating_country,
            func.count(func.distinct(InitiatingCountry.doc_id)).label('count')
        ).join(
            RecipientCountry, RecipientCountry.doc_id == InitiatingCountry.doc_id
        ).filter(*base_filters).group_by(
            InitiatingCountry.initiating_country
        ).all()
        inf_doc_map = {inf: count for inf, count in inf_docs}

        # Event counts + avg materiality per influencer (from CanonicalEvent via primary_recipients JSONB)
        inf_events = session.query(
            CanonicalEvent.initiating_country,
            func.count(CanonicalEvent.id).label('event_count'),
            func.avg(CanonicalEvent.material_score).label('avg_mat'),
        ).filter(
            CanonicalEvent.master_event_id.is_(None),
            CanonicalEvent.initiating_country.in_(INFLUENCERS),
            CanonicalEvent.primary_recipients.has_key(recipient),
        ).group_by(CanonicalEvent.initiating_country).all()
        inf_event_map = {inf: (ec, am) for inf, ec, am in inf_events}

        # Top category per influencer
        cat_by_inf = session.query(
            InitiatingCountry.initiating_country,
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('count')
        ).join(
            Category, Category.doc_id == InitiatingCountry.doc_id
        ).join(
            RecipientCountry, RecipientCountry.doc_id == InitiatingCountry.doc_id
        ).filter(*base_filters).group_by(
            InitiatingCountry.initiating_country, Category.category
        ).all()

        # Build top category map
        top_cat_map = {}
        for inf, cat, count in cat_by_inf:
            if inf not in top_cat_map or count > top_cat_map[inf][1]:
                top_cat_map[inf] = (cat, count)

        influencer_summary = []
        for inf in INFLUENCERS:
            ec, am = inf_event_map.get(inf, (0, None))
            top_cat, _ = top_cat_map.get(inf, (None, 0))
            influencer_summary.append({
                "influencer": inf,
                "doc_count": inf_doc_map.get(inf, 0),
                "event_count": ec or 0,
                "top_category": top_cat,
                "avg_materiality": round(float(am), 2) if am else None,
            })

        # 3. Monthly by influencer — pivot into {month, China: N, Russia: N, ...}
        monthly_raw = session.query(
            func.date_trunc('month', Document.date).label('month'),
            InitiatingCountry.initiating_country,
            func.count(func.distinct(Document.doc_id)).label('count')
        ).join(InitiatingCountry).join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            *base_filters,
            Document.date.isnot(None),
            *date_filters,
        ).group_by(
            func.date_trunc('month', Document.date),
            InitiatingCountry.initiating_country
        ).order_by(func.date_trunc('month', Document.date)).all()

        # Pivot
        monthly_map = {}
        for month, inf, count in monthly_raw:
            m_str = str(month.date()) if month else None
            if m_str not in monthly_map:
                monthly_map[m_str] = {"month": m_str}
                for i in INFLUENCERS:
                    monthly_map[m_str][i] = 0
            monthly_map[m_str][inf] = count

        monthly_by_influencer = list(monthly_map.values())

        # 4. Category matrix — {influencer, Economic: N, Social: N, ...}
        category_matrix = []
        cat_data = {}
        for inf, cat, count in cat_by_inf:
            if inf not in cat_data:
                cat_data[inf] = {"influencer": inf}
            cat_data[inf][cat] = count
        for inf in INFLUENCERS:
            if inf in cat_data:
                category_matrix.append(cat_data[inf])
            else:
                category_matrix.append({"influencer": inf})

        # 5. Recent events per influencer (top 3 each)
        recent_events = {}
        for inf in INFLUENCERS:
            events = session.query(
                CanonicalEvent.id,
                CanonicalEvent.canonical_name,
                CanonicalEvent.last_mention_date,
                CanonicalEvent.material_score,
                CanonicalEvent.story_phase,
            ).filter(
                CanonicalEvent.master_event_id.is_(None),
                CanonicalEvent.initiating_country == inf,
                CanonicalEvent.primary_recipients.has_key(recipient),
            ).order_by(
                CanonicalEvent.last_mention_date.desc()
            ).limit(3).all()

            recent_events[inf] = [
                {
                    "id": str(e.id),
                    "event_name": e.canonical_name,
                    "date": str(e.last_mention_date) if e.last_mention_date else None,
                    "material_score": float(e.material_score) if e.material_score else None,
                    "story_phase": e.story_phase,
                }
                for e in events
            ]

        return {
            "recipient": recipient,
            "total_documents": total_docs,
            "influencer_summary": influencer_summary,
            "monthly_by_influencer": monthly_by_influencer,
            "category_matrix": category_matrix,
            "recent_events": recent_events,
        }


class ComparativeAssessmentRequest(BaseModel):
    metrics_context: str  # Pre-formatted metrics string from the frontend


@app.post("/api/competing-influence/{recipient}/assessment")
async def generate_comparative_assessment(
    recipient: str,
    request: ComparativeAssessmentRequest,
    current_user: dict = Depends(get_current_user),
):
    """Stream a RAG-powered comparative assessment for all influencers in a recipient."""
    from services.chat.rag_service import (
        intelligent_search, generate_comparative_assessment_stream,
    )
    import json as _json

    if recipient not in RECIPIENTS:
        raise HTTPException(status_code=404, detail=f"{recipient} is not a recognized recipient")

    rag_config = CONFIG.get('rag', {})

    # Search for relevant documents across all influencers for this recipient
    sources, search_metadata = intelligent_search(
        query=f"Compare all influencer countries' soft power activities, investments, and diplomacy in {recipient}",
        k=30,
        recipient=recipient,
        apply_intelligence=False,
        enable_entity_boost=True,
    )

    matched_entities = search_metadata.get("_matched_entities_full", [])
    strategic_ctx = search_metadata.get("_strategic_context")
    event_ctx = search_metadata.get("_event_context")

    async def event_generator():
        # Send sources first so the frontend can render them
        yield f"data: {_json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        # Stream the comparative assessment with layered context
        for chunk in generate_comparative_assessment_stream(
            recipient=recipient,
            documents=sources,
            metrics_context=request.metrics_context,
            matched_entities=matched_entities,
            strategic_context=strategic_ctx,
            event_context=event_ctx,
        ):
            yield f"data: {_json.dumps({'type': 'content', 'content': chunk})}\n\n"

        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ============================================================================
# Alert endpoints
# ============================================================================

@app.get("/api/alerts/rules")
def list_alert_rules(current_user: dict = Depends(get_current_user)):
    """List the current user's alert rules."""
    with get_session() as session:
        rules = (
            session.query(AlertRule)
            .filter(
                AlertRule.user_id == current_user["user_id"],
                AlertRule.is_deleted == False,
            )
            .order_by(AlertRule.created_at.desc())
            .all()
        )
        return {"rules": [r.to_dict() for r in rules]}


class CreateAlertRuleRequest(BaseModel):
    name: str
    condition_type: str
    description: Optional[str] = None
    condition_params: dict = {}
    channels: List[str] = ["in_app"]
    channel_config: dict = {}
    severity: str = "info"
    cooldown_minutes: int = 60

@app.post("/api/alerts/rules")
def create_alert_rule(
    body: CreateAlertRuleRequest,
    current_user: dict = Depends(require_analyst_or_above),
):
    """Create a new alert rule."""
    try:
        ct = AlertConditionType(body.condition_type)
    except ValueError:
        valid = [t.value for t in AlertConditionType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid condition_type. Must be one of: {valid}",
        )

    with get_session() as session:
        rule = AlertRule(
            user_id=current_user["user_id"],
            name=body.name,
            description=body.description,
            condition_type=ct,
            condition_params=body.condition_params,
            channels=body.channels,
            channel_config=body.channel_config,
            severity=AlertSeverity(body.severity),
            cooldown_minutes=body.cooldown_minutes,
        )
        session.add(rule)
        session.flush()
        result = rule.to_dict()
    return result


class UpdateAlertRuleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    condition_type: Optional[str] = None
    condition_params: Optional[dict] = None
    channels: Optional[List[str]] = None
    channel_config: Optional[dict] = None
    severity: Optional[str] = None
    cooldown_minutes: Optional[int] = None
    is_enabled: Optional[bool] = None

@app.put("/api/alerts/rules/{rule_id}")
def update_alert_rule(
    rule_id: str,
    body: UpdateAlertRuleRequest,
    current_user: dict = Depends(require_analyst_or_above),
):
    """Update an existing alert rule (must be owned by user)."""
    with get_session() as session:
        rule = (
            session.query(AlertRule)
            .filter(
                AlertRule.id == rule_id,
                AlertRule.user_id == current_user["user_id"],
                AlertRule.is_deleted == False,
            )
            .first()
        )
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        updatable = [
            "name", "description", "condition_params", "channels",
            "channel_config", "cooldown_minutes", "is_enabled",
        ]
        body_dict = body.model_dump(exclude_none=True)
        for field in updatable:
            if field in body_dict:
                setattr(rule, field, body_dict[field])

        if body.condition_type is not None:
            rule.condition_type = AlertConditionType(body.condition_type)
        if body.severity is not None:
            rule.severity = AlertSeverity(body.severity)

        session.flush()
        return rule.to_dict()


@app.delete("/api/alerts/rules/{rule_id}")
def delete_alert_rule(
    rule_id: str,
    current_user: dict = Depends(require_analyst_or_above),
):
    """Soft-delete an alert rule."""
    with get_session() as session:
        rule = (
            session.query(AlertRule)
            .filter(
                AlertRule.id == rule_id,
                AlertRule.user_id == current_user["user_id"],
                AlertRule.is_deleted == False,
            )
            .first()
        )
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        rule.is_deleted = True
        rule.deleted_at = datetime.now(timezone.utc)
        return {"status": "deleted"}


@app.get("/api/alerts/history")
def list_alert_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """List alert history for the current user's rules."""
    with get_session() as session:
        user_rule_ids = (
            session.query(AlertRule.id)
            .filter(
                AlertRule.user_id == current_user["user_id"],
                AlertRule.is_deleted == False,
            )
            .subquery()
        )

        query = (
            session.query(AlertHistory)
            .filter(AlertHistory.alert_rule_id.in_(user_rule_ids))
            .order_by(AlertHistory.triggered_at.desc())
        )
        total = query.count()
        alerts = query.offset(offset).limit(limit).all()

        return {
            "alerts": [a.to_dict() for a in alerts],
            "total": total,
        }


@app.post("/api/alerts/history/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Acknowledge an alert."""
    with get_session() as session:
        # Verify the alert belongs to a rule owned by this user
        alert = (
            session.query(AlertHistory)
            .join(AlertRule)
            .filter(
                AlertHistory.id == alert_id,
                AlertRule.user_id == current_user["user_id"],
            )
            .first()
        )
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        alert.acknowledged = True
        alert.acknowledged_by = current_user["user_id"]
        alert.acknowledged_at = datetime.now(timezone.utc)
        return {"status": "acknowledged"}


@app.get("/api/alerts/unread-count")
def get_unread_alert_count(current_user: dict = Depends(get_current_user)):
    """Count unacknowledged alerts for the current user."""
    with get_session() as session:
        user_rule_ids = (
            session.query(AlertRule.id)
            .filter(
                AlertRule.user_id == current_user["user_id"],
                AlertRule.is_deleted == False,
            )
            .subquery()
        )
        count = (
            session.query(func.count(AlertHistory.id))
            .filter(
                AlertHistory.alert_rule_id.in_(user_rule_ids),
                AlertHistory.acknowledged == False,
            )
            .scalar()
        )
        return {"count": count or 0}


@app.post("/api/alerts/test/{rule_id}")
def test_alert_rule(
    rule_id: str,
    current_user: dict = Depends(require_analyst_or_above),
):
    """Force-evaluate a single rule for testing."""
    from server.alert_evaluator import evaluate_rule
    from server.alert_notifier import dispatch_alert

    with get_session() as session:
        rule = (
            session.query(AlertRule)
            .filter(
                AlertRule.id == rule_id,
                AlertRule.user_id == current_user["user_id"],
                AlertRule.is_deleted == False,
            )
            .first()
        )
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        alert = evaluate_rule(rule, session)
        if alert:
            session.add(alert)
            session.flush()
            try:
                notified = dispatch_alert(alert, rule)
                alert.channels_notified = notified
            except Exception:
                pass
            rule.last_evaluated_at = datetime.now(timezone.utc)
            rule.last_triggered_at = datetime.now(timezone.utc)
            return {
                "triggered": True,
                "alert": alert.to_dict(),
            }
        else:
            rule.last_evaluated_at = datetime.now(timezone.utc)
            return {
                "triggered": False,
                "message": "Condition not met — no alert generated",
            }


# Static file serving for React SPA
# IMPORTANT: This must come AFTER all @app.get() API route definitions
# so that API routes take precedence over the catch-all
if STATIC_DIR.exists():
    # Mount static assets directory (only if it exists, e.g., after npm run build)
    if (STATIC_DIR / "assets").exists():
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
    port = int(os.environ.get("API_PORT", "8000"))
    host = os.environ.get("API_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
