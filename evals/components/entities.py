"""Entity-layer evals.

entities_structural (DB only)
    Master/child state, alias coverage, embedding dimensionality, residual
    duplicate masters above the pipeline's own 0.88 consolidation threshold,
    and daily-mention traceability.

entity_matching (DB + pg extensions)
    Behavioral eval of the RAG three-tier entity matcher
    (services.chat.rag_service.search_entities): for a stratified sample of
    prominent entities, query with
      - the exact canonical name        -> expect a tier-1 exact hit at rank 1
      - a stored alias                  -> expect exact/fuzzy hit
      - a typo perturbation             -> expect fuzzy/semantic hit
      - a descriptive paraphrase        -> expect semantic tier to fire
      - gibberish negative controls     -> expect no matches
    Also verifies each tier is actually operational (pg_trgm / pgvector
    degradation is silent in production code).
"""
from __future__ import annotations

import random

import numpy as np
from sqlalchemy import text

from evals.core.runner import EvalResult, register
from shared.database.database import get_session

SEED = 20260729


@register("entities_structural")
def entities_structural(**kwargs) -> EvalResult:
    res = EvalResult(component="entities_structural")
    with get_session() as s:
        res.metrics["entities_total"] = s.execute(
            text("SELECT count(*) FROM canonical_entities")).scalar()
        res.metrics["masters"] = s.execute(
            text("SELECT count(*) FROM canonical_entities WHERE master_entity_id IS NULL")
        ).scalar()
        dims = s.execute(
            text("SELECT array_length(embedding_vector,1), count(*) "
                 "FROM canonical_entities GROUP BY 1")
        ).fetchall()
        res.metrics["embedding_dims"] = {str(d): c for d, c in dims}
        wrong_dim = sum(c for d, c in dims if d != 768)
        if wrong_dim:
            res.notes.append(
                f"{wrong_dim} entities have non-768-dim (or NULL) embeddings — "
                "semantic tier cannot match them."
            )
        res.metrics["alias_coverage"] = float(s.execute(
            text("SELECT avg(CASE WHEN array_length(alternative_names,1) >= 1 "
                 "THEN 1.0 ELSE 0.0 END) FROM canonical_entities "
                 "WHERE master_entity_id IS NULL")
        ).scalar() or 0)
        res.metrics["description_coverage"] = float(s.execute(
            text("SELECT avg(CASE WHEN entity_description IS NOT NULL THEN 1.0 "
                 "ELSE 0.0 END) FROM canonical_entities WHERE master_entity_id IS NULL")
        ).scalar() or 0)

        # residual duplicates above the pipeline's own consolidation threshold
        for country in ["Iran", "China"]:
            rows = s.execute(
                text(
                    """
                    SELECT canonical_name, embedding_vector, entity_type::text
                    FROM canonical_entities
                    WHERE master_entity_id IS NULL AND initiating_country = :c
                      AND embedding_vector IS NOT NULL
                      AND array_length(embedding_vector,1) = 768
                      AND total_documents >= 3
                    """
                ),
                {"c": country},
            ).fetchall()
            if len(rows) < 20:
                continue
            M = np.array([r[1] for r in rows], dtype=np.float32)
            M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
            sims = M @ M.T
            types = np.array([r[2] for r in rows])
            same_type = types[:, None] == types[None, :]
            iu = np.triu_indices(len(rows), k=1)
            dup = (sims[iu] >= 0.88) & same_type[iu]
            res.metrics[f"{country}_masters_scanned"] = len(rows)
            res.metrics[f"{country}_residual_dup_pairs_ge088"] = int(dup.sum())
            order = np.argsort(-(sims[iu] * dup))[:5]
            for k in order:
                if not dup[k]:
                    continue
                a, b = iu[0][k], iu[1][k]
                res.cases.append({
                    "country": country,
                    "sim": float(sims[a, b]),
                    "a": rows[a][0][:80],
                    "b": rows[b][0][:80],
                    "type": rows[a][2],
                })

        # daily mention traceability
        rows = s.execute(
            text("SELECT doc_ids FROM daily_entity_mentions "
                 "ORDER BY md5(id::text || :seed) LIMIT 200"),
            {"seed": str(SEED)},
        ).fetchall()
        ids = sorted({d for (arr,) in rows for d in (arr or [])})
        found = set()
        for i in range(0, len(ids), 5000):
            found.update(r[0] for r in s.execute(
                text("SELECT doc_id FROM documents WHERE doc_id = ANY(:ids)"),
                {"ids": ids[i:i + 5000]}).fetchall())
        res.metrics["entity_mention_traceability"] = len(found) / max(len(ids), 1)
    res.caveats.append(
        "Residual-duplicate pairs (cosine>=0.88, same type) are merge "
        "candidates the consolidation stage would group on its next run — "
        "confirm by inspection; transliteration-heavy corpora (Iran) inflate "
        "near-duplicates legitimately (e.g. father/son name variants)."
    )
    return res


def _perturb_typo(name: str, rng: random.Random) -> str:
    if len(name) < 5:
        return name + "e"
    i = rng.randrange(1, len(name) - 2)
    return name[:i] + name[i + 1] + name[i] + name[i + 2:]


GIBBERISH = ["Zxqv Plimtor", "Qwrf Blenkoth Institute", "Xylo Vantrago"]


@register("entity_matching")
def entity_matching(sample_n: int = 40, **kwargs) -> EvalResult:
    res = EvalResult(component="entity_matching")
    from services.chat.rag_service import search_entities

    rng = random.Random(SEED)
    with get_session() as s:
        rows = s.execute(
            text(
                """
                SELECT id::text, canonical_name, alternative_names,
                       entity_description, initiating_country
                FROM canonical_entities
                WHERE master_entity_id IS NULL AND total_documents >= 10
                  AND length(canonical_name) >= 6
                ORDER BY md5(id::text || :seed)
                LIMIT :n
                """
            ),
            {"seed": str(SEED), "n": sample_n},
        ).fetchall()

    probes = {
        "exact_name": {"hit": 0, "rank1": 0, "n": 0},
        "alias": {"hit": 0, "rank1": 0, "n": 0},
        "typo": {"hit": 0, "rank1": 0, "n": 0},
        "description": {"hit": 0, "rank1": 0, "n": 0},
    }
    tier_seen: dict[str, int] = {}

    def run_probe(kind: str, query: str, target_id: str):
        probes[kind]["n"] += 1
        try:
            matches = search_entities(query, top_k=10)
        except Exception as e:
            res.cases.append({"probe": kind, "query": query[:80], "error": str(e)[:150]})
            return
        for m in matches:
            tier_seen[m.match_type] = tier_seen.get(m.match_type, 0) + 1
        ids = [m.entity_id for m in matches]
        if target_id in ids:
            probes[kind]["hit"] += 1
            if ids[0] == target_id:
                probes[kind]["rank1"] += 1
        else:
            res.cases.append({
                "probe": kind, "query": query[:80], "expected": target_id,
                "got": [m.canonical_name[:40] for m in matches[:3]],
            })

    for eid, name, aliases, desc, country in rows:
        run_probe("exact_name", name, eid)
        aliases = [a for a in (aliases or []) if a and a.lower() != name.lower()]
        if aliases:
            run_probe("alias", rng.choice(aliases), eid)
        run_probe("typo", _perturb_typo(name, rng), eid)
        if desc and len(desc) > 80:
            # Profile head as a paraphrase probe, with the entity's own name
            # (and its tokens) scrubbed so lexical overlap doesn't trivialize it
            para = desc[:200]
            for tok in [name] + name.split():
                if len(tok) > 3:
                    para = para.replace(tok, " ")
            para = " ".join(para.split())
            if len(para) >= 50:
                run_probe("description", para[:160], eid)

    fp = 0
    for g in GIBBERISH:
        try:
            if search_entities(g, top_k=5):
                fp += 1
        except Exception:
            pass
    res.metrics["gibberish_false_positive"] = f"{fp}/{len(GIBBERISH)}"

    for kind, st in probes.items():
        if st["n"]:
            res.metrics[f"{kind}_hit@10"] = st["hit"] / st["n"]
            res.metrics[f"{kind}_rank1"] = st["rank1"] / st["n"]
            res.metrics[f"{kind}_n"] = st["n"]
    res.metrics["tier_usage"] = tier_seen
    if not tier_seen.get("fuzzy"):
        res.notes.append(
            "Fuzzy tier never fired — pg_trgm may be missing/disabled "
            "(production code swallows that failure silently)."
        )
    if not tier_seen.get("semantic"):
        res.notes.append(
            "Semantic tier never fired — pgvector cast on embedding_vector may "
            "be failing silently, or exact/fuzzy always saturate top_k."
        )
    res.caveats.append(
        "Description-paraphrase probes use the entity's own LLM-written "
        "profile, which shares vocabulary with the stored embedding — treat "
        "semantic hit rates as optimistic."
    )
    return res
