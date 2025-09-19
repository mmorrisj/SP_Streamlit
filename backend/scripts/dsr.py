import json
import os
from backend.scripts.utils import Config
from backend.scripts.models import Document
from datetime import datetime
from backend.extensions import db

cfg = Config.from_yaml()

def move_file(src, dst):
    """
    Move a file from src to dst, creating the destination directory if it doesn't exist.
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.rename(src, dst)
    print(f"Moved {src} to {dst}")

def load_dsr(directory=None,relocate=True):
    if directory is None: 
        directory = cfg.dsr_data
        # Resolve the full directory path relative to this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    directory = os.path.abspath(os.path.join(base_dir, '..', '..', directory))
    print(f"Looking for files in: {directory}")
    dsr = []
    for filename in os.listdir(directory):
        if filename.endswith('.json'):
            if 'errors' in filename:
                continue
            file = os.path.join(directory, filename)
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                dsr.append(data)
                print(f'loaded {file}...')
            if relocate:    
                move_file(file,os.path.join(directory,'processed'))
    print(f'{len(dsr)} documents loaded...')  
    return dsr

def parse_date(date_str):
        # Parse the date string and convert it to the desired format
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime('%Y-%m-%d')

def parse_doc(dsr_doc):

    field_fix = {'project-name': 'projects'}
    if 'auto' not in dsr_doc.keys():
        return None
    gai = dsr_doc['auto']['gai'][1]
    machine_translations = dsr_doc.get('machineTranslations', {})
    title_translation = machine_translations.get('title_title', {}).get('text')
    doc = Document(
        doc_id=dsr_doc['id'],
        title=title_translation or dsr_doc.get('title', {}).get('title', 'Default Title'),
        source_name=dsr_doc['source']['name']['transliterated'],
        source_geofocus=dsr_doc['source'].get('geofocusCountry'),
        source_description=dsr_doc['source'].get('descriptor'),
        source_medium=dsr_doc['source'].get('medium'),
        source_location=dsr_doc['source'].get('country',{}).get('physical','None Specified'),
        source_editorial=dsr_doc['source'].get('country',{}).get('editorial','None Specified'),
        source_consumption=dsr_doc['source'].get('country',{}).get('consumption','None Specified'),
        date=parse_date(dsr_doc['source']['startDate']),
        collection_name=dsr_doc['custom']['atom']['collection_name'],
        gai_engine=gai['modelVersion'],
        gai_promptid=gai['filter']['identifier'],
        gai_promptversion=gai['filter']['version'],

    ) 
    
    event_value = None
    projects_value = None

    for response in gai['value']:
        response_type = response.get('type')
        response_value = response.get('value')

        # Normalize empty or invalid values
        normalized_value = (
            response_value
            if response_value and response_value.strip().lower() not in ['n/a', 'na', 'none', 'null', '']
            else None
        )

        # Assign event_name and projects separately with fallback
        if response_type == 'event-name' and normalized_value:
            event_value = normalized_value

        elif response_type == 'projects':
            projects_value = normalized_value
            if not event_value:
                event_value = normalized_value

        # Set other fields
        if response_type in field_fix:
            setattr(doc, field_fix[response_type], normalized_value)
        else:
            setattr(doc, response_type.replace('-', '_'), normalized_value)  # normalize for model field

    # Final assignment (always overwrite to ensure consistency)
    setattr(doc, 'event_name', event_value)
    setattr(doc, 'projects', projects_value)

    return doc
   
def process_dsr(relocate=True):
    dsr = load_dsr(directory=cfg.dsr_data,relocate=relocate)
    for dsr_docs in dsr:
        print('loading dsr...')
        for dsr_doc in dsr_docs:
            try:
                doc = parse_doc(dsr_doc)
            except:
                print(f'error processing{dsr_doc["id"]}')
                continue
            if doc:
                existing_doc = Document.query.filter_by(doc_id=doc.doc_id).first()
                if existing_doc:
                    print(f"Document {doc.doc_id} already exists. Skipping...")
                    continue
                # Save the document to the database
                db.session.add(doc)
                db.session.commit()
                # print(f"Processed document: {doc.doc_id}")
            else:
                print(f"Skipped document: {dsr_doc['id']}")

if __name__ == "__main__":
    from backend.app import app
    with app.app_context():
        # Call the function to process DSR files
        process_dsr(relocate=False)
        # Uncomment the line below to load DSR data with relocation
        # dsr = load_dsr(directory=cfg.dsr_data, relocate=True)
