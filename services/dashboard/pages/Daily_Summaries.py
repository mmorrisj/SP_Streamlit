"""
Daily Event Summaries Dashboard

Browse and explore AP-style daily summaries of soft power events with complete
source traceability.
"""

import streamlit as st
from datetime import datetime, date, timedelta
from shared.utils.utils import Config
from queries.summary_queries import (
    get_available_summary_dates,
    get_daily_summaries_by_date,
    get_summary_statistics,
    search_summaries,
    get_top_events_by_period
)


# Helper functions (defined first)
def display_summary_content(summary: dict):
    """Display the content of a summary."""

    narrative = summary['narrative_summary']

    # Overview section
    if 'overview' in narrative:
        st.markdown("### Overview")
        st.markdown(narrative['overview'])

    # Outcomes section
    if 'outcomes' in narrative:
        st.markdown("### Outcomes")
        st.markdown(narrative['outcomes'])

    # Metadata section
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


def display_summary_card(summary: dict):
    """Display a summary as an expandable card."""

    # Event name and document count
    event_name = summary['event_name']
    doc_count = summary['total_documents']

    with st.expander(
        f"**{event_name}** ({doc_count} article{'s' if doc_count != 1 else ''})",
        expanded=False
    ):
        display_summary_content(summary)


# Page configuration
st.set_page_config(
    page_title="Daily Event Summaries",
    page_icon="📰",
    layout="wide"
)

st.title("📰 Daily Event Summaries")
st.markdown("*AP-style narrative summaries of soft power events with complete source traceability*")

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

# Date range selection
col1, col2 = st.sidebar.columns(2)

# Get available dates for the country
available_dates = get_available_summary_dates(country, 'DAILY')

if not available_dates:
    st.warning(f"No daily summaries available for {country}. Please generate summaries first.")
    st.stop()

# Set default date range to available dates
min_date = min(available_dates)
max_date = max(available_dates)

with col1:
    start_date = st.date_input(
        "Start Date",
        value=max_date - timedelta(days=7),  # Default to last 7 days
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
    options=["By Date", "Top Events", "Search Results"],
    index=0
)

# Statistics section
st.sidebar.markdown("---")
st.sidebar.subheader("Statistics")

stats = get_summary_statistics(country, start_date, end_date, 'DAILY')

st.sidebar.metric("Total Summaries", f"{stats['total_summaries']:,}")
st.sidebar.metric("Total Documents", f"{stats['total_documents']:,}")
st.sidebar.metric("Days Covered", stats['days_covered'])

# Main content area
st.markdown("---")

# Display based on mode
if display_mode == "Search Results" and search_term:
    st.subheader(f"Search Results for '{search_term}'")

    results = search_summaries(
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
            display_summary_card(summary)

elif display_mode == "Top Events":
    st.subheader(f"Top Events: {start_date} to {end_date}")

    top_events = get_top_events_by_period(
        country=country,
        start_date=start_date,
        end_date=end_date,
        limit=20
    )

    if not top_events:
        st.info("No events found in this date range.")
    else:
        # Display top events summary
        st.markdown(f"**Showing top {len(top_events)} events by document volume**")

        for i, event in enumerate(top_events, 1):
            with st.expander(
                f"#{i} **{event['event_name']}** "
                f"({event['total_documents']} docs across {event['days_mentioned']} days)"
            ):
                st.markdown(f"**First mentioned:** {event['first_date'].strftime('%B %d, %Y')}")
                st.markdown(f"**Last mentioned:** {event['last_date'].strftime('%B %d, %Y')}")
                st.markdown(f"**Total documents:** {event['total_documents']:,}")
                st.markdown(f"**Days active:** {event['days_mentioned']}")

                # Get one sample summary for this event
                sample_summaries = search_summaries(
                    country=country,
                    search_term=event['event_name'],
                    start_date=start_date,
                    end_date=end_date,
                    limit=1
                )

                if sample_summaries:
                    summary = sample_summaries[0]
                    st.markdown("---")
                    st.markdown(f"**Sample Summary ({summary['period_start'].strftime('%B %d, %Y')}):**")
                    display_summary_content(summary)

else:  # By Date mode
    st.subheader(f"{country} Daily Summaries: {start_date} to {end_date}")

    # Get all summaries in date range
    summaries = []
    current_date = start_date

    while current_date <= end_date:
        day_summaries = get_daily_summaries_by_date(
            country=country,
            target_date=current_date
        )

        if day_summaries:
            summaries.extend(day_summaries)

        current_date += timedelta(days=1)

    if not summaries:
        st.info(f"No summaries found for {country} between {start_date} and {end_date}.")
    else:
        # Group by date
        dates_with_summaries = {}
        for summary in summaries:
            date_key = summary['period_start']
            if date_key not in dates_with_summaries:
                dates_with_summaries[date_key] = []
            dates_with_summaries[date_key].append(summary)

        # Display by date (most recent first)
        for summary_date in sorted(dates_with_summaries.keys(), reverse=True):
            date_summaries = dates_with_summaries[summary_date]

            st.markdown(f"## {summary_date.strftime('%A, %B %d, %Y')}")
            st.markdown(f"*{len(date_summaries)} events reported*")

            for summary in date_summaries:
                display_summary_card(summary)

            st.markdown("---")


# Help section at bottom
with st.expander("ℹ️ About Daily Summaries"):
    st.markdown(f"""
    ### What are Daily Summaries?

    Daily summaries are **AP-style narrative summaries** of soft power events that occurred on a specific day.
    Each summary is generated by AI using actual source documents and follows Associated Press reporting standards:

    - **Factual reporting only** - No analysis or interpretation
    - **Source attribution** - All statements cite sources
    - **Specific details** - Numbers, dates, locations, official statements
    - **Past tense** - Reports on completed actions

    ### Structure

    Each summary contains:
    - **Overview:** What happened, when, where, who was involved, and what sources reported
    - **Outcomes:** Specific results, official statements, and concrete actions taken
    - **Sources:** Complete traceability to original documents via ATOM hyperlinks
    - **Citations:** Formatted references to source documents

    ### How to Use

    - **By Date:** Browse summaries chronologically
    - **Top Events:** See the most covered events by document volume
    - **Search:** Find specific events or topics

    ### Data Quality

    - Summaries are based on {stats['total_documents']:,} source documents
    - Each summary links to all supporting documents
    - Citations include source name, ATOM ID, title, and date
    """)
