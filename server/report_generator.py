"""
Report generator for the Publication page.

Generates structured reports with LLM narratives, metrics, and
citations grouped by category and event. Adapted from
publications/scripts/generate_dual_publication.py.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import json
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from collections import defaultdict
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from shared.database.database import get_session
from shared.utils.utils import Config, gai
from shared.utils.citation_utils import build_hyperlink
from shared.models.models import (
    Document, Category, Subcategory,
    InitiatingCountry, RecipientCountry,
    CanonicalEvent, CanonicalEntity, DailyEntityMention
)


def _check_llm_availability() -> bool:
    """Quick check if the LLM proxy is reachable (< 2s timeout)."""
    import requests
    fastapi_url = os.getenv('FASTAPI_URL', '').strip()
    if not fastapi_url:
        api_url = os.getenv('API_URL', '').strip()
        if api_url:
            fastapi_url = f"{api_url.rstrip('/')}/material_query"
        else:
            return False
    try:
        # Use HEAD/GET with a very short timeout just to check connectivity
        base_url = fastapi_url.rsplit('/', 1)[0]  # strip /material_query
        requests.get(f"{base_url}/docs", timeout=2)
        return True
    except Exception:
        return False


def parse_date(date_str: str) -> date:
    """Parse date string to date object."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def get_top_events_by_category(
    session: Session,
    country: str,
    start_date: date,
    end_date: date,
    recipient: Optional[str] = None,
    top_n: int = 10
) -> Dict[str, List[Dict]]:
    """
    Get top N events per category, ranked by article count and materiality.
    Only includes master events (consolidated multi-day events).
    Optionally filters by recipient using primary_recipients JSONB.
    """
    config = Config.from_yaml()
    valid_categories = config.categories
    events_by_category = defaultdict(list)

    for category in valid_categories:
        # Build recipient filter clause
        recipient_clause = ""
        params = {
            'country': country,
            'category': category,
            'start_date': start_date,
            'end_date': end_date,
            'top_n': top_n
        }

        if recipient:
            recipient_clause = "AND ce.primary_recipients ? :recipient"
            params['recipient'] = recipient

        query = text(f"""
            SELECT
                ce.id,
                ce.canonical_name,
                ce.consolidated_description,
                ce.first_mention_date,
                ce.last_mention_date,
                ce.total_articles,
                ce.total_mention_days,
                ce.llm_validated,
                COALESCE(ce.material_score, 0) as materiality_score,
                (
                    SELECT ARRAY_AGG(DISTINCT d)
                    FROM daily_event_mentions dem2, unnest(dem2.doc_ids) as d
                    WHERE dem2.canonical_event_id = ce.id
                ) as doc_ids,
                (
                    SELECT COUNT(DISTINCT did)
                    FROM daily_event_mentions dem4, unnest(dem4.doc_ids) as did
                    JOIN categories c3 ON c3.doc_id = did
                    WHERE dem4.canonical_event_id = ce.id
                    AND c3.category = :category
                ) as category_doc_count
            FROM canonical_events ce
            WHERE ce.initiating_country = :country
                AND ce.master_event_id IS NULL
                AND ce.first_mention_date <= :end_date
                AND ce.last_mention_date >= :start_date
                AND EXISTS (
                    SELECT 1
                    FROM daily_event_mentions dem3, unnest(dem3.doc_ids) as did
                    JOIN categories c2 ON c2.doc_id = did
                    WHERE dem3.canonical_event_id = ce.id
                    AND c2.category = :category
                )
                {recipient_clause}
            ORDER BY ce.total_articles DESC, materiality_score DESC
            LIMIT :top_n
        """)

        result = session.execute(query, params).fetchall()

        for row in result:
            # Flatten doc_ids array
            doc_ids = []
            if row.doc_ids:
                for doc_id_item in row.doc_ids:
                    if isinstance(doc_id_item, list):
                        doc_ids.extend(doc_id_item)
                    else:
                        doc_ids.append(doc_id_item)

            events_by_category[category].append({
                'id': str(row.id),
                'event_name': row.canonical_name,
                'description': row.consolidated_description,
                'first_mention_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
                'last_mention_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
                'article_count': row.total_articles or 0,
                'mention_days': row.total_mention_days or 0,
                'materiality_score': float(row.materiality_score) if row.materiality_score else 0.0,
                'llm_validated': row.llm_validated,
                'doc_ids': list(set(doc_ids)),
                'category_doc_count': row.category_doc_count or 0,
            })

    return dict(events_by_category)


def _deduplicate_and_backfill(
    events_by_category: Dict[str, List[Dict]],
    session: Session,
    country: str,
    start_date: date,
    end_date: date,
    recipient: Optional[str],
    top_n: int,
    min_articles: int = 2
) -> Dict[str, List[Dict]]:
    """
    Remove duplicate events that appear in multiple categories, then backfill
    categories that lost events with the next top-ranked events.

    Each event is assigned to the category where it has the most documents.
    Ties broken by config order. Categories below top_n are refilled with the
    next highest-ranked events (by article count + materiality), excluding
    already-assigned IDs, with a minimum article threshold.
    """
    # --- Phase 1: Deduplicate ---
    event_appearances: Dict[str, list] = {}
    for category, events in events_by_category.items():
        for event in events:
            eid = event['id']
            if eid not in event_appearances:
                event_appearances[eid] = []
            event_appearances[eid].append((category, event.get('category_doc_count', 0)))

    best_category: Dict[str, str] = {}
    for eid, appearances in event_appearances.items():
        if len(appearances) == 1:
            best_category[eid] = appearances[0][0]
        else:
            appearances.sort(key=lambda x: x[1], reverse=True)
            best_category[eid] = appearances[0][0]

    deduped = {}
    for category, events in events_by_category.items():
        deduped[category] = [e for e in events if best_category[e['id']] == category]

    removed = sum(len(events) for events in events_by_category.values()) - sum(len(events) for events in deduped.values())
    if removed > 0:
        print(f"[Report] Deduplication removed {removed} duplicate event entries")

    # --- Phase 2: Backfill categories that lost events ---
    # Collect all event IDs already assigned across all categories
    all_assigned_ids = set()
    for events in deduped.values():
        for e in events:
            all_assigned_ids.add(e['id'])

    for category, events in deduped.items():
        need = top_n - len(events)
        if need <= 0:
            continue

        # Query for replacement events, excluding already-assigned IDs
        exclude_ids = list(all_assigned_ids)
        recipient_clause = ""
        params: Dict[str, Any] = {
            'country': country,
            'category': category,
            'start_date': start_date,
            'end_date': end_date,
            'backfill_limit': need,
            'min_articles': min_articles,
        }

        if recipient:
            recipient_clause = "AND ce.primary_recipients ? :recipient"
            params['recipient'] = recipient

        # Build exclude clause — cast text list to UUID for type match
        exclude_clause = ""
        if exclude_ids:
            params['exclude_ids'] = exclude_ids
            exclude_clause = "AND ce.id::text != ALL(:exclude_ids)"

        query = text(f"""
            SELECT
                ce.id,
                ce.canonical_name,
                ce.consolidated_description,
                ce.first_mention_date,
                ce.last_mention_date,
                ce.total_articles,
                ce.total_mention_days,
                ce.llm_validated,
                COALESCE(ce.material_score, 0) as materiality_score,
                (
                    SELECT ARRAY_AGG(DISTINCT d)
                    FROM daily_event_mentions dem2, unnest(dem2.doc_ids) as d
                    WHERE dem2.canonical_event_id = ce.id
                ) as doc_ids,
                (
                    SELECT COUNT(DISTINCT did)
                    FROM daily_event_mentions dem4, unnest(dem4.doc_ids) as did
                    JOIN categories c3 ON c3.doc_id = did
                    WHERE dem4.canonical_event_id = ce.id
                    AND c3.category = :category
                ) as category_doc_count
            FROM canonical_events ce
            WHERE ce.initiating_country = :country
                AND ce.master_event_id IS NULL
                AND ce.first_mention_date <= :end_date
                AND ce.last_mention_date >= :start_date
                AND ce.total_articles >= :min_articles
                AND EXISTS (
                    SELECT 1
                    FROM daily_event_mentions dem3, unnest(dem3.doc_ids) as did
                    JOIN categories c2 ON c2.doc_id = did
                    WHERE dem3.canonical_event_id = ce.id
                    AND c2.category = :category
                )
                {exclude_clause}
                {recipient_clause}
            ORDER BY ce.total_articles DESC, materiality_score DESC
            LIMIT :backfill_limit
        """)

        result = session.execute(query, params).fetchall()

        backfilled = 0
        for row in result:
            doc_ids = []
            if row.doc_ids:
                for doc_id_item in row.doc_ids:
                    if isinstance(doc_id_item, list):
                        doc_ids.extend(doc_id_item)
                    else:
                        doc_ids.append(doc_id_item)

            new_event = {
                'id': str(row.id),
                'event_name': row.canonical_name,
                'description': row.consolidated_description,
                'first_mention_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
                'last_mention_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
                'article_count': row.total_articles or 0,
                'mention_days': row.total_mention_days or 0,
                'materiality_score': float(row.materiality_score) if row.materiality_score else 0.0,
                'llm_validated': row.llm_validated,
                'doc_ids': list(set(doc_ids)),
                'category_doc_count': row.category_doc_count or 0,
            }
            deduped[category].append(new_event)
            all_assigned_ids.add(new_event['id'])
            backfilled += 1

        if backfilled > 0:
            print(f"[Report] Backfilled {backfilled} events into {category}")

    return deduped


def get_document_details(session: Session, doc_ids: List[str]) -> List[Dict]:
    """Get document details for citations."""
    if not doc_ids:
        return []

    query = text("""
        SELECT
            d.doc_id,
            d.title,
            d.source_name,
            d.date as published_date,
            d.salience,
            ARRAY_AGG(DISTINCT c.category) as categories,
            ARRAY_AGG(DISTINCT rc.recipient_country) as recipients
        FROM documents d
        LEFT JOIN categories c ON d.doc_id = c.doc_id
        LEFT JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE d.doc_id = ANY(:doc_ids)
        GROUP BY d.doc_id, d.title, d.source_name, d.date, d.salience
        ORDER BY d.date DESC
    """)

    result = session.execute(query, {'doc_ids': doc_ids}).fetchall()

    documents = []
    for row in result:
        documents.append({
            'doc_id': row.doc_id,
            'headline': row.title or 'Untitled',
            'source_name': row.source_name or 'Unknown',
            'source_url': build_hyperlink([row.doc_id]),
            'published_date': row.published_date.isoformat() if row.published_date else None,
            'salience': row.salience,
            'categories': [c for c in (row.categories or []) if c],
            'recipients': [r for r in (row.recipients or []) if r]
        })

    return documents


def compute_metrics(
    session: Session,
    country: str,
    start_date: date,
    end_date: date,
    recipient: Optional[str],
    events_by_category: Dict[str, List[Dict]]
) -> Dict[str, Any]:
    """Compute metrics for the report: category, subcategory, recipient distributions and materiality histogram."""

    # Base filters for document queries
    base_filters = [
        Document.date.between(start_date, end_date),
        InitiatingCountry.initiating_country == country
    ]

    # Total documents
    doc_query = session.query(
        func.count(func.distinct(Document.doc_id))
    ).join(
        InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
    )
    if recipient:
        doc_query = doc_query.join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(
            RecipientCountry.recipient_country == recipient,
            *base_filters
        )
    else:
        doc_query = doc_query.filter(*base_filters)

    total_documents = doc_query.scalar() or 0

    # Total events
    total_events = sum(len(events) for events in events_by_category.values())

    # Category distribution
    cat_query = session.query(
        Category.category,
        func.count(func.distinct(Category.doc_id)).label('count')
    ).join(
        Document, Category.doc_id == Document.doc_id
    ).join(
        InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
    ).filter(
        Document.date.between(start_date, end_date),
        InitiatingCountry.initiating_country == country
    )
    if recipient:
        cat_query = cat_query.join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(RecipientCountry.recipient_country == recipient)

    category_dist = cat_query.group_by(Category.category).order_by(
        func.count(func.distinct(Category.doc_id)).desc()
    ).all()

    # Subcategory distribution
    subcat_query = session.query(
        Subcategory.subcategory,
        func.count(func.distinct(Subcategory.doc_id)).label('count')
    ).join(
        Document, Subcategory.doc_id == Document.doc_id
    ).join(
        InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
    ).filter(
        Document.date.between(start_date, end_date),
        InitiatingCountry.initiating_country == country
    )
    if recipient:
        subcat_query = subcat_query.join(
            RecipientCountry, RecipientCountry.doc_id == Document.doc_id
        ).filter(RecipientCountry.recipient_country == recipient)

    subcategory_dist = subcat_query.group_by(Subcategory.subcategory).order_by(
        func.count(func.distinct(Subcategory.doc_id)).desc()
    ).all()

    # Recipient distribution
    recip_query = session.query(
        RecipientCountry.recipient_country,
        func.count(func.distinct(RecipientCountry.doc_id)).label('count')
    ).join(
        Document, RecipientCountry.doc_id == Document.doc_id
    ).join(
        InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
    ).filter(
        Document.date.between(start_date, end_date),
        InitiatingCountry.initiating_country == country
    )
    if recipient:
        recip_query = recip_query.filter(
            RecipientCountry.recipient_country == recipient
        )

    recipient_dist = recip_query.group_by(
        RecipientCountry.recipient_country
    ).order_by(
        func.count(func.distinct(RecipientCountry.doc_id)).desc()
    ).limit(20).all()

    # Materiality histogram from events
    bins = {f"{i}-{i+1}": 0 for i in range(10)}
    for events in events_by_category.values():
        for event in events:
            score = event.get('materiality_score', 0)
            bin_idx = min(int(score), 9)
            bins[f"{bin_idx}-{bin_idx+1}"] += 1

    return {
        'total_documents': total_documents,
        'total_events': total_events,
        'category_distribution': [
            {'category': row.category, 'count': row.count}
            for row in category_dist
        ],
        'subcategory_distribution': [
            {'subcategory': row.subcategory, 'count': row.count}
            for row in subcategory_dist
        ],
        'recipient_distribution': [
            {'recipient': row.recipient_country, 'count': row.count}
            for row in recipient_dist
        ],
        'materiality_histogram': [
            {'bin': k, 'count': v} for k, v in bins.items()
        ]
    }


def generate_event_narrative(event: Dict, config: Config) -> Dict[str, str]:
    """Generate Overview and Outcomes for an event using LLM."""

    sys_prompt = """You are an expert analyst creating executive briefing summaries.

Generate two sections:
1. OVERVIEW: What happened (actors, actions, context) - 2-3 sentences
2. OUTCOMES: Results, impacts, significance - 2-3 sentences

Be concise, factual, and strategic. Focus on geopolitical implications."""

    user_prompt = f"""Event: {event['event_name']}
Description: {event['description']}
Date Range: {event['first_mention_date']} to {event['last_mention_date']}
Coverage: {event['article_count']} articles over {event['mention_days']} days
Materiality Score: {event['materiality_score']}/10

Generate Overview and Outcomes.
Return JSON: {{"overview": "...", "outcomes": "..."}}"""

    try:
        response = gai(sys_prompt, user_prompt, model="gpt-4o-mini")

        if isinstance(response, dict):
            return response

        response_str = response.strip()
        if response_str.startswith("```json"):
            response_str = response_str[7:]
        if response_str.endswith("```"):
            response_str = response_str[:-3]

        return json.loads(response_str.strip())
    except Exception as e:
        print(f"  Warning: Error generating narrative for {event['event_name'][:50]}: {e}")
        return {
            'overview': event.get('description') or f"Event: {event['event_name']}",
            'outcomes': "This event represents a significant development in regional engagement."
        }


def generate_category_narrative(
    country: str,
    category: str,
    events: List[Dict],
    source_map: Dict[str, int],
    documents_by_event: Dict[str, List[Dict]],
    start_date: date,
    end_date: date
) -> str:
    """Generate a category-level narrative with inline citations."""

    # Build event list with citation numbers
    event_list = []
    for event in events[:10]:
        docs = documents_by_event.get(event['id'], [])
        citation_nums = [
            str(source_map[doc['doc_id']])
            for doc in docs[:5]
            if doc['doc_id'] in source_map
        ]

        citations_str = ""
        if citation_nums:
            citations_str = f" [Citations: {', '.join(citation_nums[:3])}]"

        event_list.append(
            f"- {event['event_name']} ({event['article_count']} articles, "
            f"materiality: {event['materiality_score']}/10){citations_str}"
        )

    events_text = "\n".join(event_list)

    sys_prompt = """You are an expert strategic analyst writing executive briefings.

Generate a flowing narrative paragraph (4-6 sentences) that synthesizes key themes and strategic implications.

IMPORTANT: Include inline citations [1], [2], [3] etc. after key claims to reference the source documents provided.
Use the citation numbers shown in the event list. Place citations at the end of relevant sentences.

Example: "China strengthened diplomatic ties through high-level bilateral meetings [1], [2]. This enhanced regional cooperation [3]."

Focus on:
- Strategic patterns and trends
- Geopolitical significance
- Policy implications
- Regional impact"""

    user_prompt = f"""Category: {category}
Period: {start_date} to {end_date}
Country: {country}

Top Events (with citation numbers):
{events_text}

Generate a strategic narrative paragraph with inline citations [1], [2], etc."""

    try:
        response = gai(sys_prompt, user_prompt, model="gpt-4o")
        narrative = response if isinstance(response, str) else response.get('summary', '')
        return narrative
    except Exception as e:
        print(f"  Warning: Error generating {category} summary: {e}")
        return (
            f"Key developments in {category} during this period included "
            f"significant diplomatic and strategic activities."
        )


def generate_overall_synthesis(
    country: str,
    category_summaries: Dict[str, str],
    start_date: date,
    end_date: date
) -> str:
    """Generate overall strategic synthesis from category narratives."""

    category_text = "\n\n".join([
        f"**{cat}:**\n{summary}"
        for cat, summary in category_summaries.items()
    ])

    sys_prompt = """You are a senior strategic analyst writing an executive summary.

Synthesize the category summaries into a cohesive strategic overview (3-4 paragraphs).

IMPORTANT: Preserve all inline citations [1], [2], etc. from the category summaries.

Structure:
1. Opening: Strategic context and key themes
2. Body: Major developments by category
3. Closing: Implications and outlook"""

    user_prompt = f"""Country: {country}
Period: {start_date} to {end_date}

Category Summaries (with citations):
{category_text}

Generate an overall strategic synthesis. Preserve all [#] citations."""

    try:
        overall_summary = gai(sys_prompt, user_prompt, model="gpt-4o")
        if isinstance(overall_summary, dict):
            overall_summary = overall_summary.get('summary', '')
        return overall_summary
    except Exception as e:
        print(f"  Warning: Error generating overall summary: {e}")
        return "This period saw significant strategic developments across multiple domains."


def generate_publication_title(
    country: str,
    events_by_category: Dict[str, List[Dict]],
    start_date: date,
    end_date: date
) -> str:
    """Generate a descriptive title for the publication."""
    start_str = start_date.strftime("%B %Y")
    end_str = end_date.strftime("%B %Y")
    date_range = start_str if start_str == end_str else f"{start_str} to {end_str}"

    # Collect top event names for context
    top_events = []
    for events in events_by_category.values():
        for event in events[:2]:
            top_events.append(event['event_name'])

    sys_prompt = f"""Create a brief, descriptive title (maximum 10 words) for a strategic briefing.
No subjective language or qualifiers. Reference the date range: {date_range}.
Focus on major themes. Return only the title, no quotes or formatting."""

    user_prompt = f"""Country: {country}
Period: {date_range}
Key Events: {', '.join(top_events[:6])}

Generate a title."""

    try:
        response = gai(sys_prompt, user_prompt, model="gpt-4o-mini")
        title = response if isinstance(response, str) else str(response)
        return title.strip().strip('"\'')
    except Exception:
        return f"{country} Strategic Activities: {date_range}"


def get_top_entities(
    session: Session,
    country: str,
    start_date: date,
    end_date: date,
    recipient: Optional[str] = None,
    top_n: int = 10
) -> Dict[str, List[Dict]]:
    """
    Get top entities by type (PERSON, ORGANIZATION, COMPANY, LOCATION),
    ranked by document count within the date range.
    Only master entities (master_entity_id IS NULL).
    """
    entity_types = ['PERSON', 'ORGANIZATION', 'COMPANY', 'LOCATION']
    entities_by_type = {}

    for etype in entity_types:
        params = {
            'country': country,
            'entity_type': etype,
            'start_date': start_date,
            'end_date': end_date,
            'top_n': top_n
        }

        recipient_clause = ""
        if recipient:
            recipient_clause = "AND ce.primary_recipients ? :recipient"
            params['recipient'] = recipient

        query = text(f"""
            SELECT
                ce.id,
                ce.canonical_name,
                ce.entity_type,
                ce.primary_role,
                ce.entity_description,
                ce.country_affiliations,
                ce.total_documents,
                ce.total_mention_days,
                ce.first_mention_date,
                ce.last_mention_date,
                ce.primary_categories,
                ce.primary_recipients,
                ce.key_activities,
                (
                    SELECT ARRAY_AGG(DISTINCT d)
                    FROM daily_entity_mentions dem2, unnest(dem2.doc_ids) as d
                    WHERE dem2.canonical_entity_id = ce.id
                    AND dem2.mention_date >= :start_date
                    AND dem2.mention_date <= :end_date
                ) as doc_ids
            FROM canonical_entities ce
            WHERE ce.initiating_country = :country
                AND ce.master_entity_id IS NULL
                AND ce.entity_type = :entity_type
                AND ce.first_mention_date <= :end_date
                AND ce.last_mention_date >= :start_date
                {recipient_clause}
            ORDER BY ce.total_documents DESC
            LIMIT :top_n
        """)

        result = session.execute(query, params).fetchall()

        entities = []
        for row in result:
            doc_ids = []
            if row.doc_ids:
                for d in row.doc_ids:
                    if isinstance(d, list):
                        doc_ids.extend(d)
                    else:
                        doc_ids.append(d)

            entities.append({
                'id': str(row.id),
                'name': row.canonical_name,
                'entity_type': row.entity_type,
                'role': row.primary_role,
                'description': row.entity_description,
                'country_affiliations': row.country_affiliations or [],
                'total_documents': row.total_documents or 0,
                'total_mention_days': row.total_mention_days or 0,
                'first_mention_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
                'last_mention_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
                'primary_categories': row.primary_categories or {},
                'primary_recipients': row.primary_recipients or {},
                'key_activities': row.key_activities,
                'doc_ids': list(set(doc_ids))
            })

        if entities:
            entities_by_type[etype] = entities

    return entities_by_type


def generate_entity_summary(entity: Dict, country: str, start_date: date, end_date: date) -> str:
    """Generate a brief summary of an entity's contribution during the time period."""

    # Build context from available fields
    categories_str = ", ".join(
        f"{k} ({v})" for k, v in sorted(
            (entity.get('primary_categories') or {}).items(),
            key=lambda x: x[1], reverse=True
        )[:4]
    ) or "Unknown"

    recipients_str = ", ".join(
        f"{k} ({v})" for k, v in sorted(
            (entity.get('primary_recipients') or {}).items(),
            key=lambda x: x[1], reverse=True
        )[:4]
    ) or "Unknown"

    sys_prompt = """You are a diplomatic analyst. Write a concise 2-3 sentence summary of this entity's
role and contribution during the specified time period. Focus on their significance in soft power
activities, key engagements, and strategic importance. Be factual and specific."""

    user_prompt = f"""Entity: {entity['name']}
Type: {entity['entity_type']}
Role: {entity.get('role') or 'Unknown'}
Country Context: {country}
Period: {start_date} to {end_date}
Documents: {entity['total_documents']} across {entity['total_mention_days']} days
Categories: {categories_str}
Recipients: {recipients_str}
Existing Description: {entity.get('description') or 'None'}

Write a brief summary of this entity's contribution during this period."""

    try:
        response = gai(sys_prompt, user_prompt, model="gpt-4o-mini")
        summary = response if isinstance(response, str) else str(response)
        return summary.strip()
    except Exception as e:
        print(f"  Warning: Error generating entity summary for {entity['name']}: {e}")
        desc = entity.get('description') or ''
        if desc:
            return desc
        return f"{entity['name']} was mentioned in {entity['total_documents']} documents during this period."


def generate_report(
    country: str,
    start_date_str: str,
    end_date_str: str,
    recipient: Optional[str] = None,
    top_n: int = 10
) -> Dict[str, Any]:
    """
    Main report generation orchestrator.

    Returns complete report JSON with narratives, metrics, and citations grouped by event.
    """
    start_date = parse_date(start_date_str)
    end_date = parse_date(end_date_str)
    config = Config.from_yaml()

    # Quick LLM availability check — avoids 46+ slow connection-refused calls
    llm_available = _check_llm_availability()
    if not llm_available:
        print("[Report] LLM proxy unavailable — using fallback text for narratives")

    with get_session() as session:
        # Step 1: Get top events by category
        print(f"[Report] Loading top events for {country} ({start_date} to {end_date})...")
        events_by_category = get_top_events_by_category(
            session, country, start_date, end_date, recipient, top_n
        )
        events_by_category = _deduplicate_and_backfill(
            events_by_category, session, country, start_date, end_date, recipient, top_n
        )

        total_events = sum(len(events) for events in events_by_category.values())
        print(f"[Report] Found {total_events} events across {len(events_by_category)} categories")

        if total_events == 0:
            return {
                'country': country,
                'title': f'{country} Report: No Events Found',
                'period_start': start_date.isoformat(),
                'period_end': end_date.isoformat(),
                'recipient_filter': recipient or 'All',
                'generated_at': datetime.now().isoformat(),
                'overall_summary': 'No events found for the selected criteria.',
                'categories': [],
                'metrics': {
                    'total_documents': 0, 'total_events': 0,
                    'category_distribution': [], 'subcategory_distribution': [],
                    'recipient_distribution': [], 'materiality_histogram': []
                },
                'citations_by_event': [],
                'entities': []
            }

        # Step 2: Get document details for each event
        print("[Report] Loading source documents...")
        documents_by_event = {}
        for category, events in events_by_category.items():
            for event in events:
                if event['doc_ids']:
                    documents_by_event[event['id']] = get_document_details(
                        session, event['doc_ids']
                    )

        # Step 3: Compute metrics
        print("[Report] Computing metrics...")
        metrics = compute_metrics(
            session, country, start_date, end_date, recipient, events_by_category
        )

        # Step 3b: Get top entities
        print("[Report] Loading top entities...")
        entities_by_type = get_top_entities(
            session, country, start_date, end_date, recipient, top_n=5
        )
        total_entities = sum(len(ents) for ents in entities_by_type.values())
        print(f"[Report] Found {total_entities} entities across {len(entities_by_type)} types")

    # Step 4: Build global source map (citation numbers)
    print("[Report] Building citation map...")
    all_sources = []
    source_map = {}  # doc_id -> citation_number
    source_counter = 1

    for category in config.categories:
        events = events_by_category.get(category, [])
        for event in events[:top_n]:
            docs = documents_by_event.get(event['id'], [])
            for doc in docs[:5]:
                doc_id = doc['doc_id']
                if doc_id not in source_map:
                    source_map[doc_id] = source_counter
                    repo_hyperlink = build_hyperlink([doc_id])
                    all_sources.append({
                        'citation_number': source_counter,
                        'doc_id': doc_id,
                        'headline': doc['headline'],
                        'source_name': doc['source_name'],
                        'published_date': doc['published_date'],
                        'categories': doc['categories'],
                        'recipients': doc['recipients'],
                        'repo_hyperlink': repo_hyperlink
                    })
                    source_counter += 1

    print(f"[Report] Total citations: {len(all_sources)}")

    # Step 5: Generate event narratives
    if llm_available:
        print("[Report] Generating event narratives...")
        for category, events in events_by_category.items():
            for event in events:
                narrative = generate_event_narrative(event, config)
                event['overview'] = narrative.get('overview', '')
                event['outcomes'] = narrative.get('outcomes', '')
    else:
        print("[Report] Skipping event narratives (LLM unavailable)")
        for category, events in events_by_category.items():
            for event in events:
                event['overview'] = event.get('description') or f"Event: {event['event_name']}"
                event['outcomes'] = "Analysis pending — LLM service unavailable."

    # Step 6: Generate category narratives
    category_summaries = {}
    if llm_available:
        print("[Report] Generating category narratives...")
        for category in config.categories:
            events = events_by_category.get(category, [])
            if not events:
                continue
            narrative = generate_category_narrative(
                country, category, events, source_map,
                documents_by_event, start_date, end_date
            )
            category_summaries[category] = narrative
    else:
        print("[Report] Skipping category narratives (LLM unavailable)")
        for category in config.categories:
            events = events_by_category.get(category, [])
            if events:
                category_summaries[category] = f"Key developments in {category} during this period included {len(events)} significant events."

    # Step 7: Generate overall synthesis
    if llm_available:
        print("[Report] Generating overall synthesis...")
        overall_summary = generate_overall_synthesis(
            country, category_summaries, start_date, end_date
        )
    else:
        print("[Report] Skipping overall synthesis (LLM unavailable)")
        overall_summary = f"This report covers {country}'s strategic activities from {start_date} to {end_date}. {total_events} events were identified across {len(events_by_category)} categories."

    # Step 7b: Generate entity summaries
    print("[Report] Generating entity summaries...")
    entities_output = []
    for etype, entities in entities_by_type.items():
        entity_list = []
        for entity in entities:
            if llm_available:
                summary = generate_entity_summary(entity, country, start_date, end_date)
            else:
                summary = f"{entity['name']} was mentioned in {entity['total_documents']} documents during this period."

            # Add entity doc_ids to the global source map for traceability
            entity_doc_citations = []
            for doc_id in entity.get('doc_ids', [])[:3]:
                if doc_id in source_map:
                    entity_doc_citations.append(source_map[doc_id])

            entity_list.append({
                'name': entity['name'],
                'entity_type': entity['entity_type'],
                'role': entity.get('role') or 'Unknown',
                'country_affiliations': entity.get('country_affiliations', []),
                'total_documents': entity['total_documents'],
                'total_mention_days': entity['total_mention_days'],
                'first_mention_date': entity.get('first_mention_date'),
                'last_mention_date': entity.get('last_mention_date'),
                'primary_categories': entity.get('primary_categories', {}),
                'primary_recipients': entity.get('primary_recipients', {}),
                'summary': summary,
                'citation_numbers': entity_doc_citations,
                'doc_ids': entity.get('doc_ids', [])[:10]
            })

        if entity_list:
            type_labels = {
                'PERSON': 'KEY PERSONS',
                'ORGANIZATION': 'KEY ORGANIZATIONS',
                'COMPANY': 'KEY COMPANIES',
                'LOCATION': 'KEY LOCATIONS',
            }
            type_label = type_labels.get(etype, etype + 'S')

            entities_output.append({
                'entity_type': etype.lower(),
                'type_label': type_label,
                'entities': entity_list
            })

    # Step 8: Generate title
    if llm_available:
        print("[Report] Generating title...")
        title = generate_publication_title(
            country, events_by_category, start_date, end_date
        )
    else:
        title = f"{country} Strategic Activities: {start_date.strftime('%B %Y')}"

    # Step 9: Build categories output
    categories_output = []
    for category in config.categories:
        events = events_by_category.get(category, [])
        if not events:
            continue

        categories_output.append({
            'category': category,
            'narrative': category_summaries.get(category, ''),
            'events': [
                {
                    'event_name': e['event_name'],
                    'first_mention_date': e['first_mention_date'],
                    'last_mention_date': e['last_mention_date'],
                    'article_count': e['article_count'],
                    'materiality_score': e['materiality_score'],
                    'overview': e.get('overview', ''),
                    'outcomes': e.get('outcomes', ''),
                    'doc_ids': e['doc_ids']
                }
                for e in events
            ]
        })

    # Step 10: Build citations grouped by event
    citations_by_event = []
    for category in config.categories:
        events = events_by_category.get(category, [])
        if not events:
            continue

        category_event_citations = []
        for event in events:
            docs = documents_by_event.get(event['id'], [])
            event_citations = []
            for doc in docs[:5]:
                doc_id = doc['doc_id']
                if doc_id in source_map:
                    event_citations.append({
                        'citation_number': source_map[doc_id],
                        'doc_id': doc_id,
                        'headline': doc['headline'],
                        'source_name': doc['source_name'],
                        'published_date': doc['published_date'],
                        'categories': doc['categories'],
                        'recipients': doc['recipients'],
                        'repo_hyperlink': build_hyperlink([doc_id])
                    })

            if event_citations:
                category_event_citations.append({
                    'event_name': event['event_name'],
                    'materiality_score': event['materiality_score'],
                    'date_range': f"{event['first_mention_date']} to {event['last_mention_date']}",
                    'citations': event_citations
                })

        if category_event_citations:
            citations_by_event.append({
                'category': category,
                'events': category_event_citations
            })

    # Assemble final report
    report = {
        'country': country,
        'title': title,
        'period_start': start_date.isoformat(),
        'period_end': end_date.isoformat(),
        'recipient_filter': recipient or 'All',
        'generated_at': datetime.now().isoformat(),
        'overall_summary': overall_summary,
        'categories': categories_output,
        'entities': entities_output,
        'metrics': metrics,
        'citations_by_event': citations_by_event
    }

    print("[Report] Generation complete!")
    return report


def _build_citations_output(
    config: Config,
    events_by_category: Dict[str, List[Dict]],
    documents_by_event: Dict[str, List[Dict]],
    source_map: Dict[str, int]
) -> list:
    """Build citations grouped by category and event (shared by both report modes)."""
    citations_by_event = []
    for category in config.categories:
        events = events_by_category.get(category, [])
        if not events:
            continue

        category_event_citations = []
        for event in events:
            docs = documents_by_event.get(event['id'], [])
            event_citations = []
            for doc in docs[:5]:
                doc_id = doc['doc_id']
                if doc_id in source_map:
                    event_citations.append({
                        'citation_number': source_map[doc_id],
                        'doc_id': doc_id,
                        'headline': doc['headline'],
                        'source_name': doc['source_name'],
                        'published_date': doc['published_date'],
                        'categories': doc['categories'],
                        'recipients': doc['recipients'],
                        'repo_hyperlink': build_hyperlink([doc_id])
                    })

            if event_citations:
                category_event_citations.append({
                    'event_name': event['event_name'],
                    'materiality_score': event['materiality_score'],
                    'date_range': f"{event['first_mention_date']} to {event['last_mention_date']}",
                    'citations': event_citations
                })

        if category_event_citations:
            citations_by_event.append({
                'category': category,
                'events': category_event_citations
            })

    return citations_by_event


def _build_entities_skeleton(
    entities_by_type: Dict[str, List[Dict]],
    source_map: Dict[str, int]
) -> list:
    """Build entities output with null summaries (for skeleton)."""
    entities_output = []
    type_labels = {
        'PERSON': 'KEY PERSONS',
        'ORGANIZATION': 'KEY ORGANIZATIONS',
        'COMPANY': 'KEY COMPANIES',
        'LOCATION': 'KEY LOCATIONS',
    }

    for etype, entities in entities_by_type.items():
        entity_list = []
        for entity in entities:
            entity_doc_citations = []
            for doc_id in entity.get('doc_ids', [])[:3]:
                if doc_id in source_map:
                    entity_doc_citations.append(source_map[doc_id])

            entity_list.append({
                'name': entity['name'],
                'entity_type': entity['entity_type'],
                'role': entity.get('role') or 'Unknown',
                'country_affiliations': entity.get('country_affiliations', []),
                'total_documents': entity['total_documents'],
                'total_mention_days': entity['total_mention_days'],
                'first_mention_date': entity.get('first_mention_date'),
                'last_mention_date': entity.get('last_mention_date'),
                'primary_categories': entity.get('primary_categories', {}),
                'primary_recipients': entity.get('primary_recipients', {}),
                'summary': None,
                'citation_numbers': entity_doc_citations,
                'doc_ids': entity.get('doc_ids', [])[:10]
            })

        if entity_list:
            type_label = type_labels.get(etype, etype + 'S')
            entities_output.append({
                'entity_type': etype.lower(),
                'type_label': type_label,
                'entities': entity_list
            })

    return entities_output


def generate_report_stream(
    country: str,
    start_date_str: str,
    end_date_str: str,
    recipient: Optional[str] = None,
    top_n: int = 10
):
    """
    Streaming version of generate_report().
    Yields SSE event dicts: {"type": str, "payload": dict}
    """
    start_date = parse_date(start_date_str)
    end_date = parse_date(end_date_str)
    config = Config.from_yaml()

    llm_available = _check_llm_availability()
    if not llm_available:
        print("[Report SSE] LLM proxy unavailable — using fallback text")

    # --- DB queries (Steps 1-4) ---
    with get_session() as session:
        print(f"[Report SSE] Loading events for {country} ({start_date} to {end_date})...")
        events_by_category = get_top_events_by_category(
            session, country, start_date, end_date, recipient, top_n
        )
        events_by_category = _deduplicate_and_backfill(
            events_by_category, session, country, start_date, end_date, recipient, top_n
        )

        total_events = sum(len(events) for events in events_by_category.values())
        print(f"[Report SSE] Found {total_events} events across {len(events_by_category)} categories")

        if total_events == 0:
            yield {"type": "skeleton", "payload": {
                'country': country,
                'title': f'{country} Report: No Events Found',
                'period_start': start_date.isoformat(),
                'period_end': end_date.isoformat(),
                'recipient_filter': recipient or 'All',
                'generated_at': datetime.now().isoformat(),
                'overall_summary': 'No events found for the selected criteria.',
                'categories': [],
                'entities': [],
                'metrics': {
                    'total_documents': 0, 'total_events': 0,
                    'category_distribution': [], 'subcategory_distribution': [],
                    'recipient_distribution': [], 'materiality_histogram': []
                },
                'citations_by_event': []
            }}
            yield {"type": "complete", "payload": {}}
            return

        print("[Report SSE] Loading source documents...")
        documents_by_event = {}
        for category, events in events_by_category.items():
            for event in events:
                if event['doc_ids']:
                    documents_by_event[event['id']] = get_document_details(
                        session, event['doc_ids']
                    )

        print("[Report SSE] Computing metrics...")
        metrics = compute_metrics(
            session, country, start_date, end_date, recipient, events_by_category
        )

        print("[Report SSE] Loading entities...")
        entities_by_type = get_top_entities(
            session, country, start_date, end_date, recipient, top_n=5
        )

    # Build source map (Step 4)
    print("[Report SSE] Building citation map...")
    source_map = {}
    source_counter = 1
    for category in config.categories:
        events = events_by_category.get(category, [])
        for event in events[:top_n]:
            docs = documents_by_event.get(event['id'], [])
            for doc in docs[:5]:
                doc_id = doc['doc_id']
                if doc_id not in source_map:
                    source_map[doc_id] = source_counter
                    source_counter += 1

    # Build skeleton
    categories_output = []
    for category in config.categories:
        events = events_by_category.get(category, [])
        if not events:
            continue
        categories_output.append({
            'category': category,
            'narrative': None,
            'events': [
                {
                    'event_name': e['event_name'],
                    'first_mention_date': e['first_mention_date'],
                    'last_mention_date': e['last_mention_date'],
                    'article_count': e['article_count'],
                    'materiality_score': e['materiality_score'],
                    'overview': None,
                    'outcomes': None,
                    'doc_ids': e['doc_ids']
                }
                for e in events
            ]
        })

    entities_output = _build_entities_skeleton(entities_by_type, source_map)
    citations_by_event = _build_citations_output(
        config, events_by_category, documents_by_event, source_map
    )

    skeleton = {
        'country': country,
        'title': f"{country} Strategic Activities: {start_date.strftime('%B %Y')}",
        'period_start': start_date.isoformat(),
        'period_end': end_date.isoformat(),
        'recipient_filter': recipient or 'All',
        'generated_at': datetime.now().isoformat(),
        'overall_summary': None,
        'categories': categories_output,
        'entities': entities_output,
        'metrics': metrics,
        'citations_by_event': citations_by_event
    }

    print(f"[Report SSE] Skeleton ready — {total_events} events, {len(citations_by_event)} citation groups")
    yield {"type": "skeleton", "payload": skeleton}

    # --- LLM generation (Steps 5-8) ---

    # Step 5: Event narratives
    print("[Report SSE] Generating event narratives...")
    for cat_data in categories_output:
        category = cat_data['category']
        events = events_by_category.get(category, [])
        for evt_idx, event in enumerate(events):
            if llm_available:
                narrative = generate_event_narrative(event, config)
                overview = narrative.get('overview', '')
                outcomes = narrative.get('outcomes', '')
            else:
                overview = event.get('description') or f"Event: {event['event_name']}"
                outcomes = "Analysis pending — LLM service unavailable."

            yield {
                "type": "event_narrative",
                "payload": {
                    "category": category,
                    "event_index": evt_idx,
                    "overview": overview,
                    "outcomes": outcomes
                }
            }

    # Step 6: Category narratives
    print("[Report SSE] Generating category narratives...")
    category_summaries = {}
    for cat_data in categories_output:
        category = cat_data['category']
        events = events_by_category.get(category, [])
        if not events:
            continue

        if llm_available:
            narrative = generate_category_narrative(
                country, category, events, source_map,
                documents_by_event, start_date, end_date
            )
        else:
            narrative = f"Key developments in {category} during this period included {len(events)} significant events."

        category_summaries[category] = narrative
        yield {
            "type": "category_narrative",
            "payload": {"category": category, "narrative": narrative}
        }

    # Step 7: Overall synthesis
    print("[Report SSE] Generating overall synthesis...")
    if llm_available:
        overall_summary = generate_overall_synthesis(
            country, category_summaries, start_date, end_date
        )
    else:
        overall_summary = (
            f"This report covers {country}'s strategic activities from {start_date} to {end_date}. "
            f"{total_events} events were identified across {len(events_by_category)} categories."
        )

    yield {
        "type": "overall_synthesis",
        "payload": {"overall_summary": overall_summary}
    }

    # Step 7b: Entity summaries
    if entities_output:
        print("[Report SSE] Generating entity summaries...")
        for type_idx, group in enumerate(entities_output):
            etype = group['entity_type'].upper()
            entities_raw = entities_by_type.get(etype, [])
            for ent_idx, entity in enumerate(entities_raw):
                if llm_available:
                    summary = generate_entity_summary(entity, country, start_date, end_date)
                else:
                    summary = f"{entity['name']} was mentioned in {entity['total_documents']} documents during this period."

                yield {
                    "type": "entity_summary",
                    "payload": {
                        "entity_type_index": type_idx,
                        "entity_index": ent_idx,
                        "summary": summary
                    }
                }

    # Step 8: Title
    if llm_available:
        print("[Report SSE] Generating title...")
        title = generate_publication_title(
            country, events_by_category, start_date, end_date
        )
    else:
        title = f"{country} Strategic Activities: {start_date.strftime('%B %Y')}"

    yield {"type": "title", "payload": {"title": title}}

    print("[Report SSE] Stream complete!")
    yield {"type": "complete", "payload": {}}
