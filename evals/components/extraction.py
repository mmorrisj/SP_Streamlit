"""Extraction-layer evals.

extraction_integrity (no LLM, DB only)
    Structural validity of what the extraction stage wrote: taxonomy
    conformance, salience field hygiene, denormalized-vs-normalized
    consistency, null rates, event-name specificity.

extraction_reliability (LLM, opt-in via llm=True)
    (a) Label stability: re-run the current extraction prompt on the stored
        distilled_text for a stratified sample and measure agreement with
        stored labels (category set, initiator/recipient sets, salience).
        This measures reproducibility of the pipeline's own judgment, not
        ground-truth accuracy — the original ran on raw title+body, which is
        not persisted.
    (b) Salience negative controls: feed clearly non-salient synthetic texts
        through the salience gate; the gate should reject them. The DB holds
        only gate-passing docs, so false-negative rate is unmeasurable here;
        this probes false-positive behavior.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import text

from evals.core.db import stratified_documents, doc_labels, tracked_influencers
from evals.core.metrics import set_prf, summarize
from evals.core.runner import EvalResult, register
from shared.database.database import get_session

GENERIC_EVENT_TOKENS = re.compile(
    r"^\s*(?:\w+[-–]\w+\s+)?(relations|cooperation|ties|meeting|talks|summit|"
    r"forum|conference|visit|agreement)s?\s*$",
    re.IGNORECASE,
)


def _config_taxonomies() -> dict:
    import yaml
    from pathlib import Path

    cfg = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "shared" / "config" / "config.yaml")
        .read_text(encoding="utf-8")
    )
    return {
        "categories": set(cfg.get("categories") or []),
        "subcategories": set(cfg.get("subcategories") or []),
        "influencers": set(cfg.get("influencers") or []),
        "recipients": set(cfg.get("recipients") or []),
    }


@register("extraction_integrity")
def extraction_integrity(**kwargs) -> EvalResult:
    res = EvalResult(component="extraction_integrity")
    tax = _config_taxonomies()
    with get_session() as s:
        total = s.execute(text("SELECT count(*) FROM documents")).scalar()
        res.metrics["documents_total"] = total

        # --- salience field hygiene -------------------------------------
        sal = dict(
            s.execute(
                text("SELECT coalesce(salience_bool,'<null>'), count(*) "
                     "FROM documents GROUP BY 1")
            ).fetchall()
        )
        res.metrics["salience_bool_values"] = {k: v for k, v in sal.items()}
        noncanonical = sum(v for k, v in sal.items()
                           if k not in ("true", "false", "<null>"))
        res.metrics["salience_bool_noncanonical_rows"] = noncanonical
        if noncanonical:
            res.notes.append(
                f"{noncanonical} rows have non-canonical salience_bool casing "
                "(e.g. 'True'/'False'); any SQL filtering on ='true' silently "
                "drops or keeps them inconsistently."
            )
        res.metrics["salience_bool_null_rate"] = sal.get("<null>", 0) / max(total, 1)
        false_rows = sal.get("false", 0) + sal.get("False", 0)
        if false_rows:
            res.notes.append(
                f"{false_rows} persisted docs are marked non-salient — the "
                "pipeline is documented to persist only salient docs, so these "
                "are anomalies worth inspecting."
            )

        # --- taxonomy conformance ---------------------------------------
        for table, col, vocab_key in [
            ("categories", "category", "categories"),
            ("subcategories", "subcategory", "subcategories"),
            ("initiating_countries", "initiating_country", None),
            ("recipient_countries", "recipient_country", None),
        ]:
            rows = s.execute(
                text(f"SELECT {col}, count(*) FROM {table} GROUP BY 1 ORDER BY 2 DESC")
            ).fetchall()
            n_rows = sum(r[1] for r in rows)
            if vocab_key:
                vocab = tax[vocab_key]
                oov = [(v, c) for v, c in rows if v not in vocab]
                oov_rows = sum(c for _, c in oov)
                res.metrics[f"{table}_oov_rate"] = oov_rows / max(n_rows, 1)
                res.metrics[f"{table}_distinct_oov_values"] = len(oov)
                if oov:
                    top = ", ".join(f"{v!r}({c})" for v, c in oov[:8])
                    res.notes.append(
                        f"{table}: {oov_rows} rows ({oov_rows / max(n_rows, 1):.1%}) use "
                        f"values outside config.yaml taxonomy — top: {top}"
                    )
            else:
                res.metrics[f"{table}_distinct_values"] = len(rows)

        # --- denormalized vs normalized consistency (sampled) -----------
        sample_rows = s.execute(
            text(
                """
                SELECT doc_id, category, initiating_country, recipient_country
                FROM documents
                WHERE category IS NOT NULL
                ORDER BY md5(doc_id || 'consistency')
                LIMIT 500
                """
            )
        ).fetchall()
    ids = [r[0] for r in sample_rows]
    norm = doc_labels(ids)
    mism = 0
    for doc_id, cat, ic, rc in sample_rows:
        denorm = {c.strip() for c in (cat or "").split(";") if c.strip()}
        if denorm != norm.get(doc_id, {}).get("categories", set()):
            mism += 1
    res.metrics["denorm_vs_norm_category_mismatch_rate"] = mism / max(len(ids), 1)

    # --- event-name specificity -------------------------------------
    with get_session() as s:
        ev = s.execute(
            text(
                """
                SELECT coalesce(specific_event_name, event_name)
                FROM raw_events
                ORDER BY md5(doc_id || event_name || 'spec')
                LIMIT 2000
                """
            )
        ).fetchall()
    generic = sum(1 for (name,) in ev if name and GENERIC_EVENT_TOKENS.match(name))
    res.metrics["generic_event_name_rate_sample2000"] = generic / max(len(ev), 1)
    res.caveats.append(
        "Generic-name detection is regex-based (relations/cooperation/meeting/... "
        "patterns); treat as a lower bound on vagueness."
    )
    res.caveats.append(
        "The DB contains only gate-passing documents, so salience recall "
        "(missed salient docs) cannot be measured from Postgres; it requires "
        "the ingestion results.json files."
    )
    return res


# ---------------------------------------------------------------------------
# LLM-dependent reliability probes
# ---------------------------------------------------------------------------
NEGATIVE_CONTROLS = [
    ("neg_sports", "Local football roundup: City Rovers beat United 2-1 in a "
     "rain-delayed match; the league table remains unchanged ahead of Sunday."),
    ("neg_weather", "A heatwave is expected this weekend with temperatures near "
     "40C; residents are advised to stay hydrated and avoid midday sun."),
    ("neg_celebrity", "The pop star announced a new album release date and a "
     "world tour, with tickets going on sale next Friday."),
    ("neg_market_brief", "Shares of the retail chain rose 3% after quarterly "
     "earnings beat analyst expectations on strong holiday sales."),
    ("neg_crime_local", "Police arrested two suspects after a burglary at a "
     "hardware store downtown; no injuries were reported."),
]

POSITIVE_CONTROLS = [
    ("pos_infra", "China's state-owned CRBC signed a $1.2 billion agreement "
     "with Egypt's transport ministry to finance and build a new light-rail "
     "line connecting Cairo's satellite cities, with Chinese banks providing "
     "concessional loans."),
    ("pos_cultural", "Russia opened a new Russkiy Mir cultural center in "
     "Damascus, offering free Russian language courses and scholarships for "
     "Syrian students to study at Russian universities."),
]


@register("extraction_reliability")
def extraction_reliability(llm: bool = False, sample_per_country: int = 15,
                           **kwargs) -> EvalResult:
    res = EvalResult(component="extraction_reliability")
    if not llm:
        res.notes.append("Skipped LLM probes (pass --llm to enable). No metrics.")
        return res

    from shared.utils.prompts import atom_salience_prompt, atom_extraction_prompt
    from shared.utils.utils import gai, fetch_gai_content

    def llm_json(sys_prompt: str, user_prompt: str):
        resp = gai(sys_prompt, user_prompt, model="gpt-4o-mini")
        # gai() returns already-parsed JSON on the proxy path, a raw OpenAI
        # envelope on direct paths, or a plain string when parsing failed.
        if isinstance(resp, dict) and "choices" in resp:
            out = fetch_gai_content(resp)
        elif isinstance(resp, str):
            import json as _json
            start, end = resp.find("{"), resp.rfind("}")
            out = _json.loads(resp[start:end + 1]) if start >= 0 else resp
        else:
            out = resp
        if isinstance(out, list) and out:
            out = out[0]
        return out

    # --- (b) salience gate controls -------------------------------------
    gate_results = {}
    for name, txt in NEGATIVE_CONTROLS + POSITIVE_CONTROLS:
        try:
            out = llm_json(atom_salience_prompt, f"{name}: {txt}")
            verdict = str(out.get("salience")).strip().lower() == "true"
        except Exception as e:
            verdict = None
            res.notes.append(f"salience gate error on {name}: {e}")
        gate_results[name] = verdict
    neg_pass = [n for n, _ in NEGATIVE_CONTROLS if gate_results.get(n) is True]
    pos_fail = [n for n, _ in POSITIVE_CONTROLS if gate_results.get(n) is False]
    res.metrics["gate_negative_controls_rejected"] = (
        sum(1 for n, _ in NEGATIVE_CONTROLS if gate_results.get(n) is False)
    )
    res.metrics["gate_negative_controls_total"] = len(NEGATIVE_CONTROLS)
    res.metrics["gate_positive_controls_accepted"] = (
        sum(1 for n, _ in POSITIVE_CONTROLS if gate_results.get(n) is True)
    )
    res.metrics["gate_positive_controls_total"] = len(POSITIVE_CONTROLS)
    if neg_pass:
        res.notes.append(f"Gate accepted non-salient controls: {neg_pass}")
    if pos_fail:
        res.notes.append(f"Gate rejected salient controls: {pos_fail}")

    # --- (a) re-extraction label stability ------------------------------
    docs = stratified_documents(per_country=sample_per_country)
    stored = doc_labels([d["doc_id"] for d in docs])
    gold_cats, pred_cats = [], []
    gold_init, pred_init = [], []
    gold_rec, pred_rec = [], []
    sal_agree, n_ok = 0, 0
    for d in docs:
        try:
            out = llm_json(atom_extraction_prompt,
                           f"{d['title']}: {d['distilled_text'][:6000]}")
            if not isinstance(out, dict):
                raise ValueError(f"non-dict output: {type(out)}")
        except Exception as e:
            res.cases.append({"doc_id": d["doc_id"], "error": str(e)[:200]})
            continue
        n_ok += 1
        lab = stored.get(d["doc_id"], {})

        def _split(v):
            return {x.strip() for x in str(v or "").split(";")
                    if x.strip() and x.strip().lower() not in ("n/a", "none", "null")}

        gold_cats.append(lab.get("categories", set()))
        pred_cats.append(_split(out.get("category")))
        gold_init.append(lab.get("initiators", set()))
        pred_init.append(_split(out.get("initiating-country")))
        gold_rec.append(lab.get("recipients", set()))
        pred_rec.append(_split(out.get("recipient-country")))
        if str(out.get("salience-bool")).strip().lower() == "true":
            sal_agree += 1
        else:
            res.cases.append({
                "doc_id": d["doc_id"],
                "disagreement": "stored salient, re-judged non-salient",
                "title": d["title"][:120],
            })
    if n_ok:
        res.metrics["reextraction_n"] = n_ok
        res.metrics["salience_positive_stability"] = sal_agree / n_ok
        res.metrics["category_agreement"] = set_prf(gold_cats, pred_cats)
        res.metrics["initiator_agreement"] = set_prf(gold_init, pred_init)
        res.metrics["recipient_agreement"] = set_prf(gold_rec, pred_rec)
    res.caveats.append(
        "Re-extraction runs on stored distilled_text (raw body is not "
        "persisted), so this measures label stability under the model's own "
        "distillation, not full input-to-output reproducibility."
    )
    res.caveats.append(
        "Agreement here treats stored labels as reference; disagreement means "
        "instability, not necessarily that the stored label is right."
    )
    # Dump disagreements as a seed gold-annotation worksheet.
    res.notes.append(
        f"{len([c for c in res.cases if 'disagreement' in c or 'error' in c])} "
        "cases logged (disagreements/errors) — usable as a human-annotation "
        "seed set in the results JSON."
    )
    return res
