#!/usr/bin/env python
"""
Test specific dates to see what data exists.
"""

from datetime import date
from backend.database import get_session
from backend.models import Document, RawEvent, InitiatingCountry
from sqlalchemy import select, func, and_

def test_date(target_date_str: str, country: str):
    """Test a specific date/country combination."""

    target_date = date.fromisoformat(target_date_str)

    print(f"\n{'='*80}")
    print(f"Testing: {target_date} / {country}")
    print('='*80)

    with get_session() as session:
        # Test 1: Documents for this date
        doc_count_date = session.query(func.count(Document.doc_id)).filter(
            Document.date == target_date
        ).scalar()
        print(f"Documents on {target_date}: {doc_count_date}")

        # Test 2: InitiatingCountry records for this country
        init_count_country = session.query(func.count(InitiatingCountry.doc_id.distinct())).filter(
            InitiatingCountry.initiating_country == country
        ).scalar()
        print(f"Documents for {country} (any date): {init_count_country}")

        # Test 3: Documents for THIS date AND country
        doc_count_both = session.query(func.count(Document.doc_id.distinct())).select_from(Document).join(
            InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
        ).filter(
            and_(
                Document.date == target_date,
                InitiatingCountry.initiating_country == country
            )
        ).scalar()
        print(f"Documents for {target_date} AND {country}: {doc_count_both}")

        # Test 4: RawEvents for these documents
        if doc_count_both > 0:
            raw_count = session.query(func.count(RawEvent.event_name)).select_from(RawEvent).join(
                Document, Document.doc_id == RawEvent.doc_id
            ).join(
                InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id
            ).filter(
                and_(
                    Document.date == target_date,
                    InitiatingCountry.initiating_country == country
                )
            ).scalar()
            print(f"RawEvents for these documents: {raw_count}")

            # Show a sample
            if raw_count > 0:
                print("\nSample events:")
                sample_stmt = (
                    select(RawEvent.event_name, Document.source_name)
                    .select_from(RawEvent)
                    .join(Document, Document.doc_id == RawEvent.doc_id)
                    .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
                    .where(
                        and_(
                            Document.date == target_date,
                            InitiatingCountry.initiating_country == country
                        )
                    )
                    .limit(5)
                )
                results = session.execute(sample_stmt).all()
                for event_name, source in results:
                    print(f"  - {event_name[:80]}... (Source: {source})")
        else:
            print(f"\n❌ No documents found for {target_date} AND {country}")

            # Show what dates DO have data for this country
            print(f"\nRecent dates with {country} data:")
            recent_stmt = (
                select(Document.date, func.count(Document.doc_id.distinct()))
                .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
                .where(InitiatingCountry.initiating_country == country)
                .group_by(Document.date)
                .order_by(Document.date.desc())
                .limit(10)
            )
            results = session.execute(recent_stmt).all()
            for doc_date, count in results:
                print(f"  {doc_date}: {count} documents")

if __name__ == "__main__":
    # Test the dates the user tried
    test_date("2024-08-01", "China")
    test_date("2024-08-05", "China")
    test_date("2025-06-01", "China")  # This one worked in debug

    print(f"\n{'='*80}")
    print("SUMMARY")
    print('='*80)
