"""
Country Category Analysis Dashboard

Explore how countries deploy specific categories of soft power (Economic, Social, Military, Diplomacy)
across all their recipient relationships.
"""

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from typing import Optional, List, Dict
from queries.category_queries import (
    get_all_country_category_summaries,
    get_country_category_summary,
    get_country_categories,
    get_category_by_countries,
    get_top_country_categories_by_documents,
    get_country_category_statistics
)


# Page configuration
st.set_page_config(
    page_title="Country Category Analysis",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 Country Category Analysis")
st.markdown("""
Analyze how countries deploy specific categories of soft power across all their bilateral relationships.
Each summary provides strategic insights into category-specific soft power deployment.
""")

# Load statistics
stats = get_country_category_statistics()

# Top-level metrics
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Summaries", stats['total_summaries'])

with col2:
    st.metric("Countries Analyzed", stats['unique_countries'])

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
    ["Overview", "By Country", "By Category", "Compare Categories"]
)

if view_mode == "Overview":
    st.header("📊 Country Category Overview")

    summaries = get_all_country_category_summaries()

    if summaries:
        # Create summary dataframe
        summary_data = []
        for s in summaries:
            summary_data.append({
                'Country': s['initiating_country'],
                'Category': s['category'],
                'Documents': s['total_documents'],
                'Daily Events': s['total_daily_events'],
                'Recipients': len(s['count_by_recipient']),
                'Material Score': s['material_score_avg'] or 0,
                'Subcategories': len(s['count_by_subcategory'])
            })

        df = pd.DataFrame(summary_data)

        # Tabs for different views
        tab1, tab2, tab3 = st.tabs([
            "📋 All Summaries",
            "🏆 Top by Volume",
            "📈 Visualizations"
        ])

        with tab1:
            st.subheader("All Country-Category Summaries")

            # Sort options
            sort_by = st.selectbox(
                "Sort by",
                ["Documents", "Material Score", "Recipients", "Country"],
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
                file_name=f"country_category_summaries_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

        with tab2:
            st.subheader("🏆 Top Country-Category Combinations")

            top_n = st.slider("Show top N", 5, 30, 15, key="top_volume")

            top_by_docs = df.nlargest(top_n, 'Documents')

            # Create a combined label for better visualization
            top_by_docs['Label'] = top_by_docs['Country'] + ' - ' + top_by_docs['Category']

            # Bar chart
            chart = alt.Chart(top_by_docs).mark_bar().encode(
                x=alt.X('Documents:Q', title='Number of Documents'),
                y=alt.Y('Label:N',
                       sort=alt.EncodingSortField(field='Documents', order='descending'),
                       title='Country - Category'),
                color=alt.Color('Category:N', legend=alt.Legend(title="Category")),
                tooltip=[
                    'Country',
                    'Category',
                    'Documents',
                    'Recipients',
                    'Material Score'
                ]
            ).properties(
                height=500,
                title=f'Top {top_n} Country-Category Combinations by Document Volume'
            )

            st.altair_chart(chart, use_container_width=True)

            # Table
            st.dataframe(
                top_by_docs[['Country', 'Category', 'Documents', 'Recipients', 'Material Score']],
                use_container_width=True,
                hide_index=True
            )

        with tab3:
            st.subheader("📈 Category Distribution Visualizations")

            # Heatmap: Country vs Category
            st.markdown("#### Activity Heatmap: Countries vs Categories")

            # Pivot data for heatmap
            heatmap_data = df.pivot_table(
                values='Documents',
                index='Country',
                columns='Category',
                fill_value=0
            ).reset_index()

            # Melt for Altair
            heatmap_melted = heatmap_data.melt(id_vars=['Country'], var_name='Category', value_name='Documents')

            heatmap = alt.Chart(heatmap_melted).mark_rect().encode(
                x=alt.X('Category:N', title='Category'),
                y=alt.Y('Country:N', title='Country'),
                color=alt.Color('Documents:Q',
                               scale=alt.Scale(scheme='viridis'),
                               legend=alt.Legend(title='Documents')),
                tooltip=['Country', 'Category', 'Documents']
            ).properties(
                height=400,
                title='Document Distribution Across Countries and Categories'
            )

            st.altair_chart(heatmap, use_container_width=True)

            # Material Score by Category
            st.markdown("#### Material Score Distribution by Category")

            material_chart = alt.Chart(df).mark_boxplot().encode(
                x=alt.X('Category:N', title='Category'),
                y=alt.Y('Material Score:Q', title='Material Score'),
                color=alt.Color('Category:N', legend=None)
            ).properties(
                height=350,
                title='Material Score Distribution by Category'
            )

            st.altair_chart(material_chart, use_container_width=True)

    else:
        st.info("No country category summaries found. Generate some using the pipeline scripts.")

elif view_mode == "By Country":
    st.header("🌍 Category Analysis by Country")

    summaries = get_all_country_category_summaries()

    if summaries:
        # Get available countries
        countries = sorted(list(set(s['initiating_country'] for s in summaries)))

        selected_country = st.selectbox(
            "Select Country",
            countries,
            key="country_select"
        )

        if selected_country:
            country_summaries = get_country_categories(selected_country)

            if country_summaries:
                st.success(f"Loaded {len(country_summaries)} category summaries for {selected_country}")

                # Overview metrics
                col1, col2, col3, col4 = st.columns(4)

                total_docs = sum(s['total_documents'] for s in country_summaries)
                total_events = sum(
                    s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events']
                    for s in country_summaries
                )
                avg_material = sum(s['material_score_avg'] or 0 for s in country_summaries) / len(country_summaries)

                with col1:
                    st.metric("Total Documents", f"{total_docs:,}")

                with col2:
                    st.metric("Total Events", f"{total_events:,}")

                with col3:
                    st.metric("Categories Analyzed", len(country_summaries))

                with col4:
                    st.metric("Avg Material Score", f"{avg_material:.2f}")

                # Category comparison
                st.markdown("### 📊 Category Comparison")

                category_data = []
                for s in country_summaries:
                    category_data.append({
                        'Category': s['category'],
                        'Documents': s['total_documents'],
                        'Events': s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events'],
                        'Recipients': len(s['count_by_recipient']),
                        'Material Score': s['material_score_avg'] or 0
                    })

                cat_df = pd.DataFrame(category_data)

                # Bar chart comparing categories
                chart = alt.Chart(cat_df).mark_bar().encode(
                    x=alt.X('Category:N', title='Category'),
                    y=alt.Y('Documents:Q', title='Number of Documents'),
                    color=alt.Color('Category:N', legend=None),
                    tooltip=['Category', 'Documents', 'Events', 'Recipients', 'Material Score']
                ).properties(
                    height=300,
                    title=f'{selected_country} - Documents by Category'
                )

                st.altair_chart(chart, use_container_width=True)

                # Detailed summaries by category
                st.markdown("### 📋 Detailed Category Summaries")

                for summary in country_summaries:
                    with st.expander(f"{summary['category']} - {summary['total_documents']:,} docs"):
                        display_country_category_summary(summary)
            else:
                st.info(f"No category summaries found for {selected_country}")
    else:
        st.info("No country category summaries available.")

elif view_mode == "By Category":
    st.header("📁 Analysis by Category")

    summaries = get_all_country_category_summaries()

    if summaries:
        # Get available categories
        categories = sorted(list(set(s['category'] for s in summaries)))

        selected_category = st.selectbox(
            "Select Category",
            categories,
            key="category_select"
        )

        if selected_category:
            category_summaries = get_category_by_countries(selected_category)

            if category_summaries:
                st.success(f"Loaded {len(category_summaries)} country summaries for {selected_category}")

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
                    st.metric("Countries Analyzed", len(category_summaries))

                with col4:
                    st.metric("Avg Material Score", f"{avg_material:.2f}")

                # Country comparison for this category
                st.markdown(f"### 📊 {selected_category} Deployment by Country")

                country_data = []
                for s in category_summaries:
                    country_data.append({
                        'Country': s['initiating_country'],
                        'Documents': s['total_documents'],
                        'Events': s['total_daily_events'] + s['total_weekly_events'] + s['total_monthly_events'],
                        'Recipients': len(s['count_by_recipient']),
                        'Material Score': s['material_score_avg'] or 0
                    })

                country_df = pd.DataFrame(country_data).sort_values('Documents', ascending=False)

                # Bar chart
                chart = alt.Chart(country_df).mark_bar().encode(
                    x=alt.X('Documents:Q', title='Number of Documents'),
                    y=alt.Y('Country:N',
                           sort=alt.EncodingSortField(field='Documents', order='descending'),
                           title='Country'),
                    color=alt.Color('Material Score:Q',
                                   scale=alt.Scale(scheme='viridis'),
                                   legend=alt.Legend(title='Material Score')),
                    tooltip=['Country', 'Documents', 'Events', 'Recipients', 'Material Score']
                ).properties(
                    height=400,
                    title=f'{selected_category} Soft Power Deployment by Country'
                )

                st.altair_chart(chart, use_container_width=True)

                # Table
                st.dataframe(
                    country_df,
                    use_container_width=True,
                    hide_index=True
                )

                # Detailed summaries
                st.markdown("### 📋 Detailed Country Summaries")

                for summary in category_summaries[:10]:  # Show top 10
                    with st.expander(f"{summary['initiating_country']} - {summary['total_documents']:,} docs"):
                        display_country_category_summary(summary)
            else:
                st.info(f"No summaries found for {selected_category}")
    else:
        st.info("No category summaries available.")

elif view_mode == "Compare Categories":
    st.header("⚖️ Compare Categories")

    summaries = get_all_country_category_summaries()

    if summaries:
        # Get available countries
        countries = sorted(list(set(s['initiating_country'] for s in summaries)))

        selected_country = st.selectbox(
            "Select Country to Compare",
            countries,
            key="compare_country"
        )

        if selected_country:
            country_summaries = get_country_categories(selected_country)

            if len(country_summaries) >= 2:
                st.markdown(f"### {selected_country} - Category Comparison")

                # Create comparison dataframe
                comparison_data = []
                for s in country_summaries:
                    comparison_data.append({
                        'Category': s['category'],
                        'Documents': s['total_documents'],
                        'Daily Events': s['total_daily_events'],
                        'Weekly Events': s['total_weekly_events'],
                        'Monthly Events': s['total_monthly_events'],
                        'Recipients': len(s['count_by_recipient']),
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

                # Side-by-side radar chart comparison
                st.markdown("### 📊 Multi-Dimensional Comparison")

                # Normalize values for radar chart
                normalized = comp_df.copy()
                for col in ['Documents', 'Daily Events', 'Recipients', 'Material Score (Avg)']:
                    max_val = normalized[col].max()
                    if max_val > 0:
                        normalized[f'{col}_norm'] = normalized[col] / max_val

                # Create multi-metric comparison
                col1, col2 = st.columns(2)

                with col1:
                    # Bar chart: Documents
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
                    # Bar chart: Material Score
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

            else:
                st.info(f"Need at least 2 categories for {selected_country} to compare")
    else:
        st.info("No category summaries available.")


def display_country_category_summary(summary: dict):
    """Display a country category summary."""

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
        st.metric("Recipients", len(summary['count_by_recipient']))

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

    # Key strategies
    st.markdown("#### 🎯 Key Strategies")
    for strategy in cat_summary.get('key_strategies', []):
        st.markdown(f"- {strategy}")

    # Top recipients
    st.markdown("#### 🌍 Top Recipients")
    recipients = sorted(
        summary['count_by_recipient'].items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    for recip, count in recipients:
        pct = (count / summary['total_documents']) * 100
        st.markdown(f"- **{recip}**: {count:,} documents ({pct:.1f}%)")

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
st.caption("💡 Tip: Use the sidebar to switch between different views and explore category-specific soft power deployment.")
