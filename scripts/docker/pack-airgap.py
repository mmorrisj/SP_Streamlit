#!/usr/bin/env python3
"""
Pack an airgap deployment directory for transfer through systems that
block/redact executables, binaries, and certain file extensions.

Transformations:
  - Binary files (.tar, .dump, .bin, .safetensors, ...) → base64 encoded to .b64.txt
  - Blocked text files (.sh, .ini) → renamed to .sh.txt, .ini.txt
  - Symlinks → recorded in manifest, replaced with placeholder .txt
  - Safe text files (.txt, .json, .py, .md, ...) → left as-is

A manifest (pack_manifest.json) records all transformations.
Run unpack-airgap.py on the target system to restore everything.

Usage:
    python scripts/docker/pack-airgap.py <package-dir>              # dry run
    python scripts/docker/pack-airgap.py <package-dir> --apply      # encode/rename

Example (after airgap-build.sh --pack):
    python scripts/docker/pack-airgap.py softpower-airgap-20260217 --apply
"""

import argparse
import base64
import json
import os
import stat
import sys
from pathlib import Path

# ============================================
# Classification rules
# ============================================

# Extensions that are binary (base64 encode)
BINARY_EXTENSIONS = {
    ".tar", ".gz", ".tgz", ".zip", ".bz2", ".xz", ".zst",
    ".dump",
    ".bin", ".safetensors", ".onnx", ".pkl", ".npy", ".npz",
    ".h5", ".pt", ".pth", ".model", ".msgpack",
    ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".so", ".dll", ".dylib",
}

# Text extensions that transfer systems block (rename to .txt)
BLOCKED_TEXT_EXTENSIONS = {".sh", ".ps1", ".ini", ".bat", ".cmd"}

# Known-safe text extensions (never encode)
SAFE_TEXT_EXTENSIONS = {
    ".txt", ".json", ".yaml", ".yml", ".md", ".py",
    ".cfg", ".conf", ".example", ".sql", ".csv", ".toml",
    ".xml", ".html", ".css", ".log", ".env",
}

MANIFEST_NAME = "pack_manifest.json"


def classify_file(filepath: Path) -> str:
    """Classify a file as 'binary', 'blocked_text', or 'safe'."""
    ext = filepath.suffix.lower()
    name = filepath.name.lower()

    # Known binary extension
    if ext in BINARY_EXTENSIONS:
        return "binary"

    # Blocked text extension
    if ext in BLOCKED_TEXT_EXTENSIONS:
        return "blocked_text"

    # Known safe text
    if ext in SAFE_TEXT_EXTENSIONS:
        return "safe"

    # No extension or unknown extension — detect by content
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(8192)
        if b"\x00" in chunk:
            return "binary"
    except (IOError, OSError):
        pass

    return "safe"


def encode_b64(src: Path, dst: Path):
    """Stream base64 encode src → dst (memory efficient for large files)."""
    # Read in multiples of 3 bytes for clean base64 boundary alignment
    CHUNK = 3 * 1024 * 1024  # 3MB raw → 4MB base64
    with open(src, "rb") as fin, open(dst, "w") as fout:
        while True:
            raw = fin.read(CHUNK)
            if not raw:
                break
            fout.write(base64.b64encode(raw).decode("ascii"))


def get_perms(path: Path) -> int:
    """Get file permission bits."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return 0o644


def pack(pkg_dir: Path, dry_run: bool = True):
    manifest_path = pkg_dir / MANIFEST_NAME

    if manifest_path.exists():
        print(f"ERROR: Manifest already exists at {manifest_path}")
        print("Directory may already be packed. Run unpack-airgap.py first.")
        sys.exit(1)

    entries = []
    symlinks = []

    # Walk the directory
    for root, dirs, files in os.walk(pkg_dir):
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(pkg_dir))

            # Handle symlinks separately
            if fpath.is_symlink():
                target = os.readlink(fpath)
                symlinks.append({
                    "path": rel,
                    "target": target,
                })
                continue

            kind = classify_file(fpath)

            if kind == "binary":
                packed_rel = rel + ".b64.txt"
                entries.append({
                    "original": rel,
                    "packed": packed_rel,
                    "action": "base64",
                    "permissions": get_perms(fpath),
                    "size": fpath.stat().st_size,
                })
            elif kind == "blocked_text":
                packed_rel = rel + ".txt"
                entries.append({
                    "original": rel,
                    "packed": packed_rel,
                    "action": "rename",
                    "permissions": get_perms(fpath),
                    "size": fpath.stat().st_size,
                })
            # else: safe, no action needed

    total_binary = sum(1 for e in entries if e["action"] == "base64")
    total_rename = sum(1 for e in entries if e["action"] == "rename")
    total_symlinks = len(symlinks)
    binary_bytes = sum(e["size"] for e in entries if e["action"] == "base64")

    print(f"Package directory: {pkg_dir}")
    print(f"  {total_binary} binary file(s) to base64 encode ({binary_bytes / 1024 / 1024:.1f} MB)")
    print(f"  {total_rename} text file(s) to rename")
    print(f"  {total_symlinks} symlink(s) to record")
    print()

    for e in entries:
        action_label = "B64" if e["action"] == "base64" else "REN"
        print(f"  [{action_label}] {e['original']}  →  {e['packed']}")
    for s in symlinks:
        print(f"  [SYM] {s['path']}  →  {s['target']}")

    if dry_run:
        print(f"\nDry run. Use --apply to transform files.")
        return

    print()

    # Process binary files (base64 encode)
    for e in entries:
        src = pkg_dir / e["original"]
        dst = pkg_dir / e["packed"]
        dst.parent.mkdir(parents=True, exist_ok=True)

        if e["action"] == "base64":
            size_mb = e["size"] / 1024 / 1024
            print(f"  Encoding {e['original']} ({size_mb:.1f} MB)...", end="", flush=True)
            encode_b64(src, dst)
            src.unlink()
            print(" done")
        elif e["action"] == "rename":
            print(f"  Renaming {e['original']}  →  {e['packed']}")
            src.rename(dst)

    # Handle symlinks: record and replace with placeholder
    for s in symlinks:
        link_path = pkg_dir / s["path"]
        placeholder = pkg_dir / (s["path"] + ".symlink.txt")
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        placeholder.write_text(f"symlink target: {s['target']}\n")
        print(f"  Symlink recorded: {s['path']}  →  {s['target']}")

    # Write manifest
    manifest = {
        "description": "Packed airgap deployment. Run unpack-airgap.py --apply to restore.",
        "files": entries,
        "symlinks": symlinks,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\nManifest written: {MANIFEST_NAME}")
    print(f"Done. {len(entries)} file(s) transformed, {len(symlinks)} symlink(s) recorded.")
    print(f"\nTransfer the '{pkg_dir.name}/' directory, then on the target run:")
    print(f"  python unpack-airgap.py --apply")


def main():
    parser = argparse.ArgumentParser(
        description="Pack airgap deployment for transfer (base64 binaries, rename scripts)"
    )
    parser.add_argument("package_dir", help="Path to the airgap package directory")
    parser.add_argument("--apply", action="store_true", help="Actually transform files (default: dry run)")
    args = parser.parse_args()

    pkg_dir = Path(args.package_dir).resolve()
    if not pkg_dir.is_dir():
        print(f"ERROR: Not a directory: {pkg_dir}")
        sys.exit(1)

    pack(pkg_dir, dry_run=not args.apply)


if __name__ == "__main__":
    main()
