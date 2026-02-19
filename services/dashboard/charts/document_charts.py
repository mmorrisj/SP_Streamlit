import altair as alt
import pandas as pd
from streamlit import cache_data
from shared.utils.utils import Config

from queries.document_queries import (
    get_document_counts_per_week,
    get_subcategory_distribution_by_document_count,
    get_top_influencers_by_document_count,
    get_category_distribution_by_document_count,
    get_category_distribution_by_document_count_by_country,
    get_category_count_over_time
)
cfg = Config.from_yaml()


@cache_data(ttl=300)
def document_counts_per_week_chart(country=None, category='ALL', subcategory='ALL', start_date=None, end_date=None):
    df = get_document_counts_per_week(country, category=category, subcategory=subcategory, start_date=start_date, end_date=end_date)
    if df.empty:
        return alt.Chart(pd.DataFrame({'x': [0]})).mark_text(text='No data available').properties(width=600, height=400)
    df['week_start'] = pd.to_datetime(df['week_start'])
    return alt.Chart(df).mark_bar(point=True).encode(
        x=alt.X('week_start:T', title='Week Start'),
        y=alt.Y('doc_count:Q', title='Document Count'),
        tooltip=['week_start:T', 'doc_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Documents per Week"
    ).interactive()


@cache_data(ttl=300)
def top_influencers_by_document_count_chart(country=None, category='ALL', subcategory='ALL', start_date=None, end_date=None):
    df = get_top_influencers_by_document_count(country, category=category, subcategory=subcategory, start_date=start_date, end_date=end_date)
    if df.empty:
        return alt.Chart(pd.DataFrame({'x': [0]})).mark_text(text='No data available').properties(width=600, height=400)
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
    ).interactive()


@cache_data(ttl=300)
def top_recipients_by_document_count_chart(country=None, category='ALL', subcategory='ALL', start_date=None, end_date=None):
    from queries.document_queries import get_top_recipients_by_document_count
    df = get_top_recipients_by_document_count(country, category=category, subcategory=subcategory, start_date=start_date, end_date=end_date)
    if df.empty:
        return alt.Chart(pd.DataFrame({'x': [0]})).mark_text(text='No data available').properties(width=600, height=400)
    df['recipient_country'] = df['recipient_country'].astype(str)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X('recipient_country:N', title='Country'),
        y=alt.Y('doc_count:Q', title='Document Count'),
        color=alt.Color('recipient_country:N', legend=None),
        tooltip=['recipient_country:N', 'doc_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Top Recipients by Document Count"
    ).interactive()


@cache_data(ttl=300)
def category_distribution_by_document_count_chart(country=None, category='ALL', subcategory='ALL', start_date=None, end_date=None):
    df = get_category_distribution_by_document_count(country, category=category, subcategory=subcategory, start_date=start_date, end_date=end_date)
    if df.empty:
        return alt.Chart(pd.DataFrame({'x': [0]})).mark_text(text='No data available').properties(width=600, height=400)
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
    ).interactive()


@cache_data(ttl=300)
def subcategory_distribution_by_document_count_chart(country=None, category='ALL', subcategory='ALL', start_date=None, end_date=None):
    df = get_subcategory_distribution_by_document_count(country, category=category, subcategory=subcategory, start_date=start_date, end_date=end_date)
    if df.empty:
        return alt.Chart(pd.DataFrame({'x': [0]})).mark_text(text='No data available').properties(width=600, height=400)
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
    ).interactive()


@cache_data(ttl=300)
def category_distribution_by_document_count_by_country_chart(country=None, category='ALL', subcategory='ALL', start_date=None, end_date=None):
    df = get_category_distribution_by_document_count_by_country(country, category=category, subcategory=subcategory, start_date=start_date, end_date=end_date)
    if df.empty:
        return alt.Chart(pd.DataFrame({'x': [0]})).mark_text(text='No data available').properties(width=700, height=400)
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
    ).interactive()
    return chart


@cache_data(ttl=300)
def category_count_over_time_chart():
    df = get_category_count_over_time()
    if df.empty:
        return alt.Chart(pd.DataFrame({'x': [0]})).mark_text(text='No data available').properties(width=600, height=400)
    df['month'] = pd.to_datetime(df['month'])
    df['month'] = df['month'].dt.strftime('%Y-%m')
    return alt.Chart(df).mark_line(point=True).encode(
        x=alt.X('month:T', title='Month'),
        y=alt.Y('category_count:Q', title='Count'),
        tooltip=['month:T', 'category_count:Q']
    ).properties(
        width=600,
        height=400,
        title="Category Count Over Time"
    ).interactive()
