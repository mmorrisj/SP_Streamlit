"""
Influencer Profile - Comprehensive country profile page.

A 7-tab deep-dive into any influencer country: Overview, Events, Entities,
Bilateral, Categories, Sources, and Timeline.  Inspired by the React
InfluencerPage component.
"""

import datetime
import os
import sys

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import text

# Ensure project root is on sys.path so shared imports resolve
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_engine
from shared.utils.utils import Config

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Influencer Profile", page_icon="\U0001f3db\ufe0f", layout="wide")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
cfg = Config.from_yaml()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.header("Influencer Profile")

selected_country = st.sidebar.selectbox(
    "Country",
    options=cfg.influencers,
    index=cfg.influencers.index("China") if "China" in cfg.influencers else 0,
)

st.sidebar.markdown("### Date Range")
start_date = st.sidebar.date_input(
    "Start Date",
    value=datetime.date(2024, 8, 1),
    min_value=datetime.date(2024, 1, 1),
    max_value=datetime.date.today(),
)
end_date = st.sidebar.date_input(
    "End Date",
    value=datetime.date.today(),
    min_value=datetime.date(2024, 1, 1),
    max_value=datetime.date.today(),
)

start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Active filters**")
st.sidebar.markdown(f"- Country: {selected_country}")
st.sidebar.markdown(f"- Dates: {start_str} to {end_str}")

# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
st.title(f"{selected_country}")
st.caption("Comprehensive country profile across documents, events, entities, bilateral relationships, categories, sources, and timeline.")

# =========================================================================
# QUERY HELPERS  (all cached for 5 minutes)
# =========================================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_overview_metrics(country: str, start: str, end: str, recipients: list):
    """Return KPI counts for the overview tab."""
    engine = get_engine()
    query = text("""
        SELECT
            (SELECT COUNT(DISTINCT d.doc_id)
             FROM documents d
             JOIN initiating_countries ic ON d.doc_id = ic.doc_id
             JOIN recipient_countries rc ON d.doc_id = rc.doc_id
             WHERE ic.initiating_country = :country
               AND rc.recipient_country IN :recipients
               AND ic.initiating_country != rc.recipient_country
               AND d.date BETWEEN :start AND :end
            ) AS total_documents,

            (SELECT COUNT(*)
             FROM canonical_events ce
             WHERE ce.initiating_country = :country
               AND ce.master_event_id IS NULL
               AND ce.first_mention_date <= :end
               AND ce.last_mention_date >= :start
            ) AS total_events,

            (SELECT COUNT(*)
             FROM canonical_entities ce
             WHERE ce.initiating_country = :country
               AND ce.master_entity_id IS NULL
               AND ce.first_mention_date <= :end
               AND ce.last_mention_date >= :start
            ) AS total_entities,

            (SELECT COUNT(DISTINCT rc.recipient_country)
             FROM documents d
             JOIN initiating_countries ic ON d.doc_id = ic.doc_id
             JOIN recipient_countries rc ON d.doc_id = rc.doc_id
             WHERE ic.initiating_country = :country
               AND rc.recipient_country IN :recipients
               AND ic.initiating_country != rc.recipient_country
               AND d.date BETWEEN :start AND :end
            ) AS total_recipients,

            (SELECT ROUND(AVG(ce.material_score)::numeric, 2)
             FROM canonical_events ce
             WHERE ce.initiating_country = :country
               AND ce.master_event_id IS NULL
               AND ce.material_score IS NOT NULL
               AND ce.first_mention_date <= :end
               AND ce.last_mention_date >= :start
            ) AS avg_materiality
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"country": country, "start": start, "end": end, "recipients": tuple(recipients)}).fetchone()
    return row


@st.cache_data(ttl=300, show_spinner=False)
def fetch_top_events(country: str, start: str, end: str, limit: int = 50):
    """Top master events by materiality."""
    engine = get_engine()
    query = text("""
        SELECT
            canonical_name,
            story_phase,
            total_articles,
            material_score,
            first_mention_date,
            last_mention_date,
            consolidated_description
        FROM canonical_events
        WHERE initiating_country = :country
          AND master_event_id IS NULL
          AND first_mention_date <= :end
          AND last_mention_date >= :start
        ORDER BY material_score DESC NULLS LAST, total_articles DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"country": country, "start": start, "end": end, "limit": limit})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_top_entities(country: str, start: str, end: str, entity_type_filter: str = "All"):
    """Top entities for this country."""
    engine = get_engine()

    type_clause = ""
    params: dict = {"country": country, "start": start, "end": end}
    if entity_type_filter != "All":
        type_clause = "AND ce.entity_type = :etype"
        params["etype"] = entity_type_filter.lower()

    query = text(f"""
        SELECT
            ce.canonical_name,
            ce.entity_type::text AS entity_type,
            ce.primary_role::text AS primary_role,
            ce.total_documents,
            ce.entity_description,
            ce.first_mention_date,
            ce.last_mention_date
        FROM canonical_entities ce
        WHERE ce.initiating_country = :country
          AND ce.master_entity_id IS NULL
          AND ce.first_mention_date <= :end
          AND ce.last_mention_date >= :start
          {type_clause}
        ORDER BY ce.total_documents DESC
        LIMIT 100
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_bilateral_summaries(country: str, recipients: list):
    """Bilateral relationship summaries for this country."""
    engine = get_engine()
    query = text("""
        SELECT
            recipient_country,
            total_documents,
            material_score,
            relationship_summary,
            first_interaction_date,
            last_interaction_date
        FROM bilateral_relationship_summaries
        WHERE initiating_country = :country
          AND recipient_country IN :recipients
          AND initiating_country != recipient_country
          AND is_deleted = false
        ORDER BY total_documents DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"country": country, "recipients": tuple(recipients)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_category_summaries(country: str):
    """Country category summaries."""
    engine = get_engine()
    query = text("""
        SELECT
            category,
            total_documents,
            total_daily_events,
            total_weekly_events,
            total_monthly_events,
            material_score_avg,
            category_summary,
            count_by_recipient,
            count_by_subcategory
        FROM country_category_summaries
        WHERE initiating_country = :country
          AND is_deleted = false
        ORDER BY total_documents DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"country": country})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_top_sources(country: str, start: str, end: str, recipients: list, limit: int = 30):
    """Top sources by document count."""
    engine = get_engine()
    query = text("""
        SELECT
            d.source_name,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country = :country
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start AND :end
          AND d.source_name IS NOT NULL
        GROUP BY d.source_name
        ORDER BY doc_count DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"country": country, "start": start, "end": end, "recipients": tuple(recipients), "limit": limit})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_source_medium_breakdown(country: str, start: str, end: str, recipients: list):
    """Source medium breakdown for a bar chart."""
    engine = get_engine()
    query = text("""
        SELECT
            d.source_medium,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country = :country
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start AND :end
          AND d.source_medium IS NOT NULL
        GROUP BY d.source_medium
        ORDER BY doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"country": country, "start": start, "end": end, "recipients": tuple(recipients)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_monthly_timeline(country: str, start: str, end: str, recipients: list):
    """Monthly document count trend."""
    engine = get_engine()
    query = text("""
        SELECT
            date_trunc('month', d.date)::date AS month,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country = :country
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start AND :end
        GROUP BY date_trunc('month', d.date)
        ORDER BY month
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"country": country, "start": start, "end": end, "recipients": tuple(recipients)})
    return df


# =========================================================================
# TABS
# =========================================================================

tab_overview, tab_events, tab_entities, tab_bilateral, tab_categories, tab_sources, tab_timeline = st.tabs([
    "Overview",
    "Events",
    "Entities",
    "Bilateral",
    "Categories",
    "Sources",
    "Timeline",
])

# -------------------------------------------------------------------------
# TAB 1 - Overview
# -------------------------------------------------------------------------
with tab_overview:
    st.header("Overview")

    metrics = fetch_overview_metrics(selected_country, start_str, end_str, cfg.recipients)

    if metrics:
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric("Total Documents", f"{(metrics[0] or 0):,}")
        with c2:
            st.metric("Total Events", f"{(metrics[1] or 0):,}")
        with c3:
            st.metric("Total Entities", f"{(metrics[2] or 0):,}")
        with c4:
            st.metric("Total Recipients", f"{(metrics[3] or 0):,}")
        with c5:
            st.metric("Avg Materiality", f"{metrics[4] or 0}")
    else:
        st.info("No data available for the selected filters.")

    st.markdown("---")

    # Quick snapshot: top 5 events
    st.subheader("Top Events by Materiality")
    top5 = fetch_top_events(selected_country, start_str, end_str, limit=5)
    if not top5.empty:
        display_df = top5[["canonical_name", "story_phase", "total_articles", "material_score"]].copy()
        display_df.columns = ["Event", "Phase", "Articles", "Materiality"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No events found for the selected filters.")

# -------------------------------------------------------------------------
# TAB 2 - Events
# -------------------------------------------------------------------------
with tab_events:
    st.header("Events")
    st.markdown("Master events (consolidated canonical events) ordered by materiality score.")

    events_df = fetch_top_events(selected_country, start_str, end_str, limit=50)

    if not events_df.empty:
        st.metric("Master Events", len(events_df))

        for _, row in events_df.iterrows():
            score_label = f"{row['material_score']:.1f}" if pd.notna(row["material_score"]) else "N/A"
            header_text = f"{score_label} | {row['canonical_name']}  ({row['total_articles']} articles)"
            with st.expander(header_text):
                ec1, ec2, ec3, ec4 = st.columns(4)
                with ec1:
                    st.markdown(f"**Phase:** {row['story_phase'] or 'N/A'}")
                with ec2:
                    st.markdown(f"**Articles:** {row['total_articles']:,}")
                with ec3:
                    st.markdown(f"**First mention:** {row['first_mention_date']}")
                with ec4:
                    st.markdown(f"**Last mention:** {row['last_mention_date']}")
                if row["consolidated_description"]:
                    st.markdown("**Description:**")
                    st.markdown(row["consolidated_description"])
    else:
        st.info("No master events found for the selected filters.")

# -------------------------------------------------------------------------
# TAB 3 - Entities
# -------------------------------------------------------------------------
with tab_entities:
    st.header("Entities")
    st.markdown("Key people, organizations, and companies associated with this country's soft power activities.")

    etype_tabs = st.radio(
        "Filter by type",
        ["All", "Person", "Organization", "Company"],
        horizontal=True,
        key="entity_type_filter",
    )

    entities_df = fetch_top_entities(selected_country, start_str, end_str, entity_type_filter=etype_tabs)

    if not entities_df.empty:
        st.metric("Entities", len(entities_df))

        for _, row in entities_df.iterrows():
            role_str = (row["primary_role"] or "").replace("_", " ").title()
            label = f"{row['canonical_name']}  ({row['entity_type']}, {row['total_documents']} docs)"
            with st.expander(label):
                ec1, ec2, ec3 = st.columns(3)
                with ec1:
                    st.markdown(f"**Type:** {row['entity_type']}")
                with ec2:
                    st.markdown(f"**Role:** {role_str or 'N/A'}")
                with ec3:
                    st.markdown(f"**Documents:** {row['total_documents']:,}")
                if row.get("entity_description"):
                    st.markdown("**Profile:**")
                    st.markdown(row["entity_description"])
    else:
        st.info("No entities found for the selected filters.")

# -------------------------------------------------------------------------
# TAB 4 - Bilateral
# -------------------------------------------------------------------------
with tab_bilateral:
    st.header("Bilateral Relationships")
    st.markdown("AI-generated relationship summaries between this country and its recipients.")

    bilateral_df = fetch_bilateral_summaries(selected_country, cfg.recipients)

    if not bilateral_df.empty:
        st.metric("Bilateral Relationships", len(bilateral_df))

        for _, row in bilateral_df.iterrows():
            score_label = f"{row['material_score']:.2f}" if pd.notna(row["material_score"]) else "N/A"
            label = f"{row['recipient_country']}  ({row['total_documents']:,} docs, materiality {score_label})"
            with st.expander(label):
                bc1, bc2, bc3 = st.columns(3)
                with bc1:
                    st.markdown(f"**Documents:** {row['total_documents']:,}")
                with bc2:
                    st.markdown(f"**Material Score:** {score_label}")
                with bc3:
                    dates = f"{row['first_interaction_date']} to {row['last_interaction_date']}"
                    st.markdown(f"**Period:** {dates}")

                rel_summary = row.get("relationship_summary")
                if isinstance(rel_summary, dict):
                    overview_text = rel_summary.get("overview", "")
                    if overview_text:
                        st.markdown("**Overview:**")
                        st.markdown(overview_text)

                    themes = rel_summary.get("key_themes", [])
                    if themes:
                        st.markdown("**Key Themes:**")
                        for theme in themes:
                            st.markdown(f"- {theme}")
                elif isinstance(rel_summary, str) and rel_summary:
                    st.markdown(rel_summary)
    else:
        st.info("No bilateral relationship summaries found for this country.")

# -------------------------------------------------------------------------
# TAB 5 - Categories
# -------------------------------------------------------------------------
with tab_categories:
    st.header("Category Strategy")
    st.markdown("Category-level analysis of this country's soft power deployment.")

    cat_df = fetch_category_summaries(selected_country)

    if not cat_df.empty:
        # Summary bar chart
        chart_data = cat_df[["category", "total_documents"]].copy()
        chart_data.columns = ["Category", "Documents"]
        bar = (
            alt.Chart(chart_data)
            .mark_bar()
            .encode(
                x=alt.X("Category:N", title="Category"),
                y=alt.Y("Documents:Q", title="Documents"),
                color=alt.Color("Category:N", legend=None),
                tooltip=["Category", "Documents"],
            )
            .properties(height=300, title=f"{selected_country} - Documents by Category")
        )
        st.altair_chart(bar, use_container_width=True)

        st.markdown("---")

        for _, row in cat_df.iterrows():
            total_events = (row["total_daily_events"] or 0) + (row["total_weekly_events"] or 0) + (row["total_monthly_events"] or 0)
            mat_label = f"{row['material_score_avg']:.2f}" if pd.notna(row["material_score_avg"]) else "N/A"
            label = f"{row['category']}  ({row['total_documents']:,} docs, {total_events} events, materiality {mat_label})"
            with st.expander(label):
                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    st.markdown(f"**Documents:** {row['total_documents']:,}")
                with cc2:
                    st.markdown(f"**Events:** {total_events}")
                with cc3:
                    st.markdown(f"**Avg Materiality:** {mat_label}")

                cat_summary = row.get("category_summary")
                if isinstance(cat_summary, dict):
                    overview_text = cat_summary.get("overview", "")
                    if overview_text:
                        st.markdown("**Overview:**")
                        st.markdown(overview_text)

                    strategies = cat_summary.get("key_strategies", [])
                    if strategies:
                        st.markdown("**Key Strategies:**")
                        for s in strategies:
                            st.markdown(f"- {s}")
                elif isinstance(cat_summary, str) and cat_summary:
                    st.markdown(cat_summary)
    else:
        st.info("No category summaries found for this country.")

# -------------------------------------------------------------------------
# TAB 6 - Sources
# -------------------------------------------------------------------------
with tab_sources:
    st.header("Sources")
    st.markdown("News sources covering this country's soft power activities.")

    sources_df = fetch_top_sources(selected_country, start_str, end_str, cfg.recipients, limit=30)

    if not sources_df.empty:
        st.subheader("Top Sources by Document Count")
        display_sources = sources_df.copy()
        display_sources.columns = ["Source", "Documents"]
        st.dataframe(display_sources, use_container_width=True, hide_index=True)

        # Source medium breakdown
        st.markdown("---")
        st.subheader("Source Medium Breakdown")
        medium_df = fetch_source_medium_breakdown(selected_country, start_str, end_str, cfg.recipients)

        if not medium_df.empty:
            medium_df.columns = ["Medium", "Documents"]
            medium_bar = (
                alt.Chart(medium_df)
                .mark_bar()
                .encode(
                    x=alt.X("Documents:Q", title="Documents"),
                    y=alt.Y("Medium:N", sort="-x", title="Source Medium"),
                    color=alt.Color("Medium:N", legend=None),
                    tooltip=["Medium", "Documents"],
                )
                .properties(height=max(200, len(medium_df) * 30), title="Documents by Source Medium")
            )
            st.altair_chart(medium_bar, use_container_width=True)
        else:
            st.info("No source medium data available.")
    else:
        st.info("No source data available for the selected filters.")

# -------------------------------------------------------------------------
# TAB 7 - Timeline
# -------------------------------------------------------------------------
with tab_timeline:
    st.header("Timeline")
    st.markdown("Monthly document volume trend.")

    timeline_df = fetch_monthly_timeline(selected_country, start_str, end_str, cfg.recipients)

    if not timeline_df.empty:
        timeline_df["month"] = pd.to_datetime(timeline_df["month"])

        line = (
            alt.Chart(timeline_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("month:T", title="Month"),
                y=alt.Y("doc_count:Q", title="Documents"),
                tooltip=[
                    alt.Tooltip("month:T", title="Month"),
                    alt.Tooltip("doc_count:Q", title="Documents"),
                ],
            )
            .properties(height=400, title=f"{selected_country} - Monthly Document Volume")
        )
        st.altair_chart(line, use_container_width=True)

        # Summary stats
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.metric("Total Months", len(timeline_df))
        with sc2:
            st.metric("Avg Documents / Month", f"{timeline_df['doc_count'].mean():.0f}")
        with sc3:
            peak = timeline_df.loc[timeline_df["doc_count"].idxmax()]
            st.metric("Peak Month", peak["month"].strftime("%Y-%m"))
            st.caption(f"{int(peak['doc_count']):,} documents")
    else:
        st.info("No timeline data available for the selected filters.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "This page aggregates data from documents, canonical events, canonical entities, "
    "bilateral relationship summaries, and country category summaries."
)
