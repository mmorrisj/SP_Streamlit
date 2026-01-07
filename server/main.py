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
CONFIG_PATH = Path(__file__).parent.parent / "shared" / "config" / "config.yaml"
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

INFLUENCERS = CONFIG.get('influencers', [])
RECIPIENTS = CONFIG.get('recipients', [])

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

    # Build path based on bilateral or all-recipients
    if recipient:
        summary_path = PUBLICATIONS_DIR / influencer / recipient / level
    else:
        summary_path = PUBLICATIONS_DIR / influencer / level

    if not summary_path.exists():
        return SummaryListResponse(summaries=[], influencer=influencer, recipient=recipient)

    summaries = []
    if level == "overall":
        # Overall summaries are individual files, not in a directory
        parent_dir = summary_path.parent
        for file in parent_dir.glob("overall_*.json"):
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
        # Daily (YYYY-MM-DD.json)
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

        # Load summary data
        with open(file, 'r', encoding='utf-8') as f:
            data = json.load(f)

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

    with open(file_path, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)

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

    with open(file_path, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)

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
