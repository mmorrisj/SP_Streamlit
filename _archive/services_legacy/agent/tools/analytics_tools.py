"""
Analytics Tools for Soft Power Agent

Provides structured tools for querying statistics, trends, and patterns.
"""

from typing import Dict, List, Optional
from datetime import datetime, date
from sqlalchemy import text, func

from shared.database.database import get_session
from shared.models.models import EventSummary, Document, PeriodType


def get_country_activity_stats(
    country: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict:
    """
    Get activity statistics for a specific country.

    Args:
        country: Initiating country name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Dictionary with activity metrics
    """
    with get_session() as session:
        # Parse dates
        start_dt = datetime.fromisoformat(start_date).date() if start_date else date(2024, 1, 1)
        end_dt = datetime.fromisoformat(end_date).date() if end_date else date.today()

        # Get event counts by period type
        event_counts = session.execute(
            text("""
                SELECT
                    period_type,
                    COUNT(*) as count,
                    SUM(total_documents_across_sources) as total_docs
                FROM event_summaries
                WHERE initiating_country = :country
                  AND period_start >= :start_date
                  AND period_end <= :end_date
                  AND status = 'ACTIVE'
                GROUP BY period_type
            """),
            {'country': country, 'start_date': start_dt, 'end_date': end_dt}
        ).fetchall()

        stats = {
            'country': country,
            'period': f"{start_dt} to {end_dt}",
            'events_by_type': {row[0]: {'count': row[1], 'total_documents': row[2]} for row in event_counts},
        }

        # Get top categories
        top_categories = session.execute(
            text("""
                SELECT
                    category,
                    COUNT(*) as event_count
                FROM event_summaries, jsonb_each_text(count_by_category)
                WHERE initiating_country = :country
                  AND period_start >= :start_date
                  AND period_end <= :end_date
                  AND status = 'ACTIVE'
                GROUP BY category
                ORDER BY event_count DESC
                LIMIT 10
            """),
            {'country': country, 'start_date': start_dt, 'end_date': end_dt}
        ).fetchall()

        stats['top_categories'] = [{'category': row[0], 'event_count': row[1]} for row in top_categories]

        # Get top recipients
        top_recipients = session.execute(
            text("""
                SELECT
                    recipient,
                    COUNT(*) as event_count
                FROM event_summaries, jsonb_each_text(count_by_recipient)
                WHERE initiating_country = :country
                  AND period_start >= :start_date
                  AND period_end <= :end_date
                  AND status = 'ACTIVE'
                GROUP BY recipient
                ORDER BY event_count DESC
                LIMIT 10
            """),
            {'country': country, 'start_date': start_dt, 'end_date': end_dt}
        ).fetchall()

        stats['top_recipients'] = [{'recipient': row[0], 'event_count': row[1]} for row in top_recipients]

        return stats


def get_bilateral_relationship_summary(
    initiating_country: str,
    recipient_country: str
) -> Optional[Dict]:
    """
    Get bilateral relationship summary between two countries.

    Args:
        initiating_country: Initiating country
        recipient_country: Recipient country

    Returns:
        Bilateral summary data or None if not found
    """
    with get_session() as session:
        result = session.execute(
            text("""
                SELECT
                    relationship_summary,
                    total_documents,
                    material_score,
                    first_interaction_date,
                    last_interaction_date,
                    count_by_category,
                    total_daily_events,
                    total_weekly_events,
                    total_monthly_events
                FROM bilateral_summaries
                WHERE initiating_country = :init_country
                  AND recipient_country = :recip_country
                LIMIT 1
            """),
            {'init_country': initiating_country, 'recip_country': recipient_country}
        ).fetchone()

        if not result:
            return None

        return {
            'initiating_country': initiating_country,
            'recipient_country': recipient_country,
            'relationship_summary': result[0],
            'total_documents': result[1],
            'material_score': float(result[2]),
            'first_interaction_date': result[3].isoformat() if result[3] else None,
            'last_interaction_date': result[4].isoformat() if result[4] else None,
            'count_by_category': result[5],
            'total_daily_events': result[6],
            'total_weekly_events': result[7],
            'total_monthly_events': result[8]
        }


def get_trending_events(
    country: Optional[str] = None,
    period_type: str = 'daily',
    limit: int = 10,
    days: int = 30
) -> List[Dict]:
    """
    Get trending events based on recent activity.

    Args:
        country: Optional country filter
        period_type: Period type (daily, weekly, monthly)
        limit: Maximum results
        days: Look back period in days

    Returns:
        List of trending events with metrics
    """
    with get_session() as session:
        lookback_date = date.today() - timedelta(days=days)

        query = text("""
            SELECT
                id,
                event_name,
                initiating_country,
                period_start,
                period_end,
                total_documents_across_sources,
                count_by_category,
                count_by_recipient
            FROM event_summaries
            WHERE period_type = :period_type
              AND period_start >= :lookback_date
              AND status = 'ACTIVE'
              AND (:country IS NULL OR initiating_country = :country)
            ORDER BY total_documents_across_sources DESC, period_start DESC
            LIMIT :limit
        """)

        results = session.execute(
            query,
            {
                'period_type': period_type.upper(),
                'lookback_date': lookback_date,
                'country': country,
                'limit': limit
            }
        ).fetchall()

        return [
            {
                'event_id': str(row[0]),
                'event_name': row[1],
                'country': row[2],
                'period_start': row[3].isoformat(),
                'period_end': row[4].isoformat(),
                'total_documents': row[5],
                'categories': list(row[6].keys()) if row[6] else [],
                'recipients': list(row[7].keys()) if row[7] else []
            }
            for row in results
        ]


def get_category_trends(
    category: str,
    country: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict:
    """
    Analyze trends for a specific category over time.

    Args:
        category: Category name
        country: Optional country filter
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Category trend analysis
    """
    with get_session() as session:
        start_dt = datetime.fromisoformat(start_date).date() if start_date else date(2024, 1, 1)
        end_dt = datetime.fromisoformat(end_date).date() if end_date else date.today()

        # Get monthly activity for this category
        monthly_activity = session.execute(
            text("""
                SELECT
                    DATE_TRUNC('month', period_start) as month,
                    COUNT(*) as event_count,
                    SUM((count_by_category->>:category)::int) as document_count
                FROM event_summaries
                WHERE count_by_category ? :category
                  AND period_start >= :start_date
                  AND period_end <= :end_date
                  AND (:country IS NULL OR initiating_country = :country)
                  AND status = 'ACTIVE'
                GROUP BY DATE_TRUNC('month', period_start)
                ORDER BY month
            """),
            {
                'category': category,
                'start_date': start_dt,
                'end_date': end_dt,
                'country': country
            }
        ).fetchall()

        # Get top events in this category
        top_events = session.execute(
            text("""
                SELECT
                    event_name,
                    initiating_country,
                    (count_by_category->>:category)::int as doc_count,
                    period_start,
                    period_end
                FROM event_summaries
                WHERE count_by_category ? :category
                  AND period_start >= :start_date
                  AND period_end <= :end_date
                  AND (:country IS NULL OR initiating_country = :country)
                  AND status = 'ACTIVE'
                ORDER BY (count_by_category->>:category)::int DESC
                LIMIT 10
            """),
            {
                'category': category,
                'start_date': start_dt,
                'end_date': end_dt,
                'country': country
            }
        ).fetchall()

        return {
            'category': category,
            'period': f"{start_dt} to {end_dt}",
            'country_filter': country,
            'monthly_activity': [
                {
                    'month': row[0].isoformat(),
                    'event_count': row[1],
                    'document_count': row[2]
                }
                for row in monthly_activity
            ],
            'top_events': [
                {
                    'event_name': row[0],
                    'country': row[1],
                    'document_count': row[2],
                    'period_start': row[3].isoformat(),
                    'period_end': row[4].isoformat()
                }
                for row in top_events
            ]
        }


def compare_countries(
    countries: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict:
    """
    Compare activity levels across multiple countries.

    Args:
        countries: List of country names
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Comparative statistics
    """
    with get_session() as session:
        start_dt = datetime.fromisoformat(start_date).date() if start_date else date(2024, 1, 1)
        end_dt = datetime.fromisoformat(end_date).date() if end_date else date.today()

        comparison = {}

        for country in countries:
            stats = get_country_activity_stats(country, start_date, end_date)
            comparison[country] = stats

        return {
            'countries': countries,
            'period': f"{start_dt} to {end_dt}",
            'comparison': comparison
        }


# Import needed for timedelta
from datetime import timedelta
