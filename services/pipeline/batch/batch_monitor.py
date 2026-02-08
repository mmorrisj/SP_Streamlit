"""
Stage 3: Monitor OpenAI Batch API job status.

Polls OpenAI batch status until completion and downloads result files.

Usage:
    # Monitor with auto-download
    python batch_monitor.py --batch-job-id <UUID> --auto-download

    # Monitor only (manual download)
    python batch_monitor.py --batch-job-id <UUID>

    # Custom poll interval
    python batch_monitor.py --batch-job-id <UUID> --poll-interval 120
"""
import argparse
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_config import (
    DEFAULT_POLL_INTERVAL,
    MAX_POLL_DURATION,
    get_batch_file_path
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.batch_api_client import get_batch_api_client
from shared.models.models import BatchJobStatus
from shared.database.database import get_session


def monitor_batch_job(
    openai_batch_id: str,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    max_duration: int = MAX_POLL_DURATION,
    verbose: bool = True
) -> dict:
    """
    Monitor OpenAI batch job until completion (via proxy).

    Args:
        openai_batch_id: OpenAI batch ID
        poll_interval: Polling interval in seconds
        max_duration: Maximum polling duration in seconds
        verbose: Print progress

    Returns:
        Dictionary with final batch status

    Raises:
        TimeoutError: If max_duration exceeded
        Exception: If batch fails
    """
    # Initialize proxy client
    client = get_batch_api_client()
    start_time = datetime.now()

    while True:
        # Check if max duration exceeded
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > max_duration:
            raise TimeoutError(f"Batch monitoring exceeded max duration of {max_duration}s ({max_duration/3600:.1f}h)")

        # Retrieve batch status via proxy
        batch = client.get_batch_status(openai_batch_id)

        status = batch['status']
        request_counts = batch.get('request_counts', {})

        if verbose and request_counts:
            print(f"\\r[{datetime.now().strftime('%H:%M:%S')}] Status: {status} | "
                  f"Completed: {request_counts.get('completed', 0)}/{request_counts.get('total', 0)} | "
                  f"Failed: {request_counts.get('failed', 0)} | "
                  f"Elapsed: {elapsed/60:.1f}m", end='', flush=True)

        # Check terminal states
        if status == 'completed':
            print()  # New line after progress
            return {
                'status': status,
                'request_counts': request_counts or {'total': 0, 'completed': 0, 'failed': 0},
                'output_file_id': batch.get('output_file_id'),
                'error_file_id': batch.get('error_file_id'),
                'completed_at': batch.get('completed_at'),
                'elapsed_seconds': elapsed
            }

        elif status == 'failed':
            print()  # New line after progress
            error_msg = batch.get('errors', 'Unknown error')
            raise Exception(f"Batch failed: {error_msg}")

        elif status == 'cancelled':
            print()  # New line after progress
            raise Exception("Batch was cancelled")

        elif status == 'expired':
            print()  # New line after progress
            raise Exception("Batch expired (exceeded 24h completion window)")

        # Wait before next poll
        time.sleep(poll_interval)


def download_batch_results(
    openai_batch_id: str,
    output_path: str
) -> dict:
    """
    Download batch result files from OpenAI (via proxy).

    Args:
        openai_batch_id: OpenAI batch ID
        output_path: Local path to save output

    Returns:
        Dictionary with download info
    """
    # Initialize proxy client
    client = get_batch_api_client()
    results = {}

    # Download output file via proxy
    print("Downloading output file via proxy...")
    download_result = client.download_results(openai_batch_id)
    content = download_result['content']

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    results['output_file'] = output_path
    results['output_size_bytes'] = len(content.encode('utf-8'))
    results['output_file_id'] = download_result.get('output_file_id')
    print(f"✓ Downloaded output: {output_path} ({results['output_size_bytes']} bytes)")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Stage 3: Monitor OpenAI Batch API job status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--batch-job-id', required=True, type=str,
                       help='Batch job UUID from Stage 2 (batch_submit.py)')
    parser.add_argument('--poll-interval', type=int, default=DEFAULT_POLL_INTERVAL,
                       help=f'Polling interval in seconds (default: {DEFAULT_POLL_INTERVAL})')
    parser.add_argument('--max-duration', type=int, default=MAX_POLL_DURATION,
                       help=f'Maximum polling duration in seconds (default: {MAX_POLL_DURATION})')
    parser.add_argument('--auto-download', action='store_true',
                       help='Automatically download results when complete')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Verbose output')

    args = parser.parse_args()

    print("=" * 80)
    print("BATCH MONITOR - Stage 3: Monitor OpenAI Batch Status")
    print("=" * 80)
    print(f"Batch Job ID: {args.batch_job_id}")
    print(f"Poll interval: {args.poll_interval}s")
    print(f"Max duration: {args.max_duration}s ({args.max_duration/3600:.1f}h)")
    print(f"Auto-download: {'Yes' if args.auto_download else 'No'}")
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

            if not batch_job.openai_batch_id:
                print("Error: Batch job has no OpenAI batch ID. Was it submitted?")
                return

            print("✓ Loaded batch job")
            print(f"  OpenAI Batch ID: {batch_job.openai_batch_id}")
            print(f"  Status: {batch_job.status}")
            print(f"  Batch size: {batch_job.batch_size}")
            print()

            # Monitor batch
            try:
                print("Monitoring batch status (press Ctrl+C to stop)...")
                print()

                result = monitor_batch_job(
                    batch_job.openai_batch_id,
                    poll_interval=args.poll_interval,
                    max_duration=args.max_duration,
                    verbose=args.verbose
                )

                print()
                print("=" * 80)
                print("BATCH COMPLETED")
                print("=" * 80)
                print(f"Status: {result['status']}")
                print(f"Completed: {result['request_counts']['completed']}/{result['request_counts']['total']}")
                print(f"Failed: {result['request_counts']['failed']}")
                print(f"Elapsed time: {result['elapsed_seconds']/60:.1f} minutes")
                print(f"Output file ID: {result['output_file_id']}")
                if result.get('error_file_id'):
                    print(f"Error file ID: {result['error_file_id']}")
                print("=" * 80)
                print()

                # Update batch_job with progress
                tracker.update_progress(
                    batch_job.id,
                    result['request_counts']['total'],
                    result['request_counts']['completed'],
                    result['request_counts']['failed']
                )
                tracker.update_status(batch_job.id, BatchJobStatus.COMPLETED)
                print("✓ Updated batch_job status to 'completed'")

                # Auto-download if requested
                if args.auto_download:
                    print()
                    print("Downloading result files...")

                    # Generate output file paths
                    output_path = get_batch_file_path(
                        batch_job.job_type,
                        'output',
                        batch_job_id=str(batch_job.id)
                    )

                    error_path = None
                    if result.get('error_file_id'):
                        error_path = get_batch_file_path(
                            batch_job.job_type,
                            'error',
                            batch_job_id=str(batch_job.id)
                        )

                    download_result = download_batch_results(
                        batch_job.openai_batch_id,
                        output_path
                    )

                    # Update batch_job with file paths
                    tracker.update_file_paths(
                        batch_job.id,
                        output_file_path=output_path,
                        output_file_id=result['output_file_id'],
                        error_file_path=error_path if error_path else None,
                        error_file_id=result.get('error_file_id')
                    )
                    print("✓ Updated batch_job with output file paths")

                    print()
                    print("Next step: Process results")
                    print(f"  python batch_process_results.py --batch-job-id {batch_job.id}")

                else:
                    print()
                    print("Manual download required:")
                    print(f"  Output file ID: {result['output_file_id']}")
                    if result.get('error_file_id'):
                        print(f"  Error file ID: {result['error_file_id']}")
                    print()
                    print("To download:")
                    print(f"  python batch_monitor.py --batch-job-id {batch_job.id} --auto-download")

            except KeyboardInterrupt:
                print()
                print()
                print("Monitoring interrupted by user.")
                print("Batch job is still running on OpenAI.")
                print("Run this command again to resume monitoring.")
                return

            except Exception as e:
                print()
                print("=" * 80)
                print("BATCH FAILED")
                print("=" * 80)
                print(f"Error: {str(e)}")
                print("=" * 80)

                # Update batch_job with error
                tracker.update_status(
                    batch_job.id,
                    BatchJobStatus.FAILED,
                    error_message=str(e)
                )
                print("✓ Updated batch_job status to 'failed'")
                return

    print()


if __name__ == "__main__":
    main()
