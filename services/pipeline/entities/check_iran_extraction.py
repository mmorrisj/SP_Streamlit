"""
Quick diagnostic script to check Iran entity extraction status.
"""

import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from shared.database.database import get_session
from shared.models.models import Document, RawEntity, InitiatingCountry, RecipientCountry
from shared.utils.utils import Config
from sqlalchemy import func, and_

def check_iran_status():
    # Load config to get valid recipients
    config_path = Path(__file__).parent.parent.parent.parent / 'shared' / 'config' / 'config.yaml'
    config = Config.from_yaml(config_path)
    valid_recipients = [r for r in config.get('recipients', []) if r != 'Iran']

    with get_session() as session:
        # Total Iran documents (with valid recipients only, excluding Iran-Iran)
        total_docs = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry
        ).filter(
            and_(
                InitiatingCountry.initiating_country == 'Iran',
                RecipientCountry.recipient_country.in_(valid_recipients),
                RecipientCountry.recipient_country != 'Iran'
            )
        ).scalar()

        # Docs with entities
        docs_with_entities = session.query(
            func.count(func.distinct(RawEntity.doc_id))
        ).join(
            Document
        ).join(
            InitiatingCountry
        ).join(
            RecipientCountry
        ).filter(
            and_(
                InitiatingCountry.initiating_country == 'Iran',
                RecipientCountry.recipient_country.in_(valid_recipients),
                RecipientCountry.recipient_country != 'Iran'
            )
        ).scalar()

        # Check 2025-06-01 specifically
        docs_on_june_1 = session.query(func.count(func.distinct(Document.doc_id))).join(
            InitiatingCountry
        ).join(
            RecipientCountry
        ).filter(
            and_(
                InitiatingCountry.initiating_country == 'Iran',
                Document.date == datetime(2025, 6, 1).date(),
                RecipientCountry.recipient_country.in_(valid_recipients),
                RecipientCountry.recipient_country != 'Iran'
            )
        ).scalar()

        docs_with_entities_june_1 = session.query(
            func.count(func.distinct(RawEntity.doc_id))
        ).join(
            Document
        ).join(
            InitiatingCountry
        ).join(
            RecipientCountry
        ).filter(
            and_(
                InitiatingCountry.initiating_country == 'Iran',
                Document.date == datetime(2025, 6, 1).date(),
                RecipientCountry.recipient_country.in_(valid_recipients),
                RecipientCountry.recipient_country != 'Iran'
            )
        ).scalar()

        print("="*60)
        print("IRAN ENTITY EXTRACTION STATUS")
        print("="*60)
        print(f"\nOverall:")
        print(f"  Total Iran documents: {total_docs}")
        print(f"  Documents with entities: {docs_with_entities}")
        print(f"  Coverage: {docs_with_entities / total_docs * 100 if total_docs > 0 else 0:.1f}%")
        print(f"  Remaining: {total_docs - docs_with_entities}")

        print(f"\n2025-06-01 Specifically:")
        print(f"  Total documents: {docs_on_june_1}")
        print(f"  With entities: {docs_with_entities_june_1}")
        print(f"  Without entities: {docs_on_june_1 - docs_with_entities_june_1}")

        # Get sample doc_ids without entities on 2025-06-01
        if docs_on_june_1 > docs_with_entities_june_1:
            print(f"\nSample doc_ids WITHOUT entities on 2025-06-01:")
            docs_without = session.query(Document.doc_id).join(
                InitiatingCountry
            ).join(
                RecipientCountry
            ).outerjoin(
                RawEntity,
                Document.doc_id == RawEntity.doc_id
            ).filter(
                and_(
                    InitiatingCountry.initiating_country == 'Iran',
                    Document.date == datetime(2025, 6, 1).date(),
                    RecipientCountry.recipient_country.in_(valid_recipients),
                    RecipientCountry.recipient_country != 'Iran',
                    RawEntity.doc_id.is_(None)
                )
            ).distinct().limit(5).all()

            for (doc_id,) in docs_without:
                print(f"  - {doc_id}")

        print("="*60)

if __name__ == "__main__":
    check_iran_status()
