"""
Database validation script to verify:
1. Documents can be queried by influencer countries
2. Documents can be queried by recipient countries
3. RawEvents table is populated
4. All relationship tables are populated
"""

import yaml
from backend.database import get_session
from backend.models import Document
from sqlalchemy import text

def load_config():
    """Load config.yaml"""
    with open('backend/config.yaml', 'r') as f:
        return yaml.safe_load(f)

def validate_database():
    config = load_config()

    with get_session() as session:
        print("=" * 80)
        print("DATABASE VALIDATION REPORT")
        print("=" * 80)

        # 1. Check total document count
        total_docs = session.query(Document).count()
        print(f"\nTotal Documents: {total_docs}")

        # 2. Check RawEvents table
        print("\n" + "=" * 80)
        print("RAW EVENTS TABLE")
        print("=" * 80)
        result = session.execute(text("SELECT COUNT(*) FROM raw_events")).scalar()
        print(f"Total RawEvents: {result}")

        # Sample of raw events
        sample_events = session.execute(
            text("SELECT event_name, COUNT(*) as count FROM raw_events GROUP BY event_name ORDER BY count DESC LIMIT 10")
        ).fetchall()
        print("\nTop 10 Events:")
        for event_name, count in sample_events:
            print(f"  - {event_name}: {count} documents")

        # 3. Check Categories table
        print("\n" + "=" * 80)
        print("CATEGORIES TABLE")
        print("=" * 80)
        result = session.execute(text("SELECT COUNT(*) FROM categories")).scalar()
        print(f"Total Category Relationships: {result}")

        category_breakdown = session.execute(
            text("SELECT category, COUNT(*) as count FROM categories GROUP BY category ORDER BY count DESC")
        ).fetchall()
        print("\nCategory Breakdown:")
        for category, count in category_breakdown:
            print(f"  - {category}: {count} documents")

        # 4. Check Subcategories table
        print("\n" + "=" * 80)
        print("SUBCATEGORIES TABLE")
        print("=" * 80)
        result = session.execute(text("SELECT COUNT(*) FROM subcategories")).scalar()
        print(f"Total Subcategory Relationships: {result}")

        subcategory_breakdown = session.execute(
            text("SELECT subcategory, COUNT(*) as count FROM subcategories GROUP BY subcategory ORDER BY count DESC LIMIT 10")
        ).fetchall()
        print("\nTop 10 Subcategories:")
        for subcategory, count in subcategory_breakdown:
            print(f"  - {subcategory}: {count} documents")

        # 5. Check Initiating Countries (Influencers)
        print("\n" + "=" * 80)
        print("INITIATING COUNTRIES (INFLUENCERS)")
        print("=" * 80)
        result = session.execute(text("SELECT COUNT(*) FROM initiating_countries")).scalar()
        print(f"Total Initiating Country Relationships: {result}")

        influencers = config.get('influencers', [])
        print(f"\nInfluencers from config.yaml: {influencers}")
        print("\nDocument counts by influencer country:")

        for country in influencers:
            count = session.execute(
                text("SELECT COUNT(DISTINCT doc_id) FROM initiating_countries WHERE initiating_country = :country"),
                {"country": country}
            ).scalar()
            print(f"  - {country}: {count} documents")

        # 6. Check Recipient Countries
        print("\n" + "=" * 80)
        print("RECIPIENT COUNTRIES")
        print("=" * 80)
        result = session.execute(text("SELECT COUNT(*) FROM recipient_countries")).scalar()
        print(f"Total Recipient Country Relationships: {result}")

        recipients = config.get('recipients', [])
        print(f"\nRecipients from config.yaml: {', '.join(recipients[:5])}... (and {len(recipients) - 5} more)")
        print("\nDocument counts by recipient country (top 10):")

        recipient_counts = []
        for country in recipients:
            count = session.execute(
                text("SELECT COUNT(DISTINCT doc_id) FROM recipient_countries WHERE recipient_country = :country"),
                {"country": country}
            ).scalar()
            recipient_counts.append((country, count))

        # Sort by count and show top 10
        recipient_counts.sort(key=lambda x: x[1], reverse=True)
        for country, count in recipient_counts[:10]:
            print(f"  - {country}: {count} documents")

        # 7. Test a complex query - Documents by China targeting Israel
        print("\n" + "=" * 80)
        print("COMPLEX QUERY TEST: China -> Israel documents")
        print("=" * 80)

        result = session.execute(text("""
            SELECT COUNT(DISTINCT d.doc_id)
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            WHERE ic.initiating_country = 'China'
            AND rc.recipient_country = 'Israel'
        """)).scalar()
        print(f"Documents where China targets Israel: {result}")

        # 8. Test another complex query - Iran documents with Diplomacy category
        print("\n" + "=" * 80)
        print("COMPLEX QUERY TEST: Iran + Diplomacy category")
        print("=" * 80)

        result = session.execute(text("""
            SELECT COUNT(DISTINCT d.doc_id)
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN categories c ON d.doc_id = c.doc_id
            WHERE ic.initiating_country = 'Iran'
            AND c.category = 'Diplomacy'
        """)).scalar()
        print(f"Documents where Iran engages in Diplomacy: {result}")

        # 9. Sample document with all relationships
        print("\n" + "=" * 80)
        print("SAMPLE DOCUMENT WITH ALL RELATIONSHIPS")
        print("=" * 80)

        sample_doc = session.execute(text("""
            SELECT d.doc_id, d.title, d.date
            FROM documents d
            LIMIT 1
        """)).fetchone()

        if sample_doc:
            doc_id, title, date = sample_doc
            print(f"\nDocument ID: {doc_id}")
            print(f"Title: {title}")
            print(f"Date: {date}")

            # Get categories
            categories = session.execute(
                text("SELECT category FROM categories WHERE doc_id = :doc_id"),
                {"doc_id": doc_id}
            ).fetchall()
            print(f"\nCategories: {', '.join([c[0] for c in categories])}")

            # Get subcategories
            subcategories = session.execute(
                text("SELECT subcategory FROM subcategories WHERE doc_id = :doc_id"),
                {"doc_id": doc_id}
            ).fetchall()
            print(f"Subcategories: {', '.join([s[0] for s in subcategories])}")

            # Get initiating countries
            init_countries = session.execute(
                text("SELECT initiating_country FROM initiating_countries WHERE doc_id = :doc_id"),
                {"doc_id": doc_id}
            ).fetchall()
            print(f"Initiating Countries: {', '.join([i[0] for i in init_countries])}")

            # Get recipient countries
            rec_countries = session.execute(
                text("SELECT recipient_country FROM recipient_countries WHERE doc_id = :doc_id"),
                {"doc_id": doc_id}
            ).fetchall()
            print(f"Recipient Countries: {', '.join([r[0] for r in rec_countries])}")

            # Get events
            events = session.execute(
                text("SELECT event_name FROM raw_events WHERE doc_id = :doc_id"),
                {"doc_id": doc_id}
            ).fetchall()
            if events:
                print(f"Events: {', '.join([e[0] for e in events])}")
            else:
                print("Events: None")

        print("\n" + "=" * 80)
        print("VALIDATION COMPLETE")
        print("=" * 80)

if __name__ == "__main__":
    validate_database()
