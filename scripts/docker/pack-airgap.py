#!/usr/bin/env python3
"""
Pack an airgap deployment directory for transfer through systems that
block/redact executables, binaries, and certain file extensions.

Transformations:
  - Binary files (.tar, .dump, .bin, .safetensors, ...) → base64 encoded to .b64.txt
    Large binaries (>500MB) are split into multiple chunk files for reliable transfer
  - Blocked text files (.sh, .ini) → renamed to .sh.txt, .ini.txt
  - Symlinks → recorded in manifest, replaced with placeholder .txt
  - Safe text files (.txt, .json, .py, .md, ...) → left as-is

A manifest (pack_manifest.json) records all transformations plus SHA256
checksums for integrity verification on the target system.

Run unpack-airgap.py on the target system to restore everything.

Usage:
    python scripts/docker/pack-airgap.py <package-dir>              # dry run
    python scripts/docker/pack-airgap.py <package-dir> --apply      # encode/rename
    python scripts/docker/pack-airgap.py <package-dir> --apply --chunk-mb 200  # smaller chunks

Example (after airgap-build.sh --pack):
    python scripts/docker/pack-airgap.py softpower-airgap-20260217 --apply
"""

import argparse
import base64
import hashlib
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
    ".whl",
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

# Default chunk size for splitting large binaries.
# 500MB of raw binary → ~667MB of base64 text per chunk.
# Most transfer systems handle files up to 1-2GB, so 500MB raw
# gives comfortable headroom.
DEFAULT_CHUNK_MB = 500


def classify_file(filepath: Path) -> str:
    """Classify a file as 'binary', 'blocked_text', or 'safe'."""
    ext = filepath.suffix.lower()

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


def encode_b64(src: Path, dst: Path):
    """Stream base64 encode src → dst (memory efficient for large files).

    Writes standard 76-character lines (RFC 2045) so the output is
    compatible with transfer systems that impose line-length limits
    and is human-inspectable in a text editor.
    """
    # Read in multiples of 3 bytes for clean base64 boundary alignment
    CHUNK = 3 * 1024 * 1024  # 3MB raw → 4MB base64
    LINE_LEN = 76
    with open(src, "rb") as fin, open(dst, "w") as fout:
        while True:
            raw = fin.read(CHUNK)
            if not raw:
                break
            encoded = base64.b64encode(raw).decode("ascii")
            for i in range(0, len(encoded), LINE_LEN):
                fout.write(encoded[i:i + LINE_LEN])
                fout.write("\n")


def encode_b64_chunked(src: Path, pkg_dir: Path, rel_path: str, chunk_bytes: int) -> list:
    """Split a large binary into multiple base64-encoded chunk files.

    Each chunk contains base64 of up to chunk_bytes of the original binary,
    written with 76-char lines (RFC 2045).

    Returns list of chunk relative paths (relative to pkg_dir).
    """
    READ_SIZE = 3 * 1024 * 1024  # 3MB (multiple of 3 for clean base64)
    LINE_LEN = 76
    chunks = []
    part_num = 0
    bytes_in_chunk = 0
    fout = None

    try:
        with open(src, "rb") as fin:
            while True:
                # Start a new chunk file if needed
                if fout is None:
                    part_num += 1
                    chunk_rel = f"{rel_path}.b64.part{part_num:03d}.txt"
                    chunk_path = pkg_dir / chunk_rel
                    chunk_path.parent.mkdir(parents=True, exist_ok=True)
                    fout = open(chunk_path, "w")
                    chunks.append(chunk_rel)
                    bytes_in_chunk = 0

                raw = fin.read(READ_SIZE)
                if not raw:
                    break

                bytes_in_chunk += len(raw)
                encoded = base64.b64encode(raw).decode("ascii")
                for i in range(0, len(encoded), LINE_LEN):
                    fout.write(encoded[i:i + LINE_LEN])
                    fout.write("\n")

                # Close this chunk and start a new one if size limit reached
                if bytes_in_chunk >= chunk_bytes:
                    fout.close()
                    fout = None
    finally:
        if fout is not None:
            fout.close()

    return chunks


def get_perms(path: Path) -> int:
    """Get file permission bits."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return 0o644


def pack(pkg_dir: Path, dry_run: bool = True, chunk_mb: int = DEFAULT_CHUNK_MB):
    manifest_path = pkg_dir / MANIFEST_NAME
    chunk_bytes = chunk_mb * 1024 * 1024

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
            file_size = fpath.stat().st_size

            if kind == "binary":
                # Large binaries get chunked for reliable transfer
                if file_size > chunk_bytes:
                    num_chunks = (file_size + chunk_bytes - 1) // chunk_bytes
                    chunk_rels = [
                        f"{rel}.b64.part{i:03d}.txt"
                        for i in range(1, num_chunks + 1)
                    ]
                    entries.append({
                        "original": rel,
                        "packed": chunk_rels,
                        "action": "base64_chunked",
                        "permissions": get_perms(fpath),
                        "size": file_size,
                    })
                else:
                    packed_rel = rel + ".b64.txt"
                    entries.append({
                        "original": rel,
                        "packed": packed_rel,
                        "action": "base64",
                        "permissions": get_perms(fpath),
                        "size": file_size,
                    })
            elif kind == "blocked_text":
                packed_rel = rel + ".txt"
                entries.append({
                    "original": rel,
                    "packed": packed_rel,
                    "action": "rename",
                    "permissions": get_perms(fpath),
                    "size": file_size,
                })
            # else: safe, no action needed

    total_binary = sum(1 for e in entries if e["action"] == "base64")
    total_chunked = sum(1 for e in entries if e["action"] == "base64_chunked")
    total_rename = sum(1 for e in entries if e["action"] == "rename")
    total_symlinks = len(symlinks)
    binary_bytes = sum(e["size"] for e in entries if e["action"] in ("base64", "base64_chunked"))

    print(f"Package directory: {pkg_dir}")
    print(f"  {total_binary} binary file(s) to base64 encode ({binary_bytes / 1024 / 1024:.1f} MB)")
    if total_chunked:
        total_chunks = sum(len(e["packed"]) for e in entries if e["action"] == "base64_chunked")
        print(f"  {total_chunked} large file(s) will be split into {total_chunks} chunks (≤{chunk_mb}MB each)")
    print(f"  {total_rename} text file(s) to rename")
    print(f"  {total_symlinks} symlink(s) to record")
    print()

    for e in entries:
        if e["action"] == "base64_chunked":
            size_mb = e["size"] / 1024 / 1024
            print(f"  [B64] {e['original']} ({size_mb:.0f}MB)  →  {len(e['packed'])} chunks")
            for chunk in e["packed"]:
                print(f"        {chunk}")
        elif e["action"] == "base64":
            print(f"  [B64] {e['original']}  →  {e['packed']}")
        else:
            print(f"  [REN] {e['original']}  →  {e['packed']}")
    for s in symlinks:
        print(f"  [SYM] {s['path']}  →  {s['target']}")

    if dry_run:
        print(f"\nDry run. Use --apply to transform files.")
        return

    print()

    # Process binary files (base64 encode, with optional chunking)
    for e in entries:
        src = pkg_dir / e["original"]

        if e["action"] == "base64_chunked":
            size_mb = e["size"] / 1024 / 1024
            print(f"  Computing SHA256 for {e['original']}...", end="", flush=True)
            e["sha256"] = sha256_file(src)
            print(f" {e['sha256'][:16]}...")
            print(f"  Encoding {e['original']} ({size_mb:.0f}MB) into {len(e['packed'])} chunks...",
                  flush=True)
            actual_chunks = encode_b64_chunked(src, pkg_dir, e["original"], chunk_bytes)
            # Update manifest with actual chunk paths (in case count differs slightly)
            e["packed"] = actual_chunks
            src.unlink()
            for i, chunk_rel in enumerate(actual_chunks, 1):
                chunk_path = pkg_dir / chunk_rel
                chunk_size_mb = chunk_path.stat().st_size / 1024 / 1024
                print(f"    chunk {i}/{len(actual_chunks)}: {chunk_rel} ({chunk_size_mb:.0f}MB)")
            print(f"  done")

        elif e["action"] == "base64":
            dst = pkg_dir / e["packed"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            size_mb = e["size"] / 1024 / 1024
            print(f"  Computing SHA256 for {e['original']}...", end="", flush=True)
            e["sha256"] = sha256_file(src)
            print(f" {e['sha256'][:16]}...")
            print(f"  Encoding {e['original']} ({size_mb:.1f} MB)...", end="", flush=True)
            encode_b64(src, dst)
            src.unlink()
            print(" done")

        elif e["action"] == "rename":
            dst = pkg_dir / e["packed"]
            dst.parent.mkdir(parents=True, exist_ok=True)
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
        "version": 2,
        "description": "Packed airgap deployment. Run unpack-airgap.py --apply to restore.",
        "chunk_mb": chunk_mb,
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
    parser.add_argument(
        "--chunk-mb", type=int, default=DEFAULT_CHUNK_MB,
        help=f"Max raw MB per base64 chunk file (default: {DEFAULT_CHUNK_MB}). "
             f"Files larger than this are split into multiple chunks."
    )
    args = parser.parse_args()

    pkg_dir = Path(args.package_dir).resolve()
    if not pkg_dir.is_dir():
        print(f"ERROR: Not a directory: {pkg_dir}")
        sys.exit(1)

    pack(pkg_dir, dry_run=not args.apply, chunk_mb=args.chunk_mb)


if __name__ == "__main__":
    main()
