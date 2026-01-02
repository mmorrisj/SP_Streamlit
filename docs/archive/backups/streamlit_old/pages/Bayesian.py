# pages/Bayesian_Trends.py
import os
import pandas as pd
import datetime as dt
from sqlalchemy import text
import streamlit as st
import altair as alt

from backend.app import create_app
from backend.extensions import db

# -----------------------------
# Streamlit setup
# -----------------------------
st.set_page_config(page_title="Bayesian Trends", page_icon="📊", layout="wide")
st.title("📊 Bayesian Trends")
st.caption("Bayesian probabilities of increase in material score by initiator, recipient, and category/subcategory.")

import streamlit as st
from datetime import date
import numpy as np
import pandas as pd

def build_transition_matrix(weekly_histograms):
    """
    Build a 11x11 transition probability matrix from a list of weekly histograms.

    Args:
        weekly_histograms (list[dict]): 
            Each element is a normalized probability distribution (0–10) for one week.
            Example: {"0":0.0, "1":0.0, "2":0.1, "3":0.3, "4":0.6, ...}

    Returns:
        pd.DataFrame: transition matrix, rows=current score, cols=next score.
    """
    n_scores = 11
    matrix = np.zeros((n_scores, n_scores))

    for t in range(len(weekly_histograms) - 1):
        current = weekly_histograms[t]
        nxt = weekly_histograms[t + 1]

        # convert dict to arrays
        p_current = np.array([current[str(i)] for i in range(n_scores)])
        p_next = np.array([nxt[str(i)] for i in range(n_scores)])

        # outer product distributes transitions proportionally
        matrix += np.outer(p_current, p_next)

    # normalize each row into a probability distribution
    row_sums = matrix.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        matrix = np.divide(matrix, row_sums, where=row_sums > 0)

    return pd.DataFrame(matrix, 
                        index=[f"From {i}" for i in range(n_scores)],
                        columns=[f"To {j}" for j in range(n_scores)])
import streamlit as st
import altair as alt

def visualize_transition_matrix(matrix_df, title="Transition Probabilities"):
    """
    Visualize transition probabilities as a heatmap in Streamlit.
    """
    st.subheader(title)
    data = matrix_df.reset_index().melt(id_vars="index", var_name="To", value_name="Probability")
    data.rename(columns={"index": "From"}, inplace=True)

    chart = (
        alt.Chart(data)
        .mark_rect()
        .encode(
            x=alt.X("To:N", title="Next Materiality Score"),
            y=alt.Y("From:N", title="Current Materiality Score"),
            color=alt.Color("Probability:Q", scale=alt.Scale(scheme="blues")),
            tooltip=["From", "To", alt.Tooltip("Probability:Q", format=".2f")]
        )
        .properties(width=600, height=400)
    )

    st.altair_chart(chart, use_container_width=True)


def visualize_expected_trend(weekly_histograms, weeks):
    """
    Show expected score over time as a line chart.
    """
    expected_scores = []
    for i, hist in enumerate(weekly_histograms):
        exp = sum(int(k) * v for k, v in hist.items())
        expected_scores.append({"Week": weeks[i], "ExpectedScore": exp})

    df = pd.DataFrame(expected_scores)

    st.subheader("Expected Materiality Trend Over Time")
    chart = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x="Week:T",
            y=alt.Y("ExpectedScore:Q", scale=alt.Scale(domain=[0, 10])),
            tooltip=["Week:T", "ExpectedScore:Q"]
        )
        .properties(width=700)
    )

    st.altair_chart(chart, use_container_width=True)

st.title("📊 Materiality Score Transition Analysis")

# Example: load precomputed weekly histograms for China→Egypt→Economic
# In practice, you'd fetch these with your `build_conditional_histogram`
weekly_histograms = [
    {"0":0,"1":0,"2":0,"3":0,"4":0.2,"5":0.5,"6":0.3,"7":0,"8":0,"9":0,"10":0},
    {"0":0,"1":0,"2":0,"3":0,"4":0.1,"5":0.3,"6":0.4,"7":0.2,"8":0,"9":0,"10":0},
    {"0":0,"1":0,"2":0,"3":0,"4":0,"5":0.2,"6":0.3,"7":0.4,"8":0.1,"9":0,"10":0},
]

weeks = [date(2025,8,11), date(2025,8,18), date(2025,8,25)]

# --- Transition Matrix ---
matrix_df = build_transition_matrix(weekly_histograms)
visualize_transition_matrix(matrix_df, title="China→Egypt→Economic Transition Matrix")

# --- Expected Score Trend ---
visualize_expected_trend(weekly_histograms, weeks)
# -----------------------------
# DB helpers
# -----------------------------
def fetch_options():
    q = """
        SELECT DISTINCT initiator, recipient, category, subcategory
        FROM bayesian_results
        ORDER BY initiator, recipient, category, subcategory
    """
    with create_app().app_context():
        df = pd.read_sql(q, db.engine)
    return df

def fetch_results(initiator, recipient, category, subcategory=None):
    q = """
        SELECT created_at, prob_increase, lower, upper, initiator, recipient, category, subcategory
        FROM bayesian_results
        WHERE initiator = :initiator
          AND recipient = :recipient
          AND category = :category
          AND method = 'advi_material_score'
    """
    if subcategory:
        q += " AND subcategory = :subcategory"
    q += " ORDER BY created_at"

    params = {"initiator": initiator, "recipient": recipient, "category": category}
    if subcategory:
        params["subcategory"] = subcategory

    with create_app().app_context():
        df = pd.read_sql(text(q), db.engine, params=params)
    return df

# -----------------------------
# UI: filters (multi-select)
# -----------------------------
opts = fetch_options()

sel_initiators = st.multiselect("Initiator(s)", opts["initiator"].dropna().unique())
if not sel_initiators:
    st.stop()

sel_recipients = st.multiselect(
    "Recipient(s)", 
    opts.query("initiator in @sel_initiators")["recipient"].dropna().unique()
)

sel_categories = st.multiselect(
    "Category(s)", 
    opts.query("initiator in @sel_initiators and recipient in @sel_recipients")["category"].dropna().unique()
)

sel_subcategories = st.multiselect(
    "Subcategory(s) [optional]", 
    opts.query(
        "initiator in @sel_initiators and recipient in @sel_recipients and category in @sel_categories"
    )["subcategory"].dropna().unique()
)

# -----------------------------
# Load and combine results
# -----------------------------
dfs = []
for i in sel_initiators:
    for r in sel_recipients:
        for c in sel_categories:
            if sel_subcategories:
                for s in sel_subcategories:
                    df = fetch_results(i, r, c, s)
                    if not df.empty:
                        df["label"] = f"{i}-{r}-{c}-{s}"
                        dfs.append(df)
            else:
                df = fetch_results(i, r, c)
                if not df.empty:
                    df["label"] = f"{i}-{r}-{c}"
                    dfs.append(df)

if not dfs:
    st.warning("No results found for this selection.")
    st.stop()

df_all = pd.concat(dfs, ignore_index=True)
df_all["created_at"] = pd.to_datetime(df_all["created_at"])
df_all["date"] = df_all["created_at"].dt.date

# -----------------------------
# Timeline Chart (overlayed)
# -----------------------------
base = alt.Chart(df_all).encode(
    x="date:T",
    color="label:N"
)

lines = base.mark_line(point=True).encode(
    y=alt.Y("prob_increase:Q", title="Probability of Increase"),
    tooltip=["label", "date", "prob_increase"]
)

bands = base.mark_area(opacity=0.15).encode(
    y="lower:Q",
    y2="upper:Q"
)

st.altair_chart((bands + lines).interactive(), use_container_width=True)

# -----------------------------
# Near-term (last 3 weeks)
# -----------------------------
cutoff_date = df_all["date"].max() - dt.timedelta(weeks=3)
df_recent = df_all[df_all["date"] >= cutoff_date]

if not df_recent.empty:
    near_lines = alt.Chart(df_recent).mark_line(point=True).encode(
        x="date:T",
        y=alt.Y("prob_increase:Q", title="Probability of Increase"),
        color="label:N",
        tooltip=["label", "date", "prob_increase"]
    )
    st.altair_chart(near_lines.interactive(), use_container_width=True)

# -----------------------------
# Metrics cards for each selection
# -----------------------------
st.subheader("📌 Current Probabilities & Certainty")

for label, df_grp in df_all.groupby("label"):
    latest = df_grp.iloc[-1]
    prev = df_grp.iloc[-2] if len(df_grp) > 1 else None

    curr_prob = latest["prob_increase"] * 100
    if prev is not None:
        delta = (latest["prob_increase"] - prev["prob_increase"]) * 100
    else:
        delta = 0.0

    # Certainty from credible interval
    if latest["upper"] is not None and latest["lower"] is not None:
        interval_width = latest["upper"] - latest["lower"]
        interval_pct = interval_width * 100
        if interval_width < 0.1:
            certainty = "High"
        elif interval_width < 0.25:
            certainty = "Medium"
        else:
            certainty = "Low"
        certainty_str = f"{certainty} (±{interval_pct:.1f}%)"
    else:
        certainty_str = "Unknown"

    c1, c2, c3 = st.columns(3)
    c1.metric(f"{label}", f"{curr_prob:.1f}%", delta=f"{delta:.1f}%")
    c2.metric("Certainty", certainty_str)
    c3.write("")  # placeholder for spacing


