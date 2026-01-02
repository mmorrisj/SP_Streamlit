# pages/Impactful_Events.py
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload, sessionmaker, scoped_session
import uuid

from backend.app import create_app
from backend.extensions import db
from backend.scripts.models import WeeklyEvent, WeeklyEventLink, DailyEventSummary
from backend.scripts.utils import Config

# -----------------------
# Streamlit setup
# -----------------------
st.set_page_config(page_title="Impactful Events Explorer", layout="wide")
st.markdown(
    """
    <style>
        .block-container {
            max-width: 1600px;
            padding-left: 2rem;
            padding-right: 2rem;
            margin: auto;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

cfg = Config.from_yaml()
app = create_app()
app.app_context().push()

# Safe session factory
Session = scoped_session(sessionmaker(bind=db.engine))

# -----------------------
# Helpers
# -----------------------
def force_arrow_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame is Arrow-safe (UUIDs/bytes → str, numerics untouched)."""
    if df.empty:
        return df
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].map(
                lambda x: str(x) if isinstance(x, (uuid.UUID, bytes, bytearray)) else x
            )
    return df


def generate_weeks(start_date, end_date):
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    weeks = []
    current_start = start_date - timedelta(days=start_date.weekday())  # align to Monday
    while current_start <= end_date:
        current_end = current_start + timedelta(days=6)
        weeks.append((current_start, min(current_end, end_date)))
        current_start += timedelta(days=7)
    return weeks


def build_event_contributions(initiator, recipient, category, subcategory, start_date, end_date):
    """
    Return weekly averages and per-event contributions for events observed in the window.
    Uses week_start/week_end overlap filtering.
    """
    weeks = generate_weeks(start_date, end_date)
    weekly_results, event_contributions, included_events = [], [], []

    with Session() as session:
        # ✅ Include any weekly event overlapping the selected window
        q = (
            session.query(WeeklyEvent)
            .filter(
                WeeklyEvent.initiating_country == initiator,
                WeeklyEvent.week_start <= end_date,
                WeeklyEvent.week_end >= start_date
            )
            .options(joinedload(WeeklyEvent.sources).joinedload(WeeklyEventLink.daily_summary))
        )
        weekly_events = q.all()

        if not weekly_events:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # Collect included events for debug
        for wevent in weekly_events:
            recipients = []
            if wevent.sources:
                for link in wevent.sources:
                    if link.daily_summary and link.daily_summary.recipient_countries:
                        recipients.extend(link.daily_summary.recipient_countries)
                recipients = list(set(recipients))
            included_events.append(
                {
                    "EventName": wevent.event_name,
                    "Initiator": wevent.initiating_country,
                    "Recipients": ", ".join(recipients) if recipients else "—",
                    "Week Start": wevent.week_start,
                    "Week End": wevent.week_end,
                    "First Observed": wevent.first_observed_date,
                    "Last Observed": wevent.last_observed_date,
                }
            )

        # Loop through each week and compute materiality averages + contributions
        for ws, we in weeks:
            scores = []
            per_week_events = []

            for wevent in weekly_events:
                for link in wevent.sources:
                    des = link.daily_summary
                    if not des or des.material_score is None:
                        continue

                    # Only include daily summaries that fall in this weekly bucket
                    if not (ws <= des.report_date <= we):
                        continue

                    # Apply filters
                    if recipient != "All" and recipient not in (des.recipient_countries or []):
                        continue
                    if category != "All" and category not in (des.categories or []):
                        continue
                    if subcategory != "All" and subcategory not in (des.subcategories or []):
                        continue

                    scores.append(des.material_score)
                    per_week_events.append(des)

            if scores:
                week_avg = np.mean(scores)
                count = len(scores)

                weekly_results.append(
                    {
                        "Week": ws,
                        "Initiator": initiator,
                        "Recipient": recipient,
                        "Category": category,
                        "Subcategory": subcategory,
                        "AvgScore": week_avg,
                        "Count": count,
                    }
                )

                # Leave-one-out contributions
                for ev in per_week_events:
                    other_scores = [
                        s for s in scores if s != ev.material_score or scores.count(s) > 1
                    ]
                    impact = week_avg - np.mean(other_scores) if other_scores else 0

                    event_contributions.append(
                        {
                            "Week": ws,
                            "EventID": str(getattr(ev, "id", "")),
                            "EventName": getattr(ev, "event_name", "Unknown"),
                            "Score": float(ev.material_score),
                            "ImpactOnAvg": float(impact),
                            "Summary": getattr(ev, "summary_text", ""),
                        }
                    )

    # ✅ Convert to DataFrames
    events_df = pd.DataFrame(event_contributions)
    if not events_df.empty:
        events_df["EventID"] = events_df["EventID"].astype(str)
        # Aggregate per event across weeks
        events_df = (
            events_df.groupby(["EventID", "EventName", "Summary"], as_index=False)
            .agg(
                Score=("Score", "mean"),
                ImpactOnAvg=("ImpactOnAvg", "mean"),
                FirstWeek=("Week", "min"),
                LastWeek=("Week", "max"),
            )
        )
        events_df["WeekRange"] = (
            events_df["FirstWeek"].astype(str) + " → " + events_df["LastWeek"].astype(str)
        )

    included_df = pd.DataFrame(included_events)
    if not included_df.empty:
        included_df["WeekRange"] = (
            included_df["Week Start"].astype(str) + " → " + included_df["Week End"].astype(str)
        )

    return (
        force_arrow_safe(pd.DataFrame(weekly_results)),
        force_arrow_safe(events_df),
        force_arrow_safe(included_df),
    )


def plot_trend_chart(df, title):
    chart = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("Week:T", title="Week"),
            y=alt.Y("AvgScore:Q", title="Average Materiality Score", scale=alt.Scale(domain=[0, 10])),
            tooltip=["Week:T", "AvgScore:Q", "Count:Q"],
        )
        .properties(width=800, height=350, title=title)
    )
    st.altair_chart(chart, use_container_width=True)


def plot_top_events(df, title, color):
    if df.empty:
        st.write(f"No data for {title}")
        return

    df["ImpactOnAvg"] = pd.to_numeric(df["ImpactOnAvg"], errors="coerce")
    df["Score"] = pd.to_numeric(df["Score"], errors="coerce")

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("ImpactOnAvg:Q", title="Impact on Avg"),
            y=alt.Y("EventName:N", sort="-x"),
            tooltip=["EventName", "Score", "ImpactOnAvg"],
            color=alt.value(color),
        )
        .properties(width=700, height=250, title=title)
    )
    st.altair_chart(chart, use_container_width=True)


# -----------------------
# Streamlit Page
# -----------------------
def run_page():
    st.title("🌟 Impactful Events Explorer")

    initiator = st.selectbox("Initiator", cfg.influencers)
    recipient = st.selectbox("Recipient", ["All"] + cfg.recipients)
    category = st.selectbox("Category", ["All"] + cfg.categories)
    subcategory = st.selectbox("Subcategory", ["All"] + cfg.subcategories)

    start_date = st.date_input("From (Week Start Overlap)", datetime(2025, 8, 1).date())
    end_date = st.date_input("To (Week End Overlap)", datetime(2025, 8, 31).date())

    show_debug = st.sidebar.checkbox("🔍 Show Included Events", value=False)

    weekly_df, events_df, included_df = build_event_contributions(
        initiator, recipient, category, subcategory, start_date, end_date
    )

    # Downloads
    st.sidebar.markdown("### ⬇️ Export Data")
    for name, df in {
        "Weekly Averages": weekly_df,
        "Event Contributions": events_df,
        "Included Events": included_df,
    }.items():
        if not df.empty:
            st.sidebar.download_button(
                f"Download {name} CSV",
                df.to_csv(index=False).encode("utf-8"),
                file_name=f"{name.replace(' ', '_').lower()}.csv",
                mime="text/csv",
            )

    if weekly_df.empty:
        st.warning("No data available for these filters.")
        return

    # Trend
    st.subheader("📈 Materiality Average Trend")
    plot_trend_chart(
        weekly_df,
        f"Materiality Trend ({initiator} → {recipient}) | {start_date} to {end_date}",
    )

    if show_debug and not included_df.empty:
        st.markdown("### 🗂 Included Events in Date Range")
        st.dataframe(
            included_df[["EventName", "Initiator", "Recipients", "WeekRange", "First Observed", "Last Observed"]]
        )

    if events_df.empty:
        st.info("No events available for impact analysis.")
        return

    # Top Material vs Symbolic
    st.subheader("🔎 Most Influential Events")

    top_materiality = events_df[events_df["ImpactOnAvg"].astype(float) > 0].sort_values(
        "ImpactOnAvg", ascending=False
    ).head(5)
    top_symbolic = events_df[events_df["ImpactOnAvg"].astype(float) < 0].sort_values(
        "ImpactOnAvg", ascending=True
    ).head(5)

    cols = st.columns(2)

    with cols[0]:
        plot_top_events(top_materiality, "Top 5 Events Impacting Materiality", "green")
        for _, row in top_materiality.iterrows():
            st.markdown(
                f"""
                <div style="border:1px solid #ddd; border-radius:8px; padding:10px; margin-bottom:10px;">
                    <b>{row['EventName']}</b> ({row['WeekRange']})<br>
                    <span style="color:green;">Impact: {float(row['ImpactOnAvg']):+.2f} | Score: {float(row['Score']):.2f}</span>
                    <p style="margin-top:5px;">{row['Summary']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with cols[1]:
        plot_top_events(top_symbolic, "Top 5 Events Impacting Symbolic Activities", "blue")
        for _, row in top_symbolic.iterrows():
            st.markdown(
                f"""
                <div style="border:1px solid #ddd; border-radius:8px; padding:10px; margin-bottom:10px;">
                    <b>{row['EventName']}</b> ({row['WeekRange']})<br>
                    <span style="color:blue;">Impact: {float(row['ImpactOnAvg']):+.2f} | Score: {float(row['Score']):.2f}</span>
                    <p style="margin-top:5px;">{row['Summary']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ✅ Run page
run_page()
