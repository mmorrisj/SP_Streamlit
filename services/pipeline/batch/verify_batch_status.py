#!/usr/bin/env python3
"""
Verify batch job statuses in the database.

Shows a summary of all batch jobs grouped by status.
"""
import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.models.models import BatchJob, BatchJobStatus
from shared.database.database import get_session


def main():
    print("=" * 80)
    print("BATCH JOB STATUS VERIFICATION")
    print("=" * 80)
    print()

    with get_session() as session:
        # Get all batch jobs
        all_jobs = session.query(BatchJob).order_by(BatchJob.created_at.desc()).all()

        if not all_jobs:
            print("No batch jobs found in database.")
            return

        # Group by status
        by_status = defaultdict(list)
        by_country = defaultdict(list)

        for job in all_jobs:
            by_status[job.status].append(job)
            country = job.initiating_country or 'Unknown'
            by_country[country].append(job)

        # Summary by status
        print(f"Total batch jobs: {len(all_jobs)}")
        print()
        print("By Status:")
        for status, jobs in sorted(by_status.items()):
            print(f"  {status}: {len(jobs)}")
        print()

        # Summary by country
        print("By Country:")
        for country, jobs in sorted(by_country.items()):
            print(f"  {country}: {len(jobs)}")
        print()

        # Jobs with output files
        jobs_with_output = [j for j in all_jobs if j.output_file_path]
        print(f"Jobs with output files: {len(jobs_with_output)}/{len(all_jobs)}")
        print()

        # Detailed status for completed jobs
        completed_jobs = by_status.get(BatchJobStatus.COMPLETED.value, [])
        if completed_jobs:
            print("=" * 80)
            print(f"COMPLETED JOBS ({len(completed_jobs)})")
            print("=" * 80)
            print()

            for job in completed_jobs[:20]:  # Show first 20
                has_output = "✓" if job.output_file_path else "✗"
                progress = ""
                if job.progress_metadata:
                    total = job.progress_metadata.get('requests_total', 0)
                    completed = job.progress_metadata.get('requests_completed', 0)
                    if total:
                        progress = f" ({completed}/{total})"

                print(f"{has_output} {job.id}")
                print(f"   Country: {job.initiating_country}")
                print(f"   Batch size: {job.batch_size}{progress}")
                print(f"   OpenAI ID: {job.openai_batch_id}")
                if job.output_file_path:
                    import os
                    filename = os.path.basename(job.output_file_path)
                    exists = "✓" if os.path.exists(job.output_file_path) else "✗ MISSING"
                    print(f"   Output: {filename} {exists}")
                print()

            if len(completed_jobs) > 20:
                print(f"... and {len(completed_jobs) - 20} more")
                print()

        # Jobs that might need attention
        print("=" * 80)
        print("JOBS NEEDING ATTENTION")
        print("=" * 80)
        print()

        # Completed but no output file
        completed_no_output = [j for j in completed_jobs if not j.output_file_path]
        if completed_no_output:
            print(f"⚠️  {len(completed_no_output)} completed jobs without output files:")
            for job in completed_no_output[:5]:
                print(f"  - {job.id} ({job.initiating_country})")
            if len(completed_no_output) > 5:
                print(f"  ... and {len(completed_no_output) - 5} more")
            print()

        # In progress
        in_progress = by_status.get(BatchJobStatus.IN_PROGRESS.value, [])
        if in_progress:
            print(f"⟳ {len(in_progress)} jobs in progress")
            print()

        # Submitted but not in progress
        submitted = by_status.get(BatchJobStatus.SUBMITTED.value, [])
        if submitted:
            print(f"📤 {len(submitted)} jobs submitted (waiting to start)")
            print()

        # Failed
        failed = by_status.get(BatchJobStatus.FAILED.value, [])
        if failed:
            print(f"✗ {len(failed)} failed jobs")
            for job in failed[:5]:
                print(f"  - {job.id} ({job.initiating_country}): {job.error_message}")
            if len(failed) > 5:
                print(f"  ... and {len(failed) - 5} more")
            print()

        # Preparing (ready to submit)
        preparing = by_status.get(BatchJobStatus.PREPARING.value, [])
        if preparing:
            print(f"📝 {len(preparing)} jobs ready to submit")
            print()

        print("=" * 80)


if __name__ == "__main__":
    main()
