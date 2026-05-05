#!/usr/bin/env python3
"""
Import a chunked database export into a PostgreSQL database.

Source modes:
    --input-dir   Local directory of chunk files (verifies checksums, reassembles, restores)
    --s3-bucket   Stream chunks directly from S3 to pg_restore (no disk staging)

Both modes use the manifest.json produced by db_export.py.

Usage:
    # Local: import using .env defaults
    python scripts/db_import.py --input-dir ./db_export_20260226

    # S3 streaming: zero disk staging (chunks pipe straight to pg_restore stdin)
    python scripts/db_import.py --s3-bucket my-bucket \
        --s3-prefix db_exports/20260226/ \
        --docker-container sp_prod_db --create-db

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

    # Dry run: verify checksums and display manifest only (input-dir mode only)
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
    params = {
        "host": args.target_host or os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or "0.0.0.0",
        "port": args.target_port or os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432",
        "user": args.target_user or os.getenv("POSTGRES_USER"),
        "password": args.target_password or os.getenv("POSTGRES_PASSWORD"),
        "dbname": args.target_db or os.getenv("POSTGRES_DB"),
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
    """Build a psql command.

    When docker_container is set, uses an ephemeral container on the
    softpower_net network instead of docker exec (enterprise compatibility).
    """
    dbname = dbname_override or conn["dbname"]
    if docker_container:
        db_image = os.getenv("DB_IMAGE", "pgvector/pgvector:0.8.1-pg17")
        return [
            "docker", "run", "--rm",
            "--network", os.getenv("NETWORK_NAME", "softpower_net"),
            "-e", f"PGPASSWORD={conn['password']}",
            db_image,
            "psql",
            f"--host={docker_container}",
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
    """Build the pg_restore command.

    When docker_container is set, uses an ephemeral container on the
    softpower_net network instead of docker exec (enterprise compatibility).

    When dump_path is None, pg_restore reads from stdin (streaming mode).
    Returns (cmd, pipe_stdin).
    """
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
        db_image = os.getenv("DB_IMAGE", "pgvector/pgvector:0.8.1-pg17")
        pg_restore_args.extend([
            f"--host={docker_container}",
            "--port=5432",
            f"--username={conn['user']}",
        ])
        # Ephemeral container: pipe dump (file or stream) via stdin
        return (
            ["docker", "run", "--rm", "-i",
             "--network", os.getenv("NETWORK_NAME", "softpower_net"),
             "-e", f"PGPASSWORD={conn['password']}",
             db_image] + pg_restore_args,
            True  # pipe_stdin=True
        )

    pg_restore_args.extend([
        f"--host={conn['host']}",
        f"--port={conn['port']}",
        f"--username={conn['user']}",
    ])
    if dump_path is None:
        # No file argument → pg_restore reads from stdin
        return pg_restore_args, True
    pg_restore_args.append(str(dump_path))
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


def make_s3_client(region=None, endpoint_url=None):
    """Build an S3 client. boto3 picks up credentials from the standard chain
    (env vars, ~/.aws/credentials, IAM role, etc.)."""
    try:
        import boto3
    except ImportError:
        print("ERROR: boto3 is required for --s3-bucket mode.")
        print("       Install with: pip install boto3")
        sys.exit(1)

    kwargs = {}
    if region:
        kwargs["region_name"] = region
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def s3_get_manifest(s3_client, bucket, prefix):
    """Download manifest.json from S3 and return parsed dict."""
    key = prefix.rstrip("/") + "/manifest.json" if prefix else "manifest.json"
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        print(f"ERROR: manifest.json not found at s3://{bucket}/{key}")
        sys.exit(1)


def restore_database_streaming(conn, manifest, s3_client, bucket, prefix,
                               docker_container=None, jobs=1):
    """Stream chunks from S3 directly to pg_restore stdin (no disk staging).

    Verifies SHA256 of each chunk on-the-fly while streaming. Aborts the
    restore if any chunk's checksum or size doesn't match the manifest.
    """
    if jobs > 1:
        print(f"  Note: --jobs={jobs} ignored in streaming mode "
              "(pg_restore needs seekable input for parallel restore)")
        jobs = 1

    cmd, _pipe = build_pg_restore_cmd(
        conn, dump_path=None, docker_container=docker_container, jobs=jobs
    )

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    chunks = manifest["chunks"]
    total_bytes = sum(c["size_bytes"] for c in chunks)

    print(f"  Streaming {len(chunks)} chunk(s) from "
          f"s3://{bucket}/{prefix} → pg_restore")
    print(f"  Total to stream: {total_bytes / (1024**3):.2f} GB")

    process = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env
    )

    bytes_streamed = 0
    try:
        for i, chunk in enumerate(chunks, 1):
            key = (prefix.rstrip("/") + "/" + chunk["file"]) if prefix else chunk["file"]
            chunk_mb = chunk["size_bytes"] / (1024**2)
            print(f"    [{i}/{len(chunks)}] {chunk['file']} ({chunk_mb:.1f} MB)...",
                  end="", flush=True)

            obj = s3_client.get_object(Bucket=bucket, Key=key)
            body = obj["Body"]
            h = hashlib.sha256()
            chunk_bytes = 0

            while True:
                block = body.read(READ_BLOCK)
                if not block:
                    break
                h.update(block)
                chunk_bytes += len(block)
                process.stdin.write(block)
                bytes_streamed += len(block)

            actual_sha = h.hexdigest()
            if chunk_bytes != chunk["size_bytes"]:
                print(" SIZE MISMATCH")
                process.stdin.close()
                process.terminate()
                raise RuntimeError(
                    f"Size mismatch on {chunk['file']}: "
                    f"expected {chunk['size_bytes']}, streamed {chunk_bytes}"
                )
            if actual_sha != chunk["sha256"]:
                print(" CHECKSUM FAIL")
                process.stdin.close()
                process.terminate()
                raise RuntimeError(
                    f"Checksum mismatch on {chunk['file']}: "
                    f"expected {chunk['sha256'][:16]}..., got {actual_sha[:16]}..."
                )
            pct = bytes_streamed / total_bytes * 100 if total_bytes else 100
            print(f" OK ({pct:.1f}%)")

        process.stdin.close()
        stdout, stderr = process.communicate()

        stderr_text = stderr.decode("utf-8", errors="replace")
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

        verbose_lines = [
            l for l in stderr_text.strip().split("\n")
            if l.strip() and "pg_restore:" in l
        ]
        if verbose_lines:
            print("  pg_restore output (last 5 lines):")
            for line in verbose_lines[-5:]:
                print(f"    {line.strip()}")

        return process.returncode

    except KeyboardInterrupt:
        print("\nAborted by user")
        process.stdin.close()
        process.terminate()
        return 1


def import_database(args):
    """Main import logic."""
    conn = get_connection_params(args)
    using_s3 = bool(args.s3_bucket)
    input_dir = Path(args.input_dir).resolve() if args.input_dir else None

    # Determine Docker container
    docker_container = args.docker_container
    if docker_container == "auto":
        docker_container = detect_docker_container()
        if docker_container:
            print(f"  Auto-detected Docker container: {docker_container}")
        else:
            print("  No Docker container detected, using local pg_restore")
            docker_container = None

    # Load manifest from S3 or local directory
    if using_s3:
        s3_client = make_s3_client(args.s3_region, args.s3_endpoint_url)
        manifest = s3_get_manifest(s3_client, args.s3_bucket, args.s3_prefix)
        source_label = f"s3://{args.s3_bucket}/{args.s3_prefix.rstrip('/')}/"
    else:
        manifest_path = input_dir / "manifest.json"
        if not manifest_path.exists():
            print(f"ERROR: manifest.json not found in {input_dir}")
            sys.exit(1)
        manifest = json.loads(manifest_path.read_text())
        source_label = str(input_dir)

    # Display manifest info
    print("=" * 60)
    print("  DATABASE IMPORT")
    print("=" * 60)
    print(f"  Source:        {source_label}")
    print(f"  Export date:   {manifest.get('created_at', 'unknown')}")
    print(f"  Source DB:     {manifest.get('database_name', 'unknown')}")
    print(f"  pg_dump ver:   {manifest.get('pg_dump_version', 'unknown')}")
    print(f"  Total size:    {manifest['total_size_bytes'] / (1024**3):.2f} GB")
    print(f"  Chunks:        {len(manifest['chunks'])}")
    print()

    if docker_container:
        print(f"  Target:        docker container {docker_container} (via network)")
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

    # Verify checksums (local mode only — S3 mode verifies on-the-fly during stream)
    if using_s3:
        print("  Skipping pre-verify (S3 streaming verifies SHA256 on-the-fly)")
        print()
    else:
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
        if using_s3:
            print("  Dry run not supported for --s3-bucket mode "
                  "(would require streaming the full export to discard).")
        else:
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

    # Run pg_restore
    temp_dump = None
    try:
        if using_s3:
            returncode = restore_database_streaming(
                conn, manifest, s3_client,
                args.s3_bucket, args.s3_prefix,
                docker_container=docker_container, jobs=args.jobs,
            )
        else:
            chunks = manifest["chunks"]
            if len(chunks) == 1:
                dump_path = input_dir / chunks[0]["file"]
                print(f"  Single chunk, using directly: {chunks[0]['file']}")
            else:
                temp_dump = Path(tempfile.mkdtemp()) / "reassembled.dump"
                dump_path = reassemble_chunks(input_dir, chunks, temp_dump)
            print()
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
        # Clean up temp reassembly file (local mode with multiple chunks)
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
  # Import from local directory
  python scripts/db_import.py --input-dir ./db_export

  # Stream from S3 (zero disk staging)
  python scripts/db_import.py --s3-bucket my-bucket \\
      --s3-prefix db_exports/20260226/ \\
      --docker-container sp_prod_db --create-db

  # Import into a different host
  python scripts/db_import.py --input-dir ./db_export \\
      --target-host newserver --target-db softpower-db

  # Create database + extensions automatically
  python scripts/db_import.py --input-dir ./db_export --create-db

  # Dry run (verify checksums only — input-dir mode)
  python scripts/db_import.py --input-dir ./db_export --dry-run
        """,
    )
    # Source: either a local directory of chunks or an S3 prefix (mutually exclusive)
    parser.add_argument("--input-dir",
                        help="Directory containing chunk files and manifest.json")
    parser.add_argument("--s3-bucket",
                        help="S3 bucket containing the export "
                             "(streams chunks directly to pg_restore, no disk staging)")
    parser.add_argument("--s3-prefix", default="",
                        help="S3 prefix containing manifest.json and chunks "
                             "(e.g. 'db_exports/20260226/')")
    parser.add_argument("--s3-region",
                        help="S3 region (default: AWS_REGION env or boto3 default)")
    parser.add_argument("--s3-endpoint-url",
                        help="Custom S3 endpoint URL (for S3-compatible services)")

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

    # Source is required: exactly one of --input-dir or --s3-bucket
    if not args.input_dir and not args.s3_bucket:
        parser.error("must specify either --input-dir or --s3-bucket")
    if args.input_dir and args.s3_bucket:
        parser.error("--input-dir and --s3-bucket are mutually exclusive")

    import_database(args)


if __name__ == "__main__":
    main()
