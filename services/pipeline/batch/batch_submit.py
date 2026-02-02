"""
Stage 2: Submit batch job to OpenAI Batch API.

Uploads JSONL input file to OpenAI and creates a batch job.
Updates batch_job record with OpenAI batch ID.

Usage:
    python batch_submit.py --batch-job-id <UUID>

    # With retry on failure
    python batch_submit.py --batch-job-id <UUID> --max-retries 3
"""
import argparse
import os
import sys
import time
from pathlib import Path
from openai import OpenAI

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_config import (
    OPENAI_API_KEY_ENV,
    OPENAI_BATCH_ENDPOINT,
    OPENAI_COMPLETION_WINDOW,
    MAX_SUBMISSION_RETRIES,
    RETRY_BACKOFF_BASE
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from shared.models.models import BatchJobStatus
from shared.database.database import get_session


def submit_batch_to_openai(
    input_file_path: str,
    batch_job_id: str,
    max_retries: int = MAX_SUBMISSION_RETRIES
) -> dict:
    """
    Submit batch job to OpenAI with retry logic.

    Args:
        input_file_path: Path to input JSONL file
        batch_job_id: Batch job ID for logging
        max_retries: Maximum number of retry attempts

    Returns:
        Dictionary with OpenAI batch response

    Raises:
        Exception: If submission fails after all retries
    """
    # Initialize OpenAI client
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        raise ValueError(f"OpenAI API key not found. Set {OPENAI_API_KEY_ENV} environment variable.")

    client = OpenAI(api_key=api_key)

    # Retry loop with exponential backoff
    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1}/{max_retries}: Uploading file to OpenAI...")

            # Upload file
            with open(input_file_path, 'rb') as f:
                batch_file = client.files.create(
                    file=f,
                    purpose="batch"
                )

            print(f"✓ File uploaded: {batch_file.id}")

            # Create batch job
            print(f"Creating batch job...")
            batch_job = client.batches.create(
                input_file_id=batch_file.id,
                endpoint=OPENAI_BATCH_ENDPOINT,
                completion_window=OPENAI_COMPLETION_WINDOW
            )

            print(f"✓ Batch job created: {batch_job.id}")

            return {
                'batch_id': batch_job.id,
                'input_file_id': batch_file.id,
                'status': batch_job.status,
                'created_at': batch_job.created_at,
                'endpoint': batch_job.endpoint,
                'completion_window': batch_job.completion_window
            }

        except Exception as e:
            print(f"✗ Attempt {attempt + 1} failed: {str(e)}")

            if attempt < max_retries - 1:
                # Exponential backoff
                wait_time = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                # Final attempt failed
                raise Exception(f"Failed to submit batch after {max_retries} attempts: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description="Stage 2: Submit batch job to OpenAI Batch API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--batch-job-id', required=True, type=str,
                       help='Batch job UUID from Stage 1 (batch_prepare.py)')
    parser.add_argument('--max-retries', type=int, default=MAX_SUBMISSION_RETRIES,
                       help=f'Maximum retry attempts (default: {MAX_SUBMISSION_RETRIES})')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Verbose output')

    args = parser.parse_args()

    print("=" * 80)
    print("BATCH SUBMIT - Stage 2: Submit to OpenAI Batch API")
    print("=" * 80)
    print(f"Batch Job ID: {args.batch_job_id}")
    print(f"Max retries: {args.max_retries}")
    print("=" * 80)
    print()

    with get_session() as session:
        with BatchJobTracker(session) as tracker:
            # Load batch job
            print("Loading batch job from database...")
            batch_job = tracker.get_batch_job(args.batch_job_id)

            if not batch_job:
                print(f"Error: Batch job not found: {args.batch_job_id}")
                return

            print(f"✓ Loaded batch job")
            print(f"  Job type: {batch_job.job_type}")
            print(f"  Batch size: {batch_job.batch_size}")
            print(f"  Status: {batch_job.status.value}")
            print(f"  Input file: {batch_job.input_file_path}")
            print()

            # Validate status
            if batch_job.status != BatchJobStatus.PREPARING:
                print(f"Warning: Batch job status is '{batch_job.status.value}', expected 'preparing'")
                print(f"Continuing anyway...")
                print()

            # Check input file exists
            if not os.path.exists(batch_job.input_file_path):
                print(f"Error: Input file not found: {batch_job.input_file_path}")
                return

            # Submit to OpenAI
            try:
                print("Submitting batch to OpenAI...")
                print()

                result = submit_batch_to_openai(
                    batch_job.input_file_path,
                    args.batch_job_id,
                    args.max_retries
                )

                print()
                print("=" * 80)
                print("SUBMISSION SUCCESSFUL")
                print("=" * 80)
                print(f"OpenAI Batch ID: {result['batch_id']}")
                print(f"Input File ID: {result['input_file_id']}")
                print(f"Status: {result['status']}")
                print(f"Endpoint: {result['endpoint']}")
                print(f"Completion window: {result['completion_window']}")
                print("=" * 80)
                print()

                # Update batch_job record
                print("Updating batch_job record...")
                tracker.update_openai_batch_id(
                    batch_job.id,
                    result['batch_id'],
                    result['input_file_id']
                )
                print("✓ Updated batch_job with OpenAI batch ID")

                # Increment retry count if this wasn't the first attempt
                if batch_job.retry_count > 0:
                    print(f"  Note: This was retry attempt #{batch_job.retry_count + 1}")

            except Exception as e:
                print()
                print("=" * 80)
                print("SUBMISSION FAILED")
                print("=" * 80)
                print(f"Error: {str(e)}")
                print("=" * 80)
                print()

                # Update batch_job with error
                tracker.update_status(
                    batch_job.id,
                    BatchJobStatus.FAILED,
                    error_message=str(e)
                )
                tracker.increment_retry_count(batch_job.id)
                print("✓ Updated batch_job status to 'failed'")
                return

            print()
            print("Next step: Monitor batch status")
            print(f"  python batch_monitor.py --batch-job-id {batch_job.id}")
            print()


if __name__ == "__main__":
    main()
