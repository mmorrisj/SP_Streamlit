#!/usr/bin/env python3
"""
Link a manually uploaded OpenAI batch to an existing batch_job record.

Use this when you upload a batch file via the OpenAI web interface
and want to track it using batch_monitor.py.

Usage:
    python link_manual_upload.py \
        --batch-job-id <our-database-uuid> \
        --openai-batch-id <batch_abc123>
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import BatchJob, BatchJobStatus


def link_manual_upload(batch_job_id: str, openai_batch_id: str):
    """
    Link a manually uploaded OpenAI batch to an existing batch_job record.

    Args:
        batch_job_id: UUID of the batch_job in our database
        openai_batch_id: OpenAI's batch ID from manual upload
    """
    with get_session() as session:
        # Load batch job
        batch_job = session.get(BatchJob, batch_job_id)

        if not batch_job:
            print(f"Error: Batch job not found: {batch_job_id}")
            return False

        print("Found batch job:")
        print(f"  ID: {batch_job.id}")
        print(f"  Job type: {batch_job.job_type}")
        print(f"  Country: {batch_job.initiating_country}")
        print(f"  Batch size: {batch_job.batch_size}")
        print(f"  Current status: {batch_job.status}")
        print(f"  Input file: {batch_job.input_file_path}")
        print()

        if batch_job.openai_batch_id:
            print(f"Warning: Batch job already has OpenAI batch ID: {batch_job.openai_batch_id}")
            confirm = input("Overwrite? (yes/no): ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return False

        # Update batch job
        batch_job.openai_batch_id = openai_batch_id
        batch_job.status = BatchJobStatus.SUBMITTED.value
        batch_job.submitted_at = datetime.utcnow()

        session.commit()

        print()
        print("Successfully linked OpenAI batch to database record")
        print(f"  OpenAI Batch ID: {openai_batch_id}")
        print("  Status updated to: submitted")
        print()
        print("You can now monitor this batch with:")
        print(f"  python services/pipeline/batch/batch_monitor.py --batch-job-id {batch_job_id} --auto-download")
        print()

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Link manually uploaded OpenAI batch to database record",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--batch-job-id', required=True, type=str,
                       help='UUID of batch_job in our database')
    parser.add_argument('--openai-batch-id', required=True, type=str,
                       help='OpenAI batch ID from manual upload (e.g., batch_abc123)')

    args = parser.parse_args()

    print("=" * 80)
    print("LINK MANUAL UPLOAD")
    print("=" * 80)
    print()

    success = link_manual_upload(args.batch_job_id, args.openai_batch_id)

    if not success:
        exit(1)


if __name__ == "__main__":
    main()
