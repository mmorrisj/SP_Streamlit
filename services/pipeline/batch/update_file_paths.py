#!/usr/bin/env python3
"""
Update database with correct output file paths.

Scans the batches directory and updates batch_job records with the
correct output_file_path for files that exist but have wrong/missing paths.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_tracker import BatchJobTracker
from shared.models.models import BatchJobStatus
from shared.database.database import get_session

# Batches directory
BATCHES_DIR = project_root / 'services' / 'pipeline' / 'batch' / 'batches'


def main():
    print("=" * 80)
    print("UPDATE FILE PATHS - Fix database paths for existing output files")
    print("=" * 80)
    print(f"Batches directory: {BATCHES_DIR}")
    print("=" * 80)
    print()

    # Find all output files in batches directory
    output_files = list(BATCHES_DIR.glob('*_output.jsonl'))

    if not output_files:
        print("No output files found in batches directory.")
        return

    print(f"Found {len(output_files)} output files:")
    print()

    updated_count = 0
    already_correct_count = 0
    not_found_count = 0

    with get_session() as session:
        with BatchJobTracker(session) as tracker:
            for output_file in output_files:
                filename = output_file.name
                print(f"Processing: {filename}")

                # Extract batch job ID from filename
                # Format: daily_entity_extract_{batch-job-id}_output.jsonl
                parts = filename.split('_')
                if len(parts) >= 5 and parts[-1] == 'output.jsonl':
                    # Find the UUID part (between job_type and _output.jsonl)
                    batch_job_id = filename.replace(f"{parts[0]}_{parts[1]}_{parts[2]}_", "").replace("_output.jsonl", "")

                    print(f"  Batch job ID: {batch_job_id}")

                    try:
                        # Look up batch job
                        from uuid import UUID
                        job = tracker.get_batch_job(UUID(batch_job_id))

                        if not job:
                            print("  ⚠️  Batch job not found in database")
                            not_found_count += 1
                            print()
                            continue

                        correct_path = str(output_file.absolute())

                        # Check if path needs updating
                        if job.output_file_path == correct_path:
                            print("  ✓ Path already correct")
                            already_correct_count += 1
                        else:
                            print(f"  Old path: {job.output_file_path or '(empty)'}")
                            print(f"  New path: {correct_path}")

                            # Update the path
                            tracker.update_file_paths(
                                job.id,
                                output_file_path=correct_path
                            )

                            # Also update status to completed if it's not already
                            if job.status != BatchJobStatus.COMPLETED.value:
                                tracker.update_status(job.id, BatchJobStatus.COMPLETED)
                                print("  ✓ Updated status to 'completed'")

                            session.commit()
                            print("  ✓ Path updated")
                            updated_count += 1

                    except ValueError:
                        print(f"  ✗ Invalid UUID: {batch_job_id}")
                        not_found_count += 1

                else:
                    print("  ⚠️  Unexpected filename format")
                    not_found_count += 1

                print()

    # Summary
    print("=" * 80)
    print("UPDATE SUMMARY")
    print("=" * 80)
    print(f"Total files found: {len(output_files)}")
    print(f"Paths updated: {updated_count}")
    print(f"Already correct: {already_correct_count}")
    print(f"Not found in DB: {not_found_count}")
    print("=" * 80)


if __name__ == "__main__":
    main()
