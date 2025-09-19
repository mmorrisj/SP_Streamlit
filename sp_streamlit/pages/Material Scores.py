# pages/Material_Score_Over_Time.py
import os
import pandas as pd
import datetime as dt
from sqlalchemy import create_engine, text, bindparam
import streamlit as st
import altair as alt

# -----------------------------
# DB connection
# -----------------------------
is_local = os.getenv("LOCAL", "true").lower() == "true"
db_host = "postgres_db"
DATABASE_URL = f"postgresql://matthew50:softpower@{db_host}:5432/softpower-db"

st.set_page_config(page_title="Material Score Over Time", page_icon="📈", layout="wide")
st.title("📈 Material Score Over Time")
st.caption("Daily averages from DailyEventSummary; filter by Initiating and/or Recipient and plot series by either.")

# -----------------------------
# Helpers: lookups
# -----------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_available_initiators() -> list[str]:
    engine = create_engine(DATABASE_URL)
    q = text("""
        SELECT DISTINCT initiating_country
        FROM daily_event_summaries
        WHERE material_score IS NOT NULL
        ORDER BY initiating_country
    """)
    with engine.connect() as conn:
        rows = conn.execute(q).fetchall()
    return [r[0] for r in rows]

@st.cache_data(ttl=300, show_spinner=False)
def fetch_available_recipients() -> list[str]:
    engine = create_engine(DATABASE_URL)
    q = text("""
        SELECT DISTINCT country
        FROM daily_event_recipient_countries
        ORDER BY country
    """)
    with engine.connect() as conn:
        rows = conn.execute(q).fetchall()
    return [r[0] for r in rows]

# -----------------------------
# Core query (supports grouping by initiator or recipient)
# -----------------------------
from sqlalchemy import create_engine, text, bindparam

@st.cache_data(ttl=300, show_spinner=True)
def fetch_timeseries(
    initiators: list[str],
    recipients: list[str],
    start: dt.date | None,
    end: dt.date | None,
    group_by: str = "initiator",   # "initiator" or "recipient"
) -> pd.DataFrame:
    """
    Returns columns: date, series, avg_material_score, initiating_country, recipient_country
    """
    engine = create_engine(DATABASE_URL)

    # --- dynamic WHERE / JOIN pieces ---
    clauses = ["des.material_score IS NOT NULL"]
    params: dict = {}

    # dates
    if start:
        clauses.append("des.report_date >= :start_date")
        params["start_date"] = start
    if end:
        clauses.append("des.report_date <= :end_date")
        params["end_date"] = end

    # initiator filter
    initiator_sql = ""
    if initiators:
        initiator_sql = "AND des.initiating_country IN :initiators"
        params["initiators"] = initiators

    # recipient join/filter only if needed
    join_recip = (group_by == "recipient") or bool(recipients)
    recipient_join = "JOIN daily_event_recipient_countries derc ON derc.daily_event_summary_id = des.id" if join_recip else ""

    recipient_filter_sql = ""
    if recipients:
        recipient_filter_sql = "AND derc.country IN :recipients"
        params["recipients"] = recipients

    # select/group target
    if group_by == "recipient":
        select_series = "derc.country AS series"
        group_series = "derc.country"
    else:
        select_series = "des.initiating_country AS series"
        group_series = "des.initiating_country"

    # recipient column in SELECT for consistent schema
    select_recipient = "derc.country" if join_recip else "NULL"
    group_recipient = ", derc.country" if join_recip else ""

    where_sql = " AND ".join(clauses)
    sql = f"""
        SELECT
            des.report_date AS date,
            {select_series},
            des.initiating_country,
            {select_recipient} AS recipient_country,
            AVG(des.material_score)::float AS avg_material_score
        FROM daily_event_summaries des
        {recipient_join}
        WHERE {where_sql}
        {initiator_sql}
        {recipient_filter_sql}
        GROUP BY des.report_date, {group_series}, des.initiating_country{group_recipient}
        ORDER BY des.report_date ASC
    """

    stmt = text(sql)
    # Bind only the params that actually appear in the SQL text:
    if initiators:
        stmt = stmt.bindparams(bindparam("initiators", expanding=True))
    if recipients:
        stmt = stmt.bindparams(bindparam("recipients", expanding=True))

    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn, params=params)

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    else:
        df = pd.DataFrame(columns=["date", "series", "avg_material_score", "initiating_country", "recipient_country"])
    return df

# -----------------------------
# Sidebar filters
# -----------------------------
with st.sidebar:
    st.header("Filters")

    all_initiators = fetch_available_initiators()
    default_inits = ["China"] if "China" in all_initiators else all_initiators[:1]
    initiators = st.multiselect("Initiating country (filter)", options=all_initiators, default=default_inits)

    all_recipients = fetch_available_recipients()
    recipients = st.multiselect("Recipient country (filter)", options=all_recipients, default=[])

    st.divider()
    group_by = st.radio("Plot series by", options=["Initiating country", "Recipient country"], index=0, horizontal=False)
    group_key = "initiator" if group_by.startswith("Initiating") else "recipient"

    # Date range
    min_date = dt.date(2020, 1, 1)
    max_date = dt.date.today()
    dater = st.date_input("Date range", value=(min_date, max_date))
    if isinstance(dater, tuple):
        start_date, end_date = dater
    else:
        start_date, end_date = min_date, dater

    st.divider()
    freq = st.selectbox("Resample frequency", ["Daily", "Weekly (W)", "Monthly (MS)"], index=0)
    agg_stat = st.selectbox("Aggregate statistic", ["Mean", "Median"], index=0)
    roll = st.number_input("Rolling window (periods)", min_value=0, max_value=365, value=7, step=1)
    show_points = st.checkbox("Show data points", value=False)
    normalize = st.checkbox("Normalize per-series (z-score)", value=False)

# -----------------------------
# Load + transform
# -----------------------------
df = fetch_timeseries(initiators, recipients, start_date, end_date, group_by=group_key)
if df.empty:
    st.info("No data found for the selected filters.")
    st.stop()

# pivot to (date x series)
pivot = df.pivot_table(index="date", columns="series", values="avg_material_score", aggfunc="mean")
pivot = pivot.asfreq("D")

# resample
if freq == "Weekly (W)":
    pivot_ag = pivot.resample("W").mean() if agg_stat == "Mean" else pivot.resample("W").median()
elif freq == "Monthly (MS)":
    pivot_ag = pivot.resample("MS").mean() if agg_stat == "Mean" else pivot.resample("MS").median()
else:
    pivot_ag = pivot

# rolling
if roll and roll > 0:
    pivot_sm = pivot_ag.rolling(window=roll, min_periods=max(1, roll // 2)).mean()
else:
    pivot_sm = pivot_ag

plot_df = pivot_sm.copy()
if normalize:
    plot_df = (plot_df - plot_df.mean()) / plot_df.std(ddof=0)

keep_cols = [c for c in plot_df.columns if plot_df[c].notna().any()]
plot_df = plot_df[keep_cols].dropna(how="all")
if plot_df.empty:
    st.info("Data exists, but all selected series are NaN after transformations. Try different filters.")
    st.stop()

# -----------------------------
# KPIs
# -----------------------------
kpi_title = "Recipient" if group_key == "recipient" else "Initiator"
latest = plot_df.dropna(how="all").tail(1)
cols = st.columns(min(4, len(keep_cols) or 1))
if not latest.empty:
    for i, c in enumerate(keep_cols[:len(cols)]):
        v = latest[c].iloc[0]
        cols[i].metric(f"{kpi_title}: {c}", f"{v:.2f}" if pd.notna(v) else "—")

# -----------------------------
# Chart
# -----------------------------
title_y = "Normalized Score" if normalize else "Avg Material Score"
melt = plot_df.reset_index().melt("date", var_name="series", value_name="score").dropna(subset=["score"])

line = alt.Chart(melt).mark_line(interpolate="monotone").encode(
    x=alt.X("date:T", title="Date"),
    y=alt.Y("score:Q", title=title_y,scale=alt.Scale(domain=[0, 10])),
    color=alt.Color("series:N", title=kpi_title),
)

chart = line
if show_points:
    chart = chart + alt.Chart(melt).mark_point().encode(
        x="date:T",
        y="score:Q",
        color="series:N",
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("series:N", title=kpi_title),
            alt.Tooltip("score:Q", title="Value", format=".2f"),
        ],
    )

st.altair_chart(chart.properties(height=460), use_container_width=True)

# -----------------------------
# Detail table + download
# -----------------------------
st.subheader("Data")
out = plot_df.copy()
out.index.name = "date"
st.dataframe(out.reset_index(), use_container_width=True)
st.download_button(
    "⬇️ Download CSV",
    data=out.reset_index().to_csv(index=False).encode("utf-8"),
    file_name=f"material_score_over_time_by_{kpi_title.lower()}.csv",
    mime="text/csv",
)

with st.expander("Notes"):
    st.markdown(
        """
- Source: `daily_event_summaries.material_score` with optional join to
  `daily_event_recipient_countries` to filter/plot by recipient.
- **Filters** narrow the rows before aggregation.
- **Plot series by** chooses the color grouping: Initiator or Recipient.
- Resampling (Daily/Weekly/Monthly), optional rolling mean, and per-series normalization are available.
        """
    )
