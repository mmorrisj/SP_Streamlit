import streamlit as st
import pandas as pd
import altair as alt
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import json
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, or_
from backend.scripts.models import DailySummary, DailyEventSummary
from backend.app import create_app
from backend.extensions import db
from backend.scripts.utils import Config

# Load configuration and initialize filter manager
cfg = Config.from_yaml()

# Configuration-aware filtering utilities (inline for this example)
class ConfigFilterManager:
    """Manages all configuration-based filtering for the analytics dashboard"""
    
    def __init__(self, config):
        self.cfg = config
        
    def filter_events_by_config(self, events_df):
        """Apply all configuration-based filters to events dataframe"""
        if events_df.empty:
            return events_df
        
        # 1. Filter initiating countries to config influencers
        events_df = events_df[events_df['initiating_country'].isin(self.cfg.influencers)]
        
        # 2. Remove same-country events
        events_df = self._remove_same_country_events(events_df)
        
        # 3. Filter to valid recipients only
        events_df = self._filter_valid_recipients(events_df)
        
        # 4. Filter to valid categories only
        events_df = self._filter_valid_categories(events_df)
        
        return events_df
    
    def _remove_same_country_events(self, events_df):
        """Remove events where initiator appears in recipient list"""
        def filter_same_country(row):
            initiator = row['initiating_country']
            recipients_list = row.get('recipient_countries', [])
            
            if not recipients_list or recipients_list is None:
                return True
            
            # Handle both string and list formats
            if isinstance(recipients_list, str):
                try:
                    import json
                    recipients_list = json.loads(recipients_list)
                except:
                    recipients_list = [recipients_list]
            
            # Exclude if initiator is in the recipient list
            return initiator not in recipients_list
        
        return events_df[events_df.apply(filter_same_country, axis=1)]
    
    def _filter_valid_recipients(self, events_df):
        """Keep only events with at least one valid recipient"""
        def has_valid_recipient(row):
            recipients_list = row.get('recipient_countries', [])
            
            if not recipients_list or recipients_list is None:
                return False
            
            # Handle both string and list formats
            if isinstance(recipients_list, str):
                try:
                    import json
                    recipients_list = json.loads(recipients_list)
                except:
                    recipients_list = [recipients_list]
            
            return any(r in self.cfg.recipients for r in recipients_list)
        
        return events_df[events_df.apply(has_valid_recipient, axis=1)]
    
    def _filter_valid_categories(self, events_df):
        """Keep events with at least one valid category (or no categories)"""
        def has_valid_category(row):
            categories_list = row.get('categories', [])
            
            if not categories_list or categories_list is None:
                return True  # Keep events without categories
            
            # Handle both string and list formats
            if isinstance(categories_list, str):
                try:
                    import json
                    categories_list = json.loads(categories_list)
                except:
                    categories_list = [categories_list]
            
            return any(c in self.cfg.categories for c in categories_list)
        
        return events_df[events_df.apply(has_valid_category, axis=1)]

    def get_data_quality_stats(self, original_df, filtered_df):
        """Generate data quality statistics"""
        if original_df.empty:
            return {}
        
        # Calculate same-country events
        same_country_events = 0
        for _, row in original_df.iterrows():
            initiator = row['initiating_country']
            recipients_list = row.get('recipient_countries', [])
            
            if recipients_list:
                if isinstance(recipients_list, str):
                    try:
                        import json
                        recipients_list = json.loads(recipients_list)
                    except:
                        recipients_list = [recipients_list]
                
                if initiator in recipients_list:
                    same_country_events += 1
        
        return {
            'total_events_raw': len(original_df),
            'total_events_filtered': len(filtered_df),
            'same_country_events_removed': same_country_events,
            'events_removed_pct': ((len(original_df) - len(filtered_df)) / len(original_df) * 100) if len(original_df) > 0 else 0,
        }

# Initialize filter manager
filter_manager = ConfigFilterManager(cfg)

# Professional styling and configuration
st.set_page_config(
    page_title="Event Analytics Platform",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Professional color palette
COLORS = {
    'primary': '#1f77b4',
    'secondary': '#ff7f0e', 
    'success': '#2ca02c',
    'danger': '#d62728',
    'warning': '#ff7f0e',
    'info': '#17a2b8',
    'neutral': '#6c757d',
    'light': '#f8f9fa',
    'dark': '#343a40'
}

# Custom CSS for professional appearance
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1f77b4 0%, #2ca02c 100%);
        color: white;
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        text-align: center;
    }
    
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-left: 4px solid #1f77b4;
        margin-bottom: 1rem;
    }
    
    .insight-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #17a2b8;
        margin: 1rem 0;
    }
    
    .filter-section {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        margin-bottom: 1rem;
    }
    
    .stMetric {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# Initialize Flask app context
@st.cache_resource
def init_app():
    app = create_app()
    ctx = app.app_context()
    ctx.push()
    return app, ctx

app, ctx = init_app()

# Utility functions
@st.cache_data(ttl=300)
def load_date_range():
    """Get available date range from database"""
    with app.app_context():
        latest_date = db.session.query(func.max(DailyEventSummary.report_date)).scalar()
        earliest_date = db.session.query(func.min(DailyEventSummary.report_date)).scalar()
    
    return earliest_date or datetime(2024, 1, 1).date(), latest_date or datetime.now().date()

@st.cache_data(ttl=300)
def load_countries():
    """Get available countries from config"""
    return cfg.influencers

@st.cache_data(ttl=300)
def load_recipients():
    """Get available recipients from config"""
    return cfg.recipients

@st.cache_data(ttl=300)
def load_categories():
    """Get available categories from config"""
    return cfg.categories

@st.cache_data(ttl=300)
def load_subcategories():
    """Get available subcategories from config"""
    return cfg.subcategories

@st.cache_data(ttl=300)
def load_raw_dashboard_data(start_date, end_date):
    """Load raw dashboard data without config filtering for quality analysis"""
    try:
        with app.app_context():
            # Load all events in date range (no filtering)
            query = db.session.query(DailyEventSummary).filter(
                DailyEventSummary.report_date.between(start_date, end_date)
            )
            
            events_df = pd.read_sql(query.statement, db.engine)
            
            # Load summary data
            summary_query = db.session.query(DailySummary).filter(
                DailySummary.date.between(start_date, end_date)
            )
            
            summary_df = pd.read_sql(summary_query.statement, db.engine)
            
        return events_df, summary_df, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), str(e)

def generate_insights(events_df, summary_df):
    """Generate automated insights from data"""
    insights = []
    
    if events_df.empty:
        return insights
    
    # Material score trends
    recent_events = events_df.tail(min(50, len(events_df)))
    if len(recent_events) > 0:
        recent_avg = recent_events['material_score'].mean()
        overall_avg = events_df['material_score'].mean()
        
        if recent_avg > overall_avg * 1.15:
            insights.append({
                'type': 'warning',
                'icon': '⚠️',
                'text': f'Recent events show {((recent_avg/overall_avg-1)*100):.0f}% higher materiality than average'
            })
    
    # Most active initiator
    initiator_counts = events_df['initiating_country'].value_counts()
    if len(initiator_counts) > 0:
        top_initiator = initiator_counts.index[0]
        top_count = initiator_counts.iloc[0]
        insights.append({
            'type': 'info',
            'icon': '🎯',
            'text': f'{top_initiator} initiated {top_count} events ({(top_count/len(events_df)*100):.1f}% of total)'
        })
    
    # High impact events
    high_material_events = events_df[events_df['material_score'] >= 7]
    if len(high_material_events) > 0:
        insights.append({
            'type': 'danger',
            'icon': '🔥',
            'text': f'{len(high_material_events)} high-impact events (score ≥7) detected'
        })
    
    # Category insights
    all_categories = []
    for _, row in events_df.iterrows():
        if row.get('categories'):
            valid_categories = [c for c in row['categories'] if c in cfg.categories]
            all_categories.extend(valid_categories)
    
    if all_categories:
        top_category = pd.Series(all_categories).value_counts().index[0]
        insights.append({
            'type': 'info',
            'icon': '📊',
            'text': f'Most common category: {top_category}'
        })
    
    return insights

def create_material_heatmap(events_df):
    """Create material score heatmap by country and category"""
    if events_df.empty:
        return None
    
    # Prepare data for heatmap - only use config categories
    heatmap_data = []
    for _, row in events_df.iterrows():
        if row['categories'] and row['material_score'] is not None:
            for category in row['categories']:
                if category in cfg.categories:  # Only include config categories
                    heatmap_data.append({
                        'country': row['initiating_country'],
                        'category': category,
                        'material_score': row['material_score']
                    })
    
    if not heatmap_data:
        return None
    
    heatmap_df = pd.DataFrame(heatmap_data)
    pivot_df = heatmap_df.groupby(['country', 'category'])['material_score'].mean().reset_index()
    
    fig = px.density_heatmap(
        pivot_df, 
        x='category', 
        y='country', 
        z='material_score',
        color_continuous_scale='RdYlBu_r',
        title='Average Material Score by Country and Category',
        labels={'material_score': 'Avg Material Score'}
    )
    
    fig.update_layout(
        height=400,
        xaxis_title='Category',
        yaxis_title='Initiating Country'
    )
    
    return fig

def create_timeline_chart(events_df):
    """Create interactive timeline of events"""
    if events_df.empty:
        return None
    
    # Daily aggregation
    daily_stats = events_df.groupby('report_date').agg({
        'material_score': 'mean',
        'event_name': 'count',
        'document_count': 'sum'
    }).reset_index()
    
    daily_stats.columns = ['date', 'avg_material_score', 'event_count', 'total_documents']
    
    # Create subplot
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=('Event Count Over Time', 'Average Material Score'),
        vertical_spacing=0.1
    )
    
    # Event count
    fig.add_trace(
        go.Scatter(
            x=daily_stats['date'],
            y=daily_stats['event_count'],
            mode='lines+markers',
            name='Event Count',
            line=dict(color=COLORS['primary'])
        ),
        row=1, col=1
    )
    
    # Material score
    fig.add_trace(
        go.Scatter(
            x=daily_stats['date'],
            y=daily_stats['avg_material_score'],
            mode='lines+markers',
            name='Avg Material Score',
            line=dict(color=COLORS['danger'])
        ),
        row=2, col=1
    )
    
    fig.update_layout(height=600, showlegend=True)
    fig.update_xaxes(title_text="Date", row=2, col=1)
    fig.update_yaxes(title_text="Count", row=1, col=1)
    fig.update_yaxes(title_text="Material Score", row=2, col=1)
    
    return fig

def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🌍 Global Event Analytics Platform</h1>
        <p>Real-time intelligence on international events and their material impact</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar filters
    with st.sidebar:
        st.header("🎛️ Dashboard Controls")
        
        # Date range
        earliest_date, latest_date = load_date_range()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "From",
                value=latest_date - timedelta(days=30),
                min_value=earliest_date,
                max_value=latest_date
            )
        with col2:
            end_date = st.date_input(
                "To", 
                value=latest_date,
                min_value=earliest_date,
                max_value=latest_date
            )
        
        # Country filter (from config)
        all_countries = load_countries()
        selected_countries = st.multiselect(
            "Initiating Countries",
            options=all_countries,
            default=all_countries,
            help="Select initiating countries to analyze"
        )
        
        # Recipient filter (from config)
        all_recipients = load_recipients()
        selected_recipients = st.multiselect(
            "Recipient Countries",
            options=all_recipients,
            default=all_recipients,
            help="Select recipient countries to analyze"
        )
        
        # Category filter (from config)
        all_categories = load_categories()
        selected_categories = st.multiselect(
            "Categories",
            options=all_categories,
            default=all_categories,
            help="Filter by event categories"
        )
        
        # Material threshold
        material_threshold = st.slider(
            "Material Score Threshold",
            min_value=0,
            max_value=10,
            value=0,
            help="Filter events by minimum material score"
        )
        
        # Data quality info
        st.markdown("---")
        st.markdown("**Data Quality Notes:**")
        st.caption("• Same-country events automatically excluded")
        st.caption("• Only configured countries/categories shown")
        st.caption(f"• Monitoring {len(all_countries)} influencer countries")
        st.caption(f"• Tracking {len(all_recipients)} recipient countries")
    
    # Load raw data first
    with st.spinner("Loading analytics data..."):
        raw_events_df, summary_df, error = load_raw_dashboard_data(start_date, end_date)
    
    if error:
        st.error(f"Error loading data: {error}")
        return
    
    if raw_events_df.empty:
        st.warning("No data available for the selected date range.")
        return
    
    # Apply configuration-based filtering
    filtered_events = filter_manager.filter_events_by_config(raw_events_df)
    
    # Generate data quality stats
    quality_stats = filter_manager.get_data_quality_stats(raw_events_df, filtered_events)
    
    # Additional user filtering
    if selected_countries and len(selected_countries) < len(all_countries):
        filtered_events = filtered_events[filtered_events['initiating_country'].isin(selected_countries)]
    
    if selected_recipients and len(selected_recipients) < len(all_recipients):
        def has_selected_recipient(row):
            recipients_list = row.get('recipient_countries', [])
            if not recipients_list:
                return False
            
            if isinstance(recipients_list, str):
                try:
                    import json
                    recipients_list = json.loads(recipients_list)
                except:
                    recipients_list = [recipients_list]
            
            return any(r in selected_recipients for r in recipients_list)
        
        filtered_events = filtered_events[filtered_events.apply(has_selected_recipient, axis=1)]
    
    if selected_categories and len(selected_categories) < len(all_categories):
        def has_selected_category(row):
            categories_list = row.get('categories', [])
            if not categories_list:
                return False
            
            if isinstance(categories_list, str):
                try:
                    import json
                    categories_list = json.loads(categories_list)
                except:
                    categories_list = [categories_list]
            
            return any(c in selected_categories for c in categories_list)
        
        filtered_events = filtered_events[filtered_events.apply(has_selected_category, axis=1)]
    
    # Apply material score filter
    if material_threshold > 0:
        filtered_events = filtered_events[
            (filtered_events['material_score'] >= material_threshold) | 
            (filtered_events['material_score'].isna())
        ]
    
    if filtered_events.empty:
        st.warning("No events match your current filters. Try:")
        st.info("• Expanding the date range")
        st.info("• Selecting different countries/recipients")
        st.info("• Lowering the material score threshold")
        
        # Show data quality info even when no results
        if quality_stats:
            st.markdown("### 📊 Data Quality Summary")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Raw Events", f"{quality_stats['total_events_raw']:,}")
            with col2:
                st.metric("After Config Filter", f"{quality_stats['total_events_filtered']:,}")
            with col3:
                st.metric("Same-Country Removed", f"{quality_stats['same_country_events_removed']:,}")
        return
    
    # Data Quality Sidebar
    with st.sidebar:
        if quality_stats:
            st.markdown("---")
            st.markdown("### 📊 Data Quality")
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    "Raw Events", 
                    f"{quality_stats['total_events_raw']:,}",
                    help="Total events in date range"
                )
            with col2:
                st.metric(
                    "Clean Events", 
                    f"{len(filtered_events):,}",
                    help="Events after all filtering"
                )
            
            if quality_stats['same_country_events_removed'] > 0:
                st.error(
                    f"🚫 {quality_stats['same_country_events_removed']:,} same-country events removed"
                )
            
            removal_pct = quality_stats['events_removed_pct']
            total_removed = quality_stats['total_events_raw'] - len(filtered_events)
            final_removal_pct = (total_removed / quality_stats['total_events_raw'] * 100) if quality_stats['total_events_raw'] > 0 else 0
            
            if final_removal_pct > 30:
                st.warning(f"⚠️ {final_removal_pct:.1f}% of events filtered out")
            elif final_removal_pct > 0:
                st.info(f"ℹ️ {final_removal_pct:.1f}% of events filtered out")
    
    # Configuration Summary
    st.markdown("### 🔧 Configuration Overview")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Influencer Countries",
            len(cfg.influencers),
            help="Countries monitored as event initiators"
        )
    
    with col2:
        st.metric(
            "Recipient Countries", 
            len(cfg.recipients),
            help="Countries monitored as event recipients"
        )
    
    with col3:
        st.metric(
            "Categories",
            len(cfg.categories),
            help="Event categories being tracked"
        )
    
    with col4:
        st.metric(
            "Subcategories",
            len(cfg.subcategories),
            help="Event subcategories being tracked"
        )
    
    # Key Metrics Row
    st.subheader("📊 Key Performance Indicators")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        total_events = len(filtered_events)
        st.metric("Total Events", f"{total_events:,}")
    
    with col2:
        total_docs = filtered_events['document_count'].sum()
        st.metric("Total Articles", f"{total_docs:,}")
    
    with col3:
        avg_material = filtered_events['material_score'].mean()
        st.metric("Avg Material Score", f"{avg_material:.1f}")
    
    with col4:
        material_events = len(filtered_events[filtered_events['material_score'] >= 7])
        st.metric("High Impact Events", f"{material_events}")
    
    with col5:
        unique_sources = filtered_events['unique_source_count'].sum()
        st.metric("Unique Sources", f"{unique_sources:,}")
    
    # Insights Section
    st.subheader("💡 Automated Insights")
    insights = generate_insights(filtered_events, summary_df)
    
    if insights:
        cols = st.columns(len(insights))
        for i, insight in enumerate(insights):
            with cols[i]:
                st.markdown(f"""
                <div class="insight-card">
                    <h4>{insight['icon']} {insight['type'].title()}</h4>
                    <p>{insight['text']}</p>
                </div>
                """, unsafe_allow_html=True)
    
    # Main Analytics Section
    tab1, tab2, tab3 = st.tabs(["📈 Trends & Patterns", "🔍 Deep Dive Analysis", "📋 Event Details"])
    
    with tab1:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Event Timeline")
            timeline_fig = create_timeline_chart(filtered_events)
            if timeline_fig:
                st.plotly_chart(timeline_fig, use_container_width=True)
        
        with col2:
            st.subheader("Top Categories")
            if not filtered_events.empty:
                # Category distribution - only show config categories
                categories = []
                for _, row in filtered_events.iterrows():
                    if row['categories']:
                        valid_categories = [c for c in row['categories'] if c in cfg.categories]
                        categories.extend(valid_categories)
                
                if categories:
                    cat_counts = pd.Series(categories).value_counts().head(10)
                    fig = px.bar(
                        x=cat_counts.values,
                        y=cat_counts.index,
                        orientation='h',
                        title='Event Categories',
                        color_discrete_sequence=[COLORS['primary']],
                        labels={'x': 'Event Count', 'y': 'Category'}
                    )
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No valid categories found in filtered data")
        
        # Recipient distribution
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Top Recipients")
            if not filtered_events.empty:
                # Recipient distribution - only show config recipients
                recipients = []
                for _, row in filtered_events.iterrows():
                    if row.get('recipient_countries'):
                        valid_recipients = [r for r in row['recipient_countries'] if r in cfg.recipients]
                        recipients.extend(valid_recipients)
                
                if recipients:
                    recip_counts = pd.Series(recipients).value_counts().head(10)
                    fig = px.bar(
                        x=recip_counts.values,
                        y=recip_counts.index,
                        orientation='h',
                        title='Recipient Countries',
                        color_discrete_sequence=[COLORS['success']],
                        labels={'x': 'Event Count', 'y': 'Recipient'}
                    )
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No valid recipients found in filtered data")
        
        with col2:
            st.subheader("Initiator Activity")
            if not filtered_events.empty:
                initiator_counts = filtered_events['initiating_country'].value_counts()
                fig = px.pie(
                    values=initiator_counts.values,
                    names=initiator_counts.index,
                    title='Events by Initiating Country',
                    color_discrete_sequence=px.colors.qualitative.Set3
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Material Impact Heatmap")
        heatmap_fig = create_material_heatmap(filtered_events)
        if heatmap_fig:
            st.plotly_chart(heatmap_fig, use_container_width=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Document Coverage Distribution")
            if not filtered_events.empty:
                fig = px.histogram(
                    filtered_events,
                    x='document_count',
                    nbins=20,
                    title='Events by Document Count',
                    color_discrete_sequence=[COLORS['secondary']]
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("Material Score Distribution")
            if not filtered_events.empty:
                fig = px.histogram(
                    filtered_events,
                    x='material_score',
                    nbins=11,
                    title='Events by Material Score',
                    color_discrete_sequence=[COLORS['success']]
                )
                st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("Event Details")
        
        # Search and sort options
        col1, col2 = st.columns([3, 1])
        with col1:
            search_term = st.text_input("Search events", placeholder="Enter keywords...")
        with col2:
            sort_by = st.selectbox("Sort by", ["material_score", "document_count", "report_date"])
        
        # Filter events by search term
        display_events = filtered_events.copy()
        if search_term:
            mask = display_events['event_name'].str.contains(search_term, case=False, na=False)
            display_events = display_events[mask]
        
        # Sort events
        display_events = display_events.sort_values(sort_by, ascending=False)
        
        # Pagination
        page_size = 10
        total_pages = len(display_events) // page_size + (1 if len(display_events) % page_size > 0 else 0)
        
        if total_pages > 1:
            page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            display_events = display_events.iloc[start_idx:end_idx]
        
        # Display events
        for _, event in display_events.iterrows():
            with st.expander(f"{event['event_name']} (Score: {event['material_score']})"):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.write("**Summary:**")
                    st.write(event.get('summary_text', 'No summary available'))
                    
                    if event.get('material_score_justification'):
                        st.write("**Justification:**")
                        st.write(event['material_score_justification'])
                
                with col2:
                    st.metric("Documents", event['document_count'])
                    st.metric("Sources", event['unique_source_count'])
                    
                    if event.get('categories'):
                        st.write("**Categories:**")
                        # Only show config categories
                        valid_categories = [c for c in event['categories'] if c in cfg.categories]
                        for cat in valid_categories:
                            st.markdown(f"`{cat}`")
                    
                    if event.get('recipient_countries'):
                        st.write("**Recipients:**")
                        # Only show config recipients
                        valid_recipients = [r for r in event['recipient_countries'] if r in cfg.recipients]
                        for recip in valid_recipients:
                            st.markdown(f"`{recip}`")
    
    # Footer
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(f"📅 Data range: {start_date} to {end_date}")
    with col2:
        st.caption(f"🔄 Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with col3:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()

if __name__ == "__main__":
    main()