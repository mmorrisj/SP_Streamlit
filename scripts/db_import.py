#!/usr/bin/env python3
"""
Import a chunked database export into a PostgreSQL database.

Reads chunks and manifest.json produced by db_export.py, verifies checksums,
reassembles the pg_dump file, and restores it with pg_restore.

Usage:
    # Import using .env defaults for target database
    python scripts/db_import.py --input-dir ./db_export_20260226

    # Import into a different database
    python scripts/db_import.py --input-dir ./db_export_20260226 \
        --target-host newserver --target-db softpower-db

    # Create target database + pgvector extension automatically
    python scripts/db_import.py --input-dir ./db_export_20260226 --create-db

    # Import via Docker container
    python scripts/db_import.py --input-dir ./db_export_20260226 \
        --docker-container sp_prod_db --create-db

    # Drop existing database and recreate (destructive!)
    python scripts/db_import.py --input-dir ./db_export_20260226 --drop-existing

    # Dry run: verify checksums and display manifest only
    python scripts/db_import.py --input-dir ./db_export_20260226 --dry-run
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Load .env for default connection params
try:
    from dotenv import load_dotenv, find_dotenv
    env_file = find_dotenv(usecwd=True)
    if env_file:
        load_dotenv(env_file, override=True)
except ImportError:
    pass

READ_BLOCK = 8 * 1024 * 1024  # 8MB blocks


def get_connection_params(args):
    """Resolve target connection params: CLI args > env vars > defaults."""
    return {
        "host": args.target_host or os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST", "localhost"),
        "port": args.target_port or os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT", "5432"),
        "user": args.target_user or os.getenv("POSTGRES_USER", "matthew50"),
        "password": args.target_password or os.getenv("POSTGRES_PASSWORD", "softpower"),
        "dbname": args.target_db or os.getenv("POSTGRES_DB", "softpower-db"),
    }


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


def verify_checksums(input_dir, chunks):
    """Verify SHA256 checksums of all chunk files. Returns (ok, errors)."""
    errors = []
    for i, chunk in enumerate(chunks, 1):
        chunk_path = input_dir / chunk["file"]
        if not chunk_path.exists():
            errors.append(f"  MISSING: {chunk['file']}")
            continue

        actual_size = chunk_path.stat().st_size
        if actual_size != chunk["size_bytes"]:
            errors.append(
                f"  SIZE MISMATCH: {chunk['file']} "
                f"(expected {chunk['size_bytes']}, got {actual_size})"
            )

        print(f"    Verifying {chunk['file']} ({i}/{len(chunks)})...", end="", flush=True)
        actual_sha = sha256_file(chunk_path)
        if actual_sha != chunk["sha256"]:
            errors.append(
                f"  CHECKSUM MISMATCH: {chunk['file']} "
                f"(expected {chunk['sha256'][:16]}..., got {actual_sha[:16]}...)"
            )
            print(" FAILED")
        else:
            print(" OK")

    return len(errors) == 0, errors


def reassemble_chunks(input_dir, chunks, output_path):
    """Reassemble chunk files into a single dump file."""
    print(f"  Reassembling {len(chunks)} chunk(s)...")
    total_written = 0

    with open(output_path, "wb") as fout:
        for i, chunk in enumerate(chunks, 1):
            chunk_path = input_dir / chunk["file"]
            chunk_size = chunk_path.stat().st_size
            print(f"    {chunk['file']} ({chunk_size / (1024**2):.1f} MB)...",
                  end="", flush=True)

            with open(chunk_path, "rb") as fin:
                while True:
                    block = fin.read(READ_BLOCK)
                    if not block:
                        break
                    fout.write(block)
                    total_written += len(block)

            print(" done")

    print(f"  Reassembled: {total_written / (1024**3):.2f} GB "
          f"({total_written / (1024**2):.0f} MB)")
    return output_path


def build_psql_cmd(conn, docker_container=None, dbname_override=None):
    """Build a psql command."""
    dbname = dbname_override or conn["dbname"]
    if docker_container:
        return [
            "docker", "exec", docker_container,
            "psql",
            "--host=localhost",
            "--port=5432",
            f"--username={conn['user']}",
            f"--dbname={dbname}",
            "--tuples-only",
            "--no-align",
        ]
    else:
        return [
            "psql",
            f"--host={conn['host']}",
            f"--port={conn['port']}",
            f"--username={conn['user']}",
            f"--dbname={dbname}",
            "--tuples-only",
            "--no-align",
        ]


def create_database(conn, docker_container=None):
    """Create the target database and pgvector extension."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    # Connect to 'postgres' maintenance database to create the target DB
    psql_cmd = build_psql_cmd(conn, docker_container, dbname_override="postgres")

    # Check if database exists
    check_query = f"SELECT 1 FROM pg_database WHERE datname = '{conn['dbname']}';"
    result = subprocess.run(
        psql_cmd + ["-c", check_query],
        capture_output=True, text=True, timeout=30, env=env
    )

    if result.stdout.strip() == "1":
        print(f"  Database '{conn['dbname']}' already exists")
    else:
        print(f"  Creating database '{conn['dbname']}'...")
        create_query = f'CREATE DATABASE "{conn["dbname"]}";'
        result = subprocess.run(
            psql_cmd + ["-c", create_query],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode != 0:
            print(f"  ERROR: Failed to create database: {result.stderr.strip()}")
            return False
        print(f"  Database '{conn['dbname']}' created")

    # Create pgvector extension in the target database
    print("  Enabling pgvector extension...")
    target_psql = build_psql_cmd(conn, docker_container)
    result = subprocess.run(
        target_psql + ["-c", "CREATE EXTENSION IF NOT EXISTS vector;"],
        capture_output=True, text=True, timeout=30, env=env
    )
    if result.returncode != 0:
        print(f"  Warning: Could not create vector extension: {result.stderr.strip()}")
        print("  (pg_restore may handle this if the extension is in the dump)")
    else:
        print("  pgvector extension enabled")

    # Create pg_trgm extension (used for fuzzy entity matching)
    result = subprocess.run(
        target_psql + ["-c", "CREATE EXTENSION IF NOT EXISTS pg_trgm;"],
        capture_output=True, text=True, timeout=30, env=env
    )
    if result.returncode == 0:
        print("  pg_trgm extension enabled")

    return True


def drop_database(conn, docker_container=None):
    """Drop the target database (destructive!)."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    psql_cmd = build_psql_cmd(conn, docker_container, dbname_override="postgres")

    # Terminate existing connections
    terminate_query = (
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{conn['dbname']}' AND pid <> pg_backend_pid();"
    )
    subprocess.run(
        psql_cmd + ["-c", terminate_query],
        capture_output=True, text=True, timeout=30, env=env
    )

    # Drop database
    drop_query = f'DROP DATABASE IF EXISTS "{conn["dbname"]}";'
    result = subprocess.run(
        psql_cmd + ["-c", drop_query],
        capture_output=True, text=True, timeout=30, env=env
    )
    if result.returncode != 0:
        print(f"  ERROR: Failed to drop database: {result.stderr.strip()}")
        return False
    print(f"  Database '{conn['dbname']}' dropped")
    return True


def build_pg_restore_cmd(conn, dump_path, docker_container=None, jobs=1):
    """Build the pg_restore command."""
    pg_restore_args = [
        "pg_restore",
        "--verbose",
        "--clean",
        "--if-exists",
        f"--dbname={conn['dbname']}",
    ]

    if jobs > 1:
        pg_restore_args.append(f"--jobs={jobs}")

    if docker_container:
        pg_restore_args.extend([
            "--host=localhost",
            "--port=5432",
            f"--username={conn['user']}",
        ])
        # For Docker, we need to pipe the dump file via stdin
        return (
            ["docker", "exec", "-i", docker_container] + pg_restore_args,
            True  # pipe_stdin=True
        )
    else:
        pg_restore_args.extend([
            f"--host={conn['host']}",
            f"--port={conn['port']}",
            f"--username={conn['user']}",
            str(dump_path),
        ])
        return pg_restore_args, False


def restore_database(conn, dump_path, docker_container=None, jobs=1):
    """Run pg_restore to load the dump file."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    cmd, pipe_stdin = build_pg_restore_cmd(conn, dump_path, docker_container, jobs)

    print(f"  Running pg_restore (jobs={jobs})...")
    try:
        if pipe_stdin:
            # Docker mode: pipe dump file to stdin
            with open(dump_path, "rb") as dump_file:
                process = subprocess.Popen(
                    cmd, stdin=dump_file, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, env=env
                )
                stdout, stderr = process.communicate()
        else:
            # Local mode: pg_restore reads file directly
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
            )
            stdout, stderr = process.communicate()

        stderr_text = stderr.decode("utf-8", errors="replace")

        # pg_restore returns non-zero even on warnings (e.g., "role does not exist")
        # Filter for actual errors vs warnings
        error_lines = []
        warning_lines = []
        for line in stderr_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if "ERROR" in line and "does not exist" not in line:
                error_lines.append(line)
            elif "WARNING" in line or "NOTICE" in line:
                warning_lines.append(line)

        if warning_lines:
            print(f"  Warnings ({len(warning_lines)}):")
            for line in warning_lines[:10]:
                print(f"    {line}")
            if len(warning_lines) > 10:
                print(f"    ... and {len(warning_lines) - 10} more")

        if error_lines:
            print(f"  Errors ({len(error_lines)}):")
            for line in error_lines[:10]:
                print(f"    {line}")
            if len(error_lines) > 10:
                print(f"    ... and {len(error_lines) - 10} more")

        # Show last few lines of verbose output
        verbose_lines = [l for l in stderr_text.strip().split("\n")
                         if l.strip() and "pg_restore:" in l]
        if verbose_lines:
            print(f"  pg_restore output (last 5 lines):")
            for line in verbose_lines[-5:]:
                print(f"    {line.strip()}")

        return process.returncode

    except FileNotFoundError:
        print("ERROR: pg_restore command not found")
        return 1
    except KeyboardInterrupt:
        print("\nAborted by user")
        return 1


def verify_row_counts(conn, manifest_tables, docker_container=None):
    """Query target database and compare row counts against manifest."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    query = (
        "SELECT n.nspname || '.' || c.relname, c.reltuples::bigint "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' "
        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY n.nspname, c.relname;"
    )
    psql_cmd = build_psql_cmd(conn, docker_container) + ["-c", query]

    # Run ANALYZE first to update row count statistics
    analyze_cmd = build_psql_cmd(conn, docker_container) + ["-c", "ANALYZE;"]
    subprocess.run(analyze_cmd, capture_output=True, text=True, timeout=120, env=env)

    result = subprocess.run(psql_cmd, capture_output=True, text=True, timeout=30, env=env)
    if result.returncode != 0:
        print(f"  Warning: Could not query target table counts")
        return

    # Parse target counts
    target_counts = {}
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
            target_counts[name] = rows

    # Build manifest lookup
    manifest_counts = {t["name"]: t["rows"] for t in manifest_tables}

    # Compare
    print()
    print("  Row count verification:")
    print(f"  {'Table':<45} {'Export':>10} {'Import':>10} {'Status':>8}")
    print(f"  {'-'*45} {'-'*10} {'-'*10} {'-'*8}")

    all_tables = sorted(set(list(manifest_counts.keys()) + list(target_counts.keys())))
    mismatches = 0
    for table in all_tables:
        export_rows = manifest_counts.get(table, -1)
        import_rows = target_counts.get(table, -1)

        if export_rows < 0 and import_rows < 0:
            status = "???"
        elif export_rows == import_rows:
            status = "OK"
        elif abs(export_rows - import_rows) <= max(1, export_rows * 0.01):
            # Within 1% tolerance (pg_stat counts are approximate)
            status = "~OK"
        else:
            status = "DIFF"
            mismatches += 1

        export_str = f"{export_rows:,}" if export_rows >= 0 else "n/a"
        import_str = f"{import_rows:,}" if import_rows >= 0 else "n/a"
        print(f"  {table:<45} {export_str:>10} {import_str:>10} {status:>8}")

    if mismatches > 0:
        print(f"\n  WARNING: {mismatches} table(s) have row count differences.")
        print("  Note: pg_stat row counts are approximate. Run ANALYZE on the target")
        print("  database and re-check if counts seem slightly off.")
    else:
        print(f"\n  All {len(all_tables)} tables verified OK")


def import_database(args):
    """Main import logic."""
    input_dir = Path(args.input_dir).resolve()
    conn = get_connection_params(args)

    # Determine Docker container
    docker_container = args.docker_container
    if docker_container == "auto":
        docker_container = detect_docker_container()
        if docker_container:
            print(f"  Auto-detected Docker container: {docker_container}")
        else:
            print("  No Docker container detected, using local pg_restore")
            docker_container = None

    # Read manifest
    manifest_path = input_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest.json not found in {input_dir}")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())

    # Display manifest info
    print("=" * 60)
    print("  DATABASE IMPORT")
    print("=" * 60)
    print(f"  Source dir:    {input_dir}")
    print(f"  Export date:   {manifest.get('created_at', 'unknown')}")
    print(f"  Source DB:     {manifest.get('database_name', 'unknown')}")
    print(f"  pg_dump ver:   {manifest.get('pg_dump_version', 'unknown')}")
    print(f"  Total size:    {manifest['total_size_bytes'] / (1024**3):.2f} GB")
    print(f"  Chunks:        {len(manifest['chunks'])}")
    print()

    if docker_container:
        print(f"  Target:        docker exec {docker_container}")
    else:
        print(f"  Target:        {conn['host']}:{conn['port']}")
    print(f"  Target DB:     {conn['dbname']}")
    print(f"  Target user:   {conn['user']}")
    print()

    # Show tables from manifest
    tables = manifest.get("tables", [])
    if tables:
        total_rows = sum(t["rows"] for t in tables if t["rows"] >= 0)
        print(f"  Tables in export: {len(tables)} (~{total_rows:,} total rows)")
        for t in tables:
            print(f"    {t['name']}: {t['rows']:,} rows")
        print()

    # Verify checksums
    print("  Verifying chunk checksums...")
    ok, errors = verify_checksums(input_dir, manifest["chunks"])
    if not ok:
        print("\n  CHECKSUM VERIFICATION FAILED:")
        for err in errors:
            print(f"    {err}")
        print("\n  The export may be corrupted. Re-export from the source database.")
        sys.exit(1)
    print("  All checksums verified OK")
    print()

    if args.dry_run:
        print("  Dry run complete. No changes made.")
        return

    # Drop existing database if requested
    if args.drop_existing:
        print(f"  WARNING: About to DROP database '{conn['dbname']}'!")
        confirm = input("  Type the database name to confirm: ")
        if confirm.strip() != conn["dbname"]:
            print("  Aborted. Database name did not match.")
            sys.exit(1)
        if not drop_database(conn, docker_container):
            sys.exit(1)
        # Must create after drop
        if not create_database(conn, docker_container):
            sys.exit(1)
        print()

    # Create database if requested
    elif args.create_db:
        if not create_database(conn, docker_container):
            sys.exit(1)
        print()

    # Reassemble chunks
    chunks = manifest["chunks"]
    if len(chunks) == 1:
        # Single chunk — use directly
        dump_path = input_dir / chunks[0]["file"]
        temp_dump = None
        print(f"  Single chunk, using directly: {chunks[0]['file']}")
    else:
        # Multiple chunks — reassemble to temp file
        temp_dump = Path(tempfile.mkdtemp()) / "reassembled.dump"
        dump_path = reassemble_chunks(input_dir, chunks, temp_dump)
    print()

    # Run pg_restore
    try:
        returncode = restore_database(
            conn, dump_path, docker_container, jobs=args.jobs
        )
        print()

        if returncode == 0:
            print("  pg_restore completed successfully")
        else:
            print(f"  pg_restore exited with code {returncode}")
            print("  Note: non-zero exit is common due to pre-existing objects or role warnings")
            print("  Check the output above for actual errors")
        print()

        # Verify row counts
        if tables:
            verify_row_counts(conn, tables, docker_container)

    finally:
        # Clean up temp file
        if temp_dump and temp_dump.exists():
            temp_dump.unlink()
            temp_dump.parent.rmdir()

    # Final summary
    print()
    print("=" * 60)
    print("  IMPORT COMPLETE")
    print("=" * 60)
    print(f"  Database:  {conn['dbname']}")
    if docker_container:
        print(f"  Host:      docker:{docker_container}")
    else:
        print(f"  Host:      {conn['host']}:{conn['port']}")
    print()
    print("  Next steps:")
    print("    1. Verify application connectivity")
    print("    2. Run: alembic upgrade head  (apply any pending migrations)")
    print("    3. Update .env on target system with new connection params")


def main():
    parser = argparse.ArgumentParser(
        description="Import chunked database export into PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import using .env defaults
  python scripts/db_import.py --input-dir ./db_export

  # Import into a different host
  python scripts/db_import.py --input-dir ./db_export \\
      --target-host newserver --target-db softpower-db

  # Create database + extensions automatically
  python scripts/db_import.py --input-dir ./db_export --create-db

  # Dry run (verify checksums only)
  python scripts/db_import.py --input-dir ./db_export --dry-run
        """,
    )
    parser.add_argument("--input-dir", required=True,
                        help="Directory containing chunk files and manifest.json")

    # Target connection params
    parser.add_argument("--target-host",
                        help="Target database host (default: from .env or localhost)")
    parser.add_argument("--target-port",
                        help="Target database port (default: from .env or 5432)")
    parser.add_argument("--target-user",
                        help="Target database user (default: from .env)")
    parser.add_argument("--target-password",
                        help="Target database password (default: from .env)")
    parser.add_argument("--target-db",
                        help="Target database name (default: from .env)")

    # Docker
    parser.add_argument("--docker-container",
                        nargs="?", const="auto", default=None,
                        help="Run pg_restore inside this Docker container "
                             "(omit value to auto-detect)")

    # Database setup
    parser.add_argument("--create-db", action="store_true",
                        help="Create target database and pgvector extension if missing")
    parser.add_argument("--drop-existing", action="store_true",
                        help="Drop existing database before restore (DESTRUCTIVE - asks for confirmation)")

    # Restore options
    parser.add_argument("--jobs", type=int, default=1,
                        help="Number of parallel restore jobs (default: 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Verify checksums and display manifest only, no restore")

    args = parser.parse_args()
    import_database(args)


if __name__ == "__main__":
    main()
