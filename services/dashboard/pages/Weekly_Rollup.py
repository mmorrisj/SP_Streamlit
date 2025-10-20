import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import select
from backend.scripts.models import WeeklyEventSummary,WeeklySummary,
from backend.app import create_app
from backend.extensions import db
from datetime import datetime

# --- Streamlit setup ---
st.set_page_config(layout="centered")

# --- Journal-like styling ---
st.markdown(
    """
    <style>
        .reportview-container .main .block-container {
            max-width: 900px;
            padding-top: 1rem;
            padding-right: 2rem;
            padding-left: 2rem;
            padding-bottom: 2rem;
        }
        html, body, [class*="css"] {
            font-family: 'Merriweather', Georgia, serif;
            line-height: 1.6;
            font-size: 1rem;
        }
        h1, h2, h3 {
            font-family: 'Lato', 'Helvetica Neue', sans-serif;
            font-weight: 600;
            letter-spacing: 0.5px;
            margin-top: 1.2em;
            margin-bottom: 0.6em;
        }
        h1 { font-size: 1.8rem; border-bottom: 1px solid #ccc; padding-bottom: 0.3rem; }
        h2 { font-size: 1.4rem; color: #444; }
        h3 { font-size: 1.2rem; color: #555; }
        [data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: 500; }
        .stContainerCustom {
            border: 1px solid #ddd;
            padding: 1rem;
            margin-bottom: 1.2rem;
            border-radius: 8px;
            background-color: #fafafa;
        }
        @media (prefers-color-scheme: dark) {
            body { background-color: #1e1e1e; color: #f0f0f0; }
            .stContainerCustom { background-color: #2a2a2a; border-color: #444; }
        }
        .figure-caption {
            font-style: italic;
            font-size: 0.9rem;
            color: #666;
            text-align: center;
            margin-top: 0.2rem;
            margin-bottom: 1rem;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# --- Setup Flask + SQLAlchemy ---
app = create_app()
ctx = app.app_context()
ctx.push()

# --- Sidebar filters ---
st.sidebar.header("Filters")

# Query all available weekly ranges
with app.app_context():
    weeks_query = (
        select(WeeklyEventSummary.week_start, WeeklyEventSummary.week_end)
        .distinct()
        .order_by(WeeklyEventSummary.week_start)
    )
    weeks = [(row[0], row[1]) for row in db.session.execute(weeks_query)]

week_options = [f"{ws.strftime('%Y-%m-%d')} → {we.strftime('%Y-%m-%d')}" for ws, we in weeks]
selected_week = st.sidebar.selectbox("Select Week", week_options)
idx = week_options.index(selected_week)
week_start, week_end = weeks[idx]

# Initiating country dropdown
with app.app_context():
    country_query = select(WeeklyEventSummary.initiating_country).distinct()
    countries = sorted([row[0] for row in db.session.execute(country_query)])
selected_country = st.sidebar.selectbox("Initiating Country", countries, index=0)

# --- Query Weekly Summaries ---
with app.app_context():
    stmt = (
        select(WeeklyEventSummary)
        .filter(
            WeeklyEventSummary.week_start == week_start,
            WeeklyEventSummary.week_end == week_end,
            WeeklyEventSummary.initiating_country == selected_country
        )
    )
    df_week = pd.read_sql(stmt, db.engine)

if df_week.empty:
    st.warning("No weekly summaries found for this filter.")
    st.stop()

weekly_summaries = df_week.to_dict(orient="records")

# --- Overall Weekly Rollup ---
st.header(f"📊 Weekly Rollup – {selected_country} ({week_start} → {week_end})")

total_events = sum(ws.get("num_daily_events", 0) for ws in weekly_summaries)
total_articles = sum(ws.get("num_articles", 0) for ws in weekly_summaries)
total_sources = sum(ws.get("num_unique_sources", 0) for ws in weekly_summaries)

symbolic_events = sum(1 for ws in weekly_summaries if ws.get("avg_material_score", 0) < 5)
material_events = sum(1 for ws in weekly_summaries if ws.get("avg_material_score", 0) >= 5)

avg_score = (
    sum(ws.get("avg_material_score", 0) for ws in weekly_summaries) / len(weekly_summaries)
    if weekly_summaries else 0
)

col1, col2, col3 = st.columns(3)
col1.metric("Total Events", total_events)
col2.metric("Total Articles", total_articles)
col3.metric("Total Sources", total_sources)

col4, col5, col6 = st.columns(3)
col4.metric("Symbolic Events", symbolic_events)
col5.metric("Material Events", material_events)
col6.metric("Avg Material Score", f"{avg_score:.2f}")

# --- Order Weekly Events ---
weekly_summaries = sorted(
    weekly_summaries,
    key=lambda ws: (ws.get("num_articles", 0), ws.get("avg_material_score", 0)),
    reverse=True
)

# --- Display Weekly Summaries ---
for ws in weekly_summaries:
    st.markdown('<div class="stContainerCustom">', unsafe_allow_html=True)

    st.subheader(f"{ws['event_name']} ({ws['week_start']} → {ws['week_end']})")
    st.caption(f"Initiator: {ws['initiating_country']} → Recipients: {', '.join(ws.get('recipient_countries', []))}")

    # Metrics for each event
    col1, col2, col3 = st.columns(3)
    col1.metric("Articles", ws.get("num_articles", 0))
    col2.metric("Sources", ws.get("num_unique_sources", 0))
    col3.metric("Daily Events", ws.get("num_daily_events", 0))

    col4, col5, col6 = st.columns(3)
    col4.metric("Recipients", ws.get("num_recipients", 0))
    col5.metric("Entities", ws.get("num_entities", 0))
    col6.metric("Avg Score", round(ws.get("avg_material_score", 0.0), 2))

    # Narratives
    if ws.get("weekly_overview"):
        st.subheader("Weekly Overview")
        st.write(ws["weekly_overview"])
    if ws.get("weekly_outcome"):
        st.subheader("Weekly Outcome")
        st.write(ws["weekly_outcome"])
    if ws.get("weekly_metrics"):
        st.subheader("Weekly Metrics Narrative")
        st.write(ws["weekly_metrics"])

    st.markdown('</div>', unsafe_allow_html=True)
