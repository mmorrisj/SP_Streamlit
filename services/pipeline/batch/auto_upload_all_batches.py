#!/usr/bin/env python3
"""
Automatically upload all preparing batches via FastAPI proxy.

This script:
1. Finds all batch_jobs with status='preparing'
2. Uploads each via FastAPI proxy (uses host's OpenAI connection)
3. Parses the OpenAI batch ID from response
4. Updates database with openai_batch_id and status='submitted'

IMPORTANT: OpenAI has an enqueued token limit (varies by usage tier, typically 1-2M tokens).
Submitting too many batches at once will hit this limit. Use --max-uploads to control
the number of batches submitted per run.

Usage:
    # Upload 10 batches at a time (recommended)
    python auto_upload_all_batches.py --job-type daily_entity_extract --max-uploads 10

    # Upload all Iran batches (respects max-uploads default)
    python auto_upload_all_batches.py --job-type daily_entity_extract --country Iran

    # Dry run to see what would be uploaded
    python auto_upload_all_batches.py --dry-run
"""
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import BatchJob, BatchJobStatus
from services.pipeline.batch.utils.batch_api_client import get_batch_api_client

# Load .env
env_path = project_root / '.env'
load_dotenv(env_path)

api_key = os.getenv('OPENAI_PROJ_API')
if not api_key:
    print("❌ Error: OPENAI_PROJ_API not found in .env")
    sys.exit(1)


def upload_via_proxy(batch_file: str, client) -> dict:
    """
    Upload batch file via FastAPI proxy (uses host's OpenAI connection).

    Args:
        batch_file: Path to JSONL file
        client: BatchAPIClient instance

    Returns:
        Dictionary with OpenAI response (includes 'file_id' field)

    Raises:
        Exception: If upload fails
    """
    if not os.path.exists(batch_file):
        raise FileNotFoundError(f"Batch file not found: {batch_file}")

    file_size_mb = os.path.getsize(batch_file) / 1024 / 1024
    print(f"  File: {os.path.basename(batch_file)}")
    print(f"  Size: {file_size_mb:.2f} MB")
    print("  Uploading via FastAPI proxy...")

    try:
        response = client.upload_file(batch_file)

        if 'file_id' not in response:
            raise Exception(f"No 'file_id' in response: {response}")

        print("  ✓ Uploaded successfully")
        print(f"  File ID: {response['file_id']}")

        return response

    except Exception as e:
        print("  ✗ Upload failed")
        print(f"  Error: {str(e)}")
        raise Exception(f"Proxy upload failed: {str(e)}")


def create_batch_job_via_proxy(file_id: str, client) -> dict:
    """
    Create OpenAI batch job from uploaded file via FastAPI proxy.

    Args:
        file_id: OpenAI file ID from upload
        client: BatchAPIClient instance

    Returns:
        Dictionary with batch job response (includes 'id' field with batch ID)
    """
    print("  Creating batch job...")

    try:
        response = client.create_batch(
            input_file_id=file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )

        if 'id' not in response:
            raise Exception(f"No 'id' in response: {response}")

        print("  ✓ Batch job created")
        print(f"  Batch ID: {response['id']}")

        return response

    except Exception as e:
        print("  ✗ Batch creation failed")
        print(f"  Error: {str(e)}")
        raise Exception(f"Batch creation failed: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description="Automatically upload all preparing batches via Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--job-type', type=str,
                       help='Filter by job type (e.g., daily_entity_extract)')
    parser.add_argument('--country', type=str,
                       help='Filter by country')
    parser.add_argument('--max-uploads', type=int, default=10,
                       help='Maximum number of batches to upload per run (default: 10, prevents hitting OpenAI enqueued token limit)')
    parser.add_argument('--no-limit', action='store_true',
                       help='Remove max-uploads limit (WARNING: may hit OpenAI enqueued token limit)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be uploaded without actually uploading')

    args = parser.parse_args()

    # Handle --no-limit flag
    if args.no_limit:
        max_uploads = None
    else:
        max_uploads = args.max_uploads

    print("=" * 80)
    print("AUTO UPLOAD ALL BATCHES")
    print("=" * 80)
    if max_uploads:
        print(f"Max uploads per run: {max_uploads}")
        print("(Use --no-limit to remove this restriction, but may hit OpenAI token limits)")
    else:
        print("⚠️  WARNING: No upload limit set - may hit OpenAI enqueued token limit!")
    print("=" * 80)
    print()

    # Query batch jobs
    with get_session() as session:
        query = session.query(BatchJob).filter(
            BatchJob.status == BatchJobStatus.PREPARING.value
        )

        if args.job_type:
            query = query.filter(BatchJob.job_type == args.job_type)

        if args.country:
            query = query.filter(BatchJob.initiating_country == args.country)

        query = query.order_by(BatchJob.created_at.asc())

        if max_uploads:
            query = query.limit(max_uploads)

        batch_jobs = query.all()

        if not batch_jobs:
            print("No batch jobs with status='preparing' found.")
            return

        print(f"Found {len(batch_jobs)} batch jobs to upload:")
        print()

        for i, job in enumerate(batch_jobs, 1):
            print(f"{i}. {job.id}")
            print(f"   Job type: {job.job_type}")
            print(f"   Country: {job.initiating_country}")
            print(f"   Batch size: {job.batch_size}")
            file_path = job.input_file_path.replace('\\', '/')
            if not os.path.isabs(file_path):
                file_path = str(project_root / file_path)
            print(f"   File: {file_path}")

            if not os.path.exists(file_path):
                print("   ⚠️  Warning: File not found!")

            print()

        if args.dry_run:
            print("DRY RUN - No uploads performed")
            return

        # Check for currently running batches
        running_query = session.query(BatchJob).filter(
            BatchJob.status.in_([
                BatchJobStatus.SUBMITTED.value,
                BatchJobStatus.IN_PROGRESS.value
            ])
        )
        if args.job_type:
            running_query = running_query.filter(BatchJob.job_type == args.job_type)

        running_count = running_query.count()

        if running_count > 0:
            print(f"⚠️  WARNING: {running_count} batches are currently running/submitted.")
            print(f"Adding {len(batch_jobs)} more may exceed OpenAI's enqueued token limit.")
            print("Consider waiting for some batches to complete before uploading more.")
            print()

        # Confirm before proceeding
        confirm = input(f"Upload {len(batch_jobs)} batches? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            return

        print()
        print("=" * 80)
        print("UPLOADING BATCHES")
        print("=" * 80)
        print()

        # Initialize batch API client (uses FastAPI proxy)
        client = get_batch_api_client()
        print()

        success_count = 0
        fail_count = 0

        for i, job in enumerate(batch_jobs, 1):
            print(f"[{i}/{len(batch_jobs)}] Uploading batch: {job.id}")
            print(f"  Country: {job.initiating_country}")
            print(f"  Batch size: {job.batch_size}")

            try:
                # Resolve file path (handle relative paths and Windows backslashes in Docker)
                file_path = job.input_file_path.replace('\\', '/')
                if not os.path.isabs(file_path):
                    file_path = str(project_root / file_path)

                # Check file exists
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"File not found: {file_path}")

                # Upload file via proxy
                file_response = upload_via_proxy(file_path, client)
                file_id = file_response['file_id']

                # Create batch job via proxy
                batch_response = create_batch_job_via_proxy(file_id, client)
                openai_batch_id = batch_response['id']

                # Update database
                job.openai_batch_id = openai_batch_id
                job.input_file_id = file_id
                job.status = BatchJobStatus.SUBMITTED.value
                job.submitted_at = datetime.utcnow()
                session.commit()

                print("  ✓ Database updated")
                print("  Status: preparing → submitted")
                print()

                success_count += 1

            except Exception as e:
                print(f"  ✗ FAILED: {str(e)}")
                print()

                # Update status to failed
                job.status = BatchJobStatus.FAILED.value
                job.error_message = str(e)
                session.commit()

                fail_count += 1

                # Ask if user wants to continue
                if i < len(batch_jobs):
                    continue_upload = input("Continue with remaining batches? (yes/no): ")
                    if continue_upload.lower() != 'yes':
                        print("Stopping uploads.")
                        break

        print()
        print("=" * 80)
        print("UPLOAD SUMMARY")
        print("=" * 80)
        print(f"Total: {len(batch_jobs)}")
        print(f"Successful: {success_count}")
        print(f"Failed: {fail_count}")
        print()

        if success_count > 0:
            print("Next steps:")
            print("  1. Monitor batches: python services/pipeline/batch/batch_monitor.py --batch-job-id <id> --auto-download")
            print("  2. Or use batch runner to monitor all")

        print()


if __name__ == "__main__":
    main()
