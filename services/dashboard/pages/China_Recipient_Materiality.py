# pages/China_Recipient_Materiality.py
import pandas as pd
import datetime as dt
from sqlalchemy import text
import streamlit as st
import altair as alt
from shared.database.database import get_engine
import yaml

st.set_page_config(page_title="China Materiality by Recipient", page_icon="🇨🇳", layout="wide")
st.title("🇨🇳 China Materiality Analysis by Recipient Country")
st.caption("Analyzing the material impact of China's soft power activities across recipient countries")

# Load recipients from config
@st.cache_data(show_spinner=False)
def load_recipients():
    """Load recipient countries from config.yaml"""
    with open('shared/config/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    return config.get('recipients', [])

# -----------------------------
# Data Fetching Functions
# -----------------------------

@st.cache_data(ttl=300, show_spinner=True)
def fetch_china_recipient_metrics(start_date, end_date):
    """Fetch overall metrics for China's events by recipient country"""
    engine = get_engine()

    query = text("""
        WITH recipient_counts AS (
            SELECT
                ce.id as event_id,
                ce.canonical_name as event_name,
                ce.material_score,
                ce.total_articles,
                ce.total_mention_days,
                ce.first_mention_date,
                ce.last_mention_date,
                jsonb_object_keys(ce.primary_recipients) as recipient_country,
                (ce.primary_recipients->>jsonb_object_keys(ce.primary_recipients))::int as doc_count
            FROM canonical_events ce
            WHERE ce.initiating_country = 'China'
            AND ce.master_event_id IS NULL
            AND ce.material_score IS NOT NULL
            AND ce.first_mention_date >= :start_date
            AND ce.last_mention_date <= :end_date
            AND ce.primary_recipients IS NOT NULL
        )
        SELECT
            recipient_country,
            COUNT(DISTINCT event_id) as total_events,
            SUM(doc_count) as total_documents,
            AVG(material_score) as avg_material_score,
            MIN(material_score) as min_material_score,
            MAX(material_score) as max_material_score,
            SUM(CASE WHEN material_score >= 7.0 THEN 1 ELSE 0 END) as high_materiality_events,
            SUM(CASE WHEN material_score >= 4.0 AND material_score < 7.0 THEN 1 ELSE 0 END) as medium_materiality_events,
            SUM(CASE WHEN material_score < 4.0 THEN 1 ELSE 0 END) as low_materiality_events
        FROM recipient_counts
        GROUP BY recipient_country
        ORDER BY total_events DESC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={
            'start_date': start_date,
            'end_date': end_date
        })

    return df


@st.cache_data(ttl=300, show_spinner=True)
def fetch_top_events_by_recipient(recipient, start_date, end_date, limit=10):
    """Fetch top material events for a specific recipient"""
    engine = get_engine()

    query = text("""
        WITH recipient_events AS (
            SELECT
                ce.id,
                ce.canonical_name as event_name,
                ce.material_score,
                ce.material_justification,
                ce.total_articles,
                ce.total_mention_days,
                ce.first_mention_date,
                ce.last_mention_date,
                ce.consolidated_description,
                jsonb_object_keys(ce.primary_recipients) as recipient_country,
                (ce.primary_recipients->>jsonb_object_keys(ce.primary_recipients))::int as doc_count,
                ce.primary_categories
            FROM canonical_events ce
            WHERE ce.initiating_country = 'China'
            AND ce.master_event_id IS NULL
            AND ce.material_score IS NOT NULL
            AND ce.first_mention_date >= :start_date
            AND ce.last_mention_date <= :end_date
            AND ce.primary_recipients IS NOT NULL
        )
        SELECT
            event_name,
            material_score,
            material_justification,
            total_articles,
            total_mention_days,
            first_mention_date,
            last_mention_date,
            consolidated_description,
            doc_count,
            primary_categories
        FROM recipient_events
        WHERE recipient_country = :recipient
        ORDER BY material_score DESC, doc_count DESC
        LIMIT :limit
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={
            'recipient': recipient,
            'start_date': start_date,
            'end_date': end_date,
            'limit': limit
        })

    return df


@st.cache_data(ttl=300, show_spinner=True)
def fetch_materiality_timeline(recipients, start_date, end_date):
    """Fetch materiality score trends over time by recipient"""
    engine = get_engine()

    recipient_filter = ""
    params = {'start_date': start_date, 'end_date': end_date}

    if recipients:
        recipient_filter = """
        AND EXISTS (
            SELECT 1
            FROM jsonb_object_keys(ce.primary_recipients) as recipient
            WHERE recipient = ANY(:recipients)
        )
        """
        params['recipients'] = recipients

    query = text(f"""
        WITH monthly_data AS (
            SELECT
                ce.id,
                ce.canonical_name,
                ce.material_score,
                ce.total_articles,
                DATE_TRUNC('month', ce.first_mention_date) as month,
                jsonb_object_keys(ce.primary_recipients) as recipient_country,
                (ce.primary_recipients->>jsonb_object_keys(ce.primary_recipients))::int as doc_count
            FROM canonical_events ce
            WHERE ce.initiating_country = 'China'
            AND ce.master_event_id IS NULL
            AND ce.material_score IS NOT NULL
            AND ce.first_mention_date >= :start_date
            AND ce.last_mention_date <= :end_date
            {recipient_filter}
        )
        SELECT
            month,
            recipient_country,
            COUNT(*) as event_count,
            AVG(material_score) as avg_material_score,
            SUM(doc_count) as total_documents
        FROM monthly_data
        GROUP BY month, recipient_country
        ORDER BY month, recipient_country
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)

    return df


# -----------------------------
# Sidebar Filters
# -----------------------------
with st.sidebar:
    st.header("Filters")

    # Date range
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Start Date",
            value=dt.date(2024, 8, 1),
            max_value=dt.date.today()
        )
    with col2:
        end_date = st.date_input(
            "End Date",
            value=dt.date.today(),
            max_value=dt.date.today()
        )

    # Recipient filter for timeline
    all_recipients = load_recipients()
    selected_recipients = st.multiselect(
        "Focus Recipients (for timeline)",
        options=all_recipients,
        default=[]
    )

    st.markdown("---")
    st.markdown("### About this Analysis")
    st.markdown("""
    This page analyzes China's soft power activities through the lens of **materiality scores** -
    measuring how concrete and substantive events are rather than purely symbolic.

    **Materiality Scale:**
    - **7-10**: High (concrete projects, specific commitments)
    - **4-6**: Medium (mixed symbolic/material)
    - **1-3**: Low (symbolic gestures, statements)
    """)

# -----------------------------
# Main Dashboard
# -----------------------------

# Fetch data
with st.spinner("Loading China-recipient metrics..."):
    metrics_df = fetch_china_recipient_metrics(start_date, end_date)
    timeline_df = fetch_materiality_timeline(selected_recipients if selected_recipients else None, start_date, end_date)

# Summary metrics at top
st.header("📊 Overview")
col1, col2, col3, col4 = st.columns(4)

with col1:
    total_recipients = len(metrics_df)
    st.metric("Recipient Countries", f"{total_recipients}")

with col2:
    total_events = metrics_df['total_events'].sum()
    st.metric("Total Events", f"{total_events:,}")

with col3:
    total_docs = metrics_df['total_documents'].sum()
    st.metric("Total Documents", f"{total_docs:,}")

with col4:
    overall_avg = metrics_df['avg_material_score'].mean()
    st.metric("Avg Materiality Score", f"{overall_avg:.2f}")

st.markdown("---")

# Recipient Rankings Table
st.header("🏆 Recipient Country Rankings")
st.caption("Ranked by total number of events")

# Format the metrics dataframe for display
display_df = metrics_df.copy()
display_df['avg_material_score'] = display_df['avg_material_score'].round(2)
display_df['min_material_score'] = display_df['min_material_score'].round(2)
display_df['max_material_score'] = display_df['max_material_score'].round(2)

# Rename columns for display
display_df = display_df.rename(columns={
    'recipient_country': 'Recipient',
    'total_events': 'Total Events',
    'total_documents': 'Documents',
    'avg_material_score': 'Avg Score',
    'min_material_score': 'Min Score',
    'max_material_score': 'Max Score',
    'high_materiality_events': 'High (7-10)',
    'medium_materiality_events': 'Medium (4-6.9)',
    'low_materiality_events': 'Low (1-3.9)'
})

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Avg Score": st.column_config.NumberColumn(format="%.2f"),
        "Min Score": st.column_config.NumberColumn(format="%.2f"),
        "Max Score": st.column_config.NumberColumn(format="%.2f"),
    }
)

st.markdown("---")

# Materiality Distribution Chart
st.header("📈 Materiality Score Distribution by Recipient")

# Create stacked bar chart
chart_data = metrics_df[['recipient_country', 'high_materiality_events', 'medium_materiality_events', 'low_materiality_events']].copy()
chart_data = chart_data.melt(
    id_vars=['recipient_country'],
    var_name='Materiality Level',
    value_name='Event Count'
)

# Map to readable names
materiality_map = {
    'high_materiality_events': 'High (7-10)',
    'medium_materiality_events': 'Medium (4-6.9)',
    'low_materiality_events': 'Low (1-3.9)'
}
chart_data['Materiality Level'] = chart_data['Materiality Level'].map(materiality_map)

chart = alt.Chart(chart_data).mark_bar().encode(
    x=alt.X('recipient_country:N', title='Recipient Country', sort='-y'),
    y=alt.Y('Event Count:Q', title='Number of Events'),
    color=alt.Color(
        'Materiality Level:N',
        scale=alt.Scale(
            domain=['High (7-10)', 'Medium (4-6.9)', 'Low (1-3.9)'],
            range=['#2ecc71', '#f39c12', '#e74c3c']
        ),
        legend=alt.Legend(title='Materiality Level')
    ),
    tooltip=[
        'recipient_country:N',
        'Materiality Level:N',
        'Event Count:Q'
    ]
).properties(
    height=400
)

st.altair_chart(chart, use_container_width=True)

st.markdown("---")

# Timeline chart
if not timeline_df.empty:
    st.header("📅 Materiality Trends Over Time")

    timeline_chart = alt.Chart(timeline_df).mark_line(point=True).encode(
        x=alt.X('month:T', title='Month'),
        y=alt.Y('avg_material_score:Q', title='Average Materiality Score', scale=alt.Scale(domain=[0, 10])),
        color=alt.Color('recipient_country:N', title='Recipient Country'),
        tooltip=[
            alt.Tooltip('month:T', title='Month'),
            alt.Tooltip('recipient_country:N', title='Recipient'),
            alt.Tooltip('avg_material_score:Q', title='Avg Score', format='.2f'),
            alt.Tooltip('event_count:Q', title='Events'),
            alt.Tooltip('total_documents:Q', title='Documents')
        ]
    ).properties(
        height=400
    )

    st.altair_chart(timeline_chart, use_container_width=True)
else:
    st.info("Select recipient countries from the sidebar to see trends over time")

st.markdown("---")

# Detailed View by Recipient
st.header("🔍 Top Material Events by Recipient")
st.caption("Select a recipient country to view their highest materiality events")

# Recipient selector
selected_recipient = st.selectbox(
    "Select Recipient Country",
    options=sorted(metrics_df['recipient_country'].unique())
)

if selected_recipient:
    with st.spinner(f"Loading events for {selected_recipient}..."):
        events_df = fetch_top_events_by_recipient(selected_recipient, start_date, end_date, limit=20)

    if not events_df.empty:
        # Show summary for this recipient
        recipient_metrics = metrics_df[metrics_df['recipient_country'] == selected_recipient].iloc[0]

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Events", f"{int(recipient_metrics['total_events'])}")
        with col2:
            st.metric("Avg Materiality", f"{recipient_metrics['avg_material_score']:.2f}")
        with col3:
            st.metric("High Materiality", f"{int(recipient_metrics['high_materiality_events'])}")
        with col4:
            st.metric("Total Documents", f"{int(recipient_metrics['total_documents'])}")

        st.markdown("---")

        # Display events
        for idx, event in events_df.iterrows():
            with st.expander(
                f"**{event['event_name']}** — Score: {event['material_score']:.1f}/10",
                expanded=(idx < 3)  # Expand first 3
            ):
                col1, col2, col3 = st.columns([2, 1, 1])

                with col1:
                    st.markdown(f"**Materiality Score:** {event['material_score']:.1f}/10")
                    st.markdown(f"**Justification:** {event['material_justification']}")

                with col2:
                    st.markdown(f"**Documents:** {event['doc_count']}")
                    st.markdown(f"**Articles:** {event['total_articles']}")

                with col3:
                    st.markdown(f"**Duration:** {event['total_mention_days']} days")
                    st.markdown(f"**First:** {event['first_mention_date'].strftime('%Y-%m-%d')}")
                    st.markdown(f"**Last:** {event['last_mention_date'].strftime('%Y-%m-%d')}")

                if event['consolidated_description']:
                    st.markdown("**Description:**")
                    st.markdown(event['consolidated_description'][:500] + ("..." if len(event['consolidated_description']) > 500 else ""))

                # Show categories if available
                if event['primary_categories']:
                    categories = list(event['primary_categories'].keys())[:5]
                    st.markdown(f"**Categories:** {', '.join(categories)}")
    else:
        st.info(f"No events found for {selected_recipient} in the selected date range")
