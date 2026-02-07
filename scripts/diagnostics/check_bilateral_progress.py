"""
Quick script to check bilateral summary generation progress.

Usage:
    python check_bilateral_progress.py
"""

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.database.database import get_session
from shared.models.models import BilateralRelationshipSummary
from sqlalchemy import text
from datetime import datetime, timedelta

with get_session() as session:
    # Config countries
    influencers = ['China', 'Russia', 'Iran', 'Turkey', 'United States']
    recipients = [
        'Bahrain', 'Cyprus', 'Egypt', 'Iran', 'Iraq', 'Israel', 'Jordan',
        'Kuwait', 'Lebanon', 'Libya', 'Oman', 'Palestine', 'Qatar',
        'Saudi Arabia', 'Syria', 'Turkey', 'United Arab Emirates', 'UAE', 'Yemen'
    ]

    # Get actual target (pairs with ≥25 docs, config-filtered, excluding same-country)
    target = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT ic.initiating_country, rc.recipient_country
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            WHERE ic.initiating_country = ANY(:influencers)
            AND rc.recipient_country = ANY(:recipients)
            AND ic.initiating_country != rc.recipient_country
            GROUP BY ic.initiating_country, rc.recipient_country
            HAVING COUNT(DISTINCT d.doc_id) >= 25
        ) subquery
    """), {'influencers': influencers, 'recipients': recipients}).scalar()

    total = session.query(BilateralRelationshipSummary).count()

    print('=' * 80)
    print('BILATERAL SUMMARY GENERATION PROGRESS')
    print('=' * 80)
    print()
    print(f'✅ Completed: {total}/{target} ({(total/target)*100:.1f}%)')
    print(f'⏳ Remaining: {target - total}')

    if total < target:
        print(f'⏱️  Estimated time: ~{target - total} minutes')
    else:
        print('🎉 All summaries complete!')

    print()

    # Show 10 most recent
    recent = session.query(BilateralRelationshipSummary).order_by(
        BilateralRelationshipSummary.created_at.desc()
    ).limit(10).all()

    print('Most recently created:')
    for i, s in enumerate(recent, 1):
        time_str = s.created_at.strftime('%H:%M:%S')
        print(f'{i:2}. {s.initiating_country:15} → {s.recipient_country:25} ({s.total_documents:6,} docs) [{time_str}]')

    print()
    print('=' * 80)
    print(f'Dashboard: http://localhost:8501')
    print('=' * 80)
