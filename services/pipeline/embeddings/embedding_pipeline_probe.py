"""Prove the document-indexing path writes vectors the query path can match.

Embeds a few documents through the REAL pipeline (chunk_store.add_texts, the
same call embed_missing_documents uses), reads them back from
langchain_pg_embedding, and compares to get_hf_embeddings().embed_documents
(what the sanity/query path expects). If cos ~1.0, the pipeline is correct and
a full re-embed will produce query-matchable vectors. If not, the index path
uses a different model/convention than the query path — a real bug to fix
BEFORE re-embedding the whole corpus.

    docker exec sp_laptop_app python -m services.pipeline.embeddings.embedding_pipeline_probe
"""
from __future__ import annotations

import math

from sqlalchemy import text

from shared.database.database import get_session


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def main(n: int = 3) -> None:
    from shared.utils.model_cache import get_hf_embeddings
    from services.pipeline.embeddings.embedding_vectorstore import chunk_store

    emb = get_hf_embeddings()

    with get_session() as s:
        rows = s.execute(text(
            "SELECT doc_id, distilled_text FROM documents "
            "WHERE distilled_text IS NOT NULL AND length(distilled_text) > 50 "
            "ORDER BY doc_id LIMIT :n"
        ), {"n": n}).fetchall()
    ids = [r.doc_id for r in rows]
    texts = [r.distilled_text for r in rows]
    print(f"probing {len(ids)} docs through chunk_store.add_texts ...")

    # write via the exact pipeline path
    chunk_store.add_texts(texts=texts, metadatas=[{"doc_id": i} for i in ids], ids=ids)

    # read back the stored vectors
    with get_session() as s:
        stored = {
            r.doc_id: [float(x) for x in r.ev.strip("[]").split(",")]
            for r in s.execute(text(
                "SELECT d.doc_id AS doc_id, e.embedding::text AS ev "
                "FROM documents d "
                "JOIN langchain_pg_collection c ON c.name = 'chunk_embeddings' "
                "JOIN langchain_pg_embedding e ON e.collection_id = c.uuid "
                " AND e.cmetadata->>'doc_id' = d.doc_id "
                "WHERE d.doc_id = ANY(:ids)"
            ), {"ids": ids}).fetchall()
        }

    fresh = emb.embed_documents(texts)
    print(f"{'cos(pipeline, embed_documents)':>32}   doc_id")
    print("-" * 60)
    vals = []
    for i, fv in zip(ids, fresh):
        sv = stored.get(i)
        if not sv:
            print(f"{'MISSING from chunk_embeddings':>32}   {i}")
            continue
        c = _cos(sv, fv)
        vals.append(c)
        print(f"{c:32.4f}   {i}")
    print("-" * 60)
    if vals and min(vals) > 0.98:
        print("=> PIPELINE OK: indexing writes vectors the query path matches. "
              "Safe to run the full re-embed; it will produce query-matchable vectors.")
    else:
        print("=> PIPELINE MISMATCH: chunk_store writes vectors that DON'T match "
              "get_hf_embeddings(). A full re-embed won't help until this is fixed.")


if __name__ == "__main__":
    main()
