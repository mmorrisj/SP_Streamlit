"""Event-pipeline evals (Stage 1 clustering, LLM deconfliction, Stage 2
consolidation).

There is no human gold standard for event identity, so this eval measures:
  1. Pipeline state/health: deconfliction coverage, LLM-failure fallback rate
     (every LLM deconfliction fails OPEN to same_event=True, which is
     invisible unless counted), validation coverage.
  2. Cluster geometry: intra-cluster cohesion vs. nearest-other-cluster
     separation for daily DBSCAN clusters, using the same raw (unprefixed)
     encoding the pipeline itself uses.
  3. Residual duplication: among master canonical events of the same country
     with overlapping/nearby date ranges, how many pairs still sit above the
     consolidation similarity threshold — an upper bound on missed merges.
  4. Traceability: daily_event_mentions.doc_ids must resolve to real
     documents (the chain the whole audit story depends on).
  5. Prefix ablation: quantifies how much the unprefixed encode() used by the
     event pipeline distorts similarity rankings relative to the prefixed
     encoding used by retrieval.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import text

from evals.core.metrics import summarize
from evals.core.runner import EvalResult, register
from shared.database.database import get_session

SEED = 20260729


def _load_model():
    from shared.utils.model_cache import load_embedding_model

    return load_embedding_model()


@register("events_pipeline")
def events_pipeline(embed: bool = True, countries: list[str] | None = None,
                    **kwargs) -> EvalResult:
    res = EvalResult(component="events_pipeline")
    countries = countries or ["China", "Iran"]

    with get_session() as s:
        # --- 1. state / health ------------------------------------------
        res.metrics["canonical_events_total"] = s.execute(
            text("SELECT count(*) FROM canonical_events")).scalar()
        res.metrics["masters"] = s.execute(
            text("SELECT count(*) FROM canonical_events WHERE master_event_id IS NULL")
        ).scalar()
        res.metrics["children_pending_merge"] = s.execute(
            text("SELECT count(*) FROM canonical_events WHERE master_event_id IS NOT NULL")
        ).scalar()
        res.metrics["llm_validated_rate"] = float(s.execute(
            text("SELECT avg(CASE WHEN llm_validated THEN 1.0 ELSE 0.0 END) "
                 "FROM canonical_events WHERE master_event_id IS NULL")
        ).scalar() or 0)
        res.metrics["multi_day_master_rate"] = float(s.execute(
            text("SELECT avg(CASE WHEN total_mention_days > 1 THEN 1.0 ELSE 0.0 END) "
                 "FROM canonical_events WHERE master_event_id IS NULL")
        ).scalar() or 0)

        clusters_total = s.execute(text("SELECT count(*) FROM event_clusters")).scalar()
        deconflicted = s.execute(
            text("SELECT count(*) FROM event_clusters WHERE llm_deconflicted")).scalar()
        res.metrics["event_clusters_total"] = clusters_total
        res.metrics["deconfliction_coverage"] = deconflicted / max(clusters_total, 1)

        # LLM fail-open rate: deconfliction defaults to same_event=True on any
        # exception; detect via explanation text in refined_clusters JSONB.
        # Exact prefix written by the (former) fail-open default; substring
        # matching on 'fail'/'error' false-positives on words like
        # "counter-terrorism" in legitimate explanations.
        failed = s.execute(
            text(
                "SELECT count(*) FROM event_clusters WHERE llm_deconflicted "
                "AND refined_clusters->>'explanation' LIKE 'LLM review failed%'"
            )
        ).scalar()
        res.metrics["llm_deconflict_failopen_count"] = failed
        res.metrics["llm_deconflict_failopen_rate"] = failed / max(deconflicted, 1)
        if failed:
            res.notes.append(
                f"{failed} clusters carry fail-open LLM deconfliction defaults "
                "(same_event=True assumed after an LLM error). These merges were "
                "never actually validated."
            )

        # --- 4. traceability --------------------------------------------
        rows = s.execute(
            text(
                """
                SELECT dem.id::text, dem.doc_ids
                FROM daily_event_mentions dem
                ORDER BY md5(dem.id::text || :seed) LIMIT 300
                """
            ),
            {"seed": str(SEED)},
        ).fetchall()
        all_ids = sorted({d for _, ids in rows for d in (ids or [])})
        found = set()
        if all_ids:
            for i in range(0, len(all_ids), 5000):
                chunk = all_ids[i:i + 5000]
                found.update(
                    r[0] for r in s.execute(
                        text("SELECT doc_id FROM documents WHERE doc_id = ANY(:ids)"),
                        {"ids": chunk},
                    ).fetchall()
                )
        dangling = len(all_ids) - len(found)
        res.metrics["mention_docids_sampled"] = len(all_ids)
        res.metrics["mention_docids_dangling"] = dangling
        res.metrics["traceability_rate"] = (
            len(found) / max(len(all_ids), 1)
        )
        empty_mentions = sum(1 for _, ids in rows if not ids)
        res.metrics["mentions_with_empty_docids_sample"] = empty_mentions

        # --- 3. residual duplication (stored vectors) -------------------
        for country in countries:
            ev = s.execute(
                text(
                    """
                    SELECT id::text, canonical_name, embedding_vector,
                           first_mention_date, last_mention_date
                    FROM canonical_events
                    WHERE master_event_id IS NULL
                      AND initiating_country = :c
                      AND embedding_vector IS NOT NULL
                    ORDER BY total_articles DESC
                    LIMIT 6000
                    """
                ),
                {"c": country},
            ).fetchall()
            # Cap keeps the O(n^2) similarity matrix bounded (~110MB at 6k
            # rows); post-backfill master counts per country reach ~50k,
            # which would OOM. Scanning the most-covered events keeps the
            # metric focused on duplicates that distort rankings most.
            if len(ev) < 10:
                res.notes.append(f"{country}: only {len(ev)} embedded masters; skipped dup scan")
                continue
            M = np.array([r[2] for r in ev], dtype=np.float32)
            M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
            sims = M @ M.T
            firsts = np.array([r[3].toordinal() for r in ev])
            lasts = np.array([r[4].toordinal() for r in ev])
            # date-gap between ranges (0 if overlapping)
            gap = np.maximum(
                firsts[None, :] - lasts[:, None], firsts[:, None] - lasts[None, :]
            )
            gap = np.maximum(gap, 0)
            iu = np.triu_indices(len(ev), k=1)
            near = (gap[iu] <= 30)
            dup_mask = (sims[iu] >= 0.90) & near
            n_pairs_near = int(near.sum())
            n_dup = int(dup_mask.sum())
            res.metrics[f"{country}_masters_scanned"] = len(ev)
            res.metrics[f"{country}_residual_dup_pairs_sim90_30d"] = n_dup
            res.metrics[f"{country}_residual_dup_rate"] = n_dup / max(n_pairs_near, 1)
            # log the worst offenders for human review
            if n_dup:
                idx = np.argsort(-sims[iu][dup_mask.nonzero()[0]] if False else -sims[iu] * dup_mask)[:5]
                for k in idx:
                    if not dup_mask[k]:
                        continue
                    a, b = iu[0][k], iu[1][k]
                    res.cases.append({
                        "country": country,
                        "sim": float(sims[a, b]),
                        "name_a": ev[a][1][:90],
                        "name_b": ev[b][1][:90],
                    })

    # --- 2 & 5. geometry + prefix ablation (needs embedding model) -------
    if embed:
        try:
            model = _load_model()
        except Exception as e:
            res.notes.append(f"embedding model unavailable, geometry/ablation skipped: {e}")
            model = None
        if model is not None:
            with get_session() as s:
                cl = s.execute(
                    text(
                        """
                        SELECT id::text, initiating_country, cluster_date::text,
                               event_names
                        FROM event_clusters
                        WHERE cluster_size BETWEEN 2 AND 12 AND NOT is_noise
                        ORDER BY md5(id::text || :seed) LIMIT 60
                        """
                    ),
                    {"seed": str(SEED)},
                ).fetchall()
            intra, names_pool = [], []
            for _, _, _, names in cl:
                uniq = list(dict.fromkeys(names or []))
                if len(uniq) < 2:
                    continue
                E = model.encode(uniq, normalize_embeddings=True)
                sims = E @ E.T
                iu = np.triu_indices(len(uniq), k=1)
                intra.append(float(sims[iu].mean()))
                names_pool.extend(uniq[:2])
            res.metrics["intra_cluster_cosine"] = summarize(intra)

            # baseline: random cross-pair similarity over the pooled names
            if len(names_pool) >= 20:
                rng = np.random.default_rng(SEED)
                pool = list(dict.fromkeys(names_pool))[:120]
                E = model.encode(pool, normalize_embeddings=True)
                sims = E @ E.T
                iu = np.triu_indices(len(pool), k=1)
                res.metrics["cross_pair_cosine_baseline"] = summarize(
                    list(map(float, rng.choice(sims[iu], size=min(500, len(sims[iu])),
                                               replace=False)))
                )

                # prefix ablation: does 'search_document: ' change pairwise order?
                E2 = model.encode([f"search_document: {n}" for n in pool],
                                  normalize_embeddings=True)
                sims2 = (E2 @ E2.T)[iu]
                sims1 = sims[iu]
                r1 = np.argsort(np.argsort(sims1))
                r2 = np.argsort(np.argsort(sims2))
                n = len(sims1)
                spearman = 1 - 6 * float(((r1 - r2) ** 2).sum()) / (n * (n * n - 1))
                res.metrics["prefix_ablation_spearman"] = spearman
                res.notes.append(
                    "prefix_ablation_spearman compares pairwise-similarity rankings "
                    "of event names embedded raw (as the event pipeline does) vs "
                    "with the 'search_document:' prefix (as retrieval does). "
                    "Values well below 1.0 mean the two spaces rank neighbors "
                    "differently — i.e. the pipeline's unprefixed vectors are not "
                    "interchangeable with retrieval-side vectors."
                )

    res.caveats.append(
        "No human gold for event identity: cohesion/duplication metrics use the "
        "system's own embedding space, so they detect inconsistency, not "
        "correctness. Residual-duplicate pairs are candidates, not confirmed "
        "duplicates — review the logged cases."
    )
    return res
