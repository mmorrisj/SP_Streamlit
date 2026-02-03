#!/usr/bin/env python3
"""
Monitor all submitted batch jobs and auto-download results as they complete.

This script:
1. Finds all batch_jobs with status='submitted' or 'in_progress'
2. Polls OpenAI for status updates
3. Auto-downloads results when batches complete
4. Updates database
5. Runs continuously until all batches are complete

Usage:
    # Monitor all batches
    python batch_monitor_all.py

    # Monitor specific job type
    python batch_monitor_all.py --job-type daily_entity_extract

    # Monitor with custom poll interval
    python batch_monitor_all.py --poll-interval 120

    # Check status once and exit
    python batch_monitor_all.py --check-once
"""
import argparse
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_config import (
    DEFAULT_POLL_INTERVAL,
    get_batch_file_path
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.batch_api_client import get_batch_api_client
from shared.models.models import BatchJob, BatchJobStatus
from shared.database.database import get_session


def check_and_update_batch(job: BatchJob, client, tracker: BatchJobTracker, session) -> str:
    """
    Check batch status and download results if complete.

    Args:
        job: BatchJob record
        client: Batch API client
        tracker: BatchJobTracker instance
        session: Database session

    Returns:
        Status string: 'completed', 'failed', 'in_progress', 'cancelled', 'expired'
    """
    if not job.openai_batch_id:
        return 'no_openai_id'

    try:
        # Get batch status from OpenAI
        batch = client.get_batch_status(job.openai_batch_id)
        status = batch['status']
        request_counts = batch.get('request_counts', {})

        # Update progress in database
        if request_counts:
            tracker.update_progress(
                job.id,
                request_counts.get('total', 0),
                request_counts.get('completed', 0),
                request_counts.get('failed', 0)
            )

        # Handle completion
        if status == 'completed':
            print(f"  ✓ COMPLETED: {job.initiating_country} batch{get_batch_number(job.input_file_path)}")
            print(f"    Total: {request_counts.get('total', 0)}, "
                  f"Completed: {request_counts.get('completed', 0)}, "
                  f"Failed: {request_counts.get('failed', 0)}")

            # Download results
            output_path = get_batch_file_path(
                job.job_type,
                'output',
                batch_job_id=str(job.id)
            )

            error_path = None
            if batch.get('error_file_id'):
                error_path = get_batch_file_path(
                    job.job_type,
                    'error',
                    batch_job_id=str(job.id)
                )

            # Download via API client
            download_result = client.download_results(job.openai_batch_id)
            content = download_result['content']

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"    Downloaded: {output_path} ({len(content)} bytes)")

            # Update database
            tracker.update_file_paths(
                job.id,
                output_file_path=output_path,
                output_file_id=batch.get('output_file_id'),
                error_file_path=error_path,
                error_file_id=batch.get('error_file_id')
            )
            tracker.update_status(job.id, BatchJobStatus.COMPLETED)
            session.commit()

            return 'completed'

        # Handle failures
        elif status == 'failed':
            error_msg = batch.get('errors', 'Unknown error')
            print(f"  ✗ FAILED: {job.initiating_country} batch{get_batch_number(job.input_file_path)}")
            print(f"    Error: {error_msg}")

            tracker.update_status(job.id, BatchJobStatus.FAILED, error_message=str(error_msg))
            session.commit()

            return 'failed'

        elif status == 'cancelled':
            print(f"  ⊘ CANCELLED: {job.initiating_country} batch{get_batch_number(job.input_file_path)}")

            tracker.update_status(job.id, BatchJobStatus.CANCELLED)
            session.commit()

            return 'cancelled'

        elif status == 'expired':
            print(f"  ⌛ EXPIRED: {job.initiating_country} batch{get_batch_number(job.input_file_path)}")

            tracker.update_status(job.id, BatchJobStatus.FAILED, error_message="Batch expired (exceeded 24h window)")
            session.commit()

            return 'expired'

        # Still in progress
        else:
            if status != job.status:
                tracker.update_status(job.id, BatchJobStatus.IN_PROGRESS)
                session.commit()

            return 'in_progress'

    except Exception as e:
        print(f"  ✗ ERROR checking {job.initiating_country} batch{get_batch_number(job.input_file_path)}: {str(e)}")
        return 'error'


def get_batch_number(file_path: str) -> str:
    """Extract batch number from file path (e.g., '_batch1' -> '1')."""
    if not file_path:
        return ''

    import re
    match = re.search(r'_batch(\d+)', file_path)
    return match.group(1) if match else ''


def main():
    parser = argparse.ArgumentParser(
        description="Monitor all submitted batch jobs and auto-download results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--job-type', type=str,
                       help='Filter by job type (e.g., daily_entity_extract)')
    parser.add_argument('--country', type=str,
                       help='Filter by country')
    parser.add_argument('--poll-interval', type=int, default=DEFAULT_POLL_INTERVAL,
                       help=f'Polling interval in seconds (default: {DEFAULT_POLL_INTERVAL})')
    parser.add_argument('--check-once', action='store_true',
                       help='Check status once and exit (no continuous monitoring)')

    args = parser.parse_args()

    print("=" * 80)
    print("BATCH MONITOR ALL - Monitor all submitted batches")
    print("=" * 80)
    print(f"Poll interval: {args.poll_interval}s")
    print(f"Mode: {'Single check' if args.check_once else 'Continuous monitoring'}")
    print("=" * 80)
    print()

    # Initialize API client
    client = get_batch_api_client()

    start_time = datetime.now()
    check_count = 0

    try:
        while True:
            check_count += 1
            print(f"[Check #{check_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
            print()

            with get_session() as session:
                with BatchJobTracker(session) as tracker:
                    # Query active batches
                    query = session.query(BatchJob).filter(
                        BatchJob.status.in_([
                            BatchJobStatus.SUBMITTED.value,
                            BatchJobStatus.IN_PROGRESS.value
                        ])
                    )

                    if args.job_type:
                        query = query.filter(BatchJob.job_type == args.job_type)

                    if args.country:
                        query = query.filter(BatchJob.initiating_country == args.country)

                    active_jobs = query.order_by(
                        BatchJob.initiating_country,
                        BatchJob.created_at
                    ).all()

                    if not active_jobs:
                        print("No active batch jobs found.")
                        print()

                        if args.check_once:
                            print("All batches complete!")
                            return
                        else:
                            print("All batches complete! Exiting.")
                            return

                    print(f"Monitoring {len(active_jobs)} active batches:")
                    print()

                    # Group by country for summary
                    by_country = {}
                    for job in active_jobs:
                        country = job.initiating_country or 'Unknown'
                        if country not in by_country:
                            by_country[country] = []
                        by_country[country].append(job)

                    # Check each batch
                    completed_count = 0
                    failed_count = 0
                    in_progress_count = 0

                    for country, jobs in sorted(by_country.items()):
                        print(f"{country}: {len(jobs)} batches")

                        for job in jobs:
                            result = check_and_update_batch(job, client, tracker, session)

                            if result == 'completed':
                                completed_count += 1
                            elif result in ('failed', 'cancelled', 'expired'):
                                failed_count += 1
                            else:
                                in_progress_count += 1

                        print()

                    # Summary
                    print("=" * 80)
                    print(f"Summary: {in_progress_count} in progress, "
                          f"{completed_count} completed this check, "
                          f"{failed_count} failed")
                    print(f"Elapsed time: {(datetime.now() - start_time).total_seconds() / 60:.1f} minutes")
                    print("=" * 80)
                    print()

                    # Exit if check-once mode
                    if args.check_once:
                        print(f"Single check complete. {in_progress_count} batches still in progress.")
                        return

                    # Exit if all complete
                    if in_progress_count == 0:
                        print("All batches complete! Exiting.")
                        print()
                        print("Next step: Process results")
                        print("  python batch_process_results.py --batch-job-id <id>")
                        return

                    # Wait before next poll
                    print(f"Waiting {args.poll_interval} seconds before next check...")
                    print(f"(Press Ctrl+C to stop monitoring)")
                    print()
                    time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        print()
        print()
        print("Monitoring stopped by user.")
        print("Batch jobs are still running on OpenAI.")
        print("Run this script again to resume monitoring.")
        return


if __name__ == "__main__":
    main()
