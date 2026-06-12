"""Modern ATOM CSV pipeline: salience gate + initial extraction.

Replaces the legacy trio (ingestion/atom.py, ingestion/atom_salience.py,
analysis/atom_extraction.py), which were SQLite/Azure-era and hardcoded to
./kuwait paths. This module is the single entry point for raw CSV exports from
the ATOM query tool:

    ATOM CSV -> find body text -> salience gate -> (if salient) initial
    extraction (distillation, event name, categories, initiating/recipient
    countries, ...) -> results.json artifact -> Postgres Document upsert

Division of labor with dsr.py: dsr.py ingests *pre-extracted* DSR JSON exports
(extraction already done upstream); this pipeline handles *raw* article text
and performs the extraction itself. Both converge on the same Document model
and shared normalization (flatten_all_relationships).

Modern conventions used throughout:
  * LLM calls go through shared.utils.utils.gai() (proxy/LiteLLM routing,
    enterprise gateway JWT) — never a direct provider SDK.
  * Prompts live in shared/utils/prompts.py (atom_salience_prompt,
    atom_extraction_prompt). Output keys are hyphenated like the DSR export;
    we map hyphen -> underscore onto Document, same as dsr.py.
  * DB via shared.database.database.get_session; idempotent on doc_id.
  * results.json is written incrementally and reloaded on restart, so an
    interrupted run resumes instead of re-paying for LLM calls.

CLI:
    python services/pipeline/ingestion/atom_pipeline.py export.csv
    ... export.csv --results-out ./results.json --limit 100
    ... export.csv --dry-run            # LLM calls + results.json, no DB writes
    ... export.csv --status             # counts only, no processing

Embeddings are intentionally out of scope — run
services/pipeline/embeddings/embed_missing_documents.py afterwards, same as
for dsr.py ingests.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# Models are env-tunable; salience is a cheap boolean gate, extraction does the
# heavy lifting. Both route through gai()'s GAI_DEFAULT_SOURCE backend.
SALIENCE_MODEL = os.getenv("ATOM_SALIENCE_MODEL", "gpt-4o-mini")
EXTRACTION_MODEL = os.getenv("ATOM_EXTRACTION_MODEL", "gpt-4o-mini")

RESULTS_FLUSH_EVERY = 25
PROMPT_ID = "atom_pipeline_extraction"
PROMPT_VERSION = 1

# Extraction output keys (hyphenated, DSR-style) -> Document attributes.
# LAT_LONG is the one key that isn't a plain hyphen->underscore mapping.
_FIELD_MAP = {
    "salience-justification": "salience_justification",
    "category": "category",
    "category-justification": "category_justification",
    "subcategory": "subcategory",
    "initiating-country": "initiating_country",
    "recipient-country": "recipient_country",
    "projects": "projects",
    "LAT_LONG": "lat_long",
    "location": "location",
    "monetary-commitment": "monetary_commitment",
    "distilled-text": "distilled_text",
    "event-name": "event_name",
}


@dataclass
class AtomRecord:
    """One row of an ATOM CSV export, reduced to the fields the pipeline needs."""

    atom_id: str
    title: str
    body: str
    source_name: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD
    collection_name: Optional[str] = None


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def _find_column(columns: Iterable[str], *candidates: str) -> Optional[str]:
    """Case/spacing-insensitive column lookup ('BODY' vs 'Body', BOM noise)."""
    normalized = {str(c).strip().lower().lstrip("﻿"): c for c in columns}
    for cand in candidates:
        if cand.lower() in normalized:
            return normalized[cand.lower()]
    return None


def _parse_date(raw: Any) -> Optional[str]:
    if raw is None or str(raw).strip() == "" or str(raw).lower() == "nan":
        return None
    s = str(raw).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(s[:19].split("T")[0], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.warning("unparseable date %r", raw)
    return None


def load_atom_csv(path: str, collection: Optional[str] = None) -> list[AtomRecord]:
    """Read an ATOM CSV export into AtomRecords.

    Tolerates the export quirks the legacy scripts handled: BOM/latin-1
    encodings, malformed lines, 'Body' vs 'BODY' casing, duplicate articles.
    Rows without an ATOM ID or body text are dropped (there is nothing to
    classify), as are duplicate titles (re-syndicated wire copies).
    """
    import pandas as pd

    try:
        df = pd.read_csv(path, engine="python", on_bad_lines="skip", encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(path, engine="python", on_bad_lines="skip", encoding="latin-1")

    id_col = _find_column(df.columns, "ATOM ID", "atom_id", "id")
    body_col = _find_column(df.columns, "BODY", "Body")
    title_col = _find_column(df.columns, "Title")
    if not id_col or not body_col:
        raise ValueError(
            f"CSV at {path} is missing required columns "
            f"(need an ATOM ID and a Body column; found: {list(df.columns)[:15]})"
        )
    source_col = _find_column(df.columns, "Source Name")
    date_col = _find_column(df.columns, "Source Date, Start", "Source Date", "Date")
    coll_col = _find_column(df.columns, "Collection Name")

    if coll_col and collection:
        df = df[df[coll_col] == collection]

    df = df.dropna(subset=[body_col, id_col])
    if title_col:
        df = df.drop_duplicates(subset=[title_col])
    df = df.drop_duplicates(subset=[id_col])

    records: list[AtomRecord] = []
    for _, row in df.iterrows():
        body = str(row[body_col]).replace("\n", " ").strip()
        if not body:
            continue
        records.append(
            AtomRecord(
                atom_id=str(row[id_col]).strip(),
                title=str(row[title_col]).strip() if title_col else "",
                body=body,
                source_name=str(row[source_col]).strip() if source_col and not _isna(row[source_col]) else None,
                date=_parse_date(row[date_col]) if date_col else None,
                collection_name=str(row[coll_col]).strip() if coll_col and not _isna(row[coll_col]) else None,
            )
        )
    return records


def _isna(v: Any) -> bool:
    return v is None or (isinstance(v, float) and v != v) or str(v).lower() == "nan"


# ---------------------------------------------------------------------------
# LLM stages
# ---------------------------------------------------------------------------

def _llm_json(sys_prompt: str, user_prompt: str, model: str) -> Any:
    """One gai() call -> parsed JSON content (or raise)."""
    from shared.utils.utils import fetch_gai_content, gai

    response = gai(sys_prompt, user_prompt, model=model)
    return fetch_gai_content(response)


def _first(obj: Any) -> Any:
    """The prompts occasionally return a one-element list around the dict."""
    if isinstance(obj, list):
        return obj[0] if obj else None
    return obj


def classify_salience(record: AtomRecord, model: str = SALIENCE_MODEL) -> bool:
    """Cheap boolean gate: is this article about a soft-power engagement?"""
    from shared.utils.prompts import atom_salience_prompt

    output = _first(_llm_json(atom_salience_prompt, f"{record.title}: {record.body}", model))
    if not isinstance(output, dict) or "salience" not in output:
        raise ValueError(f"unexpected salience output: {output!r}")
    return str(output["salience"]).strip().lower() == "true"


def extract_record(record: AtomRecord, model: str = EXTRACTION_MODEL) -> dict[str, Any]:
    """Full initial extraction for a salient article.

    Returns the raw hyphen-keyed dict from the prompt (the same shape the DSR
    export carries), so results.json stays schema-compatible with upstream.
    """
    from shared.utils.prompts import atom_extraction_prompt

    output = _first(_llm_json(atom_extraction_prompt, f"{record.title}: {record.body}", model))
    if not isinstance(output, dict) or "salience-bool" not in output:
        raise ValueError(f"unexpected extraction output: {output!r}")
    return output


# ---------------------------------------------------------------------------
# Document mapping
# ---------------------------------------------------------------------------

def _normalize(val: Any) -> Optional[str]:
    """Match dsr.py's normalize_value: empty/N-A-ish -> None, else stripped str."""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in ("n/a", "na", "none", "null", "n/a.", ""):
        return None
    return s


def build_document(record: AtomRecord, extraction: dict[str, Any], model: str):
    """Map a record + extraction output onto a Document model instance."""
    from shared.models.models import Document

    doc = Document(
        doc_id=record.atom_id,
        title=record.title or None,
        source_name=record.source_name,
        date=datetime.strptime(record.date, "%Y-%m-%d").date() if record.date else None,
        collection_name=record.collection_name,
        gai_engine=model,
        gai_promptid=PROMPT_ID,
        gai_promptversion=PROMPT_VERSION,
        salience_bool=str(_truthy(extraction.get("salience-bool"))).lower(),
    )
    for src_key, attr in _FIELD_MAP.items():
        if attr == "projects":
            doc.projects = _normalize(extraction.get(src_key))
            continue
        setattr(doc, attr, _normalize(extraction.get(src_key)))
    # Same consolidation as dsr.py: fall back to projects when the model
    # produced no event name.
    if not doc.event_name and doc.projects:
        doc.event_name = doc.projects
    return doc


def _truthy(val: Any) -> bool:
    return str(val).strip().lower() == "true"


# ---------------------------------------------------------------------------
# results.json artifact
# ---------------------------------------------------------------------------

def _load_results(path: str) -> dict[str, dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        data = json.load(f)
    # Tolerate the legacy list-of-{atom_id: output} shape as well as the
    # current flat {atom_id: output} mapping.
    if isinstance(data, list):
        flat: dict[str, dict[str, Any]] = {}
        for item in data:
            if isinstance(item, dict):
                flat.update(item)
        return flat
    return data if isinstance(data, dict) else {}


def _save_results(path: str, results: dict[str, dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(results, f, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _existing_doc_ids(atom_ids: list[str]) -> set[str]:
    from sqlalchemy import text as sql_text
    from sqlalchemy import bindparam
    from sqlalchemy.dialects.postgresql import ARRAY
    from sqlalchemy.types import String as SAString
    from shared.database.database import get_session

    if not atom_ids:
        return set()
    stmt = sql_text(
        "SELECT doc_id FROM documents WHERE doc_id = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=ARRAY(SAString)))
    with get_session() as session:
        rows = session.execute(stmt, {"ids": atom_ids}).fetchall()
    return {r[0] for r in rows}


def _persist_documents(documents: list) -> None:
    """Insert new Documents and flatten their multi-value fields, reusing
    dsr.py's normalization so both ingest paths stay identical downstream."""
    from services.pipeline.ingestion.dsr import flatten_all_relationships
    from shared.database.database import get_session

    if not documents:
        return
    with get_session() as session:
        for doc in documents:
            session.merge(doc)
        flatten_all_relationships(session, documents)


def process_atom_csv(
    csv_path: str,
    results_path: Optional[str] = None,
    collection: Optional[str] = None,
    dry_run: bool = False,
    reprocess: bool = False,
    limit: Optional[int] = None,
    salience_model: str = SALIENCE_MODEL,
    extraction_model: str = EXTRACTION_MODEL,
    progress_cb=None,
    should_cancel=None,
) -> dict[str, Any]:
    """Run the full pipeline over one CSV export.

    Returns a summary dict: counts of records seen, skipped (already in DB or
    results.json), gated out as non-salient, extracted, persisted, and errored,
    plus persisted_doc_ids (for a follow-on embedding step) and cancelled.

    progress_cb(summary) is invoked after every processed record so a caller
    (e.g. the ingestion UI worker) can surface live counts. should_cancel() is
    checked at each record boundary; when it returns True the run stops
    gracefully — results.json is flushed and already-extracted documents are
    still persisted, so the run can resume later without re-paying LLM calls.
    """
    results_path = results_path or os.path.join(
        os.path.dirname(os.path.abspath(csv_path)),
        f"results_{datetime.now().strftime('%Y-%m-%d')}.json",
    )

    records = load_atom_csv(csv_path, collection=collection)
    results = _load_results(results_path)

    skip_ids: set[str] = set(results.keys())
    if not dry_run and not reprocess:
        skip_ids |= _existing_doc_ids([r.atom_id for r in records])

    summary = {
        "csv": csv_path,
        "results_json": results_path,
        "total_rows": len(records),
        "skipped_existing": 0,
        "non_salient": 0,
        "extracted": 0,
        "persisted": 0,
        "errors": 0,
        "persisted_doc_ids": [],
        "cancelled": False,
    }

    pending_docs: list = []
    since_flush = 0
    processed = 0

    for record in records:
        if limit is not None and processed >= limit:
            break
        if should_cancel is not None and should_cancel():
            summary["cancelled"] = True
            break
        if record.atom_id in skip_ids and not reprocess:
            summary["skipped_existing"] += 1
            continue
        processed += 1

        try:
            salient = classify_salience(record, model=salience_model)
        except Exception as e:
            logger.exception("salience failed for %s", record.atom_id)
            results[record.atom_id] = {"error": f"salience: {e}"}
            summary["errors"] += 1
            continue

        if not salient:
            results[record.atom_id] = {"salience-bool": False}
            summary["non_salient"] += 1
        else:
            try:
                extraction = extract_record(record, model=extraction_model)
            except Exception as e:
                logger.exception("extraction failed for %s", record.atom_id)
                results[record.atom_id] = {"error": f"extraction: {e}"}
                summary["errors"] += 1
                continue
            results[record.atom_id] = extraction
            summary["extracted"] += 1
            # The extraction pass re-judges salience with full context; only
            # persist documents it still considers salient.
            if _truthy(extraction.get("salience-bool")) and not dry_run:
                pending_docs.append(build_document(record, extraction, extraction_model))

        since_flush += 1
        if since_flush >= RESULTS_FLUSH_EVERY:
            _save_results(results_path, results)
            since_flush = 0
            logger.info("flushed results.json (%d entries)", len(results))
        if progress_cb is not None:
            progress_cb(dict(summary))

    _save_results(results_path, results)

    if pending_docs:
        _persist_documents(pending_docs)
        summary["persisted"] = len(pending_docs)
        summary["persisted_doc_ids"] = [d.doc_id for d in pending_docs]

    if progress_cb is not None:
        progress_cb(dict(summary))
    return summary


def status(csv_path: str, results_path: Optional[str] = None) -> dict[str, Any]:
    """Counts only — how much of this CSV is already processed."""
    records = load_atom_csv(csv_path)
    atom_ids = [r.atom_id for r in records]
    results = _load_results(results_path) if results_path else {}
    in_db = _existing_doc_ids(atom_ids)
    return {
        "rows": len(records),
        "in_results_json": sum(1 for a in atom_ids if a in results),
        "in_database": len(in_db),
        "remaining": sum(1 for a in atom_ids if a not in results and a not in in_db),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="ATOM CSV salience + extraction pipeline")
    p.add_argument("csv", help="Path to an ATOM CSV export")
    p.add_argument("--results-out", help="results.json path (default: alongside the CSV)")
    p.add_argument("--collection", help="Filter rows to this Collection Name")
    p.add_argument("--dry-run", action="store_true", help="LLM + results.json, no DB writes")
    p.add_argument("--reprocess", action="store_true", help="Re-run rows already processed")
    p.add_argument("--limit", type=int, help="Process at most N unprocessed rows")
    p.add_argument("--status", action="store_true", help="Report counts and exit")
    p.add_argument("--salience-model", default=SALIENCE_MODEL)
    p.add_argument("--extraction-model", default=EXTRACTION_MODEL)
    args = p.parse_args()

    if args.status:
        print(json.dumps(status(args.csv, args.results_out), indent=2))
        return

    summary = process_atom_csv(
        csv_path=args.csv,
        results_path=args.results_out,
        collection=args.collection,
        dry_run=args.dry_run,
        reprocess=args.reprocess,
        limit=args.limit,
        salience_model=args.salience_model,
        extraction_model=args.extraction_model,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
