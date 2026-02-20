"""
Master Events Dashboard

Displays comprehensive analytics for master events (consolidated events tracked across multiple days).
Shows event metrics for influencing and recipient countries defined in config.yaml.
"""
import streamlit as st
import datetime
import pandas as pd

from queries.event_queries import (
    get_master_event_overview,
    get_top_master_events,
    get_events_by_country,
    get_temporal_trends,
    get_category_breakdown,
    get_recipient_impact,
    get_master_event_details,
    get_master_event_timeline,
    get_standalone_canonical_events
)

from charts.event_charts import (
    top_master_events_chart,
    events_by_country_chart,
    temporal_trends_chart,
    category_breakdown_chart,
    recipient_impact_chart,
    master_event_timeline_chart,
    country_article_comparison_chart
)

from shared.utils.utils import Config

# Load config for country lists
cfg = Config.from_yaml()

st.set_page_config(
    page_title="Master Events Dashboard",
    page_icon="🌍",
    layout="wide"
)

st.markdown(
    "<h1 style='text-align: center; color: #4F8BF9;'>🌍 Master Events Dashboard</h1>",
    unsafe_allow_html=True
)

st.markdown("""
This dashboard displays master events - consolidated events tracked across multiple days.
Master events aggregate related canonical events to provide a comprehensive view of ongoing international developments.

**Data Filtering:** This dashboard shows only events and documents that match the countries, categories, and subcategories
defined in `config.yaml`. All metrics count unique documents that match ALL filter criteria:
- **Initiating Countries:** Limited to influencers from config
- **Recipient Countries:** Limited to recipients from config (default: all 18 Middle East countries)
- **Categories:** Economic, Social, Military, Diplomacy
- **Subcategories:** All {num_subcat} subcategories from config
""".format(num_subcat=len(cfg.subcategories)))

# Sidebar filters
st.sidebar.title("Filters")

st.sidebar.markdown("### Geographic Filters")

# Initiating country filter
influencer_countries = ['ALL'] + cfg.influencers
selected_country = st.sidebar.selectbox(
    "Initiating Country",
    options=influencer_countries,
    index=0,
    help="Filter by country initiating the events"
)

# Recipient country filter
recipient_countries_options = ['ALL'] + cfg.recipients
selected_recipients = st.sidebar.multiselect(
    "Recipient Countries",
    options=cfg.recipients,
    default=cfg.recipients,
    help="Filter by countries receiving/targeted by events. Showing only config.yaml recipients by default."
)

# If no recipients selected, use all
if not selected_recipients:
    selected_recipients = cfg.recipients

# Date range filter
st.sidebar.markdown("### Date Range Filter")
start_date = st.sidebar.date_input(
    "Start Date",
    value=datetime.date(2024, 8, 1),
    min_value=datetime.date(2024, 8, 1),
    max_value=datetime.date.today()
)
end_date = st.sidebar.date_input(
    "End Date",
    value=datetime.date(2024, 8, 31),
    min_value=datetime.date(2024, 8, 1),
    max_value=datetime.date.today()
)

# Convert dates to strings for queries
start_date_str = start_date.strftime('%Y-%m-%d')
end_date_str = end_date.strftime('%Y-%m-%d')

st.sidebar.markdown("---")
st.sidebar.markdown(f"""
**Active Filters:**
- Initiating: {selected_country}
- Recipients: {len(selected_recipients)} of {len(cfg.recipients)} countries
- Categories: {len(cfg.categories)} categories
- Subcategories: {len(cfg.subcategories)} subcategories
""")

# Main content
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Overview",
    "🌎 Country Analysis",
    "📈 Temporal Trends",
    "🔍 Event Explorer",
    "🎯 Recipient Impact"
])

with tab1:
    st.header("Master Events Overview")

    st.info(f"""
    📊 **Data Scope:** Showing events from **{len(cfg.influencers)} influencer countries**
    targeting **{len(selected_recipients)} recipient countries** (from {len(cfg.recipients)} total in config).
    All article counts reflect unique documents matching ALL config filters.
    """)

    # Get overview stats
    overview_df = get_master_event_overview(start_date_str, end_date_str)

    if not overview_df.empty:
        row = overview_df.iloc[0]

        # Display metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                label="Total Master Events",
                value=int(row['master_event_count'])
            )

        with col2:
            st.metric(
                label="Total Child Events",
                value=int(row['child_event_count'])
            )

        with col3:
            st.metric(
                label="Total Articles",
                value=f"{int(row['total_articles']):,}"
            )

        with col4:
            date_range = (pd.to_datetime(row['latest_date']) - pd.to_datetime(row['earliest_date'])).days + 1
            st.metric(
                label="Days Span",
                value=date_range
            )

        st.markdown("---")

    # Top master events
    st.subheader("Top Master Events by Article Volume")

    country_filter = None if selected_country == 'ALL' else selected_country
    top_events_df = get_top_master_events(
        limit=20,
        country=country_filter,
        start_date=start_date_str,
        end_date=end_date_str
    )

    if not top_events_df.empty:
        st.altair_chart(top_master_events_chart(top_events_df), use_container_width=True)

        # Display table
        with st.expander("View Data Table"):
            display_df = top_events_df.copy()
            display_df.columns = ['Event Name', 'Country', 'First Mention', 'Last Mention',
                                   'Total Articles', 'Child Events', 'Days Active']
            st.dataframe(display_df, use_container_width=True)
    else:
        st.info("No master events found for the selected filters.")

with tab2:
    st.header("Country Analysis")

    # Get country breakdown
    country_df = get_events_by_country(start_date_str, end_date_str)

    if not country_df.empty:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Master Events by Country")
            st.altair_chart(events_by_country_chart(country_df), use_container_width=True)

        with col2:
            st.subheader("Article Volume by Country")
            st.altair_chart(country_article_comparison_chart(country_df), use_container_width=True)

        # Summary table
        st.subheader("Country Summary")
        summary_df = country_df.copy()
        summary_df.columns = ['Country', 'Master Events', 'Child Events', 'Total Articles']
        st.dataframe(summary_df, use_container_width=True)

        # Category breakdown by country
        st.subheader("Category Distribution")
        category_df = get_category_breakdown(
            country=country_filter,
            start_date=start_date_str,
            end_date=end_date_str
        )

        if not category_df.empty:
            st.altair_chart(category_breakdown_chart(category_df), use_container_width=True)

            with st.expander("View Category Data"):
                cat_display_df = category_df.copy()
                cat_display_df.columns = ['Category', 'Master Events', 'Total Articles']
                st.dataframe(cat_display_df, use_container_width=True)
    else:
        st.info("No data available for the selected date range.")

with tab3:
    st.header("Temporal Trends")

    # Get temporal trends
    trends_df = get_temporal_trends(
        country=country_filter,
        start_date=start_date_str,
        end_date=end_date_str
    )

    if not trends_df.empty:
        st.altair_chart(temporal_trends_chart(trends_df), use_container_width=True)

        # Statistics
        col1, col2, col3 = st.columns(3)

        with col1:
            avg_articles = trends_df['article_count'].mean()
            st.metric("Avg Daily Articles", f"{avg_articles:.1f}")

        with col2:
            peak_day = trends_df.loc[trends_df['article_count'].idxmax()]
            st.metric("Peak Article Day", peak_day['date'].strftime('%Y-%m-%d'))
            st.caption(f"{int(peak_day['article_count'])} articles")

        with col3:
            avg_events = trends_df['event_count'].mean()
            st.metric("Avg Daily Events", f"{avg_events:.1f}")

        # Show data table
        with st.expander("View Daily Data"):
            display_trends = trends_df.copy()
            display_trends['date'] = display_trends['date'].dt.strftime('%Y-%m-%d')
            display_trends.columns = ['Date', 'Articles', 'Events']
            st.dataframe(display_trends, use_container_width=True)
    else:
        st.info("No temporal data available for the selected filters.")

with tab4:
    st.header("Master Event Explorer")

    # Get list of master events for selection
    events_list_df = get_top_master_events(
        limit=100,
        country=country_filter,
        start_date=start_date_str,
        end_date=end_date_str
    )

    if not events_list_df.empty:
        # Event selector
        event_names = events_list_df['canonical_name'].tolist()
        selected_event = st.selectbox(
            "Select a Master Event to Explore",
            options=event_names,
            index=0
        )

        if selected_event:
            # Get event details
            master_info_df, child_events_df = get_master_event_details(
                selected_event,
                country=country_filter if country_filter != 'ALL' else None
            )

            if not master_info_df.empty:
                st.subheader(f"Master Event: {selected_event}")

                # Display master event info
                row = master_info_df.iloc[0]
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric("Country", row['initiating_country'])

                with col2:
                    st.metric("Total Articles", f"{int(row['total_articles']):,}")

                with col3:
                    st.metric("Days Active", int(row['days_span']))

                with col4:
                    st.metric("Mention Days", int(row['total_mention_days']))

                # Show categories and recipients
                col1, col2 = st.columns(2)

                with col1:
                    if row['primary_categories']:
                        st.write("**Categories:**")
                        if isinstance(row['primary_categories'], str):
                            st.write(row['primary_categories'])
                        else:
                            for cat in list(row['primary_categories'].keys())[:5]:
                                st.write(f"- {cat}")

                with col2:
                    if row['primary_recipients']:
                        st.write("**Recipients:**")
                        if isinstance(row['primary_recipients'], str):
                            st.write(row['primary_recipients'])
                        else:
                            for rec in list(row['primary_recipients'].keys())[:5]:
                                st.write(f"- {rec}")

                st.markdown("---")

                # Child events
                if not child_events_df.empty:
                    st.subheader(f"Child Events ({len(child_events_df)})")

                    child_display = child_events_df.copy()
                    child_display.columns = ['Event Name', 'First Mention', 'Last Mention',
                                             'Articles', 'Mention Days']
                    st.dataframe(child_display, use_container_width=True)

                # Timeline
                st.subheader("Timeline")
                timeline_df = get_master_event_timeline(selected_event)

                if not timeline_df.empty:
                    st.altair_chart(
                        master_event_timeline_chart(timeline_df),
                        use_container_width=True
                    )
                else:
                    st.info("No timeline data available.")
            else:
                st.warning("Event details not found.")
    else:
        st.info("No master events found for the selected filters.")

    # Standalone events section
    st.markdown("---")
    st.subheader("Standalone Canonical Events")
    st.caption("Events that are not part of any master event cluster")

    standalone_df = get_standalone_canonical_events(
        country=country_filter,
        limit=20,
        start_date=start_date_str,
        end_date=end_date_str
    )

    if not standalone_df.empty:
        standalone_display = standalone_df.copy()
        standalone_display.columns = ['Event Name', 'Country', 'First Mention',
                                       'Last Mention', 'Articles', 'Mention Days']
        st.dataframe(standalone_display, use_container_width=True)
    else:
        st.info("All canonical events are part of master event clusters.")

with tab5:
    st.header("Recipient Impact Analysis")

    st.markdown("""
    This section shows which recipient countries are most affected by master events
    from different initiating countries. **All documents are filtered to match config.yaml recipients.**
    """)

    # Get recipient impact data (always uses cfg.recipients for data filtering)
    recipient_df = get_recipient_impact(
        cfg.recipients,
        start_date=start_date_str,
        end_date=end_date_str
    )

    # Filter display by selected recipients (UI filter only)
    if 'ALL' not in selected_recipients and len(selected_recipients) < len(cfg.recipients):
        recipient_df = recipient_df[recipient_df['recipient'].isin(selected_recipients)]

    if not recipient_df.empty:
        # Heatmap
        st.subheader("Impact Heatmap")
        st.altair_chart(recipient_impact_chart(recipient_df), use_container_width=True)

        # Top recipients
        st.subheader("Top Recipient Countries")
        top_recipients = recipient_df.groupby('recipient').agg({
            'master_event_count': 'sum',
            'total_articles': 'sum'
        }).reset_index().sort_values('total_articles', ascending=False).head(10)

        top_recipients.columns = ['Recipient', 'Master Events', 'Total Articles']
        st.dataframe(top_recipients, use_container_width=True)

        # Detailed table
        with st.expander("View Full Recipient Impact Data"):
            detail_df = recipient_df.copy()
            detail_df.columns = ['Recipient', 'Initiating Country', 'Master Events', 'Total Articles']
            st.dataframe(detail_df, use_container_width=True)
    else:
        st.info("No recipient impact data available for the selected filters.")

# Footer
st.markdown("---")
st.markdown("""
**About Master Events:** Master events are created by consolidating related canonical events
that occur across multiple days using embedding similarity (0.80 threshold) and temporal
proximity (7-day window). This provides a comprehensive view of ongoing international developments.
""")
