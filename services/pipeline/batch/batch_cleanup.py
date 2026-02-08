"""
Stage 5: Cleanup batch processing files and resources.

Archives JSONL files to S3 (optional) and deletes OpenAI files.
Marks batch job as completed.

Usage:
    # Cleanup with S3 archiving
    python batch_cleanup.py --batch-job-id <UUID> --archive-s3

    # Cleanup without S3 archiving
    python batch_cleanup.py --batch-job-id <UUID>

    # Delete local files after archiving
    python batch_cleanup.py --batch-job-id <UUID> --archive-s3 --delete-local
"""
import argparse
import os
import sys
from pathlib import Path
from openai import OpenAI

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_config import (
    OPENAI_API_KEY_ENV,
    S3_BUCKET_ENV,
    get_s3_key
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from shared.database.database import get_session


def upload_to_s3(local_path: str, s3_key: str, bucket: str) -> bool:
    """
    Upload file to S3.

    Args:
        local_path: Local file path
        s3_key: S3 object key
        bucket: S3 bucket name

    Returns:
        True if successful, False otherwise
    """
    try:
        import boto3

        s3_client = boto3.client('s3')
        s3_client.upload_file(local_path, bucket, s3_key)

        print(f"  ✓ Uploaded to s3://{bucket}/{s3_key}")
        return True

    except ImportError:
        print("  ✗ boto3 not installed. Install with: pip install boto3")
        return False
    except Exception as e:
        print(f"  ✗ Failed to upload to S3: {e}")
        return False


def delete_openai_file(client: OpenAI, file_id: str, file_type: str = "file") -> bool:
    """
    Delete file from OpenAI.

    Args:
        client: OpenAI client
        file_id: OpenAI file ID
        file_type: Type of file (for logging)

    Returns:
        True if successful, False otherwise
    """
    try:
        client.files.delete(file_id)
        print(f"  ✓ Deleted OpenAI {file_type}: {file_id}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to delete OpenAI {file_type} {file_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Stage 5: Cleanup batch processing files and resources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--batch-job-id', required=True, type=str,
                       help='Batch job UUID from Stage 1 (batch_prepare.py)')
    parser.add_argument('--archive-s3', action='store_true',
                       help='Archive JSONL files to S3 before cleanup')
    parser.add_argument('--delete-local', action='store_true',
                       help='Delete local JSONL files after archiving (requires --archive-s3)')
    parser.add_argument('--skip-openai-delete', action='store_true',
                       help='Skip deleting files from OpenAI (keep for debugging)')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Verbose output')

    args = parser.parse_args()

    # Validate arguments
    if args.delete_local and not args.archive_s3:
        print("Error: --delete-local requires --archive-s3")
        return

    print("=" * 80)
    print("BATCH CLEANUP - Stage 5: Archive and Cleanup")
    print("=" * 80)
    print(f"Batch Job ID: {args.batch_job_id}")
    print(f"Archive to S3: {'Yes' if args.archive_s3 else 'No'}")
    print(f"Delete local files: {'Yes' if args.delete_local else 'No'}")
    print(f"Delete OpenAI files: {'No' if args.skip_openai_delete else 'Yes'}")
    print("=" * 80)
    print()

    # Initialize OpenAI client
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        print(f"Error: OpenAI API key not found. Set {OPENAI_API_KEY_ENV} environment variable.")
        return

    client = OpenAI(api_key=api_key)

    with get_session() as session:
        with BatchJobTracker(session) as tracker:
            # Load batch job
            print("Loading batch job from database...")
            batch_job = tracker.get_batch_job(args.batch_job_id)

            if not batch_job:
                print(f"Error: Batch job not found: {args.batch_job_id}")
                return

            print("✓ Loaded batch job")
            print(f"  Job type: {batch_job.job_type}")
            print(f"  Status: {batch_job.status}")
            print(f"  Input file: {batch_job.input_file_path}")
            print(f"  Output file: {batch_job.output_file_path}")
            if batch_job.error_file_path:
                print(f"  Error file: {batch_job.error_file_path}")
            print()

            # Archive to S3 if requested
            if args.archive_s3:
                print("Archiving files to S3...")

                s3_bucket = os.getenv(S3_BUCKET_ENV)
                if not s3_bucket:
                    print("  Warning: S3_BUCKET environment variable not set")
                    print("  Skipping S3 archiving")
                else:
                    # Archive input file
                    if batch_job.input_file_path and Path(batch_job.input_file_path).exists():
                        s3_key = get_s3_key(batch_job.job_type, 'input', str(batch_job.id))
                        upload_to_s3(batch_job.input_file_path, s3_key, s3_bucket)

                    # Archive output file
                    if batch_job.output_file_path and Path(batch_job.output_file_path).exists():
                        s3_key = get_s3_key(batch_job.job_type, 'output', str(batch_job.id))
                        upload_to_s3(batch_job.output_file_path, s3_key, s3_bucket)

                    # Archive error file if present
                    if batch_job.error_file_path and Path(batch_job.error_file_path).exists():
                        s3_key = get_s3_key(batch_job.job_type, 'error', str(batch_job.id))
                        upload_to_s3(batch_job.error_file_path, s3_key, s3_bucket)

                print()

            # Delete local files if requested
            if args.delete_local:
                print("Deleting local JSONL files...")

                files_to_delete = [
                    batch_job.input_file_path,
                    batch_job.output_file_path,
                    batch_job.error_file_path
                ]

                for file_path in files_to_delete:
                    if file_path and Path(file_path).exists():
                        try:
                            os.remove(file_path)
                            print(f"  ✓ Deleted: {file_path}")
                        except Exception as e:
                            print(f"  ✗ Failed to delete {file_path}: {e}")

                print()

            # Delete OpenAI files
            if not args.skip_openai_delete:
                print("Deleting OpenAI files...")

                deleted_count = 0

                # Delete input file
                if batch_job.input_file_id:
                    if delete_openai_file(client, batch_job.input_file_id, "input file"):
                        deleted_count += 1

                # Delete output file
                if batch_job.output_file_id:
                    if delete_openai_file(client, batch_job.output_file_id, "output file"):
                        deleted_count += 1

                # Delete error file if present
                if batch_job.error_file_id:
                    if delete_openai_file(client, batch_job.error_file_id, "error file"):
                        deleted_count += 1

                print(f"  Deleted {deleted_count} OpenAI files")
                print()

            # Mark batch job as completed (if not already)
            from shared.models.models import BatchJobStatus
            if batch_job.status != BatchJobStatus.COMPLETED:
                tracker.update_status(batch_job.id, BatchJobStatus.COMPLETED)
                print("✓ Updated batch_job status to 'completed'")
            else:
                print("✓ Batch job already marked as completed")

            print()
            print("=" * 80)
            print("CLEANUP COMPLETE")
            print("=" * 80)
            print(f"Batch Job ID: {batch_job.id}")
            print(f"Status: {batch_job.status}")

            if args.archive_s3:
                print("Files archived to S3: Yes")
                if args.delete_local:
                    print("Local files deleted: Yes")

            if not args.skip_openai_delete:
                print("OpenAI files deleted: Yes")

            print("=" * 80)
            print()


if __name__ == "__main__":
    main()
