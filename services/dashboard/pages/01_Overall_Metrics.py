"""
Overall Metrics Dashboard

High-level overview of the entire soft power analytics dataset: total documents,
events, entities, bilateral pairs, monthly trends, category distribution,
and influencer comparisons.
"""

import datetime as dt
import pandas as pd
import altair as alt
import streamlit as st
from sqlalchemy import text
from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Overall Metrics", page_icon="📊", layout="wide")
st.title("📊 Overall Metrics")
st.caption("System-wide view of documents, events, entities, and bilateral relationships")

# ---------------------------------------------------------------------------
# Query Functions
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_total_documents(influencers):
    """Total document count across selected influencers."""
    engine = get_engine()
    query = text("""
        SELECT COUNT(DISTINCT d.doc_id) AS total
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE ic.initiating_country IN :influencers
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"influencers": tuple(influencers)}).fetchone()
    return row[0] if row else 0


@st.cache_data(ttl=300, show_spinner=False)
def get_total_events(influencers):
    """Total master canonical events."""
    engine = get_engine()
    query = text("""
        SELECT COUNT(*) AS total
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND initiating_country IN :influencers
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"influencers": tuple(influencers)}).fetchone()
    return row[0] if row else 0


@st.cache_data(ttl=300, show_spinner=False)
def get_total_entities(influencers):
    """Total master canonical entities."""
    engine = get_engine()
    query = text("""
        SELECT COUNT(*) AS total
        FROM canonical_entities
        WHERE master_entity_id IS NULL
          AND initiating_country IN :influencers
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"influencers": tuple(influencers)}).fetchone()
    return row[0] if row else 0


@st.cache_data(ttl=300, show_spinner=False)
def get_total_bilateral_pairs(influencers, recipients):
    """Total bilateral relationship summaries."""
    engine = get_engine()
    query = text("""
        SELECT COUNT(*) AS total
        FROM bilateral_relationship_summaries
        WHERE is_deleted = FALSE
          AND initiating_country IN :influencers
          AND recipient_country IN :recipients
    """)
    with engine.connect() as conn:
        row = conn.execute(
            query, {"influencers": tuple(influencers), "recipients": tuple(recipients)}
        ).fetchone()
    return row[0] if row else 0


@st.cache_data(ttl=300, show_spinner=False)
def get_monthly_doc_trend(influencers):
    """Monthly documents across all selected influencers."""
    engine = get_engine()
    query = text("""
        SELECT
            DATE_TRUNC('month', d.date)::date AS month,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE ic.initiating_country IN :influencers
          AND d.date IS NOT NULL
        GROUP BY DATE_TRUNC('month', d.date)
        ORDER BY month
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"influencers": tuple(influencers)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_category_distribution(influencers):
    """Category distribution across all documents."""
    engine = get_engine()
    query = text("""
        SELECT
            c.category,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country IN :influencers
        GROUP BY c.category
        ORDER BY doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"influencers": tuple(influencers)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_influencer_doc_counts(influencers):
    """Document counts per influencer."""
    engine = get_engine()
    query = text("""
        SELECT
            ic.initiating_country,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE ic.initiating_country IN :influencers
        GROUP BY ic.initiating_country
        ORDER BY doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"influencers": tuple(influencers)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_stacked_category_by_influencer(influencers):
    """Category counts per influencer for stacked bar chart."""
    engine = get_engine()
    query = text("""
        SELECT
            ic.initiating_country,
            c.category,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country IN :influencers
        GROUP BY ic.initiating_country, c.category
        ORDER BY ic.initiating_country, doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"influencers": tuple(influencers)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_subcategory_breakdown(influencers):
    """Subcategory counts across all influencers."""
    engine = get_engine()
    query = text("""
        SELECT
            sc.subcategory,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN subcategories sc ON d.doc_id = sc.doc_id
        WHERE ic.initiating_country IN :influencers
        GROUP BY sc.subcategory
        ORDER BY doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"influencers": tuple(influencers)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_date_range(influencers):
    """Earliest and latest document dates."""
    engine = get_engine()
    query = text("""
        SELECT MIN(d.date) AS min_date, MAX(d.date) AS max_date
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE ic.initiating_country IN :influencers
          AND d.date IS NOT NULL
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"influencers": tuple(influencers)}).fetchone()
    return row if row else (None, None)


@st.cache_data(ttl=300, show_spinner=False)
def get_monthly_doc_trend_by_country(influencers):
    """Monthly document counts split by influencer."""
    engine = get_engine()
    query = text("""
        SELECT
            DATE_TRUNC('month', d.date)::date AS month,
            ic.initiating_country,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE ic.initiating_country IN :influencers
          AND d.date IS NOT NULL
        GROUP BY DATE_TRUNC('month', d.date), ic.initiating_country
        ORDER BY month
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"influencers": tuple(influencers)})
    return df


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------
influencers = cfg.influencers
recipients = cfg.recipients

total_docs = get_total_documents(influencers)
total_events = get_total_events(influencers)
total_entities = get_total_entities(influencers)
total_bilateral = get_total_bilateral_pairs(influencers, recipients)
date_range = get_date_range(influencers)

# ---------------------------------------------------------------------------
# KPI Row
# ---------------------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Total Documents", f"{total_docs:,}")
with k2:
    st.metric("Total Events", f"{total_events:,}")
with k3:
    st.metric("Total Entities", f"{total_entities:,}")
with k4:
    st.metric("Bilateral Pairs", f"{total_bilateral:,}")

if date_range and date_range[0] and date_range[1]:
    st.caption(f"Data coverage: {date_range[0]} to {date_range[1]}")

st.divider()

# ---------------------------------------------------------------------------
# Monthly Trend Line Chart (All Countries Combined)
# ---------------------------------------------------------------------------
st.header("Monthly Document Trend")

monthly_df = get_monthly_doc_trend(influencers)

if monthly_df.empty:
    st.info("No monthly trend data available.")
else:
    trend_chart = (
        alt.Chart(monthly_df)
        .mark_area(
            line={"color": "#1f77b4"},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="white", offset=0),
                    alt.GradientStop(color="#1f77b4", offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
        )
        .encode(
            x=alt.X("month:T", title="Month"),
            y=alt.Y("doc_count:Q", title="Documents"),
            tooltip=[
                alt.Tooltip("month:T", title="Month"),
                alt.Tooltip("doc_count:Q", title="Documents"),
            ],
        )
        .properties(height=350, title="Monthly Document Volume (All Influencers)")
    )
    st.altair_chart(trend_chart, use_container_width=True)

# Monthly trend by country
st.subheader("Monthly Trend by Country")

monthly_country_df = get_monthly_doc_trend_by_country(influencers)

if monthly_country_df.empty:
    st.info("No country-level monthly trend data available.")
else:
    country_trend = (
        alt.Chart(monthly_country_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:T", title="Month"),
            y=alt.Y("doc_count:Q", title="Documents"),
            color=alt.Color("initiating_country:N", legend=alt.Legend(title="Country")),
            tooltip=[
                alt.Tooltip("month:T", title="Month"),
                alt.Tooltip("initiating_country:N", title="Country"),
                alt.Tooltip("doc_count:Q", title="Documents"),
            ],
        )
        .properties(height=400, title="Monthly Document Volume by Country")
    )
    st.altair_chart(country_trend, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Category Distribution
# ---------------------------------------------------------------------------
st.header("Category Distribution")

cat_df = get_category_distribution(influencers)

if cat_df.empty:
    st.info("No category data available.")
else:
    col_bar, col_donut = st.columns(2)

    with col_bar:
        cat_bar = (
            alt.Chart(cat_df)
            .mark_bar()
            .encode(
                x=alt.X("doc_count:Q", title="Documents"),
                y=alt.Y("category:N", title="Category", sort="-x"),
                color=alt.Color("category:N", legend=None),
                tooltip=["category:N", "doc_count:Q"],
            )
            .properties(height=max(200, len(cat_df) * 45), title="Documents by Category")
        )
        st.altair_chart(cat_bar, use_container_width=True)

    with col_donut:
        cat_donut = (
            alt.Chart(cat_df)
            .mark_arc(innerRadius=50)
            .encode(
                theta=alt.Theta("doc_count:Q"),
                color=alt.Color("category:N", legend=alt.Legend(title="Category")),
                tooltip=["category:N", "doc_count:Q"],
            )
            .properties(height=350, title="Category Proportions")
        )
        st.altair_chart(cat_donut, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Influencer Comparison
# ---------------------------------------------------------------------------
st.header("Influencer Comparison")

inf_df = get_influencer_doc_counts(influencers)

if inf_df.empty:
    st.info("No influencer data available.")
else:
    inf_bar = (
        alt.Chart(inf_df)
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
        .properties(height=max(200, len(inf_df) * 50), title="Document Volume by Influencer")
    )
    st.altair_chart(inf_bar, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Stacked Category by Influencer
# ---------------------------------------------------------------------------
st.header("Category Mix by Influencer")

stacked_df = get_stacked_category_by_influencer(influencers)

if stacked_df.empty:
    st.info("No stacked category data available.")
else:
    # Normalized
    stacked_norm = (
        alt.Chart(stacked_df)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Proportion", stack="normalize"),
            y=alt.Y(
                "initiating_country:N",
                title="Influencer",
                sort=alt.EncodingSortField(field="doc_count", op="sum", order="descending"),
            ),
            color=alt.Color("category:N", legend=alt.Legend(title="Category")),
            tooltip=["initiating_country:N", "category:N", "doc_count:Q"],
        )
        .properties(height=max(200, len(influencers) * 50), title="Normalized Category Distribution per Influencer")
    )
    st.altair_chart(stacked_norm, use_container_width=True)

    # Absolute
    stacked_abs = (
        alt.Chart(stacked_df)
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
        .properties(height=max(200, len(influencers) * 50), title="Absolute Category Volumes per Influencer")
    )
    st.altair_chart(stacked_abs, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Subcategory Breakdown Table
# ---------------------------------------------------------------------------
st.header("Subcategory Breakdown")

subcat_df = get_subcategory_breakdown(influencers)

if subcat_df.empty:
    st.info("No subcategory data available.")
else:
    # Top subcategories bar chart
    top_subcat = subcat_df.head(20)
    subcat_chart = (
        alt.Chart(top_subcat)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Documents"),
            y=alt.Y("subcategory:N", title="Subcategory", sort="-x"),
            color=alt.Color("doc_count:Q", scale=alt.Scale(scheme="viridis"), legend=None),
            tooltip=["subcategory:N", "doc_count:Q"],
        )
        .properties(height=max(300, len(top_subcat) * 25), title="Top 20 Subcategories by Document Volume")
    )
    st.altair_chart(subcat_chart, use_container_width=True)

    # Full table
    st.subheader("Full Subcategory Table")
    st.dataframe(
        subcat_df.rename(columns={"subcategory": "Subcategory", "doc_count": "Documents"}),
        use_container_width=True,
        hide_index=True,
    )

    # Download
    csv = subcat_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Subcategory Data as CSV",
        data=csv,
        file_name="subcategory_breakdown.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "Data sourced from documents, canonical_events, canonical_entities, "
    "bilateral_relationship_summaries, categories, and subcategories tables. "
    "Filtered by cfg.influencers and cfg.recipients."
)
