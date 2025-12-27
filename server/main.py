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

from shared.database.database import get_session
from shared.models.models import Document, EventSummary, CanonicalEvent

app = FastAPI(title="Soft Power API", version="1.0.0")

STATIC_DIR = Path(__file__).parent.parent / "client" / "dist"

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
        query = session.query(Document)
        
        if country and country != 'ALL':
            query = query.filter(Document.initiating_country == country)
        if category and category != 'ALL':
            query = query.filter(Document.category == category)
            
        total = query.count()
        
        week_query = session.query(
            func.date_trunc('week', Document.date).label('week'),
            func.count().label('count')
        ).filter(Document.date.isnot(None))
        if country and country != 'ALL':
            week_query = week_query.filter(Document.initiating_country == country)
        if category and category != 'ALL':
            week_query = week_query.filter(Document.category == category)
        if start_date:
            week_query = week_query.filter(Document.date >= start_date)
        if end_date:
            week_query = week_query.filter(Document.date <= end_date)
        docs_by_week = week_query.group_by('week').order_by('week').limit(20).all()
        
        countries_query = session.query(
            Document.initiating_country.label('country'),
            func.count().label('count')
        ).filter(Document.initiating_country.isnot(None))
        if category and category != 'ALL':
            countries_query = countries_query.filter(Document.category == category)
        top_countries = countries_query.group_by(Document.initiating_country
        ).order_by(func.count().desc()).limit(10).all()
        
        cat_query = session.query(
            Document.category.label('category'),
            func.count().label('count')
        ).filter(Document.category.isnot(None))
        if country and country != 'ALL':
            cat_query = cat_query.filter(Document.initiating_country == country)
        category_dist = cat_query.group_by(Document.category
        ).order_by(func.count().desc()).all()
        
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
        query = session.query(Document)
        
        if search:
            query = query.filter(Document.title.ilike(f'%{search}%'))
        if country and country != 'ALL':
            query = query.filter(Document.initiating_country == country)
        if category and category != 'ALL':
            query = query.filter(Document.category == category)
            
        total = query.count()
        offset = (page - 1) * limit
        docs = query.order_by(Document.date.desc()).offset(offset).limit(limit).all()
        
        return DocumentResponse(
            documents=[
                {
                    "id": doc.doc_id,
                    "atom_id": doc.doc_id,
                    "title": doc.title,
                    "source_name": doc.source_name,
                    "source_date": str(doc.date) if doc.date else None,
                    "category": doc.category,
                    "subcategory": doc.subcategory,
                    "initiating_country": doc.initiating_country,
                    "recipient_country": doc.recipient_country,
                }
                for doc in docs
            ],
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
        relationships = session.query(
            Document.initiating_country,
            Document.recipient_country,
            func.count().label('count')
        ).filter(
            Document.initiating_country.isnot(None),
            Document.recipient_country.isnot(None)
        ).group_by(
            Document.initiating_country,
            Document.recipient_country
        ).order_by(func.count().desc()).limit(30).all()
        
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
        categories = session.query(
            Document.category,
            func.count().label('count')
        ).filter(Document.category.isnot(None)
        ).group_by(Document.category
        ).order_by(func.count().desc()).all()
        
        subcategories = session.query(
            Document.subcategory,
            func.count().label('count')
        ).filter(Document.subcategory.isnot(None)
        ).group_by(Document.subcategory
        ).order_by(func.count().desc()).limit(20).all()
        
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
        countries = session.query(Document.initiating_country
        ).distinct().filter(Document.initiating_country.isnot(None)).all()
        
        categories = session.query(Document.category
        ).distinct().filter(Document.category.isnot(None)).all()
        
        subcategories = session.query(Document.subcategory
        ).distinct().filter(Document.subcategory.isnot(None)).all()
        
        date_range = session.query(
            func.min(Document.date).label('min'),
            func.max(Document.date).label('max')
        ).first()
        
        return FiltersResponse(
            countries=[c[0] for c in countries if c[0]],
            categories=[c[0] for c in categories if c[0]],
            subcategories=[c[0] for c in subcategories if c[0]],
            date_range={
                "min": str(date_range.min) if date_range and date_range.min else None,
                "max": str(date_range.max) if date_range and date_range.max else None
            }
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
