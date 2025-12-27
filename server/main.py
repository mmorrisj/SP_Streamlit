import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel
from sqlalchemy import func, text
from pathlib import Path
import yaml

from shared.database.database import get_session
from shared.models.models import (
    Document, EventSummary, CanonicalEvent,
    Category, Subcategory, InitiatingCountry, RecipientCountry
)

app = FastAPI(title="Soft Power API", version="1.0.0")

STATIC_DIR = Path(__file__).parent.parent / "client" / "dist"

# Load config.yaml for influencers and recipients lists
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

INFLUENCERS = CONFIG.get('influencers', [])
RECIPIENTS = CONFIG.get('recipients', [])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DocumentStats(BaseModel):
    total_documents: int
    documents_by_week: list
    top_countries: list
    category_distribution: list

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
    categories: list
    subcategories: list
    date_range: dict

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/documents/stats", response_model=DocumentStats)
def get_document_stats(
    country: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
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
        if category and category != 'ALL':
            base_query = base_query.join(Category).filter(
                Category.category == category
            )

        total = base_query.distinct().count()

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

        docs_by_week = week_query.group_by('week').order_by('week').limit(20).all()

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

        return DocumentStats(
            total_documents=total,
            documents_by_week=[
                {"week": str(row.week)[:10] if row.week else "", "count": row.count}
                for row in docs_by_week
            ],
            top_countries=[
                {"country": row.country, "count": row.count}
                for row in top_countries
            ],
            category_distribution=[
                {"category": row.category, "count": row.count}
                for row in category_dist
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
            DailyEventMention.doc_id.in_(session.query(bilateral_doc_ids)),
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

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)
