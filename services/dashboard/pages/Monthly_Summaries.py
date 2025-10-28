"""
Monthly Event Summaries Dashboard

Browse and explore AP-style monthly summaries of soft power events synthesized from
weekly summaries with strategic analysis.
"""

import streamlit as st
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from shared.utils.utils import Config
from queries.summary_queries import (
    get_available_summary_dates,
    get_summary_statistics
)
from sqlalchemy import text
from shared.database.database import get_engine


# Helper functions for monthly summaries
def get_monthly_summaries_by_date_range(
    country: str,
    start_date: date,
    end_date: date
):
    """Get all monthly summaries for a country within a date range."""
    engine = get_engine()

    query = text("""
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
          AND period_type = 'MONTHLY'
          AND period_start >= :start_date
          AND period_start <= :end_date
          AND is_deleted = false
        ORDER BY period_start DESC, total_documents_across_sources DESC
    """)

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


def search_monthly_summaries(
    country: str,
    search_term: str,
    start_date: date = None,
    end_date: date = None,
    limit: int = 50
):
    """Search monthly summaries by event name or content."""
    engine = get_engine()

    where_clauses = [
        "initiating_country = :country",
        "period_type = 'MONTHLY'",
        "is_deleted = false",
        "(LOWER(event_name) LIKE LOWER(:search_term) OR " +
        "LOWER(narrative_summary->>'monthly_overview') LIKE LOWER(:search_term) OR " +
        "LOWER(narrative_summary->>'key_outcomes') LIKE LOWER(:search_term) OR " +
        "LOWER(narrative_summary->>'strategic_significance') LIKE LOWER(:search_term))"
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


def display_monthly_summary_content(summary: dict):
    """Display the content of a monthly summary."""

    narrative = summary['narrative_summary']

    # Monthly Overview section
    if 'monthly_overview' in narrative:
        st.markdown("### Monthly Overview")
        st.markdown(narrative['monthly_overview'])

    # Key Outcomes section
    if 'key_outcomes' in narrative:
        st.markdown("### Key Outcomes")
        st.markdown(narrative['key_outcomes'])

    # Strategic Significance section
    if 'strategic_significance' in narrative:
        st.markdown("### Strategic Significance")
        st.markdown(narrative['strategic_significance'])

    # Timeline information
    st.markdown("---")
    st.markdown("### Event Timeline")

    col1, col2 = st.columns(2)
    with col1:
        if summary.get('first_observed_date'):
            st.markdown(f"**First Observed:** {summary['first_observed_date'].strftime('%B %d, %Y')}")
    with col2:
        if summary.get('last_observed_date'):
            st.markdown(f"**Last Observed:** {summary['last_observed_date'].strftime('%B %d, %Y')}")

    # Metadata section
    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        # Categories
        if summary['count_by_category']:
            st.markdown("**Top Categories:**")
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
            st.markdown("**Top Recipients:**")
            recipients = sorted(
                summary['count_by_recipient'].items(),
                key=lambda x: x[1],
                reverse=True
            )
            for recipient, count in recipients[:5]:  # Top 5
                st.markdown(f"- {recipient} ({count})")

    # Metadata footer
    st.markdown("---")
    st.caption(
        f"Generated: {summary['created_at'].strftime('%Y-%m-%d %H:%M UTC')} | "
        f"Summary ID: {summary['id'][:8]}..."
    )


def display_monthly_summary_card(summary: dict):
    """Display a monthly summary as an expandable card."""

    # Event name and month
    event_name = summary['event_name']
    month_year = summary['period_start'].strftime('%B %Y')

    # Duration calculation
    if summary.get('first_observed_date') and summary.get('last_observed_date'):
        days_active = (summary['last_observed_date'] - summary['first_observed_date']).days + 1
        duration_text = f"{days_active} days active"
    else:
        duration_text = "1 month"

    with st.expander(
        f"**{event_name}** ({month_year} - {duration_text})",
        expanded=False
    ):
        display_monthly_summary_content(summary)


# Page configuration
st.set_page_config(
    page_title="Monthly Event Summaries",
    page_icon="📅",
    layout="wide"
)

st.title("📅 Monthly Event Summaries")
st.markdown("*Strategic monthly summaries synthesized from weekly reports with analysis of key outcomes and significance*")

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
available_dates = get_available_summary_dates(country, 'MONTHLY')

if not available_dates:
    st.warning(f"No monthly summaries available for {country}. Please generate monthly summaries first.")
    st.stop()

# Set default date range to available dates
min_date = min(available_dates)
max_date = max(available_dates)

# Month selection (use month start dates)
col1, col2 = st.sidebar.columns(2)

with col1:
    start_date = st.date_input(
        "Start Month",
        value=min_date,
        min_value=min_date,
        max_value=max_date
    )

with col2:
    end_date = st.date_input(
        "End Month",
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
    options=["By Month", "Search Results"],
    index=0
)

# Statistics section
st.sidebar.markdown("---")
st.sidebar.subheader("Statistics")

stats = get_summary_statistics(country, start_date, end_date, 'MONTHLY')

st.sidebar.metric("Total Events", f"{stats['total_summaries']:,}")
st.sidebar.metric("Months Covered", stats['days_covered'])

# Main content area
st.markdown("---")

# Display based on mode
if display_mode == "Search Results" and search_term:
    st.subheader(f"Search Results for '{search_term}'")

    results = search_monthly_summaries(
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
            display_monthly_summary_card(summary)

else:  # By Month mode
    st.subheader(f"{country} Monthly Summaries: {start_date.strftime('%B %Y')} to {end_date.strftime('%B %Y')}")

    # Get all summaries in date range
    summaries = get_monthly_summaries_by_date_range(
        country=country,
        start_date=start_date,
        end_date=end_date
    )

    if not summaries:
        st.info(f"No monthly summaries found for {country} in this date range.")
    else:
        # Group by month
        months_with_summaries = {}
        for summary in summaries:
            month_key = summary['period_start']
            if month_key not in months_with_summaries:
                months_with_summaries[month_key] = []
            months_with_summaries[month_key].append(summary)

        # Display by month (most recent first)
        for month_date in sorted(months_with_summaries.keys(), reverse=True):
            month_summaries = months_with_summaries[month_date]

            st.markdown(f"## {month_date.strftime('%B %Y')}")
            st.markdown(f"*{len(month_summaries)} events tracked this month*")

            for summary in month_summaries:
                display_monthly_summary_card(summary)

            st.markdown("---")


# Help section at bottom
with st.expander("ℹ️ About Monthly Summaries"):
    st.markdown(f"""
    ### What are Monthly Summaries?

    Monthly summaries are **strategic AP-style summaries** that synthesize multiple weekly summaries
    into a comprehensive monthly narrative. Each summary provides:

    - **Monthly Overview:** High-level summary of the event's progression throughout the month
    - **Key Outcomes:** Concrete results, milestones, and developments that occurred
    - **Strategic Significance:** Analysis of the event's importance and broader implications

    ### Structure

    Monthly summaries are built hierarchically:
    1. **Daily Summaries** → Factual reports of daily events
    2. **Weekly Summaries** → Synthesized from 2+ daily summaries
    3. **Monthly Summaries** → Synthesized from 2+ weekly summaries

    ### Key Features

    - **Temporal Tracking:** First and last observed dates show event duration
    - **Category Analysis:** Top categories show event classification patterns
    - **Recipient Analysis:** Top recipients show geographic distribution
    - **Source Traceability:** All summaries link back to original documents

    ### How to Use

    - **By Month:** Browse summaries chronologically by month
    - **Search:** Find specific events or topics across all monthly summaries

    ### Data Quality

    - Currently covering {stats['days_covered']} months of data
    - Total of {stats['total_summaries']:,} monthly event summaries
    - Each summary synthesizes multiple weekly reports
    - Only master events (non-duplicate events) are summarized
    """)
