"""
Dual Publication Generator: Summary + Review Versions

Generates two publication formats from consolidated canonical events:

1. SUMMARY VERSION (Narrative Format):
   - High-level strategic overview by category
   - Flowing narrative prose
   - Citations to source documents
   - Target audience: Executive briefing

2. REVIEW VERSION (Event-Centric Format):
   - Top events by article count and materiality score
   - Organized by category
   - Each event shows:
     * Event name and date range
     * Article count and materiality score
     * Overview and outcomes
     * Source document citations with hyperlinks
   - Target audience: Analysts for validation

Usage:
    python publications/scripts/generate_dual_publication.py \
        --country China \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --output-dir publications/China \
        --top-events 20

    # Only generate summary version
    python publications/scripts/generate_dual_publication.py \
        --country China \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --summary-only

    # Only generate review version
    python publications/scripts/generate_dual_publication.py \
        --country China \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --review-only
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
from datetime import datetime, date
from typing import List, Dict, Any
from collections import defaultdict
from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import Config, gai
from shared.utils.citation_utils import build_hyperlink


def parse_date(date_str: str) -> date:
    """Parse date string."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def get_top_events_by_category(
    session,
    country: str,
    start_date: date,
    end_date: date,
    top_n: int = 20
) -> Dict[str, List[Dict]]:
    """
    Get top N events per category, ranked by article count and materiality.
    Only includes master events (consolidated multi-day events).
    """

    # Load valid categories from config
    config = Config.from_yaml()
    valid_categories = config.categories

    events_by_category = defaultdict(list)

    for category in valid_categories:
        query = text("""
            SELECT
                ce.id,
                ce.canonical_name,
                ce.consolidated_description,
                ce.first_mention_date,
                ce.last_mention_date,
                ce.total_articles,
                ce.total_mention_days,
                ce.llm_validated,
                COALESCE(ce.materiality_score, 0) as materiality_score,
                -- Get all doc_ids from daily_event_mentions
                ARRAY_AGG(DISTINCT dem.doc_id) FILTER (WHERE dem.doc_id IS NOT NULL) as doc_ids
            FROM canonical_events ce
            LEFT JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
            LEFT JOIN categories cat ON dem.doc_id = ANY(
                SELECT doc_id FROM categories WHERE category = :category
            )
            WHERE ce.initiating_country = :country
                AND ce.master_event_id IS NULL  -- Only master events
                AND ce.first_mention_date <= :end_date
                AND ce.last_mention_date >= :start_date
                AND EXISTS (
                    SELECT 1 FROM categories c2
                    WHERE c2.doc_id = dem.doc_id
                    AND c2.category = :category
                )
            GROUP BY ce.id
            ORDER BY ce.total_articles DESC, materiality_score DESC
            LIMIT :top_n
        """)

        result = session.execute(query, {
            'country': country,
            'category': category,
            'start_date': start_date,
            'end_date': end_date,
            'top_n': top_n
        }).fetchall()

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
                'id': row.id,
                'event_name': row.canonical_name,
                'description': row.consolidated_description,
                'first_mention_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
                'last_mention_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
                'article_count': row.total_articles,
                'mention_days': row.total_mention_days,
                'materiality_score': float(row.materiality_score) if row.materiality_score else 0.0,
                'llm_validated': row.llm_validated,
                'doc_ids': list(set(doc_ids))  # Deduplicate
            })

    return events_by_category


def get_document_details(session, doc_ids: List[str]) -> List[Dict]:
    """Get document details for citations."""
    if not doc_ids:
        return []

    query = text("""
        SELECT
            d.doc_id,
            d.headline,
            d.source,
            d.url,
            d.date as published_date,
            d.salience,
            ARRAY_AGG(DISTINCT c.category) as categories,
            ARRAY_AGG(DISTINCT rc.recipient_country) as recipients
        FROM documents d
        LEFT JOIN categories c ON d.doc_id = c.doc_id
        LEFT JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE d.doc_id = ANY(:doc_ids)
        GROUP BY d.doc_id, d.headline, d.source, d.url, d.date, d.salience
        ORDER BY d.date DESC
    """)

    result = session.execute(query, {'doc_ids': doc_ids}).fetchall()

    documents = []
    for row in result:
        documents.append({
            'doc_id': row.doc_id,
            'headline': row.headline,
            'source_name': row.source,
            'source_url': row.url,
            'published_date': row.published_date.isoformat() if row.published_date else None,
            'salience': row.salience,
            'categories': row.categories or [],
            'recipients': row.recipients or []
        })

    return documents


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

        # Parse string response
        response_str = response.strip()
        if response_str.startswith("```json"):
            response_str = response_str[7:]
        if response_str.endswith("```"):
            response_str = response_str[:-3]

        return json.loads(response_str.strip())
    except Exception as e:
        print(f"  ⚠️  Error generating narrative for {event['event_name'][:50]}: {e}")
        return {
            'overview': event['description'] or f"Event: {event['event_name']}",
            'outcomes': "This event represents a significant development in regional engagement."
        }


def generate_review_version(
    summary_data: Dict,
    events_by_category: Dict[str, List[Dict]],
    documents_by_event: Dict[str, List[Dict]]
) -> Dict:
    """
    Generate Review version: same narrative as Summary but sources IMMEDIATELY after each section.
    Analysts can quickly verify claims without scrolling to end.
    """

    print("\n" + "="*80)
    print("GENERATING REVIEW VERSION (sources immediately accessible)")
    print("="*80)

    review_data = {
        'version': 'review',
        'country': summary_data['country'],
        'period_start': summary_data['period_start'],
        'period_end': summary_data['period_end'],
        'generated_at': datetime.now().isoformat(),
        'overall_summary': summary_data['overall_summary'],
        'categories': []
    }

    # Use the same source list from summary version (maintains same citation numbers)
    source_map = {s['doc_id']: s['citation_number'] for s in summary_data['sources']}

    # Process each category
    for category, narrative in summary_data['category_summaries'].items():
        events = events_by_category.get(category, [])

        if not events:
            continue

        print(f"\nProcessing {category}: {len(events)} events")

        # Collect sources for THIS category only
        category_sources = []
        for event in events[:10]:
            docs = documents_by_event.get(event['id'], [])

            for doc in docs[:5]:  # Top 5 sources per event
                doc_id = doc['doc_id']

                if doc_id in source_map:
                    # Find the source from summary data
                    source = next((s for s in summary_data['sources'] if s['doc_id'] == doc_id), None)

                    if source and source not in category_sources:
                        # Add event metrics
                        source_with_event = source.copy()
                        source_with_event['event_metrics'] = {
                            'article_count': event['article_count'],
                            'materiality_score': event['materiality_score']
                        }
                        category_sources.append(source_with_event)

        category_data = {
            'category': category,
            'narrative': narrative,  # SAME text as summary version (with [1], [2] citations)
            'sources': category_sources,  # Sources IMMEDIATELY after narrative
            'top_events': []
        }

        # Add top events with their metrics
        for event in events[:10]:
            category_data['top_events'].append({
                'event_name': event['event_name'],
                'date_range': f"{event['first_mention_date']} to {event['last_mention_date']}",
                'article_count': event['article_count'],
                'materiality_score': event['materiality_score'],
                'mention_days': event['mention_days']
            })

        review_data['categories'].append(category_data)

    print(f"\nReview version created with sources per category")

    return review_data


def generate_summary_version(
    country: str,
    start_date: date,
    end_date: date,
    events_by_category: Dict[str, List[Dict]],
    documents_by_event: Dict[str, List[Dict]],
    config: Config
) -> Dict:
    """Generate Summary version: narrative with inline citations [1], [2], sources at END."""

    print("\n" + "="*80)
    print("GENERATING SUMMARY VERSION (with citations)")
    print("="*80)

    # Build global source list
    all_sources = []
    source_counter = 1
    source_map = {}  # Maps doc_id -> citation number

    # First pass: collect all sources and assign citation numbers
    for category in config.categories:
        events = events_by_category.get(category, [])

        for event in events[:10]:  # Top 10 per category
            docs = documents_by_event.get(event['id'], [])

            for doc in docs[:5]:  # Top 5 docs per event
                doc_id = doc['doc_id']

                if doc_id not in source_map:
                    source_map[doc_id] = source_counter

                    # Build ATOM repository hyperlink using doc_id (UUID)
                    repo_hyperlink = build_hyperlink([doc_id])

                    all_sources.append({
                        'citation_number': source_counter,
                        'doc_id': doc_id,
                        'headline': doc['headline'],
                        'source_name': doc['source_name'],
                        'source_url': doc['source_url'],
                        'published_date': doc['published_date'],
                        'event_name': event['event_name'],
                        'repo_hyperlink': repo_hyperlink  # ATOM search hyperlink
                    })

                    source_counter += 1

    print(f"Total sources: {len(all_sources)}")

    # Generate category summaries with citation hints
    category_summaries = {}
    category_citations = {}  # Track which citations belong to which category

    for category in config.categories:
        events = events_by_category.get(category, [])

        if not events:
            continue

        print(f"\nGenerating {category} summary from {len(events)} events...")

        # Build event list with citation numbers
        event_list = []
        category_citation_nums = []

        for event in events[:10]:
            docs = documents_by_event.get(event['id'], [])
            citation_nums = [str(source_map[doc['doc_id']]) for doc in docs[:5] if doc['doc_id'] in source_map]

            if citation_nums:
                category_citation_nums.extend(citation_nums)
                citations_str = f" [Citations: {', '.join(citation_nums[:3])}]"
            else:
                citations_str = ""

            event_list.append(f"- {event['event_name']} ({event['article_count']} articles, materiality: {event['materiality_score']}/10){citations_str}")

        events_text = "\n".join(event_list)

        # Deduplicate and sort citation numbers
        category_citation_nums = sorted(set(category_citation_nums), key=int)
        category_citations[category] = category_citation_nums

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
            category_summaries[category] = narrative
        except Exception as e:
            print(f"  ⚠️  Error generating {category} summary: {e}")
            category_summaries[category] = f"Key developments in {category} during this period included significant diplomatic and strategic activities."

    # Generate overall synthesis
    print("\nGenerating overall synthesis...")

    category_text = "\n\n".join([f"**{cat}:**\n{summary}" for cat, summary in category_summaries.items()])

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
    except Exception as e:
        print(f"  ⚠️  Error generating overall summary: {e}")
        overall_summary = "This period saw significant strategic developments across multiple domains."

    summary_data = {
        'version': 'summary',
        'country': country,
        'period_start': start_date.isoformat(),
        'period_end': end_date.isoformat(),
        'generated_at': datetime.now().isoformat(),
        'overall_summary': overall_summary,
        'category_summaries': category_summaries,
        'sources': all_sources  # Sources at END for Summary version
    }

    return summary_data


def main():
    parser = argparse.ArgumentParser(
        description='Generate dual publications: Summary + Review versions'
    )
    parser.add_argument('--country', required=True, help='Country (e.g., China)')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--output-dir', default='publications', help='Output directory')
    parser.add_argument('--top-events', type=int, default=20, help='Top N events per category')
    parser.add_argument('--summary-only', action='store_true', help='Only generate summary version')
    parser.add_argument('--review-only', action='store_true', help='Only generate review version')

    args = parser.parse_args()

    # Parse dates
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    # Load config
    config = Config.from_yaml()

    print("="*80)
    print("DUAL PUBLICATION GENERATOR")
    print("="*80)
    print(f"Country: {args.country}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Top events per category: {args.top_events}")
    print("="*80)

    with get_session() as session:
        # Step 1: Get top events by category
        print("\nStep 1: Loading top events by category...")
        events_by_category = get_top_events_by_category(
            session,
            args.country,
            start_date,
            end_date,
            args.top_events
        )

        total_events = sum(len(events) for events in events_by_category.values())
        print(f"Loaded {total_events} events across {len(events_by_category)} categories")

        # Step 2: Get document details for each event
        print("\nStep 2: Loading source documents...")
        documents_by_event = {}

        for category, events in events_by_category.items():
            for event in events:
                if event['doc_ids']:
                    documents_by_event[event['id']] = get_document_details(
                        session,
                        event['doc_ids']
                    )

        total_docs = sum(len(docs) for docs in documents_by_event.values())
        print(f"Loaded {total_docs} source documents")

    # Step 3: Generate outputs
    output_dir = Path(args.output_dir) / args.country
    output_dir.mkdir(parents=True, exist_ok=True)

    # Always generate summary first (needed for review version)
    summary_data = generate_summary_version(
        args.country,
        start_date,
        end_date,
        events_by_category,
        documents_by_event,
        config
    )

    if not args.review_only:
        summary_file = output_dir / f"summary_{start_date}_{end_date}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Summary version saved: {summary_file}")

    if not args.summary_only:
        # Generate review version (same narrative, but with sources)
        review_data = generate_review_version(
            summary_data,
            events_by_category,
            documents_by_event
        )

        review_file = output_dir / f"review_{start_date}_{end_date}.json"
        with open(review_file, 'w', encoding='utf-8') as f:
            json.dump(review_data, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Review version saved: {review_file}")

    print("\n" + "="*80)
    print("GENERATION COMPLETE")
    print("="*80)


if __name__ == '__main__':
    main()
