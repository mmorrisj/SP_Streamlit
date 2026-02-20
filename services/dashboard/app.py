import streamlit as st
st.set_page_config(
    page_title="Soft Power Dashboard",
    page_icon="📄",
    layout="wide",
)
import datetime

from queries.document_queries import (
    initiating_country_list,
    recipient_country_list,
    category_list,
    subcategory_list,
    get_document_counts_per_week,
    get_top_influencers_by_document_count,
    get_category_distribution_by_document_count,
    get_category_distribution_by_document_count_by_country,
)

from charts.document_charts import (
    document_counts_per_week_chart,
    top_influencers_by_document_count_chart,
    category_distribution_by_document_count_chart,
    category_distribution_by_document_count_by_country_chart,
)

from utils.filters import init_session_filters, INFLUENCER_COLORS, CATEGORY_COLORS

from dotenv import load_dotenv
load_dotenv()

init_session_filters()

st.markdown(
    """
    <style>
    .main .block-container {
        max-width: 1200px;
        margin-left: auto;
        margin-right: auto;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(
    "<h1 style='text-align: center; color: #4F8BF9;'>Soft Power Dashboard</h1>",
    unsafe_allow_html=True
)

# --- Sidebar Filters ---
st.sidebar.title("Filters")
country = st.sidebar.multiselect(
    "Select Initiating Country",
    options=["ALL"] + initiating_country_list(),
    default=["ALL"],
    key="home_country",
)
rec_list = st.sidebar.multiselect(
    "Select Recipient Country",
    options=["ALL"] + recipient_country_list(),
    default=["ALL"],
    key="home_recipient",
)
category_sel = st.sidebar.selectbox(
    "Select a Category",
    options=["ALL"] + category_list(),
    index=0,
    key="home_category",
)
subcategory_sel = st.sidebar.selectbox(
    "Select a SubCategory",
    options=["ALL"] + subcategory_list(),
    index=0,
    key="home_subcategory",
)
st.sidebar.markdown("### Date Range Filter")
start_date = st.sidebar.date_input(
    "Start Date",
    value=datetime.date(2024, 8, 1),
    min_value=datetime.date(2024, 8, 1),
    max_value=datetime.date.today(),
    key="home_start_date",
)
end_date = st.sidebar.date_input(
    "End Date",
    value=datetime.date.today(),
    min_value=datetime.date(2000, 1, 1),
    key="home_end_date",
)

# Persist to session state for cross-page use
st.session_state["filter_countries"] = country
st.session_state["filter_recipients"] = rec_list
st.session_state["filter_category"] = category_sel
st.session_state["filter_subcategory"] = subcategory_sel
st.session_state["filter_start_date"] = start_date
st.session_state["filter_end_date"] = end_date

st.sidebar.markdown("---")
st.sidebar.markdown(
    "This dashboard provides insights into the documents related to international diplomacy. "
    "You can filter the data by country and view various charts to understand trends and distributions."
)

# --- Charts (all wired to filters) ---
st.markdown("## Documents per Week")
st.altair_chart(
    document_counts_per_week_chart(
        country=country,
        category=category_sel,
        subcategory=subcategory_sel,
        start_date=start_date,
        end_date=end_date,
    ),
    use_container_width=True
)

st.markdown("## Top Countries by Document Count")
st.altair_chart(
    top_influencers_by_document_count_chart(
        country=country,
        category=category_sel,
        subcategory=subcategory_sel,
        start_date=start_date,
        end_date=end_date,
    ),
    use_container_width=True
)

st.markdown("## Category Distribution by Document Count")
st.altair_chart(
    category_distribution_by_document_count_chart(
        country=country,
        category=category_sel,
        subcategory=subcategory_sel,
        start_date=start_date,
        end_date=end_date,
    ),
    use_container_width=True
)

st.markdown("## Category Distribution by Document Count by Country")
chart = category_distribution_by_document_count_by_country_chart(
    country=country,
    category=category_sel,
    subcategory=subcategory_sel,
    start_date=start_date,
    end_date=end_date,
)
st.altair_chart(chart, use_container_width=True)
