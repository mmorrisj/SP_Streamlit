import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
from datetime import datetime, timedelta

from backend.app import create_app
from backend.extensions import db
from backend.scripts.models import DailyEventSummary
from backend.scripts.utils import Config

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
    current_start = start_date - timedelta(days=start_date.weekday())  # align to Monday
    while current_start <= end_date:
        current_end = current_start + timedelta(days=6)
        weeks.append((current_start, min(current_end, end_date)))
        current_start += timedelta(days=7)
    return weeks


def build_weekly_stats(initiator, recipient, start_date, end_date, category=None):
    """Return weekly avg materiality + count for initiator→recipient."""
    weeks = generate_weeks(start_date, end_date)
    results = []

    for ws, we in weeks:
        q = (
            db.session.query(DailyEventSummary)
            .filter(
                DailyEventSummary.initiating_country == initiator,
                DailyEventSummary.report_date.between(ws, we),
            )
        )
        if recipient != "All":
            q = q.filter(DailyEventSummary.recipient_countries.contains([recipient]))
        if category and category != "All":
            q = q.filter(DailyEventSummary.categories.contains([category]))

        rows = q.all()
        if not rows:
            continue

        scores = [r.material_score for r in rows if r.material_score is not None]
        if not scores:
            continue

        avg_score = np.mean(scores)
        count = len(rows)
        results.append(
            {
                "Week": ws,
                "Initiator": initiator,
                "Recipient": recipient,
                "Category": category or "All",
                "AvgScore": avg_score,
                "Count": count,
            }
        )
    return results


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
    for recipient in cfg.recipients:
        for initiator in cfg.influencers:
            res = build_weekly_stats(
                initiator, recipient, start_date, end_date,
                category=None if category == "All" else category
            )
            all_results.extend(res)

    if not all_results:
        st.warning("No data available for selected filters.")
        return

    df = pd.DataFrame(all_results)

    # --- Charts by recipient
    for recipient in cfg.recipients:
        sub = df[df["Recipient"] == recipient]
        if sub.empty:
            continue

        st.markdown(f"## 🎯 Recipient: {recipient}")

        plot_trends(sub, "AvgScore",
                    f"📈 Materiality Trend Over Time ({recipient})",
                    "Average Materiality Score", domain=[0, 10])

        plot_trends(sub, "Count",
                    f"📊 Document/Event Count Trend ({recipient})",
                    "Document Count")


# ✅ Run page
run_page()
