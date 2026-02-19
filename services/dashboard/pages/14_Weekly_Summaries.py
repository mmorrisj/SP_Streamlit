"""
Weekly Event Summaries Dashboard

Browse and explore AP-style weekly summaries of soft power events synthesized from
daily summaries with progression tracking.
"""

import streamlit as st
from datetime import date, timedelta
from typing import List, Dict, Optional, Any
from shared.utils.utils import Config
from queries.summary_queries import (
    get_available_summary_dates,
    get_summary_statistics
)
from sqlalchemy import text
from shared.database.database import get_engine


# Local query functions for WEEKLY period_type

def get_weekly_summaries_by_date_range(
    country: str,
    start_date: date,
    end_date: date,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Get all weekly summaries for a country within a date range."""
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
            created_at,
            first_observed_date,
            last_observed_date
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = 'WEEKLY'
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
                'total_documents': row[4] or 0,
                'narrative_summary': row[5],
                'count_by_category': row[6],
                'count_by_recipient': row[7],
                'created_at': row[8],
                'first_observed_date': row[9],
                'last_observed_date': row[10]
            })

        return summaries


def search_weekly_summaries(
    country: str,
    search_term: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Search weekly summaries by event name or content."""
    engine = get_engine()

    where_clauses = [
        "initiating_country = :country",
        "period_type = 'WEEKLY'",
        "is_deleted = false",
        "(LOWER(event_name) LIKE LOWER(:search_term) OR "
        "LOWER(narrative_summary->>'overview') LIKE LOWER(:search_term) OR "
        "LOWER(narrative_summary->>'outcomes') LIKE LOWER(:search_term) OR "
        "LOWER(narrative_summary->>'progression') LIKE LOWER(:search_term))"
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
            created_at,
            first_observed_date,
            last_observed_date
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
                'total_documents': row[4] or 0,
                'narrative_summary': row[5],
                'count_by_category': row[6],
                'count_by_recipient': row[7],
                'created_at': row[8],
                'first_observed_date': row[9],
                'last_observed_date': row[10]
            })

        return summaries


def get_top_weekly_events(
    country: str,
    start_date: date,
    end_date: date,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get top weekly events by document count for a time period."""
    engine = get_engine()

    query = text("""
        SELECT
            event_name,
            COUNT(*) as weeks_mentioned,
            SUM(total_documents_across_sources) as total_documents,
            MIN(period_start) as first_date,
            MAX(period_start) as last_date
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = 'WEEKLY'
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
                'weeks_mentioned': row[1],
                'total_documents': row[2],
                'first_date': row[3],
                'last_date': row[4]
            })

        return events


# Display helper functions

def display_weekly_summary_content(summary: dict):
    """Display the content of a weekly summary."""

    narrative = summary['narrative_summary']

    # Overview section
    if 'overview' in narrative:
        st.markdown("### Overview")
        st.markdown(narrative['overview'])

    # Outcomes section
    if 'outcomes' in narrative:
        st.markdown("### Outcomes")
        st.markdown(narrative['outcomes'])

    # Progression section (weekly-specific)
    if 'progression' in narrative:
        st.markdown("### Progression")
        st.markdown(narrative['progression'])

    # Timeline information
    st.markdown("---")
    st.markdown("### Event Timeline")

    col1, col2 = st.columns(2)
    with col1:
        if summary.get('first_observed_date'):
            st.markdown(f"**First Observed:** {summary['first_observed_date'].strftime('%B %d, %Y')}")
        if summary.get('period_start'):
            st.markdown(f"**Week Starting:** {summary['period_start'].strftime('%B %d, %Y')}")
    with col2:
        if summary.get('last_observed_date'):
            st.markdown(f"**Last Observed:** {summary['last_observed_date'].strftime('%B %d, %Y')}")
        if summary.get('period_end'):
            st.markdown(f"**Week Ending:** {summary['period_end'].strftime('%B %d, %Y')}")

    # Metadata section
    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        # Categories
        if summary['count_by_category']:
            st.markdown("**Categories:**")
            categories = sorted(
                summary['count_by_category'].items(),
                key=lambda x: x[1],
                reverse=True
            )
            for cat, count in categories[:5]:  # Top 5
                st.markdown(f"- {cat} ({count})")

    with col2:
        # Recipients
        if summary['count_by_recipient']:
            st.markdown("**Recipients:**")
            recipients = sorted(
                summary['count_by_recipient'].items(),
                key=lambda x: x[1],
                reverse=True
            )
            for recipient, count in recipients[:5]:  # Top 5
                st.markdown(f"- {recipient} ({count})")

    # Source section
    st.markdown("### Sources")

    doc_count = summary['total_documents']

    # Source link
    if 'source_link' in narrative and narrative['source_link']:
        st.markdown(f"[View all {narrative.get('source_count', doc_count)} source documents in ATOM]({narrative['source_link']})")

    # Citations (collapsible)
    if 'citations' in narrative and narrative['citations']:
        with st.expander(f"View Citations ({len(narrative['citations'])} shown)"):
            for i, citation in enumerate(narrative['citations'], 1):
                st.markdown(f"{i}. {citation}")

    # Metadata footer
    st.markdown("---")
    st.caption(
        f"Generated: {summary['created_at'].strftime('%Y-%m-%d %H:%M UTC')} | "
        f"Summary ID: {summary['id'][:8]}..."
    )


def display_weekly_summary_card(summary: dict):
    """Display a weekly summary as an expandable card."""

    event_name = summary['event_name']
    doc_count = summary['total_documents']

    # Show week date range in the card header
    week_start = summary['period_start'].strftime('%b %d')
    if summary.get('period_end'):
        week_end = summary['period_end'].strftime('%b %d, %Y')
        week_label = f"{week_start} - {week_end}"
    else:
        week_label = f"Week of {summary['period_start'].strftime('%b %d, %Y')}"

    with st.expander(
        f"**{event_name}** ({week_label} - {doc_count} article{'s' if doc_count != 1 else ''})",
        expanded=False
    ):
        display_weekly_summary_content(summary)


# Page configuration
st.set_page_config(
    page_title="Weekly Event Summaries",
    page_icon="📅",
    layout="wide"
)

st.title("📅 Weekly Event Summaries")
st.markdown("*AP-style weekly summaries synthesized from daily reports with progression tracking*")

# Load config
cfg = Config.from_yaml('shared/config/config.yaml')

# Sidebar filters
st.sidebar.header("Filters")

# Country selection
country = st.sidebar.selectbox(
    "Select Country",
    options=cfg.influencers,
    index=cfg.influencers.index("China") if "China" in cfg.influencers else 0
)

# Get available dates for the country
available_dates = get_available_summary_dates(country, 'WEEKLY')

if not available_dates:
    st.warning(f"No weekly summaries available for {country}. Please generate weekly summaries first.")
    st.stop()

# Set default date range to available dates
min_date = min(available_dates)
max_date = max(available_dates)

# Date range selection
col1, col2 = st.sidebar.columns(2)

with col1:
    start_date = st.date_input(
        "Start Date",
        value=max_date - timedelta(weeks=4),  # Default to last 4 weeks
        min_value=min_date,
        max_value=max_date
    )

with col2:
    end_date = st.date_input(
        "End Date",
        value=max_date,
        min_value=min_date,
        max_value=max_date
    )

# Search box
search_term = st.sidebar.text_input(
    "Search Summaries",
    placeholder="Enter event name or keywords..."
)

# Display mode
display_mode = st.sidebar.radio(
    "Display Mode",
    options=["By Week", "Top Events", "Search Results"],
    index=0
)

# Statistics section
st.sidebar.markdown("---")
st.sidebar.subheader("Statistics")

stats = get_summary_statistics(country, start_date, end_date, 'WEEKLY')

st.sidebar.metric("Total Summaries", f"{stats['total_summaries']:,}")
st.sidebar.metric("Total Documents", f"{stats['total_documents']:,}")
st.sidebar.metric("Weeks Covered", stats['days_covered'])

# Main content area
st.markdown("---")

# Display based on mode
if display_mode == "Search Results" and search_term:
    st.subheader(f"Search Results for '{search_term}'")

    results = search_weekly_summaries(
        country=country,
        search_term=search_term,
        start_date=start_date,
        end_date=end_date,
        limit=50
    )

    if not results:
        st.info("No results found. Try different keywords.")
    else:
        st.info(f"Found {len(results)} matching summaries")

        for summary in results:
            display_weekly_summary_card(summary)

elif display_mode == "Top Events":
    st.subheader(f"Top Events: {start_date} to {end_date}")

    top_events = get_top_weekly_events(
        country=country,
        start_date=start_date,
        end_date=end_date,
        limit=20
    )

    if not top_events:
        st.info("No events found in this date range.")
    else:
        st.markdown(f"**Showing top {len(top_events)} events by document volume**")

        for i, event in enumerate(top_events, 1):
            with st.expander(
                f"#{i} **{event['event_name']}** "
                f"({event['total_documents']} docs across {event['weeks_mentioned']} week{'s' if event['weeks_mentioned'] != 1 else ''})"
            ):
                st.markdown(f"**First mentioned:** {event['first_date'].strftime('%B %d, %Y')}")
                st.markdown(f"**Last mentioned:** {event['last_date'].strftime('%B %d, %Y')}")
                st.markdown(f"**Total documents:** {event['total_documents']:,}")
                st.markdown(f"**Weeks active:** {event['weeks_mentioned']}")

                # Get one sample summary for this event
                sample_summaries = search_weekly_summaries(
                    country=country,
                    search_term=event['event_name'],
                    start_date=start_date,
                    end_date=end_date,
                    limit=1
                )

                if sample_summaries:
                    summary = sample_summaries[0]
                    st.markdown("---")
                    week_label = summary['period_start'].strftime('%B %d, %Y')
                    st.markdown(f"**Sample Summary (Week of {week_label}):**")
                    display_weekly_summary_content(summary)

else:  # By Week mode
    st.subheader(f"{country} Weekly Summaries: {start_date} to {end_date}")

    # Get all summaries in date range
    summaries = get_weekly_summaries_by_date_range(
        country=country,
        start_date=start_date,
        end_date=end_date
    )

    if not summaries:
        st.info(f"No weekly summaries found for {country} between {start_date} and {end_date}.")
    else:
        # Group by week (period_start)
        weeks_with_summaries = {}
        for summary in summaries:
            week_key = summary['period_start']
            if week_key not in weeks_with_summaries:
                weeks_with_summaries[week_key] = []
            weeks_with_summaries[week_key].append(summary)

        # Display by week (most recent first)
        for week_date in sorted(weeks_with_summaries.keys(), reverse=True):
            week_summaries = weeks_with_summaries[week_date]

            # Calculate week end date for display
            week_end = week_date + timedelta(days=6)
            st.markdown(f"## Week of {week_date.strftime('%B %d')} - {week_end.strftime('%B %d, %Y')}")
            st.markdown(f"*{len(week_summaries)} events reported*")

            for summary in week_summaries:
                display_weekly_summary_card(summary)

            st.markdown("---")


# Help section at bottom
with st.expander("ℹ️ About Weekly Summaries"):
    st.markdown(f"""
    ### What are Weekly Summaries?

    Weekly summaries are **AP-style narrative summaries** that synthesize multiple daily summaries
    into a coherent weekly narrative. Each summary provides:

    - **Overview:** What happened across the week, with source attribution
    - **Outcomes:** Cumulative results and concrete actions taken
    - **Progression:** How the situation evolved day-by-day throughout the week

    ### Structure

    Weekly summaries are built hierarchically:
    1. **Daily Summaries** - Factual reports of daily events
    2. **Weekly Summaries** - Synthesized from 2+ daily summaries for the same event

    ### Key Features

    - **Temporal Tracking:** First and last observed dates show event duration
    - **Category Analysis:** Top categories show event classification patterns
    - **Recipient Analysis:** Top recipients show geographic distribution
    - **Source Traceability:** All summaries link back to original documents via citations

    ### How to Use

    - **By Week:** Browse summaries chronologically by week
    - **Top Events:** See the most covered events by document volume
    - **Search:** Find specific events or topics across all weekly summaries

    ### Data Quality

    - Currently covering {stats['days_covered']} weeks of data
    - Total of {stats['total_summaries']:,} weekly event summaries
    - Based on {stats['total_documents']:,} source documents
    - Each summary synthesizes multiple daily reports
    """)
