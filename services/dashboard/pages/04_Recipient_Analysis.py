"""
Recipient Analysis Dashboard

Analyze how a specific recipient country is engaged by different influencer nations,
including category breakdowns, recent events, and monthly activity trends.
"""

import datetime as dt
import pandas as pd
import altair as alt
import streamlit as st
from sqlalchemy import text
from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Recipient Analysis", page_icon="🎯", layout="wide")
st.title("🎯 Recipient Analysis")
st.caption("Understand how influencer nations engage with a specific recipient country")

# ---------------------------------------------------------------------------
# Query Functions
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_docs_by_influencer(recipient, start_date, end_date, influencers):
    """Documents per influencer for a given recipient."""
    engine = get_engine()
    query = text("""
        SELECT ic.initiating_country, COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE rc.recipient_country = :recipient
          AND ic.initiating_country IN :influencers
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY ic.initiating_country
        ORDER BY doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={
                "recipient": recipient,
                "influencers": tuple(influencers),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_category_breakdown(recipient, start_date, end_date, influencers):
    """Category distribution for documents mentioning this recipient."""
    engine = get_engine()
    query = text("""
        SELECT c.category, COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE rc.recipient_country = :recipient
          AND ic.initiating_country IN :influencers
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY c.category
        ORDER BY doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={
                "recipient": recipient,
                "influencers": tuple(influencers),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_recent_events(recipient, influencers, limit=30):
    """Recent canonical events mentioning this recipient via primary_recipients JSONB."""
    engine = get_engine()
    query = text("""
        SELECT
            canonical_name,
            initiating_country,
            first_mention_date,
            last_mention_date,
            total_articles,
            story_phase,
            CAST(material_score AS FLOAT) AS material_score,
            primary_categories
        FROM canonical_events
        WHERE primary_recipients ? :recipient
          AND master_event_id IS NULL
          AND initiating_country = ANY(:influencers)
        ORDER BY last_mention_date DESC
        LIMIT :lim
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"recipient": recipient, "influencers": list(influencers), "lim": limit},
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_monthly_trend(recipient, start_date, end_date, influencers):
    """Monthly document counts for this recipient."""
    engine = get_engine()
    query = text("""
        SELECT
            DATE_TRUNC('month', d.date)::date AS month,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE rc.recipient_country = :recipient
          AND ic.initiating_country IN :influencers
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY DATE_TRUNC('month', d.date)
        ORDER BY month
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={
                "recipient": recipient,
                "influencers": tuple(influencers),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_influencer_category_matrix(recipient, start_date, end_date, influencers):
    """Category counts per influencer for this recipient (for stacked chart)."""
    engine = get_engine()
    query = text("""
        SELECT ic.initiating_country, c.category, COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE rc.recipient_country = :recipient
          AND ic.initiating_country IN :influencers
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY ic.initiating_country, c.category
        ORDER BY ic.initiating_country, doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={
                "recipient": recipient,
                "influencers": tuple(influencers),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_total_doc_count(recipient, start_date, end_date, influencers):
    """Total document count for this recipient within the date range."""
    engine = get_engine()
    query = text("""
        SELECT COUNT(DISTINCT d.doc_id) AS total
        FROM documents d
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE rc.recipient_country = :recipient
          AND ic.initiating_country IN :influencers
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
    """)
    with engine.connect() as conn:
        row = conn.execute(
            query,
            {
                "recipient": recipient,
                "influencers": tuple(influencers),
                "start_date": start_date,
                "end_date": end_date,
            },
        ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")

    selected_recipient = st.selectbox("Recipient Country", cfg.recipients)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=dt.date(2024, 1, 1))
    with col2:
        end_date = st.date_input("End Date", value=dt.date.today())

    influencer_options = cfg.influencers
    selected_influencers = st.multiselect(
        "Influencers to Include",
        options=influencer_options,
        default=influencer_options,
    )

if not selected_influencers:
    st.info("Please select at least one influencer country.")
    st.stop()

# ---------------------------------------------------------------------------
# KPI Row
# ---------------------------------------------------------------------------
total_docs = get_total_doc_count(selected_recipient, start_date, end_date, selected_influencers)
influencer_df = get_docs_by_influencer(selected_recipient, start_date, end_date, selected_influencers)
category_df = get_category_breakdown(selected_recipient, start_date, end_date, selected_influencers)
events_df = get_recent_events(selected_recipient, selected_influencers)

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
with kpi1:
    st.metric("Total Documents", f"{total_docs:,}")
with kpi2:
    st.metric("Active Influencers", len(influencer_df))
with kpi3:
    st.metric("Categories Covered", len(category_df))
with kpi4:
    st.metric("Canonical Events", len(events_df))

st.divider()

# ---------------------------------------------------------------------------
# Influencer Engagement Bar Chart
# ---------------------------------------------------------------------------
st.header("Influencer Engagement")

if influencer_df.empty:
    st.info("No document data found for the selected filters.")
else:
    influencer_chart = (
        alt.Chart(influencer_df)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Documents"),
            y=alt.Y(
                "initiating_country:N",
                title="Influencer",
                sort=alt.EncodingSortField(field="doc_count", order="descending"),
            ),
            color=alt.Color("initiating_country:N", legend=None),
            tooltip=[
                alt.Tooltip("initiating_country:N", title="Country"),
                alt.Tooltip("doc_count:Q", title="Documents"),
            ],
        )
        .properties(height=max(200, len(influencer_df) * 40), title=f"Documents Targeting {selected_recipient} by Influencer")
    )
    st.altair_chart(influencer_chart, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Category Breakdown
# ---------------------------------------------------------------------------
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Category Breakdown")
    if category_df.empty:
        st.info("No category data available.")
    else:
        cat_bar = (
            alt.Chart(category_df)
            .mark_bar()
            .encode(
                x=alt.X("doc_count:Q", title="Documents"),
                y=alt.Y("category:N", title="Category", sort="-x"),
                color=alt.Color("category:N", legend=None),
                tooltip=["category:N", "doc_count:Q"],
            )
            .properties(height=max(200, len(category_df) * 40), title="Document Count by Category")
        )
        st.altair_chart(cat_bar, use_container_width=True)

with col_right:
    st.subheader("Category Share")
    if category_df.empty:
        st.info("No category data available.")
    else:
        cat_pie = (
            alt.Chart(category_df)
            .mark_arc(innerRadius=50)
            .encode(
                theta=alt.Theta("doc_count:Q"),
                color=alt.Color("category:N", legend=alt.Legend(title="Category")),
                tooltip=["category:N", "doc_count:Q"],
            )
            .properties(height=350, title="Category Proportions")
        )
        st.altair_chart(cat_pie, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Influencer-Category Matrix (stacked bar)
# ---------------------------------------------------------------------------
st.header("Influencer-Category Matrix")

matrix_df = get_influencer_category_matrix(selected_recipient, start_date, end_date, selected_influencers)

if matrix_df.empty:
    st.info("No data for influencer-category matrix.")
else:
    stacked = (
        alt.Chart(matrix_df)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Documents", stack="zero"),
            y=alt.Y(
                "initiating_country:N",
                title="Influencer",
                sort=alt.EncodingSortField(field="doc_count", op="sum", order="descending"),
            ),
            color=alt.Color("category:N", legend=alt.Legend(title="Category")),
            tooltip=["initiating_country:N", "category:N", "doc_count:Q"],
        )
        .properties(height=max(200, len(matrix_df["initiating_country"].unique()) * 50), title=f"Category Mix per Influencer Targeting {selected_recipient}")
    )
    st.altair_chart(stacked, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Monthly Activity Trend
# ---------------------------------------------------------------------------
st.header("Monthly Activity Trend")

trend_df = get_monthly_trend(selected_recipient, start_date, end_date, selected_influencers)

if trend_df.empty:
    st.info("No monthly trend data available.")
else:
    trend_chart = (
        alt.Chart(trend_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:T", title="Month"),
            y=alt.Y("doc_count:Q", title="Documents"),
            tooltip=[
                alt.Tooltip("month:T", title="Month"),
                alt.Tooltip("doc_count:Q", title="Documents"),
            ],
        )
        .properties(height=350, title=f"Monthly Document Volume for {selected_recipient}")
    )
    st.altair_chart(trend_chart, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Recent Canonical Events
# ---------------------------------------------------------------------------
st.header("Recent Canonical Events")

if events_df.empty:
    st.info("No canonical events found mentioning this recipient.")
else:
    for _, ev in events_df.iterrows():
        score_label = f"{ev['material_score']:.1f}" if pd.notna(ev["material_score"]) else "N/A"
        with st.expander(f"{score_label} | {ev['canonical_name']}  ({ev['first_mention_date']} - {ev['last_mention_date']})"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**Initiator:** {ev['initiating_country']}")
            with c2:
                st.markdown(f"**Articles:** {ev['total_articles']}")
            with c3:
                st.markdown(f"**Phase:** {ev['story_phase']}")

            cats = ev.get("primary_categories")
            if cats and isinstance(cats, dict):
                st.markdown("**Categories:** " + ", ".join(f"{k} ({v})" for k, v in sorted(cats.items(), key=lambda x: x[1], reverse=True)))

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption("Data sourced from documents, canonical_events, and related tables. Filters respect cfg.influencers and cfg.recipients.")
