"""Convert a pre-extracted ATOM CSV export into DSR-style JSON for dsr.py.

Some ATOM query-tool exports already carry the document-level GAI extraction
(salience, distilled-text, event-name, categories, countries, ...) in the
pipe-delimited "Auto GAI, Value" / "Auto GAI, Value Type" columns. Re-running
extraction via atom_pipeline.py would re-pay for LLM calls the upstream system
already made, so this converter reshapes each CSV row into the nested DSR
document structure that dsr_core.parse_doc consumes, then dsr.py --source
local ingests the output exactly like any other DSR drop.

Row anatomy (pipe-joined, positionally aligned across Value / Value Type):
  pass 1: salience filter        -> salience-justification | salience
  pass N: optional tisc_* passes -> interleaved before or after extraction
  pass 2: full extraction        -> salience-justification | salience-bool |
          category | ... | distilled-text | event-name  (13 fields)

The extraction pass is located by anchoring on the unique 'salience-bool'
token rather than tail position, because tisc_* passes can appear after it.

CLI:
    python services/pipeline/ingestion/atom_extracted_csv.py export.csv
    ... export.csv --output-dir ./data --chunk-size 2000
    ... export.csv --dry-run          # parse + report, write nothing
"""
from __future__ import annotations

import argparse
import json
import os

# The 13 extraction-pass fields, in export order. Collection stops at the
# first token outside this set so trailing tisc_* passes are excluded.
EXTRACTION_TYPES = [
    "salience-justification",
    "salience-bool",
    "category",
    "category-justification",
    "subcategory",
    "initiating-country",
    "recipient-country",
    "projects",
    "lat-long",
    "location",
    "monetary-commitment",
    "distilled-text",
    "event-name",
]
_EXTRACTION_SET = set(EXTRACTION_TYPES)

DELIM = " | "


def _clean(val):
    """pandas NaN / empty -> None, else stripped str."""
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


def _split(val):
    return [t.strip() for t in str(val).split(DELIM)] if _clean(val) else []


def extract_gai_pairs(types, values):
    """Return (extraction_pairs, salience_value) or (None, reason).

    extraction_pairs is the [{'type','value'}...] list for the extraction
    pass, anchored on 'salience-bool'; salience_value comes from the pass-1
    salience filter ('true'/'false').
    """
    if len(types) != len(values):
        return None, f"token mismatch ({len(values)} values vs {len(types)} types)"
    if "salience-bool" not in types:
        return None, "no extraction pass (missing salience-bool)"

    anchor = types.index("salience-bool")
    start = anchor - 1 if anchor > 0 and types[anchor - 1] == "salience-justification" else anchor

    pairs = []
    for ty, va in zip(types[start:], values[start:]):
        if ty not in _EXTRACTION_SET:
            break
        pairs.append({"type": ty, "value": va})

    # parse_doc reads doc.salience from the gai value list; the filter pass
    # holds it, so append it to the extraction pass explicitly.
    if "salience" in types:
        pairs.append({"type": "salience", "value": values[types.index("salience")]})

    return pairs, None


def row_to_dsr_doc(row):
    """Map one CSV row (dict) to a DSR-style document dict, or (None, reason)."""
    atom_id = _clean(row.get("ATOM ID"))
    if not atom_id:
        return None, "missing ATOM ID"
    start_date = _clean(row.get("Source Date, Start"))
    if not start_date:
        return None, "missing Source Date, Start"

    types = _split(row.get("Auto GAI, Value Type"))
    values = _split(row.get("Auto GAI, Value"))
    pairs, err = extract_gai_pairs(types, values)
    if err:
        return None, err

    # Per-pass metadata columns are pipe-joined in pass order; the extraction
    # pass is second (after the salience filter) when present.
    models = _split(row.get("Auto GAI, Model Version"))
    prompt_ids = _split(row.get("Auto GAI, Prompt Identifier"))
    prompt_versions = _split(row.get("Auto GAI, Prompt Version"))

    def second_or_first(items):
        return items[1] if len(items) > 1 else (items[0] if items else None)

    extraction_pass = {
        "modelVersion": second_or_first(models),
        "filter": {
            "identifier": second_or_first(prompt_ids),
            "version": second_or_first(prompt_versions),
        },
        "value": pairs,
    }
    # parse_doc requires len(gai) >= 2 and reads gai[1]; gai[0] mirrors the
    # upstream salience-filter pass and is otherwise unused.
    salience_pass = {
        "modelVersion": models[0] if models else None,
        "filter": {
            "identifier": prompt_ids[0] if prompt_ids else None,
            "version": prompt_versions[0] if prompt_versions else None,
        },
        "value": [],
    }

    doc = {
        "id": atom_id,
        "title": {"title": _clean(row.get("Title")) or "Default Title"},
        "source": {
            "name": {"transliterated": _clean(row.get("Source Name"))},
            "geofocusCountry": _clean(row.get("Source Geofocus Country")),
            "descriptor": _clean(row.get("Source Descriptor")),
            "medium": _clean(row.get("Source Medium")),
            "country": {
                "physical": _clean(row.get("Source Country, Physical")) or "None Specified",
                "editorial": _clean(row.get("Source Country, Editorial")) or "None Specified",
                "consumption": _clean(row.get("Source Country, Consumption")) or "None Specified",
            },
            "startDate": start_date,
        },
        "custom": {"atom": {"collection_name": _clean(row.get("Collection Name"))}},
        "auto": {"gai": [salience_pass, extraction_pass]},
    }

    mt_title = _clean(row.get("Machine Translations, Title, Text"))
    if mt_title:
        doc["machineTranslations"] = {"title_title": {"text": mt_title}}

    return doc, None


def convert(csv_path, output_dir="./data", chunk_size=2000, dry_run=False):
    import pandas as pd

    usecols = [
        "ATOM ID", "Title", "Source Name", "Source Date, Start", "Collection Name",
        "Source Geofocus Country", "Source Descriptor", "Source Medium",
        "Source Country, Physical", "Source Country, Editorial", "Source Country, Consumption",
        "Auto GAI, Value", "Auto GAI, Value Type",
        "Auto GAI, Model Version", "Auto GAI, Prompt Identifier", "Auto GAI, Prompt Version",
        "Machine Translations, Title, Text",
    ]
    try:
        df = pd.read_csv(csv_path, engine="python", on_bad_lines="skip",
                         encoding="utf-8-sig", usecols=usecols)
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, engine="python", on_bad_lines="skip",
                         encoding="latin-1", usecols=usecols)

    docs, skipped, seen = [], [], set()
    for _, row in df.iterrows():
        doc, err = row_to_dsr_doc(row.to_dict())
        if err:
            skipped.append({"atom_id": _clean(row.get("ATOM ID")), "reason": err})
            continue
        if doc["id"] in seen:
            skipped.append({"atom_id": doc["id"], "reason": "duplicate ATOM ID in CSV"})
            continue
        seen.add(doc["id"])
        docs.append(doc)

    print(f"Converted {len(docs)} documents; skipped {len(skipped)} rows")
    for s in skipped:
        print(f"  skipped {s['atom_id']}: {s['reason']}")

    if dry_run:
        print("[DRY RUN] no files written")
        return docs

    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    written = []
    for i in range(0, len(docs), chunk_size):
        out_path = os.path.join(output_dir, f"{stem}_part{i // chunk_size + 1:02d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(docs[i:i + chunk_size], f, ensure_ascii=False)
        written.append(out_path)
        print(f"Wrote {min(chunk_size, len(docs) - i)} docs -> {out_path}")
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv_path", help="Pre-extracted ATOM CSV export")
    parser.add_argument("--output-dir", default="./data",
                        help="Directory for DSR JSON output (default: ./data, where dsr.py --source local reads)")
    parser.add_argument("--chunk-size", type=int, default=2000, help="Documents per JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing files")
    args = parser.parse_args()
    convert(args.csv_path, output_dir=args.output_dir,
            chunk_size=args.chunk_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
