"""
Generate daily event summaries in AP style with full source traceability.

This script:
1. Queries master events active on each day for each country
2. Generates AP-style summaries (factual reporting, no analysis)
3. Creates ATOM hyperlinks to source documents
4. Generates formatted citations
5. Stores in EventSummary with complete source tracking via EventSourceLink

Usage:
    python generate_daily_summaries.py --country Iran --date 2024-08-15
    python generate_daily_summaries.py --country Iran --start-date 2024-08-01 --end-date 2024-08-31
    python generate_daily_summaries.py --influencers --start-date 2024-08-01 --end-date 2024-08-31
    python generate_daily_summaries.py --dry-run --country Iran --date 2024-08-15
"""

import sys
import io
import argparse
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

# Configure stdout encoding for Unicode support on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.database.database import get_session, get_engine
from shared.models.models import (
    CanonicalEvent, DailyEventMention, EventSummary, EventSourceLink,
    Document, PeriodType
)
from shared.utils.utils import gai, Config
from shared.utils.citation_utils import (
    build_hyperlink, get_citations_for_doc_ids
)
from summary_prompts import DAILY_SUMMARY_PROMPT


def get_active_master_events(
    session: Session,
    country: str,
    date: datetime,
    limit: int = 10  # Deprecated parameter kept for backward compatibility
) -> List[Dict]:
    """
    Get master events active on a specific day for a country.

    Now returns ALL events with ≥3 articles (changed from top 10 limit).

    Args:
        session: Database session
        country: Initiating country
        date: Date to query
        limit: DEPRECATED - No longer used, kept for backward compatibility

    Returns:
        List of dicts with event metadata and doc_ids (all events with ≥3 articles)
    """
    query = text("""
        WITH master_events AS (
            -- Get master events (master_event_id IS NULL) active on this date
            SELECT
                ce.id as master_id,
                ce.canonical_name,
                ce.primary_categories,
                ce.primary_recipients
            FROM canonical_events ce
            WHERE ce.master_event_id IS NULL
              AND ce.initiating_country = :country
              AND ce.first_mention_date <= :date
              AND ce.last_mention_date >= :date
        ),
        event_family AS (
            -- Get master events plus all their child events
            SELECT
                me.master_id,
                me.canonical_name,
                me.primary_categories,
                me.primary_recipients,
                ce.id as canonical_event_id
            FROM master_events me
            LEFT JOIN canonical_events ce ON (
                ce.master_event_id = me.master_id OR ce.id = me.master_id
            )
        ),
        daily_mentions AS (
            -- Get mentions for this date
            SELECT
                dem.canonical_event_id,
                dem.doc_ids
            FROM daily_event_mentions dem
            WHERE dem.mention_date = :date
        )
        SELECT
            ef.master_id,
            ef.canonical_name,
            ef.primary_categories,
            ef.primary_recipients,
            COALESCE(
                array_agg(DISTINCT unnested_doc ORDER BY unnested_doc) FILTER (WHERE unnested_doc IS NOT NULL),
                ARRAY[]::text[]
            ) as doc_ids,
            COUNT(DISTINCT unnested_doc) FILTER (WHERE unnested_doc IS NOT NULL) as article_count
        FROM event_family ef
        LEFT JOIN daily_mentions dm ON dm.canonical_event_id = ef.canonical_event_id
        LEFT JOIN LATERAL unnest(dm.doc_ids) unnested_doc ON true
        GROUP BY ef.master_id, ef.canonical_name, ef.primary_categories, ef.primary_recipients
        HAVING COUNT(DISTINCT unnested_doc) FILTER (WHERE unnested_doc IS NOT NULL) >= 3
        ORDER BY article_count DESC
    """)

    result = session.execute(
        query,
        {"country": country, "date": date}
    ).fetchall()

    events = []
    for row in result:
        events.append({
            "master_id": row.master_id,
            "canonical_name": row.canonical_name,
            "primary_categories": row.primary_categories,
            "primary_recipients": row.primary_recipients,
            "doc_ids": row.doc_ids,
            "article_count": row.article_count
        })

    return events


def select_representative_docs(
    session: Session,
    doc_ids: List[str],
    limit: int = 5
) -> List[Document]:
    """
    Select representative documents from a list of doc_ids.

    Strategy: Take first N documents ordered by date (most recent first)

    Args:
        session: Database session
        doc_ids: List of document IDs
        limit: Number of documents to select

    Returns:
        List of Document objects
    """
    if not doc_ids:
        return []

    stmt = (
        select(Document)
        .where(Document.doc_id.in_(doc_ids))
        .order_by(Document.date.desc())
        .limit(limit)
    )

    return list(session.execute(stmt).scalars().all())


def format_article_samples(documents: List[Document]) -> str:
    """
    Format documents for LLM prompt.

    Args:
        documents: List of Document objects

    Returns:
        Formatted string with numbered articles
    """
    samples = []
    for i, doc in enumerate(documents, 1):
        samples.append(f"""[{i}] {doc.title}
Source: {doc.source_name}
Date: {doc.date.strftime('%B %d, %Y') if doc.date else 'Unknown'}
Excerpt: {doc.distilled_text[:500] if doc.distilled_text else doc.title[:500] if doc.title else 'No text available'}...
""")

    return "\n".join(samples)


def generate_daily_summary_for_event(
    session: Session,
    event: Dict,
    country: str,
    date: datetime,
    dry_run: bool = False
) -> Optional[str]:
    """
    Generate AP-style daily summary for a single event.

    Args:
        session: Database session
        event: Event metadata dict
        country: Initiating country
        date: Date of summary
        dry_run: If True, don't write to database

    Returns:
        EventSummary ID if created, None if dry_run
    """
    print(f"\n{'='*80}")
    # Handle Unicode safely for Windows console
    event_name = event['canonical_name'].encode('ascii', 'replace').decode('ascii')
    print(f"Processing: {event_name}")
    print(f"Articles: {event['article_count']}")

    # Check if summary already exists
    existing_summary = session.query(EventSummary).filter(
        EventSummary.period_type == PeriodType.DAILY,
        EventSummary.period_start == date,
        EventSummary.period_end == date,
        EventSummary.initiating_country == country,
        EventSummary.event_name == event['canonical_name']
    ).first()

    if existing_summary:
        print(f"[SKIP] Summary already exists: {existing_summary.id}")
        return str(existing_summary.id) if not dry_run else None

    # Get representative documents
    representative_docs = select_representative_docs(
        session, event['doc_ids'], limit=5
    )

    if not representative_docs:
        print(f"[WARNING] No documents found for event, skipping")
        return None

    # Format article samples for prompt
    article_samples = format_article_samples(representative_docs)

    # Extract categories and recipients from JSONB
    categories = list(event['primary_categories'].keys()) if event['primary_categories'] else []
    recipients = list(event['primary_recipients'].keys()) if event['primary_recipients'] else []

    # Build prompt
    prompt = DAILY_SUMMARY_PROMPT.format(
        country=country,
        date=date.strftime('%B %d, %Y'),
        event_name=event['canonical_name'],
        article_count=event['article_count'],
        article_samples=article_samples,
        categories=', '.join(categories),
        recipients=', '.join(recipients)
    )

    # Call LLM
    print(f"Calling LLM for summary generation...")

    try:
        # Call LLM via FastAPI proxy
        response = gai(
            sys_prompt="You are an experienced journalist writing in Associated Press (AP) style. Follow the instructions exactly and output valid JSON only.",
            user_prompt=prompt,
            model="gpt-4o-mini",
            use_proxy=True
        )

        # Parse JSON response (handle both dict and string)
        if isinstance(response, str):
            # Try to extract JSON from markdown code blocks if present
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                response = json_match.group(1)
            summary_data = json.loads(response)
        else:
            summary_data = response

        print(f"[OK] Generated summary:")
        try:
            print(f"   Overview: {summary_data['overview'][:100]}...")
            print(f"   Outcomes: {summary_data['outcomes'][:100]}...")
        except UnicodeEncodeError:
            print(f"   Overview: [Unicode content - {len(summary_data['overview'])} chars]")
            print(f"   Outcomes: [Unicode content - {len(summary_data['outcomes'])} chars]")

    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse LLM response as JSON: {e}")
        try:
            print(f"   Response: {response[:500] if isinstance(response, str) else str(response)[:500]}...")
        except UnicodeEncodeError:
            print(f"   Response: [Unicode encoding error - response contains non-ASCII characters]")
        return None
    except Exception as e:
        try:
            print(f"[ERROR] LLM call failed: {e}")
        except UnicodeEncodeError:
            print(f"[ERROR] LLM call failed: [Unicode encoding error]")
        return None

    if dry_run:
        print(f"[DRY RUN] Would create EventSummary with {len(event['doc_ids'])} source links")
        return None

    # Filter out None values from doc_ids before processing
    valid_doc_ids = [doc_id for doc_id in event['doc_ids'] if doc_id is not None]

    # Build hyperlink and get citations
    source_link = build_hyperlink(valid_doc_ids)
    citations = get_citations_for_doc_ids(valid_doc_ids[:10])  # First 10 citations

    # Create EventSummary record
    event_summary = EventSummary(
        period_type=PeriodType.DAILY,
        period_start=date,
        period_end=date,
        event_name=event['canonical_name'],
        initiating_country=country,
        first_observed_date=date,  # For daily summaries, same as period_start
        last_observed_date=date,   # For daily summaries, same as period_end
        narrative_summary={
            'overview': summary_data['overview'],
            'outcomes': summary_data['outcomes'],
            'source_link': source_link,
            'source_count': len(valid_doc_ids),
            'citations': citations
        },
        count_by_category=event['primary_categories'] if event['primary_categories'] else {},
        count_by_recipient=event['primary_recipients'] if event['primary_recipients'] else {},
        total_documents_across_sources=len(valid_doc_ids)
    )

    session.add(event_summary)
    session.flush()  # Get ID

    print(f"[SAVED] Created EventSummary: {event_summary.id}")

    # Create EventSourceLink records for ALL valid doc_ids
    for doc_id in valid_doc_ids:
        # Weight: 1.0 for featured docs, 0.5 for others
        weight = 1.0 if doc_id in [d.doc_id for d in representative_docs] else 0.5

        link = EventSourceLink(
            event_summary_id=event_summary.id,
            doc_id=doc_id,
            contribution_weight=weight
        )
        session.add(link)

    print(f"[LINKS] Created {len(valid_doc_ids)} EventSourceLink records")

    return str(event_summary.id)


def generate_daily_summaries(
    country: str,
    start_date: datetime,
    end_date: datetime,
    dry_run: bool = False,
    limit_per_day: int = 10
):
    """
    Generate daily summaries for a country across a date range.

    Args:
        country: Initiating country
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        dry_run: If True, don't write to database
        limit_per_day: Maximum events to summarize per day
    """
    print(f"\n{'='*80}")
    print(f"DAILY SUMMARY GENERATION")
    print(f"{'='*80}")
    print(f"Country: {country}")
    print(f"Date Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Selection Criteria: All events with ≥3 articles")
    print(f"Dry Run: {dry_run}")
    print(f"{'='*80}\n")

    current_date = start_date
    total_summaries = 0

    with get_session() as session:
        while current_date <= end_date:
            print(f"\nProcessing {current_date.strftime('%Y-%m-%d')}...")

            # Get active master events for this day
            events = get_active_master_events(
                session, country, current_date, limit=limit_per_day
            )

            print(f"   Found {len(events)} active master events")

            if not events:
                print(f"   [WARNING] No events found for this day, skipping")
                current_date += timedelta(days=1)
                continue

            # Generate summary for each event
            day_summaries = 0
            for event in events:
                summary_id = generate_daily_summary_for_event(
                    session, event, country, current_date, dry_run=dry_run
                )
                if summary_id:
                    day_summaries += 1

            if not dry_run and day_summaries > 0:
                session.commit()
                print(f"\n[OK] Committed {day_summaries} summaries for {current_date.strftime('%Y-%m-%d')}")

            total_summaries += day_summaries
            current_date += timedelta(days=1)

    print(f"\n{'='*80}")
    print(f"SUMMARY GENERATION COMPLETE")
    print(f"{'='*80}")
    print(f"Total Summaries Created: {total_summaries}")
    print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Generate daily event summaries in AP style with source traceability"
    )

    # Date arguments
    parser.add_argument(
        '--date',
        type=str,
        help='Single date to process (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date (YYYY-MM-DD)'
    )

    # Country arguments
    parser.add_argument(
        '--country',
        type=str,
        help='Single country to process'
    )
    parser.add_argument(
        '--influencers',
        action='store_true',
        help='Process all influencer countries from config.yaml'
    )

    # Options
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test without writing to database'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='DEPRECATED: Now processes all events with ≥3 articles (parameter kept for backward compatibility)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not (args.country or args.influencers):
        parser.error("Must specify either --country or --influencers")

    if args.date and (args.start_date or args.end_date):
        parser.error("Cannot specify both --date and --start-date/--end-date")

    if not (args.date or (args.start_date and args.end_date)):
        parser.error("Must specify either --date or both --start-date and --end-date")

    # Parse dates
    if args.date:
        start_date = end_date = datetime.strptime(args.date, '%Y-%m-%d')
    else:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')

    # Get countries
    if args.country:
        countries = [args.country]
    else:
        config = Config.from_yaml('shared/config/config.yaml')
        countries = config.influencers

    # Process each country
    for country in countries:
        generate_daily_summaries(
            country=country,
            start_date=start_date,
            end_date=end_date,
            dry_run=args.dry_run,
            limit_per_day=args.limit
        )


if __name__ == "__main__":
    main()
