#!/usr/bin/env python
"""
Test specific dates to see what data exists.
"""
import pandas as pd
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

        # Test 4: Export all documents for this date to CSV
        if doc_count_date > 0:
            print(f"\n📊 Exporting all documents for {target_date} to CSV...")

            # Get all documents for this date with their flattened relationships
            export_stmt = (
                select(
                    Document.doc_id,
                    Document.date,
                    Document.title,
                    Document.source_name,
                    Document.initiating_country,
                    Document.recipient_country,
                    Document.category,
                    Document.subcategory,
                    Document.event_name,
                    Document.distilled_text,
                    Document.salience,
                    Document.salience_bool
                )
                .where(Document.date == target_date)
                .order_by(Document.doc_id)
            )

            documents = session.execute(export_stmt).all()

            # Convert to DataFrame
            df = pd.DataFrame(documents, columns=[
                'doc_id', 'date', 'title', 'source_name',
                'initiating_country', 'recipient_country',
                'category', 'subcategory', 'event_name',
                'distilled_text', 'salience', 'salience_bool'
            ])

            # Export to CSV
            filename = f"documents_{target_date}_{country}.csv"
            df.to_csv(filename, index=False)
            print(f"✅ Exported {len(df)} documents to: {filename}")

            # Also export InitiatingCountry relationships for this date
            init_stmt = (
                select(InitiatingCountry.doc_id, InitiatingCountry.initiating_country)
                .join(Document, Document.doc_id == InitiatingCountry.doc_id)
                .where(Document.date == target_date)
                .order_by(InitiatingCountry.doc_id)
            )
            init_records = session.execute(init_stmt).all()
            init_df = pd.DataFrame(init_records, columns=['doc_id', 'initiating_country'])
            init_filename = f"./initiating_countries_{target_date}.csv"
            init_df.to_csv(init_filename, index=False)
            print(f"✅ Exported {len(init_df)} InitiatingCountry records to: {init_filename}")

            # Export RawEvent relationships for this date
            raw_stmt = (
                select(RawEvent.doc_id, RawEvent.event_name)
                .join(Document, Document.doc_id == RawEvent.doc_id)
                .where(Document.date == target_date)
                .order_by(RawEvent.doc_id)
            )
            raw_records = session.execute(raw_stmt).all()
            raw_df = pd.DataFrame(raw_records, columns=['doc_id', 'event_name'])
            raw_filename = f"raw_events_{target_date}.csv"
            raw_df.to_csv(raw_filename, index=False)
            print(f"✅ Exported {len(raw_df)} RawEvent records to: {raw_filename}")

        # Test 5: RawEvents for these documents
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
            print(f"\nRawEvents for {target_date} AND {country}: {raw_count}")

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
