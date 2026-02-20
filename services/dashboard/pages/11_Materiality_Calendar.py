"""
Materiality Calendar

Monthly materiality heatmap matrix and 90-day activity strip for each
initiating country. Uses canonical_events and daily_event_mentions.
"""

import sys
import os
import datetime
from collections import defaultdict

import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Materiality Calendar", page_icon="🗓️", layout="wide")

st.title("Materiality Calendar")
st.caption(
    "Monthly materiality heatmap by country and 90-day activity strips "
    "showing daily event intensity"
)


# ---------------------------------------------------------------------------
# Cached queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_monthly_materiality(countries):
    """Average material_score per country per month from canonical_events (master only)."""
    engine = get_engine()
    query = text("""
        SELECT
            initiating_country,
            date_trunc('month', first_mention_date)::date AS month,
            AVG(CAST(material_score AS FLOAT)) AS avg_score,
            COUNT(*) AS event_count
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND material_score IS NOT NULL
          AND initiating_country IN :countries
        GROUP BY initiating_country, date_trunc('month', first_mention_date)
        ORDER BY initiating_country, month
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"countries": tuple(countries)})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_daily_activity(countries, days_back=90):
    """Daily event mention counts per country for the last N days."""
    engine = get_engine()
    cutoff = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    query = text("""
        SELECT
            initiating_country,
            mention_date,
            SUM(article_count) AS total_articles,
            COUNT(*) AS mention_count
        FROM daily_event_mentions
        WHERE initiating_country IN :countries
          AND mention_date >= :cutoff
        GROUP BY initiating_country, mention_date
        ORDER BY initiating_country, mention_date
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={
            "countries": tuple(countries),
            "cutoff": cutoff,
        })
    return df


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("Filters")

selected_countries = st.sidebar.multiselect(
    "Initiating Countries",
    options=cfg.influencers,
    default=cfg.influencers,
    help="Select one or more countries for the heatmap",
)

if not selected_countries:
    st.warning("Please select at least one country.")
    st.stop()


# ---------------------------------------------------------------------------
# Monthly Materiality Matrix (HTML heatmap table)
# ---------------------------------------------------------------------------

st.header("Monthly Materiality Matrix")
st.markdown(
    "Each cell shows the **average material score** of master events whose "
    "`first_mention_date` falls in that month. Color intensity indicates score magnitude."
)

monthly_df = get_monthly_materiality(selected_countries)

if monthly_df.empty:
    st.info("No materiality data found for the selected countries.")
else:
    # Pivot: rows = country, columns = months
    monthly_df['month'] = pd.to_datetime(monthly_df['month'])
    monthly_df['month_label'] = monthly_df['month'].dt.strftime('%Y-%m')

    pivot = monthly_df.pivot_table(
        index='initiating_country',
        columns='month_label',
        values='avg_score',
        aggfunc='mean',
    )

    # Sort columns chronologically
    sorted_cols = sorted(pivot.columns)
    pivot = pivot[sorted_cols]

    # Also build event-count pivot for tooltips
    count_pivot = monthly_df.pivot_table(
        index='initiating_country',
        columns='month_label',
        values='event_count',
        aggfunc='sum',
    ).reindex(columns=sorted_cols, index=pivot.index).fillna(0).astype(int)

    def score_to_color(val):
        """Map a score to a background color."""
        if pd.isna(val) or val == 0:
            return "#e0e0e0"  # gray
        if val >= 8:
            return "#e74c3c"  # red
        if val >= 6:
            return "#e67e22"  # orange
        if val >= 4:
            return "#f1c40f"  # yellow
        if val >= 2:
            return "#27ae60"  # green
        return "#e0e0e0"      # gray

    def text_color(val):
        """Choose white or black text for readability."""
        if pd.isna(val) or val == 0:
            return "#888"
        if val >= 6:
            return "#fff"
        return "#222"

    # Build HTML table
    html_parts = []
    html_parts.append("<table style='border-collapse:collapse; width:100%; font-size:13px;'>")

    # Header row
    html_parts.append("<tr><th style='padding:6px 10px; text-align:left; border:1px solid #ccc;'>Country</th>")
    for col in sorted_cols:
        html_parts.append(
            f"<th style='padding:6px 8px; text-align:center; border:1px solid #ccc; min-width:60px;'>{col}</th>"
        )
    html_parts.append("</tr>")

    # Data rows
    for country in pivot.index:
        html_parts.append("<tr>")
        html_parts.append(
            f"<td style='padding:6px 10px; font-weight:bold; border:1px solid #ccc; white-space:nowrap;'>{country}</td>"
        )
        for col in sorted_cols:
            val = pivot.loc[country, col] if col in pivot.columns else None
            evt_count = int(count_pivot.loc[country, col]) if col in count_pivot.columns else 0
            bg = score_to_color(val)
            tc = text_color(val)
            cell_text = f"{val:.1f}" if pd.notna(val) else "-"
            title_attr = f"title='{country} | {col} | Score: {cell_text} | Events: {evt_count}'"
            html_parts.append(
                f"<td style='padding:6px 8px; text-align:center; background:{bg}; color:{tc}; "
                f"border:1px solid #ccc; cursor:default;' {title_attr}>{cell_text}</td>"
            )
        html_parts.append("</tr>")

    html_parts.append("</table>")

    # Legend
    html_parts.append(
        "<div style='margin-top:10px; font-size:12px;'>"
        "<span style='display:inline-block; width:16px; height:16px; background:#e74c3c; border:1px solid #ccc; vertical-align:middle;'></span> 8+ (High) &nbsp;&nbsp;"
        "<span style='display:inline-block; width:16px; height:16px; background:#e67e22; border:1px solid #ccc; vertical-align:middle;'></span> 6-8 (Elevated) &nbsp;&nbsp;"
        "<span style='display:inline-block; width:16px; height:16px; background:#f1c40f; border:1px solid #ccc; vertical-align:middle;'></span> 4-6 (Medium) &nbsp;&nbsp;"
        "<span style='display:inline-block; width:16px; height:16px; background:#27ae60; border:1px solid #ccc; vertical-align:middle;'></span> 2-4 (Low) &nbsp;&nbsp;"
        "<span style='display:inline-block; width:16px; height:16px; background:#e0e0e0; border:1px solid #ccc; vertical-align:middle;'></span> No data"
        "</div>"
    )

    st.markdown("".join(html_parts), unsafe_allow_html=True)

    # Also show as an Altair heatmap for interactive exploration
    with st.expander("Interactive Altair heatmap"):
        heatmap_data = monthly_df.copy()
        heatmap_data['avg_score'] = heatmap_data['avg_score'].round(2)

        heat = alt.Chart(heatmap_data).mark_rect().encode(
            x=alt.X('month_label:O', title='Month', sort=sorted_cols),
            y=alt.Y('initiating_country:N', title='Country'),
            color=alt.Color(
                'avg_score:Q',
                title='Avg Score',
                scale=alt.Scale(scheme='redyellowgreen', domain=[0, 10], reverse=True),
            ),
            tooltip=[
                alt.Tooltip('initiating_country:N', title='Country'),
                alt.Tooltip('month_label:O', title='Month'),
                alt.Tooltip('avg_score:Q', title='Avg Score', format='.2f'),
                alt.Tooltip('event_count:Q', title='Events'),
            ]
        ).properties(height=max(200, len(selected_countries) * 40))

        st.altair_chart(heat, use_container_width=True)


st.markdown("---")

# ---------------------------------------------------------------------------
# 90-Day Activity Strip
# ---------------------------------------------------------------------------

st.header("90-Day Activity Strip")
st.markdown(
    "Each colored square represents one day. Brighter / larger squares indicate "
    "more daily event mentions. Hover for details."
)

daily_df = get_daily_activity(selected_countries, days_back=90)

if daily_df.empty:
    st.info("No daily event mention data found for the last 90 days.")
else:
    daily_df['mention_date'] = pd.to_datetime(daily_df['mention_date'])

    # Build a full date range per country so gaps show as empty squares
    date_min = daily_df['mention_date'].min()
    date_max = daily_df['mention_date'].max()
    full_dates = pd.date_range(start=date_min, end=date_max, freq='D')

    all_rows = []
    for country in selected_countries:
        country_data = daily_df[daily_df['initiating_country'] == country].set_index('mention_date')
        for d in full_dates:
            if d in country_data.index:
                row = country_data.loc[d]
                total = int(row['total_articles']) if not isinstance(row, pd.DataFrame) else int(row['total_articles'].sum())
                mentions = int(row['mention_count']) if not isinstance(row, pd.DataFrame) else int(row['mention_count'].sum())
            else:
                total = 0
                mentions = 0
            all_rows.append({
                'country': country,
                'date': d,
                'total_articles': total,
                'mention_count': mentions,
            })

    strip_df = pd.DataFrame(all_rows)
    strip_df['date_label'] = strip_df['date'].dt.strftime('%Y-%m-%d')
    strip_df['week'] = strip_df['date'].dt.isocalendar().week.astype(int)
    strip_df['day_of_week'] = strip_df['date'].dt.dayofweek  # 0=Mon

    # Build HTML activity strip per country (small colored squares)
    for country in selected_countries:
        cdf = strip_df[strip_df['country'] == country].sort_values('date')
        if cdf.empty:
            continue

        st.markdown(f"**{country}**")

        squares = []
        for _, row in cdf.iterrows():
            articles = row['total_articles']
            date_str = row['date_label']

            # Intensity color
            if articles == 0:
                bg = "#2d2d2d"
            elif articles < 5:
                bg = "#1a472a"
            elif articles < 15:
                bg = "#2d6a3f"
            elif articles < 30:
                bg = "#3d9956"
            elif articles < 60:
                bg = "#52c472"
            else:
                bg = "#73e895"

            squares.append(
                f"<span title='{date_str}: {articles} articles, {int(row['mention_count'])} events' "
                f"style='display:inline-block; width:10px; height:10px; margin:1px; "
                f"background:{bg}; border-radius:2px; cursor:default;'></span>"
            )

        strip_html = (
            "<div style='line-height:0; margin-bottom:12px;'>"
            + "".join(squares)
            + "</div>"
        )
        st.markdown(strip_html, unsafe_allow_html=True)

    # Legend for the strip
    strip_legend = (
        "<div style='font-size:12px; margin-top:4px;'>"
        "<span style='display:inline-block; width:10px; height:10px; background:#2d2d2d; border:1px solid #555; vertical-align:middle;'></span> 0 &nbsp;"
        "<span style='display:inline-block; width:10px; height:10px; background:#1a472a; border:1px solid #555; vertical-align:middle;'></span> 1-4 &nbsp;"
        "<span style='display:inline-block; width:10px; height:10px; background:#2d6a3f; border:1px solid #555; vertical-align:middle;'></span> 5-14 &nbsp;"
        "<span style='display:inline-block; width:10px; height:10px; background:#3d9956; border:1px solid #555; vertical-align:middle;'></span> 15-29 &nbsp;"
        "<span style='display:inline-block; width:10px; height:10px; background:#52c472; border:1px solid #555; vertical-align:middle;'></span> 30-59 &nbsp;"
        "<span style='display:inline-block; width:10px; height:10px; background:#73e895; border:1px solid #555; vertical-align:middle;'></span> 60+ articles"
        "</div>"
    )
    st.markdown(strip_legend, unsafe_allow_html=True)

    # Also provide an Altair chart version of the strip
    with st.expander("Interactive daily activity chart"):
        daily_chart = alt.Chart(strip_df).mark_rect().encode(
            x=alt.X('date:T', title='Date'),
            y=alt.Y('country:N', title='Country'),
            color=alt.Color(
                'total_articles:Q',
                title='Articles',
                scale=alt.Scale(scheme='greens'),
            ),
            tooltip=[
                alt.Tooltip('country:N', title='Country'),
                alt.Tooltip('date:T', title='Date', format='%Y-%m-%d'),
                alt.Tooltip('total_articles:Q', title='Articles'),
                alt.Tooltip('mention_count:Q', title='Events'),
            ]
        ).properties(height=max(150, len(selected_countries) * 35))

        st.altair_chart(daily_chart, use_container_width=True)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown(
    "**About:** The materiality matrix uses average `material_score` from "
    "`canonical_events` (master events only) grouped by month. The activity strip "
    "shows `daily_event_mentions` article counts over the last 90 days."
)
