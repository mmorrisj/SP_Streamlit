"""
Comprehensive Master Event Processing Verification

This script provides a detailed diagnostic report of the event pipeline processing status,
including consolidation, LLM validation, merging, and materiality scoring.

USAGE:
    python check_master_events.py

OUTPUT SECTIONS:
    Executive Summary - High-level metrics and pipeline stage distribution
    1. Master/Child Distribution - Shows consolidation status per country
    2. LLM Validation Status - Percentage of master events validated
    3. Orphaned Children Check - Detects data integrity issues
    4. Daily Event Mentions Coverage - Verifies event-mention linkage
    5. Data Integrity - Checks for children incorrectly marked as validated
    6. Materiality Scoring Coverage - Tracks scoring progress
    7. Multi-Day Event Consolidation - Shows temporal consolidation results
    8. Daily Event Mentions Integrity - Summary of mention data
    9. LLM Validation Timeline - When validation ran and how long it took
    10. Pipeline Stage Completion - Which stage each country is at
    11. Work Remaining Estimate - Specific counts of remaining work
    Summary & Recommendations - Actionable next steps per country

PIPELINE STAGES:
    Stage 1: Only daily clustering complete (consolidate_all_events.py not run)
        - All events are masters (0 children)
        - No consolidation has occurred

    Stage 2A: Consolidation complete, validation pending
        - Master-child relationships created
        - LLM validation not yet run
        - merge_canonical_events.py cannot run (requires validated masters)

    Stage 2B/2C: Validation started or merge in progress
        - Some masters validated
        - Children may still exist (merge incomplete)

    Complete: All processing done
        - All children merged and deleted
        - Only master events remain
        - Ready for materiality scoring

INTERPRETING RESULTS:
    - Children > 0: merge_canonical_events.py needs to run (or complete)
    - Validated = 0: llm_deconflict_canonical_events.py hasn't run
    - Unique Masters = 0: consolidate_all_events.py hasn't run
    - Scored < 100%: score_canonical_event_materiality.py needs to continue

COMMON ISSUES:
    - "6,107 child events still exist": Run merge_canonical_events.py
    - "0% validated but has children": Run llm_deconflict_canonical_events.py
    - "0 unique masters": Run consolidate_all_events.py first
    - "Orphaned children found": Database corruption - investigate immediately
"""

from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    print('='*100)
    print('MASTER EVENT PROCESSING VERIFICATION')
    print('='*100)

    # Executive Summary
    exec_summary = session.execute(text('''
        SELECT
            COUNT(DISTINCT initiating_country) as countries,
            COUNT(*) as total_events,
            COUNT(*) FILTER (WHERE master_event_id IS NULL) as masters,
            COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) as children,
            COUNT(*) FILTER (WHERE master_event_id IS NULL AND llm_validated = TRUE) as validated,
            COUNT(*) FILTER (WHERE master_event_id IS NULL AND material_score IS NOT NULL) as scored
        FROM canonical_events
    ''')).fetchone()

    print('\nEXECUTIVE SUMMARY:')
    print(f'  Countries: {exec_summary[0]}')
    print(f'  Total Events: {exec_summary[1]:,} ({exec_summary[2]:,} masters, {exec_summary[3]:,} children)')
    print(f'  LLM Validated: {exec_summary[4]:,} / {exec_summary[2]:,} masters ({100*exec_summary[4]/exec_summary[2]:.1f}%)')
    print(f'  Materiality Scored: {exec_summary[5]:,} / {exec_summary[2]:,} masters ({100*exec_summary[5]/exec_summary[2]:.1f}%)')

    # Pipeline stage summary
    stage_summary = session.execute(text('''
        SELECT
            CASE
                WHEN COUNT(DISTINCT CASE WHEN master_event_id IS NOT NULL THEN master_event_id END) = 0 THEN 'Stage 1'
                WHEN SUM(CASE WHEN master_event_id IS NOT NULL THEN 1 ELSE 0 END) > 0
                     AND SUM(CASE WHEN master_event_id IS NULL AND llm_validated = TRUE THEN 1 ELSE 0 END) = 0 THEN 'Stage 2A'
                WHEN SUM(CASE WHEN master_event_id IS NOT NULL THEN 1 ELSE 0 END) > 0 THEN 'Stage 2B/2C'
                ELSE 'Complete'
            END as stage,
            COUNT(DISTINCT initiating_country) as country_count
        FROM canonical_events
        GROUP BY initiating_country
    ''')).fetchall()

    stage_counts = {}
    for row in stage_summary:
        stage = row[0]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    print(f'\n  Pipeline Stages:')
    for stage in ['Stage 1', 'Stage 2A', 'Stage 2B/2C', 'Complete']:
        count = stage_counts.get(stage, 0)
        if count > 0:
            print(f'    {stage}: {count} countries')

    print('\n' + '='*100)

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

    # Check 9: Validation timestamps (when was LLM validation run?)
    print('\n9. LLM VALIDATION TIMELINE')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) FILTER (WHERE llm_validated = TRUE) as validated_count,
            MIN(llm_validated_at) as first_validation,
            MAX(llm_validated_at) as last_validation,
            EXTRACT(EPOCH FROM (MAX(llm_validated_at) - MIN(llm_validated_at)))/3600 as hours_duration
        FROM canonical_events
        WHERE llm_validated = TRUE
          AND llm_validated_at IS NOT NULL
        GROUP BY initiating_country
        ORDER BY last_validation DESC NULLS LAST
    ''')).fetchall()

    if result:
        print(f"{'Country':20} {'Validated':>12} {'First Validation':>22} {'Last Validation':>22} {'Duration (hrs)':>15}")
        print('-'*100)
        for row in result:
            first_str = str(row[2])[:19] if row[2] else 'N/A'
            last_str = str(row[3])[:19] if row[3] else 'N/A'
            duration = f'{row[4]:.1f}' if row[4] is not None else 'N/A'
            print(f'{row[0]:20} {row[1]:>12,} {first_str:>22} {last_str:>22} {duration:>15}')
    else:
        print('[INFO] No validation timestamps found')
        print('This indicates llm_deconflict_canonical_events.py has not been run,')
        print('OR was run before timestamps were added to the schema.')

    # Check 10: Pipeline stage completion by country
    print('\n10. PIPELINE STAGE COMPLETION BY COUNTRY')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            ce.initiating_country,
            COUNT(*) as total_events,
            COUNT(DISTINCT CASE WHEN ce.master_event_id IS NOT NULL THEN ce.master_event_id END) as has_consolidation,
            COUNT(*) FILTER (WHERE ce.master_event_id IS NULL AND ce.llm_validated = TRUE) as has_validation,
            COUNT(*) FILTER (WHERE ce.master_event_id IS NOT NULL) as has_children,
            CASE
                WHEN COUNT(DISTINCT CASE WHEN ce.master_event_id IS NOT NULL THEN ce.master_event_id END) = 0 THEN 'Stage 1'
                WHEN COUNT(*) FILTER (WHERE ce.master_event_id IS NOT NULL) > 0
                     AND COUNT(*) FILTER (WHERE ce.master_event_id IS NULL AND ce.llm_validated = TRUE) = 0 THEN 'Stage 2A'
                WHEN COUNT(*) FILTER (WHERE ce.master_event_id IS NOT NULL) > 0
                     AND COUNT(*) FILTER (WHERE ce.master_event_id IS NULL AND ce.llm_validated = TRUE) > 0 THEN 'Stage 2B/2C'
                ELSE 'Complete'
            END as pipeline_stage
        FROM canonical_events ce
        GROUP BY ce.initiating_country
        ORDER BY total_events DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Total':>10} {'Consolidate':>12} {'Validated':>12} {'Children':>10} {'Stage':>12}")
    print('-'*100)
    for row in result:
        stage_status = row[5]
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>12,} {row[3]:>12,} {row[4]:>10,} {stage_status:>12}')

    print('\nStage Legend:')
    print('  Stage 1     : Only daily clustering complete (no consolidation)')
    print('  Stage 2A    : Consolidation ran (has children, but not validated)')
    print('  Stage 2B/2C : Validation started/merge in progress')
    print('  Complete    : All children merged and deleted')

    # Check 11: Work Remaining Estimate
    print('\n11. WORK REMAINING ESTIMATE')
    print('-'*100)

    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) FILTER (WHERE master_event_id IS NULL AND llm_validated = FALSE) as unvalidated_masters,
            COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) as unmerged_children,
            COUNT(*) FILTER (WHERE master_event_id IS NULL AND material_score IS NULL) as unscored_masters
        FROM canonical_events
        GROUP BY initiating_country
        ORDER BY unvalidated_masters DESC
    ''')).fetchall()

    print(f"{'Country':20} {'Need Validation':>18} {'Need Merge':>12} {'Need Scoring':>15}")
    print('-'*100)
    for row in result:
        print(f'{row[0]:20} {row[1]:>18,} {row[2]:>12,} {row[3]:>15,}')

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

    print(f'\nOVERALL STATISTICS:')
    print(f'  Total Master Events: {summary[0]:,}')
    print(f'  Total Child Events: {summary[1]:,}')
    print(f'  Validated Masters: {summary[2]:,} ({100*summary[2]/summary[0]:.1f}%)')
    print(f'  Scored Masters: {summary[3]:,} ({100*summary[3]/summary[0]:.1f}%)')

    # Determine what needs to be done per country
    print('\nNEXT STEPS BY COUNTRY:')
    print('-'*100)

    per_country = session.execute(text('''
        SELECT
            ce.initiating_country,
            COUNT(*) as total,
            COUNT(DISTINCT CASE WHEN ce.master_event_id IS NOT NULL THEN ce.master_event_id END) as unique_masters,
            COUNT(*) FILTER (WHERE ce.master_event_id IS NOT NULL) as children,
            COUNT(*) FILTER (WHERE ce.master_event_id IS NULL AND ce.llm_validated = TRUE) as validated_masters,
            COUNT(*) FILTER (WHERE ce.master_event_id IS NULL AND ce.llm_validated = FALSE) as unvalidated_masters
        FROM canonical_events ce
        GROUP BY ce.initiating_country
        ORDER BY total DESC
    ''')).fetchall()

    for row in per_country:
        country = row[0]
        total = row[1]
        unique_masters = row[2]
        children = row[3]
        validated = row[4]
        unvalidated = row[5]

        print(f'\n{country}:')

        if unique_masters == 0 and children == 0:
            print(f'  1. Run: consolidate_all_events.py --country "{country}"')
            print(f'  2. Run: llm_deconflict_canonical_events.py --country "{country}" --batch-size 10')
            print(f'  3. Run: merge_canonical_events.py --country "{country}"')
            print(f'  4. Run: score_canonical_event_materiality.py --country "{country}"')
        elif children > 0 and validated == 0:
            print(f'  1. Run: llm_deconflict_canonical_events.py --country "{country}" --batch-size 10')
            print(f'  2. Run: merge_canonical_events.py --country "{country}"')
            print(f'  3. Run: score_canonical_event_materiality.py --country "{country}"')
        elif children > 0 and validated > 0:
            if unvalidated > 0:
                print(f'  1. Resume: llm_deconflict_canonical_events.py --country "{country}" --resume --batch-size 10')
                print(f'     ({unvalidated:,} masters still need validation)')
            print(f'  2. Run: merge_canonical_events.py --country "{country}"')
            print(f'     ({children:,} children need to be merged)')
            print(f'  3. Continue: score_canonical_event_materiality.py --country "{country}"')
        else:
            print(f'  1. Continue: score_canonical_event_materiality.py --country "{country}"')

    # Overall health assessment
    print('\n' + '='*100)
    print('PIPELINE HEALTH ASSESSMENT')
    print('='*100)

    if summary[1] > 0:
        print(f'\n[CRITICAL] {summary[1]:,} child events still exist!')
        print('   Child events should be deleted after merging their mentions to masters.')
        print('   This indicates merge_canonical_events.py did not complete successfully.')
    else:
        print('\n[OK] All child events successfully merged and deleted')

    if summary[2] < summary[0]:
        pct_unvalidated = 100 * (summary[0] - summary[2]) / summary[0]
        print(f'\n[WARNING] {summary[0] - summary[2]:,} master events not yet LLM validated ({pct_unvalidated:.1f}%)')
        if summary[1] == 0 and summary[2] == 0:
            print('   Note: Validation is optional if consolidation was not run')
    else:
        print('\n[OK] All master events LLM validated')

    if summary[3] < summary[0]:
        pct_unscored = 100 * (summary[0] - summary[3]) / summary[0]
        print(f'\n[WARNING] {summary[0] - summary[3]:,} master events not yet scored ({pct_unscored:.1f}% remaining)')
    else:
        print('\n[OK] All master events scored')

    print('='*100)
