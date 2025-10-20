#!/usr/bin/env python
"""
Debug script to diagnose why process_daily_news is finding 0 events.
Run this on your server to see what's happening at each step.
"""

from datetime import date
from shared.database.database import get_session
from shared.models.models import Document, RawEvent, InitiatingCountry
from sqlalchemy import select, func, and_

def debug_data_flow(target_date: date, country: str):
    """Debug the data flow step by step."""

    print("=" * 80)
    print(f"DEBUGGING: {target_date} / {country}")
    print("=" * 80)

    with get_session() as session:
        # Step 1: Check if Documents exist (using flattened InitiatingCountry table)
        print("\n[STEP 1] Checking Documents table...")
        doc_stmt = (
            select(func.count(Document.doc_id.distinct()))
            .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
            .where(
                and_(
                    Document.date == target_date,
                    InitiatingCountry.initiating_country == country
                )
            )
        )
        doc_count = session.scalar(doc_stmt)
        print(f"  Found {doc_count} documents for {target_date} / {country}")

        if doc_count == 0:
            print("\n  ❌ NO DOCUMENTS FOUND!")
            print("  Checking what dates/countries ARE available...")

            # Show available dates
            date_stmt = select(func.min(Document.date), func.max(Document.date))
            min_date, max_date = session.execute(date_stmt).first()
            print(f"    Date range in DB: {min_date} to {max_date}")

            # Show countries with data on this date (using flattened table)
            country_stmt = (
                select(InitiatingCountry.initiating_country, func.count(Document.doc_id.distinct()))
                .join(Document, Document.doc_id == InitiatingCountry.doc_id)
                .where(Document.date == target_date)
                .group_by(InitiatingCountry.initiating_country)
            )
            results = session.execute(country_stmt).all()
            print(f"\n    Countries with data on {target_date}:")
            for country_name, count in results:
                print(f"      - {country_name}: {count} documents")

            # Show dates with data for this country (using flattened table)
            date_stmt = (
                select(Document.date, func.count(Document.doc_id.distinct()))
                .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
                .where(InitiatingCountry.initiating_country == country)
                .group_by(Document.date)
                .order_by(Document.date.desc())
                .limit(10)
            )
            results = session.execute(date_stmt).all()
            print(f"\n    Recent dates with data for {country}:")
            for doc_date, count in results:
                print(f"      - {doc_date}: {count} documents")

            return

        # Step 2: Check if RawEvents exist
        print("\n[STEP 2] Checking RawEvents table...")
        raw_stmt = (
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
        raw_count = session.scalar(raw_stmt)
        print(f"  Found {raw_count} raw events")

        if raw_count == 0:
            print("\n  ❌ NO RAW EVENTS FOUND!")
            print("  Documents exist but no RawEvents. Possible causes:")
            print("    1. RawEvent table is empty (need to run flatten.py)")
            print("    2. Documents have no event_name field")
            print("    3. JOIN is failing")

            # Check total raw events
            total_raw = session.query(func.count(RawEvent.event_name)).scalar()
            print(f"\n    Total RawEvents in database: {total_raw}")

            if total_raw == 0:
                print("    → RawEvent table is EMPTY. Run: python backend/scripts/flatten.py")
            else:
                # Show sample of what RawEvents look like
                print("\n    Sample RawEvents:")
                sample_stmt = select(RawEvent).limit(5)
                samples = list(session.scalars(sample_stmt).all())
                for raw in samples:
                    print(f"      - doc_id={raw.doc_id}, event_name={raw.event_name[:60]}...")

            return

        # Step 3: Show sample raw events
        print("\n[STEP 3] Sample raw events that WILL be processed:")
        sample_stmt = (
            select(Document, RawEvent)
            .join(RawEvent, RawEvent.doc_id == Document.doc_id)
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
        for i, (doc, raw) in enumerate(results, 1):
            print(f"  {i}. {raw.event_name[:70]}...")
            print(f"     Source: {doc.source_name}, Date: {doc.date}")

        print("\n✅ Data exists! The pipeline should work.")
        print("\nNext steps:")
        print("  1. Run: python backend/scripts/process_daily_news.py --date", target_date, "--country", f'"{country}"')
        print("  2. Check for errors in the clustering/LLM steps")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Debug news tracker data flow')
    parser.add_argument('--date', type=str, required=True, help='Date to check (YYYY-MM-DD)')
    parser.add_argument('--country', type=str, required=True, help='Country to check')
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    debug_data_flow(target_date, args.country)
