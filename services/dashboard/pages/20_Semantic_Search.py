"""
Semantic Search - RAG-powered chat interface for querying soft power documents.

Provides a natural language search interface backed by the FastAPI RAG service
with entity-aware boosting, automatic filter inference, and source traceability.
"""

import streamlit as st
import pandas as pd
import requests
import os
import json
from datetime import datetime, date, timedelta

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_engine
from shared.utils.utils import Config
from sqlalchemy import text

# Page configuration
st.set_page_config(
    page_title="Semantic Search",
    page_icon="\U0001f50e",
    layout="wide"
)

cfg = Config.from_yaml('shared/config/config.yaml')

API_URL = os.getenv('API_URL', 'http://localhost:5001')


# ---------- Cached helpers ----------

@st.cache_data(ttl=300)
def get_category_list():
    """Fetch distinct categories from the database."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT category FROM categories WHERE category IS NOT NULL ORDER BY category"
        )).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=300)
def get_date_range():
    """Get the min and max document dates."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM documents"
        )).fetchone()
    if row and row[0] and row[1]:
        return row[0], row[1]
    return date(2024, 8, 1), date.today()


# ---------- Session state ----------

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

if "last_sources" not in st.session_state:
    st.session_state["last_sources"] = []

if "last_metadata" not in st.session_state:
    st.session_state["last_metadata"] = {}


# ---------- Sidebar ----------

st.title("\U0001f50e Semantic Search")
st.markdown("Ask natural-language questions about soft power documents. "
            "The RAG engine retrieves relevant sources, boosts entity-matched documents, "
            "and generates an answer with citations.")

with st.sidebar:
    st.header("Search Filters")
    st.caption("Optional -- the system also infers filters from your query automatically.")

    influencer_options = ["(auto-detect)"] + list(cfg.influencers)
    selected_country = st.selectbox("Initiating Country", options=influencer_options, index=0)

    category_options = ["(auto-detect)"] + get_category_list()
    selected_category = st.selectbox("Category", options=category_options, index=0)

    min_date, max_date = get_date_range()

    st.markdown("#### Date Range")
    col_sd, col_ed = st.columns(2)
    with col_sd:
        start_date = st.date_input(
            "Start",
            value=min_date,
            min_value=min_date,
            max_value=max_date,
            key="ss_start"
        )
    with col_ed:
        end_date = st.date_input(
            "End",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            key="ss_end"
        )

    st.markdown("---")

    if st.button("Clear Conversation", use_container_width=True):
        st.session_state["chat_history"] = []
        st.session_state["last_sources"] = []
        st.session_state["last_metadata"] = {}
        st.rerun()


# ---------- Helpers ----------

def call_chat_api(user_message: str) -> dict:
    """POST to the FastAPI /api/chat endpoint and return the JSON response."""
    payload = {
        "message": user_message,
        "enable_entity_boost": True,
    }

    # Apply explicit filters only when the user selected something
    if selected_country != "(auto-detect)":
        payload["influencer"] = selected_country
    if selected_category != "(auto-detect)":
        payload["category"] = selected_category
    if start_date != min_date:
        payload["start_date"] = str(start_date)
    if end_date != max_date:
        payload["end_date"] = str(end_date)

    try:
        resp = requests.post(
            f"{API_URL}/api/chat",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": f"Could not connect to the API at {API_URL}. Is the FastAPI server running?"}
    except requests.exceptions.Timeout:
        return {"error": "The request timed out after 120 seconds. Try a narrower query."}
    except requests.exceptions.HTTPError as exc:
        return {"error": f"API returned status {exc.response.status_code}: {exc.response.text[:500]}"}
    except Exception as exc:
        return {"error": f"Unexpected error: {exc}"}


def build_conversation_markdown() -> str:
    """Export the full conversation history as a Markdown string."""
    lines = ["# Semantic Search -- Conversation Export\n"]
    lines.append(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("---\n")
    for entry in st.session_state["chat_history"]:
        role = entry["role"]
        content = entry["content"]
        if role == "user":
            lines.append(f"## User\n\n{content}\n")
        else:
            lines.append(f"## Assistant\n\n{content}\n")

            # Append sources if available
            sources = entry.get("sources", [])
            if sources:
                lines.append("\n### Sources\n")
                for i, src in enumerate(sources, 1):
                    title = src.get("title", "Untitled")
                    score = src.get("relevance_score", src.get("score", ""))
                    score_str = f" (relevance: {score:.3f})" if isinstance(score, (int, float)) else ""
                    lines.append(f"{i}. **{title}**{score_str}")
                lines.append("")

            # Append matched entities if available
            entities = entry.get("matched_entities", [])
            if entities:
                lines.append("\n### Matched Entities\n")
                for ent in entities:
                    name = ent if isinstance(ent, str) else ent.get("name", str(ent))
                    lines.append(f"- {name}")
                lines.append("")

        lines.append("---\n")
    return "\n".join(lines)


# ---------- Display conversation ----------

for entry in st.session_state["chat_history"]:
    with st.chat_message(entry["role"]):
        st.markdown(entry["content"])


# ---------- Chat input ----------

user_query = st.chat_input("Ask a question about soft power documents...")

if user_query:
    # Show user message immediately
    st.session_state["chat_history"].append({
        "role": "user",
        "content": user_query,
    })
    with st.chat_message("user"):
        st.markdown(user_query)

    # Call API
    with st.chat_message("assistant"):
        with st.spinner("Searching documents and generating response..."):
            result = call_chat_api(user_query)

        if "error" in result:
            st.error(result["error"])
            st.session_state["chat_history"].append({
                "role": "assistant",
                "content": f"**Error:** {result['error']}",
            })
        else:
            answer = result.get("response", "No response received.")
            sources = result.get("sources", [])
            matched_entities = result.get("matched_entities", [])
            filters_inferred = result.get("filters_inferred", {})
            inference_notes = result.get("inference_notes", [])
            filters_applied = result.get("filters_applied", {})

            # Store metadata for the sidebar / expanders
            st.session_state["last_sources"] = sources
            st.session_state["last_metadata"] = {
                "filters_applied": filters_applied,
                "filters_inferred": filters_inferred,
                "inference_notes": inference_notes,
                "matched_entities": matched_entities,
            }

            # Render answer
            st.markdown(answer)

            # Inferred filters info
            if filters_inferred or inference_notes:
                with st.expander("Inferred Filters & Confidence Notes"):
                    if filters_inferred:
                        st.json(filters_inferred)
                    if inference_notes:
                        for note in inference_notes:
                            st.markdown(f"- {note}")
                    if filters_applied:
                        st.markdown("**Filters ultimately applied:**")
                        st.json(filters_applied)

            # Matched entities
            if matched_entities:
                with st.expander(f"Matched Entities ({len(matched_entities)})"):
                    for ent in matched_entities:
                        if isinstance(ent, dict):
                            name = ent.get("name", ent.get("canonical_name", str(ent)))
                            etype = ent.get("entity_type", "")
                            match_type = ent.get("match_type", "")
                            st.markdown(
                                f"- **{name}** "
                                f"{'(' + etype + ')' if etype else ''} "
                                f"{'-- matched via ' + match_type if match_type else ''}"
                            )
                        else:
                            st.markdown(f"- {ent}")

            # Sources table
            if sources:
                with st.expander(f"Sources ({len(sources)} documents)"):
                    source_rows = []
                    for src in sources:
                        source_rows.append({
                            "Title": src.get("title", "Untitled")[:80],
                            "Date": src.get("date", ""),
                            "Country": src.get("initiating_country", src.get("country", "")),
                            "Category": src.get("category", ""),
                            "Relevance": round(src.get("relevance_score", src.get("score", 0)), 3)
                                         if isinstance(src.get("relevance_score", src.get("score", 0)), (int, float))
                                         else "",
                        })
                    df_sources = pd.DataFrame(source_rows)
                    if not df_sources.empty and "Relevance" in df_sources.columns:
                        df_sources = df_sources.sort_values("Relevance", ascending=False)
                    st.dataframe(df_sources, use_container_width=True, hide_index=True)

            # Save to history
            st.session_state["chat_history"].append({
                "role": "assistant",
                "content": answer,
                "sources": sources,
                "matched_entities": matched_entities,
            })


# ---------- Export button ----------

if st.session_state["chat_history"]:
    st.markdown("---")
    md_export = build_conversation_markdown()
    st.download_button(
        label="Download Conversation as Markdown",
        data=md_export,
        file_name=f"semantic_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        mime="text/markdown",
        use_container_width=True,
    )
