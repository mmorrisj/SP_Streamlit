"""Triage tool: walk every DSR JSON in s3://<bucket>/dsr_extracts/, apply the
soft-power country filters, and emit a JSON file of chunked ATOM search
hyperlinks for human review.

No LLM calls, no CSV lookup. Cheap to run.

Filters applied to each doc:
  1. salience-bool == TRUE
  2. initiating_country has at least one match in --initiators
     (defaults to config.yaml influencers)
  3. recipient_country has at least one match in --recipients
     (defaults to config.yaml recipients)
  4. Optional date range (--start / --end)
  5. Self-country skip: if SET of initiators == SET of recipients (e.g. Iran -> Iran),
     skip. Disabled with --allow-self-country.

Usage:
  python services/pipeline/analysis/dsr_hyperlinks.py \\
      --output triage/$(date +%Y%m%d)_hyperlinks.json

  python services/pipeline/analysis/dsr_hyperlinks.py \\
      --s3-files 28July_DSNR_EXTRACT.json \\
      --output triage/28july.json --include-titles
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, date as DateType
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

from services.pipeline.analysis.proposition_pilot import (
    parse_dsr_doc_minimal,
    load_country_lists_from_config,
    _country_matches,
)
from services.pipeline.embeddings.s3 import (
    list_s3_json_files,
    download_s3_json_file,
    get_bucket_name,
)
from shared.utils.citation_utils import build_hyperlinks_chunked


def _semicolon_set(field_value: Optional[str]) -> Set[str]:
    if not field_value:
        return set()
    return {p.strip().lower() for p in field_value.split(";") if p.strip()}


def _parse_cli_date(s: Optional[str]) -> Optional[DateType]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s3-prefix", default="dsr_extracts/")
    ap.add_argument("--s3-files", nargs="+",
                    help="Specific filenames within --s3-prefix (otherwise process all)")
    ap.add_argument("--filename-contains", nargs="+", default=None,
                    help="Only download S3 files whose name (case-insensitive) contains ANY of "
                         "these substrings. Example: --filename-contains 2026 Mar2026.")
    ap.add_argument("--initiators",
                    help="Comma-separated initiator allowlist (defaults to config influencers)")
    ap.add_argument("--recipients",
                    help="Comma-separated recipient allowlist (defaults to config recipients)")
    ap.add_argument("--no-config-filter", action="store_true",
                    help="Disable the default config-driven initiator/recipient filter")
    ap.add_argument("--allow-self-country", action="store_true",
                    help="Don't skip docs where initiator set equals recipient set (e.g. Iran->Iran)")
    ap.add_argument("--start", dest="start_date", help="YYYY-MM-DD")
    ap.add_argument("--end", dest="end_date", help="YYYY-MM-DD")
    ap.add_argument("--chunk-size", type=int, default=80,
                    help="Max doc_ids per ATOM hyperlink (default 80, ~3.7 KB for UUID ids)")
    ap.add_argument("--include-titles", action="store_true",
                    help="Include per-doc metadata (doc_id, title, date, countries) in the output")
    ap.add_argument("--output", required=True, help="Output JSON path")
    args = ap.parse_args()

    # Resolve filters
    initiators: Optional[List[str]] = None
    recipients: Optional[List[str]] = None
    if args.initiators:
        initiators = [c.strip() for c in args.initiators.split(",") if c.strip()]
    if args.recipients:
        recipients = [c.strip() for c in args.recipients.split(",") if c.strip()]
    if initiators is None and recipients is None and not args.no_config_filter:
        initiators, recipients = load_country_lists_from_config()
        print(f"Filters from config.yaml: {len(initiators)} initiators, {len(recipients)} recipients")

    start_d = _parse_cli_date(args.start_date)
    end_d = _parse_cli_date(args.end_date)

    bucket = get_bucket_name()
    print(f"Bucket: {bucket}  Prefix: {args.s3_prefix}")
    print(f"Filters: initiators={initiators}  recipients={recipients}  "
          f"dates={args.start_date}..{args.end_date}  "
          f"self_country_skip={not args.allow_self_country}")

    if args.s3_files:
        files = [{"key": f"{args.s3_prefix}{fn}", "filename": fn} for fn in args.s3_files]
    else:
        files = list_s3_json_files(s3_prefix=args.s3_prefix)
    if args.filename_contains:
        patterns_lc = [p.lower() for p in args.filename_contains]
        before = len(files)
        files = [f for f in files if any(p in f["filename"].lower() for p in patterns_lc)]
        print(f"Filename filter {args.filename_contains}: {before} -> {len(files)} files")
    print(f"Scanning {len(files)} S3 file(s)")

    counters = {
        "files_processed": 0,
        "docs_seen": 0,
        "unparseable": 0,
        "rejected": {},
        "eligible": 0,
    }
    eligible_ids: List[str] = []
    per_doc: List[Dict[str, Any]] = []
    per_file_counts: List[Dict[str, Any]] = []
    started = time.time()

    for fi in files:
        try:
            payload = download_s3_json_file(fi["key"])
        except Exception as e:
            print(f"  [WARN] failed to download {fi['key']}: {e}")
            continue

        if not isinstance(payload, list):
            print(f"  [WARN] unexpected payload in {fi['filename']}; skipping")
            continue

        counters["files_processed"] += 1
        file_eligible = 0

        for raw in payload:
            counters["docs_seen"] += 1
            parsed = parse_dsr_doc_minimal(raw)
            if parsed is None or not parsed.get("doc_id"):
                counters["unparseable"] += 1
                continue

            # Salience gate
            if (parsed.get("salience") or "").upper() != "TRUE":
                counters["rejected"]["salience"] = counters["rejected"].get("salience", 0) + 1
                continue

            # Country filters (skip if filter set and no match)
            if initiators and not _country_matches(parsed.get("initiating_country"), initiators):
                counters["rejected"]["initiating_country"] = counters["rejected"].get("initiating_country", 0) + 1
                continue
            if recipients and not _country_matches(parsed.get("recipient_country"), recipients):
                counters["rejected"]["recipient_country"] = counters["rejected"].get("recipient_country", 0) + 1
                continue

            # Self-country skip
            if not args.allow_self_country:
                init_set = _semicolon_set(parsed.get("initiating_country"))
                recip_set = _semicolon_set(parsed.get("recipient_country"))
                if init_set and recip_set and init_set == recip_set:
                    counters["rejected"]["self_country"] = counters["rejected"].get("self_country", 0) + 1
                    continue

            # Date range
            d = parsed.get("date")
            if start_d and (d is None or d < start_d):
                counters["rejected"]["date"] = counters["rejected"].get("date", 0) + 1
                continue
            if end_d and (d is None or d > end_d):
                counters["rejected"]["date"] = counters["rejected"].get("date", 0) + 1
                continue

            counters["eligible"] += 1
            file_eligible += 1
            eligible_ids.append(parsed["doc_id"])
            if args.include_titles:
                per_doc.append({
                    "doc_id": parsed["doc_id"],
                    "date": str(parsed["date"]) if parsed.get("date") else None,
                    "title": parsed.get("title"),
                    "initiating_country": parsed.get("initiating_country"),
                    "recipient_country": parsed.get("recipient_country"),
                    "category": parsed.get("category"),
                    "source_s3_file": fi["filename"],
                })

        per_file_counts.append({"s3_file": fi["filename"], "eligible": file_eligible})
        print(f"  {fi['filename']}: {file_eligible} eligible "
              f"(running total {counters['eligible']})")

    elapsed = time.time() - started

    hyperlinks = build_hyperlinks_chunked(eligible_ids, chunk_size=args.chunk_size)

    output = {
        "generated_at": datetime.utcnow().isoformat(),
        "bucket": bucket,
        "s3_prefix": args.s3_prefix,
        "initiators_used": initiators,
        "recipients_used": recipients,
        "allow_self_country": args.allow_self_country,
        "date_range": {"start": args.start_date, "end": args.end_date},
        "chunk_size": args.chunk_size,
        "filter_summary": counters,
        "elapsed_seconds": round(elapsed, 1),
        "files_processed": counters["files_processed"],
        "doc_count": len(eligible_ids),
        "hyperlink_count": len(hyperlinks),
        "hyperlinks": hyperlinks,
        "per_file_counts": per_file_counts,
    }
    if args.include_titles:
        output["docs"] = per_doc

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
        f.write("\n")

    print(f"\nDone in {elapsed:.1f}s")
    print(f"  files_processed: {counters['files_processed']}")
    print(f"  docs_seen:       {counters['docs_seen']}")
    print(f"  eligible:        {counters['eligible']}")
    print(f"  rejected by reason:")
    for k, v in sorted(counters["rejected"].items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")
    print(f"\n  hyperlinks generated: {len(hyperlinks)} (chunk_size={args.chunk_size})")
    print(f"  output: {out_path}")


if __name__ == "__main__":
    main()
