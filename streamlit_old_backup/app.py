import streamlit as st
st.set_page_config(
    page_title="Soft Power Dashboard",
    page_icon="📄",
    layout="wide",
)
import datetime

from queries.document_queries import (
    get_document_counts_per_week, 
    get_top_influencers_by_document_count, 
    get_top_recipients_by_document_count,
    get_category_distribution_by_document_count,
    get_category_distribution_by_document_count_by_country,
    get_subcategory_distribution_by_document_count,
    get_category_count_over_time,
    initiating_country_list,
    recipient_country_list,
    category_list,
    subcategory_list)

from charts.document_charts import (
    document_counts_per_week_chart, 
    top_influencers_by_document_count_chart,
    category_distribution_by_document_count_chart,
    category_distribution_by_document_count_by_country_chart,
    subcategory_distribution_by_document_count_chart,
    category_count_over_time_chart,
)

import os
from dotenv import load_dotenv
import pandas as pd
import altair as alt

st.markdown(
    """
    <style>
    .main .block-container {
        max-width: 800px;   /* Adjust px value as needed */
        margin-left: auto;
        margin-right: auto;
    }
    </style>
    """,
    unsafe_allow_html=True
)

load_dotenv()
st.markdown(
    "<h1 style='text-align: center; color: #4F8BF9;'>📄 Soft Power Dashboard</h1>",
    unsafe_allow_html=True
)


st.sidebar.title("Filters")
country = st.sidebar.multiselect(
    "Select Initiating Country",
    options=["ALL"] + initiating_country_list(),
    default=["ALL"]
)
rec_list = st.sidebar.multiselect(
    "Select Recipient Country",
    options=["ALL"] + recipient_country_list(),
    default=["ALL"]
)
category = st.sidebar.selectbox(
    "Select a Category",
    options=["ALL"] + category_list(),
    index=0
)
subcategory = st.sidebar.selectbox(
    "Select a SubCategory",
    options=["ALL"] + subcategory_list(),
    index=0
)
st.sidebar.markdown("### Date Range Filter")
start_date = st.sidebar.date_input(
    "Start Date",
    value=datetime.date(2024, 8, 1),
    min_value=datetime.date(2024, 8, 1),
    max_value=datetime.date.today()
)
end_date = st.sidebar.date_input(
    "End Date",
    value=datetime.date.today(),
    min_value=datetime.date(2000, 1, 1),            
)
       
st.sidebar.markdown("---")
st.sidebar.markdown(
    "This dashboard provides insights into the documents related to international diplomacy. "
    "You can filter the data by country and view various charts to understand trends and distributions."
)   
# add charts to the main page from document_charts.py
st.markdown("## Documents per Week")
st.altair_chart(
    document_counts_per_week_chart(country),
    use_container_width=True
)   
st.markdown("## Top Countries by Document Count")
st.altair_chart(
    top_influencers_by_document_count_chart(),
    use_container_width=True
)
st.markdown("## Category Distribution by Document Count")
st.altair_chart(
    category_distribution_by_document_count_chart(country),
    use_container_width=True
)
st.markdown("## Category Distribution by Document Count by Country")
chart = category_distribution_by_document_count_by_country_chart()
st.altair_chart(chart,
    use_container_width=True
)

st.markdown("## Data Source")
st.markdown(
    "The data for this dashboard is sourced from a PostgreSQL database. "
    "You can find the source code and more information on [GitHub]"
)