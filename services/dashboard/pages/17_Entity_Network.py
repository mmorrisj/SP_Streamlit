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
import datetime
from typing import List, Dict

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_session
from shared.models.models import CanonicalEntity, EntityRelationship
from sqlalchemy import and_

st.set_page_config(page_title="Entity Network", page_icon="🕸️", layout="wide")

st.title("🕸️ Entity Relationship Network")
st.markdown("Interactive network visualization of entities and their relationships in soft power transactions")

# Sidebar filters
with st.sidebar:
    st.header("Filters")

    # Load filter options from database
    with get_session() as session:
        entity_count = session.query(CanonicalEntity).filter(
            CanonicalEntity.master_entity_id.is_(None)
        ).count()
        relationship_count = session.query(EntityRelationship).count()

        st.metric("Total Entities (Master)", entity_count)
        st.metric("Total Relationships", relationship_count)

        if entity_count == 0:
            st.warning("No entities found. Run entity extraction pipeline first.")
            st.info("Run: `extract_daily_entities.py` → `cluster_daily_entities.py` → `llm_deconflict_entity_clusters.py`")
            st.stop()

        countries = session.query(CanonicalEntity.initiating_country).distinct().filter(
            CanonicalEntity.initiating_country.isnot(None),
            CanonicalEntity.master_entity_id.is_(None)
        ).all()
        countries = [c[0] for c in countries]

        entity_types = session.query(CanonicalEntity.entity_type).distinct().filter(
            CanonicalEntity.master_entity_id.is_(None)
        ).all()
        entity_types = [t[0] for t in entity_types]

        rel_types = session.query(EntityRelationship.relationship_type).distinct().all()
        rel_types = [r[0] for r in rel_types]

    if entity_count > 0:
        selected_countries = st.multiselect("Countries", countries, default=countries[:3] if len(countries) > 3 else countries)
        selected_entity_types = st.multiselect("Entity Types", entity_types, default=entity_types)
        selected_rel_types = st.multiselect("Relationship Types", rel_types, default=rel_types)

        min_mentions = st.slider("Min Mentions", 1, 10, 1)
        max_entities = st.slider("Max Entities to Display", 10, 200, 50)

        # Temporal filtering
        st.markdown("---")
        st.markdown("### Temporal Filter")
        enable_date_filter = st.checkbox("Filter by date range", value=False)
        if enable_date_filter:
            date_col1, date_col2 = st.columns(2)
            with date_col1:
                date_start = st.date_input("From", value=datetime.date(2024, 8, 1), key="ent_date_start")
            with date_col2:
                date_end = st.date_input("To", value=datetime.date.today(), key="ent_date_end")
        else:
            date_start = None
            date_end = None

    st.markdown("---")
    st.markdown("### Graph Settings")

    height = st.slider("Graph Height (px)", 400, 1000, 750)
    physics_enabled = st.checkbox("Enable Physics", value=True)
    show_labels = st.checkbox("Show Labels", value=True)


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


# Main content — always real data (sample-data demo mode removed)
# Load data from database
with get_session() as session:
    query = session.query(CanonicalEntity).filter(
        CanonicalEntity.total_documents >= min_mentions,
        CanonicalEntity.master_entity_id.is_(None)
    )

    if selected_countries:
        query = query.filter(CanonicalEntity.initiating_country.in_(selected_countries))

    if selected_entity_types:
        query = query.filter(CanonicalEntity.entity_type.in_(selected_entity_types))

    # Apply temporal filter
    if enable_date_filter and date_start and date_end:
        query = query.filter(
            CanonicalEntity.last_mention_date >= date_start,
            CanonicalEntity.first_mention_date <= date_end
        )

    # Order by document count and limit
    query = query.order_by(CanonicalEntity.total_documents.desc()).limit(max_entities)

    db_entities = query.all()

    if not db_entities:
        st.warning("No entities match the filters")
        st.stop()

    # Get entity IDs for relationship filtering
    entity_ids = [str(e.id) for e in db_entities]

    # Query relationships between these entities
    db_relationships = session.query(EntityRelationship).filter(
        and_(
            EntityRelationship.entity_from_id.in_(entity_ids),
            EntityRelationship.entity_to_id.in_(entity_ids)
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
            "type": e.entity_type.value,  # Get enum value
            "country": e.initiating_country,
            "mentions": e.total_documents
        }
        for e in db_entities
    ]

    relationships = [
        {
            "source": str(r.entity_from_id),
            "target": str(r.entity_to_id),
            "type": r.relationship_type,
            "count": r.co_occurrence_count,
            "value": None  # total_value_usd not in new model
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

    # Entity Profile Panel
    st.markdown("### Entity Profile")
    entity_names = [e['name'] for e in entities]
    selected_entity_name = st.selectbox("Select an entity to view its profile", [""] + sorted(entity_names))

    if selected_entity_name:
        with get_session() as session:
            entity_obj = session.query(CanonicalEntity).filter(
                CanonicalEntity.canonical_name == selected_entity_name,
                CanonicalEntity.master_entity_id.is_(None)
            ).first()

            if entity_obj:
                prof_col1, prof_col2, prof_col3, prof_col4 = st.columns(4)
                with prof_col1:
                    st.metric("Documents", entity_obj.total_documents or 0)
                with prof_col2:
                    st.metric("Mention Days", entity_obj.total_mention_days or 0)
                with prof_col3:
                    st.metric("Type", str(entity_obj.entity_type.value) if entity_obj.entity_type else "Unknown")
                with prof_col4:
                    st.metric("Role", entity_obj.primary_role or "Unknown")

                if entity_obj.entity_description:
                    st.markdown("**Description:**")
                    st.markdown(entity_obj.entity_description)

                if entity_obj.first_mention_date and entity_obj.last_mention_date:
                    st.markdown(f"**Active:** {entity_obj.first_mention_date} to {entity_obj.last_mention_date}")

                if entity_obj.key_activities:
                    with st.expander("Key Activities"):
                        if isinstance(entity_obj.key_activities, list):
                            for activity in entity_obj.key_activities:
                                st.markdown(f"- {activity}")
                        elif isinstance(entity_obj.key_activities, dict):
                            for k, v in entity_obj.key_activities.items():
                                st.markdown(f"- **{k}:** {v}")

                if entity_obj.associated_events:
                    with st.expander(f"Associated Events ({len(entity_obj.associated_events)})"):
                        for event in entity_obj.associated_events[:20]:
                            st.markdown(f"- {event}")

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
