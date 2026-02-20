"""
Source Intelligence Dashboard

Analyze the media sources behind soft power coverage: top sources by volume,
medium breakdown, and source diversity per influencer country.
"""

import datetime as dt
import pandas as pd
import altair as alt
import streamlit as st
from sqlalchemy import text
from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Source Intelligence", page_icon="📡", layout="wide")
st.title("📡 Source Intelligence")
st.caption("Understand the media landscape: which sources drive coverage and how diverse is each country's media footprint")

# ---------------------------------------------------------------------------
# Query Functions
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_top_sources(countries, start_date, end_date, limit=30):
    """Top sources by document volume."""
    engine = get_engine()
    query = text("""
        SELECT
            d.source_name,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
          AND d.source_name IS NOT NULL
        GROUP BY d.source_name
        ORDER BY doc_count DESC
        LIMIT :lim
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={
                "countries": tuple(countries),
                "recipients": tuple(cfg.recipients),
                "start_date": start_date,
                "end_date": end_date,
                "lim": limit,
            },
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_top_sources_by_country(countries, start_date, end_date, limit=10):
    """Top sources per country."""
    engine = get_engine()
    query = text("""
        SELECT
            ic.initiating_country,
            d.source_name,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
          AND d.source_name IS NOT NULL
        GROUP BY ic.initiating_country, d.source_name
        ORDER BY ic.initiating_country, doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={
                "countries": tuple(countries),
                "recipients": tuple(cfg.recipients),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
    # Keep only top N per country
    result = df.groupby("initiating_country").head(limit).reset_index(drop=True)
    return result


@st.cache_data(ttl=300, show_spinner=False)
def get_medium_breakdown(countries, start_date, end_date):
    """Source medium distribution."""
    engine = get_engine()
    query = text("""
        SELECT
            COALESCE(d.source_medium, 'Unknown') AS source_medium,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY COALESCE(d.source_medium, 'Unknown')
        ORDER BY doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(cfg.recipients), "start_date": start_date, "end_date": end_date},
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_medium_by_country(countries, start_date, end_date):
    """Source medium per influencer country."""
    engine = get_engine()
    query = text("""
        SELECT
            ic.initiating_country,
            COALESCE(d.source_medium, 'Unknown') AS source_medium,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY ic.initiating_country, COALESCE(d.source_medium, 'Unknown')
        ORDER BY ic.initiating_country, doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(cfg.recipients), "start_date": start_date, "end_date": end_date},
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_source_diversity(countries, start_date, end_date):
    """Count of distinct sources and documents per influencer country."""
    engine = get_engine()
    query = text("""
        SELECT
            ic.initiating_country,
            COUNT(DISTINCT d.source_name) AS unique_sources,
            COUNT(DISTINCT d.doc_id) AS total_docs
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
          AND d.source_name IS NOT NULL
        GROUP BY ic.initiating_country
        ORDER BY unique_sources DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(cfg.recipients), "start_date": start_date, "end_date": end_date},
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_source_geofocus_breakdown(countries, start_date, end_date):
    """Source geographic focus distribution."""
    engine = get_engine()
    query = text("""
        SELECT
            COALESCE(d.source_geofocus, 'Unknown') AS source_geofocus,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY COALESCE(d.source_geofocus, 'Unknown')
        ORDER BY doc_count DESC
        LIMIT 20
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(cfg.recipients), "start_date": start_date, "end_date": end_date},
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_monthly_source_trend(countries, start_date, end_date):
    """Monthly unique source count."""
    engine = get_engine()
    query = text("""
        SELECT
            DATE_TRUNC('month', d.date)::date AS month,
            COUNT(DISTINCT d.source_name) AS unique_sources,
            COUNT(DISTINCT d.doc_id) AS total_docs
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
          AND d.source_name IS NOT NULL
        GROUP BY DATE_TRUNC('month', d.date)
        ORDER BY month
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(cfg.recipients), "start_date": start_date, "end_date": end_date},
        )
    return df


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")

    selected_countries = st.multiselect(
        "Influencer Countries",
        options=cfg.influencers,
        default=cfg.influencers,
    )

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=dt.date(2024, 1, 1))
    with col2:
        end_date = st.date_input("End Date", value=dt.date.today())

    top_n = st.slider("Top N Sources", 10, 50, 25)

if not selected_countries:
    st.info("Please select at least one influencer country.")
    st.stop()

# ---------------------------------------------------------------------------
# KPI Row
# ---------------------------------------------------------------------------
diversity_df = get_source_diversity(selected_countries, start_date, end_date)
medium_df = get_medium_breakdown(selected_countries, start_date, end_date)

total_unique_sources = diversity_df["unique_sources"].sum() if not diversity_df.empty else 0
total_documents = diversity_df["total_docs"].sum() if not diversity_df.empty else 0
total_mediums = len(medium_df) if not medium_df.empty else 0
avg_docs_per_source = total_documents / total_unique_sources if total_unique_sources > 0 else 0

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Unique Sources", f"{total_unique_sources:,}")
with k2:
    st.metric("Total Documents", f"{total_documents:,}")
with k3:
    st.metric("Source Mediums", total_mediums)
with k4:
    st.metric("Avg Docs/Source", f"{avg_docs_per_source:.1f}")

st.divider()

# ---------------------------------------------------------------------------
# Top Sources by Volume
# ---------------------------------------------------------------------------
st.header("Top Sources by Volume")

top_sources_df = get_top_sources(selected_countries, start_date, end_date, limit=top_n)

if top_sources_df.empty:
    st.info("No source data found.")
else:
    source_bar = (
        alt.Chart(top_sources_df)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Documents"),
            y=alt.Y(
                "source_name:N",
                title="Source",
                sort=alt.EncodingSortField(field="doc_count", order="descending"),
            ),
            color=alt.Color("doc_count:Q", scale=alt.Scale(scheme="blues"), legend=None),
            tooltip=[
                alt.Tooltip("source_name:N", title="Source"),
                alt.Tooltip("doc_count:Q", title="Documents"),
            ],
        )
        .properties(height=max(400, len(top_sources_df) * 22), title=f"Top {top_n} Sources by Document Volume")
    )
    st.altair_chart(source_bar, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Source Medium Breakdown
# ---------------------------------------------------------------------------
st.header("Source Medium Breakdown")

col_pie, col_bar = st.columns(2)

with col_pie:
    if medium_df.empty:
        st.info("No medium data available.")
    else:
        medium_pie = (
            alt.Chart(medium_df)
            .mark_arc(innerRadius=50)
            .encode(
                theta=alt.Theta("doc_count:Q"),
                color=alt.Color("source_medium:N", legend=alt.Legend(title="Medium")),
                tooltip=["source_medium:N", "doc_count:Q"],
            )
            .properties(height=400, title="Document Share by Medium")
        )
        st.altair_chart(medium_pie, use_container_width=True)

with col_bar:
    if medium_df.empty:
        st.info("No medium data available.")
    else:
        medium_bar = (
            alt.Chart(medium_df)
            .mark_bar()
            .encode(
                x=alt.X("doc_count:Q", title="Documents"),
                y=alt.Y("source_medium:N", title="Medium", sort="-x"),
                color=alt.Color("source_medium:N", legend=None),
                tooltip=["source_medium:N", "doc_count:Q"],
            )
            .properties(height=max(200, len(medium_df) * 35), title="Documents by Medium")
        )
        st.altair_chart(medium_bar, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Medium by Country (stacked)
# ---------------------------------------------------------------------------
st.header("Medium Distribution by Country")

medium_country_df = get_medium_by_country(selected_countries, start_date, end_date)

if medium_country_df.empty:
    st.info("No data available.")
else:
    medium_country_chart = (
        alt.Chart(medium_country_df)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Documents", stack="normalize"),
            y=alt.Y(
                "initiating_country:N",
                title="Influencer",
                sort=alt.EncodingSortField(field="doc_count", op="sum", order="descending"),
            ),
            color=alt.Color("source_medium:N", legend=alt.Legend(title="Medium")),
            tooltip=["initiating_country:N", "source_medium:N", "doc_count:Q"],
        )
        .properties(
            height=max(200, len(selected_countries) * 50),
            title="Normalized Medium Mix per Influencer",
        )
    )
    st.altair_chart(medium_country_chart, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Source Diversity per Country
# ---------------------------------------------------------------------------
st.header("Source Diversity per Country")

if diversity_df.empty:
    st.info("No diversity data available.")
else:
    diversity_df["docs_per_source"] = (
        diversity_df["total_docs"] / diversity_df["unique_sources"]
    ).round(1)

    div_chart = (
        alt.Chart(diversity_df)
        .mark_bar()
        .encode(
            x=alt.X("unique_sources:Q", title="Unique Sources"),
            y=alt.Y(
                "initiating_country:N",
                title="Country",
                sort=alt.EncodingSortField(field="unique_sources", order="descending"),
            ),
            color=alt.Color("initiating_country:N", legend=None),
            tooltip=[
                alt.Tooltip("initiating_country:N", title="Country"),
                alt.Tooltip("unique_sources:Q", title="Unique Sources"),
                alt.Tooltip("total_docs:Q", title="Total Docs"),
                alt.Tooltip("docs_per_source:Q", title="Docs/Source"),
            ],
        )
        .properties(height=max(200, len(diversity_df) * 45), title="Source Diversity: Unique Sources per Country")
    )
    st.altair_chart(div_chart, use_container_width=True)

    # Show table
    st.dataframe(
        diversity_df.rename(columns={
            "initiating_country": "Country",
            "unique_sources": "Unique Sources",
            "total_docs": "Total Documents",
            "docs_per_source": "Avg Docs/Source",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Top Sources per Country
# ---------------------------------------------------------------------------
st.header("Top Sources per Country")

country_sources_df = get_top_sources_by_country(selected_countries, start_date, end_date, limit=10)

if country_sources_df.empty:
    st.info("No per-country source data.")
else:
    for country in selected_countries:
        subset = country_sources_df[country_sources_df["initiating_country"] == country]
        if subset.empty:
            continue
        with st.expander(f"{country} - Top {len(subset)} Sources"):
            cs_chart = (
                alt.Chart(subset)
                .mark_bar()
                .encode(
                    x=alt.X("doc_count:Q", title="Documents"),
                    y=alt.Y("source_name:N", title="Source", sort="-x"),
                    color=alt.Color("doc_count:Q", scale=alt.Scale(scheme="tealblues"), legend=None),
                    tooltip=["source_name:N", "doc_count:Q"],
                )
                .properties(height=max(200, len(subset) * 28))
            )
            st.altair_chart(cs_chart, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Source Geographic Focus
# ---------------------------------------------------------------------------
st.header("Source Geographic Focus")

geofocus_df = get_source_geofocus_breakdown(selected_countries, start_date, end_date)

if geofocus_df.empty:
    st.info("No geographic focus data available.")
else:
    geo_chart = (
        alt.Chart(geofocus_df)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Documents"),
            y=alt.Y("source_geofocus:N", title="Geographic Focus", sort="-x"),
            color=alt.Color("doc_count:Q", scale=alt.Scale(scheme="oranges"), legend=None),
            tooltip=["source_geofocus:N", "doc_count:Q"],
        )
        .properties(height=max(300, len(geofocus_df) * 25), title="Top Source Geographic Focus Areas")
    )
    st.altair_chart(geo_chart, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Monthly Source Trend
# ---------------------------------------------------------------------------
st.header("Monthly Source Trend")

monthly_src_df = get_monthly_source_trend(selected_countries, start_date, end_date)

if monthly_src_df.empty:
    st.info("No monthly trend data.")
else:
    base = alt.Chart(monthly_src_df).encode(x=alt.X("month:T", title="Month"))

    line_sources = base.mark_line(color="#1f77b4", point=True).encode(
        y=alt.Y("unique_sources:Q", title="Unique Sources"),
        tooltip=[
            alt.Tooltip("month:T", title="Month"),
            alt.Tooltip("unique_sources:Q", title="Unique Sources"),
            alt.Tooltip("total_docs:Q", title="Total Docs"),
        ],
    )

    line_docs = base.mark_line(color="#ff7f0e", strokeDash=[5, 3], point=True).encode(
        y=alt.Y("total_docs:Q", title="Total Documents"),
    )

    combined = alt.layer(line_sources, line_docs).resolve_scale(y="independent").properties(
        height=350,
        title="Monthly Unique Sources (blue) and Document Volume (orange)",
    )
    st.altair_chart(combined, use_container_width=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption("Source data from documents.source_name, documents.source_medium, and documents.source_geofocus columns.")
