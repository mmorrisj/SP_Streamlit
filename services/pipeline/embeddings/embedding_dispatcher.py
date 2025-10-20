
def is_already_embedded(doc_id: str) -> bool:
    """Check if a document already has embeddings in LangChain's table."""
    from shared.database.database import get_engine
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



def split_multi(val):
                if not val:
                    return []
                return [x.strip() for x in str(val).split(";") if x.strip()]

def run_dispatcher(batch_size: int = 100, force: bool = False):
    import logging
    from shared.database.database import get_session
    from shared.models.models import Document
    from backend.tasks.embedding_tasks import process_document_task

    logging.info("🚀 Starting Celery embedding dispatcher...")

    with get_session() as session:
        documents = session.query(Document).yield_per(batch_size)

        for doc in documents:
            if not doc.distilled_text:
                continue

            if not force and is_already_embedded(doc.doc_id):
                logging.info(f"⏩ Skipping {doc.doc_id} (already embedded)")
                continue

            full_text = doc.distilled_text
            doc_date = str(doc.date) if doc.date else None
            

            meta = {
                "doc_id": str(doc.doc_id),
                "initiating_country": split_multi(doc.initiating_country),
                "recipient_country": split_multi(doc.recipient_country),
                "category": split_multi(doc.category),
                "subcategory": split_multi(doc.subcategory),
                "event_name": split_multi(doc.event_name or doc.projects),
                "location": split_multi(doc.location or doc.lat_long),
            }

            if force:
                logging.info(f"♻️ Re-embedding {doc.doc_id} (force=True)")
            else:
                logging.info(f"📤 Dispatching embedding task for doc_id={doc.doc_id}")

            process_document_task.delay(doc.doc_id, full_text, doc_date, meta)

    logging.info("✅ Finished dispatching embedding tasks.")
