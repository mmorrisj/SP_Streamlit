#!/usr/bin/env python3
"""
Clean up stale batch_job records where input files no longer exist.

This script:
1. Finds all batch_jobs with status='preparing'
2. Checks if input_file_path exists
3. Deletes records where file is missing
4. Reports what was cleaned up

Usage:
    python cleanup_stale_batches.py --job-type daily_entity_extract
    python cleanup_stale_batches.py --dry-run  # Show what would be deleted
"""
import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import BatchJob, BatchJobStatus


def main():
    parser = argparse.ArgumentParser(
        description="Clean up stale batch_job records with missing files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--job-type', type=str,
                       help='Filter by job type (e.g., daily_entity_extract)')
    parser.add_argument('--country', type=str,
                       help='Filter by country')
    parser.add_argument('--status', type=str, default='preparing',
                       help='Filter by status (default: preparing)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be deleted without actually deleting')

    args = parser.parse_args()

    print("=" * 80)
    print("CLEANUP STALE BATCH JOBS")
    print("=" * 80)
    print()

    with get_session() as session:
        # Query batch jobs
        query = session.query(BatchJob)

        if args.status:
            if args.status == 'preparing':
                query = query.filter(BatchJob.status == BatchJobStatus.PREPARING.value)
            elif args.status == 'failed':
                query = query.filter(BatchJob.status == BatchJobStatus.FAILED.value)
            elif args.status == 'submitted':
                query = query.filter(BatchJob.status == BatchJobStatus.SUBMITTED.value)

        if args.job_type:
            query = query.filter(BatchJob.job_type == args.job_type)

        if args.country:
            query = query.filter(BatchJob.initiating_country == args.country)

        batch_jobs = query.order_by(BatchJob.created_at.desc()).all()

        if not batch_jobs:
            print("No batch jobs found.")
            return

        print(f"Checking {len(batch_jobs)} batch jobs...")
        print()

        stale_jobs = []
        valid_jobs = []

        for job in batch_jobs:
            file_exists = os.path.exists(job.input_file_path) if job.input_file_path else False

            if not file_exists:
                stale_jobs.append(job)
            else:
                valid_jobs.append(job)

        print(f"Valid jobs (file exists): {len(valid_jobs)}")
        print(f"Stale jobs (file missing): {len(stale_jobs)}")
        print()

        if not stale_jobs:
            print("✓ No stale jobs to clean up!")
            return

        print("Stale jobs to be deleted:")
        print()

        for i, job in enumerate(stale_jobs, 1):
            print(f"{i}. {job.id}")
            print(f"   Job type: {job.job_type}")
            print(f"   Country: {job.initiating_country}")
            print(f"   Status: {job.status}")
            print(f"   Batch size: {job.batch_size}")
            print(f"   Created: {job.created_at}")
            print(f"   Missing file: {job.input_file_path}")
            print()

        if args.dry_run:
            print("DRY RUN - No deletions performed")
            return

        # Confirm deletion
        confirm = input(f"Delete {len(stale_jobs)} stale batch jobs? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            return

        # Delete stale jobs
        for job in stale_jobs:
            session.delete(job)

        session.commit()

        print()
        print(f"✓ Deleted {len(stale_jobs)} stale batch jobs")
        print()

        if valid_jobs:
            print(f"Remaining valid jobs: {len(valid_jobs)}")
            print()
            print("Valid jobs by country:")
            country_counts = {}
            for job in valid_jobs:
                country = job.initiating_country or "Unknown"
                country_counts[country] = country_counts.get(country, 0) + 1

            for country, count in sorted(country_counts.items()):
                print(f"  {country}: {count} batches")

        print()


if __name__ == "__main__":
    main()
