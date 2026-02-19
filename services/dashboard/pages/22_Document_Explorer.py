"""
Document Explorer

Search and browse individual source documents with filtering by country,
category, date range, and free-text search.
"""

import streamlit as st
import pandas as pd
import datetime
from sqlalchemy import text
from shared.database.database import get_engine
from shared.utils.utils import Config

# Load config
cfg = Config.from_yaml()

# Page configuration
st.set_page_config(
    page_title="Document Explorer",
    page_icon="\U0001F50D",
    layout="wide"
)

st.title("\U0001F50D Document Explorer")
st.markdown("Search and browse individual source documents from the soft power analytics corpus.")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESULTS_PER_PAGE = 25

# ---------------------------------------------------------------------------
# Cached query helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_category_options():
    """Return distinct categories present in the database that match config."""
    query = text("""
        SELECT DISTINCT category
        FROM categories
        WHERE category = ANY(:categories)
        ORDER BY category
    """)
    with get_engine().connect() as conn:
        df = pd.read_sql(query, conn, params={"categories": cfg.categories})
    return df["category"].tolist()


@st.cache_data(ttl=300)
def get_date_range():
    """Return the min and max document dates in the filtered dataset."""
    query = text("""
        SELECT MIN(d.date) AS min_date, MAX(d.date) AS max_date
        FROM documents d
        WHERE d.date IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM initiating_countries ic
              WHERE ic.doc_id = d.doc_id
                AND ic.initiating_country = ANY(:influencers)
          )
          AND EXISTS (
              SELECT 1 FROM recipient_countries rc
              WHERE rc.doc_id = d.doc_id
                AND rc.recipient_country = ANY(:recipients)
          )
    """)
    with get_engine().connect() as conn:
        row = conn.execute(query, {
            "influencers": cfg.influencers,
            "recipients": cfg.recipients,
        }).fetchone()
    if row and row[0] and row[1]:
        return row[0], row[1]
    return datetime.date(2024, 8, 1), datetime.date.today()


@st.cache_data(ttl=300)
def query_documents(
    initiating_country,
    recipient_country,
    category,
    start_date,
    end_date,
    search_text,
    page,
    per_page,
):
    """
    Query documents with filters and pagination.

    Returns (total_count, results_dataframe).
    """
    # Build WHERE clauses dynamically
    where_clauses = [
        "d.date >= :start_date",
        "d.date <= :end_date",
    ]
    params = {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "influencers": cfg.influencers,
        "recipients": cfg.recipients,
    }

    # Initiating country filter
    if initiating_country and initiating_country != "ALL":
        where_clauses.append("ic.initiating_country = :init_country")
        params["init_country"] = initiating_country
    else:
        where_clauses.append("ic.initiating_country = ANY(:influencers)")

    # Recipient country filter
    if recipient_country and recipient_country != "ALL":
        where_clauses.append("rc.recipient_country = :recip_country")
        params["recip_country"] = recipient_country
    else:
        where_clauses.append("rc.recipient_country = ANY(:recipients)")

    # Category filter
    if category and category != "ALL":
        where_clauses.append("d.category = :category")
        params["category"] = category

    # Full-text search on title and distilled_text
    if search_text and search_text.strip():
        where_clauses.append(
            "(d.title ILIKE :search OR d.distilled_text ILIKE :search)"
        )
        params["search"] = f"%{search_text.strip()}%"

    where_sql = " AND ".join(where_clauses)

    # Count query
    count_sql = text(f"""
        SELECT COUNT(DISTINCT d.doc_id)
        FROM documents d
        JOIN initiating_countries ic ON ic.doc_id = d.doc_id
        JOIN recipient_countries rc ON rc.doc_id = d.doc_id
        WHERE d.date IS NOT NULL
          AND {where_sql}
    """)

    # Data query with pagination
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    data_sql = text(f"""
        SELECT DISTINCT
            d.doc_id,
            d.title,
            d.source_name,
            d.date,
            d.category,
            d.subcategory,
            d.initiating_country,
            d.recipient_country,
            d.salience,
            d.salience_justification,
            d.distilled_text,
            d.source_medium,
            d.location
        FROM documents d
        JOIN initiating_countries ic ON ic.doc_id = d.doc_id
        JOIN recipient_countries rc ON rc.doc_id = d.doc_id
        WHERE d.date IS NOT NULL
          AND {where_sql}
        ORDER BY d.date DESC, d.title ASC
        LIMIT :limit OFFSET :offset
    """)

    with get_engine().connect() as conn:
        total_count = conn.execute(count_sql, params).scalar() or 0
        df = pd.read_sql(data_sql, conn, params=params)

    return total_count, df


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
st.sidebar.header("Filters")

# Initiating country
influencer_options = ["ALL"] + cfg.influencers
selected_initiating = st.sidebar.selectbox(
    "Initiating Country",
    options=influencer_options,
    index=0,
    help="Filter documents by the country initiating the soft power activity.",
)

# Recipient country
recipient_options = ["ALL"] + cfg.recipients
selected_recipient = st.sidebar.selectbox(
    "Recipient Country",
    options=recipient_options,
    index=0,
    help="Filter documents by the recipient country.",
)

# Category
category_options = ["ALL"] + get_category_options()
selected_category = st.sidebar.selectbox(
    "Category",
    options=category_options,
    index=0,
    help="Filter by document category.",
)

# Date range
st.sidebar.markdown("### Date Range")
min_date, max_date = get_date_range()

col_sd, col_ed = st.sidebar.columns(2)
with col_sd:
    selected_start = st.date_input(
        "Start",
        value=min_date,
        min_value=min_date,
        max_value=max_date,
    )
with col_ed:
    selected_end = st.date_input(
        "End",
        value=max_date,
        min_value=min_date,
        max_value=max_date,
    )

# Search text
search_text = st.sidebar.text_input(
    "Search",
    placeholder="Search title or content...",
    help="Full-text search across document titles and distilled text using ILIKE.",
)

# ---------------------------------------------------------------------------
# Pagination state
# ---------------------------------------------------------------------------
if "doc_explorer_page" not in st.session_state:
    st.session_state.doc_explorer_page = 1

# Reset to page 1 whenever filters change
filter_key = (
    selected_initiating,
    selected_recipient,
    selected_category,
    str(selected_start),
    str(selected_end),
    search_text,
)
if "doc_explorer_filter_key" not in st.session_state:
    st.session_state.doc_explorer_filter_key = filter_key
if st.session_state.doc_explorer_filter_key != filter_key:
    st.session_state.doc_explorer_page = 1
    st.session_state.doc_explorer_filter_key = filter_key

current_page = st.session_state.doc_explorer_page

# ---------------------------------------------------------------------------
# Execute query
# ---------------------------------------------------------------------------
total_count, results_df = query_documents(
    initiating_country=selected_initiating,
    recipient_country=selected_recipient,
    category=selected_category,
    start_date=selected_start,
    end_date=selected_end,
    search_text=search_text,
    page=current_page,
    per_page=RESULTS_PER_PAGE,
)

total_pages = max(1, (total_count + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)

# Clamp current page
if current_page > total_pages:
    current_page = total_pages
    st.session_state.doc_explorer_page = current_page

# ---------------------------------------------------------------------------
# Top metrics
# ---------------------------------------------------------------------------
st.markdown("---")

metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
with metric_col1:
    st.metric("Total Documents", f"{total_count:,}")
with metric_col2:
    st.metric("Current Page", f"{current_page} / {total_pages}")
with metric_col3:
    showing_start = (current_page - 1) * RESULTS_PER_PAGE + 1 if total_count > 0 else 0
    showing_end = min(current_page * RESULTS_PER_PAGE, total_count)
    st.metric("Showing", f"{showing_start}-{showing_end}")
with metric_col4:
    filter_desc_parts = []
    if selected_initiating != "ALL":
        filter_desc_parts.append(selected_initiating)
    if selected_recipient != "ALL":
        filter_desc_parts.append(selected_recipient)
    if selected_category != "ALL":
        filter_desc_parts.append(selected_category)
    st.metric("Active Filters", len(filter_desc_parts) + (1 if search_text.strip() else 0))

st.markdown("---")

# ---------------------------------------------------------------------------
# Pagination controls (top)
# ---------------------------------------------------------------------------
if total_pages > 1:
    pag_col1, pag_col2, pag_col3 = st.columns([1, 2, 1])
    with pag_col1:
        if st.button("\u25C0 Previous", disabled=(current_page <= 1), key="prev_top"):
            st.session_state.doc_explorer_page = current_page - 1
            st.rerun()
    with pag_col2:
        new_page = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=current_page,
            step=1,
            key="page_input_top",
            label_visibility="collapsed",
        )
        if new_page != current_page:
            st.session_state.doc_explorer_page = new_page
            st.rerun()
    with pag_col3:
        if st.button("Next \u25B6", disabled=(current_page >= total_pages), key="next_top"):
            st.session_state.doc_explorer_page = current_page + 1
            st.rerun()

# ---------------------------------------------------------------------------
# Display results as expandable cards
# ---------------------------------------------------------------------------
if results_df.empty:
    st.info("No documents found matching the current filters. Try broadening your search criteria.")
else:
    for _, row in results_df.iterrows():
        doc_title = row["title"] or "Untitled"
        doc_source = row["source_name"] or "Unknown Source"
        doc_date = row["date"]
        doc_category = row["category"] or "N/A"
        doc_salience = row["salience"] or "N/A"

        # Format the date for display
        if pd.notna(doc_date):
            if isinstance(doc_date, str):
                date_display = doc_date
            else:
                date_display = pd.to_datetime(doc_date).strftime("%Y-%m-%d")
        else:
            date_display = "N/A"

        # Build card header
        header = f"**{doc_title}** | {doc_source} | {date_display} | {doc_category} | Salience: {doc_salience}"

        with st.expander(header, expanded=False):
            # Metadata row
            info_col1, info_col2, info_col3, info_col4 = st.columns(4)
            with info_col1:
                st.markdown(f"**Source:** {doc_source}")
            with info_col2:
                st.markdown(f"**Date:** {date_display}")
            with info_col3:
                st.markdown(f"**Category:** {doc_category}")
            with info_col4:
                st.markdown(f"**Subcategory:** {row['subcategory'] or 'N/A'}")

            info_col5, info_col6, info_col7, info_col8 = st.columns(4)
            with info_col5:
                st.markdown(f"**Initiating Country:** {row['initiating_country'] or 'N/A'}")
            with info_col6:
                st.markdown(f"**Recipient Country:** {row['recipient_country'] or 'N/A'}")
            with info_col7:
                st.markdown(f"**Source Medium:** {row['source_medium'] or 'N/A'}")
            with info_col8:
                st.markdown(f"**Location:** {row['location'] or 'N/A'}")

            st.markdown(f"**Salience:** {doc_salience}")

            # Salience justification
            salience_just = row["salience_justification"]
            if salience_just and str(salience_just).strip():
                st.markdown("**Salience Justification:**")
                st.markdown(salience_just)

            # Distilled text
            distilled = row["distilled_text"]
            if distilled and str(distilled).strip():
                st.markdown("**Distilled Text:**")
                st.markdown(distilled)

            # Doc ID for reference
            st.caption(f"Doc ID: {row['doc_id']}")

# ---------------------------------------------------------------------------
# Pagination controls (bottom)
# ---------------------------------------------------------------------------
if total_pages > 1:
    st.markdown("---")
    pag_b_col1, pag_b_col2, pag_b_col3 = st.columns([1, 2, 1])
    with pag_b_col1:
        if st.button("\u25C0 Previous", disabled=(current_page <= 1), key="prev_bottom"):
            st.session_state.doc_explorer_page = current_page - 1
            st.rerun()
    with pag_b_col2:
        new_page_bottom = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=current_page,
            step=1,
            key="page_input_bottom",
            label_visibility="collapsed",
        )
        if new_page_bottom != current_page:
            st.session_state.doc_explorer_page = new_page_bottom
            st.rerun()
    with pag_b_col3:
        if st.button("Next \u25B6", disabled=(current_page >= total_pages), key="next_bottom"):
            st.session_state.doc_explorer_page = current_page + 1
            st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "Use the sidebar filters to narrow results by country, category, date range, "
    "or free-text search. Results are paginated at 25 documents per page."
)
