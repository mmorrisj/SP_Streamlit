"""
Generate country-level category-specific summaries.

Creates AI-powered summaries for how each country deploys specific categories of soft power
across all their recipient relationships (e.g., "China's Economic soft power", "Russia's Military soft power").

Usage:
    # Single country-category combination
    python services/pipeline/summaries/generate_country_category_summaries.py \
        --country China --category Economic

    # All categories for a country
    python services/pipeline/summaries/generate_country_category_summaries.py \
        --country China --all-categories

    # All countries and all categories with minimum docs
    python services/pipeline/summaries/generate_country_category_summaries.py \
        --all --min-docs 500

    # Regenerate existing summaries
    python services/pipeline/summaries/generate_country_category_summaries.py \
        --all --min-docs 500 --regenerate
"""

import sys
import argparse
import json
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.database.database import get_session
from shared.models.models import CountryCategorySummary
from shared.utils.utils import Config, gai


# AI Prompt for country category analysis
COUNTRY_CATEGORY_SUMMARY_PROMPT = """You are analyzing **{country}'s** use of **{category}** soft power across all recipient countries.

**TIME PERIOD:** {first_date} to {last_date}

**DATA PROVIDED:**
- Total Documents: {total_docs:,}
- Total Events: {total_events:,} (Daily: {daily_events}, Weekly: {weekly_events}, Monthly: {monthly_events})
- Number of Recipient Countries: {num_recipients}
- Top Recipients: {top_recipients}
- Subcategory Distribution: {subcategory_breakdown}
- Source Distribution: {source_breakdown}
- Monthly Activity Trend: {monthly_trend}
- Material Score: Avg {material_avg:.2f}, Median {material_median:.2f} (from {material_count} scored events)

**Sample Recent Event Names ({category} category only):**
{recent_events}

**TASK:**
Analyze how {country} deploys **{category}** soft power as a strategic tool.

**OUTPUT FORMAT (JSON only, no markdown):**
{{
    "overview": "2-3 sentences summarizing {country}'s overall {category} soft power strategy and approach",
    "key_strategies": ["specific strategy 1", "specific strategy 2", "..."],
    "top_recipients": [
        {{"country": "recipient name", "focus_areas": "what {category} activities focus on", "intensity": "high/medium/low"}},
        ...
    ],
    "major_initiatives": [
        {{"name": "initiative name", "description": "what it involves", "timeframe": "when it occurred"}},
        ...
    ],
    "trend_analysis": "How {country}'s use of {category} soft power has evolved over time",
    "effectiveness_assessment": "Evidence of impact and outcomes of {category} initiatives",
    "material_assessment": {{
        "score": <float between 0.0 and 1.0>,
        "justification": "Why this score reflects the materiality of {country}'s {category} soft power"
    }}
}}

**INSTRUCTIONS:**
- Focus ONLY on the {category} category - ignore other categories
- Be specific about subcategories (e.g., within Economic: Trade, Infrastructure, etc.)
- Identify geographic and thematic patterns across recipients
- Use concrete examples from the event names provided
- Assess materiality based on: breadth of deployment, diversity of tools, strategic coherence

Generate the JSON response now:"""


def get_country_categories_with_minimum_docs(
    session: Session,
    min_docs: int = 500,
    country: Optional[str] = None,
    category: Optional[str] = None,
    config: Optional[Config] = None
) -> List[Tuple[str, str, int]]:
    """
    Get all country-category pairs that have at least min_docs documents.

    Args:
        session: Database session
        min_docs: Minimum number of documents required
        country: If specified, only get categories for this country
        category: If specified, only get this category
        config: Config object to filter by influencers/categories

    Returns:
        List of tuples: (initiating_country, category, doc_count)
    """
    # Get lists from config if provided
    if config:
        influencers = config.influencers if hasattr(config, 'influencers') else []
        categories = config.categories if hasattr(config, 'categories') else ['Economic', 'Social', 'Military', 'Diplomacy']

        query = text("""
            SELECT
                ic.initiating_country,
                c.category,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN categories c ON d.doc_id = c.doc_id
            WHERE (:country IS NULL OR ic.initiating_country = :country)
            AND (:category IS NULL OR c.category = :category)
            AND ic.initiating_country = ANY(:influencers)
            AND c.category = ANY(:categories)
            GROUP BY ic.initiating_country, c.category
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        results = session.execute(
            query,
            {
                "country": country,
                "category": category,
                "min_docs": min_docs,
                "influencers": influencers,
                "categories": categories
            }
        ).fetchall()
    else:
        # Original query without config filters
        query = text("""
            SELECT
                ic.initiating_country,
                c.category,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN categories c ON d.doc_id = c.doc_id
            WHERE (:country IS NULL OR ic.initiating_country = :country)
            AND (:category IS NULL OR c.category = :category)
            GROUP BY ic.initiating_country, c.category
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        results = session.execute(
            query,
            {"country": country, "category": category, "min_docs": min_docs}
        ).fetchall()

    return [(row[0], row[1], row[2]) for row in results]


def gather_country_category_data(
    session: Session,
    country: str,
    category: str
) -> Dict:
    """
    Gather all data for a country category analysis.

    Returns dict with documents, events, recipients, subcategories, sources, temporal data, etc.
    """
    data = {}

    print(f"  📊 Gathering {category} data for {country}...")

    # Get document count and date range for this category
    doc_query = text("""
        SELECT
            COUNT(DISTINCT d.doc_id) as total_docs,
            MIN(d.date) as first_date,
            MAX(d.date) as last_date
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :country
        AND c.category = :category
    """)

    doc_result = session.execute(
        doc_query,
        {"country": country, "category": category}
    ).first()

    data['total_documents'] = doc_result[0]
    data['first_interaction_date'] = doc_result[1]
    data['last_interaction_date'] = doc_result[2]

    print(f"  📈 Found {data['total_documents']:,} documents ({doc_result[1].strftime('%Y-%m-%d')} to {doc_result[2].strftime('%Y-%m-%d')})")

    # Get event counts (category-filtered)
    event_query = text("""
        SELECT
            COUNT(DISTINCT CASE WHEN es.period_type = 'DAILY' THEN es.id END) as daily_events,
            COUNT(DISTINCT CASE WHEN es.period_type = 'WEEKLY' THEN es.id END) as weekly_events,
            COUNT(DISTINCT CASE WHEN es.period_type = 'MONTHLY' THEN es.id END) as monthly_events
        FROM event_summaries es
        WHERE es.initiating_country = :country
        AND es.count_by_category ? :category
    """)

    event_result = session.execute(
        event_query,
        {"country": country, "category": category}
    ).first()

    data['daily_events'] = event_result[0] or 0
    data['weekly_events'] = event_result[1] or 0
    data['monthly_events'] = event_result[2] or 0

    print(f"  📅 Events: {data['daily_events']} daily, {data['weekly_events']} weekly, {data['monthly_events']} monthly")

    # Get recipient breakdown (which countries receive this category of soft power)
    recipient_query = text("""
        SELECT rc.recipient_country, COUNT(DISTINCT d.doc_id) as count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :country
        AND c.category = :category
        GROUP BY rc.recipient_country
        ORDER BY count DESC
    """)

    recipient_results = session.execute(
        recipient_query,
        {"country": country, "category": category}
    ).fetchall()

    data['recipient_counts'] = {row[0]: row[1] for row in recipient_results}

    # Get subcategory breakdown (within this category)
    subcat_query = text("""
        SELECT sc.subcategory, COUNT(DISTINCT d.doc_id) as count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        JOIN subcategories sc ON d.doc_id = sc.doc_id
        WHERE ic.initiating_country = :country
        AND c.category = :category
        GROUP BY sc.subcategory
        ORDER BY count DESC
    """)

    subcat_results = session.execute(
        subcat_query,
        {"country": country, "category": category}
    ).fetchall()

    data['subcategory_counts'] = {row[0]: row[1] for row in subcat_results}

    # Get source breakdown
    source_query = text("""
        SELECT d.source_name, COUNT(DISTINCT d.doc_id) as count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :country
        AND c.category = :category
        GROUP BY d.source_name
        ORDER BY count DESC
    """)

    source_results = session.execute(
        source_query,
        {"country": country, "category": category}
    ).fetchall()

    data['source_counts'] = {row[0]: row[1] for row in source_results}

    # Get monthly activity
    monthly_query = text("""
        SELECT
            TO_CHAR(d.date, 'YYYY-MM') as month,
            COUNT(DISTINCT d.doc_id) as count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :country
        AND c.category = :category
        GROUP BY month
        ORDER BY month
    """)

    monthly_results = session.execute(
        monthly_query,
        {"country": country, "category": category}
    ).fetchall()

    data['monthly_activity'] = {row[0]: row[1] for row in monthly_results}

    # Get recent event names (category-filtered)
    recent_query = text("""
        SELECT es.event_name, es.period_start
        FROM event_summaries es
        WHERE es.initiating_country = :country
        AND es.count_by_category ? :category
        ORDER BY es.period_start DESC
        LIMIT 20
    """)

    recent_results = session.execute(
        recent_query,
        {"country": country, "category": category}
    ).fetchall()

    data['recent_events'] = [
        {"name": row[0], "date": row[1].strftime("%Y-%m-%d")}
        for row in recent_results
    ]

    # Get material score histogram from event summaries (category-filtered)
    material_query = text("""
        SELECT
            es.material_score,
            COUNT(*) as event_count
        FROM event_summaries es
        WHERE es.initiating_country = :country
        AND es.count_by_category ? :category
        AND es.material_score IS NOT NULL
        GROUP BY es.material_score
        ORDER BY es.material_score
    """)

    material_results = session.execute(
        material_query,
        {"country": country, "category": category}
    ).fetchall()

    # Build histogram with rounded scores
    material_histogram = {}
    material_scores = []
    for row in material_results:
        score = row[0]
        count = row[1]
        rounded_score = round(score * 2) / 2
        material_histogram[str(rounded_score)] = material_histogram.get(str(rounded_score), 0) + count
        material_scores.extend([score] * count)

    data['material_histogram'] = material_histogram

    # Calculate avg and median
    if material_scores:
        import statistics
        data['material_avg'] = statistics.mean(material_scores)
        data['material_median'] = statistics.median(material_scores)
        data['material_count'] = len(material_scores)
    else:
        data['material_avg'] = 0.0
        data['material_median'] = 0.0
        data['material_count'] = 0

    return data


def format_country_category_data_for_prompt(data: Dict, category: str) -> Dict[str, str]:
    """Format gathered data into prompt-friendly strings."""

    # Top recipients
    recipient_lines = []
    for recipient, count in sorted(data['recipient_counts'].items(), key=lambda x: x[1], reverse=True)[:10]:
        pct = (count / data['total_documents'] * 100) if data['total_documents'] > 0 else 0
        recipient_lines.append(f"  - {recipient}: {count:,} docs ({pct:.1f}%)")

    # Subcategory breakdown
    subcat_lines = []
    for subcat, count in sorted(data['subcategory_counts'].items(), key=lambda x: x[1], reverse=True)[:10]:
        pct = (count / data['total_documents'] * 100) if data['total_documents'] > 0 else 0
        subcat_lines.append(f"  - {subcat}: {count:,} docs ({pct:.1f}%)")

    # Source breakdown
    source_lines = []
    for source, count in sorted(data['source_counts'].items(), key=lambda x: x[1], reverse=True)[:5]:
        pct = (count / data['total_documents'] * 100) if data['total_documents'] > 0 else 0
        source_lines.append(f"  - {source}: {count:,} docs ({pct:.1f}%)")

    # Recent events
    event_lines = []
    for i, event in enumerate(data['recent_events'][:15], 1):
        event_lines.append(f"{i}. {event['name']} ({event['date']})")

    # Monthly trend (show last 6 months)
    monthly_items = sorted(data['monthly_activity'].items(), reverse=True)[:6]
    monthly_trend = ", ".join([f"{month}: {count}" for month, count in reversed(monthly_items)])

    return {
        "num_recipients": len(data['recipient_counts']),
        "top_recipients": "\n".join(recipient_lines) if recipient_lines else "No recipients",
        "subcategory_breakdown": "\n".join(subcat_lines) if subcat_lines else "No subcategories",
        "source_breakdown": "\n".join(source_lines) if source_lines else "No sources",
        "recent_events": "\n".join(event_lines) if event_lines else "No recent events",
        "monthly_trend": monthly_trend if monthly_trend else "No data"
    }


def generate_country_category_summary(
    session: Session,
    country: str,
    category: str,
    config: Config,
    dry_run: bool = False,
    regenerate: bool = False
) -> Optional[CountryCategorySummary]:
    """
    Generate AI-powered country category summary.

    Args:
        session: Database session
        country: Initiating country
        category: Category to analyze
        config: Configuration object
        dry_run: If True, don't save to database
        regenerate: If True, update existing summary

    Returns:
        CountryCategorySummary object or None
    """

    # Check if summary already exists
    existing = session.query(CountryCategorySummary).filter_by(
        initiating_country=country,
        category=category,
        is_deleted=False
    ).first()

    if existing and not regenerate:
        print(f"  ⏭️  Summary already exists (use --regenerate to update)")
        return existing

    # Gather data
    data = gather_country_category_data(session, country, category)

    # Format data for prompt
    prompt_data = format_country_category_data_for_prompt(data, category)

    # Generate AI analysis
    print(f"  🤖 Generating AI summary for {category} category...")

    prompt = COUNTRY_CATEGORY_SUMMARY_PROMPT.format(
        country=country,
        category=category,
        first_date=data['first_interaction_date'].strftime("%Y-%m-%d"),
        last_date=data['last_interaction_date'].strftime("%Y-%m-%d"),
        total_docs=data['total_documents'],
        total_events=data['daily_events'] + data['weekly_events'] + data['monthly_events'],
        daily_events=data['daily_events'],
        weekly_events=data['weekly_events'],
        monthly_events=data['monthly_events'],
        material_avg=data['material_avg'],
        material_median=data['material_median'],
        material_count=data['material_count'],
        **prompt_data
    )

    try:
        # Use model from config
        model = config.default_model if hasattr(config, 'default_model') else "gpt-4o-mini"

        response = gai(
            sys_prompt="You are an expert analyst of international relations and soft power diplomacy. Output valid JSON only.",
            user_prompt=prompt,
            model=model,
            use_proxy=True
        )

        # Handle response
        if isinstance(response, dict):
            category_summary = response
        else:
            category_summary = json.loads(response)

    except (json.JSONDecodeError, TypeError) as e:
        print(f"  ❌ Failed to parse AI response: {e}")
        print(f"  Raw response type: {type(response)}")
        print(f"  Raw response: {str(response)[:500]}...")
        return None

    # Extract material score
    material_score = category_summary.get('material_assessment', {}).get('score')
    material_justification = category_summary.get('material_assessment', {}).get('justification')

    if dry_run:
        print(f"\n  🔍 DRY RUN - Would create/update:")
        print(f"     {country} → {category}")
        return None

    # Save to database
    if existing and regenerate:
        print(f"  🔄 Updating existing summary (version {existing.version} → {existing.version + 1})")
        existing.total_documents = data['total_documents']
        existing.first_interaction_date = data['first_interaction_date']
        existing.last_interaction_date = data['last_interaction_date']
        existing.total_daily_events = data['daily_events']
        existing.total_weekly_events = data['weekly_events']
        existing.total_monthly_events = data['monthly_events']
        existing.count_by_recipient = data['recipient_counts']
        existing.count_by_subcategory = data['subcategory_counts']
        existing.count_by_source = data['source_counts']
        existing.activity_by_month = data['monthly_activity']
        existing.category_summary = category_summary
        existing.material_score = material_score
        existing.material_justification = material_justification
        existing.material_score_histogram = data['material_histogram']
        existing.material_score_avg = data['material_avg']
        existing.material_score_median = data['material_median']
        existing.analysis_generated_at = datetime.utcnow()
        existing.updated_at = datetime.utcnow()
        existing.version += 1

        summary = existing
    else:
        print(f"  ✨ Creating new country category summary")
        summary = CountryCategorySummary(
            initiating_country=country,
            category=category,
            first_interaction_date=data['first_interaction_date'],
            last_interaction_date=data['last_interaction_date'],
            total_documents=data['total_documents'],
            total_daily_events=data['daily_events'],
            total_weekly_events=data['weekly_events'],
            total_monthly_events=data['monthly_events'],
            count_by_recipient=data['recipient_counts'],
            count_by_subcategory=data['subcategory_counts'],
            count_by_source=data['source_counts'],
            activity_by_month=data['monthly_activity'],
            category_summary=category_summary,
            material_score=material_score,
            material_justification=material_justification,
            material_score_histogram=data['material_histogram'],
            material_score_avg=data['material_avg'],
            material_score_median=data['material_median'],
            created_by="generate_country_category_summaries.py"
        )

        session.add(summary)

    session.commit()
    print(f"  ✅ Summary saved successfully!")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Generate country-level category-specific summaries"
    )
    parser.add_argument(
        '--country',
        type=str,
        help='Initiating country (e.g., China)'
    )
    parser.add_argument(
        '--category',
        type=str,
        help='Category to analyze (e.g., Economic, Military, Diplomacy, Social)'
    )
    parser.add_argument(
        '--all-categories',
        action='store_true',
        help='Generate summaries for all categories (requires --country)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Generate summaries for all country-category pairs meeting threshold'
    )
    parser.add_argument(
        '--min-docs',
        type=int,
        default=500,
        help='Minimum number of documents required (default: 500)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be generated without saving'
    )
    parser.add_argument(
        '--regenerate',
        action='store_true',
        help='Regenerate existing summaries (update with fresh AI analysis)'
    )

    args = parser.parse_args()

    # Load config
    config = Config.from_yaml('shared/config/config.yaml')

    print(f"\n{'=' * 80}")
    print(f"COUNTRY CATEGORY SUMMARY GENERATION")
    print(f"{'=' * 80}\n")

    with get_session() as session:
        # Get country-category pairs to process
        if args.country and args.category:
            # Single specific pair
            pairs = [(args.country, args.category, None)]
        elif args.country and args.all_categories:
            # All categories for a specific country
            categories = config.categories if hasattr(config, 'categories') else ['Economic', 'Social', 'Military', 'Diplomacy']
            pairs = [
                (args.country, cat, None)
                for cat in categories
            ]
        elif args.all:
            # Get all pairs meeting threshold
            print(f"\n🔍 Finding country-category pairs with ≥{args.min_docs} documents...")
            print(f"   (Filtering by config influencers/categories)")
            pairs = get_country_categories_with_minimum_docs(
                session,
                min_docs=args.min_docs,
                config=config
            )
            print(f"   Found {len(pairs)} country-category pairs")
        else:
            print("❌ Error: Must specify either:")
            print("   1. --country and --category")
            print("   2. --country and --all-categories")
            print("   3. --all")
            return

        # Process each pair
        success_count = 0
        skip_count = 0
        error_count = 0

        for idx, pair in enumerate(pairs, 1):
            country, category, doc_count = pair if len(pair) == 3 else (*pair, None)

            print(f"\n{'─' * 80}")
            print(f"🌍 {country} → {category}")
            if doc_count:
                print(f"   {doc_count:,} documents")

            try:
                summary = generate_country_category_summary(
                    session,
                    country,
                    category,
                    config,
                    dry_run=args.dry_run,
                    regenerate=args.regenerate
                )

                if summary:
                    success_count += 1
                else:
                    skip_count += 1

            except Exception as e:
                print(f"  ❌ Error: {e}")
                import traceback
                traceback.print_exc()
                error_count += 1
                continue

        # Summary
        print(f"\n{'=' * 80}")
        print(f"GENERATION COMPLETE")
        print(f"{'=' * 80}")
        print(f"✅ Success: {success_count}")
        print(f"⏭️  Skipped: {skip_count}")
        print(f"❌ Errors: {error_count}")
        print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
