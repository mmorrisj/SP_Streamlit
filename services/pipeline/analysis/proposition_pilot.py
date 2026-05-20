"""Proposition extraction pilot - reads DSR JSON from S3, writes JSONL.

Two modes:

  Pilot / single-file mode (--output FILE):
      Run a small slice end-to-end and produce a single pretty-printed JSON
      array. Good for evaluating prompt changes.

  Batch mode (--output-dir DIR):
      Stream JSONL output, one file per source CSV, with --resume support.
      Used for populating proposition data at scale before loading to Postgres.
      Reads initiator/recipient country lists from shared/config/config.yaml
      (influencers / recipients) when --country/--recipient/--initiators/--recipients
      are not supplied.

S3 bucket comes from the project's config (S3_BUCKET env var or
shared/config/config.yaml). Default prefix is dsr_extracts/.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, date as DateType
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Allow running as `python services/pipeline/analysis/proposition_pilot.py`
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env so LITELLM_URL / LITELLM_API_KEY / GAI_DEFAULT_SOURCE etc. are available
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

from shared.utils.utils import gai, find_json_objects
from shared.utils.prompts_proposition import (
    proposition_extraction_prompt,
    PROPOSITION_PROMPT_VERSION,
)
from services.pipeline.embeddings.s3 import (
    list_s3_json_files,
    download_s3_json_file,
    get_bucket_name,
)


def _normalize(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in {"", "n/a", "na", "none", "null", "n/a."}:
        return None
    return s


def parse_dsr_doc_minimal(dsr_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull all gai typed responses + minimal source metadata from a raw DSR doc.

    Captures every type->value mapping in `gai_fields` so we can diagnose
    type-name variations across DSR generations (salience vs salience-bool,
    distilled-text vs distilled_text, etc.).
    """
    auto = dsr_doc.get("auto") or {}
    gai_list = auto.get("gai") or []
    if len(gai_list) < 2:
        return None
    gai_block = gai_list[1] or {}

    gai_fields: Dict[str, Optional[str]] = {}
    for response in gai_block.get("value", []) or []:
        rtype = response.get("type")
        if not rtype:
            continue
        gai_fields[rtype] = _normalize(response.get("value"))

    mt = dsr_doc.get("machineTranslations") or {}
    title_translation = (mt.get("title_title") or {}).get("text")
    title = title_translation or (dsr_doc.get("title") or {}).get("title")

    start_date_raw = (dsr_doc.get("source") or {}).get("startDate")
    doc_date = _parse_date(start_date_raw)

    # Salience can appear as 'salience', 'salience-bool', or capitalized variants.
    salience = (
        gai_fields.get("salience")
        or gai_fields.get("salience-bool")
        or gai_fields.get("Salience")
        or gai_fields.get("Salience_Bool")
    )

    return {
        "doc_id": dsr_doc.get("id"),
        "title": title,
        "date": doc_date,
        "source_name": ((dsr_doc.get("source") or {}).get("name") or {}).get("transliterated"),
        "salience": salience,
        "category": gai_fields.get("category") or gai_fields.get("Category"),
        "subcategory": gai_fields.get("subcategory") or gai_fields.get("Subcategory"),
        "initiating_country": gai_fields.get("initiating-country") or gai_fields.get("Initiating_Country"),
        "recipient_country": gai_fields.get("recipient-country") or gai_fields.get("Recipient_Country"),
        "event_name": (
            gai_fields.get("event-name")
            or gai_fields.get("project-name")
            or gai_fields.get("projects")
        ),
        "location": gai_fields.get("location") or gai_fields.get("Location"),
        "lat_long": gai_fields.get("lat-long") or gai_fields.get("LAT_LONG"),
        "monetary_commitment": gai_fields.get("monetary-commitment") or gai_fields.get("Monetary_Commitment"),
        "distilled_text": (
            gai_fields.get("distilled-text")
            or gai_fields.get("Distilled_Text")
            or gai_fields.get("distilled_text")
        ),
        # body_text is attached later via the ATOM CSV index (--body-csv)
        "body_text": None,
        # Full mapping retained for debug dump.
        "_gai_fields": gai_fields,
    }


def _download_s3_csvs(s3_uri: str, dest_dir: Path) -> List[Path]:
    """Download every .csv under s3://bucket/prefix/ to dest_dir. Returns local paths."""
    import boto3

    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got {s3_uri!r}")
    rest = s3_uri[5:]
    bucket, _, prefix = rest.partition("/")
    if not bucket:
        raise ValueError(f"Could not parse bucket from {s3_uri!r}")

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    downloaded: List[Path] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if not key.lower().endswith(".csv"):
                continue
            local = dest_dir / Path(key).name
            print(f"  [body-csv] downloading s3://{bucket}/{key} -> {local.name}")
            s3.download_file(bucket, key, str(local))
            downloaded.append(local)
    return downloaded


def load_body_csv_index(csv_paths: List[str]) -> Dict[str, Tuple[str, str]]:
    """Load ATOM CSV(s) and return {doc_id -> (body_text, source_csv_filename)}.

    Tracks which CSV provided each body so batch mode can route output to a
    JSONL named after the source CSV.

    Accepts local files, local directories, or s3://bucket/prefix/ URIs.
    Tries utf-8-sig then latin-1 (matches services/pipeline/ingestion/atom.py).
    Column name candidates:
      doc id: 'ATOM ID', 'atom_id', 'doc_id'
      body:   'Body', 'BODY', 'body'
    """
    import pandas as pd
    import tempfile

    expanded: List[Path] = []
    tmp_dir_obj = None
    for p in csv_paths:
        if isinstance(p, str) and p.startswith("s3://"):
            if tmp_dir_obj is None:
                tmp_dir_obj = tempfile.TemporaryDirectory(prefix="atom_csv_")
            expanded.extend(_download_s3_csvs(p, Path(tmp_dir_obj.name)))
            continue
        path = Path(p)
        if path.is_dir():
            expanded.extend(sorted(path.glob("*.csv")))
        else:
            expanded.append(path)

    if not expanded:
        return {}

    id_cols = ("ATOM ID", "atom_id", "doc_id")
    body_cols = ("Body", "BODY", "body")
    index: Dict[str, Tuple[str, str]] = {}

    for path in expanded:
        try:
            df = pd.read_csv(path, engine="python", on_bad_lines="skip", encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(path, engine="python", on_bad_lines="skip", encoding="latin-1")

        id_col = next((c for c in id_cols if c in df.columns), None)
        body_col = next((c for c in body_cols if c in df.columns), None)
        if not id_col or not body_col:
            print(f"  [WARN] {path.name}: missing id or body column "
                  f"(id_col={id_col!r}, body_col={body_col!r}, columns={list(df.columns)[:10]}...)")
            continue

        df = df.dropna(subset=[id_col, body_col])
        added = 0
        for _, row in df.iterrows():
            doc_id = str(row[id_col]).strip()
            body = str(row[body_col]).strip()
            if doc_id and body and doc_id not in index:
                index[doc_id] = (body, path.name)
                added += 1
        print(f"  [body-csv] {path.name}: +{added} bodies (total {len(index)})")

    return index


def _summarize_keys(obj: Any, depth: int = 0, max_depth: int = 3, max_items: int = 6) -> Any:
    """Return a shape-only summary of a nested JSON structure for inspection."""
    if depth >= max_depth:
        return f"<{type(obj).__name__}>"
    if isinstance(obj, dict):
        out = {}
        for k in list(obj.keys())[:max_items]:
            out[k] = _summarize_keys(obj[k], depth + 1, max_depth, max_items)
        if len(obj) > max_items:
            out["...truncated..."] = f"{len(obj) - max_items} more keys"
        return out
    if isinstance(obj, list):
        return [_summarize_keys(obj[i], depth + 1, max_depth, max_items)
                for i in range(min(len(obj), 3))] + ([f"...+{len(obj) - 3}"] if len(obj) > 3 else [])
    if isinstance(obj, str):
        return f"<str len={len(obj)} sample={obj[:80]!r}>"
    return obj


def inspect_doc(s3_prefix: str, specific_files: Optional[List[str]], n: int):
    if specific_files:
        key = f"{s3_prefix}{specific_files[0]}"
    else:
        files = list_s3_json_files(s3_prefix=s3_prefix)
        if not files:
            print("No S3 files found.")
            return
        key = files[0]["key"]
    print(f"Inspecting doc #{n} in {key}")
    payload = download_s3_json_file(key)
    if not isinstance(payload, list) or n >= len(payload):
        print(f"  Bad payload or N={n} out of range (file has {len(payload) if isinstance(payload, list) else '?'} docs)")
        return
    raw = payload[n]
    print(f"\nTop-level keys: {list(raw.keys())}")
    print("\nStructure summary (depth=3):")
    print(json.dumps(_summarize_keys(raw, max_depth=3), indent=2, default=str))

    parsed = parse_dsr_doc_minimal(raw)
    if parsed:
        print(f"\nMinimal-parsed doc_id: {parsed.get('doc_id')}")
        print("Body text is NOT embedded in DSR JSON for this dataset - "
              "load it from the ATOM CSV via --body-csv.")


def _parse_date(raw: Optional[str]) -> Optional[DateType]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def rejection_reason(doc: Dict[str, Any], initiators, recipients, start_date, end_date) -> Optional[str]:
    """Return None if doc passes filters, else a short reason string.

    `initiators` and `recipients` may be None (no filter), a single string, or a
    list/set of strings. Match is case-insensitive; any-part match for semicolon
    -separated DSR values is sufficient.
    """
    sal = (doc.get("salience") or "").upper()
    if sal != "TRUE":
        return f"salience={sal or 'MISSING'}"
    if not doc.get("distilled_text"):
        return "no_distilled_text"
    if initiators and not _country_matches(doc.get("initiating_country"), initiators):
        return f"initiating_country={doc.get('initiating_country')!r}"
    if recipients and not _country_matches(doc.get("recipient_country"), recipients):
        return f"recipient_country={doc.get('recipient_country')!r}"
    d = doc.get("date")
    if start_date and (d is None or d < start_date):
        return f"date={d}<start"
    if end_date and (d is None or d > end_date):
        return f"date={d}>end"
    return None


def _country_matches(field_value: Optional[str], wanted) -> bool:
    """DSR initiating/recipient fields can be semicolon-separated lists.

    `wanted` is either a string or an iterable of strings; the field qualifies
    if ANY semicolon-split part case-insensitively equals ANY wanted value.
    """
    if not field_value or not wanted:
        return False
    parts = {p.strip().lower() for p in field_value.split(";")}
    if isinstance(wanted, str):
        return wanted.lower() in parts
    wanted_set = {w.lower() for w in wanted}
    return bool(parts & wanted_set)


def load_country_lists_from_config() -> Tuple[List[str], List[str]]:
    """Return (influencers, recipients) from shared/config/config.yaml."""
    import yaml
    config_path = project_root / "shared" / "config" / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return list(cfg.get("influencers") or []), list(cfg.get("recipients") or [])


def scan_processed_doc_ids(output_dir: Path) -> Set[str]:
    """Walk every *.jsonl under output_dir and return the set of doc_ids already written."""
    processed: Set[str] = set()
    if not output_dir.exists():
        return processed
    for jsonl in sorted(output_dir.glob("*.jsonl")):
        with jsonl.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                did = rec.get("doc_id")
                if did:
                    processed.add(did)
    return processed


def iter_eligible_docs(s3_prefix, specific_files, initiators, recipients,
                       start_date, end_date, limit, debug_sample=0, debug_dump_path=None,
                       skip_doc_ids: Optional[Set[str]] = None,
                       filename_contains: Optional[List[str]] = None,
                       worker_id: int = 0, worker_count: int = 1):
    """Stream parsed+filtered DSR docs from S3 until limit is reached.

    initiators / recipients can be None, a single string, or a list.
    skip_doc_ids: doc_ids that should be skipped (already processed; resume mode).
    filename_contains: prune S3 file list to those whose name contains any pattern
        (case-insensitive). Cheap way to avoid downloading 90 files when you only
        want a date range, e.g. ["2026"].
    worker_id / worker_count: deterministic partitioning for concurrent runs.
        When worker_count > 1, a doc is yielded only if
        md5(doc_id) % worker_count == worker_id.
    """
    skip_doc_ids = skip_doc_ids or set()
    if specific_files:
        files = [{"key": f"{s3_prefix}{fn}", "filename": fn} for fn in specific_files]
    else:
        files = list_s3_json_files(s3_prefix=s3_prefix)
    if filename_contains:
        patterns_lc = [p.lower() for p in filename_contains]
        before = len(files)
        files = [f for f in files if any(p in f["filename"].lower() for p in patterns_lc)]
        print(f"Filename filter {filename_contains}: {before} -> {len(files)} files")

    print(f"Scanning {len(files)} S3 file(s) for eligible docs (limit={limit})")

    counters = {
        "docs_seen": 0,
        "unparseable": 0,
        "rejected": {},   # reason_key -> count
        "eligible": 0,
    }
    debug_samples: List[Dict[str, Any]] = []
    seen_country_values: Dict[str, int] = {}
    seen_recipient_values: Dict[str, int] = {}
    seen_salience_values: Dict[str, int] = {}
    seen_gai_type_keys: Dict[str, int] = {}

    yielded = 0
    for fi in files:
        if yielded >= limit:
            break
        try:
            payload = download_s3_json_file(fi["key"])
        except Exception as e:
            print(f"  [WARN] failed to download {fi['key']}: {e}")
            continue

        if not isinstance(payload, list):
            print(f"  [WARN] unexpected payload shape in {fi['filename']} (not a list); skipping")
            continue

        file_yielded = 0
        for raw in payload:
            if yielded >= limit:
                break
            counters["docs_seen"] += 1
            parsed = parse_dsr_doc_minimal(raw)
            if parsed is None or not parsed.get("doc_id"):
                counters["unparseable"] += 1
                continue

            if parsed["doc_id"] in skip_doc_ids:
                counters["rejected"]["already_processed"] = counters["rejected"].get("already_processed", 0) + 1
                continue

            if worker_count > 1:
                import hashlib as _hl
                h = int(_hl.md5(parsed["doc_id"].encode("utf-8")).hexdigest()[:8], 16)
                if h % worker_count != worker_id:
                    counters["rejected"]["other_worker"] = counters["rejected"].get("other_worker", 0) + 1
                    continue

            # Track seen values regardless of filter result (helps diagnose mismatches)
            ic = parsed.get("initiating_country")
            if ic:
                seen_country_values[ic] = seen_country_values.get(ic, 0) + 1
            rc = parsed.get("recipient_country")
            if rc:
                seen_recipient_values[rc] = seen_recipient_values.get(rc, 0) + 1
            sal_key = parsed.get("salience") if parsed.get("salience") is not None else "<MISSING>"
            seen_salience_values[sal_key] = seen_salience_values.get(sal_key, 0) + 1
            for k in (parsed.get("_gai_fields") or {}).keys():
                seen_gai_type_keys[k] = seen_gai_type_keys.get(k, 0) + 1

            reason = rejection_reason(parsed, initiators, recipients, start_date, end_date)

            if len(debug_samples) < debug_sample:
                debug_samples.append({
                    "_source_s3_file": fi["filename"],
                    "rejection_reason": reason,
                    "parsed": parsed,
                })

            if reason is not None:
                reason_key = reason.split("=", 1)[0]
                counters["rejected"][reason_key] = counters["rejected"].get(reason_key, 0) + 1
                continue

            parsed["_source_s3_file"] = fi["filename"]
            parsed.pop("_gai_fields", None)  # not needed downstream of filter
            counters["eligible"] += 1
            yield parsed
            yielded += 1
            file_yielded += 1
        print(f"  {fi['filename']}: {file_yielded} eligible (running total {yielded}/{limit})")

    # Print summary diagnostics
    print("\n--- Filter diagnostics ---")
    print(f"  docs_seen:    {counters['docs_seen']}")
    print(f"  unparseable:  {counters['unparseable']}")
    print(f"  eligible:     {counters['eligible']}")
    if counters["rejected"]:
        print("  rejected by reason:")
        for k, v in sorted(counters["rejected"].items(), key=lambda x: -x[1]):
            print(f"    {k}: {v}")
    if seen_salience_values:
        print("  salience values seen (across all docs):")
        for k, v in sorted(seen_salience_values.items(), key=lambda x: -x[1]):
            print(f"    {v:>5}  {k!r}")
    if seen_gai_type_keys:
        top = sorted(seen_gai_type_keys.items(), key=lambda x: -x[1])[:25]
        print("  top gai type keys seen (raw):")
        for k, v in top:
            print(f"    {v:>5}  {k!r}")
    if seen_country_values:
        top = sorted(seen_country_values.items(), key=lambda x: -x[1])[:10]
        print("  top initiating_country values seen:")
        for k, v in top:
            print(f"    {v:>5}  {k!r}")
    if seen_recipient_values:
        top = sorted(seen_recipient_values.items(), key=lambda x: -x[1])[:10]
        print("  top recipient_country values seen:")
        for k, v in top:
            print(f"    {v:>5}  {k!r}")

    if debug_dump_path and debug_samples:
        Path(debug_dump_path).parent.mkdir(parents=True, exist_ok=True)
        with open(debug_dump_path, "w") as f:
            json.dump({
                "counters": counters,
                "seen_initiating_country": seen_country_values,
                "seen_recipient_country": seen_recipient_values,
                "seen_salience_values": seen_salience_values,
                "seen_gai_type_keys": seen_gai_type_keys,
                "samples": debug_samples,
            }, f, indent=2, default=str)
        print(f"  debug sample written: {debug_dump_path}")


def parse_llm_output(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list) and raw:
        return raw[0] if isinstance(raw[0], dict) else None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            objs = find_json_objects(raw)
            return objs[0] if objs else None
    return None


def extract_propositions(doc: Dict[str, Any], model: str, source: Optional[str] = None,
                         input_text_source: str = "distilled"):
    if input_text_source == "body":
        text = doc.get("body_text") or ""
        text_label = "body_text"
    else:
        text = doc.get("distilled_text") or ""
        text_label = "distilled_text"

    if not text:
        return None, f"empty_{text_label}"

    user_prompt = (
        f"doc_id: {doc['doc_id']}\n"
        f"date: {doc.get('date')}\n"
        f"title: {doc.get('title')}\n"
        f"doc_initiating_country: {doc.get('initiating_country')}\n"
        f"doc_recipient_country: {doc.get('recipient_country')}\n"
        f"{text_label}:\n{text}"
    )
    gai_kwargs = {"model": model}
    if source:
        gai_kwargs["source"] = source
    try:
        raw = gai(proposition_extraction_prompt, user_prompt, **gai_kwargs)
    except Exception as e:
        return None, f"llm_call_failed: {type(e).__name__}: {e}"

    parsed = parse_llm_output(raw)
    if parsed is None:
        return None, f"unparseable_output: {str(raw)[:300]}"
    return parsed, None


def _parse_cli_date(s: Optional[str]) -> Optional[DateType]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s3-prefix", default="dsr_extracts/")
    ap.add_argument("--s3-files", nargs="+", help="Specific filenames within --s3-prefix")
    ap.add_argument("--filename-contains", nargs="+", default=None,
                    help="Only download S3 files whose name (case-insensitive) contains ANY of "
                         "these substrings. Example: --filename-contains 2026 Mar2026.")
    ap.add_argument("--country", help="Single initiating country filter (shortcut for --initiators X)")
    ap.add_argument("--recipient", help="Single recipient country filter (shortcut for --recipients X)")
    ap.add_argument("--initiators", help="Comma-separated initiator allowlist (defaults to config influencers)")
    ap.add_argument("--recipients", help="Comma-separated recipient allowlist (defaults to config recipients)")
    ap.add_argument("--no-config-filter", action="store_true",
                    help="Disable the default config-driven initiator/recipient filter")
    ap.add_argument("--start", dest="start_date", help="YYYY-MM-DD")
    ap.add_argument("--end", dest="end_date", help="YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=50,
                    help="Cap on docs to process this run (use a high value for batch mode)")
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--gai-source", default=None,
                    choices=["proxy", "litellm", "azure", "openai"],
                    help="Override gai() backend (otherwise uses GAI_DEFAULT_SOURCE env var)")
    out_group = ap.add_mutually_exclusive_group(required=True)
    out_group.add_argument("--output", help="Single JSON-array file (small-run / pilot mode)")
    out_group.add_argument("--output-dir", help="Directory for JSONL-per-source-CSV batch mode")
    ap.add_argument("--resume", action="store_true",
                    help="(batch mode) Skip doc_ids already present in --output-dir/*.jsonl")
    ap.add_argument("--worker-id", type=int, default=0,
                    help="0-based index of this worker (use with --worker-count for safe concurrency)")
    ap.add_argument("--worker-count", type=int, default=1,
                    help="Total concurrent workers; each worker processes docs where "
                         "md5(doc_id) %% worker_count == worker_id and writes to JSONL "
                         "files suffixed with .worker_<id> so they never collide.")
    ap.add_argument("--debug-sample", type=int, default=0,
                    help="Dump the first N parsed docs (passed or rejected) for inspection")
    ap.add_argument("--debug-dump", default=None,
                    help="Path for debug sample JSON (defaults next to --output)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Scan and filter only; do not call the LLM")
    ap.add_argument("--inspect-doc", type=int, default=None, metavar="N",
                    help="Dump the JSON structure of the Nth doc in the first S3 file and exit. "
                         "Use to discover where the full body text lives.")
    ap.add_argument("--input-text", choices=["distilled", "body", "both"], default="distilled",
                    help="Which text to feed the LLM. 'both' runs each doc twice for A/B comparison.")
    ap.add_argument("--body-csv", nargs="+", default=None,
                    help="One or more ATOM CSV sources: local file, local directory, or "
                         "s3://bucket/prefix/. Required for --input-text body|both. "
                         "Looks up by ATOM ID column.")
    args = ap.parse_args()

    if args.worker_count < 1 or args.worker_id < 0 or args.worker_id >= args.worker_count:
        ap.error(f"Invalid worker config: worker_id={args.worker_id}, worker_count={args.worker_count}. "
                 f"Require worker_count >= 1 and 0 <= worker_id < worker_count.")

    batch_mode = bool(args.output_dir)
    out_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    if batch_mode:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    start_d = _parse_cli_date(args.start_date)
    end_d = _parse_cli_date(args.end_date)

    if args.inspect_doc is not None:
        inspect_doc(args.s3_prefix, args.s3_files, args.inspect_doc)
        return

    # Resolve initiator/recipient filters: explicit CLI > config defaults.
    initiators: Optional[List[str]] = None
    recipients: Optional[List[str]] = None
    if args.country:
        initiators = [args.country]
    elif args.initiators:
        initiators = [c.strip() for c in args.initiators.split(",") if c.strip()]
    if args.recipient:
        recipients = [args.recipient]
    elif args.recipients:
        recipients = [c.strip() for c in args.recipients.split(",") if c.strip()]
    if initiators is None and recipients is None and not args.no_config_filter:
        initiators, recipients = load_country_lists_from_config()
        print(f"Filters from config.yaml: {len(initiators)} initiators, {len(recipients)} recipients")

    bucket = get_bucket_name()
    print(f"Bucket: {bucket}  Prefix: {args.s3_prefix}")
    print(f"Filters: initiators={initiators}  recipients={recipients}  "
          f"dates={args.start_date}..{args.end_date}  limit={args.limit}")
    if args.worker_count > 1:
        print(f"Worker: {args.worker_id}/{args.worker_count} "
              f"(processes docs where md5(doc_id) %% {args.worker_count} == {args.worker_id})")
    print(f"Mode: {'batch (--output-dir)' if batch_mode else 'single-file (--output)'}  "
          f"input_text={args.input_text}")

    effective_source = args.gai_source or os.getenv("GAI_DEFAULT_SOURCE", "proxy")
    print(f"GAI backend: {effective_source}", end="")
    if effective_source == "litellm":
        url_set = bool(os.getenv("LITELLM_URL"))
        key_set = bool(os.getenv("LITELLM_API_KEY"))
        model_env = os.getenv("LITELLM_MODEL")
        print(f"  LITELLM_URL={'set' if url_set else 'MISSING'} "
              f"LITELLM_API_KEY={'set' if key_set else 'MISSING'} "
              f"LITELLM_MODEL={model_env or '(falls back to --model)'}")
    else:
        print()

    # Resume set (batch mode)
    skip_doc_ids: Set[str] = set()
    if batch_mode and args.resume:
        skip_doc_ids = scan_processed_doc_ids(output_dir)
        print(f"Resume: {len(skip_doc_ids)} doc_ids already in {output_dir}; will skip")

    debug_dump_path = args.debug_dump
    if args.debug_sample and not debug_dump_path and out_path is not None:
        debug_dump_path = str(out_path.with_name(out_path.stem + "_debug.json"))

    docs = list(iter_eligible_docs(
        s3_prefix=args.s3_prefix,
        specific_files=args.s3_files,
        initiators=initiators,
        recipients=recipients,
        start_date=start_d,
        end_date=end_d,
        limit=args.limit,
        debug_sample=args.debug_sample,
        debug_dump_path=debug_dump_path,
        skip_doc_ids=skip_doc_ids,
        filename_contains=args.filename_contains,
        worker_id=args.worker_id,
        worker_count=args.worker_count,
    ))

    if not docs:
        print("No eligible documents found. Exiting.")
        return

    sources_to_run = (["distilled", "body"] if args.input_text == "both" else [args.input_text])

    # Body CSV index (also gives us source filename for output routing).
    # Do this BEFORE the dry-run check so the dry-run reports body match coverage,
    # which is the most important pre-flight signal for batch-mode body runs.
    body_index: Dict[str, Tuple[str, str]] = {}
    if "body" in sources_to_run:
        if not args.body_csv:
            print("ERROR: --input-text body|both requires --body-csv pointing to ATOM CSV file(s).")
            return
        print(f"Loading body text from CSV: {args.body_csv}")
        body_index = load_body_csv_index(args.body_csv)
        print(f"  body index size: {len(body_index)}")
        matched = 0
        for d in docs:
            entry = body_index.get(d["doc_id"])
            if entry:
                d["body_text"], d["_body_csv"] = entry
                matched += 1
        print(f"  body_text matched on {matched}/{len(docs)} eligible docs")
        if matched == 0:
            print("  WARNING: no doc_ids matched the CSV index. Sample doc_id: "
                  f"{docs[0]['doc_id'] if docs else 'n/a'}")

    if args.dry_run:
        print(f"\n[dry-run] Would extract from {len(docs)} docs. Skipping LLM calls.")
        return

    # In batch mode with body source, skip docs whose body wasn't found.
    if batch_mode and args.input_text in ("body", "both"):
        before = len(docs)
        docs = [d for d in docs if d.get("body_text")]
        skipped = before - len(docs)
        if skipped:
            print(f"  skipping {skipped} docs with no body match (batch mode)")

    if not docs:
        print("Nothing to process after body match. Exiting.")
        return

    print(f"\nExtracting propositions from {len(docs)} docs via {args.model}...")
    stats: Dict[str, Any] = {
        "docs_processed": 0,
        "docs_with_propositions": 0,
        "docs_failed": 0,
        "total_propositions": 0,
        "errors": [],
    }
    started = time.time()
    consecutive_failures = 0
    FAIL_FAST_THRESHOLD = 3
    records: List[Dict[str, Any]] = []  # only used in single-file mode
    open_files: Dict[str, Any] = {}     # csv_filename -> open file handle (batch mode)

    def get_output_handle(source_csv: Optional[str]):
        """Return a file handle in append mode for the given source CSV.

        With concurrency, each worker writes to a worker-specific JSONL so two
        workers never share a write target.
        """
        base = (source_csv or "unknown").replace(".csv", "")
        if args.worker_count > 1:
            base += f".worker_{args.worker_id}"
        key = base + ".propositions.jsonl"
        if key not in open_files:
            open_files[key] = (output_dir / key).open("a")
        return open_files[key]

    try:
        for i, doc in enumerate(docs, 1):
            print(f"[{i}/{len(docs)}] {doc['doc_id']} ({doc.get('date')})", flush=True)

            record = {
                "doc_id": doc["doc_id"],
                "doc_date": str(doc.get("date")) if doc.get("date") else None,
                "doc_title": doc.get("title"),
                "doc_initiating_country": doc.get("initiating_country"),
                "doc_recipient_country": doc.get("recipient_country"),
                "doc_event_name": doc.get("event_name"),
                "source_s3_file": doc.get("_source_s3_file"),
                "source_body_csv": doc.get("_body_csv"),
                "extractor_model": args.model,
                "extractor_version": PROPOSITION_PROMPT_VERSION,
                "extracted_at": datetime.utcnow().isoformat(),
                "runs": {},
            }
            stats["docs_processed"] += 1

            any_propositions = False
            for src in sources_to_run:
                print(f"    [{src}]", flush=True)
                parsed, err = extract_propositions(doc, args.model, source=args.gai_source,
                                                   input_text_source=src)
                run_entry: Dict[str, Any] = {
                    "input_text_source": src,
                    "input_text_chars": len(
                        (doc.get("body_text") if src == "body" else doc.get("distilled_text")) or ""
                    ),
                }
                if err:
                    print(f"      ERROR: {err}", flush=True)
                    consecutive_failures += 1
                    run_entry["error"] = err
                    run_entry["propositions"] = []
                    stats["errors"].append({"doc_id": doc["doc_id"], "source": src, "error": err})
                else:
                    consecutive_failures = 0
                    props = parsed.get("propositions", []) if isinstance(parsed, dict) else []
                    run_entry["propositions"] = props
                    run_entry["proposition_count"] = len(props)
                    stats["total_propositions"] += len(props)
                    if props:
                        any_propositions = True
                record["runs"][src] = run_entry

            if not any_propositions:
                stats["docs_failed"] += 1
            else:
                stats["docs_with_propositions"] += 1

            if batch_mode:
                fh = get_output_handle(doc.get("_body_csv"))
                fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
                fh.flush()
            else:
                records.append(record)

            if consecutive_failures >= FAIL_FAST_THRESHOLD and i < len(docs):
                print(f"\nAborting: {consecutive_failures} consecutive LLM failures. "
                      f"Fix the gai backend (see --gai-source / GAI_DEFAULT_SOURCE) and retry.",
                      flush=True)
                break
    finally:
        for fh in open_files.values():
            fh.close()

    elapsed = time.time() - started
    stats["elapsed_seconds"] = round(elapsed, 1)
    stats["bucket"] = bucket
    stats["s3_prefix"] = args.s3_prefix

    if batch_mode:
        stats["output_dir"] = str(output_dir)
        stats["output_files"] = sorted(open_files.keys())
        summary_path = output_dir / f"_run_summary_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json"
        with summary_path.open("w") as f:
            json.dump(stats, f, indent=2)
    else:
        with out_path.open("w") as f:
            json.dump(records, f, indent=2, default=str, ensure_ascii=False)
            f.write("\n")
        stats["output_file"] = str(out_path)
        summary_path = out_path.with_name(out_path.stem + "_summary.json")
        with summary_path.open("w") as f:
            json.dump(stats, f, indent=2)

    print(f"\nDone in {elapsed:.1f}s")
    print(f"  docs_processed:         {stats['docs_processed']}")
    print(f"  docs_with_propositions: {stats['docs_with_propositions']}")
    print(f"  docs_failed:            {stats['docs_failed']}")
    print(f"  total_propositions:     {stats['total_propositions']}")
    if not batch_mode and args.input_text == "both":
        print("\n  per-doc proposition counts (distilled vs body):")
        print(f"  {'doc_id':<40}  {'distilled':>10}  {'body':>10}  {'delta':>6}")
        for rec in records:
            runs = rec.get("runs", {})
            d = runs.get("distilled", {}).get("proposition_count", 0)
            b = runs.get("body", {}).get("proposition_count", 0)
            print(f"  {rec['doc_id']:<40}  {d:>10}  {b:>10}  {b - d:>+6}")
    if batch_mode:
        print(f"\n  output_dir: {output_dir}")
        for fn in sorted(open_files.keys()):
            print(f"    {fn}")
    else:
        print(f"\n  output:  {out_path}")
    print(f"  summary: {summary_path}")


if __name__ == "__main__":
    main()
