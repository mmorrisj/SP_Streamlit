"""
Data Quality Dashboard - Pipeline health metrics, coverage stats, and freshness alerts.

All queries use raw SQL via get_engine() for direct, efficient access to every
table in the Soft Power database.
"""

import streamlit as st
import pandas as pd
import altair as alt
import os
from datetime import datetime, date, timedelta

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_engine
from shared.utils.utils import Config
from sqlalchemy import text

# Page configuration
st.set_page_config(
    page_title="Data Quality Dashboard",
    page_icon="\U0001f527",
    layout="wide"
)

cfg = Config.from_yaml('shared/config/config.yaml')


# ==========================================================================
#  Cached query functions
# ==========================================================================

@st.cache_data(ttl=300)
def get_total_documents() -> int:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(DISTINCT doc_id) FROM documents")).fetchone()
    return row[0] if row else 0


@st.cache_data(ttl=300)
def get_total_events() -> int:
    """Count master canonical events (those without a master_event_id)."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NULL"
        )).fetchone()
    return row[0] if row else 0


@st.cache_data(ttl=300)
def get_total_entities() -> int:
    """Count master canonical entities (those without a master_entity_id)."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM canonical_entities WHERE master_entity_id IS NULL"
        )).fetchone()
    return row[0] if row else 0


@st.cache_data(ttl=300)
def get_total_embeddings() -> int:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM langchain_pg_embedding")).fetchone()
    return row[0] if row else 0


# ---------- Section 1: Document Ingestion ----------

@st.cache_data(ttl=300)
def get_latest_document_date():
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT MAX(date) FROM documents")).fetchone()
    return row[0] if row and row[0] else None


@st.cache_data(ttl=300)
def get_documents_per_day_last_30() -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT date, COUNT(DISTINCT doc_id) AS doc_count "
            "FROM documents "
            "WHERE date >= current_date - 30 "
            "GROUP BY date "
            "ORDER BY date"
        )).fetchall()
    if rows:
        return pd.DataFrame(rows, columns=["date", "doc_count"])
    return pd.DataFrame(columns=["date", "doc_count"])


# ---------- Section 2: Embedding Coverage ----------

@st.cache_data(ttl=300)
def get_embedding_count() -> int:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM langchain_pg_embedding")).fetchone()
    return row[0] if row else 0


# ---------- Section 3: Entity Coverage ----------

@st.cache_data(ttl=300)
def get_entity_coverage() -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        total = conn.execute(text(
            "SELECT COUNT(*) FROM canonical_entities WHERE master_entity_id IS NULL"
        )).fetchone()[0]

        with_desc = conn.execute(text(
            "SELECT COUNT(*) FROM canonical_entities "
            "WHERE master_entity_id IS NULL AND entity_description IS NOT NULL"
        )).fetchone()[0]

        with_embed = conn.execute(text(
            "SELECT COUNT(*) FROM canonical_entities "
            "WHERE master_entity_id IS NULL AND embedding_vector IS NOT NULL"
        )).fetchone()[0]

    return {
        "total": total or 0,
        "with_description": with_desc or 0,
        "with_embedding": with_embed or 0,
    }


# ---------- Section 4: Event Processing ----------

@st.cache_data(ttl=300)
def get_event_processing_status() -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        master_events = conn.execute(text(
            "SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NULL"
        )).fetchone()[0] or 0

        child_events = conn.execute(text(
            "SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NOT NULL"
        )).fetchone()[0] or 0

        daily_mentions = conn.execute(text(
            "SELECT COUNT(*) FROM daily_event_mentions"
        )).fetchone()[0] or 0

        # Event summaries by period type
        summary_rows = conn.execute(text(
            "SELECT period_type, COUNT(*) AS cnt "
            "FROM event_summaries "
            "GROUP BY period_type "
            "ORDER BY period_type"
        )).fetchall()

    summaries_by_type = {r[0]: r[1] for r in summary_rows} if summary_rows else {}

    return {
        "master_events": master_events,
        "child_events": child_events,
        "daily_mentions": daily_mentions,
        "summaries_by_type": summaries_by_type,
    }


# ---------- Section 5: Bilateral Summaries ----------

@st.cache_data(ttl=300)
def get_bilateral_status() -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        bilateral = conn.execute(text(
            "SELECT COUNT(*) FROM bilateral_relationship_summaries WHERE is_deleted = false"
        )).fetchone()[0] or 0

        country_cat = conn.execute(text(
            "SELECT COUNT(*) FROM country_category_summaries WHERE is_deleted = false"
        )).fetchone()[0] or 0

        bilateral_cat = conn.execute(text(
            "SELECT COUNT(*) FROM bilateral_category_summaries WHERE is_deleted = false"
        )).fetchone()[0] or 0

        avg_mat = conn.execute(text(
            "SELECT AVG(material_score) FROM bilateral_relationship_summaries "
            "WHERE is_deleted = false AND material_score IS NOT NULL"
        )).fetchone()[0]

    return {
        "bilateral_summaries": bilateral,
        "country_category_summaries": country_cat,
        "bilateral_category_summaries": bilateral_cat,
        "avg_material_score": round(float(avg_mat), 3) if avg_mat else 0.0,
    }


# ---------- Section 6: Freshness ----------

@st.cache_data(ttl=300)
def get_freshness_alerts() -> dict:
    engine = get_engine()
    with engine.connect() as conn:
        last_doc_date = conn.execute(text(
            "SELECT MAX(date) FROM documents"
        )).fetchone()[0]

        last_event_summary = conn.execute(text(
            "SELECT MAX(created_at) FROM event_summaries"
        )).fetchone()[0]

    today = date.today()
    days_since_doc = (today - last_doc_date).days if last_doc_date else None
    days_since_event = (today - last_event_summary.date()).days if last_event_summary else None

    return {
        "last_document_date": last_doc_date,
        "last_event_summary_date": last_event_summary,
        "days_since_last_document": days_since_doc,
        "days_since_last_event_summary": days_since_event,
    }


def freshness_color(days):
    """Return a color indicator based on the number of days."""
    if days is None:
        return "inverse"
    if days < 3:
        return "normal"      # green delta
    if days <= 7:
        return "off"         # yellow / grey
    return "inverse"         # red


def freshness_label(days):
    if days is None:
        return "N/A"
    if days < 3:
        return "Fresh"
    if days <= 7:
        return "Aging"
    return "Stale"


# ==========================================================================
#  Page Layout
# ==========================================================================

st.title("\U0001f527 Data Quality Dashboard")
st.markdown("Pipeline health metrics, coverage statistics, and data freshness alerts.")

# --- KPI row ---
st.markdown("---")

kpi1, kpi2, kpi3, kpi4 = st.columns(4)

total_docs = get_total_documents()
total_events = get_total_events()
total_entities = get_total_entities()
total_embeds = get_total_embeddings()

with kpi1:
    st.metric("Total Documents", f"{total_docs:,}")
with kpi2:
    st.metric("Total Events (Master)", f"{total_events:,}")
with kpi3:
    st.metric("Total Entities (Master)", f"{total_entities:,}")
with kpi4:
    st.metric("Total Embeddings", f"{total_embeds:,}")

st.markdown("---")

# ==========================================================================
# Section 1: Document Ingestion Status
# ==========================================================================

st.markdown("## 1. Document Ingestion Status")

latest_date = get_latest_document_date()

col_a, col_b = st.columns(2)
with col_a:
    st.metric("Total Documents", f"{total_docs:,}")
with col_b:
    st.metric("Latest Document Date", str(latest_date) if latest_date else "N/A")

df_daily = get_documents_per_day_last_30()

if not df_daily.empty:
    df_daily["date"] = pd.to_datetime(df_daily["date"])
    chart = (
        alt.Chart(df_daily)
        .mark_line(point=True, color="#4F8BF9")
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("doc_count:Q", title="Documents Ingested"),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("doc_count:Q", title="Documents"),
            ],
        )
        .properties(height=300, title="Documents Ingested Per Day (Last 30 Days)")
    )
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No documents ingested in the last 30 days.")

st.markdown("---")

# ==========================================================================
# Section 2: Embedding Coverage
# ==========================================================================

st.markdown("## 2. Embedding Coverage")

embed_count = get_embedding_count()
docs_without = max(total_docs - embed_count, 0)
coverage_pct = (embed_count / total_docs * 100) if total_docs > 0 else 0.0

col_e1, col_e2, col_e3 = st.columns(3)
with col_e1:
    st.metric("Documents with Embeddings", f"{embed_count:,}")
with col_e2:
    st.metric("Documents without Embeddings", f"{docs_without:,}")
with col_e3:
    st.metric("Coverage", f"{coverage_pct:.1f}%")

if total_docs > 0:
    progress_val = min(embed_count / total_docs, 1.0)
    st.progress(progress_val, text=f"{coverage_pct:.1f}% embedding coverage")

st.markdown("---")

# ==========================================================================
# Section 3: Entity Coverage
# ==========================================================================

st.markdown("## 3. Entity Coverage")

ent_cov = get_entity_coverage()

col_n1, col_n2, col_n3 = st.columns(3)

with col_n1:
    st.metric("Total Entities (Master)", f"{ent_cov['total']:,}")

with col_n2:
    desc_pct = (ent_cov["with_description"] / ent_cov["total"] * 100) if ent_cov["total"] > 0 else 0.0
    st.metric(
        "With Descriptions",
        f"{ent_cov['with_description']:,}",
        delta=f"{desc_pct:.1f}%",
    )

with col_n3:
    emb_pct = (ent_cov["with_embedding"] / ent_cov["total"] * 100) if ent_cov["total"] > 0 else 0.0
    st.metric(
        "With Embeddings",
        f"{ent_cov['with_embedding']:,}",
        delta=f"{emb_pct:.1f}%",
    )

if ent_cov["total"] > 0:
    ent_df = pd.DataFrame([
        {"Metric": "Has Description", "Count": ent_cov["with_description"],
         "Missing": ent_cov["total"] - ent_cov["with_description"]},
        {"Metric": "Has Embedding", "Count": ent_cov["with_embedding"],
         "Missing": ent_cov["total"] - ent_cov["with_embedding"]},
    ])
    st.dataframe(ent_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ==========================================================================
# Section 4: Event Processing Status
# ==========================================================================

st.markdown("## 4. Event Processing Status")

evt_status = get_event_processing_status()

col_v1, col_v2, col_v3 = st.columns(3)
with col_v1:
    st.metric("Master Canonical Events", f"{evt_status['master_events']:,}")
with col_v2:
    st.metric("Child Canonical Events", f"{evt_status['child_events']:,}")
with col_v3:
    st.metric("Daily Event Mentions", f"{evt_status['daily_mentions']:,}")

summaries = evt_status["summaries_by_type"]
if summaries:
    st.markdown("#### Event Summaries by Period Type")
    summary_df = pd.DataFrame([
        {"Period Type": k, "Count": v}
        for k, v in sorted(summaries.items())
    ])
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    total_summaries = sum(summaries.values())
    st.metric("Total Event Summaries", f"{total_summaries:,}")
else:
    st.info("No event summaries found in the database.")

st.markdown("---")

# ==========================================================================
# Section 5: Bilateral Summaries Status
# ==========================================================================

st.markdown("## 5. Bilateral Summaries Status")

bi_status = get_bilateral_status()

col_b1, col_b2, col_b3, col_b4 = st.columns(4)
with col_b1:
    st.metric("Bilateral Summaries", f"{bi_status['bilateral_summaries']:,}")
with col_b2:
    st.metric("Country-Category Summaries", f"{bi_status['country_category_summaries']:,}")
with col_b3:
    st.metric("Bilateral-Category Summaries", f"{bi_status['bilateral_category_summaries']:,}")
with col_b4:
    st.metric("Avg Material Score", f"{bi_status['avg_material_score']:.3f}")

st.markdown("---")

# ==========================================================================
# Section 6: Data Freshness Alerts
# ==========================================================================

st.markdown("## 6. Data Freshness Alerts")

freshness = get_freshness_alerts()

col_f1, col_f2 = st.columns(2)

with col_f1:
    days_doc = freshness["days_since_last_document"]
    st.metric(
        "Days Since Last Document",
        days_doc if days_doc is not None else "N/A",
    )
    if days_doc is not None:
        if days_doc < 3:
            st.success(f"Document pipeline is fresh (last document: {freshness['last_document_date']})")
        elif days_doc <= 7:
            st.warning(f"Document pipeline is aging -- last document {days_doc} days ago ({freshness['last_document_date']})")
        else:
            st.error(f"Document pipeline is stale -- no new documents in {days_doc} days (last: {freshness['last_document_date']})")
    else:
        st.error("No documents found in the database.")

with col_f2:
    days_evt = freshness["days_since_last_event_summary"]
    st.metric(
        "Days Since Last Event Summary",
        days_evt if days_evt is not None else "N/A",
    )
    if days_evt is not None:
        if days_evt < 3:
            st.success(f"Event pipeline is fresh (last summary: {freshness['last_event_summary_date']})")
        elif days_evt <= 7:
            st.warning(f"Event pipeline is aging -- last summary {days_evt} days ago ({freshness['last_event_summary_date']})")
        else:
            st.error(f"Event pipeline is stale -- no new summaries in {days_evt} days (last: {freshness['last_event_summary_date']})")
    else:
        st.error("No event summaries found in the database.")

# ---------- Refresh button ----------
st.markdown("---")
if st.button("Refresh All Metrics", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
