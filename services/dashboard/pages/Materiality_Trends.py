"""
Materiality Trends Dashboard

Track symbolic vs substantive exchanges over time, showing the balance between
rhetorical gestures and concrete material investments.
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, date
from sqlalchemy import text
from shared.database.database import get_engine
from shared.utils.utils import Config


# Helper functions
@st.cache_data(ttl=300)
def get_materiality_scores_by_month(
    country: str,
    start_date: date,
    end_date: date
):
    """Get monthly material scores for a country."""
    engine = get_engine()

    query = text("""
        SELECT
            period_start,
            event_name,
            material_score,
            material_justification,
            count_by_category,
            count_by_recipient
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = 'MONTHLY'
          AND period_start >= :start_date
          AND period_start <= :end_date
          AND material_score IS NOT NULL
          AND is_deleted = false
        ORDER BY period_start, material_score DESC
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'country': country,
            'start_date': start_date,
            'end_date': end_date
        })

        data = []
        for row in result:
            data.append({
                'month': row[0],
                'event_name': row[1],
                'material_score': float(row[2]) if row[2] else None,
                'justification': row[3],
                'categories': row[4] or {},
                'recipients': row[5] or {}
            })

        return pd.DataFrame(data)


@st.cache_data(ttl=300)
def get_materiality_statistics(
    country: str,
    start_date: date,
    end_date: date
):
    """Get aggregate materiality statistics."""
    engine = get_engine()

    query = text("""
        SELECT
            COUNT(*) as total_events,
            AVG(material_score) as avg_score,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY material_score) as median_score,
            COUNT(CASE WHEN material_score >= 1.0 AND material_score < 4.0 THEN 1 END) as symbolic_count,
            COUNT(CASE WHEN material_score >= 4.0 AND material_score < 7.0 THEN 1 END) as mixed_count,
            COUNT(CASE WHEN material_score >= 7.0 AND material_score <= 10.0 THEN 1 END) as substantive_count
        FROM event_summaries
        WHERE initiating_country = :country
          AND period_type = 'MONTHLY'
          AND period_start >= :start_date
          AND period_start <= :end_date
          AND material_score IS NOT NULL
          AND is_deleted = false
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'country': country,
            'start_date': start_date,
            'end_date': end_date
        }).fetchone()

        return {
            'total_events': result[0] or 0,
            'avg_score': round(float(result[1]), 2) if result[1] else 0.0,
            'median_score': round(float(result[2]), 2) if result[2] else 0.0,
            'symbolic_count': result[3] or 0,
            'mixed_count': result[4] or 0,
            'substantive_count': result[5] or 0
        }


def categorize_materiality(score):
    """Categorize material score into symbolic/mixed/substantive."""
    if score < 4.0:
        return 'Symbolic (1.0-3.9)'
    elif score < 7.0:
        return 'Mixed (4.0-6.9)'
    else:
        return 'Substantive (7.0-10.0)'


# Page configuration
st.set_page_config(
    page_title="Materiality Trends",
    page_icon="⚖️",
    layout="wide"
)

st.title("⚖️ Materiality Trends: Symbolic vs Substantive Exchanges")
st.markdown("*Track the balance between rhetorical gestures and concrete material investments over time*")

# Load config
cfg = Config.from_yaml('shared/config/config.yaml')

# Sidebar filters
st.sidebar.header("Filters")

# Country selection
country = st.sidebar.selectbox(
    "Select Country",
    options=cfg.influencers,
    index=cfg.influencers.index("China") if "China" in cfg.influencers else 0
)

# Date range
min_date = date(2024, 8, 1)
max_date = date(2024, 9, 30)

col1, col2 = st.sidebar.columns(2)
with col1:
    start_date = st.date_input(
        "Start Month",
        value=min_date,
        min_value=min_date,
        max_value=max_date
    )

with col2:
    end_date = st.date_input(
        "End Month",
        value=max_date,
        min_value=min_date,
        max_value=max_date
    )

# Load data
df = get_materiality_scores_by_month(country, start_date, end_date)
stats = get_materiality_statistics(country, start_date, end_date)

if df.empty:
    st.warning(f"No materiality scores found for {country} in this date range. Please run the materiality scoring script first.")
    st.stop()

# Add materiality category
df['category'] = df['material_score'].apply(categorize_materiality)

# Statistics section
st.markdown("---")
st.subheader("📊 Summary Statistics")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Events", f"{stats['total_events']:,}")

with col2:
    st.metric("Average Score", f"{stats['avg_score']:.1f}/10")

with col3:
    pct_symbolic = (stats['symbolic_count'] / stats['total_events'] * 100) if stats['total_events'] > 0 else 0
    st.metric("Symbolic Events", f"{stats['symbolic_count']}", f"{pct_symbolic:.0f}%")

with col4:
    pct_substantive = (stats['substantive_count'] / stats['total_events'] * 100) if stats['total_events'] > 0 else 0
    st.metric("Substantive Events", f"{stats['substantive_count']}", f"{pct_substantive:.0f}%")

# Distribution pie chart
st.markdown("---")
st.subheader("📈 Materiality Distribution")

col1, col2 = st.columns([1, 2])

with col1:
    # Pie chart data
    pie_data = pd.DataFrame({
        'Category': ['Symbolic', 'Mixed', 'Substantive'],
        'Count': [stats['symbolic_count'], stats['mixed_count'], stats['substantive_count']],
        'Color': ['#FF6B6B', '#FFD93D', '#6BCF7F']
    })

    pie_chart = alt.Chart(pie_data).mark_arc(innerRadius=50).encode(
        theta=alt.Theta('Count:Q'),
        color=alt.Color('Category:N', scale=alt.Scale(
            domain=['Symbolic', 'Mixed', 'Substantive'],
            range=['#FF6B6B', '#FFD93D', '#6BCF7F']
        ), legend=alt.Legend(title="Materiality")),
        tooltip=['Category:N', 'Count:Q']
    ).properties(height=300)

    st.altair_chart(pie_chart, use_container_width=True)

with col2:
    # Score distribution histogram
    hist_chart = alt.Chart(df).mark_bar().encode(
        x=alt.X('material_score:Q', bin=alt.Bin(maxbins=10), title='Material Score'),
        y=alt.Y('count():Q', title='Number of Events'),
        color=alt.Color('category:N', scale=alt.Scale(
            domain=['Symbolic (1.0-3.9)', 'Mixed (4.0-6.9)', 'Substantive (7.0-10.0)'],
            range=['#FF6B6B', '#FFD93D', '#6BCF7F']
        ), legend=None),
        tooltip=[
            alt.Tooltip('material_score:Q', bin=alt.Bin(maxbins=10), title='Score Range'),
            alt.Tooltip('count():Q', title='Event Count')
        ]
    ).properties(height=300)

    st.altair_chart(hist_chart, use_container_width=True)

# Timeline visualization
st.markdown("---")
st.subheader("📅 Materiality Over Time")

# Monthly average trend
monthly_avg = df.groupby('month')['material_score'].agg(['mean', 'count']).reset_index()
monthly_avg.columns = ['month', 'avg_score', 'event_count']

trend_chart = alt.Chart(monthly_avg).mark_line(point=True, strokeWidth=3).encode(
    x=alt.X('month:T', title='Month'),
    y=alt.Y('avg_score:Q', title='Average Material Score', scale=alt.Scale(domain=[0, 10])),
    tooltip=[
        alt.Tooltip('month:T', title='Month', format='%B %Y'),
        alt.Tooltip('avg_score:Q', title='Avg Score', format='.2f'),
        alt.Tooltip('event_count:Q', title='Events')
    ]
).properties(height=300)

# Add reference bands
symbolic_band = alt.Chart(pd.DataFrame({'y': [0, 4]})).mark_rect(opacity=0.1, color='#FF6B6B').encode(
    y=alt.Y('y:Q', scale=alt.Scale(domain=[0, 10]))
)

mixed_band = alt.Chart(pd.DataFrame({'y': [4, 7]})).mark_rect(opacity=0.1, color='#FFD93D').encode(
    y=alt.Y('y:Q', scale=alt.Scale(domain=[0, 10]))
)

substantive_band = alt.Chart(pd.DataFrame({'y': [7, 10]})).mark_rect(opacity=0.1, color='#6BCF7F').encode(
    y=alt.Y('y:Q', scale=alt.Scale(domain=[0, 10]))
)

combined_chart = symbolic_band + mixed_band + substantive_band + trend_chart

st.altair_chart(combined_chart, use_container_width=True)

# Event-level scatter plot
st.markdown("---")
st.subheader("🔍 Individual Events by Materiality")

scatter_chart = alt.Chart(df).mark_circle(size=100).encode(
    x=alt.X('month:T', title='Month'),
    y=alt.Y('material_score:Q', title='Material Score', scale=alt.Scale(domain=[0, 10])),
    color=alt.Color('category:N', scale=alt.Scale(
        domain=['Symbolic (1.0-3.9)', 'Mixed (4.0-6.9)', 'Substantive (7.0-10.0)'],
        range=['#FF6B6B', '#FFD93D', '#6BCF7F']
    ), legend=alt.Legend(title="Materiality")),
    tooltip=[
        alt.Tooltip('event_name:N', title='Event'),
        alt.Tooltip('material_score:Q', title='Score', format='.1f'),
        alt.Tooltip('month:T', title='Month', format='%B %Y')
    ]
).properties(height=400).interactive()

st.altair_chart(scatter_chart, use_container_width=True)

# Top/Bottom events
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.subheader("🔝 Most Substantive Events")
    top_events = df.nlargest(10, 'material_score')[['event_name', 'material_score', 'month']]
    for idx, row in top_events.iterrows():
        score_color = "#6BCF7F" if row['material_score'] >= 7 else "#FFD93D"
        st.markdown(f"**{row['event_name']}**")
        st.markdown(f"<span style='color:{score_color}; font-weight:bold;'>Score: {row['material_score']:.1f}/10</span> | {row['month'].strftime('%B %Y')}", unsafe_allow_html=True)
        st.markdown("---")

with col2:
    st.subheader("🔻 Most Symbolic Events")
    bottom_events = df.nsmallest(10, 'material_score')[['event_name', 'material_score', 'month']]
    for idx, row in bottom_events.iterrows():
        score_color = "#FF6B6B" if row['material_score'] < 4 else "#FFD93D"
        st.markdown(f"**{row['event_name']}**")
        st.markdown(f"<span style='color:{score_color}; font-weight:bold;'>Score: {row['material_score']:.1f}/10</span> | {row['month'].strftime('%B %Y')}", unsafe_allow_html=True)
        st.markdown("---")

# Detailed table
st.markdown("---")
st.subheader("📋 All Events with Scores")

# Prepare display dataframe
display_df = df[['month', 'event_name', 'material_score', 'category', 'justification']].copy()
display_df['month'] = display_df['month'].apply(lambda x: x.strftime('%B %Y'))
display_df = display_df.sort_values('material_score', ascending=False)
display_df.columns = ['Month', 'Event Name', 'Score', 'Category', 'Justification']

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Score": st.column_config.NumberColumn(
            "Score",
            format="%.1f",
            min_value=1.0,
            max_value=10.0
        )
    }
)

# Download button
csv = display_df.to_csv(index=False).encode('utf-8')
st.download_button(
    label="⬇️ Download Data as CSV",
    data=csv,
    file_name=f"materiality_trends_{country}_{start_date}_{end_date}.csv",
    mime="text/csv"
)

# Help section
with st.expander("ℹ️ About Materiality Scoring"):
    st.markdown(f"""
    ### What is Materiality Scoring?

    Materiality scores measure the **concrete, substantive nature** of soft power events versus purely **symbolic or rhetorical gestures**.

    ### Scoring Scale (1.0 - 10.0)

    **1.0-3.9: Symbolic/Rhetorical**
    - Diplomatic statements, declarations, speeches
    - Cultural performances, exhibitions, festivals
    - Goodwill visits without tangible commitments
    - Joint communiqués without specific outcomes

    **4.0-6.9: Mixed/Transitional**
    - MOUs with modest financial commitments (< $10M)
    - Capacity building programs, training initiatives
    - Small-scale pilot projects
    - Educational exchanges with institutional backing

    **7.0-10.0: Substantive/Material**
    - Major infrastructure projects with confirmed funding (> $10M)
    - Significant trade agreements with monetary values
    - Military equipment transfers, defense cooperation
    - Large-scale energy deals, resource extraction
    - Completed construction projects, operational facilities

    ### How Scores Are Generated

    Each monthly event summary is analyzed by an AI system that:
    1. Reviews the event's summary narrative
    2. Identifies concrete commitments (financial, construction, equipment)
    3. Distinguishes announcements from implementation
    4. Assigns a score based on the materiality scale
    5. Provides justification citing specific evidence

    ### Current Data

    - **Total Events**: {stats['total_events']:,}
    - **Date Range**: {start_date.strftime('%B %Y')} to {end_date.strftime('%B %Y')}
    - **Symbolic Events**: {stats['symbolic_count']} ({pct_symbolic:.1f}%)
    - **Mixed Events**: {stats['mixed_count']} ({(stats['mixed_count']/stats['total_events']*100) if stats['total_events'] > 0 else 0:.1f}%)
    - **Substantive Events**: {stats['substantive_count']} ({pct_substantive:.1f}%)

    ### Use Cases

    - **Policy Analysis**: Identify whether relationships are based on concrete investments or rhetoric
    - **Trend Detection**: Track shifts from symbolic to substantive engagement over time
    - **Comparative Analysis**: Compare countries' balance of symbolic vs material influence
    - **Strategic Assessment**: Evaluate the tangible impact of soft power activities
    """)
