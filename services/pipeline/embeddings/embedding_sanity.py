"""Diagnose whether stored document embeddings match the current query model.

Symptom this checks for: semantic search returns near-random documents even
though the data exists. Cause: the stored embeddings in langchain_pg_embedding
were produced by a different embedding process than the current nomic query
path (e.g. a different 768-dim model, or nomic without the search_document
prefix). Same dimension → no pgvector error, just degraded retrieval.

For a few documents that clearly match a probe query, it compares:
  * stored_sim  — cosine(query_vec, the embedding already in the DB)
  * fresh_sim   — cosine(query_vec, the doc re-embedded with the current model)

If fresh_sim is consistently and substantially higher than stored_sim, the
stored embeddings are incompatible with the current model and the corpus must
be re-embedded. If they're close, embeddings are fine and the problem is
elsewhere.

Run inside the app image:
    docker exec sp_laptop_app python -m services.pipeline.embeddings.embedding_sanity \
        --probe "China infrastructure projects Middle East North Africa"
"""
from __future__ import annotations

import argparse
import math

from sqlalchemy import text

from shared.database.database import get_session


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def run(probe: str, keyword: str, sample: int) -> None:
    from shared.utils.model_cache import get_hf_embeddings

    emb = get_hf_embeddings()
    qvec = emb.embed_query(probe)
    qstr = "[" + ",".join(str(x) for x in qvec) + "]"

    with get_session() as session:
        # Inline the query vector (our own numeric string) — SQLAlchemy text()
        # can't bind a param directly before the ::vector cast. kw/n stay bound.
        sql = f"""
            SELECT d.doc_id, d.title, d.distilled_text,
                   1 - (e.embedding <=> '{qstr}'::vector) AS stored_sim
            FROM documents d
            JOIN langchain_pg_embedding e ON e.cmetadata->>'doc_id' = d.doc_id
            WHERE d.initiating_country ILIKE '%China%'
              AND d.distilled_text ILIKE :kw
            LIMIT :n
        """
        rows = session.execute(
            text(sql),
            {"kw": f"%{keyword}%", "n": sample},
        ).fetchall()

    if not rows:
        print(f"No China docs matching '{keyword}' found — try a different --keyword.")
        return

    texts = [r.distilled_text or "" for r in rows]
    fresh = emb.embed_documents(texts)

    print(f"probe: {probe!r}")
    print(f"{'stored':>8}  {'fresh':>8}   title")
    print("-" * 70)
    stored_avg = fresh_avg = 0.0
    for r, fv in zip(rows, fresh):
        fs = _cos(qvec, fv)
        ss = float(r.stored_sim)
        stored_avg += ss
        fresh_avg += fs
        print(f"{ss:8.3f}  {fs:8.3f}   {(r.title or '')[:55]}")
    n = len(rows)
    print("-" * 70)
    print(f"{stored_avg / n:8.3f}  {fresh_avg / n:8.3f}   AVG")
    print()
    if fresh_avg - stored_avg > 0.15 * n:
        print("=> Stored embeddings look INCOMPATIBLE with the current model "
              "(fresh >> stored). Re-embed the corpus.")
    else:
        print("=> Stored embeddings look consistent with the current model. "
              "Retrieval issue is elsewhere (HyDE, rerank, chunking).")


def main() -> None:
    p = argparse.ArgumentParser(description="Check stored vs current-model document embeddings")
    p.add_argument("--probe", default="China infrastructure projects Middle East North Africa")
    p.add_argument("--keyword", default="infrastructure", help="distilled_text keyword to sample docs")
    p.add_argument("--sample", type=int, default=8)
    args = p.parse_args()
    run(args.probe, args.keyword, args.sample)


if __name__ == "__main__":
    main()
