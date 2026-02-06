"""Check if consolidation actually completed by looking for multi-day events"""

from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    result = session.execute(text('''
        SELECT
            initiating_country,
            COUNT(*) FILTER (WHERE total_mention_days > 1) as multi_day,
            COUNT(*) as total,
            ROUND(100.0 * COUNT(*) FILTER (WHERE total_mention_days > 1) / COUNT(*), 1) as pct
        FROM canonical_events
        WHERE master_event_id IS NULL
        GROUP BY initiating_country
        ORDER BY multi_day DESC
    ''')).fetchall()

    print('='*60)
    print('MULTI-DAY EVENT CHECK (Proof of Consolidation)')
    print('='*60)
    print(f"{'Country':20} {'Multi-Day':>10} {'Total':>10} {'%':>8}")
    print('-'*60)
    for row in result:
        print(f'{row[0]:20} {row[1]:>10,} {row[2]:>10,} {row[3]:>7.1f}%')

    print('\n' + '='*60)
    print('INTERPRETATION:')
    print('='*60)
    print('If Multi-Day > 0: Consolidation & merge COMPLETED')
    print('If Multi-Day = 0: Consolidation never ran OR failed')
    print('='*60)
