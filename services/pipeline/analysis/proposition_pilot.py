"""Proposition extraction pilot - reads DSR JSON from S3, writes JSONL.

Standalone, no DB writes. Uses the same S3 helpers as dsr.py and applies
salience/country/date filters in-memory before running the extraction
prompt. The processed-files tracker is NOT updated (read-only pilot).

Usage:
  python services/pipeline/analysis/proposition_pilot.py \
      --country China --recipient Egypt \
      --start 2024-08-01 --end 2024-08-31 \
      --limit 50 \
      --output pilot_outputs/china_egypt_aug24.jsonl

  # Restrict to a known set of S3 files:
  python services/pipeline/analysis/proposition_pilot.py \
      --s3-files chunk_2024-08-01.json chunk_2024-08-02.json \
      --limit 20 --output pilot_outputs/aug_first_two.jsonl

S3 bucket comes from the project's config (S3_BUCKET env var or
shared/config/config.yaml). Default prefix is dsr_extracts/.
"""
import argparse
import json
import time
from datetime import datetime, date as DateType
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# DSR docs encode soft-power fields as typed responses inside
# auto.gai[1].value = [{type: "salience", value: "TRUE"}, {type: "distilled-text", value: "..."}, ...]
RELEVANT_TYPES = {
    "salience",
    "salience-justification",
    "category",
    "category-justification",
    "subcategory",
    "initiating-country",
    "recipient-country",
    "project-name",
    "event-name",
    "projects",
    "location",
    "lat-long",
    "monetary-commitment",
    "distilled-text",
}


def _normalize(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in {"", "n/a", "na", "none", "null", "n/a."}:
        return None
    return s


def parse_dsr_doc_minimal(dsr_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull only the fields the pilot needs from a raw DSR doc."""
    auto = dsr_doc.get("auto") or {}
    gai_list = auto.get("gai") or []
    if len(gai_list) < 2:
        return None
    gai_block = gai_list[1] or {}

    fields: Dict[str, Optional[str]] = {t: None for t in RELEVANT_TYPES}
    for response in gai_block.get("value", []) or []:
        rtype = response.get("type")
        if rtype in RELEVANT_TYPES:
            fields[rtype] = _normalize(response.get("value"))

    mt = dsr_doc.get("machineTranslations") or {}
    title_translation = (mt.get("title_title") or {}).get("text")
    title = title_translation or (dsr_doc.get("title") or {}).get("title")

    start_date_raw = (dsr_doc.get("source") or {}).get("startDate")
    doc_date = _parse_date(start_date_raw)

    return {
        "doc_id": dsr_doc.get("id"),
        "title": title,
        "date": doc_date,
        "source_name": ((dsr_doc.get("source") or {}).get("name") or {}).get("transliterated"),
        "salience": fields["salience"],
        "category": fields["category"],
        "subcategory": fields["subcategory"],
        "initiating_country": fields["initiating-country"],
        "recipient_country": fields["recipient-country"],
        "event_name": fields["event-name"] or fields["project-name"] or fields["projects"],
        "location": fields["location"],
        "lat_long": fields["lat-long"],
        "monetary_commitment": fields["monetary-commitment"],
        "distilled_text": fields["distilled-text"],
    }


def _parse_date(raw: Optional[str]) -> Optional[DateType]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def matches_filters(doc: Dict[str, Any], country, recipient, start_date, end_date) -> bool:
    if (doc.get("salience") or "").upper() != "TRUE":
        return False
    if not doc.get("distilled_text"):
        return False
    if country and not _country_matches(doc.get("initiating_country"), country):
        return False
    if recipient and not _country_matches(doc.get("recipient_country"), recipient):
        return False
    d = doc.get("date")
    if start_date and (d is None or d < start_date):
        return False
    if end_date and (d is None or d > end_date):
        return False
    return True


def _country_matches(field_value: Optional[str], wanted: str) -> bool:
    """DSR initiating/recipient fields can be semicolon-separated lists."""
    if not field_value:
        return False
    parts = [p.strip().lower() for p in field_value.split(";")]
    return wanted.lower() in parts


def iter_eligible_docs(s3_prefix, specific_files, country, recipient, start_date, end_date, limit):
    """Stream parsed+filtered DSR docs from S3 until limit is reached."""
    if specific_files:
        files = [{"key": f"{s3_prefix}{fn}", "filename": fn} for fn in specific_files]
    else:
        files = list_s3_json_files(s3_prefix=s3_prefix)

    print(f"Scanning {len(files)} S3 file(s) for eligible docs (limit={limit})")

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
            parsed = parse_dsr_doc_minimal(raw)
            if parsed is None or not parsed.get("doc_id"):
                continue
            if not matches_filters(parsed, country, recipient, start_date, end_date):
                continue
            parsed["_source_s3_file"] = fi["filename"]
            yield parsed
            yielded += 1
            file_yielded += 1
        print(f"  {fi['filename']}: {file_yielded} eligible (running total {yielded}/{limit})")


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


def extract_propositions(doc: Dict[str, Any], model: str):
    user_prompt = (
        f"doc_id: {doc['doc_id']}\n"
        f"date: {doc.get('date')}\n"
        f"title: {doc.get('title')}\n"
        f"doc_initiating_country: {doc.get('initiating_country')}\n"
        f"doc_recipient_country: {doc.get('recipient_country')}\n"
        f"distilled_text:\n{doc['distilled_text']}"
    )
    try:
        raw = gai(proposition_extraction_prompt, user_prompt, model=model)
    except Exception as e:
        return None, f"llm_call_failed: {e}"

    parsed = parse_llm_output(raw)
    if parsed is None:
        return None, f"unparseable_output: {str(raw)[:200]}"
    return parsed, None


def _parse_cli_date(s: Optional[str]) -> Optional[DateType]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s3-prefix", default="dsr_extracts/")
    ap.add_argument("--s3-files", nargs="+", help="Specific filenames within --s3-prefix")
    ap.add_argument("--country", help="Initiating country filter")
    ap.add_argument("--recipient", help="Recipient country filter")
    ap.add_argument("--start", dest="start_date", help="YYYY-MM-DD")
    ap.add_argument("--end", dest="end_date", help="YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    start_d = _parse_cli_date(args.start_date)
    end_d = _parse_cli_date(args.end_date)

    bucket = get_bucket_name()
    print(f"Bucket: {bucket}  Prefix: {args.s3_prefix}")
    print(f"Filters: country={args.country} recipient={args.recipient} "
          f"dates={args.start_date}..{args.end_date} limit={args.limit}")

    docs = list(iter_eligible_docs(
        s3_prefix=args.s3_prefix,
        specific_files=args.s3_files,
        country=args.country,
        recipient=args.recipient,
        start_date=start_d,
        end_date=end_d,
        limit=args.limit,
    ))

    if not docs:
        print("No eligible documents found. Exiting.")
        return

    print(f"\nExtracting propositions from {len(docs)} docs via {args.model}...")
    stats = {
        "docs_processed": 0,
        "docs_with_propositions": 0,
        "docs_failed": 0,
        "total_propositions": 0,
        "errors": [],
    }
    started = time.time()

    with out_path.open("w") as f:
        for i, doc in enumerate(docs, 1):
            print(f"[{i}/{len(docs)}] {doc['doc_id']} ({doc.get('date')})", flush=True)
            parsed, err = extract_propositions(doc, args.model)
            stats["docs_processed"] += 1

            record = {
                "doc_id": doc["doc_id"],
                "doc_date": str(doc.get("date")) if doc.get("date") else None,
                "doc_title": doc.get("title"),
                "doc_initiating_country": doc.get("initiating_country"),
                "doc_recipient_country": doc.get("recipient_country"),
                "doc_category": doc.get("category"),
                "doc_subcategory": doc.get("subcategory"),
                "doc_event_name": doc.get("event_name"),
                "source_s3_file": doc.get("_source_s3_file"),
                "extractor_model": args.model,
                "extractor_version": PROPOSITION_PROMPT_VERSION,
                "extracted_at": datetime.utcnow().isoformat(),
            }

            if err:
                stats["docs_failed"] += 1
                stats["errors"].append({"doc_id": doc["doc_id"], "error": err})
                record["error"] = err
                record["propositions"] = []
            else:
                props = parsed.get("propositions", []) if isinstance(parsed, dict) else []
                record["propositions"] = props
                stats["total_propositions"] += len(props)
                if props:
                    stats["docs_with_propositions"] += 1

            f.write(json.dumps(record, default=str) + "\n")

    elapsed = time.time() - started
    summary_path = out_path.with_name(out_path.stem + "_summary.json")
    stats["elapsed_seconds"] = round(elapsed, 1)
    stats["bucket"] = bucket
    stats["s3_prefix"] = args.s3_prefix
    stats["output_file"] = str(out_path)
    with summary_path.open("w") as f:
        json.dump(stats, f, indent=2)

    print(f"\nDone in {elapsed:.1f}s")
    print(f"  docs_processed:         {stats['docs_processed']}")
    print(f"  docs_with_propositions: {stats['docs_with_propositions']}")
    print(f"  docs_failed:            {stats['docs_failed']}")
    print(f"  total_propositions:     {stats['total_propositions']}")
    print(f"  output:  {out_path}")
    print(f"  summary: {summary_path}")


if __name__ == "__main__":
    main()
