#!/usr/bin/env python3
"""
Unpack files after transfer.

Reads the manifest created by pack_files.py and restores files to their
original names and permissions. Empty file placeholders are truncated back
to 0 bytes.

Usage:
    python scripts/unpack_files.py          # dry run (default)
    python scripts/unpack_files.py --apply  # actually restore files
"""

import argparse
import json
import os
import sys
from pathlib import Path

MANIFEST_FILENAME = ".packed_manifest.json"


def find_repo_root() -> Path:
    """Walk up from this script's location to find the repo root (contains .git)."""
    path = Path(__file__).resolve().parent
    while path != path.parent:
        if (path / ".git").exists():
            return path
        path = path.parent
    # Fallback: assume parent of scripts/
    return Path(__file__).resolve().parent.parent


def unpack(repo_root: Path, dry_run: bool = True) -> None:
    manifest_path = repo_root / MANIFEST_FILENAME

    if not manifest_path.exists():
        print(f"ERROR: No manifest found at {manifest_path}")
        print("Run pack_executables.py --apply first to create one.")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    files = manifest["files"]

    if not files:
        print("Manifest is empty. Nothing to unpack.")
        return

    print(f"Found {len(files)} file(s) to unpack:\n")

    missing = []
    for entry in files:
        packed = repo_root / entry["packed_path"]
        original = entry["original_path"]
        perms = oct(entry["permissions"])
        exists = packed.exists()
        status = "" if exists else "  [MISSING]"
        if entry.get("empty_placeholder"):
            print(f"  [MTY] {original}  (placeholder -> empty){status}")
        else:
            print(f"  [REN] {entry['packed_path']}  ->  {original}  (perms: {perms}){status}")
        if not exists:
            missing.append(entry["packed_path"])

    if missing:
        print(f"\nWARNING: {len(missing)} packed file(s) not found.")
        print("These will be skipped during unpack.")

    if dry_run:
        print(f"\nDry run complete. Use --apply to restore files.")
        return

    restored = 0
    skipped = 0
    for entry in files:
        packed = repo_root / entry["packed_path"]
        original = repo_root / entry["original_path"]

        if not packed.exists():
            print(f"  SKIP (missing): {entry['packed_path']}")
            skipped += 1
            continue

        if entry.get("empty_placeholder"):
            # Truncate back to 0 bytes (remove placeholder content)
            original.write_bytes(b"")
            print(f"  Emptied:   {entry['original_path']}")
        else:
            packed.rename(original)
            print(f"  Restored:  {entry['original_path']}  (perms: {oct(entry['permissions'])})")

        os.chmod(original, entry["permissions"])
        restored += 1

    # Remove manifest
    manifest_path.unlink()
    print(f"\nManifest removed.")
    print(f"\nDone. {restored} file(s) restored, {skipped} skipped.")


def main():
    parser = argparse.ArgumentParser(
        description="Unpack executable files after transfer (restore from .txt)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually restore files (default is dry run)",
    )
    args = parser.parse_args()

    repo_root = find_repo_root()
    print(f"Repo root: {repo_root}\n")
    unpack(repo_root, dry_run=not args.apply)


if __name__ == "__main__":
    main()