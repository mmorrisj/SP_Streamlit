import argparse
import logging
from backend.app import create_app
from backend.extensions import db
from backend.scripts.models import DailyEventSummary
from backend.scripts.embedding_vectorstore import summary_store


def embed_summaries(batch_size: int = 100):
    """
    Embed all DailyEventSummary rows that do not yet exist in the summary_store.
    Each embedding is created from event_name + summary_text.
    Metadata includes event_name, recipients, categories, and subcategories.
    """
    logging.info("🚀 Starting DailyEventSummary embedding dispatcher...")

    # Fetch already embedded IDs
    try:
        existing = {doc.metadata["summary_id"] for doc in summary_store.get()}
    except Exception:
        existing = set()

    logging.info(f"📦 Found {len(existing)} already embedded summaries")

    # Query all summaries in batches
    q = db.session.query(DailyEventSummary).yield_per(batch_size)

    buffer_texts, buffer_ids, buffer_metadatas = [], [], []
    new_count = 0

    for s in q:
        sid = str(s.id)
        if sid in existing:
            continue
        if not s.summary_text and not s.event_name:
            continue

        # Event name + summary text for embedding
        text_for_embedding = f"{s.event_name or ''}. {s.summary_text or ''}".strip()

        buffer_texts.append(text_for_embedding)
        buffer_ids.append(sid)
        buffer_metadatas.append({
            "summary_id": sid,
            "event_id": str(s.event_id),
            "report_date": s.report_date.isoformat() if s.report_date else None,
            "initiating_country": s.initiating_country,
            "event_name": s.event_name,
            "recipients": s.recipient_countries or [],
            "categories": s.categories or [],
            "subcategories": s.subcategories or []
        })

        if len(buffer_texts) >= batch_size:
            summary_store.add_texts(buffer_texts, metadatas=buffer_metadatas, ids=buffer_ids)
            logging.info(f"✅ Embedded {len(buffer_texts)} summaries")
            new_count += len(buffer_texts)
            buffer_texts, buffer_ids, buffer_metadatas = [], [], []

    # Final flush
    if buffer_texts:
        summary_store.add_texts(buffer_texts, metadatas=buffer_metadatas, ids=buffer_ids)
        logging.info(f"✅ Embedded {len(buffer_texts)} summaries (final batch)")
        new_count += len(buffer_texts)

    logging.info(f"🎯 Embedding complete: {new_count} new summaries added")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Embed DailyEventSummaries into pgvector")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for embeddings")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    app = create_app()
    with app.app_context():
        embed_summaries(batch_size=args.batch_size)