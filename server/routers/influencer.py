"""Influencer-specific API endpoints (`/api/influencer/*`).

Extracted verbatim from server/main.py. Routes keep their full paths (no
prefix) so the public API is unchanged.
"""
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import func

from shared.database.database import get_session
from shared.cache.redis_cache import cache
from shared.models.models import (
    Document, EventSummary, CanonicalEvent, Category, CountryCategorySummary,
    DailyEventMention, InitiatingCountry, RecipientCountry, CanonicalEntity,
    BilateralRelationshipSummary,
)
from server._shared import INFLUENCERS, RECIPIENTS, _get_narrative_for_events

router = APIRouter()


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

@router.get("/api/influencer/{country}/overview", response_model=InfluencerOverview)
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

@router.get("/api/influencer/{country}/recent-activities", response_model=RecentActivity)
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

@router.get("/api/influencer/{country}/events", response_model=InfluencerEventsResponse)
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


@router.get("/api/influencer/{country}/entities", response_model=InfluencerEntitiesResponse)
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


@router.get("/api/influencer/{country}/bilateral-summaries", response_model=InfluencerBilateralSummariesResponse)
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


@router.get("/api/influencer/{country}/category-summaries", response_model=InfluencerCategorySummariesResponse)
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


@router.get("/api/influencer/{country}/sources", response_model=InfluencerSourcesResponse)
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


@router.get("/api/influencer/{country}/timeline", response_model=InfluencerTimelineResponse)
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
