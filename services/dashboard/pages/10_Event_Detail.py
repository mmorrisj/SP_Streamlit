"""
Event Detail Page

Deep-dive into individual master events: metrics, narratives, daily timelines,
child events, and cross-period summaries.
"""

import sys
import os
import datetime

import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_engine
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Event Detail", page_icon="📋", layout="wide")

st.title("Event Detail Explorer")
st.caption("Deep-dive into individual master events with metrics, timelines, and cross-period summaries")


# ---------------------------------------------------------------------------
# Cached query functions
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_master_events_for_country(country):
    """Fetch top 50 master events (canonical_events WHERE master_event_id IS NULL)
    for a given initiating country, ordered by total_articles desc."""
    engine = get_engine()
    query = text("""
        SELECT
            id,
            canonical_name,
            initiating_country,
            total_articles,
            total_mention_days,
            CAST(material_score AS FLOAT) AS material_score,
            first_mention_date,
            last_mention_date
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND initiating_country = :country
        ORDER BY total_articles DESC
        LIMIT 50
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"country": country})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_event_details(event_id):
    """Get full detail row for a single canonical event."""
    engine = get_engine()
    query = text("""
        SELECT
            id,
            canonical_name,
            initiating_country,
            total_articles,
            total_mention_days,
            CAST(material_score AS FLOAT) AS material_score,
            material_justification,
            story_phase,
            peak_daily_article_count,
            peak_mention_date,
            consolidated_description,
            first_mention_date,
            last_mention_date,
            primary_categories,
            primary_recipients,
            alternative_names,
            unique_sources,
            source_count
        FROM canonical_events
        WHERE id = :event_id
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"event_id": event_id})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_daily_mentions(event_id):
    """Get daily mention timeline for a canonical event."""
    engine = get_engine()
    query = text("""
        SELECT
            mention_date,
            article_count,
            consolidated_headline,
            daily_summary,
            mention_context,
            news_intensity
        FROM daily_event_mentions
        WHERE canonical_event_id = :event_id
        ORDER BY mention_date
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"event_id": event_id})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_child_events(master_event_id):
    """Get child events for a master event."""
    engine = get_engine()
    query = text("""
        SELECT
            id,
            canonical_name,
            initiating_country,
            total_articles,
            total_mention_days,
            CAST(material_score AS FLOAT) AS material_score,
            story_phase,
            first_mention_date,
            last_mention_date
        FROM canonical_events
        WHERE master_event_id = :master_id
        ORDER BY total_articles DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"master_id": master_event_id})
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_cross_period_summaries(event_name, country):
    """Query event_summaries for matching event_name across all period_types."""
    engine = get_engine()
    query = text("""
        SELECT
            period_type,
            period_start,
            period_end,
            event_name,
            initiating_country,
            CAST(material_score AS FLOAT) AS material_score,
            narrative_summary,
            overall_summary,
            category_count,
            source_count,
            total_documents_across_categories
        FROM event_summaries
        WHERE event_name = :event_name
          AND initiating_country = :country
          AND is_deleted = false
        ORDER BY
            CASE period_type
                WHEN 'DAILY' THEN 1
                WHEN 'WEEKLY' THEN 2
                WHEN 'MONTHLY' THEN 3
                WHEN 'YEARLY' THEN 4
            END,
            period_start
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={
            "event_name": event_name,
            "country": country,
        })
    return df


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("Event Selection")

selected_country = st.sidebar.selectbox(
    "Initiating Country",
    options=cfg.influencers,
    index=0,
    help="Filter master events by initiating country",
)

master_events_df = get_master_events_for_country(selected_country)

if master_events_df.empty:
    st.warning(f"No master events found for {selected_country}.")
    st.stop()

# Build event labels for the selectbox
event_labels = []
event_id_map = {}
for _, row in master_events_df.iterrows():
    label = f"{row['canonical_name']}  ({int(row['total_articles'])} articles)"
    event_labels.append(label)
    event_id_map[label] = str(row['id'])

# Search / selector
search_text = st.sidebar.text_input("Search events", "", help="Type to filter the event list")
filtered_labels = [lbl for lbl in event_labels if search_text.lower() in lbl.lower()] if search_text else event_labels

if not filtered_labels:
    st.sidebar.warning("No events match your search.")
    st.stop()

selected_label = st.sidebar.selectbox("Select Event", options=filtered_labels, index=0)
selected_event_id = event_id_map[selected_label]

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Country:** {selected_country}")
st.sidebar.markdown(f"**Events loaded:** {len(master_events_df)}")


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

detail_df = get_event_details(selected_event_id)

if detail_df.empty:
    st.error("Could not load event details.")
    st.stop()

event = detail_df.iloc[0]

st.header(event['canonical_name'])

# -- Metrics grid --
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total Articles", f"{int(event['total_articles']):,}")
with col2:
    st.metric("Mention Days", int(event['total_mention_days']))
with col3:
    score = event['material_score']
    st.metric("Material Score", f"{score:.1f}" if score is not None else "N/A")
with col4:
    st.metric("Story Phase", str(event['story_phase'] or "N/A").capitalize())
with col5:
    st.metric("Peak Daily Articles", int(event['peak_daily_article_count']))

st.markdown("---")

# -- Narrative sections --
with st.expander("Consolidated Description", expanded=True):
    desc = event['consolidated_description']
    if desc:
        st.markdown(desc)
    else:
        st.info("No consolidated description available for this event.")

with st.expander("Material Justification", expanded=False):
    justification = event['material_justification']
    if justification:
        st.markdown(justification)
    else:
        st.info("No material justification available for this event.")

# -- Categories and Recipients --
col_left, col_right = st.columns(2)
with col_left:
    with st.expander("Primary Categories", expanded=False):
        cats = event['primary_categories']
        if cats and isinstance(cats, dict):
            for cat, count in sorted(cats.items(), key=lambda x: x[1], reverse=True):
                st.markdown(f"- **{cat}**: {count} documents")
        else:
            st.info("No category data available.")

with col_right:
    with st.expander("Primary Recipients", expanded=False):
        recs = event['primary_recipients']
        if recs and isinstance(recs, dict):
            # Filter to config recipients
            config_recs = {k: v for k, v in recs.items() if k in cfg.recipients}
            other_recs = {k: v for k, v in recs.items() if k not in cfg.recipients}
            for rec, count in sorted(config_recs.items(), key=lambda x: x[1], reverse=True):
                st.markdown(f"- **{rec}**: {count} documents")
            if other_recs:
                st.caption(f"+ {len(other_recs)} other recipient(s) not in config")
        else:
            st.info("No recipient data available.")

st.markdown("---")

# -- Daily mention timeline --
st.subheader("Daily Mention Timeline")

mentions_df = get_daily_mentions(selected_event_id)

if not mentions_df.empty:
    mentions_df['mention_date'] = pd.to_datetime(mentions_df['mention_date'])

    timeline_chart = alt.Chart(mentions_df).mark_bar(
        color='#4F8BF9',
        cornerRadiusTopLeft=3,
        cornerRadiusTopRight=3,
    ).encode(
        x=alt.X('mention_date:T', title='Date', axis=alt.Axis(format='%Y-%m-%d', labelAngle=-45)),
        y=alt.Y('article_count:Q', title='Article Count'),
        tooltip=[
            alt.Tooltip('mention_date:T', title='Date', format='%Y-%m-%d'),
            alt.Tooltip('article_count:Q', title='Articles'),
            alt.Tooltip('consolidated_headline:N', title='Headline'),
            alt.Tooltip('mention_context:N', title='Context'),
            alt.Tooltip('news_intensity:N', title='Intensity'),
        ]
    ).properties(
        height=350,
        title='Daily Article Counts'
    )

    st.altair_chart(timeline_chart, use_container_width=True)

    # Daily details table
    with st.expander("View Daily Details"):
        display_mentions = mentions_df.copy()
        display_mentions['mention_date'] = display_mentions['mention_date'].dt.strftime('%Y-%m-%d')
        display_mentions = display_mentions.rename(columns={
            'mention_date': 'Date',
            'article_count': 'Articles',
            'consolidated_headline': 'Headline',
            'daily_summary': 'Summary',
            'mention_context': 'Context',
            'news_intensity': 'Intensity',
        })
        st.dataframe(display_mentions[['Date', 'Articles', 'Headline', 'Context', 'Intensity']],
                      use_container_width=True, hide_index=True)
else:
    st.info("No daily mention data available for this event.")

st.markdown("---")

# -- Child events --
st.subheader("Child Events")

children_df = get_child_events(selected_event_id)

if not children_df.empty:
    st.markdown(f"**{len(children_df)} child event(s)** consolidated under this master event.")

    for idx, child in children_df.iterrows():
        with st.expander(f"{child['canonical_name']} -- {int(child['total_articles'])} articles"):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Articles", int(child['total_articles']))
            with c2:
                st.metric("Mention Days", int(child['total_mention_days']))
            with c3:
                child_score = child['material_score']
                st.metric("Material Score", f"{child_score:.1f}" if child_score is not None else "N/A")
            with c4:
                st.metric("Phase", str(child['story_phase'] or "N/A").capitalize())
            st.caption(f"Active: {child['first_mention_date']} to {child['last_mention_date']}")
else:
    st.info("This master event has no child events (standalone event).")

st.markdown("---")

# -- Cross-period summaries --
st.subheader("Cross-Period Summaries")
st.caption("Event summaries from the event_summaries table across DAILY / WEEKLY / MONTHLY / YEARLY period types")

cross_df = get_cross_period_summaries(event['canonical_name'], event['initiating_country'])

if not cross_df.empty:
    period_types_found = cross_df['period_type'].unique().tolist()
    st.markdown(f"Found summaries in **{len(period_types_found)}** period type(s): {', '.join(period_types_found)}")

    for pt in ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY']:
        subset = cross_df[cross_df['period_type'] == pt]
        if subset.empty:
            continue

        with st.expander(f"{pt} Summaries ({len(subset)} record(s))", expanded=(pt == 'MONTHLY')):
            for _, row in subset.iterrows():
                st.markdown(f"**Period:** {row['period_start']} to {row['period_end']}")
                cs_score = row['material_score']
                cs_cats = row['category_count']
                cs_sources = row['source_count']
                cs_docs = row['total_documents_across_categories']
                st.markdown(
                    f"Material Score: **{cs_score:.1f}**  |  "
                    f"Categories: **{cs_cats}**  |  "
                    f"Sources: **{cs_sources}**  |  "
                    f"Documents: **{cs_docs}**"
                    if cs_score is not None
                    else f"Categories: **{cs_cats}**  |  Sources: **{cs_sources}**  |  Documents: **{cs_docs}**"
                )
                summary_text = row.get('overall_summary') or ""
                narrative = row.get('narrative_summary')
                if summary_text:
                    st.markdown(summary_text)
                elif narrative and isinstance(narrative, dict):
                    st.json(narrative)
                else:
                    st.caption("No narrative available for this period.")
                st.markdown("---")
else:
    st.info("No cross-period summaries found for this event name in event_summaries.")

# -- Footer --
st.markdown("---")
st.markdown(
    "**About:** This page displays detail for master canonical events "
    "(canonical_events where master_event_id IS NULL). Child events are those "
    "consolidated under a master event via embedding similarity."
)
