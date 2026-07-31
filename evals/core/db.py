"""Shared DB helpers for evals: deterministic sampling and common lookups.

Sampling is seeded so eval runs are reproducible run-to-run; stratification
by initiating country counteracts corpus volume skew (Iran over-representation)
so per-component metrics are not dominated by one media ecosystem.
"""
from __future__ import annotations

import random

from sqlalchemy import text

from shared.database.database import get_session

DEFAULT_SEED = 20260729

# Initiators the platform tracks as influencers; kept in sync with
# shared/config/config.yaml at call time when possible.
def tracked_influencers() -> list[str]:
    try:
        import yaml
        from pathlib import Path

        cfg = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "shared" / "config" / "config.yaml")
            .read_text(encoding="utf-8")
        )
        vals = cfg.get("influencers") or []
        if vals:
            return list(vals)
    except Exception:
        pass
    return ["China", "Russia", "Iran", "Turkey"]


def stratified_documents(
    per_country: int = 25,
    countries: list[str] | None = None,
    min_text_len: int = 400,
    seed: int = DEFAULT_SEED,
) -> list[dict]:
    """Sample documents stratified by initiating country.

    Uses a seeded md5 ordering for determinism (avoids ORDER BY random()
    nondeterminism across runs).
    """
    countries = countries or tracked_influencers()
    out: list[dict] = []
    with get_session() as s:
        for c in countries:
            rows = s.execute(
                text(
                    """
                    SELECT d.doc_id, d.title, d.distilled_text, d.date::text AS date,
                           :country AS initiating_country
                    FROM documents d
                    JOIN initiating_countries ic ON ic.doc_id = d.doc_id
                    WHERE ic.initiating_country = :country
                      AND length(coalesce(d.distilled_text, '')) >= :minlen
                    ORDER BY md5(d.doc_id || :seed)
                    LIMIT :n
                    """
                ),
                {"country": c, "minlen": min_text_len, "seed": str(seed), "n": per_country},
            ).mappings().all()
            out.extend(dict(r) for r in rows)
    rng = random.Random(seed)
    rng.shuffle(out)
    return out


def doc_labels(doc_ids: list[str]) -> dict[str, dict]:
    """Fetch stored (pipeline-extracted) labels for docs: categories,
    initiating/recipient countries — the system's own output, used as the
    'prediction' side in re-extraction agreement evals."""
    if not doc_ids:
        return {}
    labels: dict[str, dict] = {
        d: {"categories": set(), "initiators": set(), "recipients": set()}
        for d in doc_ids
    }
    with get_session() as s:
        for table, col, key in [
            ("categories", "category", "categories"),
            ("initiating_countries", "initiating_country", "initiators"),
            ("recipient_countries", "recipient_country", "recipients"),
        ]:
            rows = s.execute(
                text(f"SELECT doc_id, {col} FROM {table} WHERE doc_id = ANY(:ids)"),
                {"ids": doc_ids},
            ).fetchall()
            for doc_id, val in rows:
                if doc_id in labels and val:
                    labels[doc_id][key].add(val)
    return labels
