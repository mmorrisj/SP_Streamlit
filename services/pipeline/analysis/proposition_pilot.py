"""Proposition extraction pilot - standalone, writes JSONL, no DB writes.

Usage:
  python services/pipeline/analysis/proposition_pilot.py \
      --country China --recipient Egypt \
      --start 2024-08-01 --end 2024-08-31 \
      --limit 50 \
      --output pilot_outputs/propositions_china_egypt_aug24.jsonl
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import gai, find_json_objects
from shared.utils.prompts_proposition import (
    proposition_extraction_prompt,
    PROPOSITION_PROMPT_VERSION,
)


def fetch_documents(session, country, recipient, start_date, end_date, limit):
    """Pull pre-filtered soft-power docs for the requested slice."""
    sql = """
        SELECT DISTINCT d.doc_id, d.title, d.date, d.distilled_text,
               d.initiating_country, d.recipient_country, d.category, d.subcategory
        FROM documents d
        LEFT JOIN initiating_countries ic ON ic.doc_id = d.doc_id
        LEFT JOIN recipient_countries rc ON rc.doc_id = d.doc_id
        WHERE d.salience_bool = 'TRUE'
          AND d.distilled_text IS NOT NULL
          AND length(d.distilled_text) > 50
    """
    params = {}
    if country:
        sql += " AND (ic.initiating_country = :country OR d.initiating_country = :country)"
        params["country"] = country
    if recipient:
        sql += " AND (rc.recipient_country = :recipient OR d.recipient_country = :recipient)"
        params["recipient"] = recipient
    if start_date:
        sql += " AND d.date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        sql += " AND d.date <= :end_date"
        params["end_date"] = end_date
    sql += " ORDER BY d.date LIMIT :limit"
    params["limit"] = limit

    return session.execute(text(sql), params).mappings().all()


def parse_llm_output(raw):
    """gai() may return dict, list, or raw string. Normalize to dict."""
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


def extract_propositions(doc, model):
    """Call the LLM and return (parsed_result, error_or_none)."""
    user_prompt = (
        f"doc_id: {doc['doc_id']}\n"
        f"date: {doc['date']}\n"
        f"title: {doc['title']}\n"
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", help="Initiating country")
    ap.add_argument("--recipient", help="Recipient country")
    ap.add_argument("--start", dest="start_date", help="Start date YYYY-MM-DD")
    ap.add_argument("--end", dest="end_date", help="End date YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--model", default="gpt-4o", help="LLM deployment/model name")
    ap.add_argument("--output", required=True, help="Output JSONL path")
    args = ap.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with get_session() as session:
        docs = fetch_documents(
            session, args.country, args.recipient,
            args.start_date, args.end_date, args.limit,
        )

    print(f"Fetched {len(docs)} documents for slice "
          f"(country={args.country}, recipient={args.recipient}, "
          f"{args.start_date}..{args.end_date})")

    if not docs:
        print("No documents matched. Exiting.")
        return

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
            print(f"[{i}/{len(docs)}] {doc['doc_id']} ({doc['date']})", flush=True)

            parsed, err = extract_propositions(doc, args.model)
            stats["docs_processed"] += 1

            record = {
                "doc_id": doc["doc_id"],
                "doc_date": str(doc["date"]) if doc["date"] else None,
                "doc_title": doc["title"],
                "doc_initiating_country": doc["initiating_country"],
                "doc_recipient_country": doc["recipient_country"],
                "doc_category": doc["category"],
                "doc_subcategory": doc["subcategory"],
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
