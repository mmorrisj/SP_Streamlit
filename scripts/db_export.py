#!/usr/bin/env python3
"""
Export the SoftPower PostgreSQL database to chunked dump files for migration.

Uses pg_dump --format=custom for native handling of all PostgreSQL types
(JSONB, ARRAY, UUID, pgvector, ENUMs) with built-in compression.
Splits the dump into chunks (default 750MB) with SHA256 checksums.

Usage:
    # Export using .env defaults (local PostgreSQL)
    python scripts/db_export.py --output-dir ./db_export_20260226

    # Export as a single dump file (no chunking)
    python scripts/db_export.py --output-dir ./db_export_20260226 --single-file

    # Export with custom chunk size
    python scripts/db_export.py --output-dir ./db_export_20260226 --chunk-mb 500

    # Export from Docker container
    python scripts/db_export.py --output-dir ./db_export_20260226 --docker-container softpower_db

    # Export with explicit connection params
    python scripts/db_export.py --output-dir ./db_export_20260226 \
        --host 0.0.0.0 --port 5432 --user $POSTGRES_USER --password $POSTGRES_PASSWORD --dbname $POSTGRES_DB

Import with:
    python scripts/db_import.py --input-dir ./db_export_20260226
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Load .env for default connection params
try:
    from dotenv import load_dotenv, find_dotenv
    env_file = find_dotenv(usecwd=True)
    if env_file:
        load_dotenv(env_file, override=True)
except ImportError:
    pass

DEFAULT_CHUNK_MB = 750
READ_BLOCK = 8 * 1024 * 1024  # 8MB read blocks


def get_connection_params(args):
    """Resolve connection params: CLI args > env vars > defaults."""
    params = {
        "host": args.host or os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or "0.0.0.0",
        "port": args.port or os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432",
        "user": args.user or os.getenv("POSTGRES_USER"),
        "password": args.password or os.getenv("POSTGRES_PASSWORD"),
        "dbname": args.dbname or os.getenv("POSTGRES_DB"),
    }
    missing = [k for k in ("user", "password", "dbname") if not params[k]]
    if missing:
        env_names = {"user": "POSTGRES_USER", "password": "POSTGRES_PASSWORD", "dbname": "POSTGRES_DB"}
        raise EnvironmentError(
            f"Required database config not set: {', '.join(env_names[k] for k in missing)}. "
            "Pass via CLI args or set in .env file."
        )
    return params


def detect_docker_container():
    """Auto-detect a running PostgreSQL container."""
    known_names = ["softpower_db", "sp_prod_db"]
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            running = result.stdout.strip().split("\n")
            for name in known_names:
                if name in running:
                    return name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def build_pg_dump_cmd(conn, docker_container=None):
    """Build the pg_dump command list.

    When docker_container is set, uses an ephemeral container on the
    softpower_net network instead of docker exec (enterprise compatibility).
    Stdout from the ephemeral container is piped to capture the dump.
    """
    pg_dump_args = [
        "pg_dump",
        "--format=custom",
        "--compress=6",
        "--verbose",
    ]

    if docker_container:
        db_image = os.getenv("DB_IMAGE", "pgvector/pgvector:0.8.1-pg16")
        network = os.getenv("NETWORK_NAME", "softpower_net")
        pg_dump_args.extend([
            f"--host={docker_container}",
            "--port=5432",
            f"--username={conn['user']}",
            f"--dbname={conn['dbname']}",
        ])
        return [
            "docker", "run", "--rm",
            "--network", network,
            "-e", f"PGPASSWORD={conn['password']}",
            db_image,
        ] + pg_dump_args
    else:
        pg_dump_args.extend([
            f"--host={conn['host']}",
            f"--port={conn['port']}",
            f"--username={conn['user']}",
            f"--dbname={conn['dbname']}",
        ])
        return pg_dump_args


def build_psql_cmd(conn, docker_container=None):
    """Build a psql command for querying metadata.

    When docker_container is set, uses an ephemeral container on the
    softpower_net network instead of docker exec (enterprise compatibility).
    """
    if docker_container:
        db_image = os.getenv("DB_IMAGE", "pgvector/pgvector:0.8.1-pg16")
        network = os.getenv("NETWORK_NAME", "softpower_net")
        return [
            "docker", "run", "--rm",
            "--network", network,
            "-e", f"PGPASSWORD={conn['password']}",
            db_image,
            "psql",
            f"--host={docker_container}",
            "--port=5432",
            f"--username={conn['user']}",
            f"--dbname={conn['dbname']}",
            "--tuples-only",
            "--no-align",
        ]
    else:
        return [
            "psql",
            f"--host={conn['host']}",
            f"--port={conn['port']}",
            f"--username={conn['user']}",
            f"--dbname={conn['dbname']}",
            "--tuples-only",
            "--no-align",
        ]


def get_pg_dump_version(docker_container=None):
    """Get the pg_dump version string."""
    try:
        if docker_container:
            db_image = os.getenv("DB_IMAGE", "pgvector/pgvector:0.8.1-pg16")
            cmd = ["docker", "run", "--rm", db_image, "pg_dump", "--version"]
        else:
            cmd = ["pg_dump", "--version"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def get_table_row_counts(conn, docker_container=None):
    """Query the database for all table names and row counts."""
    # Use relname/schemaname from pg_class join to avoid column name issues
    query = (
        "SELECT n.nspname || '.' || c.relname, c.reltuples::bigint "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' "
        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY n.nspname, c.relname;"
    )

    cmd = build_psql_cmd(conn, docker_container) + ["-c", query]
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode != 0:
            print(f"  Warning: Could not query table counts: {result.stderr.strip()}")
            return []

        tables = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("("):
                continue
            parts = line.split("|")
            if len(parts) == 2:
                name = parts[0].strip()
                try:
                    rows = int(parts[1].strip())
                except ValueError:
                    rows = -1
                tables.append({"name": name, "rows": rows})
        return tables
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  Warning: Could not query table counts: {e}")
        return []


def get_database_size(conn, docker_container=None):
    """Get total database size."""
    query = f"SELECT pg_size_pretty(pg_database_size('{conn['dbname']}'));"
    cmd = build_psql_cmd(conn, docker_container) + ["-c", query]
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def split_dump_file(dump_path, output_dir, chunk_bytes):
    """Split a dump file into chunks, computing SHA256 per chunk.

    Returns list of chunk dicts: [{"file": "chunk_001.dump", "size_bytes": N, "sha256": "..."}]
    """
    dump_size = dump_path.stat().st_size
    num_chunks = max(1, (dump_size + chunk_bytes - 1) // chunk_bytes)

    if num_chunks == 1:
        # Single chunk — just move the file
        chunk_name = "chunk_001.dump"
        dest = output_dir / chunk_name
        shutil.move(str(dump_path), str(dest))
        sha = sha256_file(dest)
        return [{"file": chunk_name, "size_bytes": dest.stat().st_size, "sha256": sha}]

    print(f"  Splitting {dump_size / (1024**3):.2f} GB into {num_chunks} chunks "
          f"(max {chunk_bytes / (1024**2):.0f} MB each)...")

    chunks = []
    part_num = 0
    bytes_in_chunk = 0
    fout = None
    hasher = None

    try:
        with open(dump_path, "rb") as fin:
            while True:
                # Start a new chunk if needed
                if fout is None:
                    part_num += 1
                    chunk_name = f"chunk_{part_num:03d}.dump"
                    fout = open(output_dir / chunk_name, "wb")
                    hasher = hashlib.sha256()
                    bytes_in_chunk = 0

                block = fin.read(READ_BLOCK)
                if not block:
                    break

                fout.write(block)
                hasher.update(block)
                bytes_in_chunk += len(block)

                # Rotate to next chunk if size limit reached
                if bytes_in_chunk >= chunk_bytes:
                    fout.close()
                    chunk_size = (output_dir / chunk_name).stat().st_size
                    chunks.append({
                        "file": chunk_name,
                        "size_bytes": chunk_size,
                        "sha256": hasher.hexdigest(),
                    })
                    print(f"    {chunk_name}: {chunk_size / (1024**2):.1f} MB")
                    fout = None
                    hasher = None
    finally:
        if fout is not None:
            fout.close()
            chunk_size = (output_dir / chunk_name).stat().st_size
            chunks.append({
                "file": chunk_name,
                "size_bytes": chunk_size,
                "sha256": hasher.hexdigest(),
            })
            print(f"    {chunk_name}: {chunk_size / (1024**2):.1f} MB")

    # Remove the original dump now that it's been split
    dump_path.unlink()
    return chunks


def sha256_file(filepath):
    """Compute SHA256 hash of a file (streaming)."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            block = f.read(READ_BLOCK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def export_database(args):
    """Main export logic."""
    output_dir = Path(args.output_dir).resolve()
    if args.single_file:
        chunk_bytes = 2**63  # effectively no chunking
    else:
        chunk_bytes = args.chunk_mb * 1024 * 1024
    conn = get_connection_params(args)

    # Determine Docker container
    docker_container = args.docker_container
    if docker_container == "auto":
        docker_container = detect_docker_container()
        if docker_container:
            print(f"  Auto-detected Docker container: {docker_container}")
        else:
            print("  No Docker container detected, using local pg_dump")
            docker_container = None

    # Display config
    print("=" * 60)
    print("  DATABASE EXPORT")
    print("=" * 60)
    if docker_container:
        print(f"  Source:     docker container {docker_container} (via network)")
    else:
        print(f"  Source:     {conn['host']}:{conn['port']}")
    print(f"  Database:  {conn['dbname']}")
    print(f"  User:      {conn['user']}")
    print(f"  Output:    {output_dir}")
    if args.single_file:
        print(f"  Mode:      single file (no chunking)")
    else:
        print(f"  Chunk size: {args.chunk_mb} MB")
    print()

    # Check pg_dump availability
    pg_version = get_pg_dump_version(docker_container)
    if pg_version == "unknown":
        mode = f"docker:{docker_container}" if docker_container else "local"
        print(f"ERROR: pg_dump not found ({mode})")
        if not docker_container:
            print("  Try: --docker-container softpower_db")
            detected = detect_docker_container()
            if detected:
                print(f"  Detected running container: {detected}")
        sys.exit(1)
    print(f"  pg_dump:   {pg_version}")

    # Get database size
    db_size = get_database_size(conn, docker_container)
    print(f"  DB size:   {db_size}")
    print()

    # Get table row counts
    print("  Querying table row counts...")
    tables = get_table_row_counts(conn, docker_container)
    if tables:
        total_rows = sum(t["rows"] for t in tables if t["rows"] >= 0)
        print(f"  Found {len(tables)} tables, ~{total_rows:,} total rows")
        for t in tables:
            print(f"    {t['name']}: {t['rows']:,} rows")
    print()

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing export
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        print(f"ERROR: manifest.json already exists in {output_dir}")
        print("  Remove the directory or choose a different output path.")
        sys.exit(1)

    # Run pg_dump to temp file
    print("  Running pg_dump...")
    dump_path = output_dir / "_full_dump.tmp"
    cmd = build_pg_dump_cmd(conn, docker_container)

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    try:
        with open(dump_path, "wb") as dump_file:
            process = subprocess.Popen(
                cmd, stdout=dump_file, stderr=subprocess.PIPE, env=env
            )
            _, stderr = process.communicate()

            if process.returncode != 0:
                print(f"ERROR: pg_dump failed (exit code {process.returncode})")
                print(stderr.decode("utf-8", errors="replace"))
                if dump_path.exists():
                    dump_path.unlink()
                sys.exit(1)

        dump_size = dump_path.stat().st_size
        print(f"  pg_dump complete: {dump_size / (1024**3):.2f} GB "
              f"({dump_size / (1024**2):.0f} MB)")

        # Print pg_dump stderr (contains progress info with --verbose)
        if stderr:
            verbose_lines = stderr.decode("utf-8", errors="replace").strip().split("\n")
            # Show last few lines of verbose output
            for line in verbose_lines[-5:]:
                if line.strip():
                    print(f"    {line.strip()}")
        print()

    except FileNotFoundError:
        print("ERROR: pg_dump command not found")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted by user")
        if dump_path.exists():
            dump_path.unlink()
        sys.exit(1)

    # Split into chunks
    print("  Splitting dump file into chunks...")
    chunks = split_dump_file(dump_path, output_dir, chunk_bytes)
    total_chunk_size = sum(c["size_bytes"] for c in chunks)
    print(f"  Split into {len(chunks)} chunk(s), total {total_chunk_size / (1024**2):.0f} MB")
    print()

    # Write manifest
    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_name": conn["dbname"],
        "pg_dump_version": pg_version,
        "total_size_bytes": total_chunk_size,
        "chunk_size_mb": None if args.single_file else args.chunk_mb,
        "tables": tables,
        "chunks": chunks,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    # Summary
    print("=" * 60)
    print("  EXPORT COMPLETE")
    print("=" * 60)
    print(f"  Output directory: {output_dir}")
    print(f"  Chunks:           {len(chunks)}")
    print(f"  Total size:       {total_chunk_size / (1024**3):.2f} GB "
          f"({total_chunk_size / (1024**2):.0f} MB)")
    print(f"  Tables:           {len(tables)}")
    print(f"  Manifest:         manifest.json")
    print()
    print("  Files:")
    for c in chunks:
        print(f"    {c['file']}: {c['size_bytes'] / (1024**2):.1f} MB  "
              f"sha256:{c['sha256'][:16]}...")
    print(f"    manifest.json")
    print()
    print("  To import on target system:")
    print(f"    python scripts/db_import.py --input-dir {output_dir.name}")


def main():
    parser = argparse.ArgumentParser(
        description="Export SoftPower database to chunked dump files for migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export using .env defaults
  python scripts/db_export.py --output-dir ./db_export

  # Export from Docker container
  python scripts/db_export.py --output-dir ./db_export --docker-container softpower_db

  # Export with 500MB chunks
  python scripts/db_export.py --output-dir ./db_export --chunk-mb 500

  # Export as a single dump file (no chunking)
  python scripts/db_export.py --output-dir ./db_export --single-file
        """,
    )
    parser.add_argument("--output-dir", required=True,
                        help="Directory to write chunk files and manifest")
    parser.add_argument("--chunk-mb", type=int, default=DEFAULT_CHUNK_MB,
                        help=f"Max chunk size in MB (default: {DEFAULT_CHUNK_MB})")
    parser.add_argument("--single-file", action="store_true",
                        help="Output a single dump file instead of chunks")

    # Connection params (override .env)
    parser.add_argument("--host", help="Database host (default: from .env or localhost)")
    parser.add_argument("--port", help="Database port (default: from .env or 5432)")
    parser.add_argument("--user", help="Database user (default: from .env)")
    parser.add_argument("--password", help="Database password (default: from .env)")
    parser.add_argument("--dbname", help="Database name (default: from .env)")

    # Docker
    parser.add_argument("--docker-container",
                        nargs="?", const="auto", default=None,
                        help="Run pg_dump inside this Docker container "
                             "(omit value to auto-detect)")

    args = parser.parse_args()
    export_database(args)


if __name__ == "__main__":
    main()
