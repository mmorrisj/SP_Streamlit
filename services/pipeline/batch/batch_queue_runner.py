#!/usr/bin/env python3
"""
Batch Queue Runner - Maintains N concurrent batches, auto-submitting as they complete.

This orchestrator:
1. Finds all batch_jobs with status='preparing' (the queue)
2. Maintains up to N concurrent running batches (default: 5)
3. Monitors active batches every X minutes (default: 5)
4. When a batch completes, automatically submits the next one from the queue
5. Continues until queue is empty and all batches complete

Usage:
    # Run with 5 concurrent batches, check every 5 minutes
    python batch_queue_runner.py --job-type daily_entity_extract

    # Run with 10 concurrent batches, check every 2 minutes
    python batch_queue_runner.py --job-type daily_entity_extract --max-concurrent 10 --poll-interval 120

    # Filter by country
    python batch_queue_runner.py --job-type daily_entity_extract --country China

    # Dry run to see what would be submitted
    python batch_queue_runner.py --dry-run

Example workflow:
    1. Prepare 50 batches (all status='preparing')
    2. Run orchestrator with --max-concurrent 5
    3. Script submits first 5 batches
    4. Polls every 5 minutes
    5. When batch #1 completes, submits batch #6
    6. When batch #2 completes, submits batch #7
    7. Continues until all 50 are processed
"""
import argparse
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_config import (
    get_batch_file_path
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.batch_api_client import get_batch_api_client
from shared.models.models import BatchJob, BatchJobStatus
from shared.database.database import get_session


def submit_batch(job: BatchJob, client, tracker: BatchJobTracker, session) -> bool:
    """
    Submit a single batch job to OpenAI.

    Args:
        job: BatchJob to submit
        client: Batch API client
        tracker: BatchJobTracker instance
        session: Database session

    Returns:
        True if submission succeeded, False otherwise
    """
    try:
        print(f"  Submitting: {job.initiating_country} ({job.batch_size} requests)")
        print(f"  File: {os.path.basename(job.input_file_path)}")

        # Resolve file path (handle relative paths and Windows backslashes in Docker)
        file_path = job.input_file_path.replace('\\', '/')
        if not os.path.isabs(file_path):
            file_path = str(project_root / file_path)

        # Check file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Upload file
        upload_result = client.upload_file(file_path)
        file_id = upload_result['file_id']
        print(f"  ✓ File uploaded: {file_id}")

        # Create batch
        batch_result = client.create_batch(
            input_file_id=file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )
        batch_id = batch_result['id']
        print(f"  ✓ Batch created: {batch_id}")

        # Update database
        tracker.update_openai_batch_id(job.id, batch_id, file_id)
        tracker.update_status(job.id, BatchJobStatus.SUBMITTED)
        session.commit()

        print("  ✓ Status: preparing → submitted")
        return True

    except Exception as e:
        print(f"  ✗ FAILED: {str(e)}")

        # Update status to failed
        tracker.update_status(job.id, BatchJobStatus.FAILED, error_message=str(e))
        session.commit()

        return False


def check_batch_completion(job: BatchJob, client, tracker: BatchJobTracker, session, stall_timeout_minutes: int = 120) -> Tuple[str, bool]:
    """
    Check if batch has completed and download results if so.

    Args:
        job: BatchJob to check
        client: Batch API client
        tracker: BatchJobTracker instance
        session: Database session

    Returns:
        Tuple of (status, changed) where:
        - status: Current status ('in_progress', 'completed', 'failed', etc.)
        - changed: True if status changed (completed or failed)
    """
    if not job.openai_batch_id:
        return ('no_openai_id', False)

    try:
        # Get batch status from OpenAI
        batch = client.get_batch_status(job.openai_batch_id)
        status = batch['status']
        request_counts = batch.get('request_counts', {})

        # Update progress
        if request_counts:
            tracker.update_progress(
                job.id,
                request_counts.get('total', 0),
                request_counts.get('completed', 0),
                request_counts.get('failed', 0)
            )

        # Handle completion
        if status == 'completed':
            # Download results
            output_path = get_batch_file_path(
                job.job_type,
                'output',
                batch_job_id=str(job.id)
            )

            download_result = client.download_results(job.openai_batch_id)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(download_result['content'])

            # Update database
            tracker.update_file_paths(
                job.id,
                output_file_path=output_path,
                output_file_id=batch.get('output_file_id')
            )
            tracker.update_status(job.id, BatchJobStatus.COMPLETED)
            session.commit()

            return ('completed', True)

        # Handle failures
        elif status in ('failed', 'cancelled', 'expired'):
            error_msg = batch.get('errors', f'Batch {status}')
            tracker.update_status(job.id, BatchJobStatus.FAILED, error_message=str(error_msg))
            session.commit()

            return (status, True)

        # Still in progress — check for stall
        else:
            if status != job.status:
                tracker.update_status(job.id, BatchJobStatus.IN_PROGRESS)
                session.commit()

            # Stall detection: no progress for stall_timeout minutes
            if stall_timeout_minutes and job.submitted_at:
                meta = job.progress_metadata or {}
                requests_completed = meta.get('requests_completed', 0)
                requests_total = meta.get('requests_total', job.batch_size)

                # Use last_progress_change_at if available, else fall back to submitted_at
                last_change_str = meta.get('last_progress_change_at')
                if last_change_str:
                    last_change = datetime.fromisoformat(last_change_str)
                else:
                    last_change = job.submitted_at

                stall_minutes = (datetime.utcnow() - last_change).total_seconds() / 60
                if stall_minutes >= stall_timeout_minutes:
                    stall_msg = (
                        f"Stalled: no progress for {stall_minutes:.0f} min "
                        f"({requests_completed}/{requests_total} completed, "
                        f"timeout={stall_timeout_minutes}min). OpenAI batch: {job.openai_batch_id}"
                    )
                    print(f"    ⚠ STALL DETECTED: {stall_msg}")

                    # Cancel the OpenAI batch so it doesn't linger
                    try:
                        client.cancel_batch(job.openai_batch_id)
                        print(f"    ⚠ Cancelled OpenAI batch: {job.openai_batch_id}")
                    except Exception as cancel_err:
                        print(f"    ⚠ Could not cancel OpenAI batch: {cancel_err}")

                    tracker.update_status(job.id, BatchJobStatus.FAILED, error_message=stall_msg)
                    session.commit()
                    return ('stalled', True)

            return ('in_progress', False)

    except Exception as e:
        print(f"    ✗ Error checking batch: {str(e)}")
        return ('error', False)


def main():
    parser = argparse.ArgumentParser(
        description="Batch Queue Runner - Maintains N concurrent batches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--job-type', type=str,
                       help='Filter by job type (e.g., daily_entity_extract)')
    parser.add_argument('--country', type=str,
                       help='Filter by country')
    parser.add_argument('--max-concurrent', type=int, default=5,
                       help='Maximum concurrent batches (default: 5)')
    parser.add_argument('--poll-interval', type=int, default=60,
                       help='Polling interval in seconds (default: 60 = 1 minute)')
    parser.add_argument('--retry-failed', action='store_true',
                       help='Reset failed batches to preparing so they get re-submitted')
    parser.add_argument('--stall-timeout', type=int, default=120,
                       help='Minutes with 0%% progress before marking a batch as failed (default: 120, 0=disabled)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be submitted without actually submitting')

    args = parser.parse_args()

    print("=" * 80)
    print("BATCH QUEUE RUNNER - Automated Concurrent Batch Processing")
    print("=" * 80)
    print(f"Max concurrent batches: {args.max_concurrent}")
    print(f"Poll interval: {args.poll_interval}s ({args.poll_interval / 60:.1f} minutes)")
    print(f"Job type: {args.job_type or 'all'}")
    print(f"Country: {args.country or 'all'}")
    print(f"Retry failed: {args.retry_failed}")
    print(f"Stall timeout: {args.stall_timeout} minutes (0=disabled)")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 80)
    print()

    # Reset failed batches if --retry-failed
    if args.retry_failed:
        with get_session() as session:
            failed_query = session.query(BatchJob).filter(
                BatchJob.status == BatchJobStatus.FAILED.value
            )
            if args.job_type:
                failed_query = failed_query.filter(BatchJob.job_type == args.job_type)
            if args.country:
                failed_query = failed_query.filter(BatchJob.initiating_country == args.country)

            failed_jobs = failed_query.all()

            if failed_jobs:
                print(f"Resetting {len(failed_jobs)} failed batches to preparing:")
                for job in failed_jobs:
                    country = job.initiating_country or 'Unknown'
                    print(f"  {job.job_type} | {country} | {job.batch_size} requests | "
                          f"retry #{(job.retry_count or 0) + 1}")
                    job.status = BatchJobStatus.PREPARING.value
                    job.error_message = None
                    job.retry_count = (job.retry_count or 0) + 1
                session.commit()
                print()
            else:
                print("No failed batches found to retry.")
                print()

    # Initialize API client
    client = get_batch_api_client()

    start_time = datetime.now()
    check_count = 0
    total_submitted = 0
    total_completed = 0
    total_failed = 0

    try:
        while True:
            check_count += 1
            print(f"[Check #{check_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
            print()

            with get_session() as session:
                with BatchJobTracker(session) as tracker:
                    # Get queue (preparing batches)
                    queue_query = session.query(BatchJob).filter(
                        BatchJob.status == BatchJobStatus.PREPARING.value
                    )
                    if args.job_type:
                        queue_query = queue_query.filter(BatchJob.job_type == args.job_type)
                    if args.country:
                        queue_query = queue_query.filter(BatchJob.initiating_country == args.country)

                    queue = queue_query.order_by(BatchJob.created_at.asc()).all()

                    # Get active batches (submitted or in_progress)
                    active_query = session.query(BatchJob).filter(
                        BatchJob.status.in_([
                            BatchJobStatus.SUBMITTED.value,
                            BatchJobStatus.IN_PROGRESS.value
                        ])
                    )
                    if args.job_type:
                        active_query = active_query.filter(BatchJob.job_type == args.job_type)
                    if args.country:
                        active_query = active_query.filter(BatchJob.initiating_country == args.country)

                    active_batches = active_query.order_by(BatchJob.created_at.asc()).all()

                    print("Queue Status:")
                    print(f"  Pending: {len(queue)} batches")
                    print(f"  Active: {len(active_batches)}/{args.max_concurrent} batches")
                    print()

                    # Check if we're done
                    if len(queue) == 0 and len(active_batches) == 0:
                        print("=" * 80)
                        print("ALL BATCHES COMPLETE!")
                        print("=" * 80)
                        print(f"Total submitted: {total_submitted}")
                        print(f"Total completed: {total_completed}")
                        print(f"Total failed: {total_failed}")
                        print(f"Elapsed time: {(datetime.now() - start_time).total_seconds() / 60:.1f} minutes")
                        print()
                        return

                    # Monitor active batches
                    if active_batches:
                        print(f"Monitoring {len(active_batches)} active batches:")

                        slots_freed = 0
                        for job in active_batches:
                            status, changed = check_batch_completion(job, client, tracker, session, args.stall_timeout)

                            if changed:
                                if status == 'completed':
                                    print(f"  ✓ COMPLETED: {job.initiating_country} ({job.batch_size} requests)")
                                    total_completed += 1
                                    slots_freed += 1
                                elif status == 'stalled':
                                    print(f"  ✗ STALLED→FAILED: {job.initiating_country} (marked failed, use --retry-failed to resubmit)")
                                    total_failed += 1
                                    slots_freed += 1
                                else:
                                    print(f"  ✗ FAILED: {job.initiating_country} ({status})")
                                    total_failed += 1
                                    slots_freed += 1
                            else:
                                progress = ""
                                if job.progress_metadata:
                                    total = job.progress_metadata.get('requests_total', 0)
                                    completed = job.progress_metadata.get('requests_completed', 0)
                                    if total and completed is not None:
                                        pct = (completed / total) * 100
                                        progress = f" - {pct:.0f}% complete ({completed}/{total})"
                                print(f"  ⟳ IN PROGRESS: {job.initiating_country}{progress}")

                        print()

                        # Refresh active count after completions
                        if slots_freed > 0:
                            active_batches = [j for j in active_batches
                                            if j.status not in [BatchJobStatus.COMPLETED.value,
                                                              BatchJobStatus.FAILED.value]]

                    # Submit new batches to fill available slots
                    available_slots = args.max_concurrent - len(active_batches)

                    if available_slots > 0 and queue:
                        to_submit = min(available_slots, len(queue))

                        if args.dry_run:
                            print(f"DRY RUN - Would submit {to_submit} batches:")
                            for i in range(to_submit):
                                job = queue[i]
                                print(f"  {i+1}. {job.initiating_country} ({job.batch_size} requests)")
                            print()
                        else:
                            print(f"Submitting {to_submit} new batches to fill available slots:")
                            print()

                            for i in range(to_submit):
                                job = queue[i]
                                print(f"[{i+1}/{to_submit}]")

                                if submit_batch(job, client, tracker, session):
                                    total_submitted += 1

                                print()

                    # Get overall database stats
                    db_completed = session.query(BatchJob).filter(
                        BatchJob.status == BatchJobStatus.COMPLETED.value
                    )
                    if args.job_type:
                        db_completed = db_completed.filter(BatchJob.job_type == args.job_type)
                    if args.country:
                        db_completed = db_completed.filter(BatchJob.initiating_country == args.country)
                    total_db_completed = db_completed.count()

                    # Summary
                    print("=" * 80)
                    print("Session Summary (This Run):")
                    print(f"  Submitted this session: {total_submitted}")
                    print(f"  Completed this session: {total_completed}")
                    print(f"  Failed this session: {total_failed}")
                    print(f"  Currently active: {len(active_batches) + (0 if args.dry_run else to_submit if available_slots > 0 and queue else 0)}")
                    print(f"  Remaining in queue: {len(queue) - (to_submit if available_slots > 0 and queue and not args.dry_run else 0)}")
                    print()
                    print("Overall Database Status:")
                    print(f"  Total completed: {total_db_completed}")
                    print(f"  Total in progress/submitted: {len(active_batches)}")
                    print(f"  Total preparing (ready): {len(queue)}")
                    print()
                    print(f"  Session elapsed time: {(datetime.now() - start_time).total_seconds() / 60:.1f} minutes")
                    print("=" * 80)
                    print()

                    # Exit if dry run
                    if args.dry_run:
                        print("DRY RUN complete.")
                        return

                    # Wait before next poll
                    print(f"Waiting {args.poll_interval} seconds before next check...")
                    print("(Press Ctrl+C to stop monitoring)")
                    print()
                    time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        print()
        print()
        print("=" * 80)
        print("Monitoring stopped by user.")
        print("=" * 80)
        print(f"Submitted this session: {total_submitted}")
        print(f"Completed this session: {total_completed}")
        print(f"Failed this session: {total_failed}")
        print()
        print("Batch jobs are still running on OpenAI.")
        print("Run this script again to resume orchestration.")
        return


if __name__ == "__main__":
    main()
