#!/usr/bin/env python3
"""
Download missing output files for completed batches.

This recovery script:
1. Finds all batch_jobs with status='completed' or 'in_progress'
2. Checks OpenAI for their current status
3. Downloads output files for completed batches that are missing locally
4. Updates database with file paths and status

Use this when:
- Batches completed but files weren't downloaded
- Local files were accidentally deleted
- Database got out of sync with OpenAI

Usage:
    # Download all missing output files
    python batch_download_missing.py --job-type daily_entity_extract

    # Check specific country
    python batch_download_missing.py --job-type daily_entity_extract --country China

    # Dry run to see what would be downloaded
    python batch_download_missing.py --dry-run

    # Force re-download even if files exist
    python batch_download_missing.py --force
"""
import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_config import get_batch_file_path
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.batch_api_client import get_batch_api_client
from shared.models.models import BatchJob, BatchJobStatus
from shared.database.database import get_session

# Use the actual batches directory where files are stored
BATCHES_DIR = project_root / 'services' / 'pipeline' / 'batch' / 'batches'


def check_and_download_batch(
    job: BatchJob,
    client,
    tracker: BatchJobTracker,
    session,
    force: bool = False
) -> tuple[bool, str]:
    """
    Check batch status and download output if needed.

    Args:
        job: BatchJob record
        client: Batch API client
        tracker: BatchJobTracker instance
        session: Database session
        force: Force re-download even if file exists

    Returns:
        Tuple of (success, message)
    """
    if not job.openai_batch_id:
        return (False, "No OpenAI batch ID")

    try:
        print(f"  Job type: {job.job_type}")
        print(f"  Batch job ID: {job.id}")

        # Get batch status from OpenAI
        batch = client.get_batch_status(job.openai_batch_id)
        openai_status = batch['status']
        request_counts = batch.get('request_counts', {})

        print(f"  OpenAI Status: {openai_status}")

        if request_counts:
            total = request_counts.get('total', 0)
            completed = request_counts.get('completed', 0)
            failed = request_counts.get('failed', 0)
            print(f"  Progress: {completed}/{total} completed, {failed} failed")

            # Update progress in database
            tracker.update_progress(job.id, total, completed, failed)

        # Check if completed on OpenAI
        if openai_status != 'completed':
            return (False, f"Not completed on OpenAI (status: {openai_status})")

        # Check if output file exists locally
        output_path = job.output_file_path
        if not output_path or output_path.strip() == '':
            # Generate output path using batches directory
            filename = f"{job.job_type}_{job.id}_output.jsonl"
            output_path = str(BATCHES_DIR / filename)
            print(f"  Generated output path: {output_path}")

        file_exists = os.path.exists(output_path)

        if file_exists and not force:
            print(f"  ✓ Output file already exists: {os.path.basename(output_path)}")

            # Make sure database is updated
            if job.status != BatchJobStatus.COMPLETED.value:
                tracker.update_status(job.id, BatchJobStatus.COMPLETED)
                print("  ✓ Updated database status to 'completed'")

            return (True, "Already downloaded")

        # Download results
        if file_exists and force:
            print("  ⚠️  Force re-downloading (will overwrite existing file)")

        print("  📥 Downloading output file...")
        download_result = client.download_results(job.openai_batch_id)
        content = download_result['content']

        # Validate output path
        if not output_path or output_path.strip() == '':
            raise ValueError(f"Invalid output path: '{output_path}'")

        # Ensure directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Write file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        file_size_kb = len(content) / 1024
        print(f"  ✓ Downloaded: {os.path.basename(output_path)} ({file_size_kb:.1f} KB)")

        # Update database
        tracker.update_file_paths(
            job.id,
            output_file_path=output_path,
            output_file_id=batch.get('output_file_id')
        )

        if job.status != BatchJobStatus.COMPLETED.value:
            tracker.update_status(job.id, BatchJobStatus.COMPLETED)

        session.commit()
        print("  ✓ Database updated")

        return (True, "Downloaded successfully")

    except Exception as e:
        print(f"  ✗ ERROR: {str(e)}")
        return (False, str(e))


def main():
    parser = argparse.ArgumentParser(
        description="Download missing output files for completed batches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--job-type', type=str,
                       help='Filter by job type (e.g., daily_entity_extract)')
    parser.add_argument('--country', type=str,
                       help='Filter by country')
    parser.add_argument('--force', action='store_true',
                       help='Force re-download even if files exist locally')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be downloaded without actually downloading')
    parser.add_argument('--status', type=str, default='completed',
                       choices=['completed', 'in_progress', 'submitted', 'all'],
                       help='Filter by batch status (default: completed)')

    args = parser.parse_args()

    # Ensure batches directory exists
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("BATCH DOWNLOAD MISSING - Download missing output files")
    print("=" * 80)
    print(f"Job type: {args.job_type or 'all'}")
    print(f"Country: {args.country or 'all'}")
    print(f"Status filter: {args.status}")
    print(f"Force re-download: {args.force}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Output directory: {BATCHES_DIR}")
    print("=" * 80)
    print()

    # Initialize API client
    client = get_batch_api_client()

    with get_session() as session:
        with BatchJobTracker(session) as tracker:
            # Query batch jobs
            query = session.query(BatchJob)

            if args.status == 'all':
                query = query.filter(
                    BatchJob.status.in_([
                        BatchJobStatus.SUBMITTED.value,
                        BatchJobStatus.IN_PROGRESS.value,
                        BatchJobStatus.COMPLETED.value
                    ])
                )
            else:
                query = query.filter(BatchJob.status == args.status)

            if args.job_type:
                query = query.filter(BatchJob.job_type == args.job_type)

            if args.country:
                query = query.filter(BatchJob.initiating_country == args.country)

            batch_jobs = query.order_by(
                BatchJob.initiating_country,
                BatchJob.created_at
            ).all()

            if not batch_jobs:
                print("No batch jobs found matching criteria.")
                return

            print(f"Found {len(batch_jobs)} batch jobs to check:")
            print()

            # Group by country for summary
            by_country = {}
            for job in batch_jobs:
                country = job.initiating_country or 'Unknown'
                if country not in by_country:
                    by_country[country] = []
                by_country[country].append(job)

            # Check each batch
            success_count = 0
            already_downloaded_count = 0
            failed_count = 0
            not_ready_count = 0

            for country, jobs in sorted(by_country.items()):
                print(f"{country}: {len(jobs)} batches")
                print()

                for i, job in enumerate(jobs, 1):
                    print(f"[{i}/{len(jobs)}] Batch ID: {job.id}")
                    print(f"  OpenAI Batch ID: {job.openai_batch_id}")
                    print(f"  DB Status: {job.status}")
                    print(f"  Created: {job.created_at.strftime('%Y-%m-%d %H:%M')}")
                    print(f"  Batch size: {job.batch_size}")

                    if args.dry_run:
                        # Just check if file exists
                        output_path = job.output_file_path or get_batch_file_path(
                            job.job_type,
                            'output',
                            batch_job_id=str(job.id)
                        )

                        if os.path.exists(output_path):
                            print(f"  ✓ File exists: {os.path.basename(output_path)}")
                            already_downloaded_count += 1
                        else:
                            print("  ⚠️  File missing: Would download")
                            print(f"  Target: {output_path}")
                        print()
                        continue

                    # Download if needed
                    success, message = check_and_download_batch(
                        job, client, tracker, session, args.force
                    )

                    if success:
                        if message == "Already downloaded":
                            already_downloaded_count += 1
                        else:
                            success_count += 1
                    elif "Not completed" in message:
                        not_ready_count += 1
                    else:
                        failed_count += 1

                    print()

                print()

            # Summary
            print("=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"Total batches checked: {len(batch_jobs)}")

            if args.dry_run:
                print(f"Already downloaded: {already_downloaded_count}")
                print(f"Would download: {len(batch_jobs) - already_downloaded_count}")
            else:
                print(f"Successfully downloaded: {success_count}")
                print(f"Already had files: {already_downloaded_count}")
                print(f"Not ready yet: {not_ready_count}")
                print(f"Failed: {failed_count}")

            print("=" * 80)
            print()

            if success_count > 0 and not args.dry_run:
                print("Next steps:")
                print("  Process the downloaded results:")
                print("  python batch_process_results.py --batch-job-id <id>")
                print()


if __name__ == "__main__":
    main()
