"""
Generate bilateral category-specific summaries.

Creates AI-powered summaries for specific category interactions between country pairs
(e.g., "China → Egypt Economic relationship", "Russia → Iran Military relationship").

Usage:
    # Single category-specific pair
    python services/pipeline/summaries/generate_bilateral_category_summaries.py \
        --init-country China --recipient-country Egypt --category Economic

    # All categories for a bilateral pair
    python services/pipeline/summaries/generate_bilateral_category_summaries.py \
        --init-country China --recipient-country Egypt --all-categories

    # All categories for all bilateral pairs with minimum docs
    python services/pipeline/summaries/generate_bilateral_category_summaries.py \
        --all --min-docs 100

    # Regenerate existing summaries
    python services/pipeline/summaries/generate_bilateral_category_summaries.py \
        --all --min-docs 100 --regenerate
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
from shared.models.models import BilateralCategorySummary
from shared.utils.utils import Config, gai


# AI Prompt for bilateral category analysis
BILATERAL_CATEGORY_SUMMARY_PROMPT = """You are analyzing the **{category}** soft power relationship between **{initiating_country}** and **{recipient_country}**.

**TIME PERIOD:** {first_date} to {last_date}

**DATA PROVIDED:**
- Total Documents: {total_docs:,}
- Total Events: {total_events:,} (Daily: {daily_events}, Weekly: {weekly_events}, Monthly: {monthly_events})
- Subcategory Distribution: {subcategory_breakdown}
- Source Distribution: {source_breakdown}
- Monthly Activity Trend: {monthly_trend}
- Material Score: Avg {material_avg:.2f}, Median {material_median:.2f} (from {material_count} scored events)

**Sample Recent Event Names ({category} category only):**
{recent_events}

**TASK:**
Analyze the **{category}** dimension of soft power in this bilateral relationship.

**OUTPUT FORMAT (JSON only, no markdown):**
{{
    "overview": "2-3 sentences summarizing {initiating_country}'s use of {category} soft power toward {recipient_country}",
    "key_focus_areas": ["specific focus area 1", "specific focus area 2", "..."],
    "major_initiatives": [
        {{"name": "initiative name", "description": "what it involves", "timeframe": "when it occurred"}},
        ...
    ],
    "interaction_patterns": "How {category} tools are deployed in this relationship - frequency, intensity, strategic approach",
    "trend_analysis": "How this category's use has evolved over time - increasing/decreasing, shifting focus",
    "impact_assessment": "Evidence of effectiveness and outcomes of {category} initiatives",
    "material_assessment": {{
        "score": <float between 0.0 and 1.0>,
        "justification": "Why this score reflects the materiality of {category} soft power in this relationship"
    }}
}}

**INSTRUCTIONS:**
- Focus ONLY on the {category} category - ignore other categories
- Be specific about subcategories (e.g., within Economic: Trade, Infrastructure, etc.)
- Use concrete examples from the event names provided
- Assess materiality based on: frequency of interaction, diversity of activities, strategic significance

Generate the JSON response now:"""


def get_category_pairs_with_minimum_docs(
    session: Session,
    min_docs: int = 50,
    initiating_country: Optional[str] = None,
    recipient_country: Optional[str] = None,
    category: Optional[str] = None,
    config: Optional[Config] = None
) -> List[Tuple[str, str, str, int]]:
    """
    Get all country-category triplets that have at least min_docs documents.

    Args:
        session: Database session
        min_docs: Minimum number of documents required
        initiating_country: If specified, only get pairs for this initiator
        recipient_country: If specified, only get pairs for this recipient
        category: If specified, only get this category
        config: Config object to filter by influencers/recipients

    Returns:
        List of tuples: (initiating_country, recipient_country, category, doc_count)
    """
    # Get country lists from config if provided
    if config:
        influencers = config.influencers if hasattr(config, 'influencers') else []
        recipients = config.recipients if hasattr(config, 'recipients') else []
        categories = config.categories if hasattr(config, 'categories') else ['Economic', 'Social', 'Military', 'Diplomacy']

        query = text("""
            SELECT
                ic.initiating_country,
                rc.recipient_country,
                c.category,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            JOIN categories c ON d.doc_id = c.doc_id
            WHERE (:init_country IS NULL OR ic.initiating_country = :init_country)
            AND (:recip_country IS NULL OR rc.recipient_country = :recip_country)
            AND (:category IS NULL OR c.category = :category)
            AND ic.initiating_country = ANY(:influencers)
            AND rc.recipient_country = ANY(:recipients)
            AND c.category = ANY(:categories)
            AND ic.initiating_country != rc.recipient_country
            GROUP BY ic.initiating_country, rc.recipient_country, c.category
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        results = session.execute(
            query,
            {
                "init_country": initiating_country,
                "recip_country": recipient_country,
                "category": category,
                "min_docs": min_docs,
                "influencers": influencers,
                "recipients": recipients,
                "categories": categories
            }
        ).fetchall()
    else:
        # Original query without config filters
        query = text("""
            SELECT
                ic.initiating_country,
                rc.recipient_country,
                c.category,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            JOIN categories c ON d.doc_id = c.doc_id
            WHERE (:init_country IS NULL OR ic.initiating_country = :init_country)
            AND (:recip_country IS NULL OR rc.recipient_country = :recip_country)
            AND (:category IS NULL OR c.category = :category)
            AND ic.initiating_country != rc.recipient_country
            GROUP BY ic.initiating_country, rc.recipient_country, c.category
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        results = session.execute(
            query,
            {
                "init_country": initiating_country,
                "recip_country": recipient_country,
                "category": category,
                "min_docs": min_docs
            }
        ).fetchall()

    return [(row[0], row[1], row[2], row[3]) for row in results]


def gather_bilateral_category_data(
    session: Session,
    initiating_country: str,
    recipient_country: str,
    category: str
) -> Dict:
    """
    Gather all data for a bilateral category analysis.

    Returns dict with documents, events, subcategories, sources, temporal data, etc.
    """
    data = {}

    print(f"  📊 Gathering {category} data for {initiating_country} → {recipient_country}...")

    # Get document count and date range for this category
    doc_query = text("""
        SELECT
            COUNT(DISTINCT d.doc_id) as total_docs,
            MIN(d.date) as first_date,
            MAX(d.date) as last_date
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        AND c.category = :category
    """)

    doc_result = session.execute(
        doc_query,
        {"init_country": initiating_country, "recip_country": recipient_country, "category": category}
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
        WHERE es.initiating_country = :init_country
        AND es.count_by_recipient ? :recip_country
        AND es.count_by_category ? :category
    """)

    event_result = session.execute(
        event_query,
        {"init_country": initiating_country, "recip_country": recipient_country, "category": category}
    ).first()

    data['daily_events'] = event_result[0] or 0
    data['weekly_events'] = event_result[1] or 0
    data['monthly_events'] = event_result[2] or 0

    print(f"  📅 Events: {data['daily_events']} daily, {data['weekly_events']} weekly, {data['monthly_events']} monthly")

    # Get subcategory breakdown (within this category)
    subcat_query = text("""
        SELECT sc.subcategory, COUNT(DISTINCT d.doc_id) as count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        JOIN subcategories sc ON d.doc_id = sc.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        AND c.category = :category
        GROUP BY sc.subcategory
        ORDER BY count DESC
    """)

    subcat_results = session.execute(
        subcat_query,
        {"init_country": initiating_country, "recip_country": recipient_country, "category": category}
    ).fetchall()

    data['subcategory_counts'] = {row[0]: row[1] for row in subcat_results}

    # Get source breakdown
    source_query = text("""
        SELECT d.source_name, COUNT(DISTINCT d.doc_id) as count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        AND c.category = :category
        GROUP BY d.source_name
        ORDER BY count DESC
    """)

    source_results = session.execute(
        source_query,
        {"init_country": initiating_country, "recip_country": recipient_country, "category": category}
    ).fetchall()

    data['source_counts'] = {row[0]: row[1] for row in source_results}

    # Get monthly activity
    monthly_query = text("""
        SELECT
            TO_CHAR(d.date, 'YYYY-MM') as month,
            COUNT(DISTINCT d.doc_id) as count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :init_country
        AND rc.recipient_country = :recip_country
        AND c.category = :category
        GROUP BY month
        ORDER BY month
    """)

    monthly_results = session.execute(
        monthly_query,
        {"init_country": initiating_country, "recip_country": recipient_country, "category": category}
    ).fetchall()

    data['monthly_activity'] = {row[0]: row[1] for row in monthly_results}

    # Get recent event names (category-filtered)
    recent_query = text("""
        SELECT es.event_name, es.period_start
        FROM event_summaries es
        WHERE es.initiating_country = :init_country
        AND es.count_by_recipient ? :recip_country
        AND es.count_by_category ? :category
        ORDER BY es.period_start DESC
        LIMIT 15
    """)

    recent_results = session.execute(
        recent_query,
        {"init_country": initiating_country, "recip_country": recipient_country, "category": category}
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
        WHERE es.initiating_country = :init_country
        AND es.count_by_recipient ? :recip_country
        AND es.count_by_category ? :category
        AND es.material_score IS NOT NULL
        GROUP BY es.material_score
        ORDER BY es.material_score
    """)

    material_results = session.execute(
        material_query,
        {"init_country": initiating_country, "recip_country": recipient_country, "category": category}
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


def format_bilateral_category_data_for_prompt(data: Dict, category: str) -> Dict[str, str]:
    """Format gathered data into prompt-friendly strings."""

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
    for i, event in enumerate(data['recent_events'][:10], 1):
        event_lines.append(f"{i}. {event['name']} ({event['date']})")

    # Monthly trend (show last 6 months)
    monthly_items = sorted(data['monthly_activity'].items(), reverse=True)[:6]
    monthly_trend = ", ".join([f"{month}: {count}" for month, count in reversed(monthly_items)])

    return {
        "subcategory_breakdown": "\n".join(subcat_lines) if subcat_lines else "No subcategories",
        "source_breakdown": "\n".join(source_lines) if source_lines else "No sources",
        "recent_events": "\n".join(event_lines) if event_lines else "No recent events",
        "monthly_trend": monthly_trend if monthly_trend else "No data"
    }


def generate_bilateral_category_summary(
    session: Session,
    initiating_country: str,
    recipient_country: str,
    category: str,
    config: Config,
    dry_run: bool = False,
    regenerate: bool = False
) -> Optional[BilateralCategorySummary]:
    """
    Generate AI-powered bilateral category summary.

    Args:
        session: Database session
        initiating_country: Initiating country
        recipient_country: Recipient country
        category: Category to analyze
        config: Configuration object
        dry_run: If True, don't save to database
        regenerate: If True, update existing summary

    Returns:
        BilateralCategorySummary object or None
    """

    # Skip if initiating and recipient countries are the same
    if initiating_country == recipient_country:
        print(f"  ⏭️  Skipping same-country pair ({initiating_country} → {recipient_country})")
        return None

    # Check if summary already exists
    existing = session.query(BilateralCategorySummary).filter_by(
        initiating_country=initiating_country,
        recipient_country=recipient_country,
        category=category,
        is_deleted=False
    ).first()

    if existing and not regenerate:
        print(f"  ⏭️  Summary already exists (use --regenerate to update)")
        return existing

    # Gather data
    data = gather_bilateral_category_data(session, initiating_country, recipient_country, category)

    # Format data for prompt
    prompt_data = format_bilateral_category_data_for_prompt(data, category)

    # Generate AI analysis
    print(f"  🤖 Generating AI summary for {category} category...")

    prompt = BILATERAL_CATEGORY_SUMMARY_PROMPT.format(
        initiating_country=initiating_country,
        recipient_country=recipient_country,
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
        print(f"     {initiating_country} → {recipient_country} → {category}")
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
        print(f"  ✨ Creating new bilateral category summary")
        summary = BilateralCategorySummary(
            initiating_country=initiating_country,
            recipient_country=recipient_country,
            category=category,
            first_interaction_date=data['first_interaction_date'],
            last_interaction_date=data['last_interaction_date'],
            total_documents=data['total_documents'],
            total_daily_events=data['daily_events'],
            total_weekly_events=data['weekly_events'],
            total_monthly_events=data['monthly_events'],
            count_by_subcategory=data['subcategory_counts'],
            count_by_source=data['source_counts'],
            activity_by_month=data['monthly_activity'],
            category_summary=category_summary,
            material_score=material_score,
            material_justification=material_justification,
            material_score_histogram=data['material_histogram'],
            material_score_avg=data['material_avg'],
            material_score_median=data['material_median'],
            created_by="generate_bilateral_category_summaries.py"
        )

        session.add(summary)

    session.commit()
    print(f"  ✅ Summary saved successfully!")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Generate bilateral category-specific summaries"
    )
    parser.add_argument(
        '--init-country',
        type=str,
        help='Initiating country (e.g., China)'
    )
    parser.add_argument(
        '--recipient-country',
        type=str,
        help='Recipient country (e.g., Egypt)'
    )
    parser.add_argument(
        '--category',
        type=str,
        help='Category to analyze (e.g., Economic, Military, Diplomacy, Social)'
    )
    parser.add_argument(
        '--all-categories',
        action='store_true',
        help='Generate summaries for all categories (requires --init-country and --recipient-country)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Generate summaries for all country-category pairs meeting threshold'
    )
    parser.add_argument(
        '--min-docs',
        type=int,
        default=50,
        help='Minimum number of documents required (default: 50)'
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
    print(f"BILATERAL CATEGORY SUMMARY GENERATION")
    print(f"{'=' * 80}\n")

    with get_session() as session:
        # Get category pairs to process
        if args.init_country and args.recipient_country and args.category:
            # Single specific triplet
            triplets = [(args.init_country, args.recipient_country, args.category, None)]
        elif args.init_country and args.recipient_country and args.all_categories:
            # All categories for a specific bilateral pair
            categories = config.categories if hasattr(config, 'categories') else ['Economic', 'Social', 'Military', 'Diplomacy']
            triplets = [
                (args.init_country, args.recipient_country, cat, None)
                for cat in categories
            ]
        elif args.all:
            # Get all triplets meeting threshold
            print(f"\n🔍 Finding country-category triplets with ≥{args.min_docs} documents...")
            print(f"   (Filtering by config influencers/recipients/categories)")
            triplets = get_category_pairs_with_minimum_docs(
                session,
                min_docs=args.min_docs,
                config=config
            )
            print(f"   Found {len(triplets)} country-category triplets")
        else:
            print("❌ Error: Must specify either:")
            print("   1. --init-country, --recipient-country, and --category")
            print("   2. --init-country, --recipient-country, and --all-categories")
            print("   3. --all")
            return

        # Process each triplet
        success_count = 0
        skip_count = 0
        error_count = 0

        for idx, triplet in enumerate(triplets, 1):
            init_country, recip_country, category, doc_count = triplet if len(triplet) == 4 else (*triplet, None)

            print(f"\n{'─' * 80}")
            print(f"🌍 {init_country} → {recip_country} → {category}")
            if doc_count:
                print(f"   {doc_count:,} documents")

            try:
                summary = generate_bilateral_category_summary(
                    session,
                    init_country,
                    recip_country,
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
