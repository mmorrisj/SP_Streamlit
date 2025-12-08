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
def get_master_event_overview(start_date='2024-08-01', end_date='2024-08-31', recipients=None):
    """
    Get overview statistics for master events.

    Filters by config.yaml lists: influencers, recipients, categories, subcategories.
    Counts only documents that match ALL filter criteria.

    Args:
        start_date: Start date filter
        end_date: End date filter
        recipients: List of recipient countries to filter by (defaults to cfg.recipients)

    Returns:
        DataFrame with total master events, total child events, total articles, date range
    """
    if recipients is None:
        recipients = cfg.recipients
    # Count distinct doc_ids from daily_event_mentions that match ALL config filters
    query = text("""
        WITH unnested_docs AS (
            SELECT DISTINCT
                unnest(dem.doc_ids) as doc_id,
                m.id as master_id
            FROM daily_event_mentions dem
            JOIN canonical_events c ON dem.canonical_event_id = c.id
            JOIN canonical_events m ON c.master_event_id = m.id OR (c.master_event_id IS NULL AND c.id = m.id)
            WHERE m.master_event_id IS NULL
              AND dem.mention_date >= :start_date
              AND dem.mention_date <= :end_date
              AND m.initiating_country = ANY(:influencers)
        ),
        filtered_docs AS (
            SELECT DISTINCT ud.doc_id
            FROM unnested_docs ud
            WHERE EXISTS (
                  SELECT 1 FROM recipient_countries rc
                  WHERE rc.doc_id = ud.doc_id
                  AND rc.recipient_country = ANY(:recipients)
              )
              AND EXISTS (
                  SELECT 1 FROM categories cat
                  WHERE cat.doc_id = ud.doc_id
                  AND cat.category = ANY(:categories)
              )
              AND EXISTS (
                  SELECT 1 FROM subcategories sub
                  WHERE sub.doc_id = ud.doc_id
                  AND sub.subcategory = ANY(:subcategories)
              )
        )
        SELECT
            COUNT(DISTINCT m.id) as master_event_count,
            (SELECT COUNT(DISTINCT c.id) FROM canonical_events c WHERE c.master_event_id IS NOT NULL
             AND c.master_event_id IN (SELECT id FROM canonical_events m2 WHERE m2.master_event_id IS NULL
                                        AND m2.first_mention_date >= :start_date
                                        AND m2.first_mention_date <= :end_date
                                        AND m2.initiating_country = ANY(:influencers))) as child_event_count,
            (SELECT COUNT(*) FROM filtered_docs) as total_articles,
            MIN(m.first_mention_date) as earliest_date,
            MAX(m.last_mention_date) as latest_date
        FROM canonical_events m
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
          AND m.initiating_country = ANY(:influencers)
    """)

    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn, params={
            'start_date': start_date,
            'end_date': end_date,
            'influencers': cfg.influencers,
            'recipients': cfg.recipients,
            'categories': cfg.categories,
            'subcategories': cfg.subcategories
        })
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

    Filters by config.yaml lists: influencers, recipients, categories, subcategories.
    Counts only documents that match ALL filter criteria.

    Args:
        limit: Number of events to return
        country: Optional filter by initiating country
        start_date: Start date filter
        end_date: End date filter

    Returns:
        DataFrame with master event details
    """
    query = """
        WITH unnested_docs AS (
            SELECT
                m.id as master_id,
                unnest(dem.doc_ids) as doc_id
            FROM canonical_events m
            LEFT JOIN canonical_events c ON c.master_event_id = m.id OR (c.master_event_id IS NULL AND c.id = m.id)
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
            WHERE m.master_event_id IS NULL
              AND dem.mention_date >= :start_date
              AND dem.mention_date <= :end_date
              AND m.initiating_country = ANY(:influencers)
    """

    params = {
        'start_date': start_date,
        'end_date': end_date,
        'limit': limit,
        'influencers': cfg.influencers,
        'recipients': cfg.recipients,
        'categories': cfg.categories,
        'subcategories': cfg.subcategories
    }

    if country and country != 'ALL':
        query += " AND m.initiating_country = :country"
        params['country'] = country

    query += """
        ),
        filtered_doc_counts AS (
            SELECT
                ud.master_id,
                COUNT(DISTINCT ud.doc_id) as filtered_article_count
            FROM unnested_docs ud
            WHERE EXISTS (
                  SELECT 1 FROM recipient_countries rc
                  WHERE rc.doc_id = ud.doc_id
                  AND rc.recipient_country = ANY(:recipients)
              )
              AND EXISTS (
                  SELECT 1 FROM categories cat
                  WHERE cat.doc_id = ud.doc_id
                  AND cat.category = ANY(:categories)
              )
              AND EXISTS (
                  SELECT 1 FROM subcategories sub
                  WHERE sub.doc_id = ud.doc_id
                  AND sub.subcategory = ANY(:subcategories)
              )
            GROUP BY ud.master_id
        )
        SELECT
            m.canonical_name,
            m.initiating_country,
            m.first_mention_date,
            m.last_mention_date,
            COALESCE(fdc.filtered_article_count, 0) as total_articles,
            COUNT(DISTINCT c.id) as child_count,
            (m.last_mention_date - m.first_mention_date) + 1 as days_span
        FROM canonical_events m
        LEFT JOIN canonical_events c ON c.master_event_id = m.id
        LEFT JOIN filtered_doc_counts fdc ON fdc.master_id = m.id
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
          AND m.initiating_country = ANY(:influencers)
        GROUP BY m.id, m.canonical_name, m.initiating_country,
                 m.first_mention_date, m.last_mention_date, fdc.filtered_article_count
        ORDER BY total_articles DESC
        LIMIT :limit
    """

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    return df


@st.cache_data
def get_events_by_country(start_date='2024-08-01', end_date='2024-08-31'):
    """
    Get master event counts and article volumes by initiating country.

    Filters by config.yaml lists: influencers, recipients, categories, subcategories.
    Counts only documents that match ALL filter criteria.

    Returns:
        DataFrame with country, master_event_count, total_articles
    """
    query = text("""
        WITH unnested_docs AS (
            SELECT
                m.id as master_id,
                m.initiating_country,
                unnest(dem.doc_ids) as doc_id
            FROM canonical_events m
            LEFT JOIN canonical_events c ON c.master_event_id = m.id OR (c.master_event_id IS NULL AND c.id = m.id)
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
            WHERE m.master_event_id IS NULL
              AND dem.mention_date >= :start_date
              AND dem.mention_date <= :end_date
              AND m.initiating_country = ANY(:influencers)
        ),
        filtered_doc_counts AS (
            SELECT
                ud.master_id,
                ud.initiating_country,
                COUNT(DISTINCT ud.doc_id) as filtered_article_count
            FROM unnested_docs ud
            WHERE EXISTS (
                  SELECT 1 FROM recipient_countries rc
                  WHERE rc.doc_id = ud.doc_id
                  AND rc.recipient_country = ANY(:recipients)
              )
              AND EXISTS (
                  SELECT 1 FROM categories cat
                  WHERE cat.doc_id = ud.doc_id
                  AND cat.category = ANY(:categories)
              )
              AND EXISTS (
                  SELECT 1 FROM subcategories sub
                  WHERE sub.doc_id = ud.doc_id
                  AND sub.subcategory = ANY(:subcategories)
              )
            GROUP BY ud.master_id, ud.initiating_country
        )
        SELECT
            m.initiating_country,
            COUNT(DISTINCT m.id) as master_event_count,
            COUNT(DISTINCT c.id) as child_event_count,
            COALESCE(SUM(fdc.filtered_article_count), 0) as total_articles
        FROM canonical_events m
        LEFT JOIN canonical_events c ON c.master_event_id = m.id
        LEFT JOIN filtered_doc_counts fdc ON fdc.master_id = m.id
        WHERE m.master_event_id IS NULL
          AND m.first_mention_date >= :start_date
          AND m.first_mention_date <= :end_date
          AND m.initiating_country = ANY(:influencers)
        GROUP BY m.initiating_country
        ORDER BY total_articles DESC
    """)

    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn, params={
            'start_date': start_date,
            'end_date': end_date,
            'influencers': cfg.influencers,
            'recipients': cfg.recipients,
            'categories': cfg.categories,
            'subcategories': cfg.subcategories
        })
    return df


@st.cache_data
def get_temporal_trends(
    country=None,
    start_date='2024-08-01',
    end_date='2024-08-31'
):
    """
    Get daily article counts for master events over time.

    Filters by config.yaml lists: influencers, recipients, categories, subcategories.
    Counts only documents that match ALL filter criteria.

    Args:
        country: Optional filter by initiating country
        start_date: Start date
        end_date: End date

    Returns:
        DataFrame with date, article_count
    """
    query = """
        WITH unnested_docs AS (
            SELECT
                dem.mention_date,
                c.id as event_id,
                unnest(dem.doc_ids) as doc_id
            FROM canonical_events m
            JOIN canonical_events c ON c.master_event_id = m.id OR (c.master_event_id IS NULL AND c.id = m.id)
            JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
            WHERE m.master_event_id IS NULL
              AND dem.mention_date >= :start_date
              AND dem.mention_date <= :end_date
              AND m.initiating_country = ANY(:influencers)
    """

    params = {
        'start_date': start_date,
        'end_date': end_date,
        'influencers': cfg.influencers,
        'recipients': cfg.recipients,
        'categories': cfg.categories,
        'subcategories': cfg.subcategories
    }

    if country and country != 'ALL':
        query += " AND m.initiating_country = :country"
        params['country'] = country

    query += """
        ),
        filtered_daily_counts AS (
            SELECT
                ud.mention_date,
                COUNT(DISTINCT ud.doc_id) as filtered_article_count,
                COUNT(DISTINCT ud.event_id) as event_count
            FROM unnested_docs ud
            WHERE EXISTS (
                  SELECT 1 FROM recipient_countries rc
                  WHERE rc.doc_id = ud.doc_id
                  AND rc.recipient_country = ANY(:recipients)
              )
              AND EXISTS (
                  SELECT 1 FROM categories cat
                  WHERE cat.doc_id = ud.doc_id
                  AND cat.category = ANY(:categories)
              )
              AND EXISTS (
                  SELECT 1 FROM subcategories sub
                  WHERE sub.doc_id = ud.doc_id
                  AND sub.subcategory = ANY(:subcategories)
              )
            GROUP BY ud.mention_date
        )
        SELECT
            mention_date as date,
            filtered_article_count as article_count,
            event_count
        FROM filtered_daily_counts
        ORDER BY mention_date
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

    Filters by config.yaml lists: influencers, recipients, categories, subcategories.
    Counts only documents that match ALL filter criteria.

    Args:
        recipient_countries: List of recipient countries from config
        start_date: Start date
        end_date: End date

    Returns:
        DataFrame with recipient analysis
    """
    # Count filtered docs per master event and recipient from flattened table
    query = text("""
        WITH unnested_docs AS (
            SELECT
                m.id as master_id,
                m.initiating_country,
                unnest(dem.doc_ids) as doc_id
            FROM canonical_events m
            LEFT JOIN canonical_events c ON c.master_event_id = m.id OR (c.master_event_id IS NULL AND c.id = m.id)
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
            WHERE m.master_event_id IS NULL
              AND dem.mention_date >= :start_date
              AND dem.mention_date <= :end_date
              AND m.initiating_country = ANY(:influencers)
        ),
        filtered_doc_counts AS (
            SELECT
                ud.master_id,
                ud.initiating_country,
                rc.recipient_country,
                COUNT(DISTINCT ud.doc_id) as filtered_article_count
            FROM unnested_docs ud
            JOIN recipient_countries rc ON rc.doc_id = ud.doc_id
            WHERE rc.recipient_country = ANY(:recipients)
              AND EXISTS (
                  SELECT 1 FROM categories cat
                  WHERE cat.doc_id = ud.doc_id
                  AND cat.category = ANY(:categories)
              )
              AND EXISTS (
                  SELECT 1 FROM subcategories sub
                  WHERE sub.doc_id = ud.doc_id
                  AND sub.subcategory = ANY(:subcategories)
              )
            GROUP BY ud.master_id, ud.initiating_country, rc.recipient_country
        )
        SELECT
            recipient_country as recipient,
            initiating_country,
            COUNT(DISTINCT master_id) as master_event_count,
            SUM(filtered_article_count) as total_articles
        FROM filtered_doc_counts
        GROUP BY recipient_country, initiating_country
        ORDER BY total_articles DESC
    """)

    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn, params={
            'start_date': start_date,
            'end_date': end_date,
            'influencers': cfg.influencers,
            'recipients': cfg.recipients,
            'categories': cfg.categories,
            'subcategories': cfg.subcategories
        })
    return df


@st.cache_data
def get_category_breakdown(
    country=None,
    start_date='2024-08-01',
    end_date='2024-08-31'
):
    """
    Get master events by category.

    Filters by config.yaml lists: influencers, recipients, categories, subcategories.
    Counts only documents that match ALL filter criteria.

    Args:
        country: Optional filter by initiating country
        start_date: Start date
        end_date: End date

    Returns:
        DataFrame with category, event_count, article_count
    """
    # Count filtered docs per master event and category from flattened table
    query = """
        WITH unnested_docs AS (
            SELECT
                m.id as master_id,
                unnest(dem.doc_ids) as doc_id
            FROM canonical_events m
            LEFT JOIN canonical_events c ON c.master_event_id = m.id OR (c.master_event_id IS NULL AND c.id = m.id)
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
            WHERE m.master_event_id IS NULL
              AND dem.mention_date >= :start_date
              AND dem.mention_date <= :end_date
              AND m.initiating_country = ANY(:influencers)
    """

    params = {
        'start_date': start_date,
        'end_date': end_date,
        'influencers': cfg.influencers,
        'recipients': cfg.recipients,
        'categories': cfg.categories,
        'subcategories': cfg.subcategories
    }

    if country and country != 'ALL':
        query += " AND m.initiating_country = :country"
        params['country'] = country

    query += """
        ),
        filtered_doc_counts AS (
            SELECT
                ud.master_id,
                cat.category,
                COUNT(DISTINCT ud.doc_id) as filtered_article_count
            FROM unnested_docs ud
            JOIN categories cat ON cat.doc_id = ud.doc_id
            WHERE cat.category = ANY(:categories)
              AND EXISTS (
                  SELECT 1 FROM recipient_countries rc
                  WHERE rc.doc_id = ud.doc_id
                  AND rc.recipient_country = ANY(:recipients)
              )
              AND EXISTS (
                  SELECT 1 FROM subcategories sub
                  WHERE sub.doc_id = ud.doc_id
                  AND sub.subcategory = ANY(:subcategories)
              )
            GROUP BY ud.master_id, cat.category
        )
        SELECT
            category,
            COUNT(DISTINCT master_id) as master_event_count,
            SUM(filtered_article_count) as total_articles
        FROM filtered_doc_counts
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

    Filters by config.yaml lists: influencers, recipients, categories, subcategories.
    Counts only documents that match ALL filter criteria.

    Args:
        country: Optional filter by initiating country
        limit: Number of events to return
        start_date: Start date filter
        end_date: End date filter

    Returns:
        DataFrame with standalone canonical event details
    """
    query = """
        WITH standalone_events AS (
            SELECT ce.id, ce.canonical_name, ce.initiating_country,
                   ce.first_mention_date, ce.last_mention_date, ce.total_mention_days
            FROM canonical_events ce
            WHERE ce.master_event_id IS NULL
              AND ce.id NOT IN (
                  SELECT DISTINCT master_event_id
                  FROM canonical_events
                  WHERE master_event_id IS NOT NULL
              )
              AND ce.first_mention_date >= :start_date
              AND ce.first_mention_date <= :end_date
              AND ce.initiating_country = ANY(:influencers)
        ),
        unnested_docs AS (
            SELECT
                se.id as event_id,
                unnest(dem.doc_ids) as doc_id
            FROM standalone_events se
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = se.id
            WHERE dem.mention_date >= :start_date
              AND dem.mention_date <= :end_date
        ),
        filtered_doc_counts AS (
            SELECT
                ud.event_id,
                COUNT(DISTINCT ud.doc_id) as filtered_article_count
            FROM unnested_docs ud
            WHERE EXISTS (
                  SELECT 1 FROM recipient_countries rc
                  WHERE rc.doc_id = ud.doc_id
                  AND rc.recipient_country = ANY(:recipients)
              )
              AND EXISTS (
                  SELECT 1 FROM categories cat
                  WHERE cat.doc_id = ud.doc_id
                  AND cat.category = ANY(:categories)
              )
              AND EXISTS (
                  SELECT 1 FROM subcategories sub
                  WHERE sub.doc_id = ud.doc_id
                  AND sub.subcategory = ANY(:subcategories)
              )
            GROUP BY ud.event_id
        )
        SELECT
            se.canonical_name,
            se.initiating_country,
            se.first_mention_date,
            se.last_mention_date,
            COALESCE(fdc.filtered_article_count, 0) as total_articles,
            se.total_mention_days
        FROM standalone_events se
        LEFT JOIN filtered_doc_counts fdc ON fdc.event_id = se.id
    """

    params = {
        'start_date': start_date,
        'end_date': end_date,
        'limit': limit,
        'influencers': cfg.influencers,
        'recipients': cfg.recipients,
        'categories': cfg.categories,
        'subcategories': cfg.subcategories
    }

    if country and country != 'ALL':
        query += " WHERE se.initiating_country = :country"
        params['country'] = country

    query += """
        ORDER BY total_articles DESC
        LIMIT :limit
    """

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    return df
