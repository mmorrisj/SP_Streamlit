#!/usr/bin/env python3
"""
Migrate output files from SCRATCHPAD_DIR to batches directory.

Moves any existing output JSONL files from the old SCRATCHPAD location
to the new services/pipeline/batch/batches directory.
"""
import os
import shutil
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.pipeline.batch.batch_config import SCRATCHPAD_DIR

# Target directory
BATCHES_DIR = project_root / 'services' / 'pipeline' / 'batch' / 'batches'

def main():
    print("=" * 80)
    print("MIGRATE OUTPUT FILES - Move from SCRATCHPAD to batches directory")
    print("=" * 80)
    print(f"Source: {SCRATCHPAD_DIR}")
    print(f"Target: {BATCHES_DIR}")
    print("=" * 80)
    print()

    # Ensure target directory exists
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)

    # Check if source directory exists
    if not os.path.exists(SCRATCHPAD_DIR):
        print(f"Source directory does not exist: {SCRATCHPAD_DIR}")
        print("Nothing to migrate.")
        return

    # Find all output files in SCRATCHPAD_DIR
    scratchpad_path = Path(SCRATCHPAD_DIR)
    output_files = list(scratchpad_path.glob('*_output.jsonl'))

    if not output_files:
        print("No output files found in SCRATCHPAD directory.")
        return

    print(f"Found {len(output_files)} output files to migrate:")
    print()

    moved_count = 0
    skipped_count = 0
    error_count = 0

    for source_file in output_files:
        target_file = BATCHES_DIR / source_file.name

        print(f"Moving: {source_file.name}")
        print(f"  From: {source_file}")
        print(f"  To:   {target_file}")

        # Check if target already exists
        if target_file.exists():
            print("  ⚠️  Target already exists, skipping")
            skipped_count += 1
            print()
            continue

        try:
            # Move the file
            shutil.move(str(source_file), str(target_file))
            print("  ✓ Moved successfully")
            moved_count += 1
        except Exception as e:
            print(f"  ✗ Error: {str(e)}")
            error_count += 1

        print()

    # Summary
    print("=" * 80)
    print("MIGRATION SUMMARY")
    print("=" * 80)
    print(f"Total files found: {len(output_files)}")
    print(f"Moved: {moved_count}")
    print(f"Skipped (already exists): {skipped_count}")
    print(f"Errors: {error_count}")
    print("=" * 80)


if __name__ == "__main__":
    main()
