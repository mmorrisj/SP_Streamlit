#!/usr/bin/env python3
"""
Convert files that get redacted by security scans during network transfers.

Renames .tsx, .ts, .sh, .ps1, Dockerfile*, and docker-compose*.yml files to .txt
and writes a manifest so they can be reverted on the other side.

Usage:
    python convert_for_transfer.py [--dry-run] [--root-dir /path/to/project]
    python convert_for_transfer.py --add-ext .jsx .mjs .cjs
    python convert_for_transfer.py --add-name Makefile Vagrantfile
    python convert_for_transfer.py --add-ext .jsx --add-name Makefile --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# File extensions to convert
EXTENSIONS_TO_CONVERT = {".tsx", ".ts", ".sh", ".ps1", ".bat", ".exe"}

# Exact filenames (case-insensitive stem matching) to convert
DOCKERFILE_NAMES = {"dockerfile"}

# Filename prefixes for docker-compose files
DOCKER_COMPOSE_PREFIX = "docker-compose"

MANIFEST_FILENAME = ".transfer_manifest.json"

# Directories to skip
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "env", ".env", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build",
}


def should_convert(file_path: Path, extra_extensions: set[str], extra_names: set[str]) -> bool:
    """Determine if a file should be converted to .txt for transfer."""
    name = file_path.name
    suffix = file_path.suffix.lower()
    stem = file_path.stem.lower()

    # Already a .txt file — skip
    if suffix == ".txt":
        return False

    # Match by extension (built-in + user-added)
    if suffix in EXTENSIONS_TO_CONVERT or suffix in extra_extensions:
        return True

    # Match by exact filename (case-insensitive, user-added)
    if name.lower() in extra_names:
        return True

    # Match Dockerfile (with or without extension, e.g., Dockerfile, api.Dockerfile)
    if stem == "dockerfile" or name.lower() == "dockerfile":
        return True
    if suffix.lower() == ".dockerfile":
        return True

    # Match docker-compose*.yml / docker-compose*.yaml
    if name.lower().startswith(DOCKER_COMPOSE_PREFIX) and suffix in {".yml", ".yaml"}:
        return True

    return False


def collect_files(root_dir: Path, extra_extensions: set[str], extra_names: set[str]) -> list[Path]:
    """Walk the directory tree and collect files that need conversion."""
    targets = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.name == MANIFEST_FILENAME:
                continue
            if should_convert(fpath, extra_extensions, extra_names):
                targets.append(fpath)
    return sorted(targets)


def convert_file(file_path: Path) -> Path:
    """Rename a file to .txt and return the new path."""
    new_path = file_path.with_name(file_path.name + ".txt")
    # Handle collision (unlikely but safe)
    if new_path.exists():
        raise FileExistsError(f"Target already exists: {new_path}")
    file_path.rename(new_path)
    return new_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert security-sensitive file types to .txt for network transfer"
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path("."),
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be renamed without making changes",
    )
    parser.add_argument(
        "--add-ext",
        nargs="+",
        default=[],
        metavar="EXT",
        help="Additional file extensions to convert (e.g. .jsx .mjs .wasm)",
    )
    parser.add_argument(
        "--add-name",
        nargs="+",
        default=[],
        metavar="NAME",
        help="Additional exact filenames to convert (e.g. Makefile Vagrantfile)",
    )
    args = parser.parse_args()

    # Normalize extra extensions: ensure they start with a dot and are lowercase
    extra_extensions = set()
    for ext in args.add_ext:
        ext = ext if ext.startswith(".") else f".{ext}"
        extra_extensions.add(ext.lower())

    # Normalize extra names to lowercase for case-insensitive matching
    extra_names = {n.lower() for n in args.add_name}

    root_dir = args.root_dir.resolve()
    if not root_dir.is_dir():
        print(f"Error: {root_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    manifest_path = root_dir / MANIFEST_FILENAME

    if manifest_path.exists():
        print(
            f"Error: Manifest already exists at {manifest_path}\n"
            "Files may already be converted. Run revert_from_transfer.py first,\n"
            "or delete the manifest if you want to start fresh.",
            file=sys.stderr,
        )
        sys.exit(1)

    if extra_extensions or extra_names:
        print("Additional file types included:")
        if extra_extensions:
            print(f"  Extensions: {', '.join(sorted(extra_extensions))}")
        if extra_names:
            print(f"  Filenames:  {', '.join(sorted(extra_names))}")
        print()

    targets = collect_files(root_dir, extra_extensions, extra_names)

    if not targets:
        print("No files found that need conversion.")
        return

    print(f"Found {len(targets)} file(s) to convert:\n")

    manifest_entries = []

    for fpath in targets:
        rel_original = fpath.relative_to(root_dir)
        rel_converted = Path(str(rel_original) + ".txt")

        if args.dry_run:
            print(f"  [DRY RUN] {rel_original} -> {rel_converted}")
        else:
            try:
                convert_file(fpath)
                print(f"  Converted: {rel_original} -> {rel_converted}")
            except FileExistsError as e:
                print(f"  SKIPPED (collision): {e}", file=sys.stderr)
                continue

        manifest_entries.append(
            {
                "original": str(rel_original),
                "converted": str(rel_converted),
            }
        )

    if not args.dry_run and manifest_entries:
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root_dir": str(root_dir),
            "file_count": len(manifest_entries),
            "default_extensions": sorted(EXTENSIONS_TO_CONVERT),
            "extra_extensions": sorted(extra_extensions) if extra_extensions else [],
            "extra_names": sorted(extra_names) if extra_names else [],
            "files": manifest_entries,
        }
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"\nManifest written to: {manifest_path}")

    summary_label = "[DRY RUN] Would convert" if args.dry_run else "Converted"
    print(f"\n{summary_label} {len(manifest_entries)} file(s).")

    if args.dry_run:
        print("\nRun without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
