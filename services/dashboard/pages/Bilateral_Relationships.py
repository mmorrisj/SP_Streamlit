"""
Bilateral Relationship Summaries Dashboard

Explore comprehensive AI-generated summaries of soft power relationships between
country pairs, aggregating all interactions, events, and trends over time.
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from typing import Optional, List, Dict
from queries.bilateral_queries import (
    get_all_bilateral_summaries,
    get_bilateral_summary,
    get_top_relationships_by_documents,
    get_top_relationships_by_material_score,
    search_bilateral_summaries
)


# Page configuration
st.set_page_config(
    page_title="Bilateral Relationships",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 Bilateral Relationship Summaries")
st.markdown("""
Explore comprehensive analyses of soft power relationships between country pairs.
Each summary aggregates all documents, events, and interactions to provide strategic insights.
""")

# Sidebar filters
st.sidebar.header("Filters")

# View mode selection
view_mode = st.sidebar.radio(
    "View Mode",
    ["Overview", "Specific Relationship", "Search", "Compare"]
)

if view_mode == "Overview":
    st.header("📊 Bilateral Relationships Overview")

    # Load all summaries
    summaries = get_all_bilateral_summaries()

    if summaries:
        st.metric("Total Bilateral Summaries", len(summaries))

        # Create summary dataframe
        summary_data = []
        for s in summaries:
            summary_data.append({
                'Initiating Country': s['initiating_country'],
                'Recipient Country': s['recipient_country'],
                'Documents': s['total_documents'],
                'Material Score': s['material_score'] or 0,
                'Time Span (Days)': (s['last_interaction_date'] - s['first_interaction_date']).days,
                'Last Updated': s['updated_at'] or s['created_at']
            })

        df = pd.DataFrame(summary_data)

        # Tabs for different views
        tab1, tab2, tab3, tab4 = st.tabs([
            "📋 All Relationships",
            "🏆 Top by Volume",
            "⭐ Top by Material Score",
            "📈 Visualizations"
        ])

        with tab1:
            st.subheader("All Bilateral Relationships")

            # Sort options
            sort_by = st.selectbox(
                "Sort by",
                ["Documents", "Material Score", "Initiating Country", "Last Updated"],
                key="overview_sort"
            )

            ascending = st.checkbox("Ascending", value=False, key="overview_asc")

            sorted_df = df.sort_values(by=sort_by, ascending=ascending)

            # Display table with clickable rows
            st.dataframe(
                sorted_df,
                use_container_width=True,
                hide_index=True
            )

            # Download option
            csv = sorted_df.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv,
                file_name=f"bilateral_relationships_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

        with tab2:
            st.subheader("🏆 Top Relationships by Document Volume")

            top_n = st.slider("Show top N relationships", 5, 30, 15, key="top_volume")

            top_by_docs = df.nlargest(top_n, 'Documents')

            # Bar chart
            chart = alt.Chart(top_by_docs).mark_bar().encode(
                x=alt.X('Documents:Q', title='Number of Documents'),
                y=alt.Y('Initiating Country:N',
                       sort=alt.EncodingSortField(field='Documents', order='descending'),
                       title='Initiating Country'),
                color=alt.Color('Recipient Country:N', legend=alt.Legend(title="Recipient")),
                tooltip=[
                    'Initiating Country',
                    'Recipient Country',
                    'Documents',
                    'Material Score'
                ]
            ).properties(
                height=400,
                title=f'Top {top_n} Bilateral Relationships by Document Volume'
            )

            st.altair_chart(chart, use_container_width=True)

            # Table
            st.dataframe(
                top_by_docs[['Initiating Country', 'Recipient Country', 'Documents', 'Material Score']],
                use_container_width=True,
                hide_index=True
            )

        with tab3:
            st.subheader("⭐ Top Relationships by Material Score")

            top_n_mat = st.slider("Show top N relationships", 5, 30, 15, key="top_material")

            top_by_score = df.nlargest(top_n_mat, 'Material Score')

            # Bar chart
            chart_mat = alt.Chart(top_by_score).mark_bar().encode(
                x=alt.X('Material Score:Q', scale=alt.Scale(domain=[0, 1]), title='Material Score'),
                y=alt.Y('Initiating Country:N',
                       sort=alt.EncodingSortField(field='Material Score', order='descending'),
                       title='Initiating Country'),
                color=alt.Color('Recipient Country:N', legend=alt.Legend(title="Recipient")),
                tooltip=[
                    'Initiating Country',
                    'Recipient Country',
                    'Material Score',
                    'Documents'
                ]
            ).properties(
                height=400,
                title=f'Top {top_n_mat} Bilateral Relationships by Material Score'
            )

            st.altair_chart(chart_mat, use_container_width=True)

            # Table
            st.dataframe(
                top_by_score[['Initiating Country', 'Recipient Country', 'Material Score', 'Documents']],
                use_container_width=True,
                hide_index=True
            )

        with tab4:
            st.subheader("📈 Relationship Visualizations")

            # Scatter plot: Documents vs Material Score
            st.markdown("#### Documents vs Material Score")

            scatter = alt.Chart(df).mark_circle(size=100).encode(
                x=alt.X('Documents:Q', scale=alt.Scale(type='log'), title='Number of Documents (log scale)'),
                y=alt.Y('Material Score:Q', scale=alt.Scale(domain=[0, 1]), title='Material Score'),
                color=alt.Color('Initiating Country:N', legend=alt.Legend(title="Initiating")),
                size=alt.Size('Time Span (Days):Q', legend=alt.Legend(title="Time Span (Days)")),
                tooltip=[
                    'Initiating Country',
                    'Recipient Country',
                    'Documents',
                    'Material Score',
                    'Time Span (Days)'
                ]
            ).properties(
                height=400,
                title='Bilateral Relationships: Volume vs Materiality'
            ).interactive()

            st.altair_chart(scatter, use_container_width=True)

            st.markdown("*Larger circles indicate longer time spans of interaction*")

    else:
        st.info("No bilateral summaries found. Generate some using the pipeline scripts.")

elif view_mode == "Specific Relationship":
    st.header("🔍 Explore Specific Relationship")

    # Get available relationships
    summaries = get_all_bilateral_summaries()

    if summaries:
        # Create selection lists
        initiators = sorted(list(set(s['initiating_country'] for s in summaries)))

        col1, col2 = st.columns(2)

        with col1:
            selected_initiator = st.selectbox(
                "Initiating Country",
                initiators,
                key="init_select"
            )

        # Filter recipients based on initiator
        recipients = sorted([
            s['recipient_country']
            for s in summaries
            if s['initiating_country'] == selected_initiator
        ])

        with col2:
            selected_recipient = st.selectbox(
                "Recipient Country",
                recipients,
                key="recip_select"
            )

        if st.button("Load Relationship Summary", type="primary"):
            summary = get_bilateral_summary(selected_initiator, selected_recipient)

            if summary:
                st.success(f"Loaded: {selected_initiator} → {selected_recipient}")

                # Display full summary
                display_bilateral_summary(summary)
            else:
                st.error("Summary not found")
    else:
        st.info("No bilateral summaries available. Generate summaries using the pipeline.")

elif view_mode == "Search":
    st.header("🔎 Search Bilateral Relationships")

    search_query = st.text_input(
        "Search in summaries (overview, themes, initiatives)",
        placeholder="e.g., Belt and Road, cultural exchange, infrastructure"
    )

    if search_query:
        results = search_bilateral_summaries(search_query)

        if results:
            st.success(f"Found {len(results)} matching relationships")

            for result in results:
                with st.expander(f"{result['initiating_country']} → {result['recipient_country']} ({result['total_documents']:,} docs)"):
                    display_bilateral_summary(result, compact=True)
        else:
            st.info("No results found")

elif view_mode == "Compare":
    st.header("⚖️ Compare Bilateral Relationships")

    summaries = get_all_bilateral_summaries()

    if summaries and len(summaries) >= 2:
        st.markdown("Select two relationships to compare side-by-side")

        col1, col2 = st.columns(2)

        # Create options for selection
        options = [f"{s['initiating_country']} → {s['recipient_country']}" for s in summaries]

        with col1:
            st.subheader("Relationship A")
            selection_a = st.selectbox("Select first relationship", options, key="compare_a")
            init_a, recip_a = selection_a.split(" → ")
            summary_a = get_bilateral_summary(init_a, recip_a)

        with col2:
            st.subheader("Relationship B")
            selection_b = st.selectbox("Select second relationship", options, key="compare_b")
            init_b, recip_b = selection_b.split(" → ")
            summary_b = get_bilateral_summary(init_b, recip_b)

        if summary_a and summary_b:
            st.markdown("---")

            # Comparison metrics
            st.subheader("📊 Comparative Metrics")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric(
                    "Documents",
                    f"{summary_a['total_documents']:,}",
                    delta=f"{summary_a['total_documents'] - summary_b['total_documents']:,}"
                )

            with col2:
                st.metric(
                    "Material Score",
                    f"{summary_a['material_score']:.2f}",
                    delta=f"{summary_a['material_score'] - summary_b['material_score']:.2f}"
                )

            with col3:
                time_span_a = (summary_a['last_interaction_date'] - summary_a['first_interaction_date']).days
                time_span_b = (summary_b['last_interaction_date'] - summary_b['first_interaction_date']).days
                st.metric(
                    "Time Span (Days)",
                    time_span_a,
                    delta=time_span_a - time_span_b
                )

            with col4:
                events_a = summary_a['total_daily_events'] + summary_a['total_weekly_events'] + summary_a['total_monthly_events']
                events_b = summary_b['total_daily_events'] + summary_b['total_weekly_events'] + summary_b['total_monthly_events']
                st.metric(
                    "Total Events",
                    events_a,
                    delta=events_a - events_b
                )

            # Side-by-side detailed comparison
            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                st.subheader(f"🌍 {summary_a['initiating_country']} → {summary_a['recipient_country']}")
                display_bilateral_summary(summary_a, compact=False)

            with col2:
                st.subheader(f"🌍 {summary_b['initiating_country']} → {summary_b['recipient_country']}")
                display_bilateral_summary(summary_b, compact=False)
    else:
        st.info("Need at least 2 bilateral summaries to compare")


def display_bilateral_summary(summary: dict, compact: bool = False):
    """Display a bilateral relationship summary."""

    # Basic metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Documents", f"{summary['total_documents']:,}")

    with col2:
        st.metric("Material Score", f"{summary['material_score']:.2f}/1.0")

    with col3:
        time_span = (summary['last_interaction_date'] - summary['first_interaction_date']).days
        st.metric("Time Span", f"{time_span} days")

    with col4:
        total_events = (
            summary['total_daily_events'] +
            summary['total_weekly_events'] +
            summary['total_monthly_events']
        )
        st.metric("Total Events", total_events)

    st.caption(f"📅 {summary['first_interaction_date']} to {summary['last_interaction_date']}")

    # Relationship summary content
    rel_summary = summary['relationship_summary']

    # Overview
    if not compact:
        st.markdown("### 📝 Overview")
        st.markdown(rel_summary.get('overview', 'N/A'))

    # Key themes
    st.markdown("### 🎯 Key Themes")
    for theme in rel_summary.get('key_themes', []):
        st.markdown(f"- {theme}")

    # Top categories
    st.markdown("### 📁 Top Categories")
    categories = sorted(
        summary['count_by_category'].items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]

    for cat, count in categories:
        pct = (count / summary['total_documents']) * 100
        st.markdown(f"- **{cat}**: {count:,} documents ({pct:.1f}%)")

    if not compact:
        # Major initiatives
        st.markdown("### 🚀 Major Initiatives")
        for i, initiative in enumerate(rel_summary.get('major_initiatives', []), 1):
            with st.expander(f"{i}. {initiative.get('name', 'Unnamed Initiative')}"):
                st.markdown(f"**Description:** {initiative.get('description', 'N/A')}")
                st.markdown(f"**Timeframe:** {initiative.get('timeframe', 'N/A')}")
                if initiative.get('categories'):
                    st.markdown(f"**Categories:** {', '.join(initiative['categories'])}")

        # Trend analysis
        st.markdown("### 📊 Trend Analysis")
        st.markdown(rel_summary.get('trend_analysis', 'N/A'))

        # Current status
        st.markdown("### 🎯 Current Status")
        st.markdown(rel_summary.get('current_status', 'N/A'))

        # Notable developments
        st.markdown("### ⭐ Notable Developments")
        for dev in rel_summary.get('notable_developments', []):
            st.markdown(f"- {dev}")

        # Material assessment
        st.markdown("### 💎 Material Assessment")
        mat = rel_summary.get('material_assessment', {})
        st.markdown(f"**Score:** {mat.get('score', 'N/A')}/1.0")
        st.markdown(f"**Justification:** {mat.get('justification', 'N/A')}")

        # Temporal activity chart
        if summary['activity_by_month']:
            st.markdown("### 📈 Activity Over Time")

            activity_df = pd.DataFrame([
                {'Month': month, 'Documents': count}
                for month, count in sorted(summary['activity_by_month'].items())
            ])

            chart = alt.Chart(activity_df).mark_line(point=True).encode(
                x=alt.X('Month:T', title='Month'),
                y=alt.Y('Documents:Q', title='Number of Documents'),
                tooltip=['Month', 'Documents']
            ).properties(
                height=300,
                title='Monthly Document Activity'
            )

            st.altair_chart(chart, use_container_width=True)


# Footer
st.markdown("---")
st.caption("💡 Tip: Use the sidebar to switch between different views and explore bilateral relationships comprehensively.")
