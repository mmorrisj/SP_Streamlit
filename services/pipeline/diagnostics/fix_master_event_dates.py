"""
Fix master event metadata (dates, mention days, articles) from daily_event_mentions.

This script retroactively updates all master canonical events with correct metadata
derived from their actual daily_event_mentions records.

WHAT IT FIXES:
    - total_mention_days: Count of distinct mention dates
    - first_mention_date: Earliest mention date
    - last_mention_date: Latest mention date
    - total_articles: Sum of all article counts across mentions
    - days_since_last_mention: Days since last mention to today
    - peak_mention_date: Date with highest article count
    - peak_daily_article_count: Highest single-day article count

WHY THIS IS NEEDED:
    merge_canonical_events.py reassigned daily_event_mentions from children to masters
    but did not update the master event's summary metadata fields. This script fixes that.

USAGE:
    # Fix all countries
    python services/pipeline/diagnostics/fix_master_event_dates.py

    # Fix specific country
    python services/pipeline/diagnostics/fix_master_event_dates.py --country China

    # Dry run (preview changes)
    python services/pipeline/diagnostics/fix_master_event_dates.py --dry-run
"""

import argparse
from shared.database.database import get_session
from sqlalchemy import text


def fix_master_event_dates(country=None, dry_run=False):
    with get_session() as session:
        # Build country filter
        country_filter = ""
        params = {}
        if country:
            country_filter = "AND ce.initiating_country = :country"
            params['country'] = country

        # First, show current state
        print('='*80)
        print('FIX MASTER EVENT METADATA')
        print('='*80)

        if country:
            print(f'Country: {country}')
        else:
            print('Country: ALL')

        if dry_run:
            print('[DRY RUN] No changes will be saved')

        # Check how many events need fixing
        result = session.execute(text(f'''
            SELECT
                ce.initiating_country,
                COUNT(*) as total_masters,
                COUNT(*) FILTER (WHERE ce.total_mention_days != sub.actual_days
                                     OR ce.first_mention_date != sub.earliest_date
                                     OR ce.last_mention_date != sub.latest_date) as needs_fix
            FROM canonical_events ce
            JOIN (
                SELECT
                    canonical_event_id,
                    COUNT(DISTINCT mention_date) as actual_days,
                    MIN(mention_date) as earliest_date,
                    MAX(mention_date) as latest_date
                FROM daily_event_mentions
                GROUP BY canonical_event_id
            ) sub ON ce.id = sub.canonical_event_id
            WHERE ce.master_event_id IS NULL
            {country_filter}
            GROUP BY ce.initiating_country
            ORDER BY needs_fix DESC
        '''), params).fetchall()

        print(f"\n{'Country':20} {'Masters':>10} {'Need Fix':>10}")
        print('-'*50)
        total_fix = 0
        for row in result:
            print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,}')
            total_fix += row[2]

        print(f"\nTotal events needing metadata fix: {total_fix:,}")

        if total_fix == 0:
            print('\n[OK] All master events have correct metadata')
            return

        if dry_run:
            # Show sample of what would change
            print('\nSample of changes (first 5):')
            print('-'*80)

            sample = session.execute(text(f'''
                SELECT
                    ce.canonical_name,
                    ce.initiating_country,
                    ce.total_mention_days as old_days,
                    sub.actual_days as new_days,
                    ce.first_mention_date as old_first,
                    sub.earliest_date as new_first,
                    ce.last_mention_date as old_last,
                    sub.latest_date as new_last
                FROM canonical_events ce
                JOIN (
                    SELECT
                        canonical_event_id,
                        COUNT(DISTINCT mention_date) as actual_days,
                        MIN(mention_date) as earliest_date,
                        MAX(mention_date) as latest_date
                    FROM daily_event_mentions
                    GROUP BY canonical_event_id
                ) sub ON ce.id = sub.canonical_event_id
                WHERE ce.master_event_id IS NULL
                  AND (ce.total_mention_days != sub.actual_days
                       OR ce.first_mention_date != sub.earliest_date
                       OR ce.last_mention_date != sub.latest_date)
                {country_filter}
                ORDER BY sub.actual_days DESC
                LIMIT 5
            '''), params).fetchall()

            for row in sample:
                name = row[0][:50]
                print(f'  {name}')
                print(f'    mention_days: {row[2]} -> {row[3]}')
                print(f'    first_date:   {row[4]} -> {row[5]}')
                print(f'    last_date:    {row[6]} -> {row[7]}')
                print()

            print('[DRY RUN] Run without --dry-run to apply fixes')
            return

        # Apply the fix
        print('\nApplying fixes...')

        updated = session.execute(text(f'''
            UPDATE canonical_events ce
            SET
                total_mention_days = sub.actual_days,
                first_mention_date = sub.earliest_date,
                last_mention_date = sub.latest_date,
                total_articles = sub.total_articles,
                days_since_last_mention = CURRENT_DATE - sub.latest_date,
                peak_mention_date = sub.peak_date,
                peak_daily_article_count = sub.peak_articles
            FROM (
                SELECT
                    dem.canonical_event_id,
                    COUNT(DISTINCT dem.mention_date) as actual_days,
                    MIN(dem.mention_date) as earliest_date,
                    MAX(dem.mention_date) as latest_date,
                    SUM(dem.article_count) as total_articles,
                    (SELECT dem2.mention_date FROM daily_event_mentions dem2
                     WHERE dem2.canonical_event_id = dem.canonical_event_id
                     ORDER BY dem2.article_count DESC LIMIT 1) as peak_date,
                    MAX(dem.article_count) as peak_articles
                FROM daily_event_mentions dem
                GROUP BY dem.canonical_event_id
            ) sub
            WHERE ce.id = sub.canonical_event_id
              AND ce.master_event_id IS NULL
              {country_filter}
        '''), params)

        session.commit()

        # Verify
        print('\n[COMMITTED] Updated master event metadata')

        # Show results
        result = session.execute(text(f'''
            SELECT
                ce.initiating_country,
                COUNT(*) as total_masters,
                COUNT(*) FILTER (WHERE ce.total_mention_days > 1) as multi_day,
                ROUND(100.0 * COUNT(*) FILTER (WHERE ce.total_mention_days > 1) / COUNT(*), 1) as pct_multi_day,
                ROUND(AVG(ce.total_mention_days), 1) as avg_days,
                MAX(ce.total_mention_days) as max_days
            FROM canonical_events ce
            WHERE ce.master_event_id IS NULL
            {country_filter}
            GROUP BY ce.initiating_country
            ORDER BY total_masters DESC
        '''), params).fetchall()

        print(f"\n{'Country':20} {'Masters':>10} {'Multi-Day':>10} {'%':>8} {'Avg Days':>10} {'Max Days':>10}")
        print('-'*80)
        for row in result:
            print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,} {row[3]:>7.1f}% {row[4]:>10.1f} {row[5]:>10,}')

        print('\n' + '='*80)
        print('[DONE] Master event metadata has been corrected')
        print('='*80)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fix master event metadata from daily_event_mentions')
    parser.add_argument('--country', type=str, help='Fix specific country only')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without saving')
    args = parser.parse_args()

    fix_master_event_dates(country=args.country, dry_run=args.dry_run)
