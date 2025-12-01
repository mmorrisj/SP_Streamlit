"""
Generate comprehensive bilateral relationship summaries between country pairs.

This script:
1. Identifies all initiating-recipient country pairs with substantial interactions
2. Aggregates documents, events, and summaries for each pair
3. Uses AI to generate comprehensive relationship analysis
4. Stores in BilateralRelationshipSummary table

Usage:
    # Generate summary for specific country pair
    python generate_bilateral_summaries.py --init-country China --recipient-country Egypt

    # Generate all pairs for an initiating country
    python generate_bilateral_summaries.py --init-country China --min-docs 100

    # Generate summaries for all major country pairs (≥500 documents)
    python generate_bilateral_summaries.py --all --min-docs 500

    # Regenerate existing summary
    python generate_bilateral_summaries.py --init-country China --recipient-country Egypt --regenerate

    # Dry run (show what would be generated)
    python generate_bilateral_summaries.py --init-country China --recipient-country Egypt --dry-run

Example Output:
    China → Egypt: 4,774 documents
    - Time range: 2024-07-27 to 2025-10-15
    - Categories: Economic (2,850), Political (1,250), Educational (674)
    - Generated comprehensive relationship summary
"""

import sys
import argparse
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from sqlalchemy import select, text, func, and_
from sqlalchemy.orm import Session

# Configure stdout encoding for Unicode support on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.database.database import get_session
from shared.models.models import (
    BilateralRelationshipSummary, Document, EventSummary,
    PeriodType, EventSourceLink
)
from shared.utils.utils import gai, Config


# AI prompt for generating bilateral relationship summaries
BILATERAL_SUMMARY_PROMPT = """You are an expert analyst of international relations and soft power diplomacy.

Given comprehensive data about all interactions between {initiating_country} and {recipient_country}, generate a detailed analytical summary of their bilateral soft power relationship.

**DATA PROVIDED:**
- Time Period: {first_date} to {last_date}
- Total Documents: {total_docs:,}
- Total Events: {total_events:,} (Daily: {daily_events}, Weekly: {weekly_events}, Monthly: {monthly_events})

**Category Breakdown:**
{category_breakdown}

**Top Recipient Sub-groups (if applicable):**
{recipient_breakdown}

**Temporal Activity:**
{temporal_trends}

**Sample Recent Event Names:**
{recent_events}

**INSTRUCTIONS:**
Generate a comprehensive JSON response with the following structure:

{{
    "overview": "2-3 paragraph high-level summary of the relationship. Describe the nature, intensity, and strategic importance of {initiating_country}'s soft power engagement with {recipient_country}.",

    "key_themes": [
        "Theme 1: Brief description",
        "Theme 2: Brief description",
        "Theme 3: Brief description"
        // 3-5 dominant themes in this relationship
    ],

    "major_initiatives": [
        {{
            "name": "Initiative name",
            "description": "What it is and its significance",
            "timeframe": "When it occurred or is ongoing",
            "categories": ["Economic", "Educational"]
        }}
        // 3-7 most significant initiatives
    ],

    "trend_analysis": "Detailed analysis of how this relationship has evolved over time. Identify periods of intensification or decline. Note any shifts in focus areas or strategic priorities.",

    "current_status": "Assessment of the present state of the relationship. Is it active and growing? Stable? Declining? What are the current priorities?",

    "notable_developments": [
        "Specific development 1",
        "Specific development 2",
        "Specific development 3"
        // 5-8 specific noteworthy developments or events
    ],

    "material_assessment": {{
        "score": 0.75,  // 0.0 to 1.0, where 1.0 = highly material/significant relationship
        "justification": "Explanation of why this relationship rates this materiality score. Consider: volume of activity, strategic importance, resource commitments, geopolitical significance."
    }}
}}

**GUIDELINES:**
- Be factual and analytical, not speculative
- Focus on concrete initiatives and documented activities
- Identify patterns and trends in the data
- Assess strategic significance and geopolitical context
- Note any unusual or noteworthy aspects of this bilateral relationship
- Consider both the initiating country's goals and the recipient country's reception
- Use specific examples from the event names provided

Generate the JSON response now:"""


def get_country_pairs_with_minimum_docs(
    session: Session,
    min_docs: int = 100,
    initiating_country: Optional[str] = None,
    config: Optional[Config] = None
) -> List[Tuple[str, str, int]]:
    """
    Get all country pairs that have at least min_docs documents.

    Excludes pairs where initiating and recipient countries are the same.
    Filters by config influencers and recipients if config provided.

    Args:
        session: Database session
        min_docs: Minimum number of documents required
        initiating_country: If specified, only get pairs for this initiator
        config: Config object to filter by influencers/recipients

    Returns:
        List of tuples: (initiating_country, recipient_country, doc_count)
    """
    # Get country lists from config if provided
    if config:
        influencers = config.influencers if hasattr(config, 'influencers') else []
        recipients = config.recipients if hasattr(config, 'recipients') else []

        query = text("""
            SELECT
                ic.initiating_country,
                rc.recipient_country,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            WHERE (:init_country IS NULL OR ic.initiating_country = :init_country)
            AND ic.initiating_country = ANY(:influencers)
            AND rc.recipient_country = ANY(:recipients)
            AND ic.initiating_country != rc.recipient_country
            GROUP BY ic.initiating_country, rc.recipient_country
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        results = session.execute(
            query,
            {
                "init_country": initiating_country,
                "min_docs": min_docs,
                "influencers": influencers,
                "recipients": recipients
            }
        ).fetchall()
    else:
        # Original query without config filters
        query = text("""
            SELECT
                ic.initiating_country,
                rc.recipient_country,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            WHERE (:init_country IS NULL OR ic.initiating_country = :init_country)
            AND ic.initiating_country != rc.recipient_country
            GROUP BY ic.initiating_country, rc.recipient_country
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        results = session.execute(
            query,
            {"init_country": initiating_country, "min_docs": min_docs}
        ).fetchall()

    return [(row[0], row[1], row[2]) for row in results]


def gather_bilateral_data(
    session: Session,
    initiating_country: str,
    recipient_country: str
) -> Dict:
    """
    Gather all data about a bilateral relationship.

    Returns dict with:
    - total_documents
    - first_date, last_date
    - category_counts, subcategory_counts, source_counts
    - monthly_activity
    - event_counts (daily, weekly, monthly)
    - recent_event_samples
    """
    data = {}

    # Get document-level aggregations
    doc_query = text("""
        SELECT
            COUNT(DISTINCT d.doc_id) as total_docs,
            MIN(d.date) as first_date,
            MAX(d.date) as last_date
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
    """)

    result = session.execute(
        doc_query,
        {"init_country": initiating_country, "recip_country": recipient_country}
    ).fetchone()

    data['total_documents'] = result[0]
    data['first_date'] = result[1]
    data['last_date'] = result[2]

    # Get category breakdown
    cat_query = text("""
        SELECT
            c.category,
            COUNT(DISTINCT d.doc_id) as doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        GROUP BY c.category
        ORDER BY doc_count DESC
    """)

    cat_results = session.execute(
        cat_query,
        {"init_country": initiating_country, "recip_country": recipient_country}
    ).fetchall()

    data['category_counts'] = {row[0]: row[1] for row in cat_results}

    # Get subcategory breakdown
    subcat_query = text("""
        SELECT
            sc.subcategory,
            COUNT(DISTINCT d.doc_id) as doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN subcategories sc ON d.doc_id = sc.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        GROUP BY sc.subcategory
        ORDER BY doc_count DESC
        LIMIT 20
    """)

    subcat_results = session.execute(
        subcat_query,
        {"init_country": initiating_country, "recip_country": recipient_country}
    ).fetchall()

    data['subcategory_counts'] = {row[0]: row[1] for row in subcat_results}

    # Get source breakdown
    source_query = text("""
        SELECT
            d.source_name,
            COUNT(DISTINCT d.doc_id) as doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        AND d.source_name IS NOT NULL
        GROUP BY d.source_name
        ORDER BY doc_count DESC
        LIMIT 30
    """)

    source_results = session.execute(
        source_query,
        {"init_country": initiating_country, "recip_country": recipient_country}
    ).fetchall()

    data['source_counts'] = {row[0]: row[1] for row in source_results}

    # Get monthly activity (for trend analysis)
    monthly_query = text("""
        SELECT
            TO_CHAR(d.date, 'YYYY-MM') as month,
            COUNT(DISTINCT d.doc_id) as doc_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        GROUP BY TO_CHAR(d.date, 'YYYY-MM')
        ORDER BY month
    """)

    monthly_results = session.execute(
        monthly_query,
        {"init_country": initiating_country, "recip_country": recipient_country}
    ).fetchall()

    data['monthly_activity'] = {row[0]: row[1] for row in monthly_results}

    # Get event summary counts
    event_query = text("""
        SELECT
            es.period_type::text,
            COUNT(DISTINCT es.id) as event_count
        FROM event_summaries es
        WHERE es.initiating_country = :init_country
        AND es.count_by_recipient ? :recip_country
        GROUP BY es.period_type
    """)

    event_results = session.execute(
        event_query,
        {"init_country": initiating_country, "recip_country": recipient_country}
    ).fetchall()

    event_counts = {row[0]: row[1] for row in event_results}
    data['daily_events'] = event_counts.get('DAILY', 0)
    data['weekly_events'] = event_counts.get('WEEKLY', 0)
    data['monthly_events'] = event_counts.get('MONTHLY', 0)

    # Get sample recent events for context
    recent_events_query = text("""
        SELECT DISTINCT
            es.event_name,
            es.period_start
        FROM event_summaries es
        WHERE es.initiating_country = :init_country
        AND es.count_by_recipient ? :recip_country
        AND es.period_type = 'DAILY'
        ORDER BY es.period_start DESC
        LIMIT 20
    """)

    recent_results = session.execute(
        recent_events_query,
        {"init_country": initiating_country, "recip_country": recipient_country}
    ).fetchall()

    data['recent_events'] = [
        {"name": row[0], "date": row[1].strftime("%Y-%m-%d")}
        for row in recent_results
    ]

    return data


def format_bilateral_data_for_prompt(data: Dict) -> Dict[str, str]:
    """Format gathered data into prompt-friendly strings."""

    # Category breakdown
    cat_lines = []
    for cat, count in sorted(data['category_counts'].items(), key=lambda x: x[1], reverse=True):
        pct = (count / data['total_documents']) * 100
        cat_lines.append(f"  - {cat}: {count:,} documents ({pct:.1f}%)")
    category_breakdown = "\n".join(cat_lines) if cat_lines else "  No category data"

    # Subcategory breakdown (top recipients within recipient country)
    subcat_lines = []
    for subcat, count in list(data['subcategory_counts'].items())[:10]:
        pct = (count / data['total_documents']) * 100
        subcat_lines.append(f"  - {subcat}: {count:,} documents ({pct:.1f}%)")
    recipient_breakdown = "\n".join(subcat_lines) if subcat_lines else "  No subcategory data"

    # Temporal trends
    if data['monthly_activity']:
        months = sorted(data['monthly_activity'].keys())
        first_months = months[:3]
        last_months = months[-3:]

        trend_lines = []
        trend_lines.append("Early period (first 3 months):")
        for month in first_months:
            trend_lines.append(f"  {month}: {data['monthly_activity'][month]:,} documents")

        trend_lines.append("\nRecent period (last 3 months):")
        for month in last_months:
            trend_lines.append(f"  {month}: {data['monthly_activity'][month]:,} documents")

        avg_early = sum(data['monthly_activity'][m] for m in first_months) / len(first_months)
        avg_recent = sum(data['monthly_activity'][m] for m in last_months) / len(last_months)
        trend_lines.append(f"\nAverage: Early={avg_early:.0f}/month, Recent={avg_recent:.0f}/month")

        temporal_trends = "\n".join(trend_lines)
    else:
        temporal_trends = "No temporal data available"

    # Recent events
    event_lines = []
    for event in data['recent_events'][:10]:
        event_lines.append(f"  - {event['date']}: {event['name']}")
    recent_events = "\n".join(event_lines) if event_lines else "  No recent events"

    return {
        'category_breakdown': category_breakdown,
        'recipient_breakdown': recipient_breakdown,
        'temporal_trends': temporal_trends,
        'recent_events': recent_events
    }


def generate_bilateral_summary(
    session: Session,
    initiating_country: str,
    recipient_country: str,
    config: Config,
    dry_run: bool = False,
    regenerate: bool = False
) -> Optional[BilateralRelationshipSummary]:
    """
    Generate and store a bilateral relationship summary.

    Args:
        session: Database session
        initiating_country: Initiating country
        recipient_country: Recipient country
        config: Configuration object
        dry_run: If True, don't save to database
        regenerate: If True, update existing summary

    Returns:
        BilateralRelationshipSummary object or None
    """

    # Skip if initiating and recipient countries are the same
    if initiating_country == recipient_country:
        print(f"  ⏭️  Skipping same-country pair ({initiating_country} → {recipient_country})")
        return None

    # Check if summary already exists
    existing = session.query(BilateralRelationshipSummary).filter_by(
        initiating_country=initiating_country,
        recipient_country=recipient_country,
        is_deleted=False
    ).first()

    if existing and not regenerate:
        print(f"  ⚠️  Summary already exists (version {existing.version}). Use --regenerate to update.")
        return existing

    # Gather data
    print(f"  📊 Gathering bilateral data...")
    data = gather_bilateral_data(session, initiating_country, recipient_country)

    if data['total_documents'] == 0:
        print(f"  ⚠️  No documents found for this country pair.")
        return None

    print(f"  📈 Found {data['total_documents']:,} documents ({data['first_date']} to {data['last_date']})")
    print(f"  📅 Events: {data['daily_events']} daily, {data['weekly_events']} weekly, {data['monthly_events']} monthly")

    # Format data for prompt
    prompt_data = format_bilateral_data_for_prompt(data)

    # Generate AI summary
    print(f"  🤖 Generating AI summary...")

    prompt = BILATERAL_SUMMARY_PROMPT.format(
        initiating_country=initiating_country,
        recipient_country=recipient_country,
        first_date=data['first_date'].strftime("%Y-%m-%d"),
        last_date=data['last_date'].strftime("%Y-%m-%d"),
        total_docs=data['total_documents'],
        total_events=data['daily_events'] + data['weekly_events'] + data['monthly_events'],
        daily_events=data['daily_events'],
        weekly_events=data['weekly_events'],
        monthly_events=data['monthly_events'],
        **prompt_data
    )

    try:
        response = gai(
            sys_prompt="You are an expert analyst of international relations and soft power diplomacy. Output valid JSON only.",
            user_prompt=prompt,
            model="gpt-4o",
            use_proxy=True
        )

        # Handle response - gai() may return dict or string depending on use_proxy
        if isinstance(response, dict):
            relationship_summary = response
        else:
            relationship_summary = json.loads(response)

    except (json.JSONDecodeError, TypeError) as e:
        print(f"  ❌ Failed to parse AI response: {e}")
        print(f"  Raw response type: {type(response)}")
        print(f"  Raw response: {str(response)[:500]}...")
        return None

    # Extract material score
    material_score = relationship_summary.get('material_assessment', {}).get('score')
    material_justification = relationship_summary.get('material_assessment', {}).get('justification')

    if dry_run:
        print(f"\n  🔍 DRY RUN - Would create/update:")
        print(f"     Initiator: {initiating_country}")
        print(f"     Recipient: {recipient_country}")
        print(f"     Documents: {data['total_documents']:,}")
        print(f"     Material Score: {material_score}")
        print(f"     Overview: {relationship_summary.get('overview', '')[:200]}...")
        return None

    # Create or update summary
    if existing:
        print(f"  🔄 Updating existing summary (version {existing.version} → {existing.version + 1})")
        existing.last_interaction_date = data['last_date']
        existing.analysis_generated_at = datetime.utcnow()
        existing.total_documents = data['total_documents']
        existing.total_daily_events = data['daily_events']
        existing.total_weekly_events = data['weekly_events']
        existing.total_monthly_events = data['monthly_events']
        existing.count_by_category = data['category_counts']
        existing.count_by_subcategory = data['subcategory_counts']
        existing.count_by_source = data['source_counts']
        existing.activity_by_month = data['monthly_activity']
        existing.relationship_summary = relationship_summary
        existing.material_score = material_score
        existing.material_justification = material_justification
        existing.updated_at = datetime.utcnow()
        existing.version += 1

        summary = existing
    else:
        print(f"  ✨ Creating new bilateral summary")
        summary = BilateralRelationshipSummary(
            initiating_country=initiating_country,
            recipient_country=recipient_country,
            first_interaction_date=data['first_date'],
            last_interaction_date=data['last_date'],
            total_documents=data['total_documents'],
            total_daily_events=data['daily_events'],
            total_weekly_events=data['weekly_events'],
            total_monthly_events=data['monthly_events'],
            count_by_category=data['category_counts'],
            count_by_subcategory=data['subcategory_counts'],
            count_by_source=data['source_counts'],
            activity_by_month=data['monthly_activity'],
            relationship_summary=relationship_summary,
            material_score=material_score,
            material_justification=material_justification,
            created_by="generate_bilateral_summaries.py"
        )

        session.add(summary)

    session.commit()
    print(f"  ✅ Summary saved successfully!")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description='Generate bilateral relationship summaries between country pairs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--init-country',
        type=str,
        help='Initiating country'
    )

    parser.add_argument(
        '--recipient-country',
        type=str,
        help='Recipient country (if not specified, processes all recipients for init-country)'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Generate summaries for all country pairs meeting min-docs threshold'
    )

    parser.add_argument(
        '--min-docs',
        type=int,
        default=500,
        help='Minimum number of documents required (default: 500)'
    )

    parser.add_argument(
        '--regenerate',
        action='store_true',
        help='Regenerate existing summaries'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be generated without saving'
    )

    parser.add_argument(
        '--config',
        type=str,
        default='shared/config/config.yaml',
        help='Path to config file'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.all and not args.init_country:
        parser.error("Must specify either --init-country or --all")

    if args.recipient_country and not args.init_country:
        parser.error("--recipient-country requires --init-country")

    # Load config
    config = Config.from_yaml(args.config)

    print("=" * 80)
    print("BILATERAL RELATIONSHIP SUMMARY GENERATION")
    print("=" * 80)

    with get_session() as session:
        # Get country pairs to process
        if args.init_country and args.recipient_country:
            # Single specific pair
            pairs = [(args.init_country, args.recipient_country, None)]
        else:
            # Get all pairs meeting threshold
            print(f"\n🔍 Finding country pairs with ≥{args.min_docs} documents...")
            print(f"   (Filtering by config influencers/recipients)")
            pairs = get_country_pairs_with_minimum_docs(
                session,
                min_docs=args.min_docs,
                initiating_country=args.init_country,
                config=config
            )
            print(f"   Found {len(pairs)} country pairs")

        # Process each pair
        success_count = 0
        skip_count = 0
        error_count = 0

        for init_country, recip_country, doc_count in pairs:
            print(f"\n{'─' * 80}")
            print(f"🌍 {init_country} → {recip_country}")
            if doc_count:
                print(f"   {doc_count:,} documents")

            try:
                result = generate_bilateral_summary(
                    session,
                    init_country,
                    recip_country,
                    config,
                    dry_run=args.dry_run,
                    regenerate=args.regenerate
                )

                if result:
                    success_count += 1
                else:
                    skip_count += 1

            except Exception as e:
                print(f"  ❌ ERROR: {e}")
                error_count += 1
                continue

    # Summary
    print(f"\n{'=' * 80}")
    print(f"SUMMARY")
    print(f"{'=' * 80}")
    print(f"✅ Successfully generated: {success_count}")
    print(f"⏭️  Skipped: {skip_count}")
    print(f"❌ Errors: {error_count}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
