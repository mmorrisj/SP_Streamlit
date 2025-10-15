import json
import os
from backend.scripts.utils import Config
from backend.models import Document
from backend.database import get_session, init_database, get_engine
from backend.scripts.embedding_vectorstore import chunk_store
from datetime import datetime
from sqlalchemy.sql import text
from backend.scripts.s3 import load_dsr_from_s3, reprocess_files, list_s3_json_files
from typing import List, Optional

cfg = Config.from_yaml()

def split_multi(val):
    """Split multi-value fields by semicolon, following the dispatcher pattern."""
    if not val:
        return []
    return [x.strip() for x in str(val).split(";") if x.strip()]

def is_already_embedded(doc_id: str) -> bool:
    """Check if a document already has embeddings in LangChain's table."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 1
                FROM langchain_pg_embedding
                WHERE cmetadata->>'doc_id' = :doc_id
                LIMIT 1
            """),
            {"doc_id": str(doc_id)},
        )
        return result.first() is not None

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

    # Debug: Track if we ever see event-name field
    event_name_found = False
    event_name_raw_value = None

    for response in gai['value']:
        response_type = response.get('type')
        response_value = response.get('value')

        # Debug: Log if we find event-name
        if response_type == 'event-name':
            event_name_found = True
            event_name_raw_value = response_value

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

    # Debug logging for event_name issues
    if not event_value:
        if not event_name_found:
            print(f"⚠️  Doc {doc.doc_id}: 'event-name' field NOT FOUND in JSON")
        else:
            print(f"⚠️  Doc {doc.doc_id}: 'event-name' found but value was: '{event_name_raw_value}' (normalized to None)")

    # Final assignment (always overwrite to ensure consistency)
    setattr(doc, 'event_name', event_value)
    setattr(doc, 'projects', projects_value)

    return doc
   
def process_dsr(relocate=True, batch_size=100):
    """
    Process DSR JSON files and load them into the database efficiently.
    Documents are loaded in batches for better performance.

    Args:
        relocate (bool): Whether to move processed files to processed folder
        batch_size (int): Number of documents to process in each batch
    """
    dsr = load_dsr(directory=cfg.dsr_data, relocate=relocate)

    # Initialize database tables if they don't exist
    init_database()

    loaded_count = 0
    skipped_count = 0
    error_count = 0
    new_doc_ids = []

    print(f"Processing DSR documents in batches of {batch_size}...")

    with get_session() as session:
        document_batch = []

        for dsr_docs in dsr:
            print(f'Loading {len(dsr_docs)} documents from DSR file...')

            for dsr_doc in dsr_docs:
                try:
                    doc = parse_doc(dsr_doc)
                except Exception as e:
                    print(f'Error processing {dsr_doc["id"]}: {e}')
                    error_count += 1
                    continue

                if doc:
                    # Check if document already exists
                    existing_doc = session.query(Document).filter_by(doc_id=doc.doc_id).first()
                    if existing_doc:
                        print(f"Document {doc.doc_id} already exists. Skipping...")
                        skipped_count += 1
                        continue

                    # Add to batch
                    document_batch.append(doc)
                    new_doc_ids.append(doc.doc_id)
                    loaded_count += 1

                    # Process batch when it reaches batch_size
                    if len(document_batch) >= batch_size:
                        session.add_all(document_batch)
                        session.commit()
                        print(f"✅ Committed batch of {len(document_batch)} documents")
                        document_batch = []

                else:
                    print(f"Skipped document: {dsr_doc['id']}")
                    skipped_count += 1

        # Process remaining documents in the final batch
        if document_batch:
            session.add_all(document_batch)
            session.commit()
            print(f"✅ Committed final batch of {len(document_batch)} documents")

    print(f"\nDSR Processing complete:")
    print(f"  - Loaded: {loaded_count} documents")
    print(f"  - Skipped: {skipped_count} documents")
    print(f"  - Errors: {error_count} documents")

    return new_doc_ids

def dispatch_embedding_tasks(doc_ids, batch_size=50):
    """
    Dispatch embedding tasks to Celery workers for parallel processing.

    Args:
        doc_ids (list): List of document IDs to embed
        batch_size (int): Number of documents to process per Celery task
    """
    if not doc_ids:
        print("No documents to embed")
        return

    print(f"Dispatching embedding tasks for {len(doc_ids)} documents...")
    print(f"Using batch size of {batch_size} documents per task")

    try:
        # Import the Celery task
        from backend.tasks.embedding_tasks import process_document_batch

        # Split doc_ids into batches
        doc_batches = [doc_ids[i:i + batch_size] for i in range(0, len(doc_ids), batch_size)]

        task_count = 0
        for batch in doc_batches:
            # Dispatch batch to Celery worker
            process_document_batch.delay(batch)
            task_count += 1
            print(f"📤 Dispatched batch {task_count} with {len(batch)} documents")

        print(f"✅ Successfully dispatched {task_count} embedding tasks to Celery workers")
        print("📋 Tasks will be processed in parallel by available workers")

    except ImportError:
        print("⚠️ Celery tasks not available. Falling back to direct embedding...")
        # Fallback to direct embedding if Celery is not available
        embed_documents_direct(doc_ids, batch_size)

def embed_documents_direct(doc_ids, batch_size=50):
    """
    Fallback function to embed documents directly without Celery.

    Args:
        doc_ids (list): List of document IDs to embed
        batch_size (int): Number of documents to process in each batch
    """
    if not doc_ids:
        print("No documents to embed")
        return

    print(f"Embedding {len(doc_ids)} documents directly...")
    embedded_count = 0

    with get_session() as session:
        # Process documents in batches
        for i in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[i:i + batch_size]

            # Get documents for this batch
            documents = session.query(Document).filter(
                Document.doc_id.in_(batch_ids),
                Document.distilled_text.isnot(None),
                Document.distilled_text != ""
            ).all()

            # Prepare batch data for embedding
            batch_texts = []
            batch_metadatas = []
            batch_embedding_ids = []

            for document in documents:
                # Check if already embedded (skip if it is)
                if is_already_embedded(document.doc_id):
                    continue

                # Extract text for embedding
                text = document_text_fn(document)
                if not text:
                    continue

                # Prepare embedding data
                batch_texts.append(text)
                batch_metadatas.append(document_metadata_fn(document))
                batch_embedding_ids.append(document.doc_id)

            # Add embeddings to vector store in batch
            if batch_texts:
                try:
                    chunk_store.add_texts(
                        texts=batch_texts,
                        metadatas=batch_metadatas,
                        ids=batch_embedding_ids
                    )
                    embedded_count += len(batch_texts)
                    print(f"✅ Embedded batch {(i//batch_size)+1}: {len(batch_texts)} documents")
                except Exception as e:
                    print(f"❌ Error embedding batch {(i//batch_size)+1}: {e}")

    print(f"🎯 Direct embedding complete: {embedded_count} documents embedded")

def process_dsr_s3(s3_prefix: str = "dsr_extracts/", specific_files: Optional[List[str]] = None, batch_size: int = 100):
    """
    Process DSR JSON files from S3 bucket and load them into the database.

    Args:
        s3_prefix (str): S3 prefix/folder to search for JSON files
        specific_files (Optional[List[str]]): Optional list of specific filenames to process
        batch_size (int): Number of documents to process in each batch

    Returns:
        List of new document IDs that were loaded
    """
    # Load DSR data from S3
    dsr_data = load_dsr_from_s3(s3_prefix=s3_prefix, specific_files=specific_files)

    if not dsr_data:
        print("No DSR data loaded from S3")
        return []

    # Initialize database tables if they don't exist
    init_database()

    loaded_count = 0
    skipped_count = 0
    error_count = 0
    new_doc_ids = []

    print(f"Processing DSR documents from S3 in batches of {batch_size}...")

    with get_session() as session:
        document_batch = []

        for dsr_docs in dsr_data:
            print(f'Loading {len(dsr_docs)} documents from S3 DSR file...')

            for dsr_doc in dsr_docs:
                try:
                    doc = parse_doc(dsr_doc)
                except Exception as e:
                    print(f'Error processing {dsr_doc["id"]}: {e}')
                    error_count += 1
                    continue

                if doc:
                    # Check if document already exists
                    existing_doc = session.query(Document).filter_by(doc_id=doc.doc_id).first()
                    if existing_doc:
                        print(f"Document {doc.doc_id} already exists. Skipping...")
                        skipped_count += 1
                        continue

                    # Add to batch
                    document_batch.append(doc)
                    new_doc_ids.append(doc.doc_id)
                    loaded_count += 1

                    # Process batch when it reaches batch_size
                    if len(document_batch) >= batch_size:
                        session.add_all(document_batch)
                        session.commit()
                        print(f"✅ Committed batch of {len(document_batch)} documents")
                        document_batch = []

                else:
                    print(f"Skipped document: {dsr_doc['id']}")
                    skipped_count += 1

        # Process remaining documents in the final batch
        if document_batch:
            session.add_all(document_batch)
            session.commit()
            print(f"✅ Committed final batch of {len(document_batch)} documents")

    print(f"\nS3 DSR Processing complete:")
    print(f"  - Loaded: {loaded_count} documents")
    print(f"  - Skipped: {skipped_count} documents")
    print(f"  - Errors: {error_count} documents")

    return new_doc_ids

def process_dsr_s3_with_embedding(s3_prefix: str = "dsr_extracts/", specific_files: Optional[List[str]] = None,
                                doc_batch_size: int = 100, embed_batch_size: int = 50, use_celery: bool = True):
    """
    Complete S3 DSR processing workflow: load documents from S3 then dispatch embedding tasks.

    Args:
        s3_prefix (str): S3 prefix/folder to search for JSON files
        specific_files (Optional[List[str]]): Optional list of specific filenames to process
        doc_batch_size (int): Batch size for document loading
        embed_batch_size (int): Batch size for embedding tasks
        use_celery (bool): Whether to use Celery for parallel embedding
    """
    # Step 1: Load documents from S3 to database
    print("🚀 Step 1: Loading DSR documents from S3 to database...")
    new_doc_ids = process_dsr_s3(s3_prefix=s3_prefix, specific_files=specific_files, batch_size=doc_batch_size)

    if not new_doc_ids:
        print("No new documents to embed")
        return

    # Step 2: Dispatch embedding tasks
    print(f"\n🚀 Step 2: Processing embeddings for {len(new_doc_ids)} new documents...")

    if use_celery:
        dispatch_embedding_tasks(new_doc_ids, batch_size=embed_batch_size)
    else:
        embed_documents_direct(new_doc_ids, batch_size=embed_batch_size)

def reprocess_s3_files(filenames: List[str], s3_prefix: str = "dsr_extracts/",
                      doc_batch_size: int = 100, embed_batch_size: int = 50, use_celery: bool = True):
    """
    Reprocess specific files from S3 by removing them from processed list and running the full workflow.

    Args:
        filenames (List[str]): List of filenames to reprocess
        s3_prefix (str): S3 prefix/folder where files are located
        doc_batch_size (int): Batch size for document loading
        embed_batch_size (int): Batch size for embedding tasks
        use_celery (bool): Whether to use Celery for parallel embedding
    """
    print(f"🔄 Reprocessing {len(filenames)} files from S3...")

    # Remove files from processed list
    reprocess_files(filenames, s3_prefix)

    # Process the specific files
    process_dsr_s3_with_embedding(
        s3_prefix=s3_prefix,
        specific_files=filenames,
        doc_batch_size=doc_batch_size,
        embed_batch_size=embed_batch_size,
        use_celery=use_celery
    )

def list_s3_dsr_status(s3_prefix: str = "dsr_extracts/"):
    """
    Show status of DSR files in S3 bucket (processed vs unprocessed).
    """
    from backend.scripts.s3 import get_unprocessed_s3_files, load_processed_files_tracker

    print(f"📊 DSR Files Status in S3 bucket (prefix: {s3_prefix})")
    print("=" * 60)

    # Get all files and processed status
    all_files = list_s3_json_files(s3_prefix)
    tracker_data = load_processed_files_tracker(s3_prefix)
    processed_files = set(tracker_data.get('processed_files', []))
    unprocessed_files = get_unprocessed_s3_files(s3_prefix)

    print(f"Total JSON files: {len(all_files)}")
    print(f"Processed files: {len(processed_files)}")
    print(f"Unprocessed files: {len(unprocessed_files)}")

    if unprocessed_files:
        print("\n📋 Unprocessed files:")
        for file_info in unprocessed_files[:10]:  # Show first 10
            print(f"  - {file_info['filename']} ({file_info['size']} bytes)")
        if len(unprocessed_files) > 10:
            print(f"  ... and {len(unprocessed_files) - 10} more")

    if tracker_data.get('last_updated'):
        print(f"\n🕒 Last tracker update: {tracker_data['last_updated']}")

def process_dsr_with_embedding(relocate=True, doc_batch_size=100, embed_batch_size=50, use_celery=True):
    """
    Complete DSR processing workflow: load documents then dispatch embedding tasks.

    Args:
        relocate (bool): Whether to move processed files to processed folder
        doc_batch_size (int): Batch size for document loading
        embed_batch_size (int): Batch size for embedding tasks
        use_celery (bool): Whether to use Celery for parallel embedding
    """
    # Step 1: Load documents to database
    print("🚀 Step 1: Loading DSR documents to database...")
    new_doc_ids = process_dsr(relocate=relocate, batch_size=doc_batch_size)

    if not new_doc_ids:
        print("No new documents to embed")
        return

    # Step 2: Dispatch embedding tasks
    print(f"\n🚀 Step 2: Processing embeddings for {len(new_doc_ids)} new documents...")

    if use_celery:
        dispatch_embedding_tasks(new_doc_ids, batch_size=embed_batch_size)
    else:
        embed_documents_direct(new_doc_ids, batch_size=embed_batch_size)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Process DSR JSON files and optionally embed documents")

    # Data source options
    parser.add_argument("--source", choices=["local", "s3"], default="s3",
                       help="Data source: local directory or S3 bucket (default: s3)")
    parser.add_argument("--s3-prefix", type=str, default="dsr_extracts/",
                       help="S3 prefix/folder for JSON files (default: dsr_extracts/)")

    # Local processing options
    parser.add_argument("--relocate", action="store_true", help="Move processed files to processed folder (local only)")

    # S3 processing options
    parser.add_argument("--s3-files", nargs="+", help="Specific S3 files to process (S3 only)")
    parser.add_argument("--reprocess", nargs="+", help="Reprocess specific files by removing from processed list (S3 only)")
    parser.add_argument("--status", action="store_true", help="Show S3 processing status (S3 only)")

    # General processing options
    parser.add_argument("--doc-batch-size", type=int, default=100, help="Batch size for document loading (default: 100)")
    parser.add_argument("--embed-batch-size", type=int, default=50, help="Batch size for embedding tasks (default: 50)")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding processing")
    parser.add_argument("--no-celery", action="store_true", help="Use direct embedding instead of Celery workers")

    args = parser.parse_args()

    if args.source == "s3":
        if args.status:
            # Show S3 status
            list_s3_dsr_status(args.s3_prefix)
        elif args.reprocess:
            # Reprocess specific files
            print(f"🔄 Reprocessing files from S3: {args.reprocess}")
            reprocess_s3_files(
                filenames=args.reprocess,
                s3_prefix=args.s3_prefix,
                doc_batch_size=args.doc_batch_size,
                embed_batch_size=args.embed_batch_size,
                use_celery=not args.no_celery
            )
        elif args.no_embed:
            # Just load documents from S3 without embedding
            print("🚀 Processing DSR documents from S3 (no embedding)...")
            new_doc_ids = process_dsr_s3(
                s3_prefix=args.s3_prefix,
                specific_files=args.s3_files,
                batch_size=args.doc_batch_size
            )
            print(f"✅ Loaded {len(new_doc_ids)} new documents")
        else:
            # Full S3 workflow with embedding
            print("🚀 Processing DSR documents from S3 with embedding...")
            process_dsr_s3_with_embedding(
                s3_prefix=args.s3_prefix,
                specific_files=args.s3_files,
                doc_batch_size=args.doc_batch_size,
                embed_batch_size=args.embed_batch_size,
                use_celery=not args.no_celery
            )
    else:
        # Local processing (original behavior)
        if args.no_embed:
            # Just load documents without embedding
            print("🚀 Processing DSR documents from local directory (no embedding)...")
            new_doc_ids = process_dsr(relocate=args.relocate, batch_size=args.doc_batch_size)
            print(f"✅ Loaded {len(new_doc_ids)} new documents")
        else:
            # Full workflow with embedding
            print("🚀 Processing DSR documents from local directory with embedding...")
            use_celery = not args.no_celery
            process_dsr_with_embedding(
                relocate=args.relocate,
                doc_batch_size=args.doc_batch_size,
                embed_batch_size=args.embed_batch_size,
                use_celery=use_celery
            )
