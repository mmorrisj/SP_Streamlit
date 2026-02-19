"""
Report Generator - Generate and export structured soft power reports via LLM.

Uses the FastAPI report generation endpoints to produce publication-quality reports
with strategic overviews, category narratives, event highlights, and entity profiles.
Supports Word document export.
"""

import streamlit as st
import pandas as pd
import requests
import os
import json
import io
from datetime import datetime, date, timedelta

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_engine
from shared.utils.utils import Config
from sqlalchemy import text

# Page configuration
st.set_page_config(
    page_title="Report Generator",
    page_icon="\U0001f4dd",
    layout="wide"
)

cfg = Config.from_yaml('shared/config/config.yaml')

API_URL = os.getenv('API_URL', 'http://localhost:5001')


# ---------- Cached helpers ----------

@st.cache_data(ttl=300)
def get_document_date_range():
    """Get the min and max document dates from the database."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM documents"
        )).fetchone()
    if row and row[0] and row[1]:
        return row[0], row[1]
    return date(2024, 8, 1), date.today()


@st.cache_data(ttl=300)
def get_recipient_list():
    """Get distinct recipient countries from the database."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT recipient_country FROM recipient_countries "
            "WHERE recipient_country IS NOT NULL ORDER BY recipient_country"
        )).fetchall()
    return [r[0] for r in rows]


# ---------- Session state ----------

if "report_data" not in st.session_state:
    st.session_state["report_data"] = None

if "report_generating" not in st.session_state:
    st.session_state["report_generating"] = False


# ---------- Sidebar ----------

st.title("\U0001f4dd Report Generator")
st.markdown("Generate comprehensive, publication-quality soft power reports using LLM analysis. "
            "Reports include strategic overviews, category breakdowns, key events, and entity profiles.")

with st.sidebar:
    st.header("Report Parameters")

    country = st.selectbox(
        "Initiating Country",
        options=cfg.influencers,
        index=cfg.influencers.index("China") if "China" in cfg.influencers else 0,
    )

    recipients = ["All"] + get_recipient_list()
    recipient = st.selectbox(
        "Recipient Country",
        options=recipients,
        index=0,
    )

    min_date, max_date = get_document_date_range()

    st.markdown("#### Date Range")
    start_date = st.date_input(
        "Start Date",
        value=max(min_date, max_date - timedelta(days=90)),
        min_value=min_date,
        max_value=max_date,
        key="rg_start",
    )
    end_date = st.date_input(
        "End Date",
        value=max_date,
        min_value=min_date,
        max_value=max_date,
        key="rg_end",
    )

    model = st.selectbox(
        "LLM Model",
        options=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
        index=0,
    )

    top_events = st.slider("Top Events per Category", min_value=3, max_value=25, value=10)

    st.markdown("---")
    st.info(
        "Report generation involves multiple LLM calls and may take 30-60 seconds. "
        "The spinner will remain visible until the full report is ready."
    )


# ---------- Helpers ----------

def generate_report():
    """Call the FastAPI report generation endpoint."""
    payload = {
        "country": country,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "recipient": recipient,
        "top_events": top_events,
        "model": model,
    }
    try:
        resp = requests.post(
            f"{API_URL}/api/report/generate",
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": f"Could not connect to the API at {API_URL}. Is the FastAPI server running?"}
    except requests.exceptions.Timeout:
        return {"error": "Report generation timed out after 5 minutes. Try a shorter date range."}
    except requests.exceptions.HTTPError as exc:
        return {"error": f"API returned status {exc.response.status_code}: {exc.response.text[:500]}"}
    except Exception as exc:
        return {"error": f"Unexpected error: {exc}"}


def export_report_to_docx(report_data: dict) -> bytes:
    """Call the FastAPI export endpoint and return raw .docx bytes."""
    try:
        resp = requests.post(
            f"{API_URL}/api/report/export",
            json=report_data,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        return None


def render_report(report: dict):
    """Render the complete report using Streamlit markdown and components."""

    # ---- Title ----
    title = report.get("title", f"{country} Soft Power Report")
    st.markdown(f"# {title}")

    period_start = report.get("period_start", str(start_date))
    period_end = report.get("period_end", str(end_date))
    st.caption(f"Period: {period_start} to {period_end} | Model: {report.get('model', model)}")

    # ---- Top-level metrics ----
    metrics = report.get("metrics", {})
    if metrics:
        cols = st.columns(4)
        with cols[0]:
            st.metric("Total Documents", f"{metrics.get('total_documents', 0):,}")
        with cols[1]:
            st.metric("Total Events", f"{metrics.get('total_events', 0):,}")
        with cols[2]:
            st.metric("Categories", metrics.get("categories_covered", ""))
        with cols[3]:
            st.metric("Date Span", f"{metrics.get('date_span_days', '')} days")

    st.markdown("---")

    # ---- Strategic overview ----
    strategic_overview = report.get("strategic_overview", "")
    if strategic_overview:
        st.markdown("## Strategic Overview")
        st.markdown(strategic_overview)
        st.markdown("---")

    # ---- Category sections ----
    categories = report.get("categories", [])
    if categories:
        st.markdown("## Category Analysis")

        for cat_section in categories:
            cat_name = cat_section.get("category", "Unknown")
            cat_doc_count = cat_section.get("document_count", 0)

            st.markdown(f"### {cat_name} ({cat_doc_count:,} documents)")

            # Narrative
            narrative = cat_section.get("narrative", "")
            if narrative:
                st.markdown(narrative)

            # Events within this category
            events = cat_section.get("events", [])
            if events:
                with st.expander(f"Key Events ({len(events)})", expanded=False):
                    for evt in events:
                        evt_name = evt.get("event_name", evt.get("name", "Unnamed Event"))
                        evt_date = evt.get("date", evt.get("period_start", ""))
                        evt_docs = evt.get("document_count", evt.get("total_documents", 0))
                        evt_summary = evt.get("summary", evt.get("narrative", ""))

                        st.markdown(f"**{evt_name}**")
                        if evt_date:
                            st.caption(f"Date: {evt_date} | Documents: {evt_docs}")
                        if evt_summary:
                            st.markdown(evt_summary)

                        # Entities mentioned in this event
                        entities = evt.get("entities_mentioned", [])
                        if entities:
                            entity_names = []
                            for ent in entities:
                                if isinstance(ent, dict):
                                    entity_names.append(ent.get("name", str(ent)))
                                else:
                                    entity_names.append(str(ent))
                            if entity_names:
                                st.markdown(f"*Entities: {', '.join(entity_names[:10])}*")

                        # Citations
                        citations = evt.get("citations", [])
                        if citations:
                            with st.expander(f"Citations ({len(citations)})"):
                                for cit in citations:
                                    if isinstance(cit, dict):
                                        cit_text = cit.get("text", cit.get("title", str(cit)))
                                        cit_link = cit.get("link", cit.get("url", ""))
                                        if cit_link:
                                            st.markdown(f"- [{cit_text}]({cit_link})")
                                        else:
                                            st.markdown(f"- {cit_text}")
                                    else:
                                        st.markdown(f"- {cit}")

                        st.markdown("---")

            # Subcategory breakdown
            subcategories = cat_section.get("subcategories", {})
            if subcategories and isinstance(subcategories, dict):
                with st.expander("Subcategory Breakdown"):
                    sub_df = pd.DataFrame([
                        {"Subcategory": k, "Documents": v}
                        for k, v in sorted(subcategories.items(), key=lambda x: x[1], reverse=True)
                    ])
                    st.dataframe(sub_df, use_container_width=True, hide_index=True)

            st.markdown("---")

    # ---- Key entities ----
    key_entities = report.get("key_entities", [])
    if key_entities:
        st.markdown("## Key Entities")
        for ent in key_entities:
            if isinstance(ent, dict):
                ent_name = ent.get("name", "Unknown")
                ent_type = ent.get("entity_type", ent.get("type", ""))
                ent_role = ent.get("role", ent.get("primary_role", ""))
                ent_mentions = ent.get("mentions", ent.get("document_count", ""))
                label_parts = [ent_name]
                if ent_type:
                    label_parts.append(f"({ent_type})")
                if ent_role:
                    label_parts.append(f"-- {ent_role}")
                if ent_mentions:
                    label_parts.append(f"[{ent_mentions} mentions]")
                st.markdown(f"- {' '.join(label_parts)}")
            else:
                st.markdown(f"- {ent}")

    # ---- Raw JSON (collapsible) ----
    with st.expander("Raw Report JSON"):
        st.json(report)


# ---------- Main area ----------

col_gen, col_exp = st.columns([1, 1])

with col_gen:
    generate_clicked = st.button(
        "Generate Report",
        type="primary",
        use_container_width=True,
        disabled=st.session_state["report_generating"],
    )

with col_exp:
    export_disabled = st.session_state["report_data"] is None
    export_clicked = st.button(
        "Export to Word (.docx)",
        use_container_width=True,
        disabled=export_disabled,
    )

# ---- Generate ----
if generate_clicked:
    st.session_state["report_generating"] = True
    with st.spinner(f"Generating {country} report for {start_date} to {end_date} using {model}... "
                    "This may take 30-60 seconds."):
        result = generate_report()

    st.session_state["report_generating"] = False

    if "error" in result:
        st.error(result["error"])
        st.session_state["report_data"] = None
    else:
        st.session_state["report_data"] = result
        st.success("Report generated successfully.")
        st.rerun()

# ---- Export ----
if export_clicked and st.session_state["report_data"] is not None:
    with st.spinner("Exporting report to Word document..."):
        docx_bytes = export_report_to_docx(st.session_state["report_data"])
    if docx_bytes:
        filename = f"{country}_Report_{start_date}.docx"
        st.download_button(
            label="Download .docx",
            data=docx_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    else:
        st.error("Failed to export report. Check that the FastAPI server is running.")

# ---- Render stored report ----
if st.session_state["report_data"] is not None:
    st.markdown("---")
    render_report(st.session_state["report_data"])
