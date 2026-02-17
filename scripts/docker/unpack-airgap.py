#!/usr/bin/env python3
"""
Unpack an airgap deployment directory after transfer.

Reverses all transformations made by pack-airgap.py:
  - .b64.txt files → base64 decoded back to original binary
  - .sh.txt files → renamed back to .sh
  - .symlink.txt placeholders → recreated as actual symlinks

Reads the manifest (pack_manifest.json) written by pack-airgap.py.

Usage:
    cd softpower-airgap-YYYYMMDD
    python unpack-airgap.py              # dry run (shows what would be restored)
    python unpack-airgap.py --apply      # actually restore files
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

MANIFEST_NAME = "pack_manifest.json"


def decode_b64(src: Path, dst: Path):
    """Stream base64 decode src → dst (memory efficient for large files)."""
    # Read in multiples of 4 chars for clean base64 boundary alignment
    CHUNK = 4 * 1024 * 1024  # 4MB base64 → 3MB raw
    with open(src, "r") as fin, open(dst, "wb") as fout:
        while True:
            encoded = fin.read(CHUNK)
            if not encoded:
                break
            fout.write(base64.b64decode(encoded))


def unpack(pkg_dir: Path, dry_run: bool = True):
    manifest_path = pkg_dir / MANIFEST_NAME

    if not manifest_path.exists():
        print(f"ERROR: No manifest found at {manifest_path}")
        print("This directory may not have been packed, or the manifest was lost.")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("files", [])
    symlinks = manifest.get("symlinks", [])

    total_b64 = sum(1 for e in entries if e["action"] == "base64")
    total_ren = sum(1 for e in entries if e["action"] == "rename")

    print(f"Package directory: {pkg_dir}")
    print(f"  {total_b64} file(s) to base64 decode")
    print(f"  {total_ren} file(s) to rename")
    print(f"  {len(symlinks)} symlink(s) to recreate")
    print()

    # Check for missing files
    missing = []
    for e in entries:
        packed_path = pkg_dir / e["packed"]
        exists = packed_path.exists()
        action_label = "B64" if e["action"] == "base64" else "REN"
        status = "" if exists else "  [MISSING]"
        print(f"  [{action_label}] {e['packed']}  →  {e['original']}{status}")
        if not exists:
            missing.append(e["packed"])

    for s in symlinks:
        placeholder = pkg_dir / (s["path"] + ".symlink.txt")
        status = "" if placeholder.exists() else "  [MISSING]"
        print(f"  [SYM] {s['path']}  →  {s['target']}{status}")

    if missing:
        print(f"\nWARNING: {len(missing)} packed file(s) not found (will be skipped).")

    if dry_run:
        print(f"\nDry run. Use --apply to restore files.")
        return

    print()

    restored = 0
    skipped = 0

    for e in entries:
        packed = pkg_dir / e["packed"]
        original = pkg_dir / e["original"]

        if not packed.exists():
            print(f"  SKIP (missing): {e['packed']}")
            skipped += 1
            continue

        original.parent.mkdir(parents=True, exist_ok=True)

        if e["action"] == "base64":
            size_mb = packed.stat().st_size / 1024 / 1024
            print(f"  Decoding {e['packed']} ({size_mb:.1f} MB)...", end="", flush=True)
            decode_b64(packed, original)
            packed.unlink()
            print(" done")
        elif e["action"] == "rename":
            print(f"  Renaming {e['packed']}  →  {e['original']}")
            packed.rename(original)

        # Restore permissions
        try:
            os.chmod(original, e["permissions"])
        except (OSError, KeyError):
            pass

        restored += 1

    # Recreate symlinks
    sym_restored = 0
    for s in symlinks:
        link_path = pkg_dir / s["path"]
        placeholder = pkg_dir / (s["path"] + ".symlink.txt")
        target = s["target"]

        link_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove placeholder if it exists
        if placeholder.exists():
            placeholder.unlink()

        # Create symlink
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        os.symlink(target, link_path)
        print(f"  Symlink: {s['path']}  →  {target}")
        sym_restored += 1

    # Remove manifest
    manifest_path.unlink()

    print(f"\nDone. {restored} file(s) restored, {sym_restored} symlink(s) recreated, {skipped} skipped.")
    print(f"\nNext steps:")
    print(f"  ./airgap-deploy.sh load ./images")
    print(f"  ./airgap-deploy.sh start")
    print(f"  ./airgap-deploy.sh migrate")


def main():
    parser = argparse.ArgumentParser(
        description="Unpack airgap deployment after transfer (decode base64, restore names)"
    )
    parser.add_argument(
        "package_dir", nargs="?", default=".",
        help="Path to the packed airgap directory (default: current directory)"
    )
    parser.add_argument("--apply", action="store_true", help="Actually restore files (default: dry run)")
    args = parser.parse_args()

    pkg_dir = Path(args.package_dir).resolve()
    if not pkg_dir.is_dir():
        print(f"ERROR: Not a directory: {pkg_dir}")
        sys.exit(1)

    unpack(pkg_dir, dry_run=not args.apply)


if __name__ == "__main__":
    main()
