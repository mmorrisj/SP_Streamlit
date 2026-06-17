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
        # Scope to the chunk_embeddings collection: doc_ids also appear in other
        # collections (summary/event stores) which weren't necessarily re-embedded;
        # an unscoped join would read a stale cross-collection vector.
        sql = f"""
            SELECT d.doc_id, d.title, d.distilled_text,
                   1 - (e.embedding <=> '{qstr}'::vector) AS stored_sim,
                   e.embedding::text AS stored_vec
            FROM documents d
            JOIN langchain_pg_collection c ON c.name = 'chunk_embeddings'
            JOIN langchain_pg_embedding e
              ON e.collection_id = c.uuid
             AND e.cmetadata->>'doc_id' = d.doc_id
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
    fresh_doc = emb.embed_documents(texts)      # search_document prefix
    fresh_qry = [emb.embed_query(t) for t in texts]  # search_query prefix

    def _parse(v):
        return [float(x) for x in v.strip("[]").split(",")]

    print(f"probe: {probe!r}")
    print(f"{'stored':>8}  {'fresh':>8}  | {'cos(stored,':>12} {'cos(stored,':>12}")
    print(f"{'sim->q':>8}  {'sim->q':>8}  | {'embed_doc)':>12} {'embed_qry)':>12}  title")
    print("-" * 88)
    stored_avg = fresh_avg = sdoc_avg = sqry_avg = 0.0
    for r, fd, fq in zip(rows, fresh_doc, fresh_qry):
        ss = float(r.stored_sim)
        fs = _cos(qvec, fd)
        sv = _parse(r.stored_vec)
        c_doc = _cos(sv, fd)   # ~1.0 if stored used search_document prefix
        c_qry = _cos(sv, fq)   # ~1.0 if stored used search_query prefix
        stored_avg += ss; fresh_avg += fs; sdoc_avg += c_doc; sqry_avg += c_qry
        print(f"{ss:8.3f}  {fs:8.3f}  | {c_doc:12.3f} {c_qry:12.3f}  {(r.title or '')[:40]}")
    n = len(rows)
    print("-" * 88)
    print(f"{stored_avg/n:8.3f}  {fresh_avg/n:8.3f}  | {sdoc_avg/n:12.3f} {sqry_avg/n:12.3f}  AVG")
    print()
    # Verdict from the direct stored-vs-prefix cosines (independent of the query).
    if sdoc_avg / n > 0.98:
        print("=> Stored docs use the correct search_document prefix — OPTIMAL. No re-embed needed.")
    elif sqry_avg / n > 0.98:
        print("=> Stored docs were indexed with the search_QUERY prefix (wrong side). "
              "Re-embed with embed_documents for best recall.")
    elif max(sdoc_avg, sqry_avg) / n < 0.9:
        print("=> Stored docs match neither current prefix — different model/convention. Re-embed.")
    else:
        print("=> Stored docs partially match; consider re-embedding for optimal recall.")


def main() -> None:
    p = argparse.ArgumentParser(description="Check stored vs current-model document embeddings")
    p.add_argument("--probe", default="China infrastructure projects Middle East North Africa")
    p.add_argument("--keyword", default="infrastructure", help="distilled_text keyword to sample docs")
    p.add_argument("--sample", type=int, default=8)
    args = p.parse_args()
    run(args.probe, args.keyword, args.sample)


if __name__ == "__main__":
    main()
