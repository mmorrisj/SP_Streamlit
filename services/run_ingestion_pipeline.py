#!/usr/bin/env python3
"""
Full ingestion and event pipeline orchestrator.

Batch-first behavior:
- Uses Batch API workflows by default for:
  - Event deconfliction (cluster/canonical)
  - Summary generation (daily/weekly/monthly)
  - Materiality scoring (events and summaries)
  - Entity extraction/deconfliction/descriptions/relationship classification
  - Bilateral summaries
- Falls back to iterative scripts when --execution-mode iterative is used.
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INFLUENCERS = ["China", "Russia", "Iran", "Turkey", "United States"]

CORE_STAGES = {
    "ingestion",
    "embeddings",
    "clustering",
    "cluster_deconflict",
    "consolidate",
    "canonical_deconflict",
    "merge",
}

SUMMARY_STAGES = {
    "daily_summaries",
    "weekly_summaries",
    "monthly_summaries",
    "summary_materiality",
    "bilateral_summaries",
}

ENTITY_STAGES = {
    "daily_entity_extraction",
    "entity_clustering",
    "entity_deconflict",
    "entity_consolidate",
    "canonical_entity_deconflict",
    "entity_merge",
    "entity_descriptions",
    "entity_cooccurrence",
    "entity_relationships",
}

EVENTS_STAGES = CORE_STAGES | {"event_materiality"}

PROFILE_STAGE_MAP = {
    "full": EVENTS_STAGES | SUMMARY_STAGES | ENTITY_STAGES,
    "core": CORE_STAGES,
    "events": EVENTS_STAGES,
    "summaries": SUMMARY_STAGES,
    "entities": ENTITY_STAGES,
}


def parse_yyyy_mm_dd(value: str) -> str:
    """Validate YYYY-MM-DD input and return unchanged string."""
    datetime.strptime(value, "%Y-%m-%d")
    return value


def load_influencers(config_path: Path) -> List[str]:
    """Load influencers from config.yaml with fallback defaults."""
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        influencers = data.get("influencers")
        if isinstance(influencers, list) and influencers:
            return [str(country) for country in influencers]
    except Exception as exc:
        print(f"[WARNING] Could not load influencers from {config_path}: {exc}")

    print(f"[WARNING] Falling back to defaults: {', '.join(DEFAULT_INFLUENCERS)}")
    return DEFAULT_INFLUENCERS


def run_command(cmd: List[str], description: str, dry_run: bool = False) -> None:
    """Run a shell command with consistent logging."""
    print("\n" + "=" * 88)
    print(f"RUNNING: {description}")
    print(f"COMMAND: {' '.join(cmd)}")
    print("=" * 88)

    if dry_run:
        print("[DRY RUN] Skipped execution")
        return

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {result.returncode}")


def run_batch_job(
    job_type: str,
    country: str,
    max_concurrent: int,
    poll_interval: int,
    dry_run: bool,
    start_date: str = None,
    end_date: str = None,
    include_dates: bool = False,
    extra_prepare_args: List[str] = None,
) -> None:
    """Run prepare -> queue runner -> process results for one batch job type."""
    prepare_cmd = [
        sys.executable,
        "services/pipeline/batch/batch_prepare.py",
        "--job-type",
        job_type,
    ]

    if country:
        prepare_cmd.extend(["--country", country])

    if include_dates:
        if not start_date or not end_date:
            raise ValueError(f"{job_type} requires start_date and end_date")
        prepare_cmd.extend(["--start-date", start_date, "--end-date", end_date])

    if extra_prepare_args:
        prepare_cmd.extend(extra_prepare_args)

    run_command(
        prepare_cmd,
        f"Batch Prepare ({job_type}) - {country or 'all'}",
        dry_run=dry_run,
    )

    queue_cmd = [
        sys.executable,
        "services/pipeline/batch/batch_queue_runner.py",
        "--job-type",
        job_type,
        "--max-concurrent",
        str(max_concurrent),
        "--poll-interval",
        str(poll_interval),
    ]
    if country:
        queue_cmd.extend(["--country", country])
    run_command(
        queue_cmd,
        f"Batch Queue Runner ({job_type}) - {country or 'all'}",
        dry_run=dry_run,
    )

    process_cmd = [
        sys.executable,
        "services/pipeline/batch/batch_process_all_results.py",
        "--job-type",
        job_type,
    ]
    if country:
        process_cmd.extend(["--country", country])
    run_command(
        process_cmd,
        f"Batch Process Results ({job_type}) - {country or 'all'}",
        dry_run=dry_run,
    )


def run_iterative_cluster_deconflict(country: str, start_date: str, end_date: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/events/llm_deconflict_clusters.py",
        "--country",
        country,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]
    run_command(cmd, f"Iterative Cluster Deconflict - {country}", dry_run=dry_run)


def run_iterative_canonical_deconflict(country: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/events/llm_deconflict_canonical_events.py",
        "--country",
        country,
        "--resume",
    ]
    run_command(cmd, f"Iterative Canonical Deconflict - {country}", dry_run=dry_run)


def run_iterative_daily_summaries(country: str, start_date: str, end_date: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/summaries/generate_daily_summaries.py",
        "--country",
        country,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]
    run_command(cmd, f"Iterative Daily Summaries - {country}", dry_run=dry_run)


def run_iterative_weekly_summaries(country: str, start_date: str, end_date: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/summaries/generate_weekly_summaries.py",
        "--country",
        country,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]
    run_command(cmd, f"Iterative Weekly Summaries - {country}", dry_run=dry_run)


def run_iterative_monthly_summaries(country: str, start_date: str, end_date: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/summaries/generate_monthly_summaries.py",
        "--country",
        country,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]
    run_command(cmd, f"Iterative Monthly Summaries - {country}", dry_run=dry_run)


def run_iterative_event_materiality(
    country: str,
    min_days: int,
    min_articles: int,
    rescore: bool,
    dry_run: bool
) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/events/score_canonical_event_materiality.py",
        "--country",
        country,
        "--min-days",
        str(min_days),
        "--min-articles",
        str(min_articles),
    ]
    if rescore:
        cmd.append("--rescore")
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Event Materiality - {country}", dry_run=dry_run)


def run_iterative_summary_materiality(
    country: str,
    start_date: str,
    end_date: str,
    period: str,
    rescore: bool,
    dry_run: bool
) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/summaries/score_materiality.py",
        "--country",
        country,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--period-type",
        period,
    ]
    if rescore:
        cmd.append("--rescore")
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Summary Materiality ({period}) - {country}", dry_run=dry_run)


def run_iterative_entity_extract(country: str, start_date: str, end_date: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/entities/extract_daily_entities.py",
        "--country",
        country,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Daily Entity Extract - {country}", dry_run=dry_run)


def run_iterative_entity_deconflict(country: str, start_date: str, end_date: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/entities/llm_deconflict_entity_clusters.py",
        "--country",
        country,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
    ]
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Entity Deconflict - {country}", dry_run=dry_run)


def run_iterative_canonical_entity_deconflict(country: str, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/entities/llm_deconflict_canonical_entities.py",
        "--country",
        country,
        "--resume",
    ]
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Canonical Entity Deconflict - {country}", dry_run=dry_run)


def run_iterative_entity_descriptions(country: str, min_docs: int, dry_run: bool) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/entities/generate_entity_descriptions.py",
        "--country",
        country,
        "--min-docs",
        str(min_docs),
    ]
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Entity Descriptions - {country}", dry_run=dry_run)


def run_iterative_entity_relationships(
    country: str,
    min_cooccurrence: int,
    dry_run: bool
) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/entities/classify_entity_relationships.py",
        "--country",
        country,
        "--min-cooccurrence",
        str(min_cooccurrence),
    ]
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Entity Relationships - {country}", dry_run=dry_run)


def run_iterative_bilateral_summaries(
    country: str,
    min_docs: int,
    regenerate: bool,
    dry_run: bool
) -> None:
    cmd = [
        sys.executable,
        "services/pipeline/summaries/generate_bilateral_summaries.py",
        "--init-country",
        country,
        "--min-docs",
        str(min_docs),
    ]
    if regenerate:
        cmd.append("--regenerate")
    if dry_run:
        cmd.append("--dry-run")
    run_command(cmd, f"Iterative Bilateral Summaries - {country}", dry_run=dry_run)


def stage_enabled(stage_name: str, skip_flag: bool, active_stages: set) -> bool:
    """Return True when stage is part of selected profile and not skipped explicitly."""
    return stage_name in active_stages and not skip_flag


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run full ingestion pipeline with batch-first orchestration. "
            "Works when invoked from either project root or the services directory."
        )
    )

    parser.add_argument("--start-date", type=parse_yyyy_mm_dd, required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", type=parse_yyyy_mm_dd, required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--source", choices=["local", "s3"], default="local", help="DSR source")
    parser.add_argument("--s3-prefix", default="dsr_extracts/", help="S3 prefix when --source s3")
    parser.add_argument("--relocate", action="store_true", help="Relocate local DSR files after processing")

    parser.add_argument(
        "--execution-mode",
        choices=["batch", "iterative"],
        default="batch",
        help="Use batch workflows when available (default: batch)",
    )
    parser.add_argument(
        "--profile",
        choices=["full", "core", "events", "summaries", "entities"],
        default="full",
        help=(
            "Subset profile. full=everything, core=ingestion->event merge, "
            "events=core+event materiality, summaries=summary generation/scoring/bilateral, "
            "entities=entity pipeline"
        ),
    )

    parser.add_argument("--countries", nargs="+", help="Override influencer countries from config")
    parser.add_argument(
        "--config-path",
        default="shared/config/config.yaml",
        help="Path to config.yaml for influencer list",
    )

    parser.add_argument("--max-concurrent", type=int, default=5, help="Batch queue max concurrent jobs")
    parser.add_argument("--poll-interval", type=int, default=300, help="Batch queue poll interval (seconds)")

    parser.add_argument("--force-clustering", action="store_true", help="Force re-cluster already clustered dates")
    parser.add_argument(
        "--no-force-consolidate",
        action="store_true",
        help="Do not reset existing master_event_id before consolidation",
    )
    parser.add_argument(
        "--no-force-entity-consolidate",
        action="store_true",
        help="Do not reset existing master_entity_id before entity consolidation",
    )
    parser.add_argument(
        "--force-entity-cooccurrence",
        action="store_true",
        help="Rebuild co-occurrence relationships even if they already exist",
    )
    parser.add_argument(
        "--force-entity-extraction",
        action="store_true",
        help="Re-extract daily entities even if already processed",
    )
    parser.add_argument(
        "--force-entity-relationships",
        action="store_true",
        help="Reclassify already classified entity relationships",
    )

    parser.add_argument(
        "--rescore-event-materiality",
        action="store_true",
        help="Re-score canonical events even if material_score already exists",
    )
    parser.add_argument(
        "--rescore-summary-materiality",
        action="store_true",
        help="Re-score summaries even if material_score already exists",
    )
    parser.add_argument(
        "--regenerate-bilateral-summaries",
        action="store_true",
        help="Regenerate bilateral summaries even if already present",
    )

    parser.add_argument(
        "--event-materiality-min-days",
        type=int,
        default=1,
        help="Minimum days mentioned for event materiality scoring (default: 1)",
    )
    parser.add_argument(
        "--event-materiality-min-articles",
        type=int,
        default=3,
        help="Minimum articles for event materiality scoring (default: 3)",
    )
    parser.add_argument(
        "--entity-description-min-docs",
        type=int,
        default=3,
        help="Minimum docs for entity description generation (default: 3)",
    )
    parser.add_argument(
        "--relationship-min-cooccurrence",
        type=int,
        default=2,
        help="Minimum co-occurrence threshold for relationship generation/classification (default: 2)",
    )
    parser.add_argument(
        "--bilateral-min-docs",
        type=int,
        default=500,
        help="Minimum document threshold for bilateral summaries (default: 500)",
    )
    parser.add_argument(
        "--summary-materiality-periods",
        nargs="+",
        choices=["DAILY", "WEEKLY", "MONTHLY"],
        default=["DAILY", "WEEKLY", "MONTHLY"],
        help="Summary periods to materiality-score (default: DAILY WEEKLY MONTHLY)",
    )

    parser.add_argument("--skip-ingestion", action="store_true")
    parser.add_argument("--skip-embeddings", action="store_true")
    parser.add_argument("--skip-clustering", action="store_true")
    parser.add_argument("--skip-cluster-deconflict", action="store_true")
    parser.add_argument("--skip-consolidate", action="store_true")
    parser.add_argument("--skip-canonical-deconflict", action="store_true")
    parser.add_argument("--skip-merge", action="store_true")
    parser.add_argument("--skip-event-materiality", action="store_true")
    parser.add_argument("--skip-daily-summaries", action="store_true")
    parser.add_argument("--skip-weekly-summaries", action="store_true")
    parser.add_argument("--skip-monthly-summaries", action="store_true")
    parser.add_argument("--skip-summary-materiality", action="store_true")
    parser.add_argument("--skip-daily-entity-extraction", action="store_true")
    parser.add_argument("--skip-entity-clustering", action="store_true")
    parser.add_argument("--skip-entity-deconflict", action="store_true")
    parser.add_argument("--skip-entity-consolidate", action="store_true")
    parser.add_argument("--skip-canonical-entity-deconflict", action="store_true")
    parser.add_argument("--skip-entity-merge", action="store_true")
    parser.add_argument("--skip-entity-descriptions", action="store_true")
    parser.add_argument("--skip-entity-cooccurrence", action="store_true")
    parser.add_argument("--skip-entity-relationships", action="store_true")
    parser.add_argument("--skip-bilateral-summaries", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")

    args = parser.parse_args()

    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    if start_dt > end_dt:
        raise ValueError("--start-date must be <= --end-date")

    config_path = (PROJECT_ROOT / args.config_path).resolve()
    countries = args.countries if args.countries else load_influencers(config_path)
    active_stages = PROFILE_STAGE_MAP[args.profile]

    print("\n" + "#" * 88)
    print("INGESTION PIPELINE (BATCH-FIRST)")
    print("#" * 88)
    print(f"Date Range: {args.start_date} to {args.end_date}")
    print(f"Source: {args.source}")
    print(f"Execution Mode: {args.execution_mode}")
    print(f"Profile: {args.profile}")
    print(f"Countries ({len(countries)}): {', '.join(countries)}")
    print(f"Force Consolidate: {not args.no_force_consolidate}")
    print(f"Force Entity Consolidate: {not args.no_force_entity_consolidate}")
    print(f"Dry Run: {args.dry_run}")
    print("#" * 88)

    try:
        if stage_enabled("ingestion", args.skip_ingestion, active_stages):
            dsr_cmd = [
                sys.executable,
                "services/pipeline/ingestion/dsr.py",
                "--source",
                args.source,
                "--no-embed",
            ]
            if args.source == "local" and args.relocate:
                dsr_cmd.append("--relocate")
            if args.source == "s3":
                dsr_cmd.extend(["--s3-prefix", args.s3_prefix])

            run_command(dsr_cmd, "Ingestion (DSR -> documents)", dry_run=args.dry_run)

        if stage_enabled("embeddings", args.skip_embeddings, active_stages):
            embed_cmd = [
                sys.executable,
                "services/pipeline/embeddings/embed_missing_documents.py",
                "--yes",
            ]
            run_command(embed_cmd, "Embeddings (missing documents)", dry_run=args.dry_run)

        if stage_enabled("clustering", args.skip_clustering, active_stages):
            for country in countries:
                cluster_cmd = [
                    sys.executable,
                    "services/pipeline/events/batch_cluster_events.py",
                    "--country",
                    country,
                    "--start-date",
                    args.start_date,
                    "--end-date",
                    args.end_date,
                ]
                if args.force_clustering:
                    cluster_cmd.append("--force")
                run_command(cluster_cmd, f"Cluster Events - {country}", dry_run=args.dry_run)

        if stage_enabled("cluster_deconflict", args.skip_cluster_deconflict, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="cluster_deconflict",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        include_dates=True,
                    )
                else:
                    run_iterative_cluster_deconflict(
                        country=country,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("consolidate", args.skip_consolidate, active_stages):
            for country in countries:
                consolidate_cmd = [
                    sys.executable,
                    "services/pipeline/events/consolidate_all_events.py",
                    "--country",
                    country,
                ]
                if not args.no_force_consolidate:
                    consolidate_cmd.append("--force")
                run_command(consolidate_cmd, f"Consolidate Events - {country}", dry_run=args.dry_run)

        if stage_enabled("canonical_deconflict", args.skip_canonical_deconflict, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="canonical_deconflict",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                    )
                else:
                    run_iterative_canonical_deconflict(country=country, dry_run=args.dry_run)

        if stage_enabled("merge", args.skip_merge, active_stages):
            for country in countries:
                merge_cmd = [
                    sys.executable,
                    "services/pipeline/events/merge_canonical_events.py",
                    "--country",
                    country,
                ]
                run_command(merge_cmd, f"Merge Canonical Events - {country}", dry_run=args.dry_run)

        if stage_enabled("event_materiality", args.skip_event_materiality, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    materiality_args = [
                        "--min-days",
                        str(args.event_materiality_min_days),
                        "--min-articles",
                        str(args.event_materiality_min_articles),
                    ]
                    if args.rescore_event_materiality:
                        materiality_args.append("--rescore")

                    run_batch_job(
                        job_type="score_materiality",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        extra_prepare_args=materiality_args,
                    )
                else:
                    run_iterative_event_materiality(
                        country=country,
                        min_days=args.event_materiality_min_days,
                        min_articles=args.event_materiality_min_articles,
                        rescore=args.rescore_event_materiality,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("daily_summaries", args.skip_daily_summaries, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="generate_daily_summary",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        include_dates=True,
                    )
                else:
                    run_iterative_daily_summaries(
                        country=country,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("weekly_summaries", args.skip_weekly_summaries, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="generate_weekly_summary",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        include_dates=True,
                    )
                else:
                    run_iterative_weekly_summaries(
                        country=country,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("monthly_summaries", args.skip_monthly_summaries, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="generate_monthly_summary",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        include_dates=True,
                    )
                else:
                    run_iterative_monthly_summaries(
                        country=country,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("summary_materiality", args.skip_summary_materiality, active_stages):
            for country in countries:
                for period in args.summary_materiality_periods:
                    if args.execution_mode == "batch":
                        summary_materiality_args = ["--period-type", period]
                        if args.rescore_summary_materiality:
                            summary_materiality_args.append("--rescore")

                        run_batch_job(
                            job_type="score_summary_materiality",
                            country=country,
                            max_concurrent=args.max_concurrent,
                            poll_interval=args.poll_interval,
                            dry_run=args.dry_run,
                            start_date=args.start_date,
                            end_date=args.end_date,
                            include_dates=True,
                            extra_prepare_args=summary_materiality_args,
                        )
                    else:
                        run_iterative_summary_materiality(
                            country=country,
                            start_date=args.start_date,
                            end_date=args.end_date,
                            period=period,
                            rescore=args.rescore_summary_materiality,
                            dry_run=args.dry_run,
                        )

        if stage_enabled("daily_entity_extraction", args.skip_daily_entity_extraction, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    entity_extract_args = []
                    if args.force_entity_extraction:
                        entity_extract_args.append("--force")
                    run_batch_job(
                        job_type="daily_entity_extract",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        include_dates=True,
                        extra_prepare_args=entity_extract_args,
                    )
                else:
                    run_iterative_entity_extract(
                        country=country,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("entity_clustering", args.skip_entity_clustering, active_stages):
            for country in countries:
                entity_cluster_cmd = [
                    sys.executable,
                    "services/pipeline/entities/cluster_daily_entities.py",
                    "--country",
                    country,
                    "--start-date",
                    args.start_date,
                    "--end-date",
                    args.end_date,
                ]
                run_command(entity_cluster_cmd, f"Cluster Daily Entities - {country}", dry_run=args.dry_run)

        if stage_enabled("entity_deconflict", args.skip_entity_deconflict, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="entity_deconflict",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        include_dates=True,
                    )
                else:
                    run_iterative_entity_deconflict(
                        country=country,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("entity_consolidate", args.skip_entity_consolidate, active_stages):
            for country in countries:
                consolidate_entities_cmd = [
                    sys.executable,
                    "services/pipeline/entities/consolidate_all_entities.py",
                    "--country",
                    country,
                ]
                if not args.no_force_entity_consolidate:
                    consolidate_entities_cmd.append("--force")
                run_command(
                    consolidate_entities_cmd,
                    f"Consolidate Entities - {country}",
                    dry_run=args.dry_run,
                )

        if stage_enabled("canonical_entity_deconflict", args.skip_canonical_entity_deconflict, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="canonical_entity_deconflict",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                    )
                else:
                    run_iterative_canonical_entity_deconflict(country=country, dry_run=args.dry_run)

        if stage_enabled("entity_merge", args.skip_entity_merge, active_stages):
            for country in countries:
                merge_entities_cmd = [
                    sys.executable,
                    "services/pipeline/entities/merge_canonical_entities.py",
                    "--country",
                    country,
                ]
                run_command(merge_entities_cmd, f"Merge Canonical Entities - {country}", dry_run=args.dry_run)

        if stage_enabled("entity_descriptions", args.skip_entity_descriptions, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    run_batch_job(
                        job_type="generate_entity_descriptions",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        extra_prepare_args=[
                            "--min-articles",
                            str(args.entity_description_min_docs),
                        ],
                    )
                else:
                    run_iterative_entity_descriptions(
                        country=country,
                        min_docs=args.entity_description_min_docs,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("entity_cooccurrence", args.skip_entity_cooccurrence, active_stages):
            for country in countries:
                cooccurrence_cmd = [
                    sys.executable,
                    "services/pipeline/entities/build_entity_cooccurrence.py",
                    "--country",
                    country,
                    "--min-cooccurrence",
                    str(args.relationship_min_cooccurrence),
                ]
                if args.force_entity_cooccurrence:
                    cooccurrence_cmd.append("--force")
                run_command(
                    cooccurrence_cmd,
                    f"Build Entity Co-occurrence - {country}",
                    dry_run=args.dry_run,
                )

        if stage_enabled("entity_relationships", args.skip_entity_relationships, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    relationship_args = [
                        "--min-articles",
                        str(args.relationship_min_cooccurrence),
                    ]
                    if args.force_entity_relationships:
                        relationship_args.append("--force")
                    run_batch_job(
                        job_type="classify_entity_relationships",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        extra_prepare_args=relationship_args,
                    )
                else:
                    run_iterative_entity_relationships(
                        country=country,
                        min_cooccurrence=args.relationship_min_cooccurrence,
                        dry_run=args.dry_run,
                    )

        if stage_enabled("bilateral_summaries", args.skip_bilateral_summaries, active_stages):
            for country in countries:
                if args.execution_mode == "batch":
                    bilateral_args = [
                        "--min-articles",
                        str(args.bilateral_min_docs),
                    ]
                    if args.regenerate_bilateral_summaries:
                        bilateral_args.append("--rescore")
                    run_batch_job(
                        job_type="generate_bilateral_summaries",
                        country=country,
                        max_concurrent=args.max_concurrent,
                        poll_interval=args.poll_interval,
                        dry_run=args.dry_run,
                        extra_prepare_args=bilateral_args,
                    )
                else:
                    run_iterative_bilateral_summaries(
                        country=country,
                        min_docs=args.bilateral_min_docs,
                        regenerate=args.regenerate_bilateral_summaries,
                        dry_run=args.dry_run,
                    )

        print("\n[SUCCESS] Pipeline completed.")

    except Exception as exc:
        print(f"\n[ERROR] Pipeline failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
