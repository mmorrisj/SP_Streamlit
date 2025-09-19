from backend.scripts.models import Document, Category, Subcategory, InitiatingCountry, RecipientCountry, Project, Event
from backend.scripts.flatten_events import flatten_event
from backend.extensions import db

# Split document fields into one-to-many relationships
def normalize_data():
    documents = Document.query.all()

    def split_field(field):
        if field:
            return [f.strip() for f in field.split(";")]
        return []

    # Preload existing relationships to avoid redundant queries
    existing_categories = {(c.doc_id, c.category) for c in Category.query.all()}
    existing_subcategories = {(s.doc_id, s.subcategory) for s in Subcategory.query.all()}
    existing_init_countries = {(i.doc_id, i.initiating_country) for i in InitiatingCountry.query.all()}
    existing_rec_countries = {(r.doc_id, r.recipient_country) for r in RecipientCountry.query.all()}
    # existing_projects = {(p.doc_id, p.project) for p in Project.query.all()}
    # existing_events = {(e.doc_id, e.event_name) for e in RawEvent.query.all()}

    counter = 0
    print('flattening data...')
    for doc in documents:
        try:
            for cat in split_field(doc.category):
                key = (doc.doc_id, cat)
                if key not in existing_categories:
                    db.session.add(Category(doc_id=doc.doc_id, category=cat))
                    existing_categories.add(key)

            for sub in split_field(doc.subcategory):
                key = (doc.doc_id, sub)
                if key not in existing_subcategories:
                    db.session.add(Subcategory(doc_id=doc.doc_id, subcategory=sub))
                    existing_subcategories.add(key)

            for ic in split_field(doc.initiating_country):
                key = (doc.doc_id, ic)
                if key not in existing_init_countries:
                    db.session.add(InitiatingCountry(doc_id=doc.doc_id, initiating_country=ic))
                    existing_init_countries.add(key)

            for rc in split_field(doc.recipient_country):
                key = (doc.doc_id, rc)
                if key not in existing_rec_countries:
                    db.session.add(RecipientCountry(doc_id=doc.doc_id, recipient_country=rc))
                    existing_rec_countries.add(key)

            # for proj in split_field(doc.projects):
            #     key = (doc.doc_id, proj)
            #     if key not in existing_projects:
            #         db.session.add(Project(doc_id=doc.doc_id, project=proj))
            #         existing_projects.add(key)

            # for evt in split_field(doc.event_name):
            #     key = (doc.doc_id, evt)
            #     if key not in existing_events:
            #         db.session.add(RawEvent(doc_id=doc.doc_id, event_name=evt))
            #         existing_events.add(key)

            # print(f"Normalized data for document ID: {doc.doc_id}")
            counter += 1
            if counter % 20000 == 0:
                db.session.commit()
                print(f"Committed {counter} records to the database.")
        except Exception as e:
            print(f"Error processing {doc.doc_id}: {e}")

    db.session.commit()
    print(f"Final commit completed for {counter} documents.")

if __name__ == "__main__":
    from backend.app import app
    with app.app_context():
        normalize_data()
        flatten_event()