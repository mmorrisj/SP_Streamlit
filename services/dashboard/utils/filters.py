"""
Shared filter utilities for cross-page filter persistence using st.session_state.
"""

import streamlit as st
import datetime
from shared.utils.utils import Config

cfg = Config.from_yaml()

# Color constants matching React app
INFLUENCER_COLORS = {
    "China": "#dc2626",
    "Russia": "#2563eb",
    "Iran": "#f97316",
    "Turkey": "#7c3aed",
    "United States": "#16a34a",
}

CATEGORY_COLORS = {
    "Economic": "#10b981",
    "Diplomacy": "#06b6d4",
    "Military": "#ef4444",
    "Social": "#8b5cf6",
}

PHASE_COLORS = {
    "emerging": "#10b981",
    "developing": "#3b82f6",
    "peak": "#f59e0b",
    "fading": "#94a3b8",
    "dormant": "#d1d5db",
}


def init_session_filters():
    """Initialize session state with default filter values if not already set."""
    defaults = {
        "filter_countries": ["ALL"],
        "filter_recipients": ["ALL"],
        "filter_category": "ALL",
        "filter_subcategory": "ALL",
        "filter_start_date": datetime.date(2024, 8, 1),
        "filter_end_date": datetime.date.today(),
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def get_filter_countries():
    """Get the current country filter from session state."""
    init_session_filters()
    return st.session_state["filter_countries"]


def get_filter_recipients():
    """Get the current recipient filter from session state."""
    init_session_filters()
    return st.session_state["filter_recipients"]


def get_filter_category():
    """Get the current category filter from session state."""
    init_session_filters()
    return st.session_state["filter_category"]


def get_filter_dates():
    """Get the current date range filter from session state."""
    init_session_filters()
    return st.session_state["filter_start_date"], st.session_state["filter_end_date"]


def render_sidebar_filters(
    show_country=True,
    show_recipient=True,
    show_category=True,
    show_subcategory=False,
    show_dates=True,
):
    """
    Render standard sidebar filters and persist to session state.

    Returns:
        dict with keys: countries, recipients, category, subcategory, start_date, end_date
    """
    init_session_filters()

    st.sidebar.title("Filters")

    filters = {}

    if show_country:
        countries = st.sidebar.multiselect(
            "Initiating Country",
            options=["ALL"] + cfg.influencers,
            default=st.session_state["filter_countries"],
            key="sb_country",
        )
        st.session_state["filter_countries"] = countries
        filters["countries"] = countries
    else:
        filters["countries"] = st.session_state["filter_countries"]

    if show_recipient:
        recipients = st.sidebar.multiselect(
            "Recipient Country",
            options=["ALL"] + cfg.recipients,
            default=st.session_state["filter_recipients"],
            key="sb_recipient",
        )
        st.session_state["filter_recipients"] = recipients
        filters["recipients"] = recipients
    else:
        filters["recipients"] = st.session_state["filter_recipients"]

    if show_category:
        cat_options = ["ALL"] + cfg.categories
        current_cat = st.session_state["filter_category"]
        cat_idx = cat_options.index(current_cat) if current_cat in cat_options else 0
        category = st.sidebar.selectbox(
            "Category",
            options=cat_options,
            index=cat_idx,
            key="sb_category",
        )
        st.session_state["filter_category"] = category
        filters["category"] = category
    else:
        filters["category"] = st.session_state["filter_category"]

    if show_subcategory:
        sub_options = ["ALL"] + cfg.subcategories
        current_sub = st.session_state["filter_subcategory"]
        sub_idx = sub_options.index(current_sub) if current_sub in sub_options else 0
        subcategory = st.sidebar.selectbox(
            "Subcategory",
            options=sub_options,
            index=sub_idx,
            key="sb_subcategory",
        )
        st.session_state["filter_subcategory"] = subcategory
        filters["subcategory"] = subcategory
    else:
        filters["subcategory"] = st.session_state["filter_subcategory"]

    if show_dates:
        st.sidebar.markdown("### Date Range")
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input(
                "Start",
                value=st.session_state["filter_start_date"],
                min_value=datetime.date(2024, 8, 1),
                max_value=datetime.date.today(),
                key="sb_start_date",
            )
        with col2:
            end_date = st.date_input(
                "End",
                value=st.session_state["filter_end_date"],
                min_value=datetime.date(2024, 8, 1),
                key="sb_end_date",
            )
        st.session_state["filter_start_date"] = start_date
        st.session_state["filter_end_date"] = end_date
        filters["start_date"] = start_date
        filters["end_date"] = end_date
    else:
        filters["start_date"] = st.session_state["filter_start_date"]
        filters["end_date"] = st.session_state["filter_end_date"]

    return filters


def format_number(n):
    """Format a number with commas."""
    if n is None:
        return "0"
    return f"{int(n):,}"


def get_country_color(country):
    """Get consistent color for an influencer country."""
    return INFLUENCER_COLORS.get(country, "#6b7280")


def get_category_color(category):
    """Get consistent color for a category."""
    return CATEGORY_COLORS.get(category, "#6b7280")
