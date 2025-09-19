from backend.scripts.models import Document,Event, RawEvent
from backend.extensions import db
#Split document fields into one-to-many relationships
def flatten_event():
    documents = db.session.query(Document.doc_id,Document.event_name).all()

    def split_field(field):
        if field:
            return [f.strip() for f in field.split(";")]
        return []

    existing_events = {(e.doc_id, e.event_name) for e in RawEvent.query.all()}
    counter = 0
    for doc in documents:
        try:
            for evt in split_field(doc.event_name):
                key = (doc.doc_id, evt)
                if key not in existing_events:
                    db.session.add(RawEvent(doc_id=doc.doc_id, event_name=evt))
                    existing_events.add(key)

            # print(f"flattened event for document ID: {doc.doc_id}")
            counter += 1
            if counter % 50000 == 0:
                db.session.commit()
                print(f"Committed {counter} records to the database.")
        except Exception as e:
            print(f"Error processing {doc.doc_id}: {e}")

    db.session.commit()
    print(f"Final commit completed for {counter} documents.")

if __name__ == "__main__":
    from backend.app import app
    with app.app_context():
        flatten_event()