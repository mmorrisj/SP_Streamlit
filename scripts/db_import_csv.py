#!/usr/bin/env python3
"""
Import CSV files exported by db_export_csv.py into a PostgreSQL database.

Uses PostgreSQL COPY FROM for fast, type-safe loading. Handles all PostgreSQL
types (JSONB, ARRAY, UUID, ENUMs) since COPY preserves the original text
representation.

Tables are loaded in dependency order (parent tables first) to satisfy
foreign key constraints.

Usage:
    # Import using .env defaults
    python scripts/db_import_csv.py --input-dir ./db_csv_export

    # Import into a different database
    python scripts/db_import_csv.py --input-dir ./db_csv_export \
        --target-host newserver --target-db softpower-db

    # Create database + extensions first
    python scripts/db_import_csv.py --input-dir ./db_csv_export --create-db

    # Truncate tables before import (keeps schema)
    python scripts/db_import_csv.py --input-dir ./db_csv_export --truncate

    # Dry run
    python scripts/db_import_csv.py --input-dir ./db_csv_export --dry-run
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Load .env for default connection params
try:
    from dotenv import load_dotenv, find_dotenv
    env_file = find_dotenv(usecwd=True)
    if env_file:
        load_dotenv(env_file, override=True)
except ImportError:
    pass

# Tables ordered by dependency (parents first).
# Tables not in this list are loaded after all listed tables.
TABLE_LOAD_ORDER = [
    # Independent tables first
    "users",
    "aiddata_projects",
    "langchain_pg_collection",
    # Core document table
    "documents",
    # Document relationship tables (depend on documents)
    "categories",
    "subcategories",
    "initiating_countries",
    "recipient_countries",
    "raw_events",
    "raw_entities",
    # Event pipeline
    "event_clusters",
    "canonical_events",
    "daily_event_mentions",
    "event_summaries",
    "event_source_links",
    "period_summaries",
    # Entity pipeline
    "entity_clusters",
    "canonical_entities",
    "daily_entity_mentions",
    "entity_relationships",
    # Summary tables
    "bilateral_relationship_summaries",
    "country_category_summaries",
    "bilateral_category_summaries",
    # Batch tracking
    "batch_jobs",
    # AidData sub-table
    "aiddata_locations",
    # Embeddings (if included)
    "langchain_pg_embedding",
]


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


def build_psql_cmd(conn, docker_container=None, dbname_override=None):
    """Build a psql command."""
    dbname = dbname_override or conn["dbname"]
    if docker_container:
        return [
            "docker", "exec", "-i", docker_container,
            "psql",
            "--host=localhost",
            "--port=5432",
            f"--username={conn['user']}",
            f"--dbname={dbname}",
        ]
    else:
        return [
            "psql",
            f"--host={conn['host']}",
            f"--port={conn['port']}",
            f"--username={conn['user']}",
            f"--dbname={dbname}",
        ]


def create_database(conn, docker_container=None):
    """Create the target database and extensions."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    psql_cmd = build_psql_cmd(conn, docker_container, dbname_override="postgres")

    # Check if database exists
    check_query = f"SELECT 1 FROM pg_database WHERE datname = '{conn['dbname']}';"
    result = subprocess.run(
        psql_cmd + ["--tuples-only", "--no-align", "-c", check_query],
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

    # Create extensions in target database
    target_psql = build_psql_cmd(conn, docker_container)
    for ext in ["vector", "pg_trgm"]:
        result = subprocess.run(
            target_psql + ["-c", f"CREATE EXTENSION IF NOT EXISTS {ext};"],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode == 0:
            print(f"  Extension '{ext}' enabled")
        else:
            print(f"  Warning: Could not create {ext}: {result.stderr.strip()}")

    return True


def truncate_table(conn, schema, table, docker_container=None):
    """Truncate a table with CASCADE."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    psql_cmd = build_psql_cmd(conn, docker_container)
    query = f'TRUNCATE "{schema}"."{table}" CASCADE;'
    result = subprocess.run(
        psql_cmd + ["-c", query],
        capture_output=True, text=True, timeout=60, env=env
    )
    return result.returncode == 0


def import_table_csv(conn, schema, table, csv_path, docker_container=None):
    """Import a CSV file into a table using COPY FROM."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    qualified = f'"{schema}"."{table}"'
    copy_cmd = f"\\COPY {qualified} FROM STDIN WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"

    psql_cmd = build_psql_cmd(conn, docker_container) + ["-c", copy_cmd]

    with open(csv_path, "r", encoding="utf-8") as f:
        process = subprocess.Popen(
            psql_cmd, stdin=f, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env
        )
        stdout, stderr = process.communicate()

    if process.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip()
        # Filter collation warnings
        error_lines = [l for l in err_text.split("\n")
                       if l.strip() and "collation version" not in l.lower()]
        if error_lines:
            return False, "\n".join(error_lines)
    return True, None


def get_table_counts(conn, docker_container=None):
    """Get row counts for all tables in target database."""
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

    psql_cmd = build_psql_cmd(conn, docker_container) + [
        "--tuples-only", "--no-align", "-c", query
    ]

    # Run ANALYZE first
    analyze_cmd = build_psql_cmd(conn, docker_container) + ["-c", "ANALYZE;"]
    subprocess.run(analyze_cmd, capture_output=True, text=True, timeout=120, env=env)

    result = subprocess.run(psql_cmd, capture_output=True, text=True, timeout=30, env=env)
    counts = {}
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().split("|")
            if len(parts) == 2:
                try:
                    counts[parts[0].strip()] = int(parts[1].strip())
                except ValueError:
                    pass
    return counts


def format_size(size_bytes):
    """Human-readable file size."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024**3):.2f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024**2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} B"


def import_csv(args):
    """Main CSV import logic."""
    input_dir = Path(args.input_dir).resolve()
    conn = get_connection_params(args)

    # Determine Docker container
    docker_container = args.docker_container
    if docker_container == "auto":
        docker_container = detect_docker_container()
        if docker_container:
            print(f"  Auto-detected Docker container: {docker_container}")
        else:
            print("  No Docker container detected, using local psql")
            docker_container = None

    # Read manifest
    manifest_path = input_dir / "csv_manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: csv_manifest.json not found in {input_dir}")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())

    # Display info
    print("=" * 60)
    print("  DATABASE CSV IMPORT")
    print("=" * 60)
    print(f"  Source dir:    {input_dir}")
    print(f"  Export date:   {manifest.get('created_at', 'unknown')}")
    print(f"  Source DB:     {manifest.get('database_name', 'unknown')}")
    total_rows = sum(t["rows"] for t in manifest["tables"])
    total_size = manifest.get("total_size_bytes", 0)
    print(f"  Tables:        {len(manifest['tables'])}")
    print(f"  Total rows:    {total_rows:,}")
    print(f"  Total size:    {format_size(total_size)}")
    print()

    if docker_container:
        print(f"  Target:        docker exec {docker_container}")
    else:
        print(f"  Target:        {conn['host']}:{conn['port']}")
    print(f"  Target DB:     {conn['dbname']}")
    print(f"  Target user:   {conn['user']}")
    if args.truncate:
        print(f"  Mode:          TRUNCATE tables before import")
    print()

    # Verify CSV files exist
    missing = []
    for t in manifest["tables"]:
        csv_path = input_dir / t["file"]
        if not csv_path.exists():
            missing.append(t["file"])
    if missing:
        print(f"ERROR: Missing CSV files:")
        for f in missing:
            print(f"  {f}")
        sys.exit(1)
    print(f"  All {len(manifest['tables'])} CSV files present")
    print()

    if args.dry_run:
        print("  Dry run complete. No changes made.")
        return

    # Create database if requested
    if args.create_db:
        if not create_database(conn, docker_container):
            sys.exit(1)
        print()

    # Sort tables by dependency order
    table_entries = manifest["tables"]
    order_map = {name: i for i, name in enumerate(TABLE_LOAD_ORDER)}
    max_order = len(TABLE_LOAD_ORDER)
    table_entries_sorted = sorted(
        table_entries,
        key=lambda t: order_map.get(t["table"], max_order)
    )

    # Disable FK constraints during import for speed and to handle circular deps
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    # Import each table
    imported = []
    errors = []
    for i, t in enumerate(table_entries_sorted, 1):
        schema = t["schema"]
        table = t["table"]
        csv_path = input_dir / t["file"]
        expected_rows = t["rows"]

        print(f"  [{i}/{len(table_entries_sorted)}] {schema}.{table} "
              f"({expected_rows:,} rows, {format_size(t['size_bytes'])})...",
              end="", flush=True)

        # Truncate if requested
        if args.truncate:
            truncate_table(conn, schema, table, docker_container)

        ok, err = import_table_csv(conn, schema, table, csv_path, docker_container)

        if not ok:
            print(f" FAILED")
            print(f"    {err}")
            errors.append({"table": f"{schema}.{table}", "error": err})
            continue

        print(f" OK")
        imported.append(t)

    print()

    # Verify row counts
    if imported:
        print("  Verifying row counts...")
        target_counts = get_table_counts(conn, docker_container)

        print(f"  {'Table':<45} {'CSV':>10} {'Target':>10} {'Status':>8}")
        print(f"  {'-'*45} {'-'*10} {'-'*10} {'-'*8}")

        mismatches = 0
        for t in table_entries_sorted:
            key = f"{t['schema']}.{t['table']}"
            csv_rows = t["rows"]
            target_rows = target_counts.get(key, -1)

            if target_rows < 0:
                status = "???"
            elif csv_rows == target_rows:
                status = "OK"
            elif abs(csv_rows - target_rows) <= max(1, csv_rows * 0.01):
                status = "~OK"
            else:
                status = "DIFF"
                mismatches += 1

            target_str = f"{target_rows:,}" if target_rows >= 0 else "n/a"
            print(f"  {key:<45} {csv_rows:>10,} {target_str:>10} {status:>8}")

        if mismatches:
            print(f"\n  WARNING: {mismatches} table(s) differ. Run ANALYZE and re-check.")
        else:
            print(f"\n  All tables verified OK")

    # Summary
    print()
    print("=" * 60)
    print("  CSV IMPORT COMPLETE")
    print("=" * 60)
    print(f"  Imported:  {len(imported)} tables")
    if errors:
        print(f"  Errors:    {len(errors)}")
        for e in errors:
            print(f"    {e['table']}: {e['error'][:80]}")
    print()
    print("  Next steps:")
    print("    1. Verify application connectivity")
    print("    2. Run: alembic upgrade head  (apply any pending migrations)")
    if manifest.get("skipped_embedding_tables"):
        print("    3. Restore embeddings separately:")
        print("       python services/pipeline/embeddings/import_embeddings.py --input-dir <backup>")


def main():
    parser = argparse.ArgumentParser(
        description="Import CSV files into PostgreSQL database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import using .env defaults
  python scripts/db_import_csv.py --input-dir ./db_csv_export

  # Import into a different host
  python scripts/db_import_csv.py --input-dir ./db_csv_export \\
      --target-host newserver --target-db softpower-db

  # Create database + extensions first
  python scripts/db_import_csv.py --input-dir ./db_csv_export --create-db

  # Truncate existing data before import
  python scripts/db_import_csv.py --input-dir ./db_csv_export --truncate

  # Dry run
  python scripts/db_import_csv.py --input-dir ./db_csv_export --dry-run
        """,
    )
    parser.add_argument("--input-dir", required=True,
                        help="Directory containing CSV files and csv_manifest.json")

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
                        help="Run psql inside this Docker container "
                             "(omit value to auto-detect)")

    # Database setup
    parser.add_argument("--create-db", action="store_true",
                        help="Create target database and extensions if missing")
    parser.add_argument("--truncate", action="store_true",
                        help="Truncate tables before importing (CASCADE)")

    # Options
    parser.add_argument("--dry-run", action="store_true",
                        help="Verify files and display manifest only, no import")

    args = parser.parse_args()
    import_csv(args)


if __name__ == "__main__":
    main()
