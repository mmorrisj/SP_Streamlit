"""
Query functions for master events and canonical events dashboard.
"""
import pandas as pd
import streamlit as st
from sqlalchemy import func, desc, text
from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml()


@st.cache_data
def get_master_event_overview(start_date='2024-08-01', end_date='2024-08-31'):
    """
    Get overview statistics for master events.

    Returns:
        DataFrame with total master events, total child events, total articles, date range
    """
    query = text("""
        SELECT
            COUNT(DISTINCT m.id) as master_event_count,
            COUNT(DISTINCT c.id) as child_event_count,
            SUM(m.total_articles) as total_articles,
            MIN(m.first_mention_date) as earliest_date,
            MAX(m.last_mention_date) as latest_date
        FROM canonical_events m
        LEFT JOIN canonical_events c ON c.master_event_id = m.id
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
    """)

    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn, params={'start_date': start_date, 'end_date': end_date})
    return df


@st.cache_data
def get_top_master_events(
    limit=20,
    country=None,
    start_date='2024-08-01',
    end_date='2024-08-31'
):
    """
    Get top master events by article count.

    Args:
        limit: Number of events to return
        country: Optional filter by initiating country
        start_date: Start date filter
        end_date: End date filter

    Returns:
        DataFrame with master event details
    """
    query = """
        SELECT
            m.canonical_name,
            m.initiating_country,
            m.first_mention_date,
            m.last_mention_date,
            m.total_articles,
            COUNT(DISTINCT c.id) as child_count,
            (m.last_mention_date - m.first_mention_date) + 1 as days_span
        FROM canonical_events m
        LEFT JOIN canonical_events c ON c.master_event_id = m.id
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
    """

    params = {'start_date': start_date, 'end_date': end_date, 'limit': limit}

    if country and country != 'ALL':
        query += " AND m.initiating_country = :country"
        params['country'] = country

    query += """
        GROUP BY m.id, m.canonical_name, m.initiating_country,
                 m.first_mention_date, m.last_mention_date, m.total_articles
        ORDER BY m.total_articles DESC
        LIMIT :limit
    """

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    return df


@st.cache_data
def get_events_by_country(start_date='2024-08-01', end_date='2024-08-31'):
    """
    Get master event counts and article volumes by initiating country.

    Returns:
        DataFrame with country, master_event_count, total_articles
    """
    query = text("""
        SELECT
            m.initiating_country,
            COUNT(DISTINCT m.id) as master_event_count,
            COUNT(DISTINCT c.id) as child_event_count,
            SUM(m.total_articles) as total_articles
        FROM canonical_events m
        LEFT JOIN canonical_events c ON c.master_event_id = m.id
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
        GROUP BY m.initiating_country
        ORDER BY total_articles DESC
    """)

    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn, params={'start_date': start_date, 'end_date': end_date})
    return df


@st.cache_data
def get_temporal_trends(
    country=None,
    start_date='2024-08-01',
    end_date='2024-08-31'
):
    """
    Get daily article counts for master events over time.

    Args:
        country: Optional filter by initiating country
        start_date: Start date
        end_date: End date

    Returns:
        DataFrame with date, article_count
    """
    query = """
        SELECT
            dem.mention_date as date,
            SUM(dem.article_count) as article_count,
            COUNT(DISTINCT c.id) as event_count
        FROM canonical_events m
        JOIN canonical_events c ON c.master_event_id = m.id
        JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
        WHERE m.master_event_id IS NULL
          AND dem.mention_date >= :start_date
          AND dem.mention_date <= :end_date
    """

    params = {'start_date': start_date, 'end_date': end_date}

    if country and country != 'ALL':
        query += " AND m.initiating_country = :country"
        params['country'] = country

    query += """
        GROUP BY dem.mention_date
        ORDER BY dem.mention_date
    """

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)

    # Convert date to datetime
    df['date'] = pd.to_datetime(df['date'])
    return df


@st.cache_data
def get_recipient_impact(
    recipient_countries,
    start_date='2024-08-01',
    end_date='2024-08-31'
):
    """
    Get master events targeting specific recipient countries.

    Args:
        recipient_countries: List of recipient countries from config
        start_date: Start date
        end_date: End date

    Returns:
        DataFrame with recipient analysis
    """
    # Use parameterized query for recipient countries
    # Build placeholders for IN clause
    placeholders = ', '.join([f':recipient_{i}' for i in range(len(recipient_countries))])

    query = f"""
        SELECT
            recipient,
            m.initiating_country,
            COUNT(DISTINCT m.id) as master_event_count,
            SUM(m.total_articles) as total_articles
        FROM canonical_events m,
        jsonb_array_elements_text(m.primary_recipients) as recipient
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
          AND recipient IN ({placeholders})
        GROUP BY recipient, m.initiating_country
        ORDER BY total_articles DESC
    """

    # Build params dict with recipient values
    params = {'start_date': start_date, 'end_date': end_date}
    for i, country in enumerate(recipient_countries):
        params[f'recipient_{i}'] = country

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    return df


@st.cache_data
def get_category_breakdown(
    country=None,
    start_date='2024-08-01',
    end_date='2024-08-31'
):
    """
    Get master events by category.

    Args:
        country: Optional filter by initiating country
        start_date: Start date
        end_date: End date

    Returns:
        DataFrame with category, event_count, article_count
    """
    query = """
        SELECT
            category,
            COUNT(DISTINCT m.id) as master_event_count,
            SUM(m.total_articles) as total_articles
        FROM canonical_events m,
        jsonb_array_elements_text(m.primary_categories) as category
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
    """

    params = {'start_date': start_date, 'end_date': end_date}

    if country and country != 'ALL':
        query += " AND m.initiating_country = :country"
        params['country'] = country

    query += """
        GROUP BY category
        ORDER BY total_articles DESC
    """

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    return df


@st.cache_data
def get_master_event_details(master_event_name, country=None):
    """
    Get detailed information about a specific master event including child events.

    Args:
        master_event_name: Name of the master event
        country: Optional country filter

    Returns:
        Tuple of (master_info_df, child_events_df)
    """
    # Get master event info
    master_query = text("""
        SELECT
            m.canonical_name,
            m.initiating_country,
            m.first_mention_date,
            m.last_mention_date,
            m.total_articles,
            m.total_mention_days,
            m.primary_categories,
            m.primary_recipients,
            (m.last_mention_date - m.first_mention_date) + 1 as days_span
        FROM canonical_events m
        WHERE m.master_event_id IS NULL
          AND m.canonical_name = :event_name
    """)

    params = {'event_name': master_event_name}

    if country:
        master_query = text(str(master_query) + " AND m.initiating_country = :country")
        params['country'] = country

    # Get child events
    child_query = text("""
        SELECT
            c.canonical_name,
            c.first_mention_date,
            c.last_mention_date,
            c.total_articles,
            c.total_mention_days
        FROM canonical_events m
        JOIN canonical_events c ON c.master_event_id = m.id
        WHERE m.master_event_id IS NULL
          AND m.canonical_name = :event_name
        ORDER BY c.total_articles DESC
    """)

    with get_engine().connect() as conn:
        master_df = pd.read_sql(master_query, conn, params=params)
        child_df = pd.read_sql(child_query, conn, params={'event_name': master_event_name})

    return master_df, child_df


@st.cache_data
def get_master_event_timeline(master_event_name):
    """
    Get daily timeline for a master event showing all child event mentions.

    Args:
        master_event_name: Name of the master event

    Returns:
        DataFrame with date, event_name, article_count, doc_count
    """
    query = text("""
        SELECT
            dem.mention_date as date,
            c.canonical_name as event_name,
            dem.article_count,
            array_length(dem.doc_ids, 1) as doc_count
        FROM canonical_events m
        JOIN canonical_events c ON c.master_event_id = m.id
        JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
        WHERE m.master_event_id IS NULL
          AND m.canonical_name = :event_name
        ORDER BY dem.mention_date, dem.article_count DESC
    """)

    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn, params={'event_name': master_event_name})

    df['date'] = pd.to_datetime(df['date'])
    return df


@st.cache_data
def get_standalone_canonical_events(
    country=None,
    limit=20,
    start_date='2024-08-01',
    end_date='2024-08-31'
):
    """
    Get canonical events that are NOT part of any master event.

    Args:
        country: Optional filter by initiating country
        limit: Number of events to return
        start_date: Start date filter
        end_date: End date filter

    Returns:
        DataFrame with standalone canonical event details
    """
    query = """
        SELECT
            canonical_name,
            initiating_country,
            first_mention_date,
            last_mention_date,
            total_articles,
            total_mention_days
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND id NOT IN (
              SELECT DISTINCT master_event_id
              FROM canonical_events
              WHERE master_event_id IS NOT NULL
          )
          AND first_mention_date >= :start_date
          AND first_mention_date <= :end_date
    """

    params = {'start_date': start_date, 'end_date': end_date, 'limit': limit}

    if country and country != 'ALL':
        query += " AND initiating_country = :country"
        params['country'] = country

    query += """
        ORDER BY total_articles DESC
        LIMIT :limit
    """

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    return df
