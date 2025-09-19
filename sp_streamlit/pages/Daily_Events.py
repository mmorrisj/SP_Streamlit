import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import json
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import networkx as nx

from backend.scripts.models import DailySummary, DailyEventSummary
from backend.app import create_app
from backend.extensions import db
from backend.scripts.utils import Config

# Load configuration
cfg = Config.from_yaml()

# --- DB SETUP --- (Your exact pattern)
app = create_app()
ctx = app.app_context()
ctx.push()

st.set_page_config(
    page_title="Event Analytics Platform",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Professional styling with dark theme support
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 2.5rem;
        border-radius: 15px;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    }
    .metric-container {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1.5rem;
        border-radius: 12px;
        margin: 0.5rem 0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .insight-alert {
        background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #ff6b6b;
        margin: 0.5rem 0;
    }
    .config-card {
        background: linear-gradient(135deg, #e3ffe7 0%, #d9e7ff 100%);
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .anomaly-highlight {
        background: #ffebee;
        border: 2px solid #f44336;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Advanced Analytics Functions

def detect_anomalies(events_df, sensitivity=2.0):
    """Detect anomalous events using statistical methods"""
    if events_df.empty:
        return pd.DataFrame()
    
    # Daily aggregation
    daily_stats = events_df.groupby('report_date').agg({
        'material_score': lambda x: x.dropna().mean() if not x.dropna().empty else 0,
        'event_name': 'count',
        'document_count': 'sum'
    }).reset_index()
    
    daily_stats.columns = ['date', 'avg_score', 'event_count', 'total_docs']
    
    if len(daily_stats) < 7:
        return pd.DataFrame()
    
    # Rolling statistics for anomaly detection
    window = min(7, len(daily_stats) // 2)
    daily_stats['rolling_mean'] = daily_stats['avg_score'].rolling(window=window, center=True).mean()
    daily_stats['rolling_std'] = daily_stats['avg_score'].rolling(window=window, center=True).std()
    
    # Z-score based anomaly detection
    daily_stats['z_score'] = (daily_stats['avg_score'] - daily_stats['rolling_mean']) / daily_stats['rolling_std']
    daily_stats['is_anomaly'] = np.abs(daily_stats['z_score']) > sensitivity
    
    # Volume anomalies
    daily_stats['vol_rolling_mean'] = daily_stats['event_count'].rolling(window=window, center=True).mean()
    daily_stats['vol_rolling_std'] = daily_stats['event_count'].rolling(window=window, center=True).std()
    daily_stats['vol_z_score'] = (daily_stats['event_count'] - daily_stats['vol_rolling_mean']) / daily_stats['vol_rolling_std']
    daily_stats['is_volume_anomaly'] = np.abs(daily_stats['vol_z_score']) > sensitivity
    
    # Return anomalous days
    anomalies = daily_stats[
        (daily_stats['is_anomaly'] == True) | 
        (daily_stats['is_volume_anomaly'] == True)
    ].copy()
    
    return anomalies.dropna()

def cluster_events(events_df, n_clusters=4):
    """Cluster events based on material score, document coverage, and source diversity"""
    if len(events_df) < n_clusters:
        return events_df
    
    # Feature engineering
    features_df = events_df[['material_score', 'document_count', 'unique_source_count']].copy()
    features_df = features_df.dropna()
    
    if len(features_df) < n_clusters:
        return events_df
    
    # Standardize features
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features_df)
    
    # K-means clustering
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(features_scaled)
    
    # Add cluster labels back to dataframe
    events_clustered = events_df.copy()
    events_clustered.loc[features_df.index, 'cluster'] = clusters
    
    # Define cluster characteristics
    cluster_names = {
        0: "High Impact, High Coverage",
        1: "Medium Impact, Broad Coverage", 
        2: "Low Impact, Focused Coverage",
        3: "Emerging Events"
    }
    
    events_clustered['cluster_name'] = events_clustered['cluster'].map(cluster_names)
    
    return events_clustered

def create_network_graph(events_df):
    """Create network visualization of country relationships"""
    if events_df.empty:
        return None
    
    # Build edges between initiators and recipients
    edges = []
    for _, event in events_df.iterrows():
        initiator = event['initiating_country']
        recipients = event.get('recipient_countries', [])
        
        if isinstance(recipients, str):
            try:
                recipients = json.loads(recipients)
            except:
                recipients = [recipients]
        
        # Only include config recipients
        valid_recipients = [r for r in recipients if r in cfg.recipients]
        
        for recipient in valid_recipients:
            edges.append({
                'source': initiator,
                'target': recipient,
                'weight': event.get('material_score', 0),
                'documents': event.get('document_count', 0)
            })
    
    if not edges:
        return None
    
    # Aggregate edges
    edge_df = pd.DataFrame(edges)
    network_df = edge_df.groupby(['source', 'target']).agg({
        'weight': 'mean',
        'documents': 'sum'
    }).reset_index()
    
    # Create network using NetworkX
    G = nx.from_pandas_edgelist(
        network_df, 
        source='source', 
        target='target', 
        edge_attr=['weight', 'documents'],
        create_using=nx.DiGraph()
    )
    
    # Calculate positions using spring layout
    pos = nx.spring_layout(G, k=3, iterations=50, seed=42)
    
    # Prepare edge traces
    edge_x = []
    edge_y = []
    edge_weights = []
    
    for edge in G.edges(data=True):
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
        edge_weights.append(edge[2]['weight'])
    
    # Prepare node traces
    node_x = []
    node_y = []
    node_text = []
    node_sizes = []
    node_colors = []
    
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)
        
        # Node size based on degree centrality
        degree = G.degree(node)
        node_sizes.append(max(20, degree * 5))
        
        # Color based on whether it's an influencer or recipient
        if node in cfg.influencers:
            node_colors.append('#ff6b6b')  # Red for influencers
        else:
            node_colors.append('#4ecdc4')  # Teal for recipients
    
    # Create plotly figure
    fig = go.Figure()
    
    # Add edges
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=1, color='rgba(125,125,125,0.5)'),
        hoverinfo='none',
        mode='lines',
        name='Relationships'
    ))
    
    # Add nodes
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y,
        mode='markers+text',
        hoverinfo='text',
        text=node_text,
        textposition='middle center',
        marker=dict(
            size=node_sizes,
            color=node_colors,
            line=dict(width=2, color='white'),
            sizemode='diameter'
        ),
        name='Countries'
    ))
    
    fig.update_layout(
        title=dict(
            text='Country Interaction Network (Red=Initiators, Teal=Recipients)',
            font=dict(size=16)
        ),
        showlegend=False,
        hovermode='closest',
        margin=dict(b=20, l=5, r=5, t=40),
        annotations=[dict(
            text="Node size = interaction frequency | Click and drag to explore",
            showarrow=False,
            xref="paper", yref="paper",
            x=0.005, y=-0.002,
            xanchor='left', yanchor='bottom',
            font=dict(color='#888', size=12)
        )],
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=500
    )
    
    return fig

def create_anomaly_timeline(events_df, anomalies_df):
    """Create anomaly detection visualization"""
    if events_df.empty:
        return None
    
    daily_stats = events_df.groupby('report_date').agg({
        'material_score': lambda x: x.dropna().mean() if not x.dropna().empty else 0,
        'event_name': 'count'
    }).reset_index()
    daily_stats.columns = ['date', 'avg_material_score', 'event_count']
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=('Material Score Anomalies', 'Event Volume Anomalies'),
        vertical_spacing=0.15
    )
    
    # Material score timeline
    fig.add_trace(
        go.Scatter(
            x=daily_stats['date'],
            y=daily_stats['avg_material_score'],
            mode='lines',
            name='Material Score',
            line=dict(color='#1f77b4', width=2)
        ),
        row=1, col=1
    )
    
    # Event count timeline
    fig.add_trace(
        go.Scatter(
            x=daily_stats['date'],
            y=daily_stats['event_count'],
            mode='lines',
            name='Event Count',
            line=dict(color='#ff7f0e', width=2)
        ),
        row=2, col=1
    )
    
    # Add anomaly markers
    if not anomalies_df.empty:
        # Material score anomalies
        score_anomalies = anomalies_df[anomalies_df['is_anomaly'] == True]
        if not score_anomalies.empty:
            fig.add_trace(
                go.Scatter(
                    x=score_anomalies['date'],
                    y=score_anomalies['avg_score'],
                    mode='markers',
                    name='Score Anomalies',
                    marker=dict(color='red', size=12, symbol='diamond'),
                    hovertemplate='<b>Anomaly Detected</b><br>Date: %{x}<br>Score: %{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )
        
        # Volume anomalies
        volume_anomalies = anomalies_df[anomalies_df['is_volume_anomaly'] == True]
        if not volume_anomalies.empty:
            fig.add_trace(
                go.Scatter(
                    x=volume_anomalies['date'],
                    y=volume_anomalies['event_count'],
                    mode='markers',
                    name='Volume Anomalies',
                    marker=dict(color='red', size=12, symbol='diamond'),
                    hovertemplate='<b>Volume Spike</b><br>Date: %{x}<br>Events: %{y}<extra></extra>'
                ),
                row=2, col=1
            )
    
    fig.update_layout(height=600, showlegend=True, title_text="Anomaly Detection Analysis")
    fig.update_xaxes(title_text="Date", row=2, col=1)
    fig.update_yaxes(title_text="Material Score", row=1, col=1)
    fig.update_yaxes(title_text="Event Count", row=2, col=1)
    
    return fig

def create_cluster_visualization(events_df):
    """Create 3D scatter plot of event clusters"""
    clustered_df = cluster_events(events_df)
    
    if 'cluster' not in clustered_df.columns:
        return None
    
    clean_df = clustered_df.dropna(subset=['material_score', 'document_count', 'unique_source_count'])
    
    if clean_df.empty:
        return None
    
    fig = px.scatter_3d(
        clean_df,
        x='material_score',
        y='document_count', 
        z='unique_source_count',
        color='cluster_name',
        hover_data=['event_name', 'initiating_country'],
        title='Event Clustering Analysis (3D)',
        labels={
            'material_score': 'Material Score',
            'document_count': 'Document Count',
            'unique_source_count': 'Unique Sources'
        },
        color_discrete_sequence=['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4']
    )
    
    fig.update_layout(height=600)
    return fig

def create_material_distribution_analysis(events_df):
    """Create comprehensive material score distribution analysis"""
    if events_df.empty:
        return None
    
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Score Distribution', 'Score by Country', 'Score Trends', 'Impact Categories'),
        specs=[[{"type": "histogram"}, {"type": "box"}],
               [{"type": "scatter"}, {"type": "bar"}]]
    )
    
    # 1. Score distribution histogram
    fig.add_trace(
        go.Histogram(
            x=events_df['material_score'].dropna(),
            nbinsx=20,
            name='Score Distribution',
            marker_color='#ff6b6b'
        ),
        row=1, col=1
    )
    
    # 2. Box plot by country
    countries_with_data = events_df.groupby('initiating_country')['material_score'].count()
    top_countries = countries_with_data.nlargest(5).index
    
    for i, country in enumerate(top_countries):
        country_scores = events_df[events_df['initiating_country'] == country]['material_score'].dropna()
        if not country_scores.empty:
            fig.add_trace(
                go.Box(
                    y=country_scores,
                    name=country,
                    showlegend=False
                ),
                row=1, col=2
            )
    
    # 3. Score trends over time
    daily_trends = events_df.groupby('report_date')['material_score'].mean().reset_index()
    fig.add_trace(
        go.Scatter(
            x=daily_trends['report_date'],
            y=daily_trends['material_score'],
            mode='lines+markers',
            name='Daily Average',
            line=dict(color='#4ecdc4', width=3)
        ),
        row=2, col=1
    )
    
    # 4. Impact categories
    score_ranges = ['Low (0-3)', 'Medium (4-6)', 'High (7-10)']
    score_counts = [
        len(events_df[(events_df['material_score'] >= 0) & (events_df['material_score'] <= 3)]),
        len(events_df[(events_df['material_score'] >= 4) & (events_df['material_score'] <= 6)]),
        len(events_df[(events_df['material_score'] >= 7) & (events_df['material_score'] <= 10)])
    ]
    
    fig.add_trace(
        go.Bar(
            x=score_ranges,
            y=score_counts,
            name='Impact Categories',
            marker_color=['#96ceb4', '#feca57', '#ff6b6b']
        ),
        row=2, col=2
    )
    
    fig.update_layout(height=700, showlegend=False, title_text="Material Score Deep Dive Analysis")
    return fig

def generate_advanced_insights(events_df, anomalies_df):
    """Generate sophisticated insights with statistical analysis"""
    insights = []
    
    if events_df.empty:
        return ["No events available for analysis"]
    
    # Anomaly insights
    if not anomalies_df.empty:
        recent_anomalies = anomalies_df[anomalies_df['date'] >= (datetime.now().date() - timedelta(days=7))]
        if not recent_anomalies.empty:
            insights.append({
                'type': 'warning',
                'icon': '🚨',
                'title': 'Recent Anomalies Detected',
                'text': f'{len(recent_anomalies)} unusual patterns detected in the last 7 days'
            })
    
    # Clustering insights
    clustered_df = cluster_events(events_df)
    if 'cluster' in clustered_df.columns:
        cluster_counts = clustered_df['cluster'].value_counts()
        dominant_cluster = cluster_counts.index[0]
        cluster_names = {0: "High Impact", 1: "Broad Coverage", 2: "Focused", 3: "Emerging"}
        insights.append({
            'type': 'info',
            'icon': '🎯',
            'title': 'Event Clustering',
            'text': f'Most events fall into {cluster_names.get(dominant_cluster, "Unknown")} category ({cluster_counts.iloc[0]} events)'
        })
    
    # Trend analysis
    recent_week = events_df[events_df['report_date'] >= (datetime.now().date() - timedelta(days=7))]
    previous_week = events_df[
        (events_df['report_date'] >= (datetime.now().date() - timedelta(days=14))) &
        (events_df['report_date'] < (datetime.now().date() - timedelta(days=7)))
    ]
    
    if not recent_week.empty and not previous_week.empty:
        recent_avg = recent_week['material_score'].mean()
        previous_avg = previous_week['material_score'].mean()
        
        if recent_avg > previous_avg * 1.2:
            insights.append({
                'type': 'danger',
                'icon': '📈',
                'title': 'Escalating Tensions',
                'text': f'Material scores increased {((recent_avg/previous_avg-1)*100):.0f}% week-over-week'
            })
        elif recent_avg < previous_avg * 0.8:
            insights.append({
                'type': 'success',
                'icon': '📉',
                'title': 'De-escalation Trend',
                'text': f'Material scores decreased {((1-recent_avg/previous_avg)*100):.0f}% week-over-week'
            })
    
    # Network insights
    unique_initiators = events_df['initiating_country'].nunique()
    all_recipients = []
    for _, row in events_df.iterrows():
        recipients = row.get('recipient_countries', [])
        if isinstance(recipients, str):
            try:
                recipients = json.loads(recipients)
            except:
                recipients = [recipients]
        all_recipients.extend([r for r in recipients if r in cfg.recipients])
    
    unique_recipients = len(set(all_recipients))
    
    if unique_initiators > 0 and unique_recipients > 0:
        network_density = len(events_df) / (unique_initiators * unique_recipients) * 100
        insights.append({
            'type': 'info',
            'icon': '🌐',
            'title': 'Network Analysis',
            'text': f'Network density: {network_density:.1f}% ({unique_initiators} initiators → {unique_recipients} recipients)'
        })
    
    return insights
def filter_same_country_events(events_df):
    """Remove events where initiator appears in recipient list"""
    if events_df.empty:
        return events_df
    
    def is_valid_event(row):
        initiator = row['initiating_country']
        recipients = row.get('recipient_countries', [])
        
        if not recipients:
            return True
        
        if isinstance(recipients, str):
            try:
                recipients = json.loads(recipients)
            except:
                recipients = [recipients]
        
        return initiator not in recipients
    
    return events_df[events_df.apply(is_valid_event, axis=1)]

def filter_to_config_recipients(events_df):
    """Keep only events with valid recipient countries from config"""
    if events_df.empty:
        return events_df
    
    def has_valid_recipient(row):
        recipients = row.get('recipient_countries', [])
        if not recipients:
            return False
        
        if isinstance(recipients, str):
            try:
                recipients = json.loads(recipients)
            except:
                recipients = [recipients]
        
        return any(r in cfg.recipients for r in recipients)
    
    return events_df[events_df.apply(has_valid_recipient, axis=1)]

def filter_to_config_categories(events_df):
    """Keep events with valid categories from config"""
    if events_df.empty:
        return events_df
        
    def has_valid_category(row):
        categories = row.get('categories', [])
        if not categories:
            return True
        
        if isinstance(categories, str):
            try:
                categories = json.loads(categories)
            except:
                categories = [categories]
        
        return any(c in cfg.categories for c in categories)
    
    return events_df[events_df.apply(has_valid_category, axis=1)]

# Data loading functions - KEY FIX: Remove @st.cache_data decorator
def load_date_range():
    """Get available date range"""
    try:
        latest_date = db.session.query(func.max(DailyEventSummary.report_date)).scalar()
        earliest_date = db.session.query(func.min(DailyEventSummary.report_date)).scalar()
        return earliest_date or datetime(2024, 1, 1).date(), latest_date or datetime.now().date()
    except Exception as e:
        st.error(f"Error loading date range: {e}")
        return datetime(2024, 1, 1).date(), datetime.now().date()

def load_events_data(start_date, end_date):
    """Load and filter events data"""
    try:
        # Load raw events
        query = db.session.query(DailyEventSummary).filter(
            DailyEventSummary.report_date.between(start_date, end_date)
        )
        
        raw_events_df = pd.read_sql(query.statement, db.engine)
        
        if raw_events_df.empty:
            return raw_events_df, {}
        
        # Apply configuration filtering
        events_df = raw_events_df.copy()
        
        # Filter to config influencers only
        events_df = events_df[events_df['initiating_country'].isin(cfg.influencers)]
        
        # Remove same-country events
        before_same_country = len(events_df)
        filtered_events = filter_same_country_events(events_df)
        same_country_removed = before_same_country - len(filtered_events)
        
        # Filter to config recipients
        filtered_events = filter_to_config_recipients(filtered_events)
        
        # Filter to config categories
        filtered_events = filter_to_config_categories(filtered_events)
        
        # Calculate stats
        quality_stats = {
            'total_raw': len(raw_events_df),
            'after_influencer_filter': len(events_df),
            'same_country_removed': same_country_removed,
            'final_events': len(filtered_events),
            'removal_pct': ((len(raw_events_df) - len(filtered_events)) / len(raw_events_df) * 100) if len(raw_events_df) > 0 else 0
        }
        
        return filtered_events, quality_stats
        
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame(), {}

def create_material_timeline(events_df):
    """Create timeline chart"""
    if events_df.empty:
        return None
    
    daily_stats = events_df.groupby('report_date').agg({
        'material_score': lambda x: x.dropna().mean() if not x.dropna().empty else 0,
        'event_name': 'count',
        'document_count': 'sum'
    }).reset_index()
    
    daily_stats.columns = ['date', 'avg_material_score', 'event_count', 'total_documents']
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=('Daily Event Count', 'Average Material Score'),
        vertical_spacing=0.1
    )
    
    fig.add_trace(
        go.Scatter(
            x=daily_stats['date'],
            y=daily_stats['event_count'],
            mode='lines+markers',
            name='Event Count',
            line=dict(color='#1f77b4')
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=daily_stats['date'],
            y=daily_stats['avg_material_score'],
            mode='lines+markers',
            name='Avg Material Score',
            line=dict(color='#d62728')
        ),
        row=2, col=1
    )
    
    fig.update_layout(height=500, showlegend=True)
    fig.update_xaxes(title_text="Date", row=2, col=1)
    fig.update_yaxes(title_text="Count", row=1, col=1)
    fig.update_yaxes(title_text="Material Score", row=2, col=1)
    
    return fig

def generate_insights(events_df, quality_stats):
    """Generate insights"""
    insights = []
    
    if events_df.empty:
        return ["No events found for selected filters"]
    
    # Most active initiator
    top_initiator = events_df['initiating_country'].value_counts()
    if len(top_initiator) > 0:
        insights.append(f"🎯 Most active: {top_initiator.index[0]} ({top_initiator.iloc[0]} events)")
    
    # High material events
    high_material = events_df[events_df['material_score'] >= 7]
    if len(high_material) > 0:
        insights.append(f"🔥 {len(high_material)} high-impact events (score ≥7)")
    
    # Data quality
    if quality_stats.get('same_country_removed', 0) > 0:
        insights.append(f"✅ Filtered {quality_stats['same_country_removed']} same-country events")
    
    return insights

def main():
    # Header with enhanced styling
    st.markdown("""
    <div class="main-header">
        <h1>🌍 Advanced Global Event Analytics Platform</h1>
        <p>AI-powered intelligence on international events with anomaly detection, clustering & network analysis</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar with advanced controls
    with st.sidebar:
        st.header("🎛️ Advanced Analytics Controls")
        
        # Date range
        earliest_date, latest_date = load_date_range()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("From", value=latest_date - timedelta(days=30))
        with col2:
            end_date = st.date_input("To", value=latest_date)
        
        # Country filters
        selected_countries = st.multiselect(
            "Initiating Countries",
            options=cfg.influencers,
            default=cfg.influencers,
            help="Select countries to monitor"
        )
        
        selected_recipients = st.multiselect(
            "Recipient Countries",
            options=cfg.recipients,
            default=cfg.recipients,
            help="Select recipient countries"
        )
        
        # Material threshold
        material_threshold = st.slider(
            "Material Score Threshold",
            min_value=0,
            max_value=10,
            value=0,
            help="Minimum material score"
        )
        
        # Advanced analytics controls
        st.markdown("---")
        st.subheader("🔬 Advanced Analytics")
        
        anomaly_sensitivity = st.slider(
            "Anomaly Detection Sensitivity",
            min_value=1.0,
            max_value=3.0,
            value=2.0,
            step=0.1,
            help="Lower = more sensitive to anomalies"
        )
        
        cluster_count = st.slider(
            "Event Clusters",
            min_value=3,
            max_value=6,
            value=4,
            help="Number of clusters for event analysis"
        )
        
        show_network = st.checkbox("Show Network Analysis", value=True)
        show_clustering = st.checkbox("Show Event Clustering", value=True)
        show_anomalies = st.checkbox("Show Anomaly Detection", value=True)
    
    # Load data
    with st.spinner("Loading analytics data..."):
        events_df, quality_stats = load_events_data(start_date, end_date)
    
    if events_df.empty:
        st.warning("No data available for selected date range")
        return
    
    # Apply user filters
    if selected_countries and len(selected_countries) < len(cfg.influencers):
        events_df = events_df[events_df['initiating_country'].isin(selected_countries)]
    
    if selected_recipients and len(selected_recipients) < len(cfg.recipients):
        def has_selected_recipient(row):
            recipients = row.get('recipient_countries', [])
            if not recipients:
                return False
            if isinstance(recipients, str):
                try:
                    recipients = json.loads(recipients)
                except:
                    recipients = [recipients]
            return any(r in selected_recipients for r in recipients)
        
        events_df = events_df[events_df.apply(has_selected_recipient, axis=1)]
    
    if material_threshold > 0:
        events_df = events_df[
            (events_df['material_score'] >= material_threshold) | 
            (events_df['material_score'].isna())
        ]
    
    if events_df.empty:
        st.warning("No events match your current filters")
        return
    
    # Run advanced analytics
    anomalies_df = detect_anomalies(events_df, anomaly_sensitivity) if show_anomalies else pd.DataFrame()
    
    # Data quality sidebar
    if quality_stats:
        with st.sidebar:
            st.markdown("---")
            st.markdown("### 📊 Data Quality")
            st.metric("Raw Events", f"{quality_stats['total_raw']:,}")
            st.metric("Final Events", f"{len(events_df):,}")
            
            if quality_stats['same_country_removed'] > 0:
                st.error(f"🚫 {quality_stats['same_country_removed']} same-country events removed")
            
            if not anomalies_df.empty:
                st.warning(f"⚠️ {len(anomalies_df)} anomalous days detected")
    
    # Configuration overview with enhanced styling
    st.subheader("🔧 Configuration Overview")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
        <div class="config-card">
            <h3>{}</h3>
            <p>Influencer Countries</p>
        </div>
        """.format(len(cfg.influencers)), unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="config-card">
            <h3>{}</h3>
            <p>Recipient Countries</p>
        </div>
        """.format(len(cfg.recipients)), unsafe_allow_html=True)
    
    with col3:
        st.markdown("""
        <div class="config-card">
            <h3>{}</h3>
            <p>Categories</p>
        </div>
        """.format(len(cfg.categories)), unsafe_allow_html=True)
    
    with col4:
        st.markdown("""
        <div class="config-card">
            <h3>{}</h3>
            <p>Subcategories</p>
        </div>
        """.format(len(cfg.subcategories)), unsafe_allow_html=True)
    
    # Key metrics with enhanced styling
    st.subheader("📊 Key Performance Indicators")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
        <div class="metric-container">
            <h2>{:,}</h2>
            <p>Total Events</p>
        </div>
        """.format(len(events_df)), unsafe_allow_html=True)
    
    with col2:
        total_docs = events_df['document_count'].sum()
        st.markdown("""
        <div class="metric-container">
            <h2>{:,}</h2>
            <p>Total Articles</p>
        </div>
        """.format(total_docs), unsafe_allow_html=True)
    
    with col3:
        avg_score = events_df['material_score'].dropna().mean() if not events_df['material_score'].dropna().empty else 0
        st.markdown("""
        <div class="metric-container">
            <h2>{:.1f}</h2>
            <p>Avg Material Score</p>
        </div>
        """.format(avg_score), unsafe_allow_html=True)
    
    with col4:
        high_impact = len(events_df[events_df['material_score'] >= 7])
        st.markdown("""
        <div class="metric-container">
            <h2>{}</h2>
            <p>High Impact Events</p>
        </div>
        """.format(high_impact), unsafe_allow_html=True)
    
    # Advanced Insights with sophisticated analysis
    st.subheader("🧠 AI-Powered Insights")
    insights = generate_advanced_insights(events_df, anomalies_df)
    
    if insights:
        cols = st.columns(min(len(insights), 3))
        for i, insight in enumerate(insights):
            with cols[i % 3]:
                insight_type = insight.get('type', 'info')
                if insight_type == 'warning':
                    st.markdown(f"""
                    <div class="insight-alert">
                        <h4>{insight['icon']} {insight['title']}</h4>
                        <p>{insight['text']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                elif insight_type == 'danger':
                    st.markdown(f"""
                    <div class="anomaly-highlight">
                        <h4>{insight['icon']} {insight['title']}</h4>
                        <p>{insight['text']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.info(f"{insight['icon']} **{insight['title']}**: {insight['text']}")
    
    # Main Analytics Tabs with Advanced Features
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 Temporal Analysis", 
        "🔍 Anomaly Detection", 
        "🎯 Event Clustering", 
        "🌐 Network Analysis", 
        "📋 Event Intelligence"
    ])
    
    with tab1:
        st.subheader("Timeline Analysis & Material Score Trends")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            timeline_fig = create_material_timeline(events_df)
            if timeline_fig:
                st.plotly_chart(timeline_fig, use_container_width=True)
        
        with col2:
            # Material distribution analysis
            material_dist_fig = create_material_distribution_analysis(events_df)
            if material_dist_fig:
                st.plotly_chart(material_dist_fig, use_container_width=True)
    
    with tab2:
        if show_anomalies:
            st.subheader("Anomaly Detection & Pattern Recognition")
            
            if not anomalies_df.empty:
                st.success(f"🎯 Detected {len(anomalies_df)} anomalous days using statistical analysis")
                
                anomaly_fig = create_anomaly_timeline(events_df, anomalies_df)
                if anomaly_fig:
                    st.plotly_chart(anomaly_fig, use_container_width=True)
                
                # Anomaly details
                st.subheader("📋 Anomaly Details")
                for _, anomaly in anomalies_df.head(5).iterrows():
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Date", anomaly['date'].strftime('%Y-%m-%d'))
                    with col2:
                        if anomaly.get('is_anomaly'):
                            st.metric("Material Score", f"{anomaly['avg_score']:.2f}", 
                                     delta=f"Z-score: {anomaly['z_score']:.2f}")
                    with col3:
                        if anomaly.get('is_volume_anomaly'):
                            st.metric("Event Count", f"{anomaly['event_count']}", 
                                     delta=f"Z-score: {anomaly['vol_z_score']:.2f}")
            else:
                st.info("No anomalies detected with current sensitivity settings. Try lowering the sensitivity threshold.")
        else:
            st.info("Anomaly detection is disabled. Enable it in the sidebar to see advanced pattern recognition.")
    
    with tab3:
        if show_clustering:
            st.subheader("Event Clustering & Classification")
            
            cluster_fig = create_cluster_visualization(events_df)
            if cluster_fig:
                st.plotly_chart(cluster_fig, use_container_width=True)
                
                # Cluster analysis
                clustered_df = cluster_events(events_df, cluster_count)
                if 'cluster' in clustered_df.columns:
                    st.subheader("📊 Cluster Characteristics")
                    cluster_summary = clustered_df.groupby('cluster_name').agg({
                        'material_score': ['mean', 'count'],
                        'document_count': 'mean',
                        'unique_source_count': 'mean'
                    }).round(2)
                    
                    cluster_summary.columns = ['Avg Material Score', 'Event Count', 'Avg Documents', 'Avg Sources']
                    st.dataframe(cluster_summary, use_container_width=True)
            else:
                st.info("Insufficient data for clustering analysis. Need more events with complete material scores.")
        else:
            st.info("Event clustering is disabled. Enable it in the sidebar to see ML-powered event classification.")
    
    with tab4:
        if show_network:
            st.subheader("Country Interaction Network Analysis")
            
            network_fig = create_network_graph(events_df)
            if network_fig:
                st.plotly_chart(network_fig, use_container_width=True)
                
                # Network statistics
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("🎯 Top Initiators")
                    initiator_counts = events_df['initiating_country'].value_counts().head(10)
                    fig = px.bar(
                        x=initiator_counts.values,
                        y=initiator_counts.index,
                        orientation='h',
                        title='Most Active Countries',
                        color_discrete_sequence=['#ff6b6b']
                    )
                    fig.update_layout(height=400)
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.subheader("🌍 Top Recipients")
                    all_recipients = []
                    for _, row in events_df.iterrows():
                        recipients = row.get('recipient_countries', [])
                        if isinstance(recipients, str):
                            try:
                                recipients = json.loads(recipients)
                            except:
                                recipients = [recipients]
                        valid_recipients = [r for r in recipients if r in cfg.recipients]
                        all_recipients.extend(valid_recipients)
                    
                    if all_recipients:
                        recip_counts = pd.Series(all_recipients).value_counts().head(10)
                        fig = px.bar(
                            x=recip_counts.values,
                            y=recip_counts.index,
                            orientation='h',
                            title='Most Targeted Countries',
                            color_discrete_sequence=['#4ecdc4']
                        )
                        fig.update_layout(height=400)
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No valid country relationships found for network analysis.")
        else:
            st.info("Network analysis is disabled. Enable it in the sidebar to see country interaction patterns.")
    
    with tab5:
        st.subheader("Event Intelligence & Details")
        
        # Advanced search and filtering
        col1, col2, col3 = st.columns(3)
        with col1:
            search_term = st.text_input("🔍 Search events", placeholder="Enter keywords...")
        with col2:
            sort_by = st.selectbox("📊 Sort by", ["material_score", "document_count", "report_date", "unique_source_count"])
        with col3:
            view_mode = st.selectbox("👁️ View mode", ["Summary", "Detailed", "Table"])
        
        # Filter events by search term
        display_events = events_df.copy()
        if search_term:
            mask = display_events['event_name'].str.contains(search_term, case=False, na=False)
            display_events = display_events[mask]
        
        # Sort events
        display_events = display_events.sort_values(sort_by, ascending=False, na_position='last')
        
        if view_mode == "Table":
            # Table view
            table_df = display_events[['event_name', 'initiating_country', 'material_score', 'document_count', 'report_date']].head(50)
            st.dataframe(table_df, use_container_width=True)
        
        elif view_mode == "Summary":
            # Summary cards
            for _, event in display_events.head(20).iterrows():
                with st.expander(f"📰 {event['event_name']} (Score: {event.get('material_score', 'N/A')})"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.caption(f"📅 {event['report_date']} | 🌍 {event['initiating_country']}")
                        summary_text = event.get('summary_text', 'No summary available')
                        if len(summary_text) > 300:
                            summary_text = summary_text[:300] + "..."
                        st.write(summary_text)
                    
                    with col2:
                        material_score = event.get('material_score')
                        if material_score is not None:
                            st.metric("Material Score", f"{material_score:.1f}")
                        else:
                            st.metric("Material Score", "N/A")
                        st.metric("Documents", event.get('document_count', 0))
                        st.metric("Sources", event.get('unique_source_count', 0))
        
        else:
            # Detailed view
            for _, event in display_events.head(10).iterrows():
                st.markdown("---")
                st.subheader(f"📰 {event['event_name']}")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.info(f"📅 **Date:** {event['report_date']}")
                with col2:
                    st.info(f"🌍 **Initiator:** {event['initiating_country']}")
                with col3:
                    material_score = event.get('material_score')
                    if material_score is not None:
                        st.info(f"⚡ **Material Score:** {material_score:.1f}/10")
                    else:
                        st.info("⚡ **Material Score:** N/A")
                
                # Summary
                if event.get('summary_text'):
                    st.write("**📄 Summary:**")
                    st.write(event['summary_text'])
                
                # Justification
                if event.get('material_score_justification'):
                    st.write("**🎯 Material Score Justification:**")
                    st.write(event['material_score_justification'])
                
                # Categories and recipients
                col1, col2 = st.columns(2)
                with col1:
                    if event.get('categories'):
                        categories = event['categories']
                        if isinstance(categories, str):
                            try:
                                categories = json.loads(categories)
                            except:
                                categories = [categories]
                        valid_categories = [c for c in categories if c in cfg.categories]
                        if valid_categories:
                            st.write("**📋 Categories:**")
                            for cat in valid_categories:
                                st.code(cat)
                
                with col2:
                    if event.get('recipient_countries'):
                        recipients = event['recipient_countries']
                        if isinstance(recipients, str):
                            try:
                                recipients = json.loads(recipients)
                            except:
                                recipients = [recipients]
                        valid_recipients = [r for r in recipients if r in cfg.recipients]
                        if valid_recipients:
                            st.write("**🎯 Recipients:**")
                            for recip in valid_recipients:
                                st.code(recip)
    
    # Footer with enhanced information
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.caption(f"📅 **Analysis Period:** {start_date} to {end_date}")
    with col2:
        st.caption(f"🔄 **Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with col3:
        if st.button("🔄 Refresh Analytics"):
            st.experimental_rerun()

if __name__ == "__main__":
    main()