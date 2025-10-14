#!/usr/bin/env python
"""
Test script for process_daily_news.py
Run this to debug the daily news processing pipeline.
"""

from datetime import date, timedelta
from backend.database import get_session
from backend.models import Document, RawEvent, CanonicalEvent, DailyEventMention
from sqlalchemy import func, select, and_

def check_data_availability():
    """Check what data is available in the database."""
    print("=" * 80)
    print("DATABASE STATUS CHECK")
    print("=" * 80)

    with get_session() as session:
        # Count documents
        doc_count = session.query(func.count(Document.doc_id)).scalar()
        print(f"\n📄 Documents: {doc_count}")

        # Count raw events
        raw_event_count = session.query(func.count(RawEvent.event_name)).scalar()
        print(f"📋 RawEvents: {raw_event_count}")

        # Count canonical events
        canonical_count = session.query(func.count(CanonicalEvent.id)).scalar()
        print(f"🎯 CanonicalEvents: {canonical_count}")

        # Count daily mentions
        mention_count = session.query(func.count(DailyEventMention.id)).scalar()
        print(f"📅 DailyEventMentions: {mention_count}")

        if doc_count == 0:
            print("\n❌ No documents found! You need to run document ingestion first.")
            print("   Run: python backend/scripts/atom.py")
            return False

        if raw_event_count == 0:
            print("\n❌ No raw events found! Documents have no event_name field.")
            print("   This might be a data issue.")
            return False

        # Get date range of documents
        stmt = select(func.min(Document.date), func.max(Document.date))
        min_date, max_date = session.execute(stmt).first()
        print(f"\n📆 Document date range: {min_date} to {max_date}")

        # Get countries
        stmt = select(Document.initiating_country).distinct()
        countries = list(session.scalars(stmt).all())
        print(f"🌍 Countries with documents: {', '.join([c for c in countries if c])[:100]}...")

        # Show sample documents with events
        print("\n📝 Sample documents with events:")
        stmt = (
            select(Document, RawEvent)
            .join(RawEvent, RawEvent.doc_id == Document.doc_id)
            .limit(5)
        )
        results = session.execute(stmt).all()
        for i, (doc, event) in enumerate(results, 1):
            print(f"  {i}. [{doc.date}] {doc.initiating_country}: {event.event_name[:60]}...")

        return True

def test_process_single_day(test_date=None, country=None):
    """Test processing a single day."""
    from backend.scripts.process_daily_news import process_daily_news

    if test_date is None:
        # Find a date with data
        with get_session() as session:
            stmt = select(Document.date).where(Document.date.isnot(None)).limit(1)
            test_date = session.scalars(stmt).first()

    if country is None:
        # Find a country with data
        with get_session() as session:
            stmt = (
                select(Document.initiating_country)
                .where(
                    and_(
                        Document.date == test_date,
                        Document.initiating_country.isnot(None)
                    )
                )
                .limit(1)
            )
            country = session.scalars(stmt).first()

    print("\n" + "=" * 80)
    print(f"TESTING DAILY PROCESSING: {test_date} for {country}")
    print("=" * 80)

    # Check how many documents/events exist for this day
    with get_session() as session:
        stmt = (
            select(func.count(Document.doc_id))
            .where(
                and_(
                    Document.date == test_date,
                    Document.initiating_country == country
                )
            )
        )
        doc_count = session.scalar(stmt)

        stmt = (
            select(func.count(RawEvent.event_name))
            .join(Document, Document.doc_id == RawEvent.doc_id)
            .where(
                and_(
                    Document.date == test_date,
                    Document.initiating_country == country
                )
            )
        )
        event_count = session.scalar(stmt)

        print(f"\nFound {doc_count} documents and {event_count} raw events for this day/country")

    if doc_count == 0:
        print(f"❌ No documents found for {test_date} / {country}")
        return

    # Run the processing
    print("\n🚀 Running process_daily_news...")
    try:
        process_daily_news(target_date=test_date, country=country)
        print("\n✅ Processing completed successfully!")

        # Check results
        with get_session() as session:
            mention_count = session.query(func.count(DailyEventMention.id)).scalar()
            canonical_count = session.query(func.count(CanonicalEvent.id)).scalar()
            print(f"\n📊 Results:")
            print(f"   DailyEventMentions: {mention_count}")
            print(f"   CanonicalEvents: {canonical_count}")

            # Show created mentions
            if mention_count > 0:
                print(f"\n✨ Created DailyEventMentions:")
                stmt = (
                    select(DailyEventMention)
                    .where(DailyEventMention.mention_date == test_date)
                    .limit(5)
                )
                mentions = list(session.scalars(stmt).all())
                for i, mention in enumerate(mentions, 1):
                    print(f"   {i}. {mention.consolidated_headline[:70]}...")
                    print(f"      Articles: {mention.article_count}, Sources: {len(mention.source_names)}")

    except Exception as e:
        print(f"\n❌ Error during processing: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main test function."""
    # Step 1: Check database status
    if not check_data_availability():
        print("\n⚠️  Cannot proceed with testing - fix data issues first")
        return

    # Step 2: Test processing a single day
    print("\n" + "=" * 80)
    response = input("\nDo you want to test processing a single day? (y/n): ")
    if response.lower() == 'y':
        date_input = input("Enter date (YYYY-MM-DD) or press Enter to auto-select: ").strip()
        country_input = input("Enter country or press Enter to auto-select: ").strip()

        test_date = date.fromisoformat(date_input) if date_input else None
        country = country_input if country_input else None

        test_process_single_day(test_date, country)

if __name__ == "__main__":
    main()
