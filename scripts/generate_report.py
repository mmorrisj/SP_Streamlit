#!/usr/bin/env python3
"""
CLI for generating publication reports.

Replicates the Publication page workflow with parameter flags for
country, date range, recipient, model selection, and source validation.
Outputs both JSON and DOCX.

Usage:
    python scripts/generate_report.py \
        --country China \
        --start-date 2024-08-01 \
        --end-date 2024-08-31 \
        --recipient Egypt \
        --top-events 10 \
        --model gpt-4o-mini \
        --validate \
        --output-dir ./reports

    # Batch mode (50% cost via OpenAI Batch API, ~1-24h)
    python scripts/generate_report.py \
        --country China \
        --start-date 2024-08-01 \
        --end-date 2024-08-31 \
        --model gpt-5-mini \
        --batch
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a publication report (JSON + DOCX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic report for China, August 2024
  python scripts/generate_report.py \\
      --country China --start-date 2024-08-01 --end-date 2024-08-31

  # Bilateral report with validation
  python scripts/generate_report.py \\
      --country China --start-date 2024-08-01 --end-date 2024-08-31 \\
      --recipient Egypt --validate

  # Custom model and output directory
  python scripts/generate_report.py \\
      --country Russia --start-date 2024-06-01 --end-date 2024-06-30 \\
      --model gpt-4.1-mini --top-events 15 --output-dir ./my_reports

  # JSON only (skip DOCX export)
  python scripts/generate_report.py \\
      --country China --start-date 2024-08-01 --end-date 2024-08-31 \\
      --json-only

  # Validation only on existing report JSON
  python scripts/generate_report.py \\
      --validate-only ./reports/China_Report_2024-08-01.json

  # Batch mode — 50% cost via OpenAI Batch API (takes ~1-24h)
  python scripts/generate_report.py \\
      --country China --start-date 2024-08-01 --end-date 2024-08-31 \\
      --model gpt-5-mini --batch

  # Batch mode with custom poll interval (120s)
  python scripts/generate_report.py \\
      --country China --start-date 2024-08-01 --end-date 2024-08-31 \\
      --batch --poll-interval 120
        """,
    )

    # Required parameters
    parser.add_argument(
        "--country", "-c",
        help="Initiating country (e.g., China, Russia, Iran)",
    )
    parser.add_argument(
        "--start-date", "-s",
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date", "-e",
        help="End date (YYYY-MM-DD)",
    )

    # Optional parameters
    parser.add_argument(
        "--recipient", "-r",
        default=None,
        help="Recipient country filter (default: All)",
    )
    parser.add_argument(
        "--top-events", "-n",
        type=int, default=10,
        help="Top events per category (1-25, default: 10)",
    )
    parser.add_argument(
        "--model", "-m",
        default="gpt-4o-mini",
        choices=["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1","gpt-5-mini"],
        help="LLM model for narrative generation (default: gpt-4o-mini)",
    )

    # Content inclusion flags (opt-in)
    parser.add_argument(
        "--entities",
        action="store_true",
        help="Include key entities (organizations, companies, locations) in report",
    )
    parser.add_argument(
        "--persons",
        action="store_true",
        help="Include key persons section in report",
    )

    # Validation flags
    parser.add_argument(
        "--validate", "-V",
        action="store_true",
        help="Run source validation after generation",
    )
    parser.add_argument(
        "--validation-model",
        default=None,
        help="LLM model for validation (default: same as --model)",
    )
    parser.add_argument(
        "--validate-only",
        metavar="JSON_FILE",
        help="Skip generation; validate an existing report JSON file",
    )

    # Batch mode
    parser.add_argument(
        "--batch", "-B",
        action="store_true",
        help="Use OpenAI Batch API for event/entity LLM calls (50%% cost, 1-24h)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int, default=60,
        help="Batch status polling interval in seconds (default: 60, only with --batch)",
    )

    # Output options
    parser.add_argument(
        "--output-dir", "-o",
        default="./reports",
        help="Output directory (default: ./reports)",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Only output JSON, skip DOCX export",
    )
    parser.add_argument(
        "--docx-only",
        action="store_true",
        help="Only output DOCX, skip JSON export",
    )
    parser.add_argument(
        "--reviewer",
        action="store_true",
        help="Also generate a reviewer validation DOCX with inline source links",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    # Validation: either --validate-only or the generation params are required
    if args.validate_only is None:
        if not args.country or not args.start_date or not args.end_date:
            parser.error(
                "--country, --start-date, and --end-date are required "
                "(unless using --validate-only)"
            )

    if args.top_events < 1 or args.top_events > 25:
        parser.error("--top-events must be between 1 and 25")

    return args


def log(msg: str, quiet: bool = False):
    if not quiet:
        print(msg, flush=True)


def generate(args) -> dict:
    """Run the report generation pipeline."""
    log(f"[CLI] Generating report: {args.country} "
        f"({args.start_date} to {args.end_date})", args.quiet)
    if args.recipient:
        log(f"[CLI] Recipient filter: {args.recipient}", args.quiet)
    log(f"[CLI] Model: {args.model}  |  Top events/category: {args.top_events}",
        args.quiet)

    if args.batch:
        from server.report_batch import generate_report_batch

        log("[CLI] Mode: BATCH (OpenAI Batch API — 50% cost reduction)", args.quiet)
        log(f"[CLI] Poll interval: {args.poll_interval}s", args.quiet)

        report = generate_report_batch(
            country=args.country,
            start_date_str=args.start_date,
            end_date_str=args.end_date,
            recipient=args.recipient,
            top_n=args.top_events,
            model=args.model,
            poll_interval=args.poll_interval,
            quiet=args.quiet,
            include_entities=args.entities,
            include_persons=args.persons,
        )
    else:
        from server.report_generator import generate_report

        report = generate_report(
            country=args.country,
            start_date_str=args.start_date,
            end_date_str=args.end_date,
            recipient=args.recipient,
            top_n=args.top_events,
            model=args.model,
            include_entities=args.entities,
            include_persons=args.persons,
        )

    total_events = report.get("metrics", {}).get("total_events", 0)
    total_docs = report.get("metrics", {}).get("total_documents", 0)
    log(f"[CLI] Generation complete: {total_events} events, "
        f"{total_docs} documents", args.quiet)

    return report


def validate(report: dict, model: str, quiet: bool = False) -> dict:
    """Run source validation on a completed report."""
    from server.report_validator import validate_report

    log("[CLI] Running source validation...", quiet)
    log(f"[CLI] Validation model: {model}", quiet)

    results = validate_report(report, model=model)

    status = results.get("status", "UNKNOWN")
    section_count = len(results.get("sections", {}))
    log(f"[CLI] Validation complete: {status} ({section_count} sections checked)",
        quiet)

    # Print per-section summary
    if not quiet:
        for section_id, section in results.get("sections", {}).items():
            s = section.get("status", "?")
            marker = {"GREEN": "+", "YELLOW": "~", "RED": "!"}.get(s, "?")
            claims = section.get("total_claims", 0)
            unsupported = section.get("unsupported_claims", 0)
            print(f"  [{marker}] {section_id}: {s} "
                  f"({claims} claims, {unsupported} unsupported)")

    return results


def export_json(report: dict, path: Path, quiet: bool = False):
    """Write report JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    log(f"[CLI] JSON saved: {path}", quiet)


def export_docx(report: dict, path: Path, quiet: bool = False):
    """Write report DOCX to disk."""
    from server.report_exporter import export_report_to_docx

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = export_report_to_docx(report)
    with open(path, "wb") as f:
        f.write(buf.read())
    log(f"[CLI] DOCX saved: {path}", quiet)


def export_reviewer_docx(report: dict, path: Path, quiet: bool = False):
    """Write reviewer validation DOCX to disk."""
    from server.report_exporter import export_reviewer_to_docx

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = export_reviewer_to_docx(report)
    with open(path, "wb") as f:
        f.write(buf.read())
    log(f"[CLI] Reviewer DOCX saved: {path}", quiet)


def export_validation_docx(
    validation: dict, report: dict, path: Path, quiet: bool = False
):
    """Write validation DOCX to disk."""
    from server.report_exporter import export_validation_to_docx

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = export_validation_to_docx(
        validation,
        report_title=report.get("title", ""),
        country=report.get("country", ""),
        period_start=report.get("period_start", ""),
        period_end=report.get("period_end", ""),
        report_data=report,
    )
    with open(path, "wb") as f:
        f.write(buf.read())
    log(f"[CLI] Validation DOCX saved: {path}", quiet)


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    validation_model = args.validation_model or args.model

    # ── Validate-only mode ──────────────────────────────────────
    if args.validate_only:
        json_path = Path(args.validate_only)
        if not json_path.exists():
            print(f"Error: File not found: {json_path}", file=sys.stderr)
            sys.exit(1)

        log(f"[CLI] Loading report from {json_path}", args.quiet)
        with open(json_path, "r", encoding="utf-8") as f:
            report = json.load(f)

        results = validate(report, validation_model, args.quiet)

        # Save validation results alongside the report
        val_path = json_path.with_name(
            json_path.stem + "_validation.json"
        )
        export_json(results, val_path, args.quiet)

        # Merge validation into report and re-export
        report["validation"] = results
        export_json(report, json_path, args.quiet)

        if not args.json_only:
            docx_path = json_path.with_suffix(".docx")
            export_docx(report, docx_path, args.quiet)

            # Validation DOCX
            val_docx_path = json_path.with_name(
                json_path.stem + "_validation.docx"
            )
            export_validation_docx(results, report, val_docx_path, args.quiet)

        sys.exit(0 if results["status"] == "GREEN" else 1)

    # ── Full generation mode ────────────────────────────────────
    report = generate(args)

    # Build output filenames
    recipient_tag = f"_{args.recipient}" if args.recipient else ""
    base_name = f"{args.country}{recipient_tag}_Report_{args.start_date}"
    json_path = output_dir / f"{base_name}.json"
    docx_path = output_dir / f"{base_name}.docx"

    # Optional source validation
    if args.validate:
        results = validate(report, validation_model, args.quiet)
        report["validation"] = results

        val_path = output_dir / f"{base_name}_validation.json"
        export_json(results, val_path, args.quiet)

    # Write outputs
    if not args.docx_only:
        export_json(report, json_path, args.quiet)

    if not args.json_only:
        export_docx(report, docx_path, args.quiet)

        # Reviewer validation DOCX (inline source links for review)
        if args.reviewer:
            reviewer_path = output_dir / f"{base_name}_reviewer.docx"
            export_reviewer_docx(report, reviewer_path, args.quiet)

        # Validation DOCX (when validation was run)
        if args.validate:
            val_docx_path = output_dir / f"{base_name}_validation.docx"
            export_validation_docx(
                report["validation"], report, val_docx_path, args.quiet
            )

    # Exit code: non-zero if validation ran and failed
    if args.validate:
        status = report.get("validation", {}).get("status", "UNKNOWN")
        sys.exit(0 if status == "GREEN" else 1)


if __name__ == "__main__":
    main()
