"""
Query functions for bilateral relationship summaries.
"""

from typing import List, Dict, Optional
from datetime import date
from sqlalchemy import text, or_, and_
from shared.database.database import get_session
from shared.models.models import BilateralRelationshipSummary, EventSummary


def get_all_bilateral_summaries() -> List[Dict]:
    """
    Get all bilateral relationship summaries.

    Returns:
        List of summary dicts with all fields
    """
    with get_session() as session:
        summaries = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.is_deleted == False
        ).all()

        return [summary_to_dict(s) for s in summaries]


def get_bilateral_summary(
    initiating_country: str,
    recipient_country: str
) -> Optional[Dict]:
    """
    Get a specific bilateral relationship summary.

    Args:
        initiating_country: Initiating country name
        recipient_country: Recipient country name

    Returns:
        Summary dict or None if not found
    """
    with get_session() as session:
        summary = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.initiating_country == initiating_country,
            BilateralRelationshipSummary.recipient_country == recipient_country,
            BilateralRelationshipSummary.is_deleted == False
        ).first()

        if summary:
            return summary_to_dict(summary)
        return None


def get_top_relationships_by_documents(limit: int = 20) -> List[Dict]:
    """
    Get top bilateral relationships by document count.

    Args:
        limit: Number of results to return

    Returns:
        List of summary dicts sorted by document count
    """
    with get_session() as session:
        summaries = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.is_deleted == False
        ).order_by(
            BilateralRelationshipSummary.total_documents.desc()
        ).limit(limit).all()

        return [summary_to_dict(s) for s in summaries]


def get_top_relationships_by_material_score(limit: int = 20) -> List[Dict]:
    """
    Get top bilateral relationships by material score.

    Args:
        limit: Number of results to return

    Returns:
        List of summary dicts sorted by material score
    """
    with get_session() as session:
        summaries = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.is_deleted == False,
            BilateralRelationshipSummary.material_score.isnot(None)
        ).order_by(
            BilateralRelationshipSummary.material_score.desc()
        ).limit(limit).all()

        return [summary_to_dict(s) for s in summaries]


def search_bilateral_summaries(query: str) -> List[Dict]:
    """
    Search bilateral summaries by text in overview, themes, or initiatives.

    Uses PostgreSQL full-text search on JSONB content.

    Args:
        query: Search query string

    Returns:
        List of matching summary dicts
    """
    with get_session() as session:
        # Search in relationship_summary JSONB field
        sql = text("""
            SELECT *
            FROM bilateral_relationship_summaries
            WHERE is_deleted = FALSE
            AND (
                relationship_summary->>'overview' ILIKE :query
                OR relationship_summary->>'trend_analysis' ILIKE :query
                OR relationship_summary->>'current_status' ILIKE :query
                OR relationship_summary::text ILIKE :query
            )
            ORDER BY material_score DESC NULLS LAST
            LIMIT 50
        """)

        results = session.execute(
            sql,
            {"query": f"%{query}%"}
        ).fetchall()

        # Convert to dicts
        summaries = []
        for row in results:
            summaries.append({
                'id': str(row[0]),
                'initiating_country': row[1],
                'recipient_country': row[2],
                'first_interaction_date': row[3],
                'last_interaction_date': row[4],
                'analysis_generated_at': row[5],
                'total_documents': row[6],
                'total_daily_events': row[7],
                'total_weekly_events': row[8],
                'total_monthly_events': row[9],
                'count_by_category': row[10],
                'count_by_subcategory': row[11],
                'count_by_source': row[12],
                'activity_by_month': row[13],
                'relationship_summary': row[14],
                'material_score': row[15],
                'material_justification': row[16],
                'created_at': row[17],
                'updated_at': row[18],
                'created_by': row[19],
                'version': row[20],
                'is_deleted': row[21],
                'deleted_at': row[22]
            })

        return summaries


def get_relationships_by_initiator(initiating_country: str) -> List[Dict]:
    """
    Get all bilateral relationships for a specific initiating country.

    Args:
        initiating_country: Initiating country name

    Returns:
        List of summary dicts for that initiator
    """
    with get_session() as session:
        summaries = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.initiating_country == initiating_country,
            BilateralRelationshipSummary.is_deleted == False
        ).order_by(
            BilateralRelationshipSummary.total_documents.desc()
        ).all()

        return [summary_to_dict(s) for s in summaries]


def get_relationships_by_recipient(recipient_country: str) -> List[Dict]:
    """
    Get all bilateral relationships where a country is the recipient.

    Args:
        recipient_country: Recipient country name

    Returns:
        List of summary dicts for that recipient
    """
    with get_session() as session:
        summaries = session.query(BilateralRelationshipSummary).filter(
            BilateralRelationshipSummary.recipient_country == recipient_country,
            BilateralRelationshipSummary.is_deleted == False
        ).order_by(
            BilateralRelationshipSummary.total_documents.desc()
        ).all()

        return [summary_to_dict(s) for s in summaries]


def get_summary_statistics() -> Dict:
    """
    Get aggregate statistics about bilateral summaries.

    Returns:
        Dict with statistics
    """
    with get_session() as session:
        result = session.execute(text("""
            SELECT
                COUNT(*) as total_summaries,
                COUNT(DISTINCT initiating_country) as unique_initiators,
                COUNT(DISTINCT recipient_country) as unique_recipients,
                SUM(total_documents) as total_documents,
                AVG(material_score) as avg_material_score,
                MAX(material_score) as max_material_score,
                MIN(material_score) as min_material_score
            FROM bilateral_relationship_summaries
            WHERE is_deleted = FALSE
        """)).fetchone()

        return {
            'total_summaries': result[0],
            'unique_initiators': result[1],
            'unique_recipients': result[2],
            'total_documents': result[3],
            'avg_material_score': float(result[4]) if result[4] else 0,
            'max_material_score': float(result[5]) if result[5] else 0,
            'min_material_score': float(result[6]) if result[6] else 0
        }


def summary_to_dict(summary: BilateralRelationshipSummary) -> Dict:
    """
    Convert a BilateralRelationshipSummary ORM object to a dict.

    Args:
        summary: BilateralRelationshipSummary instance

    Returns:
        Dict representation
    """
    return {
        'id': str(summary.id),
        'initiating_country': summary.initiating_country,
        'recipient_country': summary.recipient_country,
        'first_interaction_date': summary.first_interaction_date,
        'last_interaction_date': summary.last_interaction_date,
        'analysis_generated_at': summary.analysis_generated_at,
        'total_documents': summary.total_documents,
        'total_daily_events': summary.total_daily_events,
        'total_weekly_events': summary.total_weekly_events,
        'total_monthly_events': summary.total_monthly_events,
        'count_by_category': summary.count_by_category,
        'count_by_subcategory': summary.count_by_subcategory,
        'count_by_source': summary.count_by_source,
        'activity_by_month': summary.activity_by_month,
        'relationship_summary': summary.relationship_summary,
        'material_score': summary.material_score,
        'material_justification': summary.material_justification,
        'created_at': summary.created_at,
        'updated_at': summary.updated_at,
        'created_by': summary.created_by,
        'version': summary.version,
        'is_deleted': summary.is_deleted,
        'deleted_at': summary.deleted_at
    }


def get_bilateral_events_by_materiality(
    initiating_country: str,
    recipient_country: str,
    min_materiality: float = 6.0,
    max_materiality: Optional[float] = None,
    period_type: str = 'DAILY',
    limit: int = 50
) -> List[Dict]:
    """
    Get event summaries for a bilateral relationship filtered by materiality score.

    Args:
        initiating_country: Initiating country name
        recipient_country: Recipient country name
        min_materiality: Minimum material score (default 6.0 for high materiality)
        max_materiality: Maximum material score (optional, for symbolic events use 5.0)
        period_type: Event period type (DAILY, WEEKLY, MONTHLY)
        limit: Maximum number of events to return

    Returns:
        List of event summary dicts
    """
    with get_session() as session:
        query = session.query(EventSummary).filter(
            EventSummary.initiating_country == initiating_country,
            EventSummary.count_by_recipient.op('?')(recipient_country),  # JSONB contains key
            EventSummary.period_type == period_type,
            EventSummary.material_score.isnot(None)
        )

        # Apply materiality filters
        if max_materiality is not None:
            query = query.filter(
                EventSummary.material_score >= min_materiality,
                EventSummary.material_score <= max_materiality
            )
        else:
            query = query.filter(EventSummary.material_score >= min_materiality)

        # Order by material score descending, then by date descending
        query = query.order_by(
            EventSummary.material_score.desc(),
            EventSummary.period_start.desc()
        ).limit(limit)

        events = query.all()

        return [event_to_dict(event) for event in events]


def event_to_dict(event: EventSummary) -> Dict:
    """Convert EventSummary ORM object to dict."""
    return {
        'id': str(event.id),
        'event_name': event.event_name,
        'period_start': event.period_start,
        'period_end': event.period_end,
        'period_type': event.period_type,
        'initiating_country': event.initiating_country,
        'count_by_category': event.count_by_category,
        'count_by_subcategory': event.count_by_subcategory,
        'count_by_recipient': event.count_by_recipient,
        'narrative_summary': event.narrative_summary,
        'material_score': event.material_score,
        'material_justification': event.material_justification,
        'total_documents_across_categories': event.total_documents_across_categories
    }
