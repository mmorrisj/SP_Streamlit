#!/usr/bin/env python3
"""
Unpack an airgap deployment directory after transfer.

Reverses all transformations made by pack-airgap.py:
  - .b64.txt files → base64 decoded back to original binary
  - .b64.partNNN.txt chunk files → decoded and concatenated back to original
  - .sh.txt files → renamed back to .sh
  - .symlink.txt placeholders → recreated as actual symlinks

Reads the manifest (pack_manifest.json) written by pack-airgap.py.
Verifies SHA256 checksums when present to detect transfer corruption.

Usage:
    cd softpower-airgap-YYYYMMDD
    python unpack-airgap.py              # dry run (shows what would be restored)
    python unpack-airgap.py --apply      # actually restore files
"""

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

MANIFEST_NAME = "pack_manifest.json"


def sha256_file(filepath: Path) -> str:
    """Compute SHA256 hash of a file (streaming, memory-efficient)."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            block = f.read(8 * 1024 * 1024)  # 8MB blocks
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def decode_b64(src: Path, dst: Path):
    """Stream base64 decode src → dst (memory efficient for large files).

    Handles both line-broken base64 (76-char lines, RFC 2045) and
    continuous base64 (no line breaks, legacy format).  Also tolerant of
    stray whitespace that transfer systems may have inserted.
    """
    CHUNK = 4 * 1024 * 1024  # ~4MB read at a time
    remainder = ""
    with open(src, "r") as fin, open(dst, "wb") as fout:
        while True:
            raw = fin.read(CHUNK)
            if not raw:
                break
            # Strip whitespace (newlines, spaces, CR) for transfer tolerance
            clean = remainder + raw.replace("\n", "").replace("\r", "").replace(" ", "")
            # Decode in multiples of 4 chars (base64 group boundary)
            cut = (len(clean) // 4) * 4
            if cut > 0:
                fout.write(base64.b64decode(clean[:cut]))
            remainder = clean[cut:]
        # Final remainder (with padding)
        if remainder:
            fout.write(base64.b64decode(remainder))


def decode_b64_chunked(chunk_paths: list, dst: Path, pkg_dir: Path):
    """Decode multiple base64 chunk files back into a single binary file.

    Chunks are decoded in order and appended to the output file.
    """
    CHUNK = 4 * 1024 * 1024
    with open(dst, "wb") as fout:
        for chunk_rel in chunk_paths:
            chunk_path = pkg_dir / chunk_rel
            remainder = ""
            with open(chunk_path, "r") as fin:
                while True:
                    raw = fin.read(CHUNK)
                    if not raw:
                        break
                    clean = remainder + raw.replace("\n", "").replace("\r", "").replace(" ", "")
                    cut = (len(clean) // 4) * 4
                    if cut > 0:
                        fout.write(base64.b64decode(clean[:cut]))
                    remainder = clean[cut:]
            # Flush remainder for this chunk (each chunk is independently valid base64)
            if remainder:
                fout.write(base64.b64decode(remainder))


def unpack(pkg_dir: Path, dry_run: bool = True):
    manifest_path = pkg_dir / MANIFEST_NAME

    if not manifest_path.exists():
        print(f"ERROR: No manifest found at {manifest_path}")
        print("This directory may not have been packed, or the manifest was lost.")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("files", [])
    symlinks = manifest.get("symlinks", [])
    manifest_version = manifest.get("version", 1)

    total_b64 = sum(1 for e in entries if e["action"] == "base64")
    total_chunked = sum(1 for e in entries if e["action"] == "base64_chunked")
    total_ren = sum(1 for e in entries if e["action"] == "rename")
    has_checksums = any(e.get("sha256") for e in entries)

    print(f"Package directory: {pkg_dir}")
    print(f"  Manifest version: {manifest_version}")
    print(f"  {total_b64} file(s) to base64 decode")
    if total_chunked:
        total_chunks = sum(len(e["packed"]) for e in entries if e["action"] == "base64_chunked")
        print(f"  {total_chunked} chunked file(s) to reassemble ({total_chunks} chunks total)")
    print(f"  {total_ren} file(s) to rename")
    print(f"  {len(symlinks)} symlink(s) to recreate")
    if has_checksums:
        print(f"  SHA256 checksums: will verify after decode")
    print()

    # Check for missing files
    missing = []
    for e in entries:
        if e["action"] == "base64_chunked":
            # Check all chunks exist
            all_present = True
            missing_chunks = []
            for chunk_rel in e["packed"]:
                if not (pkg_dir / chunk_rel).exists():
                    all_present = False
                    missing_chunks.append(chunk_rel)
            status = "" if all_present else f"  [MISSING {len(missing_chunks)} chunk(s)]"
            size_mb = e.get("size", 0) / 1024 / 1024
            print(f"  [B64] {len(e['packed'])} chunks → {e['original']} ({size_mb:.0f}MB){status}")
            if missing_chunks:
                for mc in missing_chunks:
                    print(f"        MISSING: {mc}")
                    missing.append(mc)
        else:
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
        print(f"\nWARNING: {len(missing)} packed file(s)/chunk(s) not found (will be skipped).")

    if dry_run:
        print(f"\nDry run. Use --apply to restore files.")
        return

    print()

    restored = 0
    skipped = 0
    checksum_errors = []

    for e in entries:
        original = pkg_dir / e["original"]
        original.parent.mkdir(parents=True, exist_ok=True)

        if e["action"] == "base64_chunked":
            # Verify all chunks are present
            chunk_paths = e["packed"]
            missing_chunks = [c for c in chunk_paths if not (pkg_dir / c).exists()]
            if missing_chunks:
                print(f"  SKIP (missing {len(missing_chunks)} chunk(s)): {e['original']}")
                skipped += 1
                continue

            total_chunk_mb = sum(
                (pkg_dir / c).stat().st_size / 1024 / 1024 for c in chunk_paths
            )
            print(f"  Decoding {len(chunk_paths)} chunks → {e['original']} ({total_chunk_mb:.0f} MB encoded)...",
                  end="", flush=True)
            decode_b64_chunked(chunk_paths, original, pkg_dir)
            print(" done")

            # Verify size
            actual_size = original.stat().st_size
            expected_size = e.get("size", 0)
            if expected_size and actual_size != expected_size:
                size_diff_mb = abs(actual_size - expected_size) / 1024 / 1024
                print(f"  WARNING: Size mismatch for {e['original']}!")
                print(f"    Expected: {expected_size:,} bytes ({expected_size / 1024 / 1024:.1f} MB)")
                print(f"    Actual:   {actual_size:,} bytes ({actual_size / 1024 / 1024:.1f} MB)")
                print(f"    Difference: {size_diff_mb:.1f} MB")
                print(f"    File may have been truncated during transfer.")
                checksum_errors.append(e["original"])

            # Verify SHA256
            expected_sha = e.get("sha256")
            if expected_sha:
                print(f"  Verifying SHA256 for {e['original']}...", end="", flush=True)
                actual_sha = sha256_file(original)
                if actual_sha == expected_sha:
                    print(f" OK")
                else:
                    print(f" FAILED!")
                    print(f"    Expected: {expected_sha}")
                    print(f"    Actual:   {actual_sha}")
                    print(f"    File is CORRUPTED — one or more chunks were damaged during transfer.")
                    checksum_errors.append(e["original"])

            # Clean up chunk files
            for chunk_rel in chunk_paths:
                (pkg_dir / chunk_rel).unlink()

            restored += 1

        elif e["action"] == "base64":
            packed = pkg_dir / e["packed"]
            if not packed.exists():
                print(f"  SKIP (missing): {e['packed']}")
                skipped += 1
                continue

            size_mb = packed.stat().st_size / 1024 / 1024
            print(f"  Decoding {e['packed']} ({size_mb:.1f} MB)...", end="", flush=True)
            decode_b64(packed, original)
            packed.unlink()
            print(" done")

            # Verify size
            actual_size = original.stat().st_size
            expected_size = e.get("size", 0)
            if expected_size and actual_size != expected_size:
                size_diff_mb = abs(actual_size - expected_size) / 1024 / 1024
                print(f"  WARNING: Size mismatch for {e['original']}!")
                print(f"    Expected: {expected_size:,} bytes ({expected_size / 1024 / 1024:.1f} MB)")
                print(f"    Actual:   {actual_size:,} bytes ({actual_size / 1024 / 1024:.1f} MB)")
                checksum_errors.append(e["original"])

            # Verify SHA256
            expected_sha = e.get("sha256")
            if expected_sha:
                print(f"  Verifying SHA256 for {e['original']}...", end="", flush=True)
                actual_sha = sha256_file(original)
                if actual_sha == expected_sha:
                    print(f" OK")
                else:
                    print(f" FAILED!")
                    print(f"    Expected: {expected_sha}")
                    print(f"    Actual:   {actual_sha}")
                    checksum_errors.append(e["original"])

            restored += 1

        elif e["action"] == "rename":
            packed = pkg_dir / e["packed"]
            if not packed.exists():
                print(f"  SKIP (missing): {e['packed']}")
                skipped += 1
                continue

            print(f"  Renaming {e['packed']}  →  {e['original']}")
            packed.rename(original)
            restored += 1

        # Restore permissions
        if original.exists():
            try:
                os.chmod(original, e["permissions"])
            except (OSError, KeyError):
                pass

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

    if checksum_errors:
        print(f"\n{'='*60}")
        print(f"WARNING: {len(checksum_errors)} file(s) FAILED integrity checks:")
        for f in checksum_errors:
            print(f"  - {f}")
        print(f"\nThese files were corrupted during transfer.")
        print(f"Re-transfer the affected chunk files and run unpack again.")
        print(f"{'='*60}")
        sys.exit(1)

    print(f"\nNext steps:")
    print(f"  ./airgap-deploy.sh load ./images")
    print(f"  ./airgap-deploy.sh setup")
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
