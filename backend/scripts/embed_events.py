import argparse
import logging
from sqlalchemy.orm import joinedload
from sqlalchemy import text
from backend.database import get_session
from backend.scripts.embedding_vectorstore import stores

# Import summary models
from backend.scripts.models import (
    DailyEventSummary,
    WeeklyEventSummary,
    MonthlyEventSummary,
    # YearlyEventSummary,
)

# -----------------------------
# Text functions
# -----------------------------

def daily_text_fn(ds: DailyEventSummary) -> str:
    return f"{ds.event_name or ''}. {ds.summary_text or ''}".strip()


def weekly_text_fn(ws: WeeklyEventSummary) -> str:
    return f"{ws.event_name or ''}. {ws.summary_text or ''}".strip()


def monthly_text_fn(ms: MonthlyEventSummary) -> str:
    return f"{ms.event_name or ''}. {ms.summary_text or ''}".strip()


# def yearly_text_fn(ys: YearlyEventSummary) -> str:
#     return f"{ys.event_name or ''}. {ys.summary_text or ''}".strip()


# -----------------------------
# Metadata functions
# -----------------------------

def daily_metadata_fn(ds: DailyEventSummary) -> dict:
    return {
        "summary_id": str(ds.id),
        "event_id": str(ds.event_id),
        "initiating_country": ds.initiating_country,
        "event_name": ds.event_name,
        "report_date": ds.report_date.isoformat() if ds.report_date else None,
        "categories": ds.categories or [],
        "subcategories": ds.subcategories or [],
        "recipients": ds.recipient_countries or [],
        "entities": ds.entities or [],
        "material_score": ds.material_score,
        "granularity": "daily",
    }


def weekly_metadata_fn(ws: WeeklyEventSummary) -> dict:
    w = ws.event
    return {
        "summary_id": str(ws.id),
        "event_id": str(ws.event_id),
        "initiating_country": ws.initiating_country or (w.initiating_country if w else None),
        "event_name": ws.event_name or (w.event_name if w else None),
        "week_start": w.week_start.isoformat() if w and w.week_start else None,
        "week_end": w.week_end.isoformat() if w and w.week_end else None,
        "categories": ws.categories or [],
        "subcategories": ws.subcategories or [],
        "recipients": ws.recipient_countries or [],
        "entities": ws.entities or [],
        "material_score": ws.material_score,
        "granularity": "weekly",
    }


def monthly_metadata_fn(ms: MonthlyEventSummary) -> dict:
    m = ms.event
    return {
        "summary_id": str(ms.id),
        "event_id": str(ms.event_id),
        "initiating_country": ms.initiating_country or (m.initiating_country if m else None),
        "event_name": ms.event_name or (m.event_name if m else None),
        "month_start": m.month_start.isoformat() if m and m.month_start else None,
        "month_end": m.month_end.isoformat() if m and m.month_end else None,
        "categories": ms.categories or [],
        "subcategories": ms.subcategories or [],
        "recipients": ms.recipient_countries or [],
        "entities": ms.entities or [],
        "material_score": ms.material_score,
        "granularity": "monthly",
    }


# def yearly_metadata_fn(ys: YearlyEventSummary) -> dict:
#     return {
#         "summary_id": str(ys.id),
#         "event_id": str(ys.event_id),
#         "initiating_country": ys.initiating_country,
#         "event_name": ys.event_name,
#         "year_start": ys.year_start.isoformat() if getattr(ys, "year_start", None) else None,
#         "year_end": ys.year_end.isoformat() if getattr(ys, "year_end", None) else None,
#         "categories": ys.categories or [],
#         "subcategories": ys.subcategories or [],
#         "recipients": ys.recipient_countries or [],
#         "entities": ys.entities or [],
#         "material_score": ys.material_score,
#         "granularity": "yearly",
#     }


# -----------------------------
# Granularity map
# -----------------------------
GRANULARITY_MAP = {
    "daily":   (DailyEventSummary, stores["daily"], daily_text_fn, daily_metadata_fn, None),
    "weekly":  (WeeklyEventSummary, stores["weekly"], weekly_text_fn, weekly_metadata_fn, "event"),
    "monthly": (MonthlyEventSummary, stores["monthly"], monthly_text_fn, monthly_metadata_fn, "event"),
    # "yearly":  (YearlyEventSummary, stores["yearly"], yearly_text_fn, yearly_metadata_fn, None),
}


# -----------------------------
# Utility: clear embeddings
# -----------------------------
def clear_embeddings(store, granularity: str):
    """
    Delete all embeddings for a given granularity from the store.
    """
    logging.info(f"🧹 Clearing all {granularity} embeddings...")
    sql = text("""
        DELETE FROM langchain_pg_embedding
        WHERE collection_id = (
            SELECT uuid FROM langchain_pg_collection WHERE name = :collection
        )
    """)
    with db.engine.begin() as conn:
        conn.execute(sql, {"collection": store.collection_name})
    logging.info(f"✅ Cleared {granularity} embeddings")


# -----------------------------
# Embed dispatcher
# -----------------------------
def embed_entities(level: str, batch_size: int = 100, replace: bool = False):
    if level not in GRANULARITY_MAP:
        raise ValueError(f"Unsupported granularity: {level}. Choose from {list(GRANULARITY_MAP)}")

    Model, store, text_fn, metadata_fn, rel = GRANULARITY_MAP[level]
    logging.info(f"🚀 Starting {level} embedding dispatcher...")

    if replace:
        clear_embeddings(store, level)
        existing = set()
    else:
        try:
            existing = {doc.metadata["summary_id"] for doc in store.get()}
        except Exception:
            existing = set()

    logging.info(f"📦 Found {len(existing)} already embedded {level} summaries")

    with get_session() as session:
        query = session.query(Model)
        if rel:
            query = query.options(joinedload(rel))

        q = query.yield_per(batch_size)

        buffer_texts, buffer_ids, buffer_metadatas = [], [], []
        new_count = 0

        for obj in q:
            oid = str(obj.id)
            if oid in existing:
                continue

            text = text_fn(obj)
            if not text:
                continue

            buffer_texts.append(text)
            buffer_ids.append(oid)
            buffer_metadatas.append(metadata_fn(obj))

            if len(buffer_texts) >= batch_size:
                store.add_texts(buffer_texts, metadatas=buffer_metadatas, ids=buffer_ids)
                logging.info(f"✅ Embedded {len(buffer_texts)} {level} summaries")
                new_count += len(buffer_texts)
                buffer_texts, buffer_ids, buffer_metadatas = [], [], []

        if buffer_texts:
            store.add_texts(buffer_texts, metadatas=buffer_metadatas, ids=buffer_ids)
            logging.info(f"✅ Embedded {len(buffer_texts)} {level} summaries (final batch)")
            new_count += len(buffer_texts)

        logging.info(f"🎯 Embedding complete: {new_count} new {level} summaries added")


# -----------------------------
# CLI
# -----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Embed event summaries into pgvector")
    parser.add_argument("--granularity", required=True, choices=["daily", "weekly", "monthly", "yearly"],
                        help="Which event summaries to embed")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for embeddings")
    parser.add_argument("--replace", action="store_true", help="Clear and re-embed all summaries for this granularity")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    embed_entities(level=args.granularity, batch_size=args.batch_size, replace=args.replace)
