"""
Generate metrics snapshot for a given country and date range.

This script queries the database to produce a metrics-based snapshot of activity
that can be used as context for overall summary publications.

Metrics included:
- Top events by article count
- Top bilateral discussions by article count
- Top categories by article count

Only countries and categories from config.yaml are included.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict

from sqlalchemy import text
from shared.database.database import get_session
from shared.utils.utils import Config


def get_valid_countries(config: Config) -> List[str]:
    """Get list of valid recipient countries from config."""
    return getattr(config, 'recipients', [])


def get_valid_categories(config: Config) -> List[str]:
    """Get list of valid categories from config."""
    categories = getattr(config, 'categories', [])
    return categories if isinstance(categories, list) else []


def get_top_events_by_count(
    session,
    country: str,
    start_date: datetime,
    end_date: datetime,
    valid_recipients: List[str],
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get top events by document count - only master (consolidated) events."""

    query = text("""
        SELECT
            ce.canonical_name,
            ce.consolidated_description,
            ce.first_mention_date,
            ce.last_mention_date,
            ce.total_articles as article_count,
            ce.total_mention_days
        FROM canonical_events ce
        WHERE ce.initiating_country = :country
            AND ce.first_mention_date <= :end_date
            AND ce.last_mention_date >= :start_date
            AND ce.master_event_id IS NULL
        ORDER BY ce.total_articles DESC
        LIMIT :limit
    """)

    result = session.execute(query, {
        'country': country,
        'start_date': start_date,
        'end_date': end_date,
        'limit': limit
    })

    events = []
    for row in result:
        events.append({
            'event_name': row.canonical_name,
            'description': row.consolidated_description if row.consolidated_description else '',
            'start_date': row.first_mention_date.isoformat() if row.first_mention_date else None,
            'end_date': row.last_mention_date.isoformat() if row.last_mention_date else None,
            'article_count': row.article_count,
            'mention_days': row.total_mention_days
        })

    return events


# Materiality column doesn't exist in current schema - removed this function


def get_top_bilateral_discussions(
    session,
    country: str,
    start_date: datetime,
    end_date: datetime,
    valid_recipients: List[str],
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get top bilateral discussions by article count."""

    # Create placeholder string for valid recipients
    recipients_placeholder = ', '.join([f':recipient_{i}' for i in range(len(valid_recipients))])

    query_str = f"""
        SELECT
            rc.recipient_country,
            COUNT(DISTINCT d.doc_id) as article_count
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        WHERE ic.initiating_country = :country
            AND rc.recipient_country IN ({recipients_placeholder})
            AND d.date BETWEEN :start_date AND :end_date
        GROUP BY rc.recipient_country
        ORDER BY article_count DESC
        LIMIT :limit
    """

    # Build parameters dict
    params = {
        'country': country,
        'start_date': start_date,
        'end_date': end_date,
        'limit': limit
    }
    for i, recipient in enumerate(valid_recipients):
        params[f'recipient_{i}'] = recipient

    result = session.execute(text(query_str), params)

    discussions = []
    for row in result:
        discussions.append({
            'recipient_country': row.recipient_country,
            'article_count': row.article_count
        })

    return discussions


def get_top_categories_by_count(
    session,
    country: str,
    start_date: datetime,
    end_date: datetime,
    valid_categories: List[str],
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get top categories by article count."""

    # Create placeholder string for valid categories
    categories_placeholder = ', '.join([f':category_{i}' for i in range(len(valid_categories))])

    query_str = f"""
        SELECT
            c.category,
            COUNT(DISTINCT d.doc_id) as article_count
        FROM documents d
        JOIN categories c ON d.doc_id = c.doc_id
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        WHERE ic.initiating_country = :country
            AND c.category IN ({categories_placeholder})
            AND d.date BETWEEN :start_date AND :end_date
        GROUP BY c.category
        ORDER BY article_count DESC
        LIMIT :limit
    """

    # Build parameters dict
    params = {
        'country': country,
        'start_date': start_date,
        'end_date': end_date,
        'limit': limit
    }
    for i, category in enumerate(valid_categories):
        params[f'category_{i}'] = category

    result = session.execute(text(query_str), params)

    categories = []
    for row in result:
        categories.append({
            'category': row.category,
            'article_count': row.article_count
        })

    return categories


# Materiality column doesn't exist in current schema - removed this function


def get_overall_stats(
    session,
    country: str,
    start_date: datetime,
    end_date: datetime,
    valid_recipients: List[str],
    valid_categories: List[str]
) -> Dict[str, Any]:
    """Get overall statistics for the period."""

    query = text("""
        SELECT
            COUNT(DISTINCT d.doc_id) as total_articles,
            COUNT(DISTINCT rc.recipient_country) as total_recipient_countries,
            COUNT(DISTINCT c.category) as total_categories
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        LEFT JOIN recipient_countries rc ON d.doc_id = rc.doc_id
        LEFT JOIN categories c ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = :country
            AND d.date BETWEEN :start_date AND :end_date
    """)

    result = session.execute(query, {
        'country': country,
        'start_date': start_date,
        'end_date': end_date
    }).fetchone()

    return {
        'total_articles': result.total_articles,
        'total_recipient_countries': result.total_recipient_countries,
        'total_categories': result.total_categories
    }


def generate_metrics_snapshot(
    country: str,
    start_date: datetime,
    end_date: datetime,
    config: Config,
    output_dir: Path = None
) -> Dict[str, Any]:
    """Generate complete metrics snapshot."""

    valid_recipients = get_valid_countries(config)
    valid_categories = get_valid_categories(config)

    print(f"Generating metrics snapshot for {country}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Valid recipients: {len(valid_recipients)} countries")
    print(f"Valid categories: {len(valid_categories)} categories")

    with get_session() as session:
        # Get all metrics
        print("\nFetching overall statistics...")
        overall_stats = get_overall_stats(
            session, country, start_date, end_date,
            valid_recipients, valid_categories
        )

        print("Fetching top events by article count...")
        top_events_by_count = get_top_events_by_count(
            session, country, start_date, end_date,
            valid_recipients, limit=20
        )

        print("Fetching top bilateral discussions...")
        top_bilateral = get_top_bilateral_discussions(
            session, country, start_date, end_date,
            valid_recipients, limit=20
        )

        print("Fetching top categories by article count...")
        top_categories_by_count = get_top_categories_by_count(
            session, country, start_date, end_date,
            valid_categories, limit=20
        )

    # Build snapshot
    snapshot = {
        'metadata': {
            'country': country,
            'start_date': start_date.date().isoformat(),
            'end_date': end_date.date().isoformat(),
            'generated_at': datetime.now().isoformat(),
            'config_filters': {
                'valid_recipients_count': len(valid_recipients),
                'valid_categories_count': len(valid_categories)
            }
        },
        'overall_statistics': overall_stats,
        'top_events_by_article_count': top_events_by_count,
        'top_bilateral_discussions_by_article_count': top_bilateral,
        'top_categories_by_article_count': top_categories_by_count
    }

    # Save to file if output_dir provided
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{country}_metrics_{start_date.date()}_{end_date.date()}.json"
        output_path = output_dir / filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Metrics snapshot saved to: {output_path}")

    return snapshot


def main():
    parser = argparse.ArgumentParser(
        description='Generate metrics snapshot for a country and date range'
    )
    parser.add_argument(
        '--country',
        required=True,
        help='Initiating country (e.g., China)'
    )
    parser.add_argument(
        '--start-date',
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        required=True,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--output-dir',
        default='publications/metrics',
        help='Output directory for metrics snapshots (default: publications/metrics)'
    )
    parser.add_argument(
        '--config',
        default='shared/config/config.yaml',
        help='Path to config file (default: shared/config/config.yaml)'
    )

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')

    # Load config
    config = Config.from_yaml(args.config)

    # Generate snapshot
    output_dir = Path(args.output_dir)
    snapshot = generate_metrics_snapshot(
        country=args.country,
        start_date=start_date,
        end_date=end_date,
        config=config,
        output_dir=output_dir
    )

    print("\n" + "="*60)
    print("METRICS SNAPSHOT SUMMARY")
    print("="*60)
    print(f"Total Articles: {snapshot['overall_statistics']['total_articles']}")
    print(f"Recipient Countries: {snapshot['overall_statistics']['total_recipient_countries']}")
    print(f"Categories: {snapshot['overall_statistics']['total_categories']}")
    print(f"\nTop Event: {snapshot['top_events_by_article_count'][0]['event_name'] if snapshot['top_events_by_article_count'] else 'N/A'}")
    print(f"  ({snapshot['top_events_by_article_count'][0]['article_count']} articles)" if snapshot['top_events_by_article_count'] else "")
    print(f"Top Bilateral: {snapshot['top_bilateral_discussions_by_article_count'][0]['recipient_country'] if snapshot['top_bilateral_discussions_by_article_count'] else 'N/A'}")
    print(f"  ({snapshot['top_bilateral_discussions_by_article_count'][0]['article_count']} articles)" if snapshot['top_bilateral_discussions_by_article_count'] else "")
    print(f"Top Category: {snapshot['top_categories_by_article_count'][0]['category'] if snapshot['top_categories_by_article_count'] else 'N/A'}")
    print(f"  ({snapshot['top_categories_by_article_count'][0]['article_count']} articles)" if snapshot['top_categories_by_article_count'] else "")
    print("="*60)


if __name__ == '__main__':
    main()
