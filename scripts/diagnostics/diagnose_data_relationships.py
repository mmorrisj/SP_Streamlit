#!/usr/bin/env python
"""
Diagnostic script to check data relationships between tables.
This will help identify why raw events aren't being found.
"""

from datetime import date
from backend.database import get_session
from backend.models import Document, RawEvent, InitiatingCountry
from sqlalchemy import select, func, and_, text

def diagnose_relationships(target_date_str: str = None, country: str = None):
    """Diagnose data relationships and potential JOIN issues."""

    print("=" * 80)
    print("DATA RELATIONSHIP DIAGNOSTIC")
    print("=" * 80)

    with get_session() as session:
        # Step 1: Overall counts
        print("\n[STEP 1] Overall Table Counts")
        print("-" * 40)

        total_docs = session.query(func.count(Document.doc_id)).scalar()
        total_raw_events = session.query(func.count(RawEvent.event_name)).scalar()
        total_init_countries = session.query(func.count(InitiatingCountry.initiating_country)).scalar()

        print(f"Documents: {total_docs}")
        print(f"RawEvents: {total_raw_events}")
        print(f"InitiatingCountry records: {total_init_countries}")

        # Step 2: Sample relationships
        print("\n[STEP 2] Sample Document → RawEvent Relationships")
        print("-" * 40)

        # Get a sample document with raw events
        sample_doc_stmt = (
            select(Document.doc_id, Document.date, Document.initiating_country, Document.event_name)
            .where(Document.event_name.isnot(None))
            .limit(3)
        )
        sample_docs = session.execute(sample_doc_stmt).all()

        for doc_id, doc_date, init_country, event_name in sample_docs:
            print(f"\nDocument: {doc_id}")
            print(f"  Date: {doc_date}")
            print(f"  Initiating Country (raw): {init_country}")
            print(f"  Event Name (raw): {event_name[:100] if event_name else 'None'}...")

            # Check if RawEvents exist for this doc
            raw_count = session.query(func.count(RawEvent.event_name)).filter(
                RawEvent.doc_id == doc_id
            ).scalar()
            print(f"  → RawEvents for this doc: {raw_count}")

            # Check if InitiatingCountry records exist for this doc
            init_count = session.query(func.count(InitiatingCountry.initiating_country)).filter(
                InitiatingCountry.doc_id == doc_id
            ).scalar()
            print(f"  → InitiatingCountry records for this doc: {init_count}")

            # Show the flattened records
            if raw_count > 0:
                raw_events = session.query(RawEvent.event_name).filter(
                    RawEvent.doc_id == doc_id
                ).all()
                print(f"  → Flattened RawEvents:")
                for (evt,) in raw_events:
                    print(f"     - {evt[:80]}...")

            if init_count > 0:
                init_countries = session.query(InitiatingCountry.initiating_country).filter(
                    InitiatingCountry.doc_id == doc_id
                ).all()
                print(f"  → Flattened InitiatingCountries:")
                for (country_name,) in init_countries:
                    print(f"     - {country_name}")

        # Step 3: Check for specific date/country if provided
        if target_date_str and country:
            target_date = date.fromisoformat(target_date_str)

            print(f"\n[STEP 3] Checking Specific Date/Country: {target_date} / {country}")
            print("-" * 40)

            # Method 1: Direct query (OLD - won't work with flattened schema)
            print("\n❌ Method 1: Direct query (Document.initiating_country - BROKEN)")
            try:
                direct_stmt = (
                    select(func.count(RawEvent.event_name))
                    .join(Document, Document.doc_id == RawEvent.doc_id)
                    .where(
                        and_(
                            Document.date == target_date,
                            Document.initiating_country == country
                        )
                    )
                )
                direct_count = session.scalar(direct_stmt)
                print(f"  Found: {direct_count} events")
            except Exception as e:
                print(f"  ERROR: {e}")

            # Method 2: Using JOIN with InitiatingCountry (NEW - should work)
            print("\n✅ Method 2: JOIN with InitiatingCountry (CORRECT)")
            try:
                join_stmt = (
                    select(func.count(RawEvent.event_name))
                    .join(Document, Document.doc_id == RawEvent.doc_id)
                    .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
                    .where(
                        and_(
                            Document.date == target_date,
                            InitiatingCountry.initiating_country == country
                        )
                    )
                )
                join_count = session.scalar(join_stmt)
                print(f"  Found: {join_count} events")
            except Exception as e:
                print(f"  ERROR: {e}")

            # Method 3: Step-by-step breakdown
            print("\n🔍 Method 3: Step-by-Step Breakdown")

            # Check documents for this date
            doc_count = session.query(func.count(Document.doc_id)).filter(
                Document.date == target_date
            ).scalar()
            print(f"  Documents on {target_date}: {doc_count}")

            # Check InitiatingCountry records for this date
            init_for_date_stmt = (
                select(func.count(InitiatingCountry.initiating_country.distinct()))
                .join(Document, Document.doc_id == InitiatingCountry.doc_id)
                .where(Document.date == target_date)
            )
            init_for_date_count = session.scalar(init_for_date_stmt)
            print(f"  InitiatingCountry records for {target_date}: {init_for_date_count}")

            # Check InitiatingCountry records for this country
            init_for_country_stmt = (
                select(func.count(InitiatingCountry.doc_id.distinct()))
                .where(InitiatingCountry.initiating_country == country)
            )
            init_for_country_count = session.scalar(init_for_country_stmt)
            print(f"  InitiatingCountry records for '{country}': {init_for_country_count}")

            # Check documents for this date AND country
            doc_for_both_stmt = (
                select(func.count(Document.doc_id.distinct()))
                .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
                .where(
                    and_(
                        Document.date == target_date,
                        InitiatingCountry.initiating_country == country
                    )
                )
            )
            doc_for_both_count = session.scalar(doc_for_both_stmt)
            print(f"  Documents for {target_date} AND '{country}': {doc_for_both_count}")

            # Check RawEvents for these documents
            if doc_for_both_count > 0:
                raw_for_both_stmt = (
                    select(func.count(RawEvent.event_name))
                    .join(Document, Document.doc_id == RawEvent.doc_id)
                    .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
                    .where(
                        and_(
                            Document.date == target_date,
                            InitiatingCountry.initiating_country == country
                        )
                    )
                )
                raw_for_both_count = session.scalar(raw_for_both_stmt)
                print(f"  RawEvents for these documents: {raw_for_both_count}")

        # Step 4: Show available dates and countries
        print("\n[STEP 4] Available Data")
        print("-" * 40)

        # Show date range
        date_range_stmt = select(func.min(Document.date), func.max(Document.date))
        min_date, max_date = session.execute(date_range_stmt).first()
        print(f"\nDate range: {min_date} to {max_date}")

        # Show top 10 countries by document count
        print("\nTop 10 Countries (by document count):")
        country_stmt = (
            select(InitiatingCountry.initiating_country, func.count(InitiatingCountry.doc_id.distinct()))
            .group_by(InitiatingCountry.initiating_country)
            .order_by(func.count(InitiatingCountry.doc_id.distinct()).desc())
            .limit(10)
        )
        countries = session.execute(country_stmt).all()
        for country_name, count in countries:
            print(f"  {country_name}: {count} documents")

        # Show recent dates with data
        print("\nRecent 10 dates with data:")
        recent_dates_stmt = (
            select(Document.date, func.count(Document.doc_id))
            .where(Document.date.isnot(None))
            .group_by(Document.date)
            .order_by(Document.date.desc())
            .limit(10)
        )
        dates = session.execute(recent_dates_stmt).all()
        for doc_date, count in dates:
            print(f"  {doc_date}: {count} documents")

        print("\n" + "=" * 80)
        print("DIAGNOSTIC COMPLETE")
        print("=" * 80)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Diagnose data relationship issues')
    parser.add_argument('--date', type=str, help='Date to check (YYYY-MM-DD)')
    parser.add_argument('--country', type=str, help='Country to check')
    args = parser.parse_args()

    diagnose_relationships(args.date, args.country)
