from backend.models import Document, RawEvent
from backend.database import get_session, init_database

def split_field(field):
    """Split multi-value fields by semicolon and clean whitespace."""
    if field:
        return [f.strip() for f in field.split(";") if f.strip()]
    return []

def flatten_event(batch_size=2000):
    """
    Split document event_name fields into normalized RawEvent relationships.

    Args:
        batch_size (int): Number of documents to process in each batch
    """
    print("🚀 Starting event name flattening process...")

    # Initialize database tables if they don't exist
    init_database()

    with get_session() as session:
        # Get total document count for progress tracking
        total_docs = session.query(Document).filter(
            Document.event_name.isnot(None),
            Document.event_name != ""
        ).count()
        print(f"📊 Processing {total_docs} documents with event names in batches of {batch_size}")

        # Preload existing event relationships
        print("📦 Loading existing event relationships...")
        existing_events = {(e.doc_id, e.event_name) for e in session.query(RawEvent).all()}
        print(f"📋 Found {len(existing_events)} existing event relationships")

        # Process documents in batches
        processed_count = 0
        new_records = []

        # Query documents with event names in batches
        for offset in range(0, total_docs, batch_size):
            documents = session.query(Document.doc_id, Document.event_name).filter(
                Document.event_name.isnot(None),
                Document.event_name != ""
            ).offset(offset).limit(batch_size).all()

            for doc in documents:
                try:
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
                print(f"✅ Processed batch: {processed_count}/{total_docs} documents, added {len(new_records)} new event relationships")
                new_records = []

        print(f"🎯 Event flattening complete: processed {processed_count} documents")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Flatten document event_name fields into RawEvent relationship table")
    parser.add_argument("--batch-size", type=int, default=2000, help="Batch size for processing documents (default: 2000)")

    args = parser.parse_args()

    print("🚀 Starting event name flattening process...")
    flatten_event(batch_size=args.batch_size)
    print("✅ Event flattening completed successfully!")