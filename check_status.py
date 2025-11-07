#!/usr/bin/env python
"""Check pipeline completion status."""

from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    # Check canonical events (batch clustering + LLM deconfliction completed)
    print('=== CANONICAL EVENTS (Batch Clustering + LLM Deconfliction) ===')
    result = session.execute(text('''
        SELECT
            DATE_TRUNC('month', start_date) as month,
            COUNT(DISTINCT canonical_event_id) as event_count,
            MIN(start_date) as earliest,
            MAX(end_date) as latest
        FROM canonical_events
        WHERE start_date >= '2024-11-01'
        GROUP BY DATE_TRUNC('month', start_date)
        ORDER BY month
    ''')).fetchall()

    for row in result:
        print(f'{row[0].strftime("%Y-%m")}: {row[1]} events (range: {row[2]} to {row[3]})')

    print('\n=== DAILY SUMMARIES ===')
    result = session.execute(text('''
        SELECT
            DATE_TRUNC('month', start_date) as month,
            initiating_country,
            COUNT(*) as summary_count
        FROM event_summaries
        WHERE period_type = 'daily'
        AND start_date >= '2024-11-01'
        GROUP BY DATE_TRUNC('month', start_date), initiating_country
        ORDER BY month, initiating_country
    ''')).fetchall()

    for row in result:
        print(f'{row[0].strftime("%Y-%m")} - {row[1]}: {row[2]} summaries')

    print('\n=== WEEKLY SUMMARIES ===')
    result = session.execute(text('''
        SELECT
            DATE_TRUNC('month', start_date) as month,
            initiating_country,
            COUNT(*) as summary_count
        FROM event_summaries
        WHERE period_type = 'weekly'
        AND start_date >= '2024-11-01'
        GROUP BY DATE_TRUNC('month', start_date), initiating_country
        ORDER BY month, initiating_country
    ''')).fetchall()

    if result:
        for row in result:
            print(f'{row[0].strftime("%Y-%m")} - {row[1]}: {row[2]} summaries')
    else:
        print('None found')

    print('\n=== MONTHLY SUMMARIES ===')
    result = session.execute(text('''
        SELECT
            DATE_TRUNC('month', start_date) as month,
            initiating_country,
            COUNT(*) as summary_count
        FROM event_summaries
        WHERE period_type = 'monthly'
        AND start_date >= '2024-11-01'
        GROUP BY DATE_TRUNC('month', start_date), initiating_country
        ORDER BY month, initiating_country
    ''')).fetchall()

    if result:
        for row in result:
            print(f'{row[0].strftime("%Y-%m")} - {row[1]}: {row[2]} summaries')
    else:
        print('None found')
