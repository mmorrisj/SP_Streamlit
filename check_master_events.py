"""Comprehensive Master Event Processing Verification"""

from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    print('='*100)
    print('MASTER EVENT PROCESSING VERIFICATION')
    print('='*100)

    # Check 1: Master vs Child event distribution
    print('\n1. MASTER/CHILD EVENT DISTRIBUTION')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) as total_events,
            COUNT(*) FILTER (WHERE master_event_id IS NULL) as master_events,
            COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) as child_events,
            ROUND(100.0 * COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as pct_children
        FROM canonical_events
        GROUP BY initiating_country
        ORDER BY total_events DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Total':>10} {'Masters':>10} {'Children':>10} {'% Children':>12}")
    print('-'*100)
    for row in result:
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,} {row[3]:>10,} {row[4]:>11.1f}%')

    # Check 2: LLM Validation Status for Master Events
    print('\n2. LLM VALIDATION STATUS (Master Events Only)')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) as total_masters,
            COUNT(*) FILTER (WHERE llm_validated = TRUE) as validated,
            COUNT(*) FILTER (WHERE llm_validated = FALSE) as unvalidated,
            ROUND(100.0 * COUNT(*) FILTER (WHERE llm_validated = TRUE) / NULLIF(COUNT(*), 0), 1) as pct_validated
        FROM canonical_events
        WHERE master_event_id IS NULL
        GROUP BY initiating_country
        ORDER BY total_masters DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Masters':>10} {'Validated':>10} {'Unvalidated':>12} {'% Valid':>10} {'Status':>8}")
    print('-'*100)
    for row in result:
        status = 'OK' if row[4] >= 90 else 'WARN' if row[4] >= 50 else 'FAIL'
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,} {row[3]:>12,} {row[4]:>9.1f}% {status:>8}')

    # Check 3: Orphaned children (children pointing to non-existent masters)
    print('\n3. ORPHANED CHILDREN CHECK')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            ce.initiating_country,
            COUNT(*) as orphaned_children
        FROM canonical_events ce
        WHERE ce.master_event_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM canonical_events master
              WHERE master.id = ce.master_event_id
          )
        GROUP BY ce.initiating_country
    ''')).fetchall()

    if result:
        print('[CRITICAL] Found orphaned children pointing to deleted masters!')
        for row in result:
            print(f'  {row[0]}: {row[1]:,} orphaned children')
    else:
        print('[OK] No orphaned children found')

    # Check 4: Daily Event Mentions Coverage
    print('\n4. DAILY EVENT MENTIONS COVERAGE')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            ce.initiating_country,
            COUNT(DISTINCT ce.id) as total_events,
            COUNT(DISTINCT dem.canonical_event_id) as events_with_mentions,
            ROUND(100.0 * COUNT(DISTINCT dem.canonical_event_id) / NULLIF(COUNT(DISTINCT ce.id), 0), 1) as pct_coverage
        FROM canonical_events ce
        LEFT JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
        WHERE ce.master_event_id IS NULL
        GROUP BY ce.initiating_country
        ORDER BY total_events DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Masters':>10} {'With Mentions':>15} {'Coverage %':>12} {'Status':>8}")
    print('-'*100)
    for row in result:
        status = 'OK' if row[3] >= 90 else 'WARN' if row[3] >= 70 else 'FAIL'
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>15,} {row[3]:>11.1f}% {status:>8}')

    # Check 5: Events with both master_event_id AND llm_validated=TRUE (shouldn't exist)
    print('\n5. DATA INTEGRITY: Children Marked as Validated')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) as invalid_children
        FROM canonical_events
        WHERE master_event_id IS NOT NULL
          AND llm_validated = TRUE
        GROUP BY initiating_country
    ''')).fetchall()

    if result:
        print('[WARNING] Found children events marked as llm_validated=TRUE')
        for row in result:
            print(f'  {row[0]}: {row[1]:,} children incorrectly marked as validated')
    else:
        print('[OK] No children marked as validated (correct)')

    # Check 6: Materiality Scoring Coverage
    print('\n6. MATERIALITY SCORING COVERAGE (Master Events Only)')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) as total_masters,
            COUNT(*) FILTER (WHERE material_score IS NOT NULL) as scored,
            COUNT(*) FILTER (WHERE material_score IS NULL) as unscored,
            ROUND(100.0 * COUNT(*) FILTER (WHERE material_score IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as pct_scored,
            ROUND(AVG(material_score), 2) as avg_score,
            MIN(material_score) as min_score,
            MAX(material_score) as max_score
        FROM canonical_events
        WHERE master_event_id IS NULL
        GROUP BY initiating_country
        ORDER BY total_masters DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Masters':>10} {'Scored':>10} {'Unscored':>10} {'% Scored':>10} {'Status':>8} {'Avg':>6} {'Min':>6} {'Max':>6}")
    print('-'*100)
    for row in result:
        status = 'OK' if row[4] >= 90 else 'WARN' if row[4] >= 50 else 'FAIL' if row[4] > 0 else 'NONE'
        avg_str = f'{row[5]:.2f}' if row[5] else 'N/A'
        min_str = f'{row[6]:.1f}' if row[6] else 'N/A'
        max_str = f'{row[7]:.1f}' if row[7] else 'N/A'
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,} {row[3]:>10,} {row[4]:>9.1f}% {status:>8} {avg_str:>6} {min_str:>6} {max_str:>6}')

    # Check 7: Multi-day events (masters with mentions spanning multiple days)
    print('\n7. MULTI-DAY EVENT CONSOLIDATION')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            ce.initiating_country,
            COUNT(DISTINCT ce.id) as total_masters,
            COUNT(DISTINCT ce.id) FILTER (WHERE ce.total_mention_days > 1) as multi_day_events,
            ROUND(100.0 * COUNT(DISTINCT ce.id) FILTER (WHERE ce.total_mention_days > 1) / NULLIF(COUNT(DISTINCT ce.id), 0), 1) as pct_multi_day,
            ROUND(AVG(ce.total_mention_days), 1) as avg_mention_days,
            MAX(ce.total_mention_days) as max_mention_days
        FROM canonical_events ce
        WHERE ce.master_event_id IS NULL
        GROUP BY ce.initiating_country
        ORDER BY total_masters DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Masters':>10} {'Multi-Day':>10} {'% Multi-Day':>12} {'Avg Days':>10} {'Max Days':>10}")
    print('-'*100)
    for row in result:
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,} {row[3]:>11.1f}% {row[4]:>10.1f} {row[5]:>10,}')

    # Check 8: Total daily_event_mentions count
    print('\n8. DAILY EVENT MENTIONS INTEGRITY')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            ce.initiating_country,
            COUNT(DISTINCT dem.id) as total_mentions,
            COUNT(DISTINCT dem.canonical_event_id) as unique_events,
            COUNT(DISTINCT dem.mention_date) as unique_dates,
            MIN(dem.mention_date) as earliest_date,
            MAX(dem.mention_date) as latest_date
        FROM daily_event_mentions dem
        JOIN canonical_events ce ON dem.canonical_event_id = ce.id
        GROUP BY ce.initiating_country
        ORDER BY total_mentions DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Mentions':>10} {'Events':>10} {'Dates':>8} {'Date Range':>30}")
    print('-'*100)
    for row in result:
        date_range = f'{row[4]} to {row[5]}'
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,} {row[3]:>8,} {date_range:>30}')

    print('\n' + '='*100)
    print('SUMMARY & RECOMMENDATIONS')
    print('='*100)

    # Get overall summary
    summary = session.execute(text('''
        SELECT
            COUNT(*) FILTER (WHERE master_event_id IS NULL) as total_masters,
            COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) as total_children,
            COUNT(*) FILTER (WHERE master_event_id IS NULL AND llm_validated = TRUE) as validated_masters,
            COUNT(*) FILTER (WHERE master_event_id IS NULL AND material_score IS NOT NULL) as scored_masters
        FROM canonical_events
    ''')).fetchone()

    print(f'\nTotal Master Events: {summary[0]:,}')
    print(f'Total Child Events: {summary[1]:,}')
    print(f'Validated Masters: {summary[2]:,} ({100*summary[2]/summary[0]:.1f}%)')
    print(f'Scored Masters: {summary[3]:,} ({100*summary[3]/summary[0]:.1f}%)')

    if summary[1] > 0:
        print(f'\n[CRITICAL] {summary[1]:,} child events still exist!')
        print('   This means merge_canonical_events.py did not complete successfully.')
        print('   Child events should be deleted after merging their mentions to masters.')
    else:
        print('\n[OK] All child events successfully merged and deleted')

    if summary[2] < summary[0]:
        print(f'\n[WARNING] {summary[0] - summary[2]:,} master events not yet LLM validated')
    else:
        print('\n[OK] All master events LLM validated')

    if summary[3] < summary[0]:
        pct_unscored = 100 * (summary[0] - summary[3]) / summary[0]
        print(f'\n[WARNING] {summary[0] - summary[3]:,} master events not yet scored ({pct_unscored:.1f}% remaining)')
    else:
        print('\n[OK] All master events scored')

    print('='*100)
