"""
Query functions for event summaries (daily, weekly, monthly).
"""

from datetime import datetime, date
from typing import List, Dict, Optional, Any
from sqlalchemy import text
from shared.database.database import get_engine


def get_available_summary_dates(
    country: str,
    period_type: str = 'DAILY'
) -> List[date]:
    """
    Get list of dates that have summaries available for a country.

    Args:
        country: Initiating country
        period_type: DAILY, WEEKLY, MONTHLY, or YEARLY

    Returns:
        List of dates with summaries
    """
    engine = get_engine()

    query = text("""
        SELECT DISTINCT period_start
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = :period_type
          AND is_deleted = false
        ORDER BY period_start DESC
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'country': country,
            'period_type': period_type
        })
        return [row[0] for row in result]


def get_daily_summaries_by_date(
    country: str,
    target_date: date,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get all daily summaries for a country on a specific date.

    Args:
        country: Initiating country
        target_date: Date to query
        limit: Optional limit on number of results

    Returns:
        List of summary dictionaries with all fields
    """
    engine = get_engine()

    query_text = """
        SELECT
            id,
            event_name,
            period_start,
            period_end,
            total_documents_across_sources,
            narrative_summary,
            count_by_category,
            count_by_recipient,
            created_at
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = 'DAILY'
          AND period_start = :target_date
          AND is_deleted = false
        ORDER BY total_documents_across_sources DESC
    """

    if limit:
        query_text += f" LIMIT {limit}"

    query = text(query_text)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'country': country,
            'target_date': target_date
        })

        summaries = []
        for row in result:
            summaries.append({
                'id': str(row[0]),
                'event_name': row[1],
                'period_start': row[2],
                'period_end': row[3],
                'total_documents': row[4],
                'narrative_summary': row[5],
                'count_by_category': row[6],
                'count_by_recipient': row[7],
                'created_at': row[8]
            })

        return summaries


def get_daily_summaries_by_date_range(
    country: str,
    start_date: date,
    end_date: date,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get all daily summaries for a country within a date range.

    Args:
        country: Initiating country
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        limit: Optional limit on total results

    Returns:
        List of summary dictionaries
    """
    engine = get_engine()

    query_text = """
        SELECT
            id,
            event_name,
            period_start,
            period_end,
            total_documents_across_sources,
            narrative_summary,
            count_by_category,
            count_by_recipient,
            created_at
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = 'DAILY'
          AND period_start >= :start_date
          AND period_start <= :end_date
          AND is_deleted = false
        ORDER BY period_start DESC, total_documents_across_sources DESC
    """

    if limit:
        query_text += f" LIMIT {limit}"

    query = text(query_text)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'country': country,
            'start_date': start_date,
            'end_date': end_date
        })

        summaries = []
        for row in result:
            summaries.append({
                'id': str(row[0]),
                'event_name': row[1],
                'period_start': row[2],
                'period_end': row[3],
                'total_documents': row[4],
                'narrative_summary': row[5],
                'count_by_category': row[6],
                'count_by_recipient': row[7],
                'created_at': row[8]
            })

        return summaries


def get_summary_statistics(
    country: str,
    start_date: date,
    end_date: date,
    period_type: str = 'DAILY'
) -> Dict[str, Any]:
    """
    Get aggregate statistics for summaries in a date range.

    Args:
        country: Initiating country
        start_date: Start date
        end_date: End date
        period_type: DAILY, WEEKLY, MONTHLY, or YEARLY

    Returns:
        Dictionary with statistics
    """
    engine = get_engine()

    query = text("""
        SELECT
            COUNT(*) as total_summaries,
            SUM(total_documents_across_sources) as total_documents,
            COUNT(DISTINCT period_start) as days_covered,
            MIN(period_start) as earliest_date,
            MAX(period_start) as latest_date
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = :period_type
          AND period_start >= :start_date
          AND period_start <= :end_date
          AND is_deleted = false
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'country': country,
            'period_type': period_type,
            'start_date': start_date,
            'end_date': end_date
        }).fetchone()

        return {
            'total_summaries': result[0] or 0,
            'total_documents': result[1] or 0,
            'days_covered': result[2] or 0,
            'earliest_date': result[3],
            'latest_date': result[4]
        }


def search_summaries(
    country: str,
    search_term: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Search summaries by event name or content.

    Args:
        country: Initiating country
        search_term: Search term (searches event name and narrative)
        start_date: Optional start date filter
        end_date: Optional end date filter
        limit: Maximum results

    Returns:
        List of matching summaries
    """
    engine = get_engine()

    # Build query with optional date filters
    where_clauses = [
        "initiating_country = :country",
        "period_type = 'DAILY'",
        "is_deleted = false",
        "(LOWER(event_name) LIKE LOWER(:search_term) OR " +
        "LOWER(narrative_summary->>'overview') LIKE LOWER(:search_term) OR " +
        "LOWER(narrative_summary->>'outcomes') LIKE LOWER(:search_term))"
    ]

    params = {
        'country': country,
        'search_term': f'%{search_term}%'
    }

    if start_date:
        where_clauses.append("period_start >= :start_date")
        params['start_date'] = start_date

    if end_date:
        where_clauses.append("period_start <= :end_date")
        params['end_date'] = end_date

    query = text(f"""
        SELECT
            id,
            event_name,
            period_start,
            period_end,
            total_documents_across_sources,
            narrative_summary,
            count_by_category,
            count_by_recipient,
            created_at
        FROM event_summaries
        WHERE {' AND '.join(where_clauses)}
        ORDER BY period_start DESC, total_documents_across_sources DESC
        LIMIT {limit}
    """)

    with engine.connect() as conn:
        result = conn.execute(query, params)

        summaries = []
        for row in result:
            summaries.append({
                'id': str(row[0]),
                'event_name': row[1],
                'period_start': row[2],
                'period_end': row[3],
                'total_documents': row[4],
                'narrative_summary': row[5],
                'count_by_category': row[6],
                'count_by_recipient': row[7],
                'created_at': row[8]
            })

        return summaries


def get_top_events_by_period(
    country: str,
    start_date: date,
    end_date: date,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get top events by document count for a time period.

    Args:
        country: Initiating country
        start_date: Start date
        end_date: End date
        limit: Number of top events to return

    Returns:
        List of top events with their summaries
    """
    engine = get_engine()

    query = text("""
        SELECT
            event_name,
            COUNT(*) as days_mentioned,
            SUM(total_documents_across_sources) as total_documents,
            MIN(period_start) as first_date,
            MAX(period_start) as last_date
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = 'DAILY'
          AND period_start >= :start_date
          AND period_start <= :end_date
          AND is_deleted = false
        GROUP BY event_name
        ORDER BY total_documents DESC
        LIMIT :limit
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'country': country,
            'start_date': start_date,
            'end_date': end_date,
            'limit': limit
        })

        events = []
        for row in result:
            events.append({
                'event_name': row[0],
                'days_mentioned': row[1],
                'total_documents': row[2],
                'first_date': row[3],
                'last_date': row[4]
            })

        return events
