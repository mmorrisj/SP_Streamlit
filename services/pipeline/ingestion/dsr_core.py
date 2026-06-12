"""Core DSR parsing and relationship-flattening logic.

Extracted from services/pipeline/ingestion/dsr.py so the FastAPI server can
import these functions without pulling in the embedding stack (torch, the
HuggingFace model, and a live vector-store connection are created at import
time by services.pipeline.embeddings.embedding_vectorstore). dsr.py re-exports
everything here, so existing CLI usage is unchanged.
"""
from datetime import datetime

from sqlalchemy.sql import text

from shared.models.models import Document


def split_multi(val):
    """Split multi-value fields by semicolon, following the dispatcher pattern."""
    if not val:
        return []
    return [x.strip() for x in str(val).split(";") if x.strip()]


def parse_date(date_str):
    # Parse the date string and convert it to the desired format
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    return dt.strftime('%Y-%m-%d')


def document_text_fn(document: Document) -> str:
    """
    Extract text content from a document for embedding.
    Uses distilled_text as primary content, following the dispatcher pattern.
    """
    return document.distilled_text or ""


def document_metadata_fn(document: Document) -> dict:
    """
    Create metadata dictionary for document embedding, following the dispatcher pattern.
    """
    return {
        "doc_id": str(document.doc_id),
        "initiating_country": split_multi(document.initiating_country),
        "recipient_country": split_multi(document.recipient_country),
        "category": split_multi(document.category),
        "subcategory": split_multi(document.subcategory),
        "event_name": split_multi(document.event_name),
        "title": document.title,
        "source_name": document.source_name,
        "source_geofocus": document.source_geofocus,
        "date": document.date.isoformat() if document.date else None,
        "collection_name": document.collection_name,
    }


def parse_doc(dsr_doc):
    """
    Parse DSR document JSON into Document model.

    Handles schema evolution:
    - Old schema: 'project-name' field
    - New schema: 'event-name' field
    - Both: 'projects' field (stored separately)

    Consolidation logic for event_name:
    1. Use 'event-name' if present and non-empty
    2. Fallback to 'project-name' if event-name is empty (old schema)
    3. Fallback to 'projects' if both are empty

    Args:
        dsr_doc (dict): Raw DSR document from JSON

    Returns:
        Document: Populated Document model instance, or None if invalid
    """
    # Validate required structure
    if 'auto' not in dsr_doc or len(dsr_doc['auto'].get('gai', [])) < 2:
        return None

    gai = dsr_doc['auto']['gai'][1]
    machine_translations = dsr_doc.get('machineTranslations', {})
    title_translation = machine_translations.get('title_title', {}).get('text')

    # Initialize document with source metadata
    doc = Document(
        doc_id=dsr_doc['id'],
        title=title_translation or dsr_doc.get('title', {}).get('title', 'Default Title'),
        source_name=dsr_doc['source']['name']['transliterated'],
        source_geofocus=dsr_doc['source'].get('geofocusCountry'),
        source_description=dsr_doc['source'].get('descriptor'),
        source_medium=dsr_doc['source'].get('medium'),
        source_location=dsr_doc['source'].get('country', {}).get('physical', 'None Specified'),
        source_editorial=dsr_doc['source'].get('country', {}).get('editorial', 'None Specified'),
        source_consumption=dsr_doc['source'].get('country', {}).get('consumption', 'None Specified'),
        date=parse_date(dsr_doc['source']['startDate']),
        collection_name=dsr_doc['custom']['atom']['collection_name'],
        gai_engine=gai['modelVersion'],
        gai_promptid=gai['filter']['identifier'],
        gai_promptversion=gai['filter']['version'],
    )

    # Tracking variables for consolidation logic
    event_name_value = None
    project_name_value = None
    projects_value = None

    # Normalization helper
    def normalize_value(val):
        """Normalize empty/invalid values to None"""
        if not val:
            return None
        val_str = str(val).strip()
        if val_str.lower() in ['n/a', 'na', 'none', 'null', 'n/a.', '']:
            return None
        return val_str

    # Field name mapping for special cases (if needed in future)
    field_mapping = {}

    # Parse all fields from gai values
    for response in gai.get('value', []):
        response_type = response.get('type')
        response_value = response.get('value')
        normalized_value = normalize_value(response_value)

        # Track event/project fields separately for consolidation
        if response_type == 'event-name':
            event_name_value = normalized_value
        elif response_type == 'project-name':
            project_name_value = normalized_value
        elif response_type == 'projects':
            projects_value = normalized_value
        else:
            # Map field name to model attribute
            if response_type in field_mapping:
                attr_name = field_mapping[response_type]
            else:
                # Default: replace hyphens with underscores
                attr_name = response_type.replace('-', '_')

            # Set attribute if it exists on the model
            if hasattr(doc, attr_name):
                setattr(doc, attr_name, normalized_value)

    # CONSOLIDATION LOGIC: Determine final event_name
    # Priority: event-name > project-name > projects
    final_event_name = event_name_value or project_name_value or projects_value

    # Set final values on document
    doc.event_name = final_event_name
    doc.project_name = project_name_value  # Store legacy field
    doc.projects = projects_value  # Store projects separately

    # Debug logging for empty event names
    if not final_event_name:
        print(f"[WARNING]  Doc {doc.doc_id}: All event fields empty (event-name, project-name, projects)")
    elif not event_name_value and project_name_value:
        print(f"[INFO]  Doc {doc.doc_id}: Using 'project-name' as fallback: '{project_name_value}'")
    elif not event_name_value and not project_name_value and projects_value:
        print(f"[INFO]  Doc {doc.doc_id}: Using 'projects' as fallback: '{projects_value}'")

    return doc


def flatten_events_to_raw_events(session, documents):
    """
    Flatten event_name, project_name, and projects fields from documents into RawEvent table.

    This consolidates all event/project mentions into a normalized many-to-many relationship.

    Args:
        session: SQLAlchemy session
        documents: List of Document objects to process

    Returns:
        int: Number of RawEvent records created
    """
    raw_events_to_insert = []

    for doc in documents:
        # Collect all unique event/project values from the document
        event_values = set()

        # Add from event_name field
        if doc.event_name:
            # Handle semicolon-separated values
            for val in split_multi(doc.event_name):
                if val:
                    event_values.add(val)

        # Add from project_name field (legacy schema)
        if hasattr(doc, 'project_name') and doc.project_name:
            for val in split_multi(doc.project_name):
                if val and val not in event_values:
                    event_values.add(val)

        # Add from projects field
        if hasattr(doc, 'projects') and doc.projects:
            for val in split_multi(doc.projects):
                if val and val not in event_values:
                    event_values.add(val)

        # Create RawEvent entries for each unique value
        for event_value in event_values:
            raw_events_to_insert.append({
                'doc_id': doc.doc_id,
                'event_name': event_value
            })

    # Bulk insert using ON CONFLICT DO NOTHING for idempotency
    if raw_events_to_insert:
        session.execute(
            text("INSERT INTO raw_events (doc_id, event_name) VALUES (:doc_id, :event_name) ON CONFLICT (doc_id, event_name) DO NOTHING"),
            raw_events_to_insert
        )
        print(f"[INFO] Flattened {len(raw_events_to_insert)} event/project entries into RawEvent table")

    return len(raw_events_to_insert)


def flatten_all_relationships(session, documents):
    """
    Flatten ALL multi-value fields into normalized relationship tables.

    This creates one-to-many relationships for:
    - Categories
    - Subcategories
    - Initiating Countries
    - Recipient Countries
    - Events/Projects (via flatten_events_to_raw_events)

    Args:
        session: SQLAlchemy session
        documents: List of Document objects to process

    Returns:
        dict: Count of records created for each relationship type
    """
    counts = {
        'categories': 0,
        'subcategories': 0,
        'initiating_countries': 0,
        'recipient_countries': 0,
        'raw_events': 0
    }

    # Collect all records to insert
    categories_to_insert = []
    subcategories_to_insert = []
    init_countries_to_insert = []
    rec_countries_to_insert = []

    for doc in documents:
        # Process categories (use set to avoid duplicates)
        if doc.category:
            unique_cats = set(split_multi(doc.category))
            for cat in unique_cats:
                if cat:
                    categories_to_insert.append({
                        'doc_id': doc.doc_id,
                        'category': cat
                    })

        # Process subcategories (use set to avoid duplicates)
        if doc.subcategory:
            unique_subs = set(split_multi(doc.subcategory))
            for sub in unique_subs:
                if sub:
                    subcategories_to_insert.append({
                        'doc_id': doc.doc_id,
                        'subcategory': sub
                    })

        # Process initiating countries (use set to avoid duplicates)
        if doc.initiating_country:
            unique_ics = set(split_multi(doc.initiating_country))
            for ic in unique_ics:
                if ic:
                    init_countries_to_insert.append({
                        'doc_id': doc.doc_id,
                        'initiating_country': ic
                    })

        # Process recipient countries (use set to avoid duplicates)
        if doc.recipient_country:
            unique_rcs = set(split_multi(doc.recipient_country))
            for rc in unique_rcs:
                if rc:
                    rec_countries_to_insert.append({
                        'doc_id': doc.doc_id,
                        'recipient_country': rc
                    })

    # Bulk insert all relationships using ON CONFLICT DO NOTHING for idempotency
    # (executemany via a list of parameter dicts — one round-trip per table,
    # not one per row)
    if categories_to_insert:
        session.execute(
            text("INSERT INTO categories (doc_id, category) VALUES (:doc_id, :category) ON CONFLICT (doc_id, category) DO NOTHING"),
            categories_to_insert
        )
        counts['categories'] = len(categories_to_insert)

    if subcategories_to_insert:
        session.execute(
            text("INSERT INTO subcategories (doc_id, subcategory) VALUES (:doc_id, :subcategory) ON CONFLICT (doc_id, subcategory) DO NOTHING"),
            subcategories_to_insert
        )
        counts['subcategories'] = len(subcategories_to_insert)

    if init_countries_to_insert:
        session.execute(
            text("INSERT INTO initiating_countries (doc_id, initiating_country) VALUES (:doc_id, :initiating_country) ON CONFLICT (doc_id, initiating_country) DO NOTHING"),
            init_countries_to_insert
        )
        counts['initiating_countries'] = len(init_countries_to_insert)

    if rec_countries_to_insert:
        session.execute(
            text("INSERT INTO recipient_countries (doc_id, recipient_country) VALUES (:doc_id, :recipient_country) ON CONFLICT (doc_id, recipient_country) DO NOTHING"),
            rec_countries_to_insert
        )
        counts['recipient_countries'] = len(rec_countries_to_insert)

    # Events/Projects
    event_count = flatten_events_to_raw_events(session, documents)
    counts['raw_events'] = event_count

    # Print summary
    print("[INFO] Flattened relationships:")
    print(f"   - Categories: {counts['categories']}")
    print(f"   - Subcategories: {counts['subcategories']}")
    print(f"   - Initiating Countries: {counts['initiating_countries']}")
    print(f"   - Recipient Countries: {counts['recipient_countries']}")
    print(f"   - Raw Events: {counts['raw_events']}")

    return counts
