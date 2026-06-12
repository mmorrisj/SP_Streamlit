"""Backend logic for UI-driven document ingestion.

Workers here run inside FastAPI background tasks (see
server/routers/ingestion.py). They communicate exclusively through the
ingestion_jobs table: each batch boundary writes fresh progress counters and
re-reads the cancel flag, so the UI can poll job state and request
cancellation at any time.

Import discipline: this module must stay cheap to import from the server.
DSR parsing comes from dsr_core (light); the embedding stack (torch + vector
store, created at import time by dsr.py) is imported lazily inside the
embedding step only.
"""
import csv
import io
import json
import os
import traceback
from collections import Counter
from datetime import datetime
from typing import Dict, List, Tuple

from shared.database.database import get_session
from shared.models.models import Document, IngestionJob, IngestionJobStatus
from services.pipeline.ingestion.dsr_core import parse_doc, flatten_all_relationships, split_multi

UPLOAD_DIR = os.getenv("INGESTION_UPLOAD_DIR", "./data/uploads")
MAX_UPLOAD_BYTES = int(os.getenv("INGESTION_MAX_UPLOAD_MB", "500")) * 1024 * 1024

# Caps to keep JSONB payloads bounded for very large/dirty files
MAX_ERROR_LOG_ENTRIES = 2000
SAMPLE_SIZE = 20
TOP_N = 10

FILE_TYPE_DSR = "dsr_json"
FILE_TYPE_ATOM = "atom_csv"


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------

def detect_file_type(filename: str, head: bytes) -> str:
    """
    Determine whether an upload is a DSR results.json or an atom CSV.

    Extension narrows the candidates; a structural sniff of the first bytes
    confirms, so a CSV renamed to .json (or vice versa) is rejected with a
    specific message rather than failing later mid-parse.
    """
    lower = (filename or "").lower()
    text_head = head.decode("utf-8", errors="replace").lstrip("﻿").lstrip()

    if lower.endswith(".json"):
        if not text_head.startswith(("[", "{")):
            raise ValueError(
                "File has a .json extension but does not start with JSON content."
            )
        return FILE_TYPE_DSR
    if lower.endswith(".csv"):
        if text_head.startswith(("[", "{")):
            raise ValueError(
                "File has a .csv extension but appears to contain JSON content."
            )
        return FILE_TYPE_ATOM
    raise ValueError(
        "Unsupported file type. Upload a DSR results .json file or an atom .csv file."
    )


# ---------------------------------------------------------------------------
# Job helpers
# ---------------------------------------------------------------------------

def _update_job(job_id: str, **fields) -> None:
    """Write fields to a job row in its own short transaction (poll-visible)."""
    with get_session() as session:
        job = session.get(IngestionJob, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        session.commit()


def _cancel_requested(job_id: str) -> bool:
    with get_session() as session:
        job = session.get(IngestionJob, job_id)
        return bool(job and job.cancel_requested)


def _existing_doc_ids(doc_ids: List[str], chunk_size: int = 1000) -> set:
    """One IN(...) query per chunk instead of one SELECT per document."""
    existing = set()
    if not doc_ids:
        return existing
    with get_session() as session:
        for i in range(0, len(doc_ids), chunk_size):
            chunk = doc_ids[i:i + chunk_size]
            rows = session.query(Document.doc_id).filter(Document.doc_id.in_(chunk)).all()
            existing.update(row[0] for row in rows)
    return existing


# ---------------------------------------------------------------------------
# DSR parsing (shared by validation and ingestion)
# ---------------------------------------------------------------------------

def _load_dsr_records(file_path: str) -> List[dict]:
    """Load raw DSR records from a results.json file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        # Some exports wrap documents in one extra list level
        if data and all(isinstance(item, list) for item in data):
            return [doc for sublist in data for doc in sublist]
        return data
    raise ValueError("Unexpected JSON structure: expected a list of DSR documents.")


def _parse_all(records: List[dict]) -> Tuple[List[Document], List[dict]]:
    """
    Run parse_doc over every record without touching the database.

    Returns (parsed detached Document instances, error entries). Within-file
    duplicates are reported as errors and dropped (first occurrence wins).
    """
    parsed: List[Document] = []
    errors: List[dict] = []
    seen_ids = set()

    for record in records:
        doc_id = record.get("id", "<missing id>") if isinstance(record, dict) else "<not an object>"
        try:
            doc = parse_doc(record)
        except Exception as exc:
            errors.append({"doc_id": str(doc_id), "stage": "parse", "reason": str(exc)})
            continue
        if doc is None:
            errors.append({
                "doc_id": str(doc_id),
                "stage": "parse",
                "reason": "Missing auto.gai analysis block (not a DSR extract record)",
            })
            continue
        if doc.doc_id in seen_ids:
            errors.append({
                "doc_id": str(doc.doc_id),
                "stage": "parse",
                "reason": "Duplicate doc_id within file (first occurrence kept)",
            })
            continue
        seen_ids.add(doc.doc_id)
        parsed.append(doc)

    return parsed, errors


def _doc_sample_row(doc: Document) -> dict:
    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "date": str(doc.date) if doc.date else None,
        "source_name": doc.source_name,
        "initiating_country": doc.initiating_country,
        "recipient_country": doc.recipient_country,
        "category": doc.category,
        "event_name": doc.event_name,
    }


# ---------------------------------------------------------------------------
# Validation workers (dry run — no document writes)
# ---------------------------------------------------------------------------

def run_validation(job_id: str) -> None:
    """Background worker: produce a validation report for an uploaded file."""
    _update_job(job_id, status=IngestionJobStatus.VALIDATING.value)
    try:
        with get_session() as session:
            job = session.get(IngestionJob, job_id)
            file_path, file_type = job.file_path, job.file_type

        if file_type == FILE_TYPE_DSR:
            report, error_log = _validate_dsr(file_path)
        else:
            report, error_log = _validate_atom_csv(file_path)

        _update_job(
            job_id,
            status=IngestionJobStatus.READY.value,
            validation_report=report,
            error_log=error_log[:MAX_ERROR_LOG_ENTRIES],
        )
    except Exception as exc:
        traceback.print_exc()
        _update_job(
            job_id,
            status=IngestionJobStatus.VALIDATION_FAILED.value,
            error_message=f"Validation failed: {exc}",
        )


def _validate_dsr(file_path: str) -> Tuple[dict, List[dict]]:
    records = _load_dsr_records(file_path)
    parsed, errors = _parse_all(records)

    doc_ids = [doc.doc_id for doc in parsed]
    existing = _existing_doc_ids(doc_ids)

    dates = sorted(str(doc.date) for doc in parsed if doc.date)
    collections = Counter(doc.collection_name for doc in parsed if doc.collection_name)
    initiating = Counter()
    recipients = Counter()
    for doc in parsed:
        initiating.update(split_multi(doc.initiating_country))
        recipients.update(split_multi(doc.recipient_country))

    missing_event = sum(1 for doc in parsed if not doc.event_name)
    missing_distilled = sum(1 for doc in parsed if not doc.distilled_text)
    within_file_dupes = sum(1 for e in errors if "Duplicate doc_id within file" in e["reason"])

    warnings = []
    if missing_event:
        warnings.append({
            "code": "missing_event_name",
            "message": "Documents with no event-name/project-name/projects value",
            "count": missing_event,
        })
    if missing_distilled:
        warnings.append({
            "code": "missing_distilled_text",
            "message": "Documents without distilled_text — these cannot be embedded",
            "count": missing_distilled,
        })
    if within_file_dupes:
        warnings.append({
            "code": "within_file_duplicates",
            "message": "Duplicate doc_ids inside the file (first occurrence kept)",
            "count": within_file_dupes,
        })

    report = {
        "file_type": FILE_TYPE_DSR,
        "total_records": len(records),
        "parseable": len(parsed),
        "parse_errors": len(errors) - within_file_dupes,
        "new_documents": len(doc_ids) - len(existing),
        "existing_documents": len(existing),
        "within_file_duplicates": within_file_dupes,
        "date_range": {"min": dates[0], "max": dates[-1]} if dates else None,
        "collections": dict(collections.most_common(TOP_N)),
        "top_initiating_countries": [
            {"country": c, "count": n} for c, n in initiating.most_common(TOP_N)
        ],
        "top_recipient_countries": [
            {"country": c, "count": n} for c, n in recipients.most_common(TOP_N)
        ],
        "warnings": warnings,
        "sample": [_doc_sample_row(doc) for doc in parsed[:SAMPLE_SIZE]],
        "runnable": len(parsed) > 0,
        "not_runnable_reason": None if parsed else "No parseable DSR documents found in file.",
    }
    return report, errors


def _validate_atom_csv(file_path: str) -> Tuple[dict, List[dict]]:
    """
    Validate an atom CSV upload: structural preview only.

    The atom path requires LLM soft-power extraction before documents are
    database-ready; that pipeline is not yet wired to the UI (Phase 3 in
    docs/INGESTION_UI_DESIGN.md), so atom jobs are never runnable — users
    still get a structure/duplication report out of the upload.
    """
    import pandas as pd

    encoding_warning = None
    try:
        df = pd.read_csv(file_path, engine="python", on_bad_lines="skip", encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, engine="python", on_bad_lines="skip", encoding="latin-1")
        df.rename(columns={"ï»¿Title": "Title"}, inplace=True)
        encoding_warning = "File was not valid UTF-8; fell back to latin-1 decoding."

    columns = [c for c in df.columns if "Unnamed" not in str(c)]
    required = ["Title", "Body"]
    missing_columns = [c for c in required if c not in columns]

    warnings = []
    if encoding_warning:
        warnings.append({"code": "encoding_fallback", "message": encoding_warning, "count": 1})
    if missing_columns:
        warnings.append({
            "code": "missing_columns",
            "message": f"Required columns missing: {', '.join(missing_columns)}",
            "count": len(missing_columns),
        })

    empty_body = int(df["Body"].isna().sum()) if "Body" in columns else None
    if empty_body:
        warnings.append({
            "code": "empty_body",
            "message": "Rows with an empty Body (dropped by the cleaning step)",
            "count": empty_body,
        })
    duplicate_titles = int(df.duplicated(subset="Title").sum()) if "Title" in columns else None
    if duplicate_titles:
        warnings.append({
            "code": "duplicate_titles",
            "message": "Rows with duplicate titles (deduplicated by the cleaning step)",
            "count": duplicate_titles,
        })

    collections = (
        df["Collection Name"].value_counts().head(TOP_N).to_dict()
        if "Collection Name" in columns else {}
    )
    sample_cols = [c for c in ["Title", "Collection Name", "Source Name", "Source Date, Start"] if c in columns]
    sample = df[sample_cols].head(SAMPLE_SIZE).fillna("").to_dict(orient="records") if sample_cols else []

    report = {
        "file_type": FILE_TYPE_ATOM,
        "total_records": int(len(df)),
        "parseable": int(len(df) - (empty_body or 0)),
        "parse_errors": 0,
        "columns": [str(c) for c in columns],
        "collections": {str(k): int(v) for k, v in collections.items()},
        "warnings": warnings,
        "sample": sample,
        "runnable": False,
        "not_runnable_reason": (
            "Atom CSV ingestion requires the LLM soft-power extraction pipeline, "
            "which is not yet available from the UI. Validation report only."
        ),
    }
    return report, []


# ---------------------------------------------------------------------------
# Ingestion worker
# ---------------------------------------------------------------------------

def run_ingestion(job_id: str) -> None:
    """
    Background worker: load a validated DSR file into the database.

    Stages: parse → batched load + relationship flattening → (optional)
    embedding. Progress counters are written and the cancel flag re-read at
    every batch boundary.
    """
    try:
        _run_ingestion_inner(job_id)
    except Exception as exc:
        traceback.print_exc()
        _update_job(
            job_id,
            status=IngestionJobStatus.FAILED.value,
            error_message=f"Ingestion failed: {exc}",
            finished_at=datetime.utcnow(),
        )


def _run_ingestion_inner(job_id: str) -> None:
    with get_session() as session:
        job = session.get(IngestionJob, job_id)
        file_path = job.file_path
        options = dict(job.options or {})

    embed_now = bool(options.get("embed_now", True))
    reflatten_duplicates = bool(options.get("reflatten_duplicates", False))
    doc_batch_size = int(options.get("doc_batch_size", 100))
    embed_batch_size = int(options.get("embed_batch_size", 50))

    _update_job(job_id, status=IngestionJobStatus.LOADING.value, started_at=datetime.utcnow())

    records = _load_dsr_records(file_path)
    parsed, errors = _parse_all(records)
    existing = _existing_doc_ids([doc.doc_id for doc in parsed])

    progress = {
        "stage": "loading",
        "total_records": len(records),
        "parsed": len(parsed),
        "loaded": 0,
        "duplicates": 0,
        "errors": len(errors),
        "relationships": {},
        "embedded": 0,
        "embed_total": 0,
    }
    _update_job(job_id, progress=dict(progress))

    new_doc_ids: List[str] = []
    relationship_totals: Dict[str, int] = {}

    def flush_batch(session, batch: List[Document]) -> None:
        session.add_all(batch)
        session.commit()
        counts = flatten_all_relationships(session, batch)
        session.commit()
        for key, value in counts.items():
            relationship_totals[key] = relationship_totals.get(key, 0) + value

    cancelled = False
    with get_session() as session:
        batch: List[Document] = []
        duplicates_to_reflatten: List[Document] = []

        for doc in parsed:
            if doc.doc_id in existing:
                progress["duplicates"] += 1
                if reflatten_duplicates:
                    duplicates_to_reflatten.append(doc)
                continue
            batch.append(doc)
            new_doc_ids.append(doc.doc_id)

            if len(batch) >= doc_batch_size:
                flush_batch(session, batch)
                progress["loaded"] += len(batch)
                progress["relationships"] = dict(relationship_totals)
                batch = []
                _update_job(job_id, progress=dict(progress))
                if _cancel_requested(job_id):
                    cancelled = True
                    break

        if not cancelled and batch:
            flush_batch(session, batch)
            progress["loaded"] += len(batch)
            progress["relationships"] = dict(relationship_totals)
            _update_job(job_id, progress=dict(progress))

        # Re-flatten relationships for documents that already existed
        # (mirrors the CLI behavior, but opt-in from the UI)
        if not cancelled and duplicates_to_reflatten:
            for i in range(0, len(duplicates_to_reflatten), doc_batch_size):
                flatten_all_relationships(session, duplicates_to_reflatten[i:i + doc_batch_size])
                session.commit()
                if _cancel_requested(job_id):
                    cancelled = True
                    break

    # Replaces the validation-time error log: the run re-parses the file, so
    # these are the same parse errors plus anything new from load/embed.
    all_errors = errors[:MAX_ERROR_LOG_ENTRIES]

    if cancelled:
        _update_job(
            job_id,
            status=IngestionJobStatus.CANCELLED.value,
            progress=dict(progress),
            error_log=all_errors,
            finished_at=datetime.utcnow(),
        )
        return

    # ----- Embedding stage -------------------------------------------------
    if embed_now and new_doc_ids:
        progress["stage"] = "embedding"
        _update_job(job_id, status=IngestionJobStatus.EMBEDDING.value, progress=dict(progress))
        embed_errors, embedded, cancelled = _embed_documents(
            job_id, new_doc_ids, embed_batch_size, progress
        )
        all_errors = (all_errors + embed_errors)[:MAX_ERROR_LOG_ENTRIES]
        progress["embedded"] = embedded
        if cancelled:
            _update_job(
                job_id,
                status=IngestionJobStatus.CANCELLED.value,
                progress=dict(progress),
                error_log=all_errors,
                finished_at=datetime.utcnow(),
            )
            return

    progress["stage"] = "done"
    final_status = (
        IngestionJobStatus.COMPLETED_WITH_ERRORS.value
        if all_errors else IngestionJobStatus.COMPLETED.value
    )
    _update_job(
        job_id,
        status=final_status,
        progress=dict(progress),
        error_log=all_errors,
        finished_at=datetime.utcnow(),
    )


def _embed_documents(
    job_id: str,
    doc_ids: List[str],
    batch_size: int,
    progress: dict,
) -> Tuple[List[dict], int, bool]:
    """
    Generate embeddings for newly loaded documents.

    Mirrors dsr.embed_documents_direct, with per-batch progress writes and
    cancellation. The vector store import is deferred to here because it
    pulls torch and the HF embedding model.
    """
    from services.pipeline.embeddings.embedding_vectorstore import chunk_store
    from services.pipeline.ingestion.dsr_core import document_text_fn, document_metadata_fn

    errors: List[dict] = []
    embedded = 0

    with get_session() as session:
        embeddable = session.query(Document).filter(
            Document.doc_id.in_(doc_ids),
            Document.distilled_text.isnot(None),
            Document.distilled_text != "",
        ).all()

        progress["embed_total"] = len(embeddable)
        _update_job(job_id, progress=dict(progress))

        for i in range(0, len(embeddable), batch_size):
            batch = embeddable[i:i + batch_size]
            texts = [document_text_fn(doc) for doc in batch]
            metadatas = [document_metadata_fn(doc) for doc in batch]
            ids = [doc.doc_id for doc in batch]
            try:
                chunk_store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
                embedded += len(batch)
            except Exception as exc:
                for doc in batch:
                    errors.append({
                        "doc_id": doc.doc_id,
                        "stage": "embed",
                        "reason": str(exc),
                    })

            progress["embedded"] = embedded
            _update_job(job_id, progress=dict(progress))
            if _cancel_requested(job_id):
                return errors, embedded, True

    return errors, embedded, False


# ---------------------------------------------------------------------------
# Error report export
# ---------------------------------------------------------------------------

def error_log_csv(job: IngestionJob) -> str:
    """Render a job's error log as CSV text for download."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["doc_id", "stage", "reason"])
    for entry in job.error_log or []:
        writer.writerow([entry.get("doc_id", ""), entry.get("stage", ""), entry.get("reason", "")])
    return buffer.getvalue()
