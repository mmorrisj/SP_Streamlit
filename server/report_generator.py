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
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from shared.database.database import get_session
from shared.utils.utils import Config, gai
from shared.utils.citation_utils import build_hyperlink
from shared.models.models import (
    Document, Category, Subcategory,
    InitiatingCountry, RecipientCountry
)


def _parse_entities_mentioned(entities_mentioned) -> List[Dict]:
    """
    Parse the canonical_events.entities_mentioned JSONB into a flat list
    of {name, entity_type, role} dicts for the frontend.
    """
    if not entities_mentioned:
        return []

    result = []
    type_map = {
        'persons': 'PERSON',
        'organizations': 'ORGANIZATION',
        'companies': 'COMPANY',
        'locations': 'LOCATION',
    }
    for json_key, entity_type in type_map.items():
        for ent in (entities_mentioned.get(json_key) or []):
            name = ent.get('entity_name') or ent.get('name')
            if name:
                result.append({
                    'name': name,
                    'entity_type': entity_type,
                    'role': ent.get('role') or ent.get('sector') or ent.get('type') or None,
                })
    return result


def _check_llm_availability() -> bool:
    """Quick check if the LLM proxy is reachable (< 2s timeout)."""
    import requests
    api_url = os.getenv('API_URL', '').strip()
    if not api_url:
        # Backward compat: try FASTAPI_URL and extract base
        fastapi_url = os.getenv('FASTAPI_URL', '').strip()
        if fastapi_url:
            api_url = fastapi_url.split('/proxy_query')[0].split('/material_query')[0]
        else:
            return False
    try:
        # Use HEAD/GET with a very short timeout just to check connectivity
        requests.get(f"{api_url.rstrip('/')}/docs", timeout=2)
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
                ce.material_justification,
                ce.entities_mentioned,
                (
                    SELECT ARRAY_AGG(DISTINCT d)
                    FROM daily_event_mentions dem2, unnest(dem2.doc_ids) as d
                    JOIN documents d2 ON d2.doc_id = d
                    WHERE dem2.canonical_event_id = ce.id
                    AND d2.date >= :start_date AND d2.date <= :end_date
                ) as doc_ids,
                (
                    SELECT COUNT(DISTINCT did)
                    FROM daily_event_mentions dem4, unnest(dem4.doc_ids) as did
                    JOIN categories c3 ON c3.doc_id = did
                    JOIN documents d3 ON d3.doc_id = did
                    WHERE dem4.canonical_event_id = ce.id
                    AND c3.category = :category
                    AND d3.date >= :start_date AND d3.date <= :end_date
                ) as category_doc_count,
                (
                    SELECT MIN(d5.date)
                    FROM daily_event_mentions dem5, unnest(dem5.doc_ids) as d5id
                    JOIN documents d5 ON d5.doc_id = d5id
                    WHERE dem5.canonical_event_id = ce.id
                    AND d5.date >= :start_date AND d5.date <= :end_date
                ) as period_first_date,
                (
                    SELECT MAX(d6.date)
                    FROM daily_event_mentions dem6, unnest(dem6.doc_ids) as d6id
                    JOIN documents d6 ON d6.doc_id = d6id
                    WHERE dem6.canonical_event_id = ce.id
                    AND d6.date >= :start_date AND d6.date <= :end_date
                ) as period_last_date,
                (
                    SELECT COUNT(DISTINCT d7)
                    FROM daily_event_mentions dem7, unnest(dem7.doc_ids) as d7
                    JOIN documents d7doc ON d7doc.doc_id = d7
                    WHERE dem7.canonical_event_id = ce.id
                    AND d7doc.date >= :start_date AND d7doc.date <= :end_date
                ) as period_article_count
            FROM canonical_events ce
            WHERE ce.initiating_country = :country
                AND ce.master_event_id IS NULL
                AND ce.first_mention_date >= :start_date
                AND ce.first_mention_date <= :end_date
                AND NOT (ce.primary_recipients ? :country)
                AND (
                    SELECT COUNT(DISTINCT d8)
                    FROM daily_event_mentions dem8, unnest(dem8.doc_ids) as d8
                    JOIN documents d8doc ON d8doc.doc_id = d8
                    WHERE dem8.canonical_event_id = ce.id
                    AND d8doc.date >= :start_date AND d8doc.date <= :end_date
                ) >= 2
                AND EXISTS (
                    SELECT 1
                    FROM daily_event_mentions dem3, unnest(dem3.doc_ids) as did
                    JOIN categories c2 ON c2.doc_id = did
                    JOIN documents d4 ON d4.doc_id = did
                    WHERE dem3.canonical_event_id = ce.id
                    AND c2.category = :category
                    AND d4.date >= :start_date AND d4.date <= :end_date
                )
                {recipient_clause}
            ORDER BY materiality_score DESC, period_article_count DESC
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

            # Use period-scoped dates and article count from date-filtered docs
            period_doc_count = len(set(doc_ids))
            period_first = row.period_first_date.isoformat() if row.period_first_date else (
                row.first_mention_date.isoformat() if row.first_mention_date else None
            )
            period_last = row.period_last_date.isoformat() if row.period_last_date else (
                row.last_mention_date.isoformat() if row.last_mention_date else None
            )

            events_by_category[category].append({
                'id': str(row.id),
                'event_name': row.canonical_name,
                'description': row.consolidated_description,
                'first_mention_date': period_first,
                'last_mention_date': period_last,
                'article_count': period_doc_count,
                'mention_days': row.total_mention_days or 0,
                'materiality_score': float(row.materiality_score) if row.materiality_score else 0.0,
                'material_justification': row.material_justification,
                'key_entities': _parse_entities_mentioned(row.entities_mentioned),
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
                ce.material_justification,
                ce.entities_mentioned,
                (
                    SELECT ARRAY_AGG(DISTINCT d)
                    FROM daily_event_mentions dem2, unnest(dem2.doc_ids) as d
                    JOIN documents d2 ON d2.doc_id = d
                    WHERE dem2.canonical_event_id = ce.id
                    AND d2.date >= :start_date AND d2.date <= :end_date
                ) as doc_ids,
                (
                    SELECT COUNT(DISTINCT did)
                    FROM daily_event_mentions dem4, unnest(dem4.doc_ids) as did
                    JOIN categories c3 ON c3.doc_id = did
                    JOIN documents d3 ON d3.doc_id = did
                    WHERE dem4.canonical_event_id = ce.id
                    AND c3.category = :category
                    AND d3.date >= :start_date AND d3.date <= :end_date
                ) as category_doc_count,
                (
                    SELECT MIN(d5.date)
                    FROM daily_event_mentions dem5, unnest(dem5.doc_ids) as d5id
                    JOIN documents d5 ON d5.doc_id = d5id
                    WHERE dem5.canonical_event_id = ce.id
                    AND d5.date >= :start_date AND d5.date <= :end_date
                ) as period_first_date,
                (
                    SELECT MAX(d6.date)
                    FROM daily_event_mentions dem6, unnest(dem6.doc_ids) as d6id
                    JOIN documents d6 ON d6.doc_id = d6id
                    WHERE dem6.canonical_event_id = ce.id
                    AND d6.date >= :start_date AND d6.date <= :end_date
                ) as period_last_date,
                (
                    SELECT COUNT(DISTINCT d7)
                    FROM daily_event_mentions dem7, unnest(dem7.doc_ids) as d7
                    JOIN documents d7doc ON d7doc.doc_id = d7
                    WHERE dem7.canonical_event_id = ce.id
                    AND d7doc.date >= :start_date AND d7doc.date <= :end_date
                ) as period_article_count
            FROM canonical_events ce
            WHERE ce.initiating_country = :country
                AND ce.master_event_id IS NULL
                AND ce.first_mention_date >= :start_date
                AND ce.first_mention_date <= :end_date
                AND ce.total_articles >= :min_articles
                AND NOT (ce.primary_recipients ? :country)
                AND (
                    SELECT COUNT(DISTINCT d8)
                    FROM daily_event_mentions dem8, unnest(dem8.doc_ids) as d8
                    JOIN documents d8doc ON d8doc.doc_id = d8
                    WHERE dem8.canonical_event_id = ce.id
                    AND d8doc.date >= :start_date AND d8doc.date <= :end_date
                ) >= 2
                AND EXISTS (
                    SELECT 1
                    FROM daily_event_mentions dem3, unnest(dem3.doc_ids) as did
                    JOIN categories c2 ON c2.doc_id = did
                    JOIN documents d4 ON d4.doc_id = did
                    WHERE dem3.canonical_event_id = ce.id
                    AND c2.category = :category
                    AND d4.date >= :start_date AND d4.date <= :end_date
                )
                {exclude_clause}
                {recipient_clause}
            ORDER BY materiality_score DESC, period_article_count DESC
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

            period_doc_count = len(set(doc_ids))
            period_first = row.period_first_date.isoformat() if row.period_first_date else (
                row.first_mention_date.isoformat() if row.first_mention_date else None
            )
            period_last = row.period_last_date.isoformat() if row.period_last_date else (
                row.last_mention_date.isoformat() if row.last_mention_date else None
            )

            new_event = {
                'id': str(row.id),
                'event_name': row.canonical_name,
                'description': row.consolidated_description,
                'first_mention_date': period_first,
                'last_mention_date': period_last,
                'article_count': period_doc_count,
                'mention_days': row.total_mention_days or 0,
                'materiality_score': float(row.materiality_score) if row.materiality_score else 0.0,
                'material_justification': row.material_justification,
                'key_entities': _parse_entities_mentioned(row.entities_mentioned),
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


def get_entities_for_events(
    session: Session,
    event_ids: List[str],
    country: str
) -> Dict[str, List[Dict]]:
    """
    For each event ID, find entities whose associated_events array contains that event.
    Returns a dict mapping event_id -> list of {name, entity_type, role}.
    """
    if not event_ids:
        return {}

    query = text("""
        SELECT
            ce.canonical_name,
            ce.entity_type::text as entity_type,
            ce.primary_role::text as primary_role,
            ce.associated_events
        FROM canonical_entities ce
        WHERE ce.initiating_country = :country
            AND ce.master_entity_id IS NULL
            AND ce.associated_events && :event_ids
    """)

    result = session.execute(query, {
        'country': country,
        'event_ids': event_ids
    }).fetchall()

    entities_by_event: Dict[str, List[Dict]] = defaultdict(list)
    for row in result:
        entity_info = {
            'name': row.canonical_name,
            'entity_type': row.entity_type or 'UNKNOWN',
            'role': row.primary_role,
        }
        if row.associated_events:
            for eid in event_ids:
                if eid in row.associated_events:
                    entities_by_event[eid].append(entity_info)

    return dict(entities_by_event)


def compute_metrics(
    session: Session,
    country: str,
    start_date: date,
    end_date: date,
    recipient: Optional[str],
    events_by_category: Dict[str, List[Dict]],
    valid_recipients: Optional[List[str]] = None,
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
    elif valid_recipients:
        recip_query = recip_query.filter(
            RecipientCountry.recipient_country.in_(valid_recipients),
            RecipientCountry.recipient_country != country
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


def compute_materiality_trends(
    session: Session,
    country: str,
    start_date: date,
    end_date: date,
    recipient: Optional[str] = None,
    valid_recipients: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute average materiality score over time by top recipients.
    Extends 3 months before start_date for comparison context.
    Returns {recipient_series, overall_series, significant_changes, trend_start}.
    """
    trend_start = start_date - timedelta(days=90)

    # Build recipient filter clause (always exclude self-references)
    if recipient:
        recip_filter = "AND r.key = :recipient"
    elif valid_recipients:
        recip_filter = "AND r.key = ANY(:valid_recipients) AND r.key != :country"
    else:
        recip_filter = "AND r.key != :country"

    query = text("""
        WITH recipient_events AS (
            SELECT
                ce.id,
                DATE_TRUNC('month', ce.first_mention_date)::date AS month,
                ce.material_score,
                r.key AS recipient
            FROM canonical_events ce,
                 jsonb_each_text(ce.primary_recipients) AS r(key, value)
            WHERE ce.initiating_country = :country
              AND ce.master_event_id IS NULL
              AND ce.material_score IS NOT NULL
              AND ce.first_mention_date >= :trend_start
              AND ce.first_mention_date <= :end_date
              {recipient_filter}
        ),
        top_recipients AS (
            SELECT recipient, COUNT(*) AS cnt
            FROM recipient_events
            GROUP BY recipient
            ORDER BY cnt DESC
            LIMIT 5
        )
        SELECT
            re.month,
            re.recipient,
            AVG(re.material_score)::numeric(4,2) AS avg_score,
            COUNT(*) AS event_count
        FROM recipient_events re
        JOIN top_recipients tr ON re.recipient = tr.recipient
        GROUP BY re.month, re.recipient
        ORDER BY re.month, re.recipient
    """.format(recipient_filter=recip_filter))

    params: Dict[str, Any] = {
        'country': country,
        'trend_start': trend_start,
        'end_date': end_date,
    }
    if recipient:
        params['recipient'] = recipient
    elif valid_recipients:
        params['valid_recipients'] = valid_recipients

    rows = session.execute(query, params).fetchall()

    # Also get overall monthly averages
    overall_query = text("""
        SELECT
            DATE_TRUNC('month', ce.first_mention_date)::date AS month,
            AVG(ce.material_score)::numeric(4,2) AS avg_score,
            COUNT(*) AS event_count
        FROM canonical_events ce
        WHERE ce.initiating_country = :country
          AND ce.master_event_id IS NULL
          AND ce.material_score IS NOT NULL
          AND ce.first_mention_date >= :trend_start
          AND ce.first_mention_date <= :end_date
        GROUP BY DATE_TRUNC('month', ce.first_mention_date)::date
        ORDER BY month
    """)
    overall_rows = session.execute(overall_query, {
        'country': country,
        'trend_start': trend_start,
        'end_date': end_date,
    }).fetchall()

    # Build recipient series: {recipient: [{month, avg_score, event_count}, ...]}
    recipient_series: Dict[str, list] = defaultdict(list)
    for row in rows:
        recipient_series[row.recipient].append({
            'month': row.month.isoformat(),
            'avg_score': float(row.avg_score),
            'event_count': int(row.event_count),
        })

    # Build overall series
    overall_series = [
        {
            'month': row.month.isoformat(),
            'avg_score': float(row.avg_score),
            'event_count': int(row.event_count),
        }
        for row in overall_rows
    ]

    # Detect significant changes (>1.5 point month-over-month shift)
    significant_changes = []
    for recip, series in recipient_series.items():
        for i in range(1, len(series)):
            prev = series[i - 1]['avg_score']
            curr = series[i]['avg_score']
            delta = curr - prev
            if abs(delta) >= 1.5:
                significant_changes.append({
                    'recipient': recip,
                    'month': series[i]['month'],
                    'previous_score': prev,
                    'current_score': curr,
                    'delta': round(delta, 2),
                    'direction': 'increase' if delta > 0 else 'decrease',
                })

    # Also check overall
    for i in range(1, len(overall_series)):
        prev = overall_series[i - 1]['avg_score']
        curr = overall_series[i]['avg_score']
        delta = curr - prev
        if abs(delta) >= 1.5:
            significant_changes.append({
                'recipient': 'Overall',
                'month': overall_series[i]['month'],
                'previous_score': prev,
                'current_score': curr,
                'delta': round(delta, 2),
                'direction': 'increase' if delta > 0 else 'decrease',
            })

    return {
        'trend_start': trend_start.isoformat(),
        'recipient_series': dict(recipient_series),
        'overall_series': overall_series,
        'significant_changes': significant_changes,
    }


def generate_event_narrative(
    event: Dict,
    config: Config,
    source_docs: Optional[List[Dict]] = None,
    source_map: Optional[Dict[str, int]] = None,
    model: str = "gpt-4o-mini"
) -> Dict[str, str]:
    """Generate Overview and Outcomes for an event using LLM, with inline citations."""

    # Build source context with citation numbers
    source_context = ""
    if source_docs and source_map:
        source_lines = []
        for doc in source_docs[:5]:
            cnum = source_map.get(doc['doc_id'])
            if cnum:
                source_lines.append(
                    f"  [{cnum}] \"{doc['headline']}\" — {doc['source_name']}, "
                    f"{doc.get('published_date', 'n.d.')}"
                )
        if source_lines:
            source_context = "\n\nSource Documents:\n" + "\n".join(source_lines)

    citation_instruction = ""
    if source_context:
        citation_instruction = (
            "\n\nIMPORTANT: Include inline citations [1], [2], etc. after factual claims, "
            "using the citation numbers from the Source Documents list. "
            "Every substantive claim must be attributed to at least one source."
        )

    sys_prompt = f"""You are an analyst writing a factual briefing. Your output must be strictly evidence-based.

Generate two sections:
1. OVERVIEW: State precisely what happened — name the specific actors, actions taken, dates, locations, and agreements or outcomes. 2-3 sentences.
2. OUTCOMES: State the documented results: agreements signed, funds committed, projects launched, statements issued, or positions taken. 2-3 sentences.

RULES:
- State what happened: name the actors, actions, agreements, dates, and places.
- Every substantive claim must have at least one citation.
- Do NOT speculate about motives, future outcomes, or strategic significance.
- Do NOT use "could", "might", "potentially", "is expected to", "remains to be seen", "signals", "underscores", "highlights".
- Do NOT use filler like "significant development", "key milestone", "growing importance", "deepening ties", "further illustrating".
- Do NOT editorialize or assess significance — report the facts only.{citation_instruction}"""

    user_prompt = f"""Event: {event['event_name']}
Description: {event['description']}
Date Range: {event['first_mention_date']} to {event['last_mention_date']}
Coverage: {event['article_count']} articles over {event['mention_days']} days{source_context}

Generate Overview and Outcomes.
Return JSON: {{"overview": "...", "outcomes": "..."}}"""

    try:
        response = gai(sys_prompt, user_prompt, model=model)

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
            'outcomes': "Detailed outcomes not available."
        }


def generate_category_narrative(
    country: str,
    category: str,
    events: List[Dict],
    source_map: Dict[str, int],
    documents_by_event: Dict[str, List[Dict]],
    start_date: date,
    end_date: date,
    model: str = "gpt-4o"
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

    sys_prompt = """You are an analyst writing a factual category summary for a policy briefing.

Generate a narrative paragraph (4-6 sentences) that summarizes the key events and documented actions in this category.

IMPORTANT: Include inline citations [1], [2], [3] etc. after factual claims, using the citation numbers from the event list.

RULES:
- State what happened: name the actors, actions, agreements, dates, and places.
- Every substantive claim must have at least one citation.
- Do NOT speculate about motives, future outcomes, or strategic significance.
- Do NOT use "could", "might", "potentially", "is expected to", "signals", "underscores", "highlights".
- Do NOT use filler like "significant development", "key milestone", "growing importance".
- Connect events by shared actors, regions, or subject matter — not by editorial assessment."""

    user_prompt = f"""Category: {category}
Period: {start_date} to {end_date}
Country: {country}

Top Events (with citation numbers):
{events_text}

Write a factual summary paragraph with inline citations [1], [2], etc."""

    try:
        response = gai(sys_prompt, user_prompt, model=model)
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
    end_date: date,
    model: str = "gpt-4o"
) -> str:
    """Generate overall strategic synthesis from category narratives."""

    category_text = "\n\n".join([
        f"**{cat}:**\n{summary}"
        for cat, summary in category_summaries.items()
    ])

    sys_prompt = """You are an analyst writing an executive summary for a policy briefing.

Synthesize the category summaries into a cohesive factual overview (3-4 paragraphs).

IMPORTANT: Preserve all inline citations [1], [2], etc. from the category summaries.

Structure:
1. Opening paragraph: Summarize the principal activities and actors during this period.
2. Body paragraphs: Group related developments across categories by theme or region.
3. Closing paragraph: State documented trends (e.g., increasing/decreasing activity in specific areas) based on the evidence presented.

RULES:
- State what happened: name the actors, actions, agreements, dates, and places.
- Report only what the category summaries state. Do not add speculation or editorial assessment.
- Do NOT use "could", "might", "potentially", "is expected to", "signals", "underscores", "highlights".
- Do NOT use filler like "significant development", "key milestone", "growing importance", "deepening ties", "expanding presence".
- Do NOT predict future outcomes or assess strategic significance beyond what the sources document.
- Connect developments by shared actors, regions, or subject matter — not by editorial assessment.
- Preserve every [#] citation from the input."""

    user_prompt = f"""Country: {country}
Period: {start_date} to {end_date}

Category Summaries (with citations):
{category_text}

Write a factual synthesis. Preserve all [#] citations."""

    try:
        overall_summary = gai(sys_prompt, user_prompt, model=model)
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
    end_date: date,
    model: str = "gpt-4o-mini"
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
        response = gai(sys_prompt, user_prompt, model=model)
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
                ) as doc_ids,
                (
                    SELECT COUNT(DISTINCT d)
                    FROM daily_entity_mentions dem3, unnest(dem3.doc_ids) as d
                    WHERE dem3.canonical_entity_id = ce.id
                    AND dem3.mention_date >= :start_date
                    AND dem3.mention_date <= :end_date
                ) as period_doc_count,
                (
                    SELECT COUNT(DISTINCT dem4.mention_date)
                    FROM daily_entity_mentions dem4
                    WHERE dem4.canonical_entity_id = ce.id
                    AND dem4.mention_date >= :start_date
                    AND dem4.mention_date <= :end_date
                ) as period_mention_days
            FROM canonical_entities ce
            WHERE ce.initiating_country = :country
                AND ce.master_entity_id IS NULL
                AND ce.entity_type = :entity_type
                AND ce.first_mention_date <= :end_date
                AND ce.last_mention_date >= :start_date
                {recipient_clause}
            ORDER BY period_doc_count DESC, ce.total_documents DESC
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
                'total_documents': row.period_doc_count or 0,
                'total_mention_days': row.period_mention_days or 0,
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


def generate_entity_summary(
    entity: Dict,
    country: str,
    start_date: date,
    end_date: date,
    source_docs: Optional[List[Dict]] = None,
    source_map: Optional[Dict[str, int]] = None,
    model: str = "gpt-4o-mini"
) -> str:
    """Generate a brief summary of an entity's role during the time period, with citations."""

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

    # Build source context with citation numbers
    source_context = ""
    citation_instruction = ""
    if source_docs and source_map:
        source_lines = []
        for doc in source_docs[:5]:
            cnum = source_map.get(doc['doc_id'])
            if cnum:
                source_lines.append(
                    f"  [{cnum}] \"{doc['headline']}\" — {doc['source_name']}, "
                    f"{doc.get('published_date', 'n.d.')}"
                )
        if source_lines:
            source_context = "\nSource Documents:\n" + "\n".join(source_lines)
            citation_instruction = (
                "\nInclude inline citations [1], [2], etc. from the Source Documents "
                "after factual claims."
            )

    sys_prompt = f"""You are an analyst. Write a concise 2-3 sentence factual summary of this entity's
documented activities during the specified period.

RULES:
- State what the entity did: meetings attended, agreements signed, statements made, projects involved in.
- Name specific counterparts, dates, locations, and outcomes where available.
- Do NOT speculate about motives, influence, or future impact.
- Do NOT use "could", "might", "potentially", "is expected to", "signals", "underscores", "highlights".
- Do NOT use "significant", "key player", "instrumental", "pivotal", "growing importance", "deepening ties", or similar editorializing.
- Report the facts only — do not assess strategic significance.{citation_instruction}"""

    user_prompt = f"""Entity: {entity['name']}
Type: {entity['entity_type']}
Role: {entity.get('role') or 'Unknown'}
Country Context: {country}
Period: {start_date} to {end_date}
Documents: {entity['total_documents']} across {entity['total_mention_days']} days
Categories: {categories_str}
Recipients: {recipients_str}
Existing Description: {entity.get('description') or 'None'}{source_context}

Write a factual summary of this entity's documented activities during this period."""

    try:
        response = gai(sys_prompt, user_prompt, model=model)
        summary = response if isinstance(response, str) else str(response)
        return summary.strip()
    except Exception as e:
        print(f"  Warning: Error generating entity summary for {entity['name']}: {e}")
        desc = entity.get('description') or ''
        if desc:
            return desc
        return f"{entity['name']} was mentioned in {entity['total_documents']} documents during this period."


def get_lookback_events(
    session: Session,
    country: str,
    start_date: date,
    end_date: date,
    events_by_category: Dict[str, List[Dict]],
    recipient: Optional[str] = None,
    max_per_event: int = 5,
) -> List[Dict]:
    """
    Find events in the 3-month lookback window related to report-period events.
    Returns list of groups: each group maps a report event to its prior related events.

    Three-tier matching (cheapest first):
    1. Master-chain: shared master_event_id hierarchy
    2. Shared entities: 2+ overlapping person/org names
    3. Category + recipient overlap
    """
    lookback_start = start_date - timedelta(days=90)
    lookback_end = start_date - timedelta(days=1)

    # Collect all report events with metadata
    report_events = []
    for category, events in events_by_category.items():
        for event in events:
            report_events.append({**event, 'category': category})

    if not report_events:
        return []

    report_event_ids = [e['id'] for e in report_events]
    # Track which lookback event IDs are already matched (to avoid duplicates)
    already_matched_ids = set()
    # Map: report_event_id -> list of lookback event dicts
    matches_by_report_event = defaultdict(list)

    # --- Tier 1: Master-chain match ---
    try:
        master_chain_query = text("""
            WITH report_masters AS (
                SELECT id, COALESCE(master_event_id::text, id::text) as effective_master
                FROM canonical_events
                WHERE id::text = ANY(:report_ids)
            )
            SELECT DISTINCT ON (ce.id)
                ce.id::text as id,
                ce.canonical_name,
                ce.consolidated_description,
                ce.first_mention_date,
                ce.last_mention_date,
                ce.total_articles,
                COALESCE(ce.material_score, 0) as materiality_score,
                ce.entities_mentioned,
                rm.id::text as matched_report_event_id,
                (
                    SELECT ARRAY_AGG(DISTINCT d)
                    FROM daily_event_mentions dem, unnest(dem.doc_ids) as d
                    WHERE dem.canonical_event_id = ce.id
                    AND dem.mention_date >= :lookback_start
                    AND dem.mention_date <= :lookback_end
                ) as doc_ids
            FROM canonical_events ce
            JOIN report_masters rm
                ON COALESCE(ce.master_event_id::text, ce.id::text) = rm.effective_master
            WHERE ce.initiating_country = :country
                AND ce.id::text != ALL(:report_ids)
                AND ce.first_mention_date >= :lookback_start
                AND ce.first_mention_date <= :lookback_end
                AND ce.total_articles >= 2
            ORDER BY ce.id, ce.material_score DESC NULLS LAST
        """)

        master_results = session.execute(master_chain_query, {
            'report_ids': report_event_ids,
            'country': country,
            'lookback_start': lookback_start,
            'lookback_end': lookback_end,
        }).fetchall()

        for row in master_results:
            lb_id = row.id
            if lb_id in already_matched_ids:
                continue
            already_matched_ids.add(lb_id)

            doc_ids = []
            if row.doc_ids:
                for d in row.doc_ids:
                    if isinstance(d, list):
                        doc_ids.extend(d)
                    else:
                        doc_ids.append(d)

            matches_by_report_event[row.matched_report_event_id].append({
                'event_name': row.canonical_name,
                'description': row.consolidated_description,
                'first_mention_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
                'last_mention_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
                'article_count': row.total_articles or 0,
                'materiality_score': float(row.materiality_score),
                'match_type': 'master_chain',
                'shared_entities': [],
                'doc_ids': list(set(doc_ids))[:10],
            })

        print(f"[Lookback] Tier 1 (master chain): {len(master_results)} matches")
    except Exception as e:
        print(f"[Lookback] Tier 1 error: {e}")

    # --- Tier 2: Shared entities (2+ person/org names in common) ---
    try:
        # Build entity name sets for each report event
        report_event_entities = {}
        for evt in report_events:
            entities_mentioned = evt.get('key_entities', [])
            names = set()
            for ent in entities_mentioned:
                if ent.get('entity_type') in ('PERSON', 'ORGANIZATION', 'COMPANY'):
                    name = ent.get('name') or ent.get('entity_name', '')
                    if name:
                        names.add(name.strip())
            if names:
                report_event_entities[evt['id']] = names

        if report_event_entities:
            # Query lookback events with their entities
            entity_query = text("""
                SELECT
                    ce.id::text as id,
                    ce.canonical_name,
                    ce.consolidated_description,
                    ce.first_mention_date,
                    ce.last_mention_date,
                    ce.total_articles,
                    COALESCE(ce.material_score, 0) as materiality_score,
                    ce.entities_mentioned,
                    (
                        SELECT ARRAY_AGG(DISTINCT d)
                        FROM daily_event_mentions dem, unnest(dem.doc_ids) as d
                        WHERE dem.canonical_event_id = ce.id
                        AND dem.mention_date >= :lookback_start
                        AND dem.mention_date <= :lookback_end
                    ) as doc_ids
                FROM canonical_events ce
                WHERE ce.initiating_country = :country
                    AND ce.master_event_id IS NULL
                    AND ce.first_mention_date >= :lookback_start
                    AND ce.first_mention_date <= :lookback_end
                    AND ce.total_articles >= 2
                    AND ce.id::text != ALL(:already_matched)
                    AND ce.id::text != ALL(:report_ids)
                ORDER BY ce.material_score DESC NULLS LAST
                LIMIT 200
            """)

            entity_results = session.execute(entity_query, {
                'country': country,
                'lookback_start': lookback_start,
                'lookback_end': lookback_end,
                'already_matched': list(already_matched_ids),
                'report_ids': report_event_ids,
            }).fetchall()

            tier2_count = 0
            for row in entity_results:
                lb_id = row.id
                if lb_id in already_matched_ids:
                    continue

                # Parse lookback event entity names
                lb_names = set()
                em = row.entities_mentioned or {}
                for key in ('persons', 'organizations', 'companies'):
                    for ent in (em.get(key) or []):
                        name = ent.get('entity_name', '').strip()
                        if name:
                            lb_names.add(name)

                # Find report events sharing 2+ entities
                for re_id, re_names in report_event_entities.items():
                    shared = re_names & lb_names
                    if len(shared) >= 2:
                        already_matched_ids.add(lb_id)

                        doc_ids = []
                        if row.doc_ids:
                            for d in row.doc_ids:
                                if isinstance(d, list):
                                    doc_ids.extend(d)
                                else:
                                    doc_ids.append(d)

                        matches_by_report_event[re_id].append({
                            'event_name': row.canonical_name,
                            'description': row.consolidated_description,
                            'first_mention_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
                            'last_mention_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
                            'article_count': row.total_articles or 0,
                            'materiality_score': float(row.materiality_score),
                            'match_type': 'shared_entities',
                            'shared_entities': list(shared)[:5],
                            'doc_ids': list(set(doc_ids))[:10],
                        })
                        tier2_count += 1
                        break  # One match per lookback event

            print(f"[Lookback] Tier 2 (shared entities): {tier2_count} matches")
    except Exception as e:
        print(f"[Lookback] Tier 2 error: {e}")

    # --- Tier 3: Category + recipient overlap ---
    try:
        # Build category->recipient mapping from report events
        cat_recipient_map = defaultdict(set)
        for evt in report_events:
            cat = evt['category']
            # Get recipients from key_entities or from the event's doc metadata
            em = evt.get('key_entities', [])
            for ent in em:
                if ent.get('entity_type') == 'LOCATION':
                    cat_recipient_map[cat].add(ent.get('name', ''))

        # Also try primary_recipients if available at the event level
        # The events have doc_ids but not direct recipient info — use category only
        if cat_recipient_map:
            for category, recipients in cat_recipient_map.items():
                recipients_list = [r for r in recipients if r]
                if not recipients_list:
                    continue

                tier3_query = text("""
                    SELECT
                        ce.id::text as id,
                        ce.canonical_name,
                        ce.consolidated_description,
                        ce.first_mention_date,
                        ce.last_mention_date,
                        ce.total_articles,
                        COALESCE(ce.material_score, 0) as materiality_score,
                        (
                            SELECT ARRAY_AGG(DISTINCT d)
                            FROM daily_event_mentions dem, unnest(dem.doc_ids) as d
                            WHERE dem.canonical_event_id = ce.id
                            AND dem.mention_date >= :lookback_start
                            AND dem.mention_date <= :lookback_end
                        ) as doc_ids
                    FROM canonical_events ce
                    WHERE ce.initiating_country = :country
                        AND ce.master_event_id IS NULL
                        AND ce.first_mention_date >= :lookback_start
                        AND ce.first_mention_date <= :lookback_end
                        AND ce.total_articles >= 2
                        AND ce.id::text != ALL(:already_matched)
                        AND ce.id::text != ALL(:report_ids)
                        AND ce.primary_categories ? :category
                        AND ce.primary_recipients ?| :recipients
                    ORDER BY ce.material_score DESC NULLS LAST
                    LIMIT 10
                """)

                tier3_results = session.execute(tier3_query, {
                    'country': country,
                    'lookback_start': lookback_start,
                    'lookback_end': lookback_end,
                    'already_matched': list(already_matched_ids),
                    'report_ids': report_event_ids,
                    'category': category,
                    'recipients': recipients_list,
                }).fetchall()

                # Assign tier 3 matches to the first report event in this category
                cat_report_events = [e for e in report_events if e['category'] == category]
                if not cat_report_events:
                    continue

                for row in tier3_results:
                    lb_id = row.id
                    if lb_id in already_matched_ids:
                        continue
                    already_matched_ids.add(lb_id)

                    doc_ids = []
                    if row.doc_ids:
                        for d in row.doc_ids:
                            if isinstance(d, list):
                                doc_ids.extend(d)
                            else:
                                doc_ids.append(d)

                    # Assign to the highest-materiality report event in same category
                    target_evt = max(cat_report_events, key=lambda e: e['materiality_score'])
                    matches_by_report_event[target_evt['id']].append({
                        'event_name': row.canonical_name,
                        'description': row.consolidated_description,
                        'first_mention_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
                        'last_mention_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
                        'article_count': row.total_articles or 0,
                        'materiality_score': float(row.materiality_score),
                        'match_type': 'category_recipient',
                        'shared_entities': [],
                        'doc_ids': list(set(doc_ids))[:10],
                    })

        print(f"[Lookback] Tier 3 (category+recipient): done")
    except Exception as e:
        print(f"[Lookback] Tier 3 error: {e}")

    # Build grouped output, sorted by materiality, capped at max_per_event
    groups = []
    report_events_by_id = {e['id']: e for e in report_events}
    for re_id, lb_events in matches_by_report_event.items():
        re = report_events_by_id.get(re_id)
        if not re or not lb_events:
            continue

        # Sort by materiality desc, cap
        sorted_lb = sorted(lb_events, key=lambda e: e['materiality_score'], reverse=True)[:max_per_event]

        groups.append({
            'report_event_name': re['event_name'],
            'report_event_category': re['category'],
            'lookback_events': sorted_lb,
        })

    # Sort groups by report event materiality desc
    groups.sort(key=lambda g: next(
        (e['materiality_score'] for e in report_events if e['event_name'] == g['report_event_name']), 0
    ), reverse=True)

    total_lb = sum(len(g['lookback_events']) for g in groups)
    print(f"[Lookback] Total: {total_lb} lookback events across {len(groups)} report event groups")
    return groups


def generate_lookback_narrative(
    country: str,
    lookback_groups: List[Dict],
    start_date: date,
    end_date: date,
    source_map: Dict[str, int],
    lookback_docs_by_event: Dict[str, List[Dict]],
    model: str = "gpt-4o"
) -> str:
    """
    Generate a cited narrative connecting lookback events to report events.
    Follows the same citation pattern as category narratives.
    """
    if not lookback_groups:
        return ""

    group_texts = []
    for group in lookback_groups:
        report_name = group['report_event_name']
        lookback_items = []
        for lb_evt in group['lookback_events'][:5]:
            # Build citation numbers from this lookback event's docs
            docs = lookback_docs_by_event.get(lb_evt['event_name'], [])
            citation_nums = [
                str(source_map[doc['doc_id']])
                for doc in docs[:5]
                if doc['doc_id'] in source_map
            ]
            citations_str = ""
            if citation_nums:
                citations_str = f" [Citations: {', '.join(citation_nums[:3])}]"

            lookback_items.append(
                f"  - {lb_evt['event_name']} "
                f"({lb_evt['first_mention_date']} to {lb_evt['last_mention_date']}, "
                f"{lb_evt['article_count']} articles, "
                f"materiality: {lb_evt['materiality_score']}/10"
                f"{', shared entities: ' + ', '.join(lb_evt['shared_entities']) if lb_evt.get('shared_entities') else ''}"
                f"){citations_str}"
            )

        if lookback_items:
            group_texts.append(
                f"Current Report Event: {report_name}\n"
                f"Prior Developments:\n" + "\n".join(lookback_items)
            )

    if not group_texts:
        return ""

    all_groups_text = "\n\n".join(group_texts)
    lookback_start = start_date - timedelta(days=90)
    lookback_end_date = start_date - timedelta(days=1)

    sys_prompt = """You are an analyst writing a historical context section for a policy briefing.

Your task: For each current report event, state what happened in the lookback period that is
factually connected. Report the prior developments chronologically using AP style.

Structure your output as paragraphs, one per report event that has prior developments.
Begin each paragraph by naming the current report event, then state the prior actions,
agreements, meetings, or announcements with specific actors, dates, locations, and figures.

IMPORTANT: Include inline citations [1], [2], [3] etc. after factual claims, using the citation
numbers from the prior developments list.

RULES:
- State what happened: name the actors, actions, agreements, dates, and places.
- Every substantive claim must have at least one citation.
- Do NOT speculate about motives, strategy, or future outcomes.
- Do NOT interpret or characterize what events "illustrate", "signal", "underscore", or "highlight".
- Do NOT use "could", "might", "potentially", "is expected to", "further demonstrating", "reflecting".
- Do NOT use filler like "significant development", "key milestone", "growing importance", "deepening ties", "expanding presence".
- Connect events by shared actors, regions, or subject matter — not by editorial assessment.
- Keep each paragraph to 3-5 sentences."""

    user_prompt = f"""Country: {country}
Report Period: {start_date} to {end_date}
Lookback Period: {lookback_start} to {lookback_end_date}

{all_groups_text}

Write the Historical Context section with inline citations."""

    try:
        response = gai(sys_prompt, user_prompt, model=model)
        narrative = response if isinstance(response, str) else str(response)
        return narrative.strip()
    except Exception as e:
        print(f"  Warning: Error generating lookback narrative: {e}")
        return ""


def generate_report(
    country: str,
    start_date_str: str,
    end_date_str: str,
    recipient: Optional[str] = None,
    top_n: int = 10,
    model: str = "gpt-4o-mini",
    quarterly: bool = False,
    include_events: bool = True,
    include_entities: bool = True,
    include_metrics: bool = True,
    include_persons: bool = True,
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
                'materiality_trends': {
                    'trend_start': (start_date - timedelta(days=90)).isoformat(),
                    'recipient_series': {},
                    'overall_series': [],
                    'significant_changes': []
                },
                'citations_by_event': [],
                'entities': [],
                'historical_context': None,
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
        if include_metrics:
            print("[Report] Computing metrics...")
            metrics = compute_metrics(
                session, country, start_date, end_date, recipient, events_by_category,
                valid_recipients=config.recipients
            )
        else:
            print("[Report] Skipping metrics (disabled)")
            metrics = {
                'total_documents': 0, 'total_events': 0,
                'category_distribution': [], 'subcategory_distribution': [],
                'recipient_distribution': [], 'materiality_histogram': []
            }

        # Step 3b: Get top entities
        if include_entities or include_persons:
            print("[Report] Loading top entities...")
            entities_by_type = get_top_entities(
                session, country, start_date, end_date, recipient, top_n=5
            )
            # Filter based on toggles
            if not include_persons:
                entities_by_type.pop('PERSON', None)
            if not include_entities:
                for etype in ['ORGANIZATION', 'COMPANY', 'LOCATION']:
                    entities_by_type.pop(etype, None)
            total_entities = sum(len(ents) for ents in entities_by_type.values())
            print(f"[Report] Found {total_entities} entities across {len(entities_by_type)} types")
        else:
            print("[Report] Skipping entities (disabled)")
            entities_by_type = {}

        # Step 3c: Compute materiality trends
        if include_metrics:
            print("[Report] Computing materiality trends...")
            materiality_trends = compute_materiality_trends(
                session, country, start_date, end_date, recipient,
                valid_recipients=config.recipients
            )
            print(f"[Report] Materiality trends: {len(materiality_trends['overall_series'])} months, "
                  f"{len(materiality_trends['significant_changes'])} significant changes")
        else:
            materiality_trends = {
                'trend_start': (start_date - timedelta(days=90)).isoformat(),
                'recipient_series': {},
                'overall_series': [],
                'significant_changes': []
            }

        # Load entity document details for citation support
        entity_docs_by_id = {}
        if entities_by_type:
            print("[Report] Loading entity source documents...")
        for etype, entities in entities_by_type.items():
            for entity in entities:
                if entity.get('doc_ids'):
                    entity_docs_by_id[entity['id']] = get_document_details(
                        session, entity['doc_ids'][:5]
                    )

        # Step 3d: Historical lookback (quarterly reports only)
        lookback_groups = []
        lookback_docs_by_event = {}
        if quarterly:
            print("[Report] Finding historical lookback events...")
            lookback_groups = get_lookback_events(
                session, country, start_date, end_date, events_by_category, recipient
            )
            # Load documents for lookback events
            if lookback_groups:
                print("[Report] Loading lookback source documents...")
                for group in lookback_groups:
                    for lb_evt in group['lookback_events']:
                        if lb_evt.get('doc_ids'):
                            lookback_docs_by_event[lb_evt['event_name']] = get_document_details(
                                session, lb_evt['doc_ids'][:5]
                            )

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

    # Add entity docs to source map
    for entity_id, docs in entity_docs_by_id.items():
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

    # Add lookback docs to source map (quarterly only)
    if quarterly and lookback_docs_by_event:
        for evt_name, docs in lookback_docs_by_event.items():
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

    # Step 5: Generate event narratives (use cached EventSummary when available)
    category_summaries = {}
    if include_events:
        # Pre-load cached narratives from EventSummary table
        cached_narratives = {}
        try:
            from shared.models.models import EventSummary as ES, PeriodType as PT
            all_event_names = [e['event_name'] for evts in events_by_category.values() for e in evts]
            if all_event_names:
                cached_rows = session.execute(text("""
                    SELECT DISTINCT ON (event_name)
                        event_name, narrative_summary
                    FROM event_summaries
                    WHERE initiating_country = :country
                      AND event_name = ANY(:names)
                      AND is_deleted = false
                      AND narrative_summary IS NOT NULL
                    ORDER BY event_name, period_start DESC
                """), {"country": country, "names": all_event_names}).fetchall()
                for row in cached_rows:
                    ns = row.narrative_summary or {}
                    if ns.get("overview"):
                        cached_narratives[row.event_name] = ns
                print(f"[Report] Found {len(cached_narratives)}/{len(all_event_names)} cached EventSummary narratives")
        except Exception as e:
            print(f"[Report] Could not load cached narratives: {e}")

        if llm_available:
            print("[Report] Generating event narratives...")
            for category, events in events_by_category.items():
                for event in events:
                    cached = cached_narratives.get(event['event_name'])
                    # Only use cache if it contains inline citations [N]
                    has_citations = (
                        cached
                        and re.search(r'\[\d+\]', cached.get('overview', ''))
                    )
                    if has_citations:
                        event['overview'] = cached.get('overview', '')
                        event['outcomes'] = cached.get('outcomes', '')
                    else:
                        event_docs = documents_by_event.get(event['id'], [])
                        narrative = generate_event_narrative(
                            event, config, source_docs=event_docs, source_map=source_map,
                            model=model
                        )
                        event['overview'] = narrative.get('overview', '')
                        event['outcomes'] = narrative.get('outcomes', '')
        else:
            print("[Report] Skipping event narratives (LLM unavailable)")
            for category, events in events_by_category.items():
                for event in events:
                    cached = cached_narratives.get(event['event_name'])
                    if cached:
                        event['overview'] = cached.get('overview', '')
                        event['outcomes'] = cached.get('outcomes', '')
                    else:
                        event['overview'] = event.get('description') or f"Event: {event['event_name']}"
                        event['outcomes'] = "Analysis pending — LLM service unavailable."

        # Step 6: Generate category narratives
        if llm_available:
            print("[Report] Generating category narratives...")
            for category in config.categories:
                events = events_by_category.get(category, [])
                if not events:
                    continue
                narrative = generate_category_narrative(
                    country, category, events, source_map,
                    documents_by_event, start_date, end_date,
                    model=model
                )
                category_summaries[category] = narrative
        else:
            print("[Report] Skipping category narratives (LLM unavailable)")
            for category in config.categories:
                events = events_by_category.get(category, [])
                if events:
                    category_summaries[category] = f"Key developments in {category} during this period included {len(events)} events."
    else:
        print("[Report] Skipping event/category narratives (disabled)")

    # Step 7: Generate overall synthesis
    if llm_available:
        print("[Report] Generating overall synthesis...")
        overall_summary = generate_overall_synthesis(
            country, category_summaries, start_date, end_date,
            model=model
        )
    else:
        print("[Report] Skipping overall synthesis (LLM unavailable)")
        overall_summary = f"This report covers {country}'s strategic activities from {start_date} to {end_date}. {total_events} events were identified across {len(events_by_category)} categories."

    # Step 7a.5: Generate lookback narrative (quarterly only)
    lookback_narrative = None
    if quarterly and lookback_groups:
        if llm_available:
            print("[Report] Generating historical context narrative...")
            lookback_narrative = generate_lookback_narrative(
                country, lookback_groups, start_date, end_date,
                source_map, lookback_docs_by_event, model=model
            )
        else:
            lookback_narrative = ""

    # Step 7b: Generate entity summaries
    entities_output = []
    if entities_by_type:
        print("[Report] Generating entity summaries...")
    else:
        print("[Report] Skipping entity summaries (none requested)")
    for etype, entities in entities_by_type.items():
        entity_list = []
        for entity in entities:
            if llm_available:
                ent_docs = entity_docs_by_id.get(entity['id'], [])
                summary = generate_entity_summary(
                    entity, country, start_date, end_date,
                    source_docs=ent_docs, source_map=source_map,
                    model=model
                )
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
            country, events_by_category, start_date, end_date,
            model=model
        )
    else:
        title = f"{country} Strategic Activities: {start_date.strftime('%B %Y')}"

    # Step 9: Build categories output (sorted by materiality desc)
    categories_output = []
    if not include_events:
        print("[Report] Skipping categories output (events disabled)")
    for category in (config.categories if include_events else []):
        events = events_by_category.get(category, [])
        if not events:
            continue

        sorted_events = sorted(events, key=lambda e: e['materiality_score'], reverse=True)
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
                    'material_justification': e.get('material_justification'),
                    'key_entities': e.get('key_entities', []),
                    'doc_ids': e['doc_ids']
                }
                for e in sorted_events
            ]
        })

    # Step 10: Build citations grouped by event (includes entity citations)
    citations_by_event = _build_citations_output(
        config, events_by_category, documents_by_event, source_map,
        entities_by_type=entities_by_type, entity_docs_by_id=entity_docs_by_id
    )

    # Add lookback citations (quarterly only)
    if quarterly and lookback_docs_by_event:
        lookback_citations = []
        for group in lookback_groups:
            for lb_evt in group['lookback_events']:
                docs = lookback_docs_by_event.get(lb_evt['event_name'], [])
                evt_cits = []
                for doc in docs[:5]:
                    doc_id = doc['doc_id']
                    if doc_id in source_map:
                        evt_cits.append({
                            'citation_number': source_map[doc_id],
                            'doc_id': doc_id,
                            'headline': doc['headline'],
                            'source_name': doc['source_name'],
                            'published_date': doc['published_date'],
                            'categories': doc['categories'],
                            'recipients': doc['recipients'],
                            'repo_hyperlink': build_hyperlink([doc_id])
                        })
                if evt_cits:
                    lookback_citations.append({
                        'event_name': lb_evt['event_name'],
                        'materiality_score': lb_evt['materiality_score'],
                        'date_range': f"{lb_evt['first_mention_date']} to {lb_evt['last_mention_date']}",
                        'citations': evt_cits
                    })
        if lookback_citations:
            citations_by_event.append({
                'category': 'Historical Context',
                'events': lookback_citations
            })

    # Build historical context payload
    historical_context = None
    if quarterly and lookback_groups:
        historical_context = {
            'lookback_start': (start_date - timedelta(days=90)).isoformat(),
            'lookback_end': (start_date - timedelta(days=1)).isoformat(),
            'groups': lookback_groups,
            'narrative': lookback_narrative,
        }

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
        'materiality_trends': materiality_trends,
        'citations_by_event': citations_by_event,
        'historical_context': historical_context,
    }

    print("[Report] Generation complete!")
    return report


def _build_citations_output(
    config: Config,
    events_by_category: Dict[str, List[Dict]],
    documents_by_event: Dict[str, List[Dict]],
    source_map: Dict[str, int],
    entities_by_type: Optional[Dict[str, List[Dict]]] = None,
    entity_docs_by_id: Optional[Dict[str, List[Dict]]] = None
) -> list:
    """Build citations grouped by category/event, plus entity citations."""
    citations_by_event = []

    # Event citations grouped by category
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

    # Entity citations — collect docs unique to entities (not already in event citations)
    if entities_by_type and entity_docs_by_id:
        cited_doc_ids = set()
        for group in citations_by_event:
            for evt in group['events']:
                for cit in evt['citations']:
                    cited_doc_ids.add(cit['doc_id'])

        entity_citations = []
        for etype, entities in entities_by_type.items():
            for entity in entities:
                docs = entity_docs_by_id.get(entity['id'], [])
                ent_cits = []
                for doc in docs[:5]:
                    doc_id = doc['doc_id']
                    if doc_id in source_map and doc_id not in cited_doc_ids:
                        ent_cits.append({
                            'citation_number': source_map[doc_id],
                            'doc_id': doc_id,
                            'headline': doc['headline'],
                            'source_name': doc['source_name'],
                            'published_date': doc['published_date'],
                            'categories': doc['categories'],
                            'recipients': doc['recipients'],
                            'repo_hyperlink': build_hyperlink([doc_id])
                        })
                        cited_doc_ids.add(doc_id)
                if ent_cits:
                    entity_citations.extend(ent_cits)

        if entity_citations:
            entity_citations.sort(key=lambda c: c['citation_number'])
            citations_by_event.append({
                'category': 'Key Entities',
                'events': [{
                    'event_name': 'Entity References',
                    'materiality_score': 0,
                    'date_range': '',
                    'citations': entity_citations
                }]
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
    top_n: int = 10,
    model: str = "gpt-4o-mini",
    quarterly: bool = False,
    include_events: bool = True,
    include_entities: bool = True,
    include_metrics: bool = True,
    include_persons: bool = True,
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
                'materiality_trends': {
                    'trend_start': (start_date - timedelta(days=90)).isoformat(),
                    'recipient_series': {},
                    'overall_series': [],
                    'significant_changes': []
                },
                'citations_by_event': [],
                'historical_context': None,
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

        if include_metrics:
            print("[Report SSE] Computing metrics...")
            metrics = compute_metrics(
                session, country, start_date, end_date, recipient, events_by_category,
                valid_recipients=config.recipients
            )
        else:
            metrics = {
                'total_documents': 0, 'total_events': 0,
                'category_distribution': [], 'subcategory_distribution': [],
                'recipient_distribution': [], 'materiality_histogram': []
            }

        if include_entities or include_persons:
            print("[Report SSE] Loading entities...")
            entities_by_type = get_top_entities(
                session, country, start_date, end_date, recipient, top_n=5
            )
            if not include_persons:
                entities_by_type.pop('PERSON', None)
            if not include_entities:
                for etype in ['ORGANIZATION', 'COMPANY', 'LOCATION']:
                    entities_by_type.pop(etype, None)
        else:
            entities_by_type = {}

        # Materiality trends
        if include_metrics:
            print("[Report SSE] Computing materiality trends...")
            materiality_trends = compute_materiality_trends(
                session, country, start_date, end_date, recipient,
                valid_recipients=config.recipients
            )
        else:
            materiality_trends = {
                'trend_start': (start_date - timedelta(days=90)).isoformat(),
                'recipient_series': {},
                'overall_series': [],
                'significant_changes': []
            }

        # Load entity document details for citation support
        entity_docs_by_id = {}
        if entities_by_type:
            print("[Report SSE] Loading entity source documents...")
            for etype, entities in entities_by_type.items():
                for entity in entities:
                    if entity.get('doc_ids'):
                        entity_docs_by_id[entity['id']] = get_document_details(
                            session, entity['doc_ids'][:5]
                        )

        # Historical lookback (quarterly only)
        lookback_groups = []
        lookback_docs_by_event = {}
        if quarterly:
            print("[Report SSE] Finding historical lookback events...")
            lookback_groups = get_lookback_events(
                session, country, start_date, end_date, events_by_category, recipient
            )
            if lookback_groups:
                print("[Report SSE] Loading lookback source documents...")
                for group in lookback_groups:
                    for lb_evt in group['lookback_events']:
                        if lb_evt.get('doc_ids'):
                            lookback_docs_by_event[lb_evt['event_name']] = get_document_details(
                                session, lb_evt['doc_ids'][:5]
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

    # Add entity docs to source map
    for entity_id, docs in entity_docs_by_id.items():
        for doc in docs[:5]:
            doc_id = doc['doc_id']
            if doc_id not in source_map:
                source_map[doc_id] = source_counter
                source_counter += 1

    # Add lookback docs to source map (quarterly only)
    if quarterly and lookback_docs_by_event:
        for evt_name, docs in lookback_docs_by_event.items():
            for doc in docs[:5]:
                doc_id = doc['doc_id']
                if doc_id not in source_map:
                    source_map[doc_id] = source_counter
                    source_counter += 1

    # Build skeleton (sorted by materiality desc)
    categories_output = []
    for category in (config.categories if include_events else []):
        events = events_by_category.get(category, [])
        if not events:
            continue
        sorted_events = sorted(events, key=lambda e: e['materiality_score'], reverse=True)
        # Update events_by_category with sorted order so SSE streaming follows same order
        events_by_category[category] = sorted_events
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
                    'material_justification': e.get('material_justification'),
                    'key_entities': e.get('key_entities', []),
                    'doc_ids': e['doc_ids']
                }
                for e in sorted_events
            ]
        })

    entities_output = _build_entities_skeleton(entities_by_type, source_map)
    citations_by_event = _build_citations_output(
        config, events_by_category, documents_by_event, source_map,
        entities_by_type=entities_by_type, entity_docs_by_id=entity_docs_by_id
    )

    # Add lookback citations (quarterly only)
    if quarterly and lookback_docs_by_event:
        lookback_citations = []
        for group in lookback_groups:
            for lb_evt in group['lookback_events']:
                docs = lookback_docs_by_event.get(lb_evt['event_name'], [])
                evt_cits = []
                for doc in docs[:5]:
                    doc_id = doc['doc_id']
                    if doc_id in source_map:
                        evt_cits.append({
                            'citation_number': source_map[doc_id],
                            'doc_id': doc_id,
                            'headline': doc['headline'],
                            'source_name': doc['source_name'],
                            'published_date': doc['published_date'],
                            'categories': doc['categories'],
                            'recipients': doc['recipients'],
                            'repo_hyperlink': build_hyperlink([doc_id])
                        })
                if evt_cits:
                    lookback_citations.append({
                        'event_name': lb_evt['event_name'],
                        'materiality_score': lb_evt['materiality_score'],
                        'date_range': f"{lb_evt['first_mention_date']} to {lb_evt['last_mention_date']}",
                        'citations': evt_cits
                    })
        if lookback_citations:
            citations_by_event.append({
                'category': 'Historical Context',
                'events': lookback_citations
            })

    # Build historical context for skeleton (narrative null — will be streamed later)
    historical_context = None
    if quarterly and lookback_groups:
        historical_context = {
            'lookback_start': (start_date - timedelta(days=90)).isoformat(),
            'lookback_end': (start_date - timedelta(days=1)).isoformat(),
            'groups': lookback_groups,
            'narrative': None,
        }

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
        'materiality_trends': materiality_trends,
        'citations_by_event': citations_by_event,
        'historical_context': historical_context,
    }

    print(f"[Report SSE] Skeleton ready — {total_events} events, {len(citations_by_event)} citation groups")
    yield {"type": "skeleton", "payload": skeleton}

    # --- LLM generation (Steps 5-8) ---

    category_summaries = {}
    if include_events:
        # Pre-load cached narratives from EventSummary table
        stream_cached_narratives = {}
        try:
            all_evt_names = [e['event_name'] for evts in events_by_category.values() for e in evts]
            if all_evt_names:
                cached_rows = session.execute(text("""
                    SELECT DISTINCT ON (event_name)
                        event_name, narrative_summary
                    FROM event_summaries
                    WHERE initiating_country = :country
                      AND event_name = ANY(:names)
                      AND is_deleted = false
                      AND narrative_summary IS NOT NULL
                    ORDER BY event_name, period_start DESC
                """), {"country": country, "names": all_evt_names}).fetchall()
                for row in cached_rows:
                    ns = row.narrative_summary or {}
                    if ns.get("overview"):
                        stream_cached_narratives[row.event_name] = ns
                print(f"[Report SSE] Found {len(stream_cached_narratives)}/{len(all_evt_names)} cached narratives")
        except Exception as e:
            print(f"[Report SSE] Could not load cached narratives: {e}")

        # Step 5: Event narratives (use cache first, LLM as fallback)
        print("[Report SSE] Generating event narratives...")
        for cat_data in categories_output:
            category = cat_data['category']
            events = events_by_category.get(category, [])
            for evt_idx, event in enumerate(events):
                cached = stream_cached_narratives.get(event['event_name'])
                # Only use cache if it contains inline citations [N]
                has_citations = (
                    cached
                    and re.search(r'\[\d+\]', cached.get('overview', ''))
                )
                if has_citations:
                    overview = cached.get('overview', '')
                    outcomes = cached.get('outcomes', '')
                elif llm_available:
                    event_docs = documents_by_event.get(event['id'], [])
                    narrative = generate_event_narrative(
                        event, config, source_docs=event_docs, source_map=source_map,
                        model=model
                    )
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
        for cat_data in categories_output:
            category = cat_data['category']
            events = events_by_category.get(category, [])
            if not events:
                continue

            if llm_available:
                narrative = generate_category_narrative(
                    country, category, events, source_map,
                    documents_by_event, start_date, end_date,
                    model=model
                )
            else:
                narrative = f"Key developments in {category} during this period included {len(events)} events."

            category_summaries[category] = narrative
            yield {
                "type": "category_narrative",
                "payload": {"category": category, "narrative": narrative}
            }
    else:
        print("[Report SSE] Skipping event/category narratives (disabled)")

    # Step 7: Overall synthesis
    print("[Report SSE] Generating overall synthesis...")
    if llm_available:
        overall_summary = generate_overall_synthesis(
            country, category_summaries, start_date, end_date,
            model=model
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

    # Step 7a.5: Historical context narrative (quarterly only)
    if quarterly and lookback_groups:
        if llm_available:
            print("[Report SSE] Generating historical context narrative...")
            lookback_narrative = generate_lookback_narrative(
                country, lookback_groups, start_date, end_date,
                source_map, lookback_docs_by_event, model=model
            )
        else:
            lookback_narrative = ""

        yield {
            "type": "historical_context",
            "payload": {"narrative": lookback_narrative}
        }

    # Step 7b: Entity summaries
    if entities_output:
        print("[Report SSE] Generating entity summaries...")
        for type_idx, group in enumerate(entities_output):
            etype = group['entity_type'].upper()
            entities_raw = entities_by_type.get(etype, [])
            for ent_idx, entity in enumerate(entities_raw):
                if llm_available:
                    ent_docs = entity_docs_by_id.get(entity['id'], [])
                    summary = generate_entity_summary(
                        entity, country, start_date, end_date,
                        source_docs=ent_docs, source_map=source_map,
                        model=model
                    )
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
            country, events_by_category, start_date, end_date,
            model=model
        )
    else:
        title = f"{country} Strategic Activities: {start_date.strftime('%B %Y')}"

    yield {"type": "title", "payload": {"title": title}}

    print("[Report SSE] Stream complete!")
    yield {"type": "complete", "payload": {}}
