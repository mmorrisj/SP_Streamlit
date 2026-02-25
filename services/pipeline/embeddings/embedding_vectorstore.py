import os
import torch
from langchain_postgres import PGVector
from sqlalchemy import text
import numpy as np
from shared.database.database import get_engine
from shared.utils.model_cache import get_hf_embeddings

# Auto-detect device: use CUDA if available, otherwise CPU
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device for embeddings: {device}")

embedding_function = get_hf_embeddings()

def build_connection_string():
    user = os.getenv("POSTGRES_USER", "matthew50")
    password = os.getenv("POSTGRES_PASSWORD", "softpower")
    db = os.getenv("POSTGRES_DB", "softpower-db")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"

CONNECTION_STRING = build_connection_string()

# These are still created at import time, but now they respect env vars
chunk_store = PGVector(
    embeddings=embedding_function,
    connection=CONNECTION_STRING,
    collection_name="chunk_embeddings",
)

summary_store = PGVector(
    embeddings=embedding_function,
    connection=CONNECTION_STRING,
    collection_name="summary_embeddings",
)

# Daily summaries
daily_store = PGVector(
    embeddings=embedding_function,
    connection=CONNECTION_STRING,
    collection_name="daily_event_embeddings",
)

# Weekly events
weekly_store = PGVector(
    embeddings=embedding_function,
    connection=CONNECTION_STRING,
    collection_name="weekly_event_embeddings",
)

# Monthly events
monthly_store = PGVector(
    embeddings=embedding_function,
    connection=CONNECTION_STRING,
    collection_name="monthly_event_embeddings",
)

# Yearly events
yearly_store = PGVector(
    embeddings=embedding_function,
    connection=CONNECTION_STRING,
    collection_name="yearly_event_embeddings",
)

stores = {
    "chunk": chunk_store,
    "daily": daily_store,
    "weekly": weekly_store,
    "monthly": monthly_store,
    "yearly": yearly_store,
}

def get_vectorstore():
    """
    Returns all vector stores for the agent to use.
    Returns: tuple of (chunk_store, summary_store, daily_store, weekly_store, monthly_store, yearly_store)
    """
    return chunk_store, summary_store, daily_store, weekly_store, monthly_store, yearly_store

def get_embeddings_by_ids(store: PGVector, ids):
    """
    Fetch embeddings from pgvector for the given summary_ids in the given store (collection).
    Returns a dict {summary_id: np.array}
    """
    if not ids:
        return {}

    sql = text("""
        SELECT cmetadata->>'summary_id' AS summary_id, embedding
        FROM langchain_pg_embedding
        WHERE cmetadata->>'summary_id' = ANY(:ids)
          AND collection_id = (
              SELECT uuid FROM langchain_pg_collection WHERE name = :collection
          )
    """)
    params = {"ids": [str(i) for i in ids], "collection": store.collection_name}

    emb_map = {}
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
        for row in rows:
            emb = row["embedding"]
            if isinstance(emb, memoryview):
                emb = np.frombuffer(emb, dtype=np.float32)
            elif isinstance(emb, str):
                emb = np.fromstring(emb.strip("[]"), sep=",")
            else:
                emb = np.array(emb, dtype=np.float32)
            emb_map[row["summary_id"]] = emb
    return emb_map
