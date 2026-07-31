"""Retrieval-layer evals against the live pgvector store.

Gold construction (no human labels available):
  * known-item: a document's own title should retrieve that document.
    Weak-but-honest proxy for embedding + hybrid quality; titles are NOT
    stored verbatim inside the embedded distilled_text, so this is not a
    trivial string match, but vocabulary overlap makes it optimistic.
  * event-mention: a validated canonical event's name should retrieve the
    documents its daily mentions point to. Multi-relevant-set queries;
    measures whether retrieval surfaces the evidence base the event layer
    says exists.

Ablations on the same query sets:
  * hybrid RRF vs pure-vector      (module flag toggle)
  * cross-encoder rerank on/off    (explicit rerank_results call)
  * entity boost on/off            (intelligent_search flag)
  * HyDE on/off                    (LLM-gated; --llm)

All searches run with use_hyde=False and apply_intelligence=False unless the
ablation says otherwise, to isolate one variable at a time.
"""
from __future__ import annotations

from sqlalchemy import text

from evals.core.db import tracked_influencers
from evals.core.metrics import hit_at_k, recall_at_k, reciprocal_rank, summarize
from evals.core.runner import EvalResult, register
from shared.database.database import get_session

SEED = 20260729


def _known_item_queries(per_country: int = 8) -> list[dict]:
    out = []
    with get_session() as s:
        for c in tracked_influencers():
            rows = s.execute(
                text(
                    """
                    SELECT d.doc_id, d.title
                    FROM documents d
                    JOIN initiating_countries ic ON ic.doc_id = d.doc_id
                    JOIN langchain_pg_embedding e ON e.cmetadata->>'doc_id' = d.doc_id
                    JOIN langchain_pg_collection col ON col.uuid = e.collection_id
                    WHERE ic.initiating_country = :c AND col.name = 'chunk_embeddings'
                      AND length(coalesce(d.title,'')) BETWEEN 40 AND 200
                    ORDER BY md5(d.doc_id || :seed) LIMIT :n
                    """
                ),
                {"c": c, "seed": str(SEED), "n": per_country},
            ).fetchall()
            for d, t in rows:
                # 20% of the corpus shares a title with another doc (syndicated
                # wire copy); any same-title doc is an equivalent hit.
                twins = {
                    r[0] for r in s.execute(
                        text("SELECT doc_id FROM documents WHERE title = :t"),
                        {"t": t},
                    ).fetchall()
                }
                out.append({"query": t, "relevant": twins or {d}, "country": c})
    return out


def _event_queries(n: int = 25) -> list[dict]:
    out = []
    with get_session() as s:
        rows = s.execute(
            text(
                """
                SELECT ce.canonical_name, ce.initiating_country,
                       array_agg(DISTINCT d) AS docs
                FROM canonical_events ce
                JOIN daily_event_mentions dem ON dem.canonical_event_id = ce.id,
                LATERAL unnest(dem.doc_ids) AS d
                WHERE ce.master_event_id IS NULL AND ce.llm_validated
                GROUP BY ce.id, ce.canonical_name, ce.initiating_country
                HAVING count(DISTINCT d) BETWEEN 5 AND 60
                ORDER BY md5(ce.id::text || :seed) LIMIT :n
                """
            ),
            {"seed": str(SEED), "n": n},
        ).fetchall()
    for name, country, docs in rows:
        out.append({"query": name, "relevant": set(docs), "country": country})
    return out


def _score(queries, search_fn, ks=(1, 5, 10, 25, 50)) -> dict:
    per = {f"hit@{k}": [] for k in ks}
    per["recall@25"] = []
    per["recall@50"] = []
    per["mrr"] = []
    failures = []
    for q in queries:
        try:
            ranked = search_fn(q)
        except Exception as e:
            failures.append(f"{q['query'][:60]}: {str(e)[:120]}")
            continue
        rel = q["relevant"]
        for k in ks:
            per[f"hit@{k}"].append(hit_at_k(rel, ranked, k))
        per["recall@25"].append(recall_at_k(rel, ranked, 25))
        per["recall@50"].append(recall_at_k(rel, ranked, 50))
        per["mrr"].append(reciprocal_rank(rel, ranked))
    out = {m: summarize(v)["mean"] if v else None for m, v in per.items()}
    out["n"] = len(queries) - len(failures)
    out["errors"] = len(failures)
    return out, failures


@register("retrieval")
def retrieval(llm: bool = False, **kwargs) -> EvalResult:
    res = EvalResult(component="retrieval")
    import services.chat.rag_service as rag

    known = _known_item_queries()
    events = _event_queries()
    res.metrics["known_item_queries"] = len(known)
    res.metrics["event_queries"] = len(events)

    def vec_search(q, k=50, hybrid=None):
        prev = rag.ENABLE_HYBRID_SEARCH
        if hybrid is not None:
            rag.ENABLE_HYBRID_SEARCH = hybrid
        try:
            rows = rag.semantic_search(q["query"], k=k, use_hyde=False)
        finally:
            rag.ENABLE_HYBRID_SEARCH = prev
        return [r["doc_id"] for r in rows]

    # --- baseline: hybrid (production default) --------------------------
    m, errs = _score(known, lambda q: vec_search(q, hybrid=True))
    res.metrics["known_hybrid"] = m
    for e in errs[:3]:
        res.notes.append(f"search error: {e}")
    m, _ = _score(events, lambda q: vec_search(q, hybrid=True))
    res.metrics["event_hybrid"] = m

    # --- ablation: pure vector ------------------------------------------
    m, _ = _score(known, lambda q: vec_search(q, hybrid=False))
    res.metrics["known_vector_only"] = m
    m, _ = _score(events, lambda q: vec_search(q, hybrid=False))
    res.metrics["event_vector_only"] = m

    # --- ablation: rerank on top of hybrid ------------------------------
    try:
        def rerank_search(q):
            rows = rag.semantic_search(q["query"], k=50, use_hyde=False)
            rows = rag.rerank_results(q["query"], rows, top_k=50)
            return [r["doc_id"] for r in rows]

        m, _ = _score(known[:20], rerank_search)
        res.metrics["known_hybrid_rerank"] = m
        m, _ = _score(events[:15], rerank_search)
        res.metrics["event_hybrid_rerank"] = m
    except Exception as e:
        res.notes.append(f"rerank ablation unavailable: {str(e)[:150]}")

    # --- ablation: entity boost via intelligent_search ------------------
    try:
        def isearch(q, boost):
            rows, _meta = rag.intelligent_search(
                q["query"], apply_intelligence=False, enable_entity_boost=boost,
                include_strategic_context=False, include_event_context=False)
            return [r["doc_id"] for r in rows]

        m_on, _ = _score(events[:15], lambda q: isearch(q, True))
        m_off, _ = _score(events[:15], lambda q: isearch(q, False))
        res.metrics["event_intelligent_boost_on"] = m_on
        res.metrics["event_intelligent_boost_off"] = m_off
    except Exception as e:
        res.notes.append(f"entity-boost ablation failed: {str(e)[:200]}")

    # --- ablation: HyDE (costs one LLM call per query) ------------------
    if llm:
        def hyde_search(q):
            rows = rag.semantic_search(q["query"], k=50, use_hyde=True)
            return [r["doc_id"] for r in rows]

        m, _ = _score(known[:15], hyde_search)
        res.metrics["known_hybrid_hyde"] = m
    else:
        res.notes.append("HyDE ablation skipped (pass --llm).")

    res.caveats.append(
        "Known-item gold shares vocabulary between query (title) and target "
        "(distilled_text) — absolute numbers are optimistic; ablation DELTAS "
        "are the reliable signal."
    )
    res.caveats.append(
        "Event-mention gold inherits event-pipeline errors: if a mention links "
        "the wrong docs, retrieval is penalized for the event layer's mistake."
    )
    res.caveats.append(
        "intelligent_search ignores its k argument when reranking is enabled "
        "(candidates=RERANK_CANDIDATE_K, final=RERANK_TOP_K from config)."
    )
    return res
