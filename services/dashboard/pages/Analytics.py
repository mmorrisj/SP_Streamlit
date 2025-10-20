# pages/Analytics.py
import streamlit as st
import pandas as pd
import altair as alt
import datetime
from sqlalchemy import func
from backend.app import create_app
from backend.extensions import db
from shared.utils.utils import Config
from backend.scripts.models import (
    Document,
    Category,
    Subcategory,
    InitiatingCountry,
    RecipientCountry,
    DailyEventSummary
)

# --- DB SETUP ---
app = create_app()
ctx = app.app_context()
ctx.push()

cfg = Config.from_yaml()

st.set_page_config(page_title="Dataset Analytics", layout="wide")
st.title("📊 General Analytics Dashboard")
# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Spike Detection Settings")

window = st.sidebar.slider(
    "Rolling Mean Window (days)",
    min_value=3,
    max_value=60,
    value=7,
    step=1,
)

sensitivity = st.sidebar.slider(
    "Spike Threshold (% above rolling mean)",
    min_value=10,
    max_value=200,
    value=60,
    step=5,
)

threshold = sensitivity / 100.0
# --- FILTER CONTROLS ---
with app.app_context():
    countries = [r[0] for r in db.session.query(InitiatingCountry.initiating_country).distinct() if r[0] in cfg.influencers]
    recipients = [r[0] for r in db.session.query(RecipientCountry.recipient_country).distinct() if r[0] in cfg.recipients]
    categories = [r[0] for r in db.session.query(Category.category).distinct() if r[0] in cfg.categories]
    subcategories = [r[0] for r in db.session.query(Subcategory.subcategory).distinct() if r[0] in cfg.subcategories]
    min_date = db.session.query(func.min(Document.date)).scalar()
    max_date = db.session.query(func.max(Document.date)).scalar()

default_start = datetime.date(2024, 8, 1)
default_end = max_date or datetime.date.today()

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    country_filter = st.multiselect("Initiating Country", countries)
with col2:
    recipient_filter = st.multiselect("Recipient Country", recipients)
with col3:
    category_filter = st.multiselect("Category", categories)
with col4:
    subcategory_filter = st.multiselect("Subcategory", subcategories)
with col5:
    date_range = st.date_input("Date Range", [default_start, default_end])

# --- QUERY DATA ---
with app.app_context():
    query = (
        db.session.query(
            Document.doc_id,
            Document.date,
            Category.category,
            Subcategory.subcategory,
            InitiatingCountry.initiating_country,
            RecipientCountry.recipient_country,
        )
        .join(Category, Category.doc_id == Document.doc_id, isouter=True)
        .join(Subcategory, Subcategory.doc_id == Document.doc_id, isouter=True)
        .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id, isouter=True)
        .join(RecipientCountry, RecipientCountry.doc_id == Document.doc_id, isouter=True)
        .filter(InitiatingCountry.initiating_country != RecipientCountry.recipient_country)
        )

    if country_filter:
        query = query.filter(InitiatingCountry.initiating_country.in_(country_filter))
    if recipient_filter:
        query = query.filter(RecipientCountry.recipient_country.in_(recipient_filter))
        
    if category_filter:
        query = query.filter(Category.category.in_(category_filter))
    if subcategory_filter:
        query = query.filter(Subcategory.subcategory.in_(subcategory_filter))
    if date_range and len(date_range) == 2:
        query = query.filter(Document.date.between(date_range[0], date_range[1]))

    df = pd.DataFrame(
        query.all(),
        columns=[
            "doc_id",
            "date",
            "category",
            "subcategory",
            "initiating_country",
            "recipient_country",
        ],
    ).drop_duplicates()

# --- Apply config constraints ---
df = df[
    (df["initiating_country"].isin(cfg.influencers)) &
    (df["recipient_country"].isin(cfg.recipients)) &
    (df["category"].isin(cfg.categories)) &
    (df["subcategory"].isin(cfg.subcategories))
]

# --- METRICS ---
st.subheader("📈 Overall Stats")
if df.empty:
    st.warning("No data matches your filter criteria.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Documents", df["doc_id"].nunique())
c2.metric("Unique Categories", df["category"].nunique())
c3.metric("Unique Subcategories", df["subcategory"].nunique())
c4.metric("Date Range", f"{df['date'].min()} → {df['date'].max()}")

# --- MAIN TIMELINE WITH UNIQUE DOC COUNTS + SPIKES ---
st.subheader("📅 Timeline of Unique Documents (with Spikes)")

timeline = (
    df.groupby("date")
    .agg(count=("doc_id", "nunique"))
    .reset_index()
    .sort_values("date")
)

# reindex to ensure continuous days
all_dates = pd.date_range(timeline["date"].min(), timeline["date"].max(), freq="D")
timeline = timeline.set_index("date").reindex(all_dates, fill_value=0).rename_axis("date").reset_index()

# rolling mean
timeline["rolling_mean"] = timeline["count"].rolling(window=window, min_periods=5).mean()

# spike detection
timeline["pct_bump"] = (timeline["count"] - timeline["rolling_mean"]) / timeline["rolling_mean"]
timeline["abs_bump"] = timeline["count"] - timeline["rolling_mean"]
timeline["is_spike"] = (timeline["pct_bump"] > threshold) & (timeline["abs_bump"] >= 5)

# chart
base = alt.Chart(timeline).encode(x="date:T")
line = base.mark_line(color="blue").encode(y="count:Q")
avg_line = base.mark_line(color="orange").encode(y="rolling_mean:Q")
spike_points = (
    alt.Chart(timeline[timeline["is_spike"]])
    .mark_point(size=100, color="red", shape="triangle-up")
    .encode(
        x="date:T",
        y="count:Q",
        tooltip=["date:T", "count:Q", "rolling_mean:Q", "pct_bump:Q", "abs_bump:Q"]
    )
)

st.altair_chart(line + avg_line + spike_points, use_container_width=True)


# --- SPIKE DRILL-DOWN WITH DAILY EVENT SUMMARY ---
spike_dates = timeline.loc[timeline["is_spike"], "date"].tolist()

if spike_dates:
    st.markdown("### 🔎 Explore Spike Days")
    selected_date = st.selectbox("Select a spike date:", spike_dates)

    if selected_date:
        st.write(f"Showing events for **{selected_date}** (≥2 articles)")

        with app.app_context():
            events = (
                db.session.query(
                    DailyEventSummary.event_name,
                    DailyEventSummary.document_count,
                    DailyEventSummary.unique_source_count,
                    DailyEventSummary.summary_text,
                    DailyEventSummary.material_score,
                )
                .filter(DailyEventSummary.report_date == selected_date)
                .filter(DailyEventSummary.document_count >= 1)
                .order_by(DailyEventSummary.document_count.desc())
                .all()
            )

        if not events:
            st.info("No events with ≥5 articles on this day.")
        else:
            event_df = pd.DataFrame(
                events,
                columns=["Event Name", "Articles", "Sources", "Outcomes", "Metrics"]
            )
            st.dataframe(event_df, use_container_width=True)
# --- CATEGORY DISTRIBUTION ---
st.subheader("📊 Category Distribution")
cat_dist = (
    df.dropna(subset=["category"])
      .groupby("category")
      .agg(count=("doc_id", "nunique"))
      .reset_index()
      .sort_values("count", ascending=False)
)
if cat_dist.empty:
    st.info("No categories available for this selection.")
else:
    cat_chart = (
        alt.Chart(cat_dist)
        .mark_bar()
        .encode(
            x=alt.X("category:N", sort="-y"),
            y="count:Q",
            color="category:N",
            tooltip=["category", "count"]
        )
    )
    st.altair_chart(cat_chart, use_container_width=True)

# --- RECIPIENT DISTRIBUTION ---
st.subheader("🌍 Recipient Country Distribution")
rec_dist = (
    df.dropna(subset=["recipient_country"])
      .groupby("recipient_country")
      .agg(count=("doc_id", "nunique"))
      .reset_index()
      .sort_values("count", ascending=False)
)
if rec_dist.empty:
    st.info("No recipient countries available for this selection.")
else:
    rec_chart = (
        alt.Chart(rec_dist)
        .mark_bar()
        .encode(
            x=alt.X("recipient_country:N", sort="-y"),
            y="count:Q",
            color="recipient_country:N",
            tooltip=["recipient_country", "count"]
        )
    )
    st.altair_chart(rec_chart, use_container_width=True)

# --- BIG 4 METRICS ---
st.subheader("🌍 Big 4 Country Metrics")
big4 = ["China", "Russia", "Iran", "United States"]
big4_df = df[df["initiating_country"].isin(big4)]

if big4_df.empty:
    st.info("No documents found for Big 4 countries in this filter range.")
else:
    total_docs = df["doc_id"].nunique()
    b1, b2, b3, b4 = st.columns(4)
    for col, country in zip([b1, b2, b3, b4], big4):
        subset = big4_df[big4_df["initiating_country"] == country]
        count = subset["doc_id"].nunique()
        pct = (count / total_docs * 100) if total_docs else 0
        col.metric(country, f"{count} ({pct:.1f}%)")

    # Big 4 timeline
    st.markdown("#### 📅 Big 4 Timeline with Rolling Mean ± Std Dev")
    big4_timeline = (
        big4_df.groupby(["date", "initiating_country"])
        .agg(count=("doc_id", "count"))
        .reset_index()
        .sort_values("date")
    )
    big4_timeline["rolling_mean"] = (
        big4_timeline.groupby("initiating_country")["count"]
        .transform(lambda x: x.rolling(window=7, min_periods=3).mean())
    )
    big4_timeline["rolling_std"] = (
        big4_timeline.groupby("initiating_country")["count"]
        .transform(lambda x: x.rolling(window=7, min_periods=3).std())
    )
    big4_timeline["upper"] = big4_timeline["rolling_mean"] + big4_timeline["rolling_std"]
    big4_timeline["lower"] = (big4_timeline["rolling_mean"] - big4_timeline["rolling_std"]).clip(lower=0)

    base = alt.Chart(big4_timeline).encode(x="date:T", color="initiating_country:N")
    line = base.mark_line().encode(y="count:Q")
    avg_line = base.mark_line(strokeDash=[5, 3]).encode(y="rolling_mean:Q")
    band = base.mark_area(opacity=0.15).encode(y="lower:Q", y2="upper:Q")

    st.altair_chart(band + line + avg_line, use_container_width=True)

    # Big 4 category comparison
    st.markdown("#### 📊 Big 4 Category Breakdown")
    cat_compare = (
        big4_df.dropna(subset=["category"])
               .groupby(["initiating_country", "category"])
               .agg(count=("doc_id", "nunique"))
               .reset_index()
               .sort_values("count", ascending=False)
    )
    if cat_compare.empty:
        st.info("No category data for Big 4 in this selection.")
    else:
        cat_chart = (
            alt.Chart(cat_compare)
            .mark_bar()
            .encode(
                x=alt.X("category:N", sort="-y"),
                y="count:Q",
                color="initiating_country:N",
                column="initiating_country:N",
                tooltip=["initiating_country", "category", "count"],
            )
        )
        st.altair_chart(cat_chart, use_container_width=True)

    # Big 4 subcategory comparison
    st.markdown("#### 📊 Big 4 Subcategory Breakdown")
    subcat_compare = (
        big4_df.dropna(subset=["subcategory"])
               .groupby(["initiating_country", "subcategory"])
               .agg(count=("doc_id", "nunique"))
               .reset_index()
               .sort_values("count", ascending=False)
    )
    if subcat_compare.empty:
        st.info("No subcategory data for Big 4 in this selection.")
    else:
        subcat_chart = (
            alt.Chart(subcat_compare)
            .mark_bar()
            .encode(
                x=alt.X("subcategory:N", sort="-y"),
                y="count:Q",
                color="initiating_country:N",
                column="initiating_country:N",
                tooltip=["initiating_country", "subcategory", "count"],
            )
        )
        st.altair_chart(subcat_chart, use_container_width=True)
    # --- MAIN TIMELINE WITH STD DEV + SPIKE HIGHLIGHTS ---
    st.subheader("📅 Timeline of Article Counts (with Std Dev Bands & Spike Highlights)")

    timeline = (
        df.groupby("date")
        .agg(count=("doc_id", "count"))
        .reset_index()
        .sort_values("date")
    )
    timeline["rolling_mean"] = timeline["count"].rolling(window=7, min_periods=3).mean()
    timeline["rolling_std"] = timeline["count"].rolling(window=7, min_periods=3).std()
    timeline["upper"] = timeline["rolling_mean"] + timeline["rolling_std"]
    timeline["lower"] = (timeline["rolling_mean"] - timeline["rolling_std"]).clip(lower=0)

    # Z-score for spike detection
    timeline["zscore"] = (timeline["count"] - timeline["rolling_mean"]) / timeline["rolling_std"]
    timeline["is_spike"] = timeline["zscore"] > 2

    # Base chart
    base = alt.Chart(timeline).encode(x="date:T")
    line = base.mark_line(color="blue").encode(y="count:Q")
    avg_line = base.mark_line(color="orange").encode(y="rolling_mean:Q")
    band = base.mark_area(opacity=0.2, color="lightblue").encode(y="lower:Q", y2="upper:Q")

    # Spike markers
    spike_points = (
        alt.Chart(timeline[timeline["is_spike"]])
        .mark_point(size=100, color="red", shape="triangle-up")
        .encode(
            x="date:T",
            y="count:Q",
            tooltip=["date:T", "count:Q", "zscore"]
        )
    )

    st.altair_chart(band + line + avg_line + spike_points, use_container_width=True)

    # --- SPIKE DRILL-DOWN ---
    spike_dates = timeline.loc[timeline["is_spike"], "date"].tolist()

    if spike_dates:
        st.markdown("### 🔎 Explore Spike Days")
        selected_date = st.selectbox("Select a spike date:", spike_dates)

        if selected_date:
            # Show top drivers on that day
            drill_df = df[df["date"] == selected_date]
            st.write(f"**{len(drill_df)} documents on {selected_date}**")

            # Show grouped events/categories
            drivers = (
                drill_df.groupby(["category", "subcategory"])
                .agg(doc_count=("doc_id", "nunique"))
                .reset_index()
                .sort_values("doc_count", ascending=False)
            )
            st.subheader("Top Categories/Subcategories Driving Spike")
            st.dataframe(drivers)

            # Optionally show raw docs
            with st.expander("See underlying documents"):
                st.dataframe(drill_df[["doc_id", "initiating_country", "recipient_country", "category", "subcategory"]])