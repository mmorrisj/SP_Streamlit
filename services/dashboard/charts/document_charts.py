import altair as alt
import pandas as pd
from streamlit import cache_data
from shared.utils.utils import Config
from sqlalchemy import func, desc


# build streamlit filters for country and date and category
from queries.document_queries import (
    get_document_counts_per_week,
    get_subcategory_distribution_by_document_count,
    get_top_influencers_by_document_count,
    get_top_recipients_by_document_count,
    get_category_distribution_by_document_count,
    get_category_distribution_by_document_count_by_country,
    get_category_count_over_time
)
cfg = Config.from_yaml()

#build streamlit chart for document counts per week
@cache_data
def document_counts_per_week_chart(country=None):
    df = get_document_counts_per_week(country)
    df['week_start'] = pd.to_datetime(df['week_start'])
    return alt.Chart(df).mark_bar(point=True).encode(
        x=alt.X('week_start:T', title='Week Start'),
        y=alt.Y('doc_count:Q', title='Document Count'),
        tooltip=['week_start:T', 'doc_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Documents per Week"
    )

#build streamlit chart for top countries by document count
@cache_data
def top_influencers_by_document_count_chart():
    df = get_top_influencers_by_document_count()
    df['initiating_country'] = df['initiating_country'].astype(str)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X('initiating_country:N', title='Country'),
        y=alt.Y('doc_count:Q', title='Document Count'),
        color=alt.Color('initiating_country:N', legend=None),
        tooltip=['initiating_country:N', 'doc_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Top Influencers by Document Count"
    )

#build streamlit chart for top countries by document count
@cache_data
def top_recipients_by_document_count_chart():
    df = get_top_influencers_by_document_count()
    df['recipients_country'] = df['recipient_country'].astype(str)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X('initiating_country:N', title='Country'),
        y=alt.Y('doc_count:Q', title='Document Count'),
        color=alt.Color('initiating_country:N', legend=None),
        tooltip=['initiating_country:N', 'doc_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Top Recipients by Document Count"
    )

#build streamlit chart for category distribution by document count
@cache_data
def category_distribution_by_document_count_chart(country=None):
    df = get_category_distribution_by_document_count(country)
    df['category'] = df['category'].astype(str)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X('category:N', title='Category'),
        y=alt.Y('doc_count:Q', title='Document Count'),
        color=alt.Color('category:N', legend=None),
        tooltip=['category:N', 'doc_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Category Distribution by Document Count"
    )

#build streamlit chart for subcategory distribution by document count
@cache_data
def subcategory_distribution_by_document_count_chart(country=None):
    df = get_subcategory_distribution_by_document_count(country)
    df['subcategory'] = df['subcategory'].astype(str)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X('subcategory:N', title='Subcategory'),
        y=alt.Y('doc_count:Q', title='Document Count'),
        color=alt.Color('subcategory:N', legend=None),
        tooltip=['subcategory:N', 'doc_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Subcategory Distribution by Document Count"
    )

#build streamlit chart for category distribution by document count by country
@cache_data
def category_distribution_by_document_count_by_country_chart():
    df = get_category_distribution_by_document_count_by_country()
    df['initiating_country'] = df['initiating_country'].astype(str) 
    df['category'] = df['category'].astype(str)
    chart = (
    alt.Chart(df)
      .mark_bar()
      .encode(
          x=alt.X("doc_count:Q"),
          y=alt.Y("initiating_country:N", sort=alt.EncodingSortField("doc_count", order="descending")),
          color="category:N",
          tooltip=["initiating_country", "category", "doc_count"]
      )
      .properties(height=400, width=700)
    )
    return chart
    
#build streamlit chart for diplomacy count over time
@cache_data
def category_count_over_time_chart():
    df = get_category_count_over_time()
    df['month'] = pd.to_datetime(df['month'])   
    df['month'] = df['month'].dt.strftime('%Y-%m')  
    return alt.Chart(df).mark_line(point=True).encode(
        x=alt.X('month:T', title='Month'),
        y=alt.Y('diplomacy_count:Q', title='Diplomacy Count'),
        tooltip=['month:T', 'diplomacy_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Diplomacy Count Over Time"
    )