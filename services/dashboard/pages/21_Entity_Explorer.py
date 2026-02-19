"""
Entity Explorer Page

Browse and search canonical entities (persons, organizations, companies) with
filtering, sorting, and detailed entity profiles including descriptions,
key activities, and associated events.
"""

import sys
import os

import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import func, and_, case

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from shared.database.database import get_session
from shared.models.models import CanonicalEntity, EntityTypeEnum
from shared.utils.utils import Config

cfg = Config.from_yaml('shared/config/config.yaml')

st.set_page_config(page_title="Entity Explorer", page_icon="👤", layout="wide")

st.title("Entity Explorer")
st.caption(
    "Browse canonical entities (persons, organizations, companies) extracted from "
    "soft power documents. Filter by country, type, and search by name."
)


# ---------------------------------------------------------------------------
# Cached query functions
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_entity_kpis(countries):
    """Get high-level KPI metrics for entities."""
    with get_session() as session:
        base_query = session.query(CanonicalEntity).filter(
            CanonicalEntity.master_entity_id.is_(None),
            CanonicalEntity.initiating_country.in_(countries),
        )

        total_entities = base_query.count()

        avg_docs = session.query(
            func.avg(CanonicalEntity.total_documents)
        ).filter(
            CanonicalEntity.master_entity_id.is_(None),
            CanonicalEntity.initiating_country.in_(countries),
        ).scalar() or 0.0

        # Count by entity type
        type_counts = session.query(
            CanonicalEntity.entity_type,
            func.count(CanonicalEntity.id),
        ).filter(
            CanonicalEntity.master_entity_id.is_(None),
            CanonicalEntity.initiating_country.in_(countries),
        ).group_by(CanonicalEntity.entity_type).all()

        type_dict = {t.value if hasattr(t, 'value') else str(t): c for t, c in type_counts}

    return {
        "total_entities": total_entities,
        "avg_docs_per_entity": round(float(avg_docs), 1),
        "type_counts": type_dict,
    }


@st.cache_data(ttl=300, show_spinner=False)
def get_entities(
    countries,
    entity_type_filter,
    search_text,
    sort_by,
    limit=100,
):
    """
    Query canonical_entities with filters. Returns master entities only.
    """
    with get_session() as session:
        query = session.query(CanonicalEntity).filter(
            CanonicalEntity.master_entity_id.is_(None),
            CanonicalEntity.initiating_country.in_(countries),
        )

        # Entity type filter
        if entity_type_filter and entity_type_filter != "All":
            try:
                enum_val = EntityTypeEnum(entity_type_filter.lower())
                query = query.filter(CanonicalEntity.entity_type == enum_val)
            except ValueError:
                pass

        # Text search on canonical_name
        if search_text:
            query = query.filter(
                CanonicalEntity.canonical_name.ilike(f"%{search_text}%")
            )

        # Sorting
        if sort_by == "documents":
            query = query.order_by(CanonicalEntity.total_documents.desc())
        elif sort_by == "mentions":
            query = query.order_by(CanonicalEntity.total_mention_days.desc())
        elif sort_by == "recency":
            query = query.order_by(CanonicalEntity.last_mention_date.desc())
        else:
            query = query.order_by(CanonicalEntity.total_documents.desc())

        query = query.limit(limit)
        entities = query.all()

        # Serialize while session is open
        results = []
        for e in entities:
            results.append({
                "id": str(e.id),
                "canonical_name": e.canonical_name,
                "entity_type": e.entity_type.value if e.entity_type else "unknown",
                "initiating_country": e.initiating_country,
                "primary_role": e.primary_role.value if e.primary_role else None,
                "total_documents": e.total_documents or 0,
                "total_mention_days": e.total_mention_days or 0,
                "first_mention_date": e.first_mention_date.isoformat() if e.first_mention_date else None,
                "last_mention_date": e.last_mention_date.isoformat() if e.last_mention_date else None,
                "entity_description": e.entity_description,
                "key_activities": e.key_activities,
                "associated_events": e.associated_events or [],
                "alternative_names": e.alternative_names or [],
                "primary_categories": e.primary_categories or {},
                "primary_recipients": e.primary_recipients or {},
                "country_affiliations": e.country_affiliations or [],
            })

    return results


@st.cache_data(ttl=300, show_spinner=False)
def get_entity_type_distribution(countries):
    """Get entity type distribution for chart."""
    with get_session() as session:
        rows = session.query(
            CanonicalEntity.entity_type,
            func.count(CanonicalEntity.id).label('count'),
        ).filter(
            CanonicalEntity.master_entity_id.is_(None),
            CanonicalEntity.initiating_country.in_(countries),
        ).group_by(CanonicalEntity.entity_type).all()

        data = [
            {"entity_type": r.entity_type.value if hasattr(r.entity_type, 'value') else str(r.entity_type),
             "count": r.count}
            for r in rows
        ]

    return pd.DataFrame(data)


@st.cache_data(ttl=300, show_spinner=False)
def get_top_entities_by_country(countries, limit_per_country=5):
    """Get top entities per country for the overview chart."""
    with get_session() as session:
        all_results = []
        for country in countries:
            rows = session.query(CanonicalEntity).filter(
                CanonicalEntity.master_entity_id.is_(None),
                CanonicalEntity.initiating_country == country,
            ).order_by(CanonicalEntity.total_documents.desc()).limit(limit_per_country).all()

            for e in rows:
                all_results.append({
                    "country": e.initiating_country,
                    "entity_name": e.canonical_name,
                    "entity_type": e.entity_type.value if e.entity_type else "unknown",
                    "total_documents": e.total_documents or 0,
                })

    return pd.DataFrame(all_results)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("Entity Filters")

# Country filter
selected_countries = st.sidebar.multiselect(
    "Initiating Country",
    options=cfg.influencers,
    default=cfg.influencers,
    help="Filter entities by country affiliation",
)

if not selected_countries:
    st.warning("Please select at least one country.")
    st.stop()

# Entity type filter
entity_type_options = ["All", "person", "organization", "company"]
selected_type = st.sidebar.selectbox(
    "Entity Type",
    options=entity_type_options,
    index=0,
    help="Filter by entity type",
)

# Search
search_text = st.sidebar.text_input(
    "Search by Name",
    value="",
    help="Case-insensitive partial match on canonical entity name",
)

# Sort
sort_options = {
    "documents": "Total Documents (desc)",
    "mentions": "Total Mention Days (desc)",
    "recency": "Most Recent (desc)",
}
sort_by = st.sidebar.selectbox(
    "Sort By",
    options=list(sort_options.keys()),
    format_func=lambda x: sort_options[x],
    index=0,
)

# Limit
result_limit = st.sidebar.slider("Max Results", 10, 200, 50, step=10)

st.sidebar.markdown("---")


# ---------------------------------------------------------------------------
# Top KPI section
# ---------------------------------------------------------------------------

st.header("Entity Overview")

kpis = get_entity_kpis(selected_countries)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Master Entities", f"{kpis['total_entities']:,}")
with col2:
    st.metric("Avg Documents per Entity", f"{kpis['avg_docs_per_entity']:.1f}")
with col3:
    st.metric("Entity Types", len(kpis['type_counts']))

# Type distribution chart
type_df = get_entity_type_distribution(selected_countries)

if not type_df.empty:
    col_chart, col_top = st.columns([1, 1])

    with col_chart:
        st.subheader("Entity Type Distribution")
        type_chart = alt.Chart(type_df).mark_bar().encode(
            x=alt.X('count:Q', title='Count'),
            y=alt.Y('entity_type:N', title='Type', sort='-x'),
            color=alt.Color('entity_type:N', legend=None, scale=alt.Scale(scheme='tableau10')),
            tooltip=[
                alt.Tooltip('entity_type:N', title='Type'),
                alt.Tooltip('count:Q', title='Count'),
            ],
        ).properties(height=max(200, len(type_df) * 35))

        st.altair_chart(type_chart, use_container_width=True)

    with col_top:
        st.subheader("Top Entities by Country")
        top_df = get_top_entities_by_country(selected_countries, limit_per_country=3)
        if not top_df.empty:
            top_chart = alt.Chart(top_df).mark_bar().encode(
                x=alt.X('total_documents:Q', title='Documents'),
                y=alt.Y('entity_name:N', title='Entity', sort='-x'),
                color=alt.Color('country:N', title='Country'),
                tooltip=[
                    alt.Tooltip('entity_name:N', title='Entity'),
                    alt.Tooltip('country:N', title='Country'),
                    alt.Tooltip('entity_type:N', title='Type'),
                    alt.Tooltip('total_documents:Q', title='Documents'),
                ],
            ).properties(height=max(200, len(top_df) * 28))

            st.altair_chart(top_chart, use_container_width=True)

st.markdown("---")


# ---------------------------------------------------------------------------
# Entity cards
# ---------------------------------------------------------------------------

st.header("Entity Directory")

entities = get_entities(
    countries=selected_countries,
    entity_type_filter=selected_type,
    search_text=search_text,
    sort_by=sort_by,
    limit=result_limit,
)

if not entities:
    st.info("No entities found matching your filters.")
    st.stop()

st.markdown(f"Showing **{len(entities)}** entities")

# Type badge colors
TYPE_BADGE_COLORS = {
    "person": "#FF6B6B",
    "organization": "#4ECDC4",
    "company": "#45B7D1",
    "location": "#FFA07A",
    "other": "#95A5A6",
}

for entity in entities:
    etype = entity['entity_type']
    badge_color = TYPE_BADGE_COLORS.get(etype, "#95A5A6")
    role_text = entity['primary_role'].replace('_', ' ').title() if entity['primary_role'] else "N/A"

    # Card header with badge
    header_html = (
        f"<div style='display:flex; align-items:center; gap:10px; margin-bottom:4px;'>"
        f"<span style='font-size:18px; font-weight:bold;'>{entity['canonical_name']}</span>"
        f"<span style='background:{badge_color}; color:white; padding:2px 8px; "
        f"border-radius:12px; font-size:12px; font-weight:bold;'>{etype}</span>"
        f"</div>"
    )

    st.markdown(header_html, unsafe_allow_html=True)

    # Inline metrics
    mc1, mc2, mc3, mc4, mc5 = st.columns([1, 1, 1, 1, 2])
    with mc1:
        st.caption("Documents")
        st.markdown(f"**{entity['total_documents']:,}**")
    with mc2:
        st.caption("Mention Days")
        st.markdown(f"**{entity['total_mention_days']}**")
    with mc3:
        st.caption("First Seen")
        st.markdown(f"**{entity['first_mention_date'] or 'N/A'}**")
    with mc4:
        st.caption("Last Seen")
        st.markdown(f"**{entity['last_mention_date'] or 'N/A'}**")
    with mc5:
        st.caption("Role / Country")
        st.markdown(f"**{role_text}** | {entity['initiating_country']}")

    # Expandable detail section
    with st.expander("Details", expanded=False):
        # Entity description
        if entity['entity_description']:
            st.markdown("**Description:**")
            st.markdown(entity['entity_description'])
        else:
            st.caption("No description available.")

        # Alternative names
        alt_names = entity['alternative_names']
        if alt_names:
            st.markdown(f"**Alternative Names:** {', '.join(alt_names)}")

        # Country affiliations
        affiliations = entity['country_affiliations']
        if affiliations:
            st.markdown(f"**Country Affiliations:** {', '.join(affiliations)}")

        # Key activities (JSONB)
        key_acts = entity['key_activities']
        if key_acts and isinstance(key_acts, dict):
            st.markdown("**Key Activities:**")
            for activity_key, activity_val in key_acts.items():
                if isinstance(activity_val, list):
                    for item in activity_val:
                        st.markdown(f"- [{activity_key}] {item}")
                elif isinstance(activity_val, str):
                    st.markdown(f"- **{activity_key}:** {activity_val}")
                else:
                    st.markdown(f"- **{activity_key}:** {activity_val}")
        elif key_acts and isinstance(key_acts, list):
            st.markdown("**Key Activities:**")
            for item in key_acts:
                st.markdown(f"- {item}")

        # Primary categories
        cats = entity['primary_categories']
        if cats:
            st.markdown("**Primary Categories:**")
            for cat, count in sorted(cats.items(), key=lambda x: x[1], reverse=True):
                st.markdown(f"- {cat}: {count} mentions")

        # Primary recipients
        recs = entity['primary_recipients']
        if recs:
            config_recs = {k: v for k, v in recs.items() if k in cfg.recipients}
            if config_recs:
                st.markdown("**Primary Recipients:**")
                for rec, count in sorted(config_recs.items(), key=lambda x: x[1], reverse=True)[:10]:
                    st.markdown(f"- {rec}: {count} mentions")

        # Associated events (ARRAY)
        events = entity['associated_events']
        if events:
            st.markdown(f"**Associated Events ({len(events)}):**")
            for evt_id in events[:15]:
                st.markdown(f"- `{evt_id}`")
            if len(events) > 15:
                st.caption(f"... and {len(events) - 15} more")

    st.markdown("---")


# ---------------------------------------------------------------------------
# Data table export
# ---------------------------------------------------------------------------

st.header("Data Export")

export_df = pd.DataFrame([
    {
        "Name": e['canonical_name'],
        "Type": e['entity_type'],
        "Country": e['initiating_country'],
        "Role": e['primary_role'] or "",
        "Documents": e['total_documents'],
        "Mention Days": e['total_mention_days'],
        "First Seen": e['first_mention_date'] or "",
        "Last Seen": e['last_mention_date'] or "",
        "Alt Names": "; ".join(e['alternative_names']) if e['alternative_names'] else "",
    }
    for e in entities
])

st.dataframe(export_df, use_container_width=True, hide_index=True)

csv = export_df.to_csv(index=False).encode('utf-8')
st.download_button(
    label="Download entities as CSV",
    data=csv,
    file_name=f"entities_{selected_type}_{sort_by}.csv",
    mime="text/csv",
)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown(
    "**About:** This page displays master canonical entities "
    "(`canonical_entities` where `master_entity_id IS NULL`). "
    "Entities are extracted from documents via the entity extraction pipeline "
    "and consolidated through DBSCAN clustering and LLM deconfliction."
)
