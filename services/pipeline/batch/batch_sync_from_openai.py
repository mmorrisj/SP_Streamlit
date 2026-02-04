#!/usr/bin/env python3
"""
Sync batch jobs from OpenAI to local database.

This script discovers batch jobs directly from the OpenAI API and syncs them
to the local batch_jobs table. Designed for multi-system setups where batch
jobs were submitted on one system and need to be pulled on another.

For each completed batch found in OpenAI:
1. Checks if a local batch_jobs record exists (by openai_batch_id)
2. If not, creates one with metadata from OpenAI
3. Downloads the output file locally
4. Updates the database record with file paths

After syncing, use batch_process_results.py to apply the results.

Usage:
    # Discover and sync all completed batches from OpenAI
    python batch_sync_from_openai.py

    # Dry run - show what would be synced
    python batch_sync_from_openai.py --dry-run

    # Sync all statuses (not just completed)
    python batch_sync_from_openai.py --status all

    # Sync a specific batch by OpenAI batch ID
    python batch_sync_from_openai.py --batch-id batch_abc123

    # Fetch more batches (default: 100)
    python batch_sync_from_openai.py --limit 50

    # Force re-download output files
    python batch_sync_from_openai.py --force
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.batch_api_client import get_batch_api_client
from services.pipeline.batch.utils.custom_id import parse_custom_id
from shared.models.models import BatchJob, BatchJobStatus
from shared.database.database import get_session

# Output directory for downloaded files
BATCHES_DIR = project_root / 'services' / 'pipeline' / 'batch' / 'batches'


def infer_job_type_from_output(content: str) -> str:
    """
    Infer job_type by parsing the first line of JSONL output.

    Args:
        content: JSONL output content string

    Returns:
        Inferred job_type or 'unknown'
    """
    try:
        first_line = content.strip().split('\n')[0]
        data = json.loads(first_line)
        custom_id = data.get('custom_id', '')
        parsed = parse_custom_id(custom_id)
        return parsed['job_type']
    except Exception:
        return 'unknown'


def infer_country_from_output(content: str) -> str:
    """
    Try to infer initiating_country from output content.

    Args:
        content: JSONL output content string

    Returns:
        Inferred country or None
    """
    try:
        first_line = content.strip().split('\n')[0]
        data = json.loads(first_line)
        # Check if the response content mentions a country
        response = data.get('response', {}).get('body', {})
        choices = response.get('choices', [])
        if choices:
            msg_content = choices[0].get('message', {}).get('content', '')
            try:
                parsed = json.loads(msg_content)
                return parsed.get('initiating_country', None)
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass
    return None


def sync_batch(
    openai_batch: dict,
    client,
    tracker: BatchJobTracker,
    session,
    force: bool = False,
    dry_run: bool = False,
) -> tuple:
    """
    Sync a single OpenAI batch to the local database.

    Returns:
        Tuple of (action, message) where action is one of:
        'created', 'exists', 'downloaded', 'skipped', 'error'
    """
    openai_id = openai_batch['id']
    status = openai_batch['status']
    request_counts = openai_batch.get('request_counts') or {}
    total = 0
    completed = 0
    failed = 0
    if hasattr(request_counts, 'total'):
        total = request_counts.total or 0
        completed = request_counts.completed or 0
        failed = request_counts.failed or 0
    elif isinstance(request_counts, dict):
        total = request_counts.get('total', 0) or 0
        completed = request_counts.get('completed', 0) or 0
        failed = request_counts.get('failed', 0) or 0

    print(f"  OpenAI ID:  {openai_id}")
    print(f"  Status:     {status}")
    print(f"  Progress:   {completed}/{total} completed, {failed} failed")
    print(f"  Created:    {datetime.fromtimestamp(openai_batch['created_at']).strftime('%Y-%m-%d %H:%M') if openai_batch.get('created_at') else 'unknown'}")

    if dry_run:
        existing = tracker.get_batch_jobs_by_openai_id(openai_id)
        if existing:
            print(f"  -> Already in local DB (job_id: {existing.id})")
            return ('exists', 'Already synced')
        else:
            print(f"  -> Would create local record and download output")
            return ('would_create', 'Would sync')

    # Check if already in local DB
    existing = tracker.get_batch_jobs_by_openai_id(openai_id)

    if existing:
        print(f"  -> Already in local DB (job_id: {existing.id})")

        # Update progress
        if total > 0:
            tracker.update_progress(existing.id, total, completed, failed)

        # Check if we need to download the output file
        output_path = existing.output_file_path
        if output_path and os.path.exists(output_path) and not force:
            print(f"  -> Output file exists: {os.path.basename(output_path)}")
            return ('exists', 'Already synced with output')

        # If completed but no output file, download it
        if status == 'completed' and openai_batch.get('output_file_id'):
            return _download_output(existing, openai_batch, client, tracker, session)

        return ('exists', 'Already synced')

    # Create new local record
    # Try to infer job_type by downloading a sample of the output
    job_type = 'unknown'
    country = None
    content = None

    if status == 'completed' and openai_batch.get('output_file_id'):
        try:
            print(f"  -> Downloading output to determine job type...")
            download_result = client.download_results(openai_id)
            content = download_result.get('content', '')
            job_type = infer_job_type_from_output(content)
            country = infer_country_from_output(content)
            print(f"  -> Inferred job_type: {job_type}")
            if country:
                print(f"  -> Inferred country: {country}")
        except Exception as e:
            print(f"  -> Could not download output: {e}")

    # Map OpenAI status to local status
    status_map = {
        'validating': BatchJobStatus.SUBMITTED.value,
        'in_progress': BatchJobStatus.IN_PROGRESS.value,
        'finalizing': BatchJobStatus.IN_PROGRESS.value,
        'completed': BatchJobStatus.COMPLETED.value,
        'failed': BatchJobStatus.FAILED.value,
        'expired': BatchJobStatus.FAILED.value,
        'cancelled': BatchJobStatus.CANCELLED.value,
        'cancelling': BatchJobStatus.CANCELLED.value,
    }
    local_status = status_map.get(status, BatchJobStatus.SUBMITTED.value)

    # Create batch job record
    batch_job = BatchJob(
        job_type=job_type,
        openai_batch_id=openai_id,
        initiating_country=country,
        batch_size=total or 0,
        status=local_status,
        input_file_id=openai_batch.get('input_file_id'),
        output_file_id=openai_batch.get('output_file_id'),
        error_file_id=openai_batch.get('error_file_id'),
        submitted_at=datetime.fromtimestamp(openai_batch['created_at']) if openai_batch.get('created_at') else None,
        completed_at=datetime.fromtimestamp(openai_batch['completed_at']) if openai_batch.get('completed_at') else None,
        created_by='batch_sync_from_openai',
        progress_metadata={
            'requests_total': total,
            'requests_completed': completed,
            'requests_failed': failed,
            'synced_from_openai': True,
            'synced_at': datetime.utcnow().isoformat(),
        },
    )

    session.add(batch_job)
    session.commit()
    session.refresh(batch_job)
    print(f"  -> Created local record: {batch_job.id}")

    # Save output file if we downloaded it
    if content and status == 'completed':
        output_path = str(BATCHES_DIR / f"{job_type}_{batch_job.id}_output.jsonl")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        file_size_kb = len(content) / 1024
        print(f"  -> Saved output: {os.path.basename(output_path)} ({file_size_kb:.1f} KB)")

        batch_job.output_file_path = output_path
        session.commit()

        return ('created', f'Synced and downloaded ({job_type})')

    return ('created', f'Synced (status: {status})')


def _download_output(
    batch_job: BatchJob,
    openai_batch: dict,
    client,
    tracker: BatchJobTracker,
    session,
) -> tuple:
    """Download output for an existing batch job that's missing its file."""
    try:
        print(f"  -> Downloading output file...")
        download_result = client.download_results(openai_batch['id'])
        content = download_result.get('content', '')

        output_path = str(BATCHES_DIR / f"{batch_job.job_type}_{batch_job.id}_output.jsonl")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        file_size_kb = len(content) / 1024
        print(f"  -> Saved: {os.path.basename(output_path)} ({file_size_kb:.1f} KB)")

        tracker.update_file_paths(
            batch_job.id,
            output_file_path=output_path,
            output_file_id=openai_batch.get('output_file_id'),
        )

        if batch_job.status != BatchJobStatus.COMPLETED.value:
            tracker.update_status(batch_job.id, BatchJobStatus.COMPLETED)

        return ('downloaded', 'Downloaded missing output')
    except Exception as e:
        return ('error', f'Download failed: {e}')


def main():
    parser = argparse.ArgumentParser(
        description="Sync batch jobs from OpenAI to local database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--batch-id', type=str,
                       help='Sync a specific OpenAI batch ID')
    parser.add_argument('--limit', type=int, default=100,
                       help='Max batches to fetch from OpenAI (default: 100)')
    parser.add_argument('--status', type=str, default='completed',
                       choices=['completed', 'in_progress', 'all'],
                       help='Only sync batches with this status (default: completed)')
    parser.add_argument('--force', action='store_true',
                       help='Force re-download output files')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be synced without making changes')

    args = parser.parse_args()

    BATCHES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("BATCH SYNC FROM OPENAI - Discover and sync batch jobs")
    print("=" * 80)
    print(f"Status filter: {args.status}")
    print(f"Limit:         {args.limit}")
    print(f"Force:         {args.force}")
    print(f"Mode:          {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Output dir:    {BATCHES_DIR}")
    print("=" * 80)
    print()

    client = get_batch_api_client()

    with get_session() as session:
        tracker = BatchJobTracker(session)

        if args.batch_id:
            # Sync a specific batch
            print(f"Fetching batch: {args.batch_id}")
            try:
                batch_info = client.get_batch_status(args.batch_id)
                batches = [batch_info]
            except Exception as e:
                print(f"ERROR: Could not fetch batch {args.batch_id}: {e}")
                return
        else:
            # List batches from OpenAI
            print("Fetching batch list from OpenAI...")
            all_batches = []
            after = None

            while True:
                result = client.list_batches(limit=min(args.limit - len(all_batches), 100), after=after)
                batch_list = result.get('batches', [])

                if not batch_list:
                    break

                all_batches.extend(batch_list)
                print(f"  Fetched {len(all_batches)} batches so far...")

                if len(all_batches) >= args.limit or not result.get('has_more'):
                    break

                after = result.get('last_id')

            batches = all_batches

        if not batches:
            print("No batches found in OpenAI.")
            return

        # Filter by status
        if args.status != 'all':
            batches = [b for b in batches if b['status'] == args.status]

        print(f"\nFound {len(batches)} batches matching criteria.")

        # Group by status for summary
        by_status = {}
        for b in batches:
            s = b['status']
            by_status[s] = by_status.get(s, 0) + 1
        for s, count in sorted(by_status.items()):
            print(f"  {s}: {count}")
        print()

        # Sync each batch
        counts = {
            'created': 0,
            'downloaded': 0,
            'exists': 0,
            'would_create': 0,
            'skipped': 0,
            'error': 0,
        }

        for i, batch in enumerate(batches, 1):
            print(f"[{i}/{len(batches)}] Batch:")
            action, message = sync_batch(
                batch, client, tracker, session,
                force=args.force, dry_run=args.dry_run,
            )
            counts[action] = counts.get(action, 0) + 1
            print(f"  Result: {message}")
            print()

        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total batches checked:   {len(batches)}")

        if args.dry_run:
            print(f"Already in local DB:     {counts['exists']}")
            print(f"Would create + download: {counts['would_create']}")
        else:
            print(f"Newly synced:            {counts['created']}")
            print(f"Downloaded missing:      {counts['downloaded']}")
            print(f"Already synced:          {counts['exists']}")
            print(f"Errors:                  {counts['error']}")
        print("=" * 80)

        if counts.get('created', 0) > 0 or counts.get('downloaded', 0) > 0:
            print()
            print("Next steps:")
            print("  Process the downloaded results:")
            print("  python batch_process_results.py --batch-job-id <id>")
            print()
            print("  Or process all completed jobs:")
            print("  python batch_process_results.py --status completed")
            print()


if __name__ == "__main__":
    main()
