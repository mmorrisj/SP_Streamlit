#!/usr/bin/env python3
"""
Process all completed batch job output files and load data into the database.

Finds all batch_jobs with status='completed' that have output files but
haven't been processed yet (processed_at IS NULL), then runs the appropriate
result handler for each based on the job type.

Usage:
    # Process all unprocessed completed batches
    python batch_process_all_results.py

    # Filter by job type
    python batch_process_all_results.py --job-type daily_entity_extract

    # Filter by country
    python batch_process_all_results.py --country China

    # Dry run (preview without database changes)
    python batch_process_all_results.py --dry-run

    # Process a specific batch that was already processed (re-process)
    python batch_process_all_results.py --include-processed
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import BatchJob, BatchJobStatus
from services.pipeline.batch.batch_config import (
    JOB_TYPE_CLUSTER_DECONFLICT,
    JOB_TYPE_CANONICAL_DECONFLICT,
    JOB_TYPE_ENTITY_EXTRACT,
    JOB_TYPE_SCORE_MATERIALITY,
    JOB_TYPE_DAILY_ENTITY_EXTRACT,
    JOB_TYPE_ENTITY_DECONFLICT,
    JOB_TYPE_CANONICAL_ENTITY_DECONFLICT,
    JOB_TYPE_GENERATE_DAILY_SUMMARY,
    JOB_TYPE_GENERATE_WEEKLY_SUMMARY,
    JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
    DEFAULT_CHECKPOINT_FREQUENCY
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.custom_id import parse_custom_id
from services.pipeline.batch.utils.jsonl_utils import read_jsonl
from services.pipeline.batch.batch_process_results import (
    process_cluster_result,
    process_canonical_result,
    process_entity_extract_result,
    process_materiality_score_result,
    process_daily_entity_extract_result,
    process_entity_deconflict_result,
    process_canonical_entity_deconflict_result,
    process_daily_summary_result,
    process_weekly_summary_result,
    process_monthly_summary_result
)
from services.pipeline.events.llm_deconflict_clusters import LLMClusterDeconfliction


def process_single_batch(
    session,
    tracker: BatchJobTracker,
    batch_job: BatchJob,
    checkpoint_frequency: int,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Process a single batch job's output file.

    Args:
        session: Database session
        tracker: BatchJobTracker instance
        batch_job: BatchJob record to process
        checkpoint_frequency: Commit every N results
        dry_run: Preview without database updates
        verbose: Print progress

    Returns:
        Statistics dict for this batch
    """
    overall_stats = {
        'total_processed': 0,
        'total_errors': 0,
        'canonical_events_created': 0,
        'canonical_events_updated': 0,
        'canonical_entities_created': 0,
        'canonical_entities_updated': 0,
        'daily_mentions_created': 0,
        'validated': 0,
        'confirmed': 0,
        'renamed': 0,
        'split': 0,
        'entities_extracted': 0,
        'events_scored': 0,
        'summaries_created': 0,
        'source_links_created': 0
    }

    # Verify output file exists
    output_path = batch_job.output_file_path
    if not output_path or not Path(output_path).exists():
        print(f"  Warning: Output file not found: {output_path}")
        overall_stats['total_errors'] += 1
        return overall_stats

    # Update status to processing
    if not dry_run:
        tracker.update_status(batch_job.id, BatchJobStatus.PROCESSING_RESULTS)

    # Initialize deconfliction processor for cluster jobs
    deconfliction_processor = None
    if batch_job.job_type == JOB_TYPE_CLUSTER_DECONFLICT:
        deconfliction_processor = LLMClusterDeconfliction(
            dry_run=dry_run,
            verbose=False
        )

    processed_count = 0

    for result in read_jsonl(output_path):
        processed_count += 1

        custom_id = result.get('custom_id')
        if not custom_id:
            if verbose:
                print("    Warning: Result missing custom_id, skipping")
            overall_stats['total_errors'] += 1
            continue

        try:
            custom_id_parts = parse_custom_id(custom_id)
            record_id = str(custom_id_parts['record_id'])
            job_type = custom_id_parts['job_type']

            # Extract LLM response
            response_body = result.get('response', {}).get('body', {})
            choices = response_body.get('choices', [])

            if not choices:
                if verbose:
                    print(f"    Warning: No choices in response for {custom_id}")
                overall_stats['total_errors'] += 1
                continue

            content = choices[0].get('message', {}).get('content', '')

            # Parse JSON response
            try:
                llm_response = json.loads(content)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                if json_match:
                    llm_response = json.loads(json_match.group(0))
                else:
                    if verbose:
                        print(f"    Warning: Could not parse JSON for {custom_id}")
                    overall_stats['total_errors'] += 1
                    continue

            # Normalize field names
            if job_type == JOB_TYPE_CLUSTER_DECONFLICT:
                if 'reasoning' in llm_response and 'explanation' not in llm_response:
                    llm_response['explanation'] = llm_response['reasoning']

            # Route to appropriate handler
            if dry_run:
                if verbose and processed_count <= 5:
                    print(f"    [DRY RUN] Would process {job_type} record {record_id}")
                overall_stats['total_processed'] += 1
            else:
                # Use savepoint for per-record isolation so one failure
                # doesn't abort the entire transaction
                savepoint = session.begin_nested()
                try:
                    suffix = custom_id_parts.get('suffix')
                    stats = _route_result(
                        session, job_type, record_id, llm_response,
                        deconfliction_processor, verbose, suffix=suffix
                    )
                    savepoint.commit()
                    overall_stats['total_processed'] += 1
                    _merge_stats(overall_stats, stats, job_type)
                except Exception as e:
                    savepoint.rollback()
                    if verbose:
                        print(f"    Error processing {custom_id}: {e}")
                    overall_stats['total_errors'] += 1

            # Checkpoint commit
            if not dry_run and processed_count % checkpoint_frequency == 0:
                session.commit()
                if verbose:
                    print(f"    [CHECKPOINT] {processed_count} results processed")

        except Exception as e:
            if verbose:
                print(f"    Error processing {custom_id}: {e}")
            overall_stats['total_errors'] += 1
            # Recover session after flush/integrity errors
            try:
                session.rollback()
            except Exception:
                pass
            continue

    # Final commit for this batch
    if not dry_run:
        session.commit()
        tracker.update_status(batch_job.id, BatchJobStatus.COMPLETED)

    return overall_stats


def _route_result(
    session, job_type, record_id, llm_response,
    deconfliction_processor, verbose, suffix=None
) -> Dict[str, Any]:
    """Route a result to the appropriate handler based on job_type."""
    if job_type == JOB_TYPE_CLUSTER_DECONFLICT:
        return process_cluster_result(
            session, record_id, llm_response,
            deconfliction_processor, verbose=verbose
        )
    elif job_type == JOB_TYPE_CANONICAL_DECONFLICT:
        return process_canonical_result(
            session, record_id, llm_response, verbose=verbose
        )
    elif job_type == JOB_TYPE_ENTITY_EXTRACT:
        return process_entity_extract_result(
            session, record_id, llm_response, verbose=verbose
        )
    elif job_type == JOB_TYPE_SCORE_MATERIALITY:
        return process_materiality_score_result(
            session, record_id, llm_response, verbose=verbose
        )
    elif job_type == JOB_TYPE_DAILY_ENTITY_EXTRACT:
        return process_daily_entity_extract_result(
            session, record_id, llm_response, verbose=verbose
        )
    elif job_type == JOB_TYPE_ENTITY_DECONFLICT:
        return process_entity_deconflict_result(
            session, record_id, llm_response, verbose=verbose
        )
    elif job_type == JOB_TYPE_CANONICAL_ENTITY_DECONFLICT:
        return process_canonical_entity_deconflict_result(
            session, record_id, llm_response, verbose=verbose
        )
    elif job_type == JOB_TYPE_GENERATE_DAILY_SUMMARY:
        if not suffix:
            raise ValueError("generate_daily_summary requires date suffix in custom_id")
        return process_daily_summary_result(
            session, record_id, llm_response,
            date_str=suffix, verbose=verbose
        )
    elif job_type == JOB_TYPE_GENERATE_WEEKLY_SUMMARY:
        if not suffix:
            raise ValueError("generate_weekly_summary requires week suffix in custom_id")
        return process_weekly_summary_result(
            session, record_id, llm_response,
            week_str=suffix, verbose=verbose
        )
    elif job_type == JOB_TYPE_GENERATE_MONTHLY_SUMMARY:
        if not suffix:
            raise ValueError("generate_monthly_summary requires month suffix in custom_id")
        return process_monthly_summary_result(
            session, record_id, llm_response,
            month_str=suffix, verbose=verbose
        )
    else:
        return {'errors': 1}


def _merge_stats(overall: Dict, stats: Dict, job_type: str):
    """Merge individual result stats into overall stats."""
    overall['total_errors'] += stats.get('errors', 0)

    if job_type == JOB_TYPE_CLUSTER_DECONFLICT:
        overall['canonical_events_created'] += stats.get('canonical_events_created', 0)
        overall['canonical_events_updated'] += stats.get('canonical_events_updated', 0)
        overall['daily_mentions_created'] += stats.get('daily_mentions_created', 0)
    elif job_type == JOB_TYPE_CANONICAL_DECONFLICT:
        overall['validated'] += stats.get('validated', 0)
        overall['renamed'] += stats.get('renamed', 0)
        overall['split'] += stats.get('split', 0)
    elif job_type in (JOB_TYPE_ENTITY_EXTRACT, JOB_TYPE_DAILY_ENTITY_EXTRACT):
        overall['entities_extracted'] += stats.get('entities_extracted', 0)
    elif job_type == JOB_TYPE_SCORE_MATERIALITY:
        overall['events_scored'] += stats.get('events_scored', 0)
    elif job_type == JOB_TYPE_ENTITY_DECONFLICT:
        overall['canonical_entities_created'] += stats.get('canonical_entities_created', 0)
        overall['canonical_entities_updated'] += stats.get('canonical_entities_updated', 0)
        overall['daily_mentions_created'] += stats.get('daily_mentions_created', 0)
        overall['confirmed'] += stats.get('confirmed', 0)
        overall['split'] += stats.get('split', 0)
    elif job_type == JOB_TYPE_CANONICAL_ENTITY_DECONFLICT:
        overall['validated'] += stats.get('validated', 0)
        overall['renamed'] += stats.get('renamed', 0)
        overall['split'] += stats.get('split', 0)
    elif job_type in (JOB_TYPE_GENERATE_DAILY_SUMMARY, JOB_TYPE_GENERATE_WEEKLY_SUMMARY, JOB_TYPE_GENERATE_MONTHLY_SUMMARY):
        overall['summaries_created'] += stats.get('summaries_created', 0)
        overall['source_links_created'] += stats.get('source_links_created', 0)


def main():
    parser = argparse.ArgumentParser(
        description="Process all completed batch output files and load data into database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--job-type', type=str,
                       help='Filter by job type (e.g., daily_entity_extract)')
    parser.add_argument('--country', type=str,
                       help='Filter by country')
    parser.add_argument('--checkpoint-frequency', type=int, default=DEFAULT_CHECKPOINT_FREQUENCY,
                       help=f'Commit every N processed results (default: {DEFAULT_CHECKPOINT_FREQUENCY})')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without updating database')
    parser.add_argument('--include-processed', action='store_true',
                       help='Include batches that were already processed (re-process)')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Verbose output')

    args = parser.parse_args()

    print("=" * 80)
    print("BATCH PROCESS ALL RESULTS - Process all completed batch output files")
    print("=" * 80)
    if args.job_type:
        print(f"Filter: job_type = {args.job_type}")
    if args.country:
        print(f"Filter: country = {args.country}")
    if args.dry_run:
        print("[DRY RUN MODE] No database updates will be made")
    if args.include_processed:
        print("Including already-processed batches")
    print(f"Checkpoint frequency: {args.checkpoint_frequency}")
    print("=" * 80)
    print()

    with get_session() as session:
        with BatchJobTracker(session) as tracker:
            # Query completed batch jobs that have output files
            query = session.query(BatchJob).filter(
                BatchJob.status == BatchJobStatus.COMPLETED.value,
                BatchJob.output_file_path.isnot(None)
            )

            # Only unprocessed unless --include-processed
            if not args.include_processed:
                query = query.filter(BatchJob.processed_at.is_(None))

            if args.job_type:
                query = query.filter(BatchJob.job_type == args.job_type)

            if args.country:
                query = query.filter(BatchJob.initiating_country == args.country)

            batch_jobs = query.order_by(
                BatchJob.job_type,
                BatchJob.initiating_country,
                BatchJob.created_at
            ).all()

            if not batch_jobs:
                print("No unprocessed completed batch jobs found.")
                print()
                print("Possible reasons:")
                print("  - All completed batches have already been processed")
                print("  - No batches have status='completed' with output files")
                print()
                print("Use --include-processed to re-process already processed batches")
                return

            print(f"Found {len(batch_jobs)} batch jobs to process:")
            print()

            # Group by job type for display
            by_type = {}
            for job in batch_jobs:
                jt = job.job_type
                if jt not in by_type:
                    by_type[jt] = []
                by_type[jt].append(job)

            for jt, jobs in sorted(by_type.items()):
                countries = set(j.initiating_country or 'Unknown' for j in jobs)
                total_size = sum(j.batch_size for j in jobs)
                print(f"  {jt}: {len(jobs)} batches ({total_size:,} total records)")
                print(f"    Countries: {', '.join(sorted(countries))}")
            print()

            # Process each batch
            grand_total = {
                'batches_processed': 0,
                'batches_failed': 0,
                'total_processed': 0,
                'total_errors': 0,
                'canonical_events_created': 0,
                'canonical_events_updated': 0,
                'canonical_entities_created': 0,
                'canonical_entities_updated': 0,
                'daily_mentions_created': 0,
                'validated': 0,
                'confirmed': 0,
                'renamed': 0,
                'split': 0,
                'entities_extracted': 0,
                'events_scored': 0,
                'summaries_created': 0,
                'source_links_created': 0
            }

            for i, job in enumerate(batch_jobs, 1):
                country = job.initiating_country or 'Unknown'
                print(f"[{i}/{len(batch_jobs)}] Processing: {job.job_type} | {country} | "
                      f"{job.batch_size:,} records")
                print(f"  Output file: {job.output_file_path}")

                try:
                    stats = process_single_batch(
                        session, tracker, job,
                        checkpoint_frequency=args.checkpoint_frequency,
                        dry_run=args.dry_run,
                        verbose=args.verbose
                    )

                    grand_total['batches_processed'] += 1
                    grand_total['total_processed'] += stats['total_processed']
                    grand_total['total_errors'] += stats['total_errors']
                    grand_total['canonical_events_created'] += stats['canonical_events_created']
                    grand_total['canonical_events_updated'] += stats['canonical_events_updated']
                    grand_total['canonical_entities_created'] += stats.get('canonical_entities_created', 0)
                    grand_total['canonical_entities_updated'] += stats.get('canonical_entities_updated', 0)
                    grand_total['daily_mentions_created'] += stats['daily_mentions_created']
                    grand_total['validated'] += stats['validated']
                    grand_total['confirmed'] += stats['confirmed']
                    grand_total['renamed'] += stats['renamed']
                    grand_total['split'] += stats['split']
                    grand_total['entities_extracted'] += stats['entities_extracted']
                    grand_total['events_scored'] += stats['events_scored']
                    grand_total['summaries_created'] += stats.get('summaries_created', 0)
                    grand_total['source_links_created'] += stats.get('source_links_created', 0)

                    print(f"  Done: {stats['total_processed']} processed, "
                          f"{stats['total_errors']} errors")

                except Exception as e:
                    print(f"  FAILED: {e}")
                    grand_total['batches_failed'] += 1

                print()

            # Final summary
            print("=" * 80)
            print("ALL BATCHES PROCESSING COMPLETE")
            print("=" * 80)
            print(f"Batches processed: {grand_total['batches_processed']}")
            print(f"Batches failed: {grand_total['batches_failed']}")
            print(f"Total results processed: {grand_total['total_processed']:,}")
            print(f"Total errors: {grand_total['total_errors']:,}")
            print()

            if grand_total['canonical_events_created'] > 0:
                print(f"Canonical events created: {grand_total['canonical_events_created']:,}")
            if grand_total['canonical_events_updated'] > 0:
                print(f"Canonical events updated: {grand_total['canonical_events_updated']:,}")
            if grand_total['canonical_entities_created'] > 0:
                print(f"Canonical entities created: {grand_total['canonical_entities_created']:,}")
            if grand_total['canonical_entities_updated'] > 0:
                print(f"Canonical entities updated: {grand_total['canonical_entities_updated']:,}")
            if grand_total['daily_mentions_created'] > 0:
                print(f"Daily mentions created: {grand_total['daily_mentions_created']:,}")
            if grand_total['validated'] > 0:
                print(f"Events validated: {grand_total['validated']:,}")
            if grand_total['confirmed'] > 0:
                print(f"Entity clusters confirmed: {grand_total['confirmed']:,}")
            if grand_total['renamed'] > 0:
                print(f"Events renamed: {grand_total['renamed']:,}")
            if grand_total['split'] > 0:
                print(f"Groups split: {grand_total['split']:,}")
            if grand_total['entities_extracted'] > 0:
                print(f"Entities extracted: {grand_total['entities_extracted']:,}")
            if grand_total['events_scored'] > 0:
                print(f"Events scored: {grand_total['events_scored']:,}")
            if grand_total['summaries_created'] > 0:
                print(f"Summaries created: {grand_total['summaries_created']:,}")
            if grand_total['source_links_created'] > 0:
                print(f"Source links created: {grand_total['source_links_created']:,}")

            print("=" * 80)
            print()


if __name__ == "__main__":
    main()
