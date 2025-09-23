from backend.models import Document, Category, Subcategory, InitiatingCountry, RecipientCountry, Project, RawEvent
from backend.database import get_session, init_database
from backend.scripts.flatten_events import flatten_event

def split_field(field):
    """Split multi-value fields by semicolon and clean whitespace."""
    if field:
        return [f.strip() for f in field.split(";") if f.strip()]
    return []

def normalize_data(batch_size=1000):
    """
    Split document fields into one-to-many relationships with optimized batch processing.

    Args:
        batch_size (int): Number of documents to process in each batch
    """
    print("🚀 Starting data normalization process...")

    # Initialize database tables if they don't exist
    init_database()

    with get_session() as session:
        # Get total document count for progress tracking
        total_docs = session.query(Document).count()
        print(f"📊 Processing {total_docs} documents in batches of {batch_size}")

        # Preload existing relationships to avoid redundant queries
        print("📦 Loading existing relationships...")
        existing_categories = {(c.doc_id, c.category) for c in session.query(Category).all()}
        existing_subcategories = {(s.doc_id, s.subcategory) for s in session.query(Subcategory).all()}
        existing_init_countries = {(i.doc_id, i.initiating_country) for i in session.query(InitiatingCountry).all()}
        existing_rec_countries = {(r.doc_id, r.recipient_country) for r in session.query(RecipientCountry).all()}
        existing_projects = {(p.doc_id, p.project) for p in session.query(Project).all()}
        existing_events = {(e.doc_id, e.event_name) for e in session.query(RawEvent).all()}

        print(f"📋 Found existing relationships:")
        print(f"  - Categories: {len(existing_categories)}")
        print(f"  - Subcategories: {len(existing_subcategories)}")
        print(f"  - Initiating Countries: {len(existing_init_countries)}")
        print(f"  - Recipient Countries: {len(existing_rec_countries)}")
        print(f"  - Projects: {len(existing_projects)}")
        print(f"  - Events: {len(existing_events)}")

        # Process documents in batches
        processed_count = 0
        new_records = []

        # Query documents in batches
        for offset in range(0, total_docs, batch_size):
            documents = session.query(Document).offset(offset).limit(batch_size).all()

            for doc in documents:
                try:
                    # Process categories
                    for cat in split_field(doc.category):
                        key = (doc.doc_id, cat)
                        if key not in existing_categories:
                            new_records.append(Category(doc_id=doc.doc_id, category=cat))
                            existing_categories.add(key)

                    # Process subcategories
                    for sub in split_field(doc.subcategory):
                        key = (doc.doc_id, sub)
                        if key not in existing_subcategories:
                            new_records.append(Subcategory(doc_id=doc.doc_id, subcategory=sub))
                            existing_subcategories.add(key)

                    # Process initiating countries
                    for ic in split_field(doc.initiating_country):
                        key = (doc.doc_id, ic)
                        if key not in existing_init_countries:
                            new_records.append(InitiatingCountry(doc_id=doc.doc_id, initiating_country=ic))
                            existing_init_countries.add(key)

                    # Process recipient countries
                    for rc in split_field(doc.recipient_country):
                        key = (doc.doc_id, rc)
                        if key not in existing_rec_countries:
                            new_records.append(RecipientCountry(doc_id=doc.doc_id, recipient_country=rc))
                            existing_rec_countries.add(key)

                    # Process projects
                    for proj in split_field(doc.projects if hasattr(doc, 'projects') else None):
                        key = (doc.doc_id, proj)
                        if key not in existing_projects:
                            new_records.append(Project(doc_id=doc.doc_id, project=proj))
                            existing_projects.add(key)

                    # Process event names
                    for evt in split_field(doc.event_name):
                        key = (doc.doc_id, evt)
                        if key not in existing_events:
                            new_records.append(RawEvent(doc_id=doc.doc_id, event_name=evt))
                            existing_events.add(key)

                    processed_count += 1

                except Exception as e:
                    print(f"❌ Error processing document {doc.doc_id}: {e}")
                    continue

            # Commit batch
            if new_records:
                session.add_all(new_records)
                session.commit()
                print(f"✅ Processed batch: {processed_count}/{total_docs} documents, added {len(new_records)} new relationships")
                new_records = []

        print(f"🎯 Normalization complete: processed {processed_count} documents")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Flatten multi-value document fields into normalized relationship tables")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for processing documents (default: 1000)")
    parser.add_argument("--skip-events", action="store_true", help="Skip event flattening process")

    args = parser.parse_args()

    print("🚀 Starting document field flattening process...")

    # Run main normalization
    normalize_data(batch_size=args.batch_size)

    # Run event flattening unless skipped
    if not args.skip_events:
        print("\n🚀 Starting event flattening process...")
        flatten_event()
    else:
        print("⏩ Skipping event flattening as requested")

    print("✅ All flattening processes completed successfully!")