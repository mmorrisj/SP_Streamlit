"""Quality checks for proposition_pilot JSONL output.

Reads all *.propositions.jsonl in a local or s3:// directory and runs a
battery of structural, filter-compliance, language, and distribution
checks. Prints a tiered report and optionally writes a machine-readable
JSON summary.

Usage:
  # Local
  python services/pipeline/analysis/proposition_quality_check.py \
      --input-dir pilot_outputs/china_2026/

  # S3 (downloads to a temp dir, runs checks)
  python services/pipeline/analysis/proposition_quality_check.py \
      --input-dir s3://morris-sp-bucket/propositions/china_2026/ \
      --allowed-initiators China Iran \
      --sample 10 \
      --output-report quality_report_china_iran.json
"""
import argparse
import json
import os
import random
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass


# Closed enums from the v0.7+ prompt / schema.
ENUM_CLAIM_TYPE = {"action", "commitment", "statement", "outcome", "perception", "capability"}
ENUM_TENSE = {"past", "present", "future"}
ENUM_MODALITY = {"actual", "planned", "proposed", "denied", "speculative"}
ENUM_SP_DOMAIN = {
    "economic_aid", "investment", "trade", "diplomatic_engagement", "cultural",
    "educational", "media_information", "science_technology", "health", "humanitarian",
    "security_military", "governance", "religious", "other",
}
ENUM_INSTRUMENT = {
    "state_visit", "bilateral_agreement", "multilateral_forum", "loan", "grant",
    "debt_relief", "direct_investment", "infrastructure_project", "scholarship",
    "exchange_program", "cultural_event", "language_institute", "media_broadcast",
    "joint_research", "training_program", "aid_delivery", "statement", "sanctions",
    "other",
}
ENUM_MECHANISM = {"attraction", "persuasion", "inducement", "coercion"}
ENUM_DATE_PRECISION = {"day", "month", "quarter", "year", "unknown", None}
ENUM_GEO_SCOPE = {"bilateral", "regional", "multilateral", "global", None}
ENUM_ACTOR_TYPE_OPEN = True  # initiator_actor_type / recipient_actor_type are open-ended

# Non-Latin script detection (Arabic, Chinese, Cyrillic, Hebrew, Devanagari, etc.)
_NON_LATIN_RE = re.compile(
    r"[֐-׿؀-ۿ܀-ݏऀ-ॿ一-鿿"
    r"぀-ヿЀ-ӿͰ-Ͽ]"
)


def load_config_recipients() -> List[str]:
    import yaml
    with open(project_root / "shared" / "config" / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    return list(cfg.get("recipients") or [])


def _coerce_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_coerce_str(v) for v in val)
    return str(val)


def _country_set(field: Any) -> set:
    s = _coerce_str(field)
    return {p.strip().lower() for p in s.split(";") if p.strip()}


def download_s3_jsonl(s3_uri: str, dest: Path) -> int:
    import boto3
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got {s3_uri!r}")
    rest = s3_uri[5:]
    bucket, _, prefix = rest.partition("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    s3 = boto3.client("s3")
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if not key.lower().endswith(".jsonl"):
                continue
            local = dest / Path(key).name
            s3.download_file(bucket, key, str(local))
            n += 1
    return n


def iter_jsonl_files(input_dir: Path) -> List[Path]:
    """Return *.propositions.jsonl (excludes *.dropped.jsonl by default)."""
    return sorted(p for p in input_dir.glob("*.propositions.jsonl")
                  if not p.name.endswith(".dropped.jsonl"))


def run_checks(input_dir: Path, allowed_initiators: set, allowed_recipients: set,
               sample_size: int = 10) -> Dict[str, Any]:
    files = iter_jsonl_files(input_dir)
    if not files:
        return {"error": f"No *.propositions.jsonl found in {input_dir}"}

    total_records = 0
    total_propositions = 0
    docs_with_zero = 0
    doc_id_seen = Counter()
    per_file_counts: List[Tuple[str, int, int]] = []  # (filename, records, props)

    # Issue buckets — each holds (doc_id, prop_idx, value/sample) tuples.
    out_of_scope_initiator: List[tuple] = []
    out_of_scope_recipient: List[tuple] = []
    self_country: List[tuple] = []
    null_recipient: List[tuple] = []
    private_individual: List[tuple] = []
    invalid_enum: Dict[str, List[tuple]] = defaultdict(list)
    missing_required: List[tuple] = []
    wrong_type: List[tuple] = []
    non_english: List[tuple] = []
    predicate_with_and: List[tuple] = []

    # Distributions
    dist: Dict[str, Counter] = {
        "sp_domain": Counter(), "instrument_type": Counter(), "mechanism": Counter(),
        "modality": Counter(), "claim_type": Counter(), "tense": Counter(),
        "recipient_country": Counter(), "initiator_country": Counter(),
        "initiator_actor_type": Counter(), "geo_scope": Counter(),
    }
    extractor_versions = Counter()
    extractor_models = Counter()
    extractor_backends = Counter()
    doc_dates: List[str] = []

    all_props_for_sample: List[Tuple[str, int, dict]] = []

    REQUIRED_FIELDS = (
        "proposition_text", "subject", "predicate", "object",
        "claim_type", "tense", "modality",
        "initiator_country", "recipient_country",
        "sp_domain", "instrument_type", "mechanism",
    )

    for fp in files:
        recs = 0
        props_in_file = 0
        with fp.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    wrong_type.append((fp.name, 0, "non_json_line"))
                    continue

                doc_id = rec.get("doc_id") or "<missing>"
                doc_id_seen[doc_id] += 1
                total_records += 1
                recs += 1

                if rec.get("doc_date"):
                    doc_dates.append(str(rec["doc_date"]))
                if rec.get("extractor_version"):
                    extractor_versions[rec["extractor_version"]] += 1
                if rec.get("extractor_model"):
                    extractor_models[rec["extractor_model"]] += 1
                if rec.get("extractor_backend"):
                    extractor_backends[rec["extractor_backend"]] += 1

                # Each record has runs.<source>.propositions
                runs = rec.get("runs") or {}
                doc_prop_count = 0
                for src, run_entry in runs.items():
                    if not isinstance(run_entry, dict):
                        continue
                    props = run_entry.get("propositions") or []
                    if not isinstance(props, list):
                        wrong_type.append((doc_id, -1, f"runs.{src}.propositions is {type(props).__name__}"))
                        continue
                    doc_prop_count += len(props)

                    for i, p in enumerate(props):
                        if not isinstance(p, dict):
                            wrong_type.append((doc_id, i, f"prop is {type(p).__name__}"))
                            continue
                        total_propositions += 1
                        all_props_for_sample.append((doc_id, i, p))
                        props_in_file += 1

                        # Required-field check
                        for fld in REQUIRED_FIELDS:
                            if fld not in p:
                                missing_required.append((doc_id, i, fld))

                        # Enum checks
                        for fld, allowed in (
                            ("claim_type", ENUM_CLAIM_TYPE),
                            ("tense", ENUM_TENSE),
                            ("modality", ENUM_MODALITY),
                            ("sp_domain", ENUM_SP_DOMAIN),
                            ("instrument_type", ENUM_INSTRUMENT),
                            ("mechanism", ENUM_MECHANISM),
                            ("date_precision", ENUM_DATE_PRECISION),
                            ("geo_scope", ENUM_GEO_SCOPE),
                        ):
                            v = p.get(fld)
                            if v not in allowed:
                                invalid_enum[fld].append((doc_id, i, v))

                        # Filter compliance (per-proposition)
                        init_set = _country_set(p.get("initiator_country"))
                        recip_set = _country_set(p.get("recipient_country"))
                        recip_actor = _coerce_str(p.get("recipient_actor")).strip()

                        if allowed_initiators and init_set and not (
                            init_set & {c.lower() for c in allowed_initiators}
                        ):
                            out_of_scope_initiator.append((doc_id, i, p.get("initiator_country")))
                        if allowed_recipients and recip_set and not (
                            recip_set & {c.lower() for c in allowed_recipients}
                        ):
                            out_of_scope_recipient.append((doc_id, i, p.get("recipient_country")))
                        if init_set and recip_set and init_set == recip_set:
                            self_country.append((doc_id, i, p.get("initiator_country")))
                        if not recip_set and not recip_actor:
                            null_recipient.append((doc_id, i, None))
                        if _coerce_str(p.get("initiator_actor_type")).strip().lower() == "individual":
                            actor = _coerce_str(p.get("initiator_actor"))
                            subj = _coerce_str(p.get("subject"))
                            haystack = (actor + " " + subj).lower()
                            STATE_MARKERS = (
                                "president", "minister", "ambassador", "ministry", "embassy",
                                "secretary", "chairman", "envoy", "spokesperson", "premier",
                                "governor", "general", "admiral", "chancellor", "consul",
                            )
                            if not any(m in haystack for m in STATE_MARKERS):
                                private_individual.append(
                                    (doc_id, i, _coerce_str(p.get("initiator_actor"))[:60])
                                )

                        # Language: non-Latin in English-required fields
                        for fld in ("proposition_text", "subject", "predicate", "object"):
                            v = _coerce_str(p.get(fld))
                            if _NON_LATIN_RE.search(v):
                                non_english.append((doc_id, i, fld, v[:80]))
                        ev = p.get("evidence_span") or {}
                        if isinstance(ev, dict):
                            evt = _coerce_str(ev.get("text"))
                            if _NON_LATIN_RE.search(evt):
                                non_english.append((doc_id, i, "evidence_span.text", evt[:80]))

                        # Atomicity: predicate contains " and "
                        pred = _coerce_str(p.get("predicate")).lower()
                        if " and " in pred:
                            predicate_with_and.append((doc_id, i, p.get("predicate")))

                        # Distributions
                        for k in dist:
                            v = _coerce_str(p.get(k)).strip()
                            if v:
                                dist[k][v] += 1

                if doc_prop_count == 0:
                    docs_with_zero += 1
        per_file_counts.append((fp.name, recs, props_in_file))

    duplicate_doc_ids = {d: c for d, c in doc_id_seen.items() if c > 1}

    # Sample for human eyeball
    sample = random.sample(all_props_for_sample, min(sample_size, len(all_props_for_sample))) \
        if all_props_for_sample else []

    return {
        "input_dir": str(input_dir),
        "files_scanned": len(files),
        "totals": {
            "records": total_records,
            "propositions": total_propositions,
            "unique_doc_ids": len(doc_id_seen),
            "duplicate_doc_ids": len(duplicate_doc_ids),
            "docs_with_zero_propositions": docs_with_zero,
        },
        "per_file_counts": per_file_counts,
        "extractor_versions": dict(extractor_versions),
        "extractor_models": dict(extractor_models),
        "extractor_backends": dict(extractor_backends),
        "doc_date_range": {
            "min": min(doc_dates) if doc_dates else None,
            "max": max(doc_dates) if doc_dates else None,
        },
        "filter_compliance": {
            "out_of_scope_initiator": out_of_scope_initiator,
            "out_of_scope_recipient": out_of_scope_recipient,
            "self_country": self_country,
            "null_recipient": null_recipient,
            "private_individual": private_individual,
        },
        "schema_issues": {
            "missing_required_field": missing_required,
            "wrong_type": wrong_type,
            "invalid_enum": {k: v for k, v in invalid_enum.items()},
        },
        "language_compliance": {
            "non_english_field_samples": non_english,
        },
        "atomicity_warnings": {
            "predicate_with_and": predicate_with_and,
        },
        "distributions": {k: dict(v.most_common(20)) for k, v in dist.items()},
        "duplicate_doc_id_counts": dict(sorted(duplicate_doc_ids.items(), key=lambda x: -x[1])[:20]),
        "sample": [
            {"doc_id": d, "prop_idx": i, "proposition": p}
            for d, i, p in sample
        ],
    }


def _print_section(title: str):
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _print_issue_list(name: str, items: list, max_show: int = 5):
    n = len(items)
    if n == 0:
        print(f"  [PASS] {name}: 0")
        return
    print(f"  [WARN] {name}: {n}")
    for sample in items[:max_show]:
        print(f"    - {sample}")
    if n > max_show:
        print(f"    ... and {n - max_show} more")


def print_report(report: Dict[str, Any]):
    if "error" in report:
        print(f"ERROR: {report['error']}")
        return

    t = report["totals"]
    _print_section("OVERVIEW")
    print(f"  Input dir:                  {report['input_dir']}")
    print(f"  Files scanned:              {report['files_scanned']}")
    print(f"  Total records (docs):       {t['records']}")
    print(f"  Total propositions:         {t['propositions']}")
    print(f"  Unique doc_ids:             {t['unique_doc_ids']}")
    print(f"  Duplicate doc_ids:          {t['duplicate_doc_ids']}")
    print(f"  Docs with 0 propositions:   {t['docs_with_zero_propositions']}")
    print(f"  Doc date range:             {report['doc_date_range']['min']} .. {report['doc_date_range']['max']}")
    print(f"  Extractor versions seen:    {report['extractor_versions']}")
    print(f"  Extractor models seen:      {report['extractor_models']}")
    print(f"  Extractor backends seen:    {report['extractor_backends']}")

    _print_section("PER-FILE COUNTS")
    for fn, recs, props in report["per_file_counts"]:
        print(f"  {recs:>6} records  {props:>7} props  {fn}")

    _print_section("FILTER COMPLIANCE")
    fc = report["filter_compliance"]
    _print_issue_list("out_of_scope_initiator", fc["out_of_scope_initiator"])
    _print_issue_list("out_of_scope_recipient", fc["out_of_scope_recipient"])
    _print_issue_list("self_country_proposition", fc["self_country"])
    _print_issue_list("null_recipient_proposition", fc["null_recipient"])
    _print_issue_list("private_individual_slipped_through", fc["private_individual"])

    _print_section("SCHEMA ISSUES")
    si = report["schema_issues"]
    _print_issue_list("missing_required_field", si["missing_required_field"])
    _print_issue_list("wrong_type", si["wrong_type"])
    if si["invalid_enum"]:
        for field, items in si["invalid_enum"].items():
            _print_issue_list(f"invalid_enum.{field}", items)
    else:
        print("  [PASS] all enum fields conform")

    _print_section("LANGUAGE COMPLIANCE")
    _print_issue_list("non_english_field_samples", report["language_compliance"]["non_english_field_samples"])

    _print_section("ATOMICITY WARNINGS")
    _print_issue_list("predicate_with_and", report["atomicity_warnings"]["predicate_with_and"])

    _print_section("DISTRIBUTIONS (top 20 per field)")
    for k, counter in report["distributions"].items():
        print(f"\n  {k}")
        for v, c in counter.items():
            print(f"    {c:>7}  {v}")

    if report["duplicate_doc_id_counts"]:
        _print_section("DUPLICATE doc_ids (top 20)")
        for d, c in report["duplicate_doc_id_counts"].items():
            print(f"    {c}x  {d}")

    if report["sample"]:
        _print_section(f"RANDOM SAMPLE ({len(report['sample'])} propositions)")
        for item in report["sample"]:
            p = item["proposition"]
            print(f"\n  doc_id: {item['doc_id']}  prop_idx: {item['prop_idx']}")
            print(f"    text:        {_coerce_str(p.get('proposition_text'))[:200]}")
            print(f"    direction:   {p.get('initiator_country')} -> {p.get('recipient_country')}")
            print(f"    actor_type:  {p.get('initiator_actor_type')} ({_coerce_str(p.get('initiator_actor'))[:60]})")
            print(f"    sp_domain:   {p.get('sp_domain')}   instrument: {p.get('instrument_type')}   mechanism: {p.get('mechanism')}")
            print(f"    modality:    {p.get('modality')} ({p.get('tense')})")
            ev = p.get("evidence_span") or {}
            if isinstance(ev, dict):
                print(f"    evidence:    {_coerce_str(ev.get('text'))[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True,
                    help="Local directory or s3://bucket/prefix/ containing *.propositions.jsonl")
    ap.add_argument("--allowed-initiators", nargs="+", default=["China", "Iran"],
                    help="Allowed initiator countries (default: China Iran)")
    ap.add_argument("--allowed-recipients", nargs="+", default=None,
                    help="Allowed recipient countries (defaults to config.yaml recipients)")
    ap.add_argument("--sample", type=int, default=10,
                    help="Number of random propositions to print for human review")
    ap.add_argument("--output-report", default=None,
                    help="Optional path for the full JSON report (warnings/distributions/sample)")
    args = ap.parse_args()

    allowed_recipients = set(args.allowed_recipients) if args.allowed_recipients else set(load_config_recipients())
    allowed_initiators = set(args.allowed_initiators)
    print(f"Allowed initiators: {sorted(allowed_initiators)}")
    print(f"Allowed recipients: {sorted(allowed_recipients)} ({len(allowed_recipients)})")

    if args.input_dir.startswith("s3://"):
        with tempfile.TemporaryDirectory(prefix="qc_") as td:
            tmp = Path(td)
            print(f"Downloading JSONLs from {args.input_dir} to {tmp}...")
            n = download_s3_jsonl(args.input_dir, tmp)
            print(f"  downloaded {n} file(s)")
            report = run_checks(tmp, allowed_initiators, allowed_recipients, args.sample)
            report["input_dir"] = args.input_dir  # show the original s3 uri in report
    else:
        report = run_checks(Path(args.input_dir), allowed_initiators, allowed_recipients, args.sample)

    print_report(report)

    if args.output_report:
        with open(args.output_report, "w") as f:
            json.dump(report, f, indent=2, default=str, ensure_ascii=False)
        print(f"\nFull report written to: {args.output_report}")


if __name__ == "__main__":
    main()
