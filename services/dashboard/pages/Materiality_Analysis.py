# pages/Materiality_Analysis.py
import pandas as pd
import datetime as dt
from sqlalchemy import text
import streamlit as st
import altair as alt
from shared.database.database import get_engine

st.set_page_config(page_title="Materiality Score Analysis", page_icon="📊", layout="wide")
st.title("📊 Materiality Score Analysis")
st.caption("Comprehensive analysis of material scores across all event summaries")

# -----------------------------
# Data Fetching Functions
# -----------------------------

@st.cache_data(ttl=300, show_spinner=False)
def fetch_countries():
    """Get list of initiating countries"""
    engine = get_engine()
    query = text("""
        SELECT DISTINCT initiating_country
        FROM event_summaries
        WHERE material_score IS NOT NULL
        ORDER BY initiating_country
    """)
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=300, show_spinner=True)
def fetch_score_distribution(countries, start_date, end_date, period_type):
    """Fetch material score distribution data"""
    engine = get_engine()

    country_filter = ""
    params = {}
    if countries:
        country_filter = "AND initiating_country IN :countries"
        params['countries'] = tuple(countries)

    params['start_date'] = start_date
    params['end_date'] = end_date
    params['period_type'] = period_type

    query = text(f"""
        SELECT
            initiating_country,
            material_score,
            event_name,
            count_by_category,
            count_by_recipient,
            period_start,
            period_end
        FROM event_summaries
        WHERE material_score IS NOT NULL
        AND period_type = :period_type
        AND period_start >= :start_date
        AND period_end <= :end_date
        {country_filter}
        ORDER BY material_score DESC
    """)

    if countries:
        query = query.bindparams(countries=tuple(countries))

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)

    return df


@st.cache_data(ttl=300, show_spinner=False)
def process_category_data(df):
    """Extract and flatten category data from JSONB"""
    category_data = []
    for _, row in df.iterrows():
        categories = row['count_by_category'] or {}
        for category, count in categories.items():
            category_data.append({
                'country': row['initiating_country'],
                'event_name': row['event_name'],
                'category': category,
                'count': count,
                'material_score': row['material_score']
            })
    return pd.DataFrame(category_data)


# -----------------------------
# Sidebar Filters
# -----------------------------
with st.sidebar:
    st.header("Filters")

    all_countries = fetch_countries()
    countries = st.multiselect(
        "Initiating Countries",
        options=all_countries,
        default=all_countries if len(all_countries) <= 5 else []
    )

    period_type = st.selectbox(
        "Summary Period",
        options=["MONTHLY", "WEEKLY", "DAILY"],
        index=0
    )

    # Date range
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=dt.date(2024, 1, 1))
    with col2:
        end_date = st.date_input("End Date", value=dt.date.today())

# -----------------------------
# Load Data
# -----------------------------
if not countries:
    st.info("Please select at least one country to view analysis")
    st.stop()

df = fetch_score_distribution(countries, start_date, end_date, period_type)

if df.empty:
    st.warning("No data found for selected filters")
    st.stop()

# -----------------------------
# Summary Statistics
# -----------------------------
st.header("Summary Statistics")

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total Events", len(df))
with col2:
    st.metric("Avg Score", f"{df['material_score'].mean():.2f}")
with col3:
    st.metric("Median Score", f"{df['material_score'].median():.2f}")
with col4:
    st.metric("Min Score", f"{df['material_score'].min():.1f}")
with col5:
    st.metric("Max Score", f"{df['material_score'].max():.1f}")

st.divider()

# -----------------------------
# 1. Overall Score Distribution (Histogram)
# -----------------------------
st.header("📈 Material Score Distribution (1-10)")

# Create bins for histogram
df['score_bin'] = pd.cut(df['material_score'], bins=range(0, 12), labels=[str(i) for i in range(1, 11)])
bin_counts = df['score_bin'].value_counts().sort_index().reset_index()
bin_counts.columns = ['Score', 'Count']

hist_chart = alt.Chart(bin_counts).mark_bar().encode(
    x=alt.X('Score:N', title='Material Score', axis=alt.Axis(labelAngle=0)),
    y=alt.Y('Count:Q', title='Number of Events'),
    color=alt.Color('Count:Q', scale=alt.Scale(scheme='blues'), legend=None),
    tooltip=[
        alt.Tooltip('Score:N', title='Score Range'),
        alt.Tooltip('Count:Q', title='Event Count')
    ]
).properties(
    height=400,
    title='Distribution of Material Scores Across All Events'
)

st.altair_chart(hist_chart, use_container_width=True)

# -----------------------------
# 2. Score Distribution by Country
# -----------------------------
st.header("🌍 Material Score Distribution by Country")

country_scores = df.groupby(['initiating_country', 'score_bin']).size().reset_index(name='count')

country_chart = alt.Chart(country_scores).mark_bar().encode(
    x=alt.X('score_bin:N', title='Material Score', axis=alt.Axis(labelAngle=0)),
    y=alt.Y('count:Q', title='Number of Events'),
    color=alt.Color('initiating_country:N', title='Country'),
    tooltip=[
        alt.Tooltip('initiating_country:N', title='Country'),
        alt.Tooltip('score_bin:N', title='Score'),
        alt.Tooltip('count:Q', title='Events')
    ]
).properties(
    height=400,
    title='Material Score Distribution by Country'
)

st.altair_chart(country_chart, use_container_width=True)

# -----------------------------
# 3. Score Distribution by Category
# -----------------------------
st.header("📂 Material Score Distribution by Category")

category_df = process_category_data(df)

if not category_df.empty:
    # Average score by category
    category_avg = category_df.groupby('category').agg({
        'material_score': 'mean',
        'event_name': 'count'
    }).reset_index()
    category_avg.columns = ['Category', 'Avg Score', 'Event Count']
    category_avg = category_avg.sort_values('Avg Score', ascending=False)

    category_chart = alt.Chart(category_avg).mark_bar().encode(
        x=alt.X('Avg Score:Q', title='Average Material Score', scale=alt.Scale(domain=[0, 10])),
        y=alt.Y('Category:N', title='Category', sort='-x'),
        color=alt.Color('Avg Score:Q', scale=alt.Scale(scheme='viridis'), legend=None),
        tooltip=[
            alt.Tooltip('Category:N', title='Category'),
            alt.Tooltip('Avg Score:Q', title='Avg Score', format='.2f'),
            alt.Tooltip('Event Count:Q', title='Event Count')
        ]
    ).properties(
        height=max(300, len(category_avg) * 25),
        title='Average Material Score by Category'
    )

    st.altair_chart(category_chart, use_container_width=True)

    # Category distribution heatmap
    st.subheader("Category Score Heatmap")

    # Create score bins for categories
    category_df['score_bin'] = pd.cut(category_df['material_score'], bins=range(0, 12), labels=[str(i) for i in range(1, 11)])
    category_heatmap = category_df.groupby(['category', 'score_bin']).size().reset_index(name='count')

    heatmap = alt.Chart(category_heatmap).mark_rect().encode(
        x=alt.X('score_bin:N', title='Material Score'),
        y=alt.Y('category:N', title='Category'),
        color=alt.Color('count:Q', scale=alt.Scale(scheme='blues'), title='Event Count'),
        tooltip=[
            alt.Tooltip('category:N', title='Category'),
            alt.Tooltip('score_bin:N', title='Score'),
            alt.Tooltip('count:Q', title='Events')
        ]
    ).properties(
        height=max(300, len(category_heatmap['category'].unique()) * 25)
    )

    st.altair_chart(heatmap, use_container_width=True)
else:
    st.info("No category data available for selected filters")

# -----------------------------
# 4. Score vs Event Coverage
# -----------------------------
st.header("📊 Material Score vs Event Coverage")

# Calculate total document count per event
df['total_docs'] = df['count_by_category'].apply(lambda x: sum((x or {}).values()))

scatter = alt.Chart(df).mark_circle(size=60).encode(
    x=alt.X('material_score:Q', title='Material Score', scale=alt.Scale(domain=[0, 10])),
    y=alt.Y('total_docs:Q', title='Number of Source Documents'),
    color=alt.Color('initiating_country:N', title='Country'),
    tooltip=[
        alt.Tooltip('event_name:N', title='Event'),
        alt.Tooltip('initiating_country:N', title='Country'),
        alt.Tooltip('material_score:Q', title='Score', format='.1f'),
        alt.Tooltip('total_docs:Q', title='Documents')
    ]
).properties(
    height=400,
    title='Relationship Between Material Score and Document Coverage'
).interactive()

st.altair_chart(scatter, use_container_width=True)

st.caption("*Higher scores generally indicate more strategically significant events, but document count shows media coverage breadth*")

# -----------------------------
# 5. Top Events by Score
# -----------------------------
st.header("🏆 Highest Scored Events")

top_events = df.nlargest(10, 'material_score')[
    ['initiating_country', 'event_name', 'material_score', 'period_start', 'period_end']
].copy()
top_events['period_start'] = pd.to_datetime(top_events['period_start']).dt.strftime('%Y-%m-%d')
top_events['period_end'] = pd.to_datetime(top_events['period_end']).dt.strftime('%Y-%m-%d')
top_events.columns = ['Country', 'Event Name', 'Score', 'Period Start', 'Period End']

st.dataframe(top_events, use_container_width=True, hide_index=True)

# -----------------------------
# 6. Detailed Data Table
# -----------------------------
st.header("📋 Detailed Event Data")

# Prepare display dataframe
display_df = df[['initiating_country', 'event_name', 'material_score', 'period_start', 'total_docs']].copy()
display_df['period_start'] = pd.to_datetime(display_df['period_start']).dt.strftime('%Y-%m-%d')
display_df = display_df.sort_values('material_score', ascending=False)
display_df.columns = ['Country', 'Event Name', 'Material Score', 'Date', 'Documents']

st.dataframe(display_df, use_container_width=True, hide_index=True)

# Download button
csv = display_df.to_csv(index=False).encode('utf-8')
st.download_button(
    label="⬇️ Download Data as CSV",
    data=csv,
    file_name=f"materiality_analysis_{start_date}_{end_date}.csv",
    mime="text/csv"
)

# -----------------------------
# Notes
# -----------------------------
with st.expander("📝 Notes on Material Scores"):
    st.markdown("""
    ### What is Material Score?
    Material scores (1-10) represent the strategic significance and impact of soft power events:

    - **1-3**: Low materiality - Symbolic or routine activities
    - **4-6**: Medium materiality - Notable events with moderate impact
    - **7-10**: High materiality - Strategically significant events

    ### Scoring Criteria:
    - Economic impact and scale
    - Political/diplomatic significance
    - Strategic timing and context
    - Regional influence and reach
    - Long-term implications

    ### Data Source:
    - `event_summaries.material_score` (AI-generated assessment)
    - Scores assigned via LLM analysis of event narratives
    - Categories extracted from `count_by_category` JSONB field
    """)
