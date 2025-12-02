"""
Bilateral Category Analysis Dashboard

Explore category-specific soft power interactions between country pairs
(e.g., China → Egypt Economic relationship).
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from typing import Optional, List, Dict
from queries.category_queries import (
    get_all_bilateral_category_summaries,
    get_bilateral_category_summary,
    get_bilateral_categories,
    get_top_bilateral_categories_by_documents,
    get_bilateral_category_statistics
)


# Page configuration
st.set_page_config(
    page_title="Bilateral Category Analysis",
    page_icon="🔗",
    layout="wide"
)

st.title("🔗 Bilateral Category Analysis")
st.markdown("""
Deep dive into category-specific soft power interactions between country pairs.
Analyze how different categories of soft power shape bilateral relationships.
""")

# Load statistics
stats = get_bilateral_category_statistics()

# Top-level metrics
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Summaries", stats['total_summaries'])

with col2:
    st.metric("Country Pairs", f"{stats['unique_initiators']} × {stats['unique_recipients']}")

with col3:
    st.metric("Categories", stats['unique_categories'])

with col4:
    st.metric("Avg Material Score", f"{stats['avg_material_score']:.2f}")

st.markdown("---")

# Sidebar filters
st.sidebar.header("Filters")

# View mode selection
view_mode = st.sidebar.radio(
    "View Mode",
    ["Overview", "Specific Relationship", "By Category", "Compare"]
)

if view_mode == "Overview":
    st.header("📊 Bilateral Category Overview")

    summaries = get_all_bilateral_category_summaries()

    if summaries:
        # Create summary dataframe
        summary_data = []
        for s in summaries:
            summary_data.append({
                'Initiating': s['initiating_country'],
                'Recipient': s['recipient_country'],
                'Category': s['category'],
                'Documents': s['total_documents'],
                'Events': s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events'],
                'Material Score': s['material_score_avg'] or 0,
                'Subcategories': len(s['count_by_subcategory'])
            })

        df = pd.DataFrame(summary_data)

        # Tabs
        tab1, tab2, tab3 = st.tabs([
            "📋 All Summaries",
            "🏆 Top Relationships",
            "📈 Visualizations"
        ])

        with tab1:
            st.subheader("All Bilateral Category Summaries")

            # Sort options
            sort_by = st.selectbox(
                "Sort by",
                ["Documents", "Material Score", "Events", "Initiating"],
                key="overview_sort"
            )

            ascending = st.checkbox("Ascending", value=False, key="overview_asc")

            sorted_df = df.sort_values(by=sort_by, ascending=ascending)

            # Display table
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
                file_name=f"bilateral_category_summaries_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

            # Show AI summaries section
            st.markdown("---")
            st.subheader("📝 View AI-Generated Summaries")
            st.markdown("Select any bilateral-category combination to view the detailed AI analysis:")

            # Create a selection for viewing summaries
            summary_options = [
                f"{s['initiating_country']} → {s['recipient_country']} - {s['category']}"
                for s in summaries
            ]
            selected_summary_label = st.selectbox(
                "Select a summary to view:",
                summary_options,
                key="overview_summary_select"
            )

            if selected_summary_label:
                # Parse the selection (format: "Country1 → Country2 - Category")
                parts = selected_summary_label.split(' - ')
                category = parts[1]
                countries = parts[0].split(' → ')
                init_country = countries[0]
                recip_country = countries[1]

                selected_summary = next(
                    (s for s in summaries
                     if s['initiating_country'] == init_country
                     and s['recipient_country'] == recip_country
                     and s['category'] == category),
                    None
                )

                if selected_summary:
                    st.markdown(f"### {init_country} → {recip_country} - {category}")
                    display_bilateral_category_summary(selected_summary)

        with tab2:
            st.subheader("🏆 Top Bilateral Category Relationships")

            top_n = st.slider("Show top N", 5, 30, 15, key="top_volume")

            top_by_docs = df.nlargest(top_n, 'Documents')

            # Create combined label
            top_by_docs['Label'] = top_by_docs['Initiating'] + ' → ' + top_by_docs['Recipient'] + ' (' + top_by_docs['Category'] + ')'

            # Bar chart
            chart = alt.Chart(top_by_docs).mark_bar().encode(
                x=alt.X('Documents:Q', title='Number of Documents'),
                y=alt.Y('Label:N',
                       sort=alt.EncodingSortField(field='Documents', order='descending'),
                       title='Relationship - Category'),
                color=alt.Color('Category:N', legend=alt.Legend(title="Category")),
                tooltip=[
                    'Initiating',
                    'Recipient',
                    'Category',
                    'Documents',
                    'Events',
                    'Material Score'
                ]
            ).properties(
                height=500,
                title=f'Top {top_n} Bilateral Category Relationships'
            )

            st.altair_chart(chart, use_container_width=True)

            # Table
            st.dataframe(
                top_by_docs[['Initiating', 'Recipient', 'Category', 'Documents', 'Events', 'Material Score']],
                use_container_width=True,
                hide_index=True
            )

        with tab3:
            st.subheader("📈 Distribution Visualizations")

            # Category distribution
            st.markdown("#### Documents by Category")

            category_totals = df.groupby('Category')['Documents'].sum().reset_index()

            pie_chart = alt.Chart(category_totals).mark_arc().encode(
                theta=alt.Theta('Documents:Q'),
                color=alt.Color('Category:N', legend=alt.Legend(title="Category")),
                tooltip=['Category', 'Documents']
            ).properties(
                height=350,
                title='Total Documents by Category'
            )

            st.altair_chart(pie_chart, use_container_width=True)

            # Material Score distribution
            st.markdown("#### Material Score Distribution")

            scatter = alt.Chart(df).mark_circle(size=100).encode(
                x=alt.X('Documents:Q',
                       scale=alt.Scale(type='log'),
                       title='Documents (log scale)'),
                y=alt.Y('Material Score:Q', title='Material Score'),
                color=alt.Color('Category:N', legend=alt.Legend(title="Category")),
                size=alt.Size('Events:Q', legend=alt.Legend(title="Events")),
                tooltip=[
                    'Initiating',
                    'Recipient',
                    'Category',
                    'Documents',
                    'Events',
                    'Material Score'
                ]
            ).properties(
                height=400,
                title='Bilateral Category Relationships: Volume vs Materiality'
            ).interactive()

            st.altair_chart(scatter, use_container_width=True)

    else:
        st.info("No bilateral category summaries found. Generate some using the pipeline scripts.")

elif view_mode == "Specific Relationship":
    st.header("🔍 Explore Specific Bilateral Relationship")

    summaries = get_all_bilateral_category_summaries()

    if summaries:
        # Get unique pairs
        pairs = list(set((s['initiating_country'], s['recipient_country']) for s in summaries))
        pair_options = [f"{init} → {recip}" for init, recip in sorted(pairs)]

        selected_pair = st.selectbox(
            "Select Country Pair",
            pair_options,
            key="pair_select"
        )

        if selected_pair:
            init, recip = selected_pair.split(" → ")

            # Get all categories for this pair
            pair_summaries = get_bilateral_categories(init, recip)

            if pair_summaries:
                st.success(f"Loaded {len(pair_summaries)} category summaries for {init} → {recip}")

                # Overview metrics
                col1, col2, col3, col4 = st.columns(4)

                total_docs = sum(s['total_documents'] for s in pair_summaries)
                total_events = sum(
                    s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events']
                    for s in pair_summaries
                )
                avg_material = sum(s['material_score_avg'] or 0 for s in pair_summaries) / len(pair_summaries)

                with col1:
                    st.metric("Total Documents", f"{total_docs:,}")

                with col2:
                    st.metric("Total Events", f"{total_events:,}")

                with col3:
                    st.metric("Categories", len(pair_summaries))

                with col4:
                    st.metric("Avg Material Score", f"{avg_material:.2f}")

                # Category breakdown
                st.markdown("### 📊 Category Breakdown")

                category_data = []
                for s in pair_summaries:
                    category_data.append({
                        'Category': s['category'],
                        'Documents': s['total_documents'],
                        'Events': s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events'],
                        'Material Score': s['material_score_avg'] or 0,
                        'Subcategories': len(s['count_by_subcategory'])
                    })

                cat_df = pd.DataFrame(category_data)

                # Stacked bar chart
                col1, col2 = st.columns(2)

                with col1:
                    doc_chart = alt.Chart(cat_df).mark_bar().encode(
                        x=alt.X('Category:N', title='Category'),
                        y=alt.Y('Documents:Q', title='Documents'),
                        color=alt.Color('Category:N', legend=None),
                        tooltip=['Category', 'Documents', 'Events']
                    ).properties(
                        height=300,
                        title='Documents by Category'
                    )
                    st.altair_chart(doc_chart, use_container_width=True)

                with col2:
                    mat_chart = alt.Chart(cat_df).mark_bar().encode(
                        x=alt.X('Category:N', title='Category'),
                        y=alt.Y('Material Score:Q', title='Material Score'),
                        color=alt.Color('Category:N', legend=None),
                        tooltip=['Category', 'Material Score']
                    ).properties(
                        height=300,
                        title='Material Score by Category'
                    )
                    st.altair_chart(mat_chart, use_container_width=True)

                # Detailed summaries
                st.markdown("### 📋 Detailed Category Summaries")

                for summary in pair_summaries:
                    with st.expander(f"{summary['category']} - {summary['total_documents']:,} docs"):
                        display_bilateral_category_summary(summary)
            else:
                st.info(f"No category summaries found for {init} → {recip}")
    else:
        st.info("No bilateral category summaries available.")

elif view_mode == "By Category":
    st.header("📁 Analysis by Category")

    summaries = get_all_bilateral_category_summaries()

    if summaries:
        # Get available categories
        categories = sorted(list(set(s['category'] for s in summaries)))

        selected_category = st.selectbox(
            "Select Category",
            categories,
            key="category_select"
        )

        if selected_category:
            # Filter summaries by category
            category_summaries = [s for s in summaries if s['category'] == selected_category]

            if category_summaries:
                st.success(f"Loaded {len(category_summaries)} bilateral relationships in {selected_category}")

                # Overview metrics
                col1, col2, col3, col4 = st.columns(4)

                total_docs = sum(s['total_documents'] for s in category_summaries)
                total_events = sum(
                    s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events']
                    for s in category_summaries
                )
                avg_material = sum(s['material_score_avg'] or 0 for s in category_summaries) / len(category_summaries)

                with col1:
                    st.metric("Total Documents", f"{total_docs:,}")

                with col2:
                    st.metric("Total Events", f"{total_events:,}")

                with col3:
                    st.metric("Relationships", len(category_summaries))

                with col4:
                    st.metric("Avg Material Score", f"{avg_material:.2f}")

                # Top relationships in this category
                st.markdown(f"### 🏆 Top {selected_category} Relationships")

                relationship_data = []
                for s in category_summaries:
                    relationship_data.append({
                        'Initiating': s['initiating_country'],
                        'Recipient': s['recipient_country'],
                        'Documents': s['total_documents'],
                        'Events': s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events'],
                        'Material Score': s['material_score_avg'] or 0
                    })

                rel_df = pd.DataFrame(relationship_data).sort_values('Documents', ascending=False)

                # Create label
                rel_df['Relationship'] = rel_df['Initiating'] + ' → ' + rel_df['Recipient']

                # Bar chart
                top_n = min(20, len(rel_df))
                top_rel = rel_df.head(top_n)

                chart = alt.Chart(top_rel).mark_bar().encode(
                    x=alt.X('Documents:Q', title='Documents'),
                    y=alt.Y('Relationship:N',
                           sort=alt.EncodingSortField(field='Documents', order='descending'),
                           title='Relationship'),
                    color=alt.Color('Material Score:Q',
                                   scale=alt.Scale(scheme='viridis'),
                                   legend=alt.Legend(title='Material Score')),
                    tooltip=['Initiating', 'Recipient', 'Documents', 'Events', 'Material Score']
                ).properties(
                    height=500,
                    title=f'Top {top_n} {selected_category} Relationships'
                )

                st.altair_chart(chart, use_container_width=True)

                # Table
                st.dataframe(
                    rel_df[['Initiating', 'Recipient', 'Documents', 'Events', 'Material Score']],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info(f"No relationships found for {selected_category}")
    else:
        st.info("No bilateral category summaries available.")

elif view_mode == "Compare":
    st.header("⚖️ Compare Categories within a Relationship")

    summaries = get_all_bilateral_category_summaries()

    if summaries:
        # Get unique pairs
        pairs = list(set((s['initiating_country'], s['recipient_country']) for s in summaries))
        pair_options = [f"{init} → {recip}" for init, recip in sorted(pairs)]

        selected_pair = st.selectbox(
            "Select Country Pair to Compare",
            pair_options,
            key="compare_pair"
        )

        if selected_pair:
            init, recip = selected_pair.split(" → ")

            pair_summaries = get_bilateral_categories(init, recip)

            if len(pair_summaries) >= 2:
                st.markdown(f"### {init} → {recip} - Category Comparison")

                # Create comparison dataframe
                comparison_data = []
                for s in pair_summaries:
                    comparison_data.append({
                        'Category': s['category'],
                        'Documents': s['total_documents'],
                        'Daily Events': s['total_daily_events'],
                        'Weekly Events': s['total_weekly_events'],
                        'Monthly Events': s['total_monthly_events'],
                        'Subcategories': len(s['count_by_subcategory']),
                        'Material Score (Avg)': s['material_score_avg'] or 0,
                        'Material Score (Median)': s['material_score_median'] or 0
                    })

                comp_df = pd.DataFrame(comparison_data)

                # Display comparison table
                st.dataframe(
                    comp_df,
                    use_container_width=True,
                    hide_index=True
                )

                # Visualizations
                col1, col2 = st.columns(2)

                with col1:
                    # Documents comparison
                    doc_chart = alt.Chart(comp_df).mark_bar().encode(
                        x=alt.X('Category:N', title='Category'),
                        y=alt.Y('Documents:Q', title='Documents'),
                        color=alt.Color('Category:N', legend=None),
                        tooltip=['Category', 'Documents']
                    ).properties(
                        height=300,
                        title='Documents by Category'
                    )
                    st.altair_chart(doc_chart, use_container_width=True)

                with col2:
                    # Material score comparison
                    mat_chart = alt.Chart(comp_df).mark_bar().encode(
                        x=alt.X('Category:N', title='Category'),
                        y=alt.Y('Material Score (Avg):Q', title='Material Score'),
                        color=alt.Color('Category:N', legend=None),
                        tooltip=['Category', 'Material Score (Avg)']
                    ).properties(
                        height=300,
                        title='Material Score by Category'
                    )
                    st.altair_chart(mat_chart, use_container_width=True)

                # Detailed comparisons
                st.markdown("### 📋 Detailed Category Comparisons")

                for summary in pair_summaries:
                    with st.expander(f"{summary['category']}"):
                        display_bilateral_category_summary(summary)

            else:
                st.info(f"Need at least 2 categories for {init} → {recip} to compare")
    else:
        st.info("No bilateral category summaries available.")


def display_bilateral_category_summary(summary: dict):
    """Display a bilateral category summary."""

    # Basic metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Documents", f"{summary['total_documents']:,}")

    with col2:
        total_events = (
            summary['total_daily_events'] +
            summary['total_weekly_events'] +
            summary['total_monthly_events']
        )
        st.metric("Total Events", f"{total_events:,}")

    with col3:
        st.metric("Subcategories", len(summary['count_by_subcategory']))

    with col4:
        if summary['material_score_avg']:
            st.metric("Material Score", f"{summary['material_score_avg']:.2f}")
        else:
            st.metric("Material Score", "N/A")

    st.caption(f"📅 {summary['first_interaction_date']} to {summary['last_interaction_date']}")

    # Category summary content
    cat_summary = summary['category_summary']

    # Overview
    st.markdown("#### 📝 Overview")
    st.markdown(cat_summary.get('overview', 'N/A'))

    # Key focus areas
    st.markdown("#### 🎯 Key Focus Areas")
    for area in cat_summary.get('key_focus_areas', []):
        st.markdown(f"- {area}")

    # Top subcategories
    st.markdown("#### 📁 Top Subcategories")
    subcats = sorted(
        summary['count_by_subcategory'].items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]

    for subcat, count in subcats:
        pct = (count / summary['total_documents']) * 100
        st.markdown(f"- **{subcat}**: {count:,} documents ({pct:.1f}%)")

    # Material histogram
    if summary['material_score_histogram']:
        st.markdown("#### 📊 Material Score Distribution")

        hist_data = []
        for score, count in summary['material_score_histogram'].items():
            hist_data.append({'Score': float(score), 'Count': count})

        if hist_data:
            hist_df = pd.DataFrame(hist_data).sort_values('Score')

            hist_chart = alt.Chart(hist_df).mark_bar().encode(
                x=alt.X('Score:Q', title='Material Score', scale=alt.Scale(domain=[2, 10])),
                y=alt.Y('Count:Q', title='Number of Events'),
                tooltip=['Score', 'Count']
            ).properties(
                height=200,
                title='Event Material Score Distribution'
            )

            st.altair_chart(hist_chart, use_container_width=True)


# Footer
st.markdown("---")
st.caption("💡 Tip: Use the sidebar to explore different views of bilateral category relationships.")
