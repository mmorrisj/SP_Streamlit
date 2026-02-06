#!/usr/bin/env python3
"""
Revert files that were converted to .txt for network transfer.

Reads the manifest created by convert_for_transfer.py and renames
each .txt file back to its original filename.

Usage:
    python revert_from_transfer.py [--dry-run] [--root-dir /path/to/project]
"""

import argparse
import json
import sys
from pathlib import Path

MANIFEST_FILENAME = ".transfer_manifest.json"


def main():
    parser = argparse.ArgumentParser(
        description="Revert .txt files back to their original names after network transfer"
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path("."),
        help="Root directory containing the manifest (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be renamed without making changes",
    )
    args = parser.parse_args()

    root_dir = args.root_dir.resolve()
    manifest_path = root_dir / MANIFEST_FILENAME

    if not manifest_path.exists():
        print(
            f"Error: No manifest found at {manifest_path}\n"
            "Make sure you're in the correct directory, or use --root-dir.\n"
            "The manifest is created by convert_for_transfer.py.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    entries = manifest.get("files", [])
    if not entries:
        print("Manifest contains no file entries. Nothing to revert.")
        return

    print(f"Found manifest with {len(entries)} file(s) to revert:\n")

    reverted = 0
    errors = 0

    for entry in entries:
        original_rel = Path(entry["original"])
        converted_rel = Path(entry["converted"])

        converted_abs = root_dir / converted_rel
        original_abs = root_dir / original_rel

        if not converted_abs.exists():
            # Check if already reverted
            if original_abs.exists():
                print(f"  Already reverted: {original_rel}")
                reverted += 1
            else:
                print(
                    f"  MISSING: {converted_rel} not found (and {original_rel} doesn't exist either)",
                    file=sys.stderr,
                )
                errors += 1
            continue

        if original_abs.exists():
            print(
                f"  CONFLICT: Both {converted_rel} and {original_rel} exist — skipping",
                file=sys.stderr,
            )
            errors += 1
            continue

        if args.dry_run:
            print(f"  [DRY RUN] {converted_rel} -> {original_rel}")
        else:
            try:
                converted_abs.rename(original_abs)
                print(f"  Reverted: {converted_rel} -> {original_rel}")
            except OSError as e:
                print(f"  ERROR reverting {converted_rel}: {e}", file=sys.stderr)
                errors += 1
                continue

        reverted += 1

    # Clean up manifest after successful revert
    if not args.dry_run and errors == 0:
        manifest_path.unlink()
        print(f"\nManifest removed: {manifest_path}")
    elif not args.dry_run and errors > 0:
        print(f"\nManifest kept (due to {errors} error(s)): {manifest_path}")

    summary_label = "[DRY RUN] Would revert" if args.dry_run else "Reverted"
    print(f"\n{summary_label} {reverted} file(s), {errors} error(s).")

    if args.dry_run:
        print("\nRun without --dry-run to apply changes.")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
