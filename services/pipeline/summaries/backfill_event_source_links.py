"""
Backfill EventSourceLink records for Weekly and Monthly summaries.

This script populates missing EventSourceLink records by traversing the aggregation hierarchy:
- Weekly summaries inherit doc_ids from their constituent daily summaries
- Monthly summaries inherit doc_ids from their constituent weekly summaries

Usage:
    python backfill_event_source_links.py --period-type WEEKLY
    python backfill_event_source_links.py --period-type MONTHLY
    python backfill_event_source_links.py --all
    python backfill_event_source_links.py --country China --period-type WEEKLY --dry-run
"""

import argparse
import yaml
from datetime import datetime
from typing import List, Set
from sqlalchemy import text
from uuid import UUID

from shared.database.database import get_session
from shared.models.models import EventSummary, EventSourceLink, PeriodType


def load_config(config_path: str = 'shared/config/config.yaml') -> dict:
    """Load configuration from config.yaml"""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return {
                'influencers': config.get('influencers', ['China', 'Russia', 'Iran', 'Turkey', 'United States'])
            }
    except Exception as e:
        print(f"[WARNING] Could not load config.yaml: {e}")
        return {'influencers': ['China', 'Russia', 'Iran', 'Turkey', 'United States']}


def get_doc_ids_from_daily_summaries(
    session,
    event_name: str,
    country: str,
    week_start,
    week_end
) -> Set[str]:
    """
    Get all unique doc_ids from daily summaries for a specific event during a week.
    """
    result = session.execute(text('''
        SELECT DISTINCT esl.doc_id
        FROM event_summaries es
        JOIN event_source_links esl ON es.id = esl.event_summary_id
        WHERE es.event_name = :event_name
          AND es.initiating_country = :country
          AND es.period_type = 'DAILY'
          AND es.period_start >= :week_start
          AND es.period_end <= :week_end
    '''), {
        'event_name': event_name,
        'country': country,
        'week_start': week_start,
        'week_end': week_end
    }).fetchall()

    return set(row[0] for row in result)


def get_doc_ids_from_weekly_summaries(
    session,
    event_name: str,
    country: str,
    month_start,
    month_end
) -> Set[str]:
    """
    Get all unique doc_ids from weekly summaries for a specific event during a month.
    """
    result = session.execute(text('''
        SELECT DISTINCT esl.doc_id
        FROM event_summaries es
        JOIN event_source_links esl ON es.id = esl.event_summary_id
        WHERE es.event_name = :event_name
          AND es.initiating_country = :country
          AND es.period_type = 'WEEKLY'
          AND es.period_start >= :month_start
          AND es.period_end <= :month_end
    '''), {
        'event_name': event_name,
        'country': country,
        'month_start': month_start,
        'month_end': month_end
    }).fetchall()

    return set(row[0] for row in result)


def backfill_weekly_source_links(session, country: str = None, dry_run: bool = False) -> dict:
    """
    Backfill EventSourceLink records for weekly summaries by collecting doc_ids from daily summaries.
    """
    print("\n" + "="*80)
    print("BACKFILLING WEEKLY EVENT SOURCE LINKS")
    print("="*80)

    # Build query
    query = '''
        SELECT
            es.id,
            es.event_name,
            es.initiating_country,
            es.period_start,
            es.period_end
        FROM event_summaries es
        WHERE es.period_type = 'WEEKLY'
          AND NOT EXISTS (
              SELECT 1 FROM event_source_links esl
              WHERE esl.event_summary_id = es.id
          )
    '''

    params = {}
    if country:
        query += " AND es.initiating_country = :country"
        params['country'] = country

    query += " ORDER BY es.initiating_country, es.period_start"

    result = session.execute(text(query), params).fetchall()

    stats = {
        'total_weekly_summaries': len(result),
        'links_created': 0,
        'summaries_updated': 0,
        'errors': 0
    }

    print(f"Found {stats['total_weekly_summaries']} weekly summaries without source links")

    for row in result:
        summary_id, event_name, init_country, period_start, period_end = row

        # Get doc_ids from constituent daily summaries
        doc_ids = get_doc_ids_from_daily_summaries(
            session,
            event_name,
            init_country,
            period_start,
            period_end
        )

        if not doc_ids:
            print(f"  [SKIP] {init_country} - {event_name} ({period_start}): No daily source links found")
            continue

        # Handle Unicode characters in event names for Windows console
        try:
            safe_event_name = event_name.encode('ascii', 'replace').decode('ascii')
        except:
            safe_event_name = "[Non-ASCII event name]"

        print(f"  [PROCESS] {init_country} - {safe_event_name} ({period_start})")
        print(f"    Found {len(doc_ids)} unique source documents from daily summaries")

        if dry_run:
            print(f"    [DRY RUN] Would create {len(doc_ids)} EventSourceLink records")
            stats['links_created'] += len(doc_ids)
            stats['summaries_updated'] += 1
            continue

        # Create EventSourceLink records
        created_count = 0
        for doc_id in doc_ids:
            try:
                link = EventSourceLink(
                    event_summary_id=summary_id,
                    doc_id=doc_id
                )
                session.add(link)
                created_count += 1
            except Exception as e:
                print(f"    [ERROR] Failed to create link for doc_id {doc_id}: {e}")
                stats['errors'] += 1

        session.flush()
        stats['links_created'] += created_count
        stats['summaries_updated'] += 1

        print(f"    [SAVED] Created {created_count} source links")

    if not dry_run:
        session.commit()
        print(f"\n[COMMITTED] All changes saved to database")

    return stats


def backfill_monthly_source_links(session, country: str = None, dry_run: bool = False) -> dict:
    """
    Backfill EventSourceLink records for monthly summaries by collecting doc_ids from weekly summaries.
    """
    print("\n" + "="*80)
    print("BACKFILLING MONTHLY EVENT SOURCE LINKS")
    print("="*80)

    # Build query
    query = '''
        SELECT
            es.id,
            es.event_name,
            es.initiating_country,
            es.period_start,
            es.period_end
        FROM event_summaries es
        WHERE es.period_type = 'MONTHLY'
          AND NOT EXISTS (
              SELECT 1 FROM event_source_links esl
              WHERE esl.event_summary_id = es.id
          )
    '''

    params = {}
    if country:
        query += " AND es.initiating_country = :country"
        params['country'] = country

    query += " ORDER BY es.initiating_country, es.period_start"

    result = session.execute(text(query), params).fetchall()

    stats = {
        'total_monthly_summaries': len(result),
        'links_created': 0,
        'summaries_updated': 0,
        'errors': 0
    }

    print(f"Found {stats['total_monthly_summaries']} monthly summaries without source links")

    for row in result:
        summary_id, event_name, init_country, period_start, period_end = row

        # Get doc_ids from constituent weekly summaries
        doc_ids = get_doc_ids_from_weekly_summaries(
            session,
            event_name,
            init_country,
            period_start,
            period_end
        )

        if not doc_ids:
            print(f"  [SKIP] {init_country} - {event_name} ({period_start}): No weekly source links found")
            continue

        # Handle Unicode characters in event names for Windows console
        try:
            safe_event_name = event_name.encode('ascii', 'replace').decode('ascii')
        except:
            safe_event_name = "[Non-ASCII event name]"

        print(f"  [PROCESS] {init_country} - {safe_event_name} ({period_start})")
        print(f"    Found {len(doc_ids)} unique source documents from weekly summaries")

        if dry_run:
            print(f"    [DRY RUN] Would create {len(doc_ids)} EventSourceLink records")
            stats['links_created'] += len(doc_ids)
            stats['summaries_updated'] += 1
            continue

        # Create EventSourceLink records
        created_count = 0
        for doc_id in doc_ids:
            try:
                link = EventSourceLink(
                    event_summary_id=summary_id,
                    doc_id=doc_id
                )
                session.add(link)
                created_count += 1
            except Exception as e:
                print(f"    [ERROR] Failed to create link for doc_id {doc_id}: {e}")
                stats['errors'] += 1

        session.flush()
        stats['links_created'] += created_count
        stats['summaries_updated'] += 1

        print(f"    [SAVED] Created {created_count} source links")

    if not dry_run:
        session.commit()
        print(f"\n[COMMITTED] All changes saved to database")

    return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill EventSourceLink records for weekly and monthly summaries')
    parser.add_argument('--period-type', type=str, choices=['WEEKLY', 'MONTHLY'],
                       help='Backfill specific period type')
    parser.add_argument('--all', action='store_true', help='Backfill both weekly and monthly')
    parser.add_argument('--country', type=str, help='Limit to specific country')
    parser.add_argument('--dry-run', action='store_true', help='Preview without making changes')

    args = parser.parse_args()

    if not args.period_type and not args.all:
        print("[ERROR] Must specify either --period-type or --all")
        return

    print("\n" + "="*80)
    print("EVENT SOURCE LINK BACKFILL")
    print("="*80)
    if args.dry_run:
        print("[DRY RUN MODE - No changes will be made]")
    if args.country:
        print(f"Country: {args.country}")
    print("="*80)

    with get_session() as session:
        total_stats = {
            'weekly': None,
            'monthly': None
        }

        # Backfill weekly
        if args.all or args.period_type == 'WEEKLY':
            total_stats['weekly'] = backfill_weekly_source_links(session, args.country, args.dry_run)

        # Backfill monthly
        if args.all or args.period_type == 'MONTHLY':
            total_stats['monthly'] = backfill_monthly_source_links(session, args.country, args.dry_run)

        # Print summary
        print("\n" + "="*80)
        print("BACKFILL SUMMARY")
        print("="*80)

        if total_stats['weekly']:
            print(f"\nWeekly Summaries:")
            print(f"  Total processed: {total_stats['weekly']['total_weekly_summaries']}")
            print(f"  Summaries updated: {total_stats['weekly']['summaries_updated']}")
            print(f"  Links created: {total_stats['weekly']['links_created']}")
            print(f"  Errors: {total_stats['weekly']['errors']}")

        if total_stats['monthly']:
            print(f"\nMonthly Summaries:")
            print(f"  Total processed: {total_stats['monthly']['total_monthly_summaries']}")
            print(f"  Summaries updated: {total_stats['monthly']['summaries_updated']}")
            print(f"  Links created: {total_stats['monthly']['links_created']}")
            print(f"  Errors: {total_stats['monthly']['errors']}")

        print("="*80)


if __name__ == '__main__':
    main()
