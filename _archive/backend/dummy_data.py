# create 100 samples of dummy date data for testing 
# inputs are start_date and end_date in 'YYYY-MM-DD' format
# module uses random dates to generate dates between the two inputs
# uses uuid as doc_id
# hits opena api to generate synthetic inputs for following json:
'''class Document(Base):
    """
    Core document model - converted from Flask-SQLAlchemy to pure SQLAlchemy.
    
    Changes made:
    - Replaced db.Model with Base
    - Added type hints with Mapped[]
    - Used mapped_column() instead of db.Column()
    - Added proper __repr__ method
    - Added relationship to Salience
    """
    __tablename__ = 'documents'
    
    # Primary key
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    
    # Core document metadata  
    title: Mapped[Optional[str]] = mapped_column(Text)
    source_name: Mapped[Optional[str]] = mapped_column(Text)
    source_geofocus: Mapped[Optional[str]] = mapped_column(Text)
    source_consumption: Mapped[Optional[str]] = mapped_column(Text)
    source_description: Mapped[Optional[str]] = mapped_column(Text)
    source_medium: Mapped[Optional[str]] = mapped_column(Text)
    source_location: Mapped[Optional[str]] = mapped_column(Text)
    source_editorial: Mapped[Optional[str]] = mapped_column(Text)
    
    # Temporal data
    date: Mapped[Optional[date]] = mapped_column(Date)
    
    # Processing metadata
    collection_name: Mapped[Optional[str]] = mapped_column(Text)
    gai_engine: Mapped[Optional[str]] = mapped_column(Text)
    gai_promptid: Mapped[Optional[str]] = mapped_column(Text)
    gai_promptversion: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Analysis results 
    salience: Mapped[Optional[str]] = mapped_column(Text)
    salience_justification: Mapped[Optional[str]] = mapped_column(Text)
    salience_bool: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    category_justification: Mapped[Optional[str]] = mapped_column(Text)
    subcategory: Mapped[Optional[str]] = mapped_column(Text)
    
    # Geographic and relational data
    initiating_country: Mapped[Optional[str]] = mapped_column(Text)
    recipient_country: Mapped[Optional[str]] = mapped_column(Text)
    projects: Mapped[Optional[str]] = mapped_column(Text)
    lat_long: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)
    
    # Financial data
    monetary_commitment: Mapped[Optional[str]] = mapped_column(Text)
    
    # Content
    distilled_text: Mapped[Optional[str]] = mapped_column(Text)
    event_name: Mapped[Optional[str]] = mapped_column(Text)
    '''
import random
from datetime import datetime, timedelta
import uuid
from openai import OpenAI
import os
import json
from typing import List, Dict, Any  
from dotenv import load_dotenv
from backend.scripts.utils import Config
from backend.database import get_session, init_database
from backend.models import Document
from backend.scripts.embedding_vectorstore import chunk_store
from datetime import datetime, date
import argparse
import logging

cfg = Config().from_yaml()

categories= cfg.categories
subcategories = cfg.subcategories
countries = cfg.influencers
recipients = cfg.recipients
gai_engine = "gpt-4o-mini"
gai_promptid = "dummy_date_v1"
gai_promptversion = 1

# Get random date between two dates
def random_date(start, end):
    """Generate a random datetime between `start` and `end`"""
    delta = end - start
    int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
    random_second = random.randrange(int_delta)
    return start + timedelta(seconds=random_second)

# select random category and subcategory
def random_category():
    category = random.choice(categories)
    subcategory = random.choice(subcategories)
    return category, subcategory

# select random country and recipient
def random_country():
    country = random.choice(countries)
    recipient = random.choice(recipients)
    return country, recipient

# load environment variables
load_dotenv()

# openai.api_key = os.getenv('OPENAI_PROJ_API')
# openai.organization = os.getenv('OPENAI_ORG')
# openai.api_base = "https://api.openai.com/v1"
# openai.api_type = "openai"
# openai.api_version = "2024-06-01"   

# instantiate openai client
client = OpenAI(api_key=os.getenv("OPENAI_PROJ_API"))

#build prompt for openai
def build_prompt(country: str, recipient: str, category: str, subcategory: str, date: str) -> str:
    prompt = (
        "Generate a JSON object with the following fields:\n"
        "- title: A random news article title about {country} and {recipient}.\n"
        "- source_name: A random news source name.\n"
        "- source_geofocus: A random geographic focus (e.g., 'Global', 'Africa', 'Asia').\n"
        "- source_consumption: A random consumption type (e.g., 'Online', 'Print', 'TV').\n"
        "- source_description: A brief description of the news source.\n"
        "- source_medium: The medium of the news source (e.g., 'Newspaper', 'Website', 'Television').\n"
        "- source_location: A random location for the news source (e.g., city or country).\n"
        "- source_editorial: A brief editorial stance or focus of the news source.\n"
        "- collection_name: A random collection name (e.g., 'World News', 'Tech Updates').\n"
        "- distilled_text: A short summary related to the title about {country} and {recipient}.\n"
        "- event_name: A random event name related to the title and distilled text.\n"
        "Ensure all fields are filled with plausible but fictional data. "
        "Return the output as a single JSON object."
    )
    return prompt

# generate dummy data
def generate_dummy_data(start_date: str, end_date: str, num_samples: int = 100) -> List[Dict[str, Any]]:
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    # load dummy data if exists
    if os.path.exists('dummy_data.json'):
        with open('dummy_data.json', 'r') as f:
            dummy_data = json.load(f)
    else:
        dummy_data = []
    
    for _ in range(num_samples):
        doc_id = str(uuid.uuid4())
        date = random_date(start, end).date()
        category, subcategory = random_category()
        country, recipient = random_country()
        
        prompt = build_prompt(country, recipient, category, subcategory, str(date))
        
        try:
            response = client.chat.completions.create(
                model=gai_engine,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}  # ✅ ensures valid JSON
            )

            content = response.choices[0].message.content
            data = json.loads(content)
            data.update({
                "doc_id": doc_id,
                "date": str(date),
                "category": category,
                "subcategory": subcategory,
                "initiating_country": country,
                "recipient_country": recipient,
                "gai_engine": gai_engine,
                "gai_promptid": gai_promptid,
                "gai_promptversion": gai_promptversion
            })

            dummy_data.append(data)

        except Exception as e:
            print(f"Error generating data for doc_id {doc_id}: {e}")

    with open("dummy_data.json", "w") as f:
        json.dump(dummy_data, f, indent=4)

    return dummy_data

def split_multi(val):
    """Split multi-value fields by semicolon, following the dispatcher pattern."""
    if not val:
        return []
    return [x.strip() for x in str(val).split(";") if x.strip()]

def is_already_embedded(doc_id: str) -> bool:
    """Check if a document already has embeddings in LangChain's table."""
    from backend.database import get_engine
    from sqlalchemy.sql import text

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

def load_data_to_database(json_file_path: str = None, embed_documents: bool = True) -> bool:
    """
    Load data from dummy_data.json into the PostgreSQL database.

    Args:
        json_file_path (str, optional): Path to the JSON file. Defaults to 'dummy_data.json'.

    Returns:
        bool: True if successful, False otherwise
    """
    if json_file_path is None:
        json_file_path = 'dummy_data.json'

    # Check if file exists
    if not os.path.exists(json_file_path):
        print(f"Error: JSON file '{json_file_path}' not found.")
        return False

    try:
        # Read JSON data
        with open(json_file_path, 'r') as f:
            data = json.load(f)

        print(f"Loading {len(data)} documents from {json_file_path}...")

        # Initialize database tables if they don't exist
        init_database()

        loaded_count = 0
        skipped_count = 0

        with get_session() as session:
            for item in data:
                try:
                    # Check if document already exists
                    existing_doc = session.query(Document).filter_by(doc_id=item.get('doc_id')).first()
                    if existing_doc:
                        print(f"Document {item.get('doc_id')} already exists, skipping...")
                        skipped_count += 1
                        continue

                    # Convert date string to date object
                    date_obj = None
                    if item.get('date'):
                        try:
                            date_obj = datetime.strptime(item['date'], '%Y-%m-%d').date()
                        except ValueError:
                            print(f"Warning: Invalid date format for doc_id {item.get('doc_id')}: {item.get('date')}")

                    # Create Document instance
                    document = Document(
                        doc_id=item.get('doc_id'),
                        title=item.get('title'),
                        source_name=item.get('source_name'),
                        source_geofocus=item.get('source_geofocus'),
                        source_consumption=item.get('source_consumption'),
                        source_description=item.get('source_description'),
                        source_medium=item.get('source_medium'),
                        source_location=item.get('source_location'),
                        source_editorial=item.get('source_editorial'),
                        date=date_obj,
                        collection_name=item.get('collection_name'),
                        gai_engine=item.get('gai_engine'),
                        gai_promptid=item.get('gai_promptid'),
                        gai_promptversion=item.get('gai_promptversion'),
                        category=item.get('category'),
                        subcategory=item.get('subcategory'),
                        initiating_country=item.get('initiating_country'),
                        recipient_country=item.get('recipient_country'),
                        distilled_text=item.get('distilled_text'),
                        event_name=item.get('event_name')
                    )

                    session.add(document)
                    loaded_count += 1

                except Exception as e:
                    print(f"Error processing document {item.get('doc_id', 'unknown')}: {e}")
                    continue

            # Commit all documents at once
            session.commit()

        print(f"Successfully loaded {loaded_count} documents to database.")
        print(f"Skipped {skipped_count} existing documents.")

        # Process embeddings for newly loaded documents if requested
        if embed_documents and loaded_count > 0:
            print("Processing embeddings for loaded documents...")
            embedded_count = 0

            with get_session() as session:
                # Get the newly loaded documents
                new_documents = session.query(Document).filter(
                    Document.doc_id.in_([item.get('doc_id') for item in data])
                ).all()

                # Prepare batch data for embedding
                batch_texts = []
                batch_metadatas = []
                batch_ids = []

                for document in new_documents:
                    # Check if already embedded (skip if it is)
                    if is_already_embedded(document.doc_id):
                        print(f"⏩ Skipping embedding for {document.doc_id} (already embedded)")
                        continue

                    # Extract text for embedding
                    text = document_text_fn(document)
                    if not text:
                        print(f"⚠️ Skipping {document.doc_id} (no text content)")
                        continue

                    # Prepare embedding data
                    batch_texts.append(text)
                    batch_metadatas.append(document_metadata_fn(document))
                    batch_ids.append(document.doc_id)
                    embedded_count += 1

                # Add embeddings to vector store in batch
                if batch_texts:
                    try:
                        chunk_store.add_texts(
                            texts=batch_texts,
                            metadatas=batch_metadatas,
                            ids=batch_ids
                        )
                        print(f"✅ Successfully embedded {embedded_count} documents")
                    except Exception as e:
                        print(f"❌ Error creating embeddings: {e}")
                        logging.error(f"Embedding error: {e}")
                else:
                    print("📭 No new documents to embed")

        return True

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON format in {json_file_path}: {e}")
        return False
    except Exception as e:
        print(f"Error loading data to database: {e}")
        return False

# add cli to run script
def main():
    parser = argparse.ArgumentParser(description="Generate dummy date data for testing or load data to database.")

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Generate command
    generate_parser = subparsers.add_parser('generate', help='Generate new dummy data')
    generate_parser.add_argument("--start", type=str, required=True, help="Start date in 'YYYY-MM-DD' format")
    generate_parser.add_argument("--end", type=str, required=True, help="End date in 'YYYY-MM-DD' format")
    generate_parser.add_argument("--num_samples", type=int, default=100, help="Number of samples to generate (default: 100)")

    # Load command
    load_parser = subparsers.add_parser('load', help='Load data from JSON file to database')
    load_parser.add_argument("--file", type=str, default="dummy_data.json", help="Path to JSON file (default: dummy_data.json)")
    load_parser.add_argument("--no-embed", action="store_true", help="Skip embedding documents in vector store")

    args = parser.parse_args()

    if args.command == 'generate':
        if not args.start or not args.end:
            print("Error: Both --start and --end dates are required for generate command")
            return

        generate_dummy_data(args.start, args.end, args.num_samples)
        print(f"Generated {args.num_samples} samples of dummy data between {args.start} and {args.end}.")

    elif args.command == 'load':
        embed_docs = not args.no_embed  # Embed by default unless --no-embed is specified
        success = load_data_to_database(args.file, embed_docs)
        if success:
            print("Data loading completed successfully.")
        else:
            print("Data loading failed.")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()