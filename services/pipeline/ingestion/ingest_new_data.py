"""
Quick ingestion script for new data files without emoji encoding issues.
Processes multiple JSON files and inserts documents directly into the database.
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import uuid

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import Document
from sqlalchemy import text

def extract_entities_from_gai(gai_data: List[Dict]) -> Dict:
    """Extract entities from GAI results in DSR format."""
    entities = {
        'categories': [],
        'subcategories': [],
        'initiating_countries': [],
        'recipient_countries': [],
        'projects': []
    }

    for gai_result in gai_data:
        if 'result' in gai_result:
            result = gai_result['result']

            # Extract categories
            if 'categories' in result:
                for cat in result['categories']:
                    if isinstance(cat, dict) and 'category' in cat:
                        entities['categories'].append(cat['category'])
                        if 'subcategories' in cat:
                            entities['subcategories'].extend(cat['subcategories'])
                    elif isinstance(cat, str):
                        entities['categories'].append(cat)

            # Extract countries
            if 'initiatingCountries' in result:
                entities['initiating_countries'].extend(result['initiatingCountries'])
            if 'recipientCountries' in result:
                entities['recipient_countries'].extend(result['recipientCountries'])

            # Extract projects
            if 'projects' in result:
                entities['projects'].extend(result['projects'])

    # Deduplicate
    for key in entities:
        entities[key] = list(set(filter(None, entities[key])))

    return entities

def process_file(filepath: str, session) -> tuple:
    """Process a single JSON file and return (inserted, updated, skipped) counts."""
    print(f"\nProcessing: {Path(filepath).name}")

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"  Total records: {len(data):,}")

    inserted = 0
    updated = 0
    skipped = 0

    for idx, record in enumerate(data):
        if (idx + 1) % 1000 == 0:
            print(f"  Progress: {idx+1:,}/{len(data):,}")

        try:
            # Get document ID
            doc_id = record.get('id')
            if not doc_id:
                skipped += 1
                continue

            # Check if document exists
            existing = session.query(Document).filter(Document.doc_id == doc_id).first()

            if existing:
                skipped += 1
                continue

            # Extract entities from GAI results
            gai_data = record.get('auto', {}).get('gai', [])
            entities = extract_entities_from_gai(gai_data)

            # Create document
            doc = Document(
                doc_id=doc_id,
                title=record.get('title', ''),
                source_name=record.get('source', {}).get('name', ''),
                url=record.get('source', {}).get('url', '')
            )

            session.add(doc)
            session.flush()  # Get the doc in session

            # Insert normalized entities
            if entities['categories']:
                for cat in entities['categories']:
                    session.execute(text(
                        "INSERT INTO categories (doc_id, category) VALUES (:doc_id, :cat) ON CONFLICT DO NOTHING"
                    ), {'doc_id': doc_id, 'cat': cat})

            if entities['subcategories']:
                for subcat in entities['subcategories']:
                    session.execute(text(
                        "INSERT INTO subcategories (doc_id, subcategory) VALUES (:doc_id, :subcat) ON CONFLICT DO NOTHING"
                    ), {'doc_id': doc_id, 'subcat': subcat})

            if entities['initiating_countries']:
                for country in entities['initiating_countries']:
                    session.execute(text(
                        "INSERT INTO initiating_countries (doc_id, initiating_country) VALUES (:doc_id, :country) ON CONFLICT DO NOTHING"
                    ), {'doc_id': doc_id, 'country': country})

            if entities['recipient_countries']:
                for country in entities['recipient_countries']:
                    session.execute(text(
                        "INSERT INTO recipient_countries (doc_id, recipient_country) VALUES (:doc_id, :country) ON CONFLICT DO NOTHING"
                    ), {'doc_id': doc_id, 'country': country})

            if entities['projects']:
                for project in entities['projects']:
                    session.execute(text(
                        "INSERT INTO projects (doc_id, project) VALUES (:doc_id, :project) ON CONFLICT DO NOTHING"
                    ), {'doc_id': doc_id, 'project': project})

            inserted += 1

        except Exception as e:
            print(f"  Error processing record {idx}: {e}")
            skipped += 1
            continue

    # Commit the batch
    session.commit()

    return inserted, updated, skipped

def main():
    """Main ingestion process."""
    # Files to process (Oct 15 - Nov 25, 2025)
    files = [
        'data/results-2025-10-15-2025-10-21.json',
        'data/results-2025-10-22-2025-10-28.json',
        'data/results-2025-10-29-2025-11-02.json',
        'data/results-2025-11-03-2025-11-04.json',
        'data/results-2025-11-05-2025-11-11.json',
        'data/results-2025-11-19-2025-11-25.json',
    ]

    print("="*60)
    print("NEW DATA INGESTION (Oct 15 - Nov 25, 2025)")
    print("="*60)

    total_inserted = 0
    total_updated = 0
    total_skipped = 0

    with get_session() as session:
        for filepath in files:
            if not Path(filepath).exists():
                print(f"\nSkipping {filepath} - file not found")
                continue

            inserted, updated, skipped = process_file(filepath, session)
            total_inserted += inserted
            total_updated += updated
            total_skipped += skipped

            print(f"  Inserted: {inserted:,}, Updated: {updated:,}, Skipped: {skipped:,}")

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total Inserted: {total_inserted:,}")
    print(f"Total Updated: {total_updated:,}")
    print(f"Total Skipped: {total_skipped:,}")
    print("="*60)

if __name__ == "__main__":
    main()
