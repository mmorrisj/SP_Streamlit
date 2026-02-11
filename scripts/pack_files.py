#!/usr/bin/env python3
"""
Pack redacted file types for transfer to systems that block them.

Finds all files matching blocked extensions (.sh, .ps1, .tsx, .js, .ini)
and blocked filenames (Dockerfile*, .gitignore, .dockerignore) in the repo,
renames them to .txt, and records a manifest so they can be restored later
with unpack_files.py.

Excludes: _archive/, .git/, node_modules/, __pycache__/, venv/

Usage:
    python scripts/pack_executables.py          # dry run (default)
    python scripts/pack_executables.py --apply  # actually rename files
"""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

# Extensions that get blocked (matched case-insensitively)
BLOCKED_EXTENSIONS = {".sh", ".ps1", ".tsx", ".js", ".ini"}

# Exact filenames that get blocked (matched case-insensitively)
BLOCKED_EXACT_NAMES = {".gitignore", ".dockerignore"}

# Filename prefixes that get blocked (e.g. Dockerfile, Dockerfile.api)
BLOCKED_NAME_PREFIXES = {"dockerfile"}

EXCLUDED_DIRS = {"_archive", ".git", "node_modules", "__pycache__", "venv", ".venv"}

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


def get_file_permissions(path: Path) -> int:
    """Get the octal permission bits of a file."""
    return stat.S_IMODE(path.stat().st_mode)


def is_blocked(fname: str) -> bool:
    """Check if a filename matches any blocked pattern."""
    lower = fname.lower()
    # Check extension
    _, ext = os.path.splitext(lower)
    if ext in BLOCKED_EXTENSIONS:
        return True
    # Check exact name
    if lower in BLOCKED_EXACT_NAMES:
        return True
    # Check prefix (handles Dockerfile, Dockerfile.api, etc.)
    for prefix in BLOCKED_NAME_PREFIXES:
        if lower == prefix or lower.startswith(prefix + "."):
            return True
    return False


def find_blocked_files(repo_root: Path) -> list[dict]:
    """Find all files matching blocked types, excluding certain directories."""
    results = []
    for root, dirs, files in os.walk(repo_root):
        # Prune excluded directories in-place to avoid descending into them
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

        for fname in files:
            if is_blocked(fname):
                fpath = Path(root) / fname
                rel_path = str(fpath.relative_to(repo_root))
                results.append({
                    "original_path": rel_path,
                    "packed_path": rel_path + ".txt",
                    "permissions": get_file_permissions(fpath),
                })
    results.sort(key=lambda x: x["original_path"])
    return results


def pack(repo_root: Path, dry_run: bool = True) -> None:
    manifest_path = repo_root / MANIFEST_FILENAME

    if manifest_path.exists():
        print(f"ERROR: Manifest already exists at {manifest_path}")
        print("Files may already be packed. Run unpack_files.py first,")
        print("or delete the manifest if you're sure files are in original state.")
        sys.exit(1)

    files = find_blocked_files(repo_root)

    if not files:
        print("No blocked files found to pack.")
        return

    print(f"Found {len(files)} file(s) to pack:\n")
    for entry in files:
        print(f"  {entry['original_path']}  ->  {entry['packed_path']}")

    if dry_run:
        print(f"\nDry run complete. Use --apply to rename files.")
        return

    # Rename files
    for entry in files:
        src = repo_root / entry["original_path"]
        dst = repo_root / entry["packed_path"]
        src.rename(dst)
        print(f"  Renamed: {entry['original_path']}  ->  {entry['packed_path']}")

    # Write manifest
    manifest = {
        "description": "Manifest for packed files. Use unpack_files.py to restore.",
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nManifest written to {MANIFEST_FILENAME}")
    print(f"\nDone. {len(files)} file(s) packed. Transfer the repo, then run:")
    print(f"  python scripts/unpack_files.py")


def main():
    parser = argparse.ArgumentParser(
        description="Pack executable files for transfer (rename to .txt)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rename files (default is dry run)",
    )
    args = parser.parse_args()

    repo_root = find_repo_root()
    print(f"Repo root: {repo_root}\n")
    pack(repo_root, dry_run=not args.apply)


if __name__ == "__main__":
    main()