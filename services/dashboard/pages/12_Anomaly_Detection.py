"""
Anomaly Detection Page

Identifies statistical anomalies in daily document counts using z-score analysis
with a rolling 30-day window. Links anomaly days to canonical events active on
those dates.
"""

import sys
import os
import datetime

import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Anomaly Detection", page_icon="⚡", layout="wide")

st.title("Anomaly Detection")
st.caption(
    "Statistical outlier detection in daily document counts using rolling z-scores. "
    "Anomalous days are linked to canonical events active on those dates."
)


# ---------------------------------------------------------------------------
# Cached queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_daily_doc_counts(country, category, start_date, end_date):
    """
    Query daily document counts from the documents table joined with
    categories and initiating_countries. Grouped by date.
    """
    engine = get_engine()

    # Build dynamic filters
    filters = []
    params = {
        "start_date": start_date,
        "end_date": end_date,
    }

    if country != "ALL":
        filters.append("ic.initiating_country = :country")
        params["country"] = country

    if category != "ALL":
        filters.append("c.category = :category")
        params["category"] = category

    where_extra = (" AND " + " AND ".join(filters)) if filters else ""

    query = text(f"""
        SELECT
            d.date AS doc_date,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE d.date IS NOT NULL
          AND d.date >= :start_date
          AND d.date <= :end_date
          AND ic.initiating_country IN :influencers
          {where_extra}
        GROUP BY d.date
        ORDER BY d.date
    """)

    params["influencers"] = tuple(cfg.influencers)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)

    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_events_on_date(target_date, country):
    """
    Get canonical events active on a specific date (first_mention_date <= date
    AND last_mention_date >= date).
    """
    engine = get_engine()

    country_filter = ""
    params = {"target_date": target_date}

    if country != "ALL":
        country_filter = "AND initiating_country = :country"
        params["country"] = country

    query = text(f"""
        SELECT
            canonical_name,
            initiating_country,
            CAST(material_score AS FLOAT) AS material_score,
            story_phase,
            total_articles,
            first_mention_date,
            last_mention_date
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND first_mention_date <= :target_date
          AND last_mention_date >= :target_date
          {country_filter}
        ORDER BY total_articles DESC
        LIMIT 20
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)

    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_available_categories():
    """Get distinct categories from the categories table."""
    engine = get_engine()
    query = text("""
        SELECT DISTINCT c.category
        FROM categories c
        JOIN initiating_countries ic ON c.doc_id = ic.doc_id
        WHERE ic.initiating_country IN :influencers
        ORDER BY c.category
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"influencers": tuple(cfg.influencers)}).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("Anomaly Parameters")

selected_country = st.sidebar.selectbox(
    "Initiating Country",
    options=["ALL"] + cfg.influencers,
    index=0,
    help="Filter documents by initiating country",
)

# Category filter
available_categories = get_available_categories()
category_options = ["ALL"] + available_categories
selected_category = st.sidebar.selectbox(
    "Category",
    options=category_options,
    index=0,
    help="Filter by document category",
)

# Threshold slider
z_threshold = st.sidebar.slider(
    "Z-Score Threshold (sigma)",
    min_value=2.0,
    max_value=4.0,
    value=2.0,
    step=0.1,
    help="Days with |z-score| above this threshold are flagged as anomalies",
)

# Date range
st.sidebar.markdown("### Date Range")
col_start, col_end = st.sidebar.columns(2)
with col_start:
    start_date = st.sidebar.date_input(
        "Start",
        value=datetime.date(2024, 8, 1),
        min_value=datetime.date(2024, 1, 1),
        max_value=datetime.date.today(),
    )
with col_end:
    end_date = st.sidebar.date_input(
        "End",
        value=datetime.date.today(),
        min_value=datetime.date(2024, 1, 1),
        max_value=datetime.date.today(),
    )

st.sidebar.markdown("---")
st.sidebar.markdown(
    f"**Active Filters:** Country={selected_country}, "
    f"Category={selected_category}, Threshold={z_threshold}σ"
)


# ---------------------------------------------------------------------------
# Load and process data
# ---------------------------------------------------------------------------

daily_df = get_daily_doc_counts(selected_country, selected_category, start_date, end_date)

if daily_df.empty:
    st.warning("No document data found for the selected filters and date range.")
    st.stop()

daily_df['doc_date'] = pd.to_datetime(daily_df['doc_date'])
daily_df = daily_df.sort_values('doc_date').reset_index(drop=True)

# Fill missing dates with zero to get a continuous series
full_range = pd.date_range(start=daily_df['doc_date'].min(), end=daily_df['doc_date'].max(), freq='D')
daily_df = daily_df.set_index('doc_date').reindex(full_range, fill_value=0).rename_axis('doc_date').reset_index()

# Calculate rolling statistics (30-day window)
window = 30
daily_df['rolling_mean'] = daily_df['doc_count'].rolling(window=window, min_periods=7, center=False).mean()
daily_df['rolling_std'] = daily_df['doc_count'].rolling(window=window, min_periods=7, center=False).std()

# Compute z-scores
daily_df['z_score'] = np.where(
    daily_df['rolling_std'] > 0,
    (daily_df['doc_count'] - daily_df['rolling_mean']) / daily_df['rolling_std'],
    0.0,
)

# Flag anomalies
daily_df['is_anomaly'] = daily_df['z_score'].abs() > z_threshold
daily_df['expected_count'] = daily_df['rolling_mean'].round(1)

anomalies_df = daily_df[daily_df['is_anomaly']].copy()


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

st.header("Overview")

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total Days", len(daily_df))
with col2:
    st.metric("Anomaly Days", len(anomalies_df))
with col3:
    pct = (len(anomalies_df) / len(daily_df) * 100) if len(daily_df) > 0 else 0
    st.metric("Anomaly Rate", f"{pct:.1f}%")
with col4:
    avg_count = daily_df['doc_count'].mean()
    st.metric("Avg Daily Docs", f"{avg_count:.1f}")
with col5:
    max_z = daily_df['z_score'].abs().max()
    st.metric("Max |Z-Score|", f"{max_z:.2f}")

st.markdown("---")


# ---------------------------------------------------------------------------
# Main chart: daily counts with anomaly highlights
# ---------------------------------------------------------------------------

st.header("Daily Document Counts with Anomaly Detection")

# Base line chart
base = alt.Chart(daily_df).encode(
    x=alt.X('doc_date:T', title='Date', axis=alt.Axis(format='%Y-%m-%d', labelAngle=-45)),
)

line = base.mark_line(color='#4F8BF9', strokeWidth=1.5).encode(
    y=alt.Y('doc_count:Q', title='Document Count'),
    tooltip=[
        alt.Tooltip('doc_date:T', title='Date', format='%Y-%m-%d'),
        alt.Tooltip('doc_count:Q', title='Documents'),
        alt.Tooltip('expected_count:Q', title='Expected (30d mean)', format='.1f'),
        alt.Tooltip('z_score:Q', title='Z-Score', format='.2f'),
    ],
)

# Rolling mean as a dashed line
mean_line = base.mark_line(color='#95a5a6', strokeDash=[5, 3], strokeWidth=1).encode(
    y=alt.Y('rolling_mean:Q'),
)

# Anomaly points highlighted in red
anomaly_points = alt.Chart(anomalies_df).mark_circle(size=80, color='#e74c3c').encode(
    x=alt.X('doc_date:T'),
    y=alt.Y('doc_count:Q'),
    tooltip=[
        alt.Tooltip('doc_date:T', title='Anomaly Date', format='%Y-%m-%d'),
        alt.Tooltip('doc_count:Q', title='Actual Count'),
        alt.Tooltip('expected_count:Q', title='Expected Count', format='.1f'),
        alt.Tooltip('z_score:Q', title='Z-Score', format='.2f'),
    ],
)

chart = (line + mean_line + anomaly_points).properties(
    height=450,
    title=f'Daily Document Counts (red dots = anomalies at {z_threshold}σ)',
).interactive()

st.altair_chart(chart, use_container_width=True)

st.caption(
    "Blue line: actual daily count. Gray dashed line: 30-day rolling mean. "
    "Red dots: anomaly days exceeding the z-score threshold."
)


# ---------------------------------------------------------------------------
# Z-Score timeline
# ---------------------------------------------------------------------------

with st.expander("Z-Score Timeline"):
    z_chart = alt.Chart(daily_df).mark_bar().encode(
        x=alt.X('doc_date:T', title='Date'),
        y=alt.Y('z_score:Q', title='Z-Score'),
        color=alt.condition(
            alt.datum.is_anomaly,
            alt.value('#e74c3c'),
            alt.value('#3498db'),
        ),
        tooltip=[
            alt.Tooltip('doc_date:T', title='Date', format='%Y-%m-%d'),
            alt.Tooltip('z_score:Q', title='Z-Score', format='.2f'),
            alt.Tooltip('doc_count:Q', title='Documents'),
        ],
    ).properties(height=300)

    # Add threshold lines
    upper_rule = alt.Chart(pd.DataFrame({'y': [z_threshold]})).mark_rule(
        color='#e74c3c', strokeDash=[4, 4]
    ).encode(y='y:Q')
    lower_rule = alt.Chart(pd.DataFrame({'y': [-z_threshold]})).mark_rule(
        color='#e74c3c', strokeDash=[4, 4]
    ).encode(y='y:Q')

    st.altair_chart((z_chart + upper_rule + lower_rule).interactive(), use_container_width=True)


st.markdown("---")

# ---------------------------------------------------------------------------
# Anomaly table with linked events
# ---------------------------------------------------------------------------

st.header("Anomaly Details")

if anomalies_df.empty:
    st.success(
        f"No anomalies detected at {z_threshold}σ threshold. "
        "Try lowering the threshold in the sidebar."
    )
else:
    # Sort by absolute z-score descending
    anomalies_display = anomalies_df.sort_values('z_score', key=abs, ascending=False).copy()
    anomalies_display['doc_date_str'] = anomalies_display['doc_date'].dt.strftime('%Y-%m-%d')
    anomalies_display['z_score_round'] = anomalies_display['z_score'].round(2)
    anomalies_display['expected_count'] = anomalies_display['expected_count'].round(1)

    st.markdown(f"**{len(anomalies_display)} anomaly day(s) detected** (sorted by |z-score|)")

    table_df = anomalies_display[['doc_date_str', 'doc_count', 'expected_count', 'z_score_round']].copy()
    table_df.columns = ['Date', 'Actual Count', 'Expected Count', 'Z-Score']
    st.dataframe(table_df, use_container_width=True, hide_index=True)

    # Download
    csv = table_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download anomalies as CSV",
        data=csv,
        file_name=f"anomalies_{selected_country}_{selected_category}_{z_threshold}sigma.csv",
        mime="text/csv",
    )

    st.markdown("---")

    # -- Linked events for each anomaly day --
    st.subheader("Events Active on Anomaly Days")
    st.caption(
        "For each anomaly date, shows canonical master events whose active period "
        "(first_mention_date to last_mention_date) overlaps that day."
    )

    # Show top 10 anomaly dates
    top_anomaly_dates = anomalies_display.head(10)

    for _, arow in top_anomaly_dates.iterrows():
        anomaly_date = arow['doc_date'].date()
        z_val = arow['z_score']
        actual = int(arow['doc_count'])
        expected = arow['expected_count']

        direction = "spike" if z_val > 0 else "drop"

        with st.expander(
            f"{anomaly_date} -- {direction} (z={z_val:.2f}, actual={actual}, expected={expected:.0f})"
        ):
            events_df = get_events_on_date(anomaly_date, selected_country)

            if not events_df.empty:
                for _, erow in events_df.iterrows():
                    score_str = f"{erow['material_score']:.1f}" if erow['material_score'] is not None else "N/A"
                    st.markdown(
                        f"- **{erow['canonical_name']}** "
                        f"({erow['initiating_country']}) -- "
                        f"{int(erow['total_articles'])} articles, "
                        f"score: {score_str}, "
                        f"phase: {erow['story_phase'] or 'N/A'}"
                    )
            else:
                st.info("No active canonical events found on this date.")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
with st.expander("Methodology"):
    st.markdown(f"""
    ### Z-Score Anomaly Detection

    1. **Data source:** Daily document counts from the `documents` table, joined with
       `initiating_countries` and `categories` for filtering. Only documents from
       configured influencer countries are included.

    2. **Rolling window:** A {window}-day trailing window computes the rolling mean
       and standard deviation.

    3. **Z-score:** For each day, z = (actual_count - rolling_mean) / rolling_std.

    4. **Threshold:** Days where |z| > {z_threshold} are flagged as anomalies.
       Positive z-scores indicate unusual spikes; negative z-scores indicate unusual drops.

    5. **Event linkage:** For each anomaly date, canonical master events whose active
       period (first_mention_date to last_mention_date) overlaps the anomaly date are
       retrieved from `canonical_events`.

    ### Interpretation
    - **High positive z-score:** Unusual surge in documents, potentially indicating a
      breaking news event or coordinated soft power push.
    - **High negative z-score:** Unusual drop in activity, which may indicate censorship,
      holiday effects, or shifts in focus.
    """)
