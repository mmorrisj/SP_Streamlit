"""
Country Comparison Dashboard

Side-by-side comparison of influencer countries with KPIs, shared recipient analysis,
and category mix visualizations.
"""

import datetime as dt
import pandas as pd
import altair as alt
import streamlit as st
from sqlalchemy import text
from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Country Comparison", page_icon="⚖️", layout="wide")
st.title("⚖️ Country Comparison")
st.caption("Compare influencer countries across document volume, events, materiality, and category deployment")

# ---------------------------------------------------------------------------
# Query Functions
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_country_kpis(countries, start_date, end_date, recipients):
    """Total docs, canonical events, and avg materiality per influencer."""
    engine = get_engine()
    query = text("""
        SELECT
            ic.initiating_country,
            COUNT(DISTINCT d.doc_id) AS total_docs
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY ic.initiating_country
        ORDER BY total_docs DESC
    """)
    with engine.connect() as conn:
        docs_df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(recipients), "start_date": start_date, "end_date": end_date},
        )

    event_query = text("""
        SELECT
            initiating_country,
            COUNT(*) AS total_events,
            AVG(CAST(material_score AS FLOAT)) AS avg_materiality
        FROM canonical_events
        WHERE initiating_country IN :countries
          AND master_event_id IS NULL
          AND first_mention_date >= :start_date
          AND last_mention_date <= :end_date
        GROUP BY initiating_country
    """)
    with engine.connect() as conn:
        events_df = pd.read_sql(
            event_query, conn,
            params={"countries": tuple(countries), "start_date": start_date, "end_date": end_date},
        )

    merged = docs_df.merge(events_df, on="initiating_country", how="left").fillna(0)
    return merged


@st.cache_data(ttl=300, show_spinner=False)
def get_shared_recipients(countries, start_date, end_date, recipients):
    """Which recipients are targeted by multiple influencers."""
    engine = get_engine()
    query = text("""
        SELECT
            rc.recipient_country,
            ic.initiating_country,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY rc.recipient_country, ic.initiating_country
        ORDER BY rc.recipient_country, doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={
                "countries": tuple(countries),
                "recipients": tuple(recipients),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_category_comparison(countries, start_date, end_date, recipients):
    """Category counts per influencer."""
    engine = get_engine()
    query = text("""
        SELECT
            ic.initiating_country,
            c.category,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY ic.initiating_country, c.category
        ORDER BY ic.initiating_country, doc_count DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(recipients), "start_date": start_date, "end_date": end_date},
        )
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_monthly_comparison(countries, start_date, end_date, recipients):
    """Monthly document trend per influencer."""
    engine = get_engine()
    query = text("""
        SELECT
            DATE_TRUNC('month', d.date)::date AS month,
            ic.initiating_country,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country IN :countries
          AND rc.recipient_country IN :recipients
          AND ic.initiating_country != rc.recipient_country
          AND d.date BETWEEN :start_date AND :end_date
        GROUP BY DATE_TRUNC('month', d.date), ic.initiating_country
        ORDER BY month
    """)
    with engine.connect() as conn:
        df = pd.read_sql(
            query, conn,
            params={"countries": tuple(countries), "recipients": tuple(recipients), "start_date": start_date, "end_date": end_date},
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

if not selected_countries or len(selected_countries) < 1:
    st.info("Please select at least one influencer country.")
    st.stop()

# ---------------------------------------------------------------------------
# KPI Comparison
# ---------------------------------------------------------------------------
st.header("Key Metrics by Country")

kpi_df = get_country_kpis(selected_countries, start_date, end_date, cfg.recipients)

if kpi_df.empty:
    st.warning("No data found for the selected countries and date range.")
    st.stop()

# Dynamic columns based on number of countries
cols = st.columns(len(kpi_df))
for idx, (_, row) in enumerate(kpi_df.iterrows()):
    with cols[idx]:
        st.subheader(row["initiating_country"])
        st.metric("Documents", f"{int(row['total_docs']):,}")
        st.metric("Events", f"{int(row['total_events']):,}")
        avg_mat = row["avg_materiality"]
        st.metric("Avg Materiality", f"{avg_mat:.1f}" if avg_mat else "N/A")

st.divider()

# ---------------------------------------------------------------------------
# KPI Bar Charts Side by Side
# ---------------------------------------------------------------------------
st.header("Comparative Bar Charts")

col_docs, col_events, col_mat = st.columns(3)

with col_docs:
    doc_chart = (
        alt.Chart(kpi_df)
        .mark_bar()
        .encode(
            x=alt.X("initiating_country:N", title="Country", sort="-y"),
            y=alt.Y("total_docs:Q", title="Documents"),
            color=alt.Color("initiating_country:N", legend=None),
            tooltip=["initiating_country:N", "total_docs:Q"],
        )
        .properties(height=300, title="Total Documents")
    )
    st.altair_chart(doc_chart, use_container_width=True)

with col_events:
    event_chart = (
        alt.Chart(kpi_df)
        .mark_bar()
        .encode(
            x=alt.X("initiating_country:N", title="Country", sort="-y"),
            y=alt.Y("total_events:Q", title="Events"),
            color=alt.Color("initiating_country:N", legend=None),
            tooltip=["initiating_country:N", "total_events:Q"],
        )
        .properties(height=300, title="Canonical Events")
    )
    st.altair_chart(event_chart, use_container_width=True)

with col_mat:
    mat_chart = (
        alt.Chart(kpi_df)
        .mark_bar()
        .encode(
            x=alt.X("initiating_country:N", title="Country", sort="-y"),
            y=alt.Y("avg_materiality:Q", title="Avg Materiality", scale=alt.Scale(domain=[0, 10])),
            color=alt.Color("initiating_country:N", legend=None),
            tooltip=[
                alt.Tooltip("initiating_country:N", title="Country"),
                alt.Tooltip("avg_materiality:Q", title="Avg Materiality", format=".2f"),
            ],
        )
        .properties(height=300, title="Avg Materiality Score")
    )
    st.altair_chart(mat_chart, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Shared Recipients Analysis
# ---------------------------------------------------------------------------
st.header("Shared Recipients Analysis")
st.markdown("Which recipients are targeted by multiple influencers, and how much attention each gives them.")

shared_df = get_shared_recipients(selected_countries, start_date, end_date, cfg.recipients)

if shared_df.empty:
    st.info("No shared recipient data found.")
else:
    # Identify recipients targeted by more than one selected influencer
    recipient_influencer_counts = shared_df.groupby("recipient_country")["initiating_country"].nunique().reset_index()
    recipient_influencer_counts.columns = ["recipient_country", "influencer_count"]
    multi_target = recipient_influencer_counts[recipient_influencer_counts["influencer_count"] > 1]

    if multi_target.empty:
        st.info("No recipients are targeted by more than one selected influencer.")
    else:
        shared_recipients = multi_target["recipient_country"].tolist()
        shared_subset = shared_df[shared_df["recipient_country"].isin(shared_recipients)]

        shared_chart = (
            alt.Chart(shared_subset)
            .mark_bar()
            .encode(
                x=alt.X("doc_count:Q", title="Documents", stack="zero"),
                y=alt.Y(
                    "recipient_country:N",
                    title="Recipient",
                    sort=alt.EncodingSortField(field="doc_count", op="sum", order="descending"),
                ),
                color=alt.Color("initiating_country:N", legend=alt.Legend(title="Influencer")),
                tooltip=["recipient_country:N", "initiating_country:N", "doc_count:Q"],
            )
            .properties(
                height=max(250, len(shared_recipients) * 35),
                title="Shared Recipients: Document Volume by Influencer",
            )
        )
        st.altair_chart(shared_chart, use_container_width=True)

    # Full pivot table
    st.subheader("Full Recipient-Influencer Matrix")
    pivot = shared_df.pivot_table(
        values="doc_count", index="recipient_country", columns="initiating_country", fill_value=0
    )
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    st.dataframe(pivot, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Category Comparison (Stacked Bar)
# ---------------------------------------------------------------------------
st.header("Category Mix Comparison")

cat_df = get_category_comparison(selected_countries, start_date, end_date, cfg.recipients)

if cat_df.empty:
    st.info("No category data found.")
else:
    stacked_cat = (
        alt.Chart(cat_df)
        .mark_bar()
        .encode(
            x=alt.X("doc_count:Q", title="Documents", stack="normalize"),
            y=alt.Y(
                "initiating_country:N",
                title="Influencer",
                sort=alt.EncodingSortField(field="doc_count", op="sum", order="descending"),
            ),
            color=alt.Color("category:N", legend=alt.Legend(title="Category")),
            tooltip=["initiating_country:N", "category:N", "doc_count:Q"],
        )
        .properties(height=max(200, len(selected_countries) * 50), title="Normalized Category Distribution per Influencer")
    )
    st.altair_chart(stacked_cat, use_container_width=True)

    # Absolute stacked bar
    abs_cat = (
        alt.Chart(cat_df)
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
        .properties(height=max(200, len(selected_countries) * 50), title="Absolute Category Volumes per Influencer")
    )
    st.altair_chart(abs_cat, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Monthly Trend Comparison
# ---------------------------------------------------------------------------
st.header("Monthly Activity Trends")

monthly_df = get_monthly_comparison(selected_countries, start_date, end_date, cfg.recipients)

if monthly_df.empty:
    st.info("No monthly trend data available.")
else:
    trend_chart = (
        alt.Chart(monthly_df)
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
    st.altair_chart(trend_chart, use_container_width=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption("Comparison uses documents, canonical_events, categories, initiating_countries, and recipient_countries tables.")
