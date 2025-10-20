import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
from datetime import datetime, timedelta

from backend.app import create_app
from backend.extensions import db
from backend.scripts.models import DailyEventSummary,WeeklyEvent
from shared.utils.utils import Config

cfg = Config.from_yaml()
app = create_app()
app.app_context().push()

# -----------------------
# Helpers
# -----------------------
def generate_weeks(start_date, end_date):
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    weeks = []
    current_start = start_date - timedelta(days=start_date.weekday())  # Monday
    while current_start <= end_date:
        current_end = current_start + timedelta(days=6)
        weeks.append((current_start, min(current_end, end_date)))
        current_start += timedelta(days=7)
    return weeks


from backend.scripts.models import WeeklyEvent, WeeklyEventLink, DailyEventSummary
from sqlalchemy.orm import joinedload

def build_weekly_stats(initiator, recipient, start_date, end_date, category=None):
    """Return weekly avg materiality + count AND per-event contributions."""
    weeks = generate_weeks(start_date, end_date)
    weekly_results = []
    event_contributions = []

    for ws, we in weeks:
        q = (
            db.session.query(WeeklyEvent)
            .filter(
                WeeklyEvent.initiating_country == initiator,
                WeeklyEvent.week_start == ws,
                WeeklyEvent.week_end == we,
            )
            .options(joinedload(WeeklyEvent.sources).joinedload(WeeklyEventLink.daily_summary))
        )

        weekly_events = q.all()
        if not weekly_events:
            continue

        scores = []
        per_week_events = []
        for wevent in weekly_events:
            for link in wevent.sources:
                des = link.daily_summary
                if not des or des.material_score is None:
                    continue

                if recipient != "All" and recipient not in (des.recipient_countries or []):
                    continue
                if category and category != "All" and category not in (des.categories or []):
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
                    "Category": category or "All",
                    "AvgScore": week_avg,
                    "Count": count,
                }
            )

            # compute contributions
            for ev in per_week_events:
                other_scores = [s for s in scores if s != ev.material_score or scores.count(s) > 1]
                if other_scores:
                    avg_without = np.mean(other_scores)
                    impact = week_avg - avg_without
                else:
                    impact = 0

                event_contributions.append(
                    {
                        "Week": ws,
                        "Initiator": initiator,
                        "Recipient": recipient,
                        "EventID": str(ev.id),
                        "EventName": ev.event_name,
                        "Score": ev.material_score,
                        "ImpactOnAvg": impact,
                        "Summary": ev.summary_text,
                    }
                )

    return weekly_results, event_contributions


def plot_trends(df, y_col, title, y_title, domain=None):
    chart = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("Week:T", title="Week"),
            y=alt.Y(f"{y_col}:Q", title=y_title,
                    scale=alt.Scale(domain=domain) if domain else alt.Undefined),
            color="Initiator:N",
            tooltip=["Week:T", "Initiator:N", f"{y_col}:Q"]
        )
        .properties(width=750, height=350, title=title)
    )
    st.altair_chart(chart, use_container_width=True)


def compute_trend(df, initiator, recipient):
    """Return current score + trend (+/-/0) over last month."""
    sub = df[(df["Initiator"] == initiator) & (df["Recipient"] == recipient)]
    if sub.empty:
        return None, None

    sub = sub.sort_values("Week")
    latest = sub.iloc[-1]["AvgScore"]

    # last 4 weeks excluding latest
    month_window = sub.iloc[-5:-1] if len(sub) > 4 else sub.iloc[:-1]
    if not month_window.empty:
        prev_avg = month_window["AvgScore"].mean()
        delta = latest - prev_avg
    else:
        delta = 0

    return latest, delta


def render_initiator_card(name, score, delta):
    arrow = "➡️"
    color = "gray"
    if delta > 0.05:
        arrow, color = "📈", "green"
    elif delta < -0.05:
        arrow, color = "📉", "red"

    st.markdown(
        f"""
        <div style="border:1px solid #ddd; border-radius:10px; padding:10px; margin:5px; text-align:center; display:inline-block; width:180px;">
            <b>{name}</b><br>
            <span style="font-size:20px;">{score:.2f}</span><br>
            <span style="color:{color};">{arrow} {delta:+.2f}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------
# Streamlit Page
# -----------------------
def run_page():
    st.title("🌍 Recipient Comparison Dashboard")

    # --- Date range
    start_date = st.date_input("Start Date", datetime(2024, 8, 1).date())
    end_date = st.date_input("End Date", datetime(2025, 8, 1).date())

    # --- Category selection
    category = st.selectbox("Category", ["All"] + cfg.categories)

    # --- Build data
    all_results = []
    all_events = []
    for recipient in cfg.recipients:
        for initiator in cfg.influencers:
            weekly_res, event_res = build_weekly_stats(
                initiator, recipient, start_date, end_date,
                category=None if category == "All" else category
            )
            all_results.extend(weekly_res)
            all_events.extend(event_res)

    df = pd.DataFrame(all_results)
    event_df = pd.DataFrame(all_events)

    # -----------------------
    # Top Scorecard
    # -----------------------
    st.subheader("🏆 Initiator Leaderboard (by Recipient)")

    leader_counts = {i: 0 for i in cfg.influencers}
    for recipient in cfg.recipients:
        sub = df[df["Recipient"] == recipient]
        if sub.empty:
            continue
        latest_week = sub["Week"].max()
        latest = sub[sub["Week"] == latest_week]
        if latest.empty:
            continue
        best = latest.loc[latest["AvgScore"].idxmax()]
        leader_counts[best["Initiator"]] += 1

    cols = st.columns(len(cfg.influencers))
    for idx, initiator in enumerate(cfg.influencers):
        with cols[idx]:
            st.markdown(
                f"""
                <div style="border:1px solid #ddd; border-radius:10px; padding:10px; text-align:center;">
                    <b>{initiator}</b><br>
                    <span style="font-size:20px;">{leader_counts[initiator]}</span><br>
                    <span style="color:gray;"># of Recipient Leads</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # -----------------------
    # Per-Recipient Sections
    # -----------------------
    for recipient in cfg.recipients:
        sub = df[df["Recipient"] == recipient]
        if sub.empty:
            continue

        st.markdown(f"## 🎯 Recipient: {recipient}")

        # Recipient-level initiator cards (horizontal layout)
        cols = st.columns(len(cfg.influencers))
        for idx, initiator in enumerate(cfg.influencers):
            score, delta = compute_trend(sub, initiator, recipient)
            if score is not None:
                with cols[idx]:
                    st.markdown(render_initiator_card(initiator, score, delta), unsafe_allow_html=True)

        # Charts
        plot_trends(sub, "AvgScore",
                    f"📈 Materiality Trend Over Time ({recipient})",
                    "Average Materiality Score", domain=[0, 10])

        plot_trends(sub, "Count",
                    f"📊 Document/Event Count Trend ({recipient})",
                    "Document Count")


# ✅ Run page
run_page()
