"""
Entity Network Visualization - Interactive network graph of entity relationships.

Visualizes entities as nodes and relationships as edges using pyvis.
"""

import streamlit as st
import pandas as pd
from pyvis.network import Network
import streamlit.components.v1 as components
import tempfile
import os
from typing import List, Dict, Any
from datetime import date

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_session
from shared.models.models_entity import Entity, EntityRelationship
from sqlalchemy import func, and_

st.set_page_config(page_title="Entity Network", page_icon="🕸️", layout="wide")

st.title("🕸️ Entity Relationship Network")
st.markdown("Interactive network visualization of entities and their relationships in soft power transactions")

# Sidebar filters
with st.sidebar:
    st.header("Filters")

    # Load filter options from database
    with get_session() as session:
        entity_count = session.query(Entity).count()
        relationship_count = session.query(EntityRelationship).count()

        st.metric("Total Entities", entity_count)
        st.metric("Total Relationships", relationship_count)

        if entity_count == 0:
            st.warning("No entities found. Run entity extraction first.")
            st.info("**Sample data available for demo**")
            use_sample_data = st.checkbox("Use sample data for demo", value=True)
        else:
            use_sample_data = False

            # Get filter options
            countries = session.query(Entity.country).distinct().filter(
                Entity.country.isnot(None)
            ).all()
            countries = [c[0] for c in countries]

            entity_types = session.query(Entity.entity_type).distinct().all()
            entity_types = [t[0] for t in entity_types]

            rel_types = session.query(EntityRelationship.relationship_type).distinct().all()
            rel_types = [r[0] for r in rel_types]

    if not use_sample_data and entity_count > 0:
        # Filters
        selected_countries = st.multiselect("Countries", countries, default=countries[:3] if len(countries) > 3 else countries)
        selected_entity_types = st.multiselect("Entity Types", entity_types, default=entity_types)
        selected_rel_types = st.multiselect("Relationship Types", rel_types, default=rel_types)

        min_mentions = st.slider("Min Mentions", 1, 10, 1)
        max_entities = st.slider("Max Entities to Display", 10, 200, 50)

    st.markdown("---")
    st.markdown("### Graph Settings")

    height = st.slider("Graph Height (px)", 400, 1000, 750)
    physics_enabled = st.checkbox("Enable Physics", value=True)
    show_labels = st.checkbox("Show Labels", value=True)


def create_sample_network_data():
    """Create sample entity and relationship data for demonstration"""

    # Sample entities
    entities = [
        {"id": "1", "name": "China Development Bank", "type": "FINANCIAL_INSTITUTION", "country": "China", "mentions": 15},
        {"id": "2", "name": "Saudi Aramco", "type": "STATE_OWNED_ENTERPRISE", "country": "Saudi Arabia", "mentions": 12},
        {"id": "3", "name": "Wang Yi", "type": "PERSON", "country": "China", "mentions": 25},
        {"id": "4", "name": "Ministry of Foreign Affairs", "type": "GOVERNMENT_AGENCY", "country": "China", "mentions": 20},
        {"id": "5", "name": "Egyptian Ministry of Finance", "type": "GOVERNMENT_AGENCY", "country": "Egypt", "mentions": 10},
        {"id": "6", "name": "Belt and Road Initiative", "type": "MULTILATERAL_ORG", "country": "China", "mentions": 30},
        {"id": "7", "name": "CNPC", "type": "STATE_OWNED_ENTERPRISE", "country": "China", "mentions": 18},
        {"id": "8", "name": "Ethiopia Electric Power", "type": "STATE_OWNED_ENTERPRISE", "country": "Ethiopia", "mentions": 8},
        {"id": "9", "name": "Huawei", "type": "PRIVATE_COMPANY", "country": "China", "mentions": 22},
        {"id": "10", "name": "African Union", "type": "MULTILATERAL_ORG", "country": "Ethiopia", "mentions": 14},
    ]

    # Sample relationships
    relationships = [
        {"source": "1", "target": "5", "type": "FUNDS", "count": 3, "value": 3000000000},
        {"source": "3", "target": "4", "type": "REPRESENTS", "count": 15, "value": None},
        {"source": "7", "target": "2", "type": "PARTNERS_WITH", "count": 5, "value": None},
        {"source": "1", "target": "8", "type": "INVESTS_IN", "count": 2, "value": 500000000},
        {"source": "9", "target": "10", "type": "SUPPLIES", "count": 4, "value": None},
        {"source": "6", "target": "5", "type": "FUNDS", "count": 8, "value": None},
        {"source": "6", "target": "8", "type": "FUNDS", "count": 6, "value": None},
        {"source": "3", "target": "5", "type": "MEETS_WITH", "count": 2, "value": None},
        {"source": "9", "target": "8", "type": "CONTRACTS_WITH", "count": 3, "value": 120000000},
    ]

    return entities, relationships


def get_entity_color(entity_type: str) -> str:
    """Return color based on entity type"""
    color_map = {
        "PERSON": "#FF6B6B",
        "GOVERNMENT_AGENCY": "#4ECDC4",
        "STATE_OWNED_ENTERPRISE": "#45B7D1",
        "PRIVATE_COMPANY": "#FFA07A",
        "MULTILATERAL_ORG": "#98D8C8",
        "NGO": "#C7CEEA",
        "EDUCATIONAL_INSTITUTION": "#FFD93D",
        "FINANCIAL_INSTITUTION": "#6BCB77",
        "MILITARY_UNIT": "#FF6B9D",
        "MEDIA_ORGANIZATION": "#C780E8",
        "RELIGIOUS_ORGANIZATION": "#DDA15E",
    }
    return color_map.get(entity_type, "#95A5A6")


def create_network_graph(entities: List[Dict], relationships: List[Dict],
                         height_px: int = 750, physics: bool = True,
                         show_labels: bool = True) -> str:
    """Create interactive network graph using pyvis"""

    # Create network
    net = Network(
        height=f"{height_px}px",
        width="100%",
        bgcolor="#1E1E1E",
        font_color="white",
        directed=True
    )

    # Set physics options
    if physics:
        net.set_options("""
        {
          "physics": {
            "enabled": true,
            "barnesHut": {
              "gravitationalConstant": -8000,
              "centralGravity": 0.3,
              "springLength": 150,
              "springConstant": 0.04,
              "damping": 0.09
            }
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 100
          }
        }
        """)
    else:
        net.toggle_physics(False)

    # Add nodes
    for entity in entities:
        node_id = str(entity['id'])
        name = entity['name']
        entity_type = entity.get('type', 'UNKNOWN')
        country = entity.get('country', 'Unknown')
        mentions = entity.get('mentions', 0)

        # Node size based on mentions
        size = 10 + (mentions * 1.5)

        # Color based on type
        color = get_entity_color(entity_type)

        # Tooltip
        title = f"<b>{name}</b><br>Type: {entity_type}<br>Country: {country}<br>Mentions: {mentions}"

        net.add_node(
            node_id,
            label=name if show_labels else "",
            title=title,
            size=size,
            color=color,
            borderWidth=2,
            borderWidthSelected=4
        )

    # Add edges
    for rel in relationships:
        source = str(rel['source'])
        target = str(rel['target'])
        rel_type = rel['type']
        count = rel.get('count', 1)
        value = rel.get('value')

        # Edge width based on observation count
        width = 1 + (count * 0.5)

        # Edge tooltip
        title = f"{rel_type}<br>Observations: {count}"
        if value:
            title += f"<br>Value: ${value:,.0f}"

        # Edge color based on relationship type
        color = {
            "FUNDS": "#6BCB77",
            "INVESTS_IN": "#4ECDC4",
            "PARTNERS_WITH": "#FFD93D",
            "MEETS_WITH": "#FF6B6B",
            "REPRESENTS": "#C7CEEA",
            "SUPPLIES": "#FFA07A",
            "CONTRACTS_WITH": "#45B7D1",
            "SIGNS_AGREEMENT": "#98D8C8",
        }.get(rel_type, "#95A5A6")

        net.add_edge(
            source,
            target,
            title=title,
            width=width,
            color=color,
            arrows={'to': {'enabled': True, 'scaleFactor': 0.5}}
        )

    # Generate HTML
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html', encoding='utf-8') as f:
        net.save_graph(f.name)
        with open(f.name, 'r', encoding='utf-8') as f2:
            html_string = f2.read()
        os.unlink(f.name)

    return html_string


# Main content
if use_sample_data:
    st.info("📊 Displaying sample data for demonstration")
    entities, relationships = create_sample_network_data()

else:
    # Load data from database
    with get_session() as session:
        # Query entities
        query = session.query(Entity).filter(
            Entity.mention_count >= min_mentions
        )

        if selected_countries:
            query = query.filter(Entity.country.in_(selected_countries))

        if selected_entity_types:
            query = query.filter(Entity.entity_type.in_(selected_entity_types))

        # Order by mentions and limit
        query = query.order_by(Entity.mention_count.desc()).limit(max_entities)

        db_entities = query.all()

        if not db_entities:
            st.warning("No entities match the filters")
            st.stop()

        # Get entity IDs for relationship filtering
        entity_ids = [str(e.id) for e in db_entities]

        # Query relationships between these entities
        db_relationships = session.query(EntityRelationship).filter(
            and_(
                EntityRelationship.source_entity_id.in_(entity_ids),
                EntityRelationship.target_entity_id.in_(entity_ids)
            )
        )

        if selected_rel_types:
            db_relationships = db_relationships.filter(
                EntityRelationship.relationship_type.in_(selected_rel_types)
            )

        db_relationships = db_relationships.all()

        # Convert to dicts
        entities = [
            {
                "id": str(e.id),
                "name": e.canonical_name,
                "type": e.entity_type,
                "country": e.country,
                "mentions": e.mention_count
            }
            for e in db_entities
        ]

        relationships = [
            {
                "source": str(r.source_entity_id),
                "target": str(r.target_entity_id),
                "type": r.relationship_type,
                "count": r.observation_count,
                "value": r.total_value_usd
            }
            for r in db_relationships
        ]

# Display metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Entities", len(entities))
with col2:
    st.metric("Relationships", len(relationships))
with col3:
    avg_connections = len(relationships) / len(entities) if entities else 0
    st.metric("Avg Connections", f"{avg_connections:.1f}")
with col4:
    entity_types_count = len(set(e['type'] for e in entities))
    st.metric("Entity Types", entity_types_count)

# Create and display network
if entities and relationships:
    with st.spinner("Generating network graph..."):
        html_string = create_network_graph(
            entities,
            relationships,
            height_px=height,
            physics=physics_enabled,
            show_labels=show_labels
        )
        components.html(html_string, height=height + 50, scrolling=False)

    # Legend
    st.markdown("### Legend")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Node Colors (Entity Types)**")
        legend_data = []
        unique_types = set(e['type'] for e in entities)
        for entity_type in sorted(unique_types):
            color = get_entity_color(entity_type)
            legend_data.append({
                "Type": entity_type,
                "Color": f'<span style="color:{color}">●</span> {entity_type}'
            })
        st.markdown("<br>".join([d["Color"] for d in legend_data]), unsafe_allow_html=True)

    with col2:
        st.markdown("**Relationship Types**")
        unique_rel_types = set(r['type'] for r in relationships)
        for rel_type in sorted(unique_rel_types):
            st.markdown(f"• {rel_type}")

    # Top entities table
    st.markdown("### Top Connected Entities")

    # Calculate degree (connections) for each entity
    entity_connections = {}
    for entity in entities:
        eid = entity['id']
        connections = sum(1 for r in relationships if r['source'] == eid or r['target'] == eid)
        entity_connections[eid] = connections

    top_entities = sorted(entities, key=lambda e: entity_connections.get(e['id'], 0), reverse=True)[:10]

    df_top = pd.DataFrame([
        {
            "Entity": e['name'],
            "Type": e['type'],
            "Country": e['country'],
            "Mentions": e['mentions'],
            "Connections": entity_connections.get(e['id'], 0)
        }
        for e in top_entities
    ])

    st.dataframe(df_top, use_container_width=True, hide_index=True)

else:
    st.warning("No relationship data to display")

# Help section
with st.expander("💡 How to use"):
    st.markdown("""
    **Interacting with the Network:**
    - **Hover** over nodes/edges to see details
    - **Click and drag** nodes to reposition them
    - **Scroll** to zoom in/out
    - **Click and drag background** to pan
    - **Click** a node to highlight its connections

    **Visual Encoding:**
    - **Node size** = Number of mentions in documents
    - **Node color** = Entity type
    - **Edge thickness** = Number of relationship observations
    - **Edge color** = Relationship type
    - **Arrow direction** = Relationship direction (source → target)

    **Filters:**
    - Use the sidebar to filter by country, entity type, and relationship type
    - Adjust minimum mentions to focus on more prominent entities
    - Limit max entities for better performance

    **Tips:**
    - Disable physics for static layout (faster interaction)
    - Hide labels to reduce clutter
    - Look for clusters to identify groups of connected entities
    - Financial relationships (FUNDS, INVESTS_IN) often have monetary values in tooltips
    """)
