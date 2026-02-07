import uuid
import os
from transformers import AutoTokenizer
from sentence_transformers import SentenceTransformer
from backend.database import get_session
from backend.models import Document
from backend.scripts.models import ChunkEmbedding
from backend.tasks.embedding_tasks import process_document_task
# Load tokenizer and model on GPU
tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cuda")  # ✅ use GPU
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("POSTGRES_USER", "user")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
DB_NAME = os.getenv("POSTGRES_DB", "mydb")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# Chunking logic
def chunk_text(text, max_tokens=250, overlap=50):
    tokens = tokenizer.encode(text, add_special_tokens=False)
    chunks = []
    i = 0
    while i < len(tokens):
        chunk_tokens = tokens[i:i + max_tokens]
        chunk_text = tokenizer.decode(chunk_tokens)
        chunks.append(chunk_text)
        i += max_tokens - overlap
    return chunks

def enqueue_documents():
    with get_session() as session:
        documents = session.query(Document).all()
        for doc in documents:
            full_text = doc.distilled_text
            metadata = {
                "category": doc.category,
                "subcategory": doc.subcategory,
                "initiating_country": doc.initiating_country,
                "recipient_country": doc.recipient_country,
                "event_name": doc.event_name,
            }
            process_document_task.delay(doc.doc_id, full_text, doc.date, metadata)

if __name__ == "__main__":
    enqueue_documents()
    print("🎉 All documents processed and embedded.")
    
# from sentence_transformers import SentenceTransformer
# import uuid
# from datetime import date
# from transformers import AutoTokenizer
# from sentence_transformers import SentenceTransformer
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker
# from backend.scripts.models import Document, SummaryEmbedding, ChunkEmbedding # from step 2
# from backend.extensions import db
# # Load tokenizer and embedding model
# tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
# model = SentenceTransformer("all-MiniLM-L6-v2",device='cuda')
# # Token chunking function
# def chunk_text(text, max_tokens=250, overlap=50):
#     tokens = tokenizer.encode(text, add_special_tokens=False)
#     chunks = []
#     i = 0
#     while i < len(tokens):
#         chunk_tokens = tokens[i:i + max_tokens]
#         chunk_text = tokenizer.decode(chunk_tokens)
#         chunks.append(chunk_text)
#         i += max_tokens - overlap
#     return chunks

# def process_document(doc_id, full_text, doc_date, metadata):
#     chunks = chunk_text(full_text)
#     embeddings = model.encode(chunks)
#     count = 0
#     for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
#         # Check if the chunk already exists
#         existing_record = db.session.query(ChunkEmbedding).filter_by(
#             article_id=doc_id, chunk_index=i).first()
#         if existing_record:
#             print(f"Chunk {i+1} for document ID {doc_id} already exists. Skipping.")
#             continue
#         record = ChunkEmbedding(
#             id=str(uuid.uuid4()),
#             article_id=doc_id,
#             chunk_index=i,
#             chunk=chunk,
#             embedding=embedding.tolist(),
#             date=doc_date,
#             metadata=metadata
#         )
#         db.session.add(record)
#         count += 1
#         if count % 25 == 0:
#             db.session.commit()
#         print(f"Processed chunk {i+1}/{len(chunks)} for document ID: {doc_id}")
#     db.session.commit()
    
# def process_documents():
#     with app.app_context():
#         documents = db.session.query(Document).all()
#         for doc in documents:
#             full_text = doc.distilled_text or doc.body
#             doc_date = doc.date
#             metadata = {
#                 "category": doc.category,
#                 "subcategory": doc.subcategory,
#                 "initiating_country": doc.initiating_country,
#                 "recipient_country": doc.recipient_country,
#                 "event_name": doc.event_name or doc.projects,
#                 "location": doc.location or doc.lat_long,
#             }
#             process_document(doc.doc_id, full_text, doc_date, metadata)

# if __name__ == "__main__":
#     from backend.app import app
#     with app.app_context():
#         process_documents()
#         print("Document processing completed.")