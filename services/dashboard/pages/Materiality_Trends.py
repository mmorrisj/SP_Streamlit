import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
from datetime import datetime, timedelta

from backend.app import create_app
from backend.extensions import db
from backend.scripts.models import WeeklyEvent, DailyEventSummary
from shared.utils.utils import Config
cfg = Config.from_yaml()
# ✅ Push Flask app context once so db.session works in Streamlit
app = create_app()
app.app_context().push()


# -----------------------
# Step 1: Generate canonical Mon–Sun weeks
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


# -----------------------
# Step 2: Weekly histogram
# -----------------------
def build_weekly_histogram(country, week_start, week_end, recipient=None, category=None):
    hist = {str(i): 0 for i in range(11)}
    total = 0

    weekly_events = (
        db.session.query(WeeklyEvent)
        .filter_by(initiating_country=country, week_start=week_start, week_end=week_end)
        .all()
    )

    for w_event in weekly_events:
        for link in w_event.sources:  # WeeklyEventLink
            des = db.session.get(DailyEventSummary, link.daily_summary_id)
            if not des:
                continue

            if recipient and recipient not in (des.recipient_countries or []):
                continue
            if category and category not in (des.categories or []):
                continue

            if des.material_score is not None:
                score = int(des.material_score)
                if 0 <= score <= 10:
                    hist[str(score)] += 1
                    total += 1

    if total > 0:
        return {k: v / total for k, v in hist.items()}
    return {k: 0.0 for k in hist.keys()}


def build_all_weekly_histograms(country, start_date, end_date, recipient=None, category=None):
    weeks = generate_weeks(start_date, end_date)
    results = []
    for ws, we in weeks:
        hist = build_weekly_histogram(country, ws, we, recipient, category)
        results.append({"week_start": ws, "week_end": we, "hist": hist})
    return results


# -----------------------
# Step 3: Transition matrices
# -----------------------
def build_transition_matrix(weekly_histograms):
    n_scores = 11
    matrix = np.zeros((n_scores, n_scores))

    for t in range(len(weekly_histograms) - 1):
        p_current = np.array([weekly_histograms[t][str(i)] for i in range(n_scores)])
        p_next = np.array([weekly_histograms[t + 1][str(i)] for i in range(n_scores)])
        matrix += np.outer(p_current, p_next)

    row_sums = matrix.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        matrix = np.divide(matrix, row_sums, where=row_sums > 0)

    return pd.DataFrame(matrix,
                        index=[f"From {i}" for i in range(n_scores)],
                        columns=[f"To {j}" for j in range(n_scores)])


def build_bucketed_transition_matrix(weekly_histograms):
    buckets = ["Low (0–3)", "Medium (4–6)", "High (7–10)"]
    matrix = np.zeros((3, 3))

    for t in range(len(weekly_histograms) - 1):
        current = weekly_histograms[t]
        nxt = weekly_histograms[t + 1]

        p_current = {
            "Low (0–3)": sum(current[str(i)] for i in range(0, 4)),
            "Medium (4–6)": sum(current[str(i)] for i in range(4, 7)),
            "High (7–10)": sum(current[str(i)] for i in range(7, 11)),
        }
        p_next = {
            "Low (0–3)": sum(nxt[str(i)] for i in range(0, 4)),
            "Medium (4–6)": sum(nxt[str(i)] for i in range(4, 7)),
            "High (7–10)": sum(nxt[str(i)] for i in range(7, 11)),
        }

        matrix += np.outer([p_current[b] for b in buckets],
                           [p_next[b] for b in buckets])

    row_sums = matrix.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        matrix = np.divide(matrix, row_sums, where=row_sums > 0)

    return pd.DataFrame(matrix, index=[f"From {b}" for b in buckets],
                        columns=[f"To {b}" for b in buckets])

def get_available_recipients(country: str, category: str = None):
    """Return unique recipients for given country/category that are also in cfg.recipients."""
    q = (
        db.session.query(DailyEventSummary.recipient_countries)
        .join(WeeklyEvent, WeeklyEvent.initiating_country == DailyEventSummary.initiating_country)
        .filter(DailyEventSummary.initiating_country == country)
    )
    if category:
        q = q.filter(DailyEventSummary.categories.contains([category]))

    results = q.all()

    # Flatten JSONB lists
    all_recipients = set()
    for row in results:
        if row[0]:
            all_recipients.update(row[0])

    # Only keep those defined in cfg.recipients
    valid_recipients = [r for r in all_recipients if r in cfg.recipients]
    return sorted(valid_recipients)

# -----------------------
# Step 4: Visualizations
# -----------------------
def visualize_transition_matrix(matrix_df, title="Transition Matrix", color_scheme="blues", bucketed=False):
    st.subheader(title)
    data = matrix_df.reset_index().melt(id_vars="index", var_name="To", value_name="Probability")
    data.rename(columns={"index": "From"}, inplace=True)

    if not bucketed:
        # Extract numeric values for ordering
        data["From_num"] = data["From"].str.extract(r"(\d+)").astype(int)
        data["To_num"] = data["To"].str.extract(r"(\d+)").astype(int)

        chart = (
            alt.Chart(data)
            .mark_rect()
            .encode(
                x=alt.X("To_num:O", title="Next Score",
                        sort=list(range(data["To_num"].min(), data["To_num"].max() + 1))),
                y=alt.Y("From_num:O", title="Current Score",
                        sort=list(range(data["From_num"].max(), data["From_num"].min() - 1, -1))),
                color=alt.Color("Probability:Q", scale=alt.Scale(scheme=color_scheme)),
                tooltip=["From", "To", alt.Tooltip("Probability:Q", format=".2f")]
            )
            .properties(width=600, height=400)
        )

    else:
        bucket_order = ["Low (0–3)", "Medium (4–6)", "High (7–10)"]
        chart = (
            alt.Chart(data)
            .mark_rect()
            .encode(
                x=alt.X("To:N", title="Next Bucket", sort=bucket_order),
                y=alt.Y("From:N", title="Current Bucket", sort=bucket_order[::-1]),
                color=alt.Color("Probability:Q", scale=alt.Scale(scheme=color_scheme)),
                tooltip=["From", "To", alt.Tooltip("Probability:Q", format=".2f")]
            )
            .properties(width=400, height=300)
        )

    st.altair_chart(chart, use_container_width=True)


def visualize_expected_trend(weekly_data, smooth=True, window=3):
    expected_scores = []
    for entry in weekly_data:
        # Skip last week if it ends before the true end of dataset (partial week)
        if entry["week_end"] < max(w["week_end"] for w in weekly_data):
            hist = entry["hist"]
            exp = sum(int(k) * v for k, v in hist.items())
            expected_scores.append({"Week": entry["week_start"], "ExpectedScore": exp})

    if not expected_scores:
        st.warning("No complete weeks available for expected trend.")
        return

    df = pd.DataFrame(expected_scores)
    df["Week"] = pd.to_datetime(df["Week"])
    df = df.sort_values("Week")

    if smooth:
        df["ExpectedScore"] = (
            df["ExpectedScore"]
            .rolling(window=window, min_periods=1, center=True)
            .mean()
        )

    st.subheader("Expected Materiality Trend Over Time")
    chart = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("Week:T", title="Week"),
            y=alt.Y("ExpectedScore:Q", scale=alt.Scale(domain=[0, 10])),
            tooltip=["Week:T", "ExpectedScore:Q"]
        )
        .properties(width=700)
    )
    st.altair_chart(chart, use_container_width=True)



def summarize_transitions(matrix_df, bucketed=False):
    """Compute chance of upward, downward, and stable transitions."""
    if not bucketed:
        # Extract numeric scores from labels
        rows = [int(idx.split()[-1]) for idx in matrix_df.index]
        cols = [int(col.split()[-1]) for col in matrix_df.columns]
    else:
        # Map buckets to numeric ranges for ordering
        bucket_map = {"Low (0–3)": 0, "Medium (4–6)": 1, "High (7–10)": 2}
        rows = [bucket_map[idx.replace("From ", "")] for idx in matrix_df.index]
        cols = [bucket_map[col.replace("To ", "")] for col in matrix_df.columns]

    up, down, same = 0.0, 0.0, 0.0
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            p = matrix_df.iloc[i, j]
            if c > r:
                up += p
            elif c < r:
                down += p
            else:
                same += p

    total = up + down + same
    if total > 0:
        up, down, same = up / total, down / total, same / total

    return {"Up": up, "Down": down, "Stable": same}

def show_transition_summary(matrix_df, bucketed=False):
    summary = summarize_transitions(matrix_df, bucketed=bucketed)
    st.write(
        f"➡️ **Stable**: {summary['Stable']:.1%} &nbsp;&nbsp; "
        f"📈 **Up**: {summary['Up']:.1%} &nbsp;&nbsp; "
        f"📉 **Down**: {summary['Down']:.1%}"
    )

def build_weekly_transition_trends(weekly_data, bucketed=False):
    """Return list of dicts with Up/Down/Stable per week transition."""
    trends = []
    if not bucketed:
        rows = list(range(11))
    else:
        rows = [0, 1, 2]  # Low, Medium, High

    for t in range(len(weekly_data) - 1):
        hist_cur = weekly_data[t]["hist"]
        hist_next = weekly_data[t+1]["hist"]

        if not bucketed:
            matrix = np.outer(
                [hist_cur[str(i)] for i in rows],
                [hist_next[str(i)] for i in rows]
            )
        else:
            def collapse(hist):
                return [
                    sum(hist[str(i)] for i in range(0, 4)),   # Low
                    sum(hist[str(i)] for i in range(4, 7)),   # Medium
                    sum(hist[str(i)] for i in range(7, 11))   # High
                ]
            matrix = np.outer(collapse(hist_cur), collapse(hist_next))

        # Summarize transitions
        up, down, same = 0.0, 0.0, 0.0
        for i, r in enumerate(rows):
            for j, c in enumerate(rows):
                p = matrix[i, j]
                if c > r: up += p
                elif c < r: down += p
                else: same += p
        total = up + down + same
        if total > 0:
            up, down, same = up/total, down/total, same/total

        trends.append({
            "Week": weekly_data[t]["week_end"],  # use week_end as label
            "Up": up,
            "Down": down,
            "Stable": same
        })

    return pd.DataFrame(trends)

def visualize_transition_trends(trend_df, title="Transition Trends Over Time",
                                smooth=True, window=3):
    st.subheader(title)

    data = trend_df.melt(id_vars="Week", var_name="Direction", value_name="Probability")
    data["Week"] = pd.to_datetime(data["Week"])

    # Drop only the last week (partial)
    if len(data["Week"].unique()) > 1:
        last_week = data["Week"].max()
        data = data[data["Week"] < last_week]

    if data.empty:
        st.warning("No complete weeks available for transition trends.")
        return

    if smooth:
        smoothed_parts = []
        for direction, group in data.groupby("Direction"):
            group = group.sort_values("Week")
            group["Probability"] = (
                group["Probability"]
                .rolling(window=window, min_periods=1, center=True)
                .mean()
            )
            smoothed_parts.append(group)
        data = pd.concat(smoothed_parts, ignore_index=True)

    chart = (
        alt.Chart(data)
        .mark_line(point=True)
        .encode(
            x=alt.X("Week:T", title="Week"),
            y=alt.Y("Probability:Q", scale=alt.Scale(domain=[0, 1])),
            color="Direction:N",
            tooltip=["Week:T", "Direction", alt.Tooltip("Probability:Q", format=".2f")]
        )
        .properties(width=700)
    )
    st.altair_chart(chart, use_container_width=True)



def smooth_trends(trend_df, window=2):
    return (
        trend_df
        .rolling(window=window, on="Week", min_periods=1)
        .mean()
        .assign(Direction=trend_df["Direction"])  # keep labels
    )

def forecast_n_weeks(p0, transition_matrix, n=3):
    """
    Forecast probability distribution n weeks ahead using transition matrix powers.
    """
    P = np.nan_to_num(np.array(transition_matrix, dtype=float), nan=0.0)

    if P.shape[0] != P.shape[1]:
        raise ValueError("Transition matrix must be square")

    if p0.sum() == 0:
        return np.zeros_like(p0)

    # Normalize starting distribution
    p0 = p0 / p0.sum()

    # Matrix power
    Pn = np.linalg.matrix_power(P, n)
    return p0 @ Pn


def visualize_forecast(p0, transition_matrix, max_horizon=3):
    st.subheader(f"📈 {max_horizon}-Week Ahead Forecast by Material Score")

    horizons = ["Current"] + [f"+{i}w" for i in range(1, max_horizon + 1)]
    forecasts = []

    for i, h in enumerate(horizons):
        if i == 0:
            dist = p0 / p0.sum() if p0.sum() > 0 else np.zeros_like(p0)
        else:
            dist = forecast_n_weeks(p0, transition_matrix, n=i)
            dist = dist / dist.sum() if dist.sum() > 0 else np.zeros_like(dist)
        forecasts.append({"Horizon": h, "dist": dist})

    # Flatten into DataFrame
    rows = []
    for f in forecasts:
        for score, prob in enumerate(f["dist"]):
            rows.append({"Horizon": f["Horizon"], "Score": str(score), "Probability": prob})
    df = pd.DataFrame(rows)

    if df["Probability"].sum() == 0:
        st.warning("⚠ No data available for forecast (last week empty or invalid).")
        return

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("Score:N", title="Materiality Score"),
            y=alt.Y("Probability:Q", scale=alt.Scale(domain=[0, 1])),
            color="Horizon:N",
            column=alt.Column("Horizon:N", title="Week Horizon")
        )
        .properties(width=120)
    )
    st.altair_chart(chart, use_container_width=True)

def get_recent_hist(weekly_data, n=3):
    """Return averaged histogram over the last n non-empty weeks."""
    nonempty = [entry["hist"] for entry in weekly_data if sum(entry["hist"].values()) > 0]
    if len(nonempty) == 0:
        return None
    recent = nonempty[-n:]  # take last n
    # average each score across weeks
    combined = {str(i): 0.0 for i in range(11)}
    for h in recent:
        for k, v in h.items():
            combined[k] += v
    for k in combined:
        combined[k] /= len(recent)
    return np.array([combined[str(i)] for i in range(11)], dtype=float)
# -----------------------
# Step 5: Streamlit page
# -----------------------

def run_page():
    st.title("📊 Materiality Score Transitions")

    # --- Select boxes with defaults ---
    country = st.selectbox(
        "Initiator Country",
        ["China", "Iran", "Turkey", "United States"],
        index=0  # default "China"
    )

    category = st.selectbox(
        "Category",
        cfg.categories,
        index=cfg.categories.index("Economic") if "Economic" in cfg.categories else 0
    )

    recipient = st.selectbox(
        "Recipient Country",
        cfg.recipients,
        index=cfg.recipients.index("Egypt") if "Egypt" in cfg.recipients else 0
    )
    if recipient == "All":
        recipient = None

    # --- Dates ---
    start_date = st.date_input("Start Date", datetime(2024, 8, 1).date())
    end_date = st.date_input("End Date", datetime(2025, 8, 1).date())

    # --- Button + pipeline ---
    if st.button("Run Analysis"):
        with st.spinner("Building histograms..."):
            weekly_data = build_all_weekly_histograms(
                country, start_date, end_date,
                recipient=recipient or None,
                category=category or None
            )
            hists = [entry["hist"] for entry in weekly_data]

            if len(hists) < 2:
                st.warning("Not enough weeks of data to build transitions.")
                return

            # Full 11x11 transitions
            matrix_df = build_transition_matrix(hists)
            visualize_transition_matrix(
                matrix_df,
                f"Full Transitions (0–10): {country} → {recipient or 'All'} ({category or 'All'})",
                color_scheme="blues",
                bucketed=False
            )
            show_transition_summary(matrix_df, bucketed=False)

            # Bucketed transitions
            bucketed_df = build_bucketed_transition_matrix(hists)
            visualize_transition_matrix(
                bucketed_df,
                f"Bucketed Transitions (Low/Medium/High): {country} → {recipient or 'All'} ({category or 'All'})",
                color_scheme="greens",
                bucketed=True
            )
            show_transition_summary(bucketed_df, bucketed=True)

            # Expected score trend
            visualize_expected_trend(weekly_data)

            # Up/Down/Stable trends
            transition_trends = build_weekly_transition_trends(weekly_data, bucketed=False)
            visualize_transition_trends(transition_trends, title="Full Score Up/Down/Stable Trend")

            bucketed_trends = build_weekly_transition_trends(weekly_data, bucketed=True)
            visualize_transition_trends(bucketed_trends, title="Bucketed Up/Down/Stable Trend")

            last_hist = weekly_data[-1]["hist"]
            p0 = get_recent_hist(weekly_data, n=3)
            if p0 is None:
                st.warning("⚠ No non-empty weeks available for forecast.")
            else:
                P = np.nan_to_num(matrix_df.to_numpy(), nan=0.0)
                visualize_forecast(p0, P, max_horizon=3)


            # ✅ Ensure Streamlit runs this page
run_page()
