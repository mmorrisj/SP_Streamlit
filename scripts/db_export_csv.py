#!/usr/bin/env python3
"""
Export all SoftPower database tables to CSV files (one per table).

Uses PostgreSQL COPY TO for native type serialization (JSONB → JSON strings,
ARRAY → {val1,val2} notation, UUIDs/ENUMs → text). CSVs are re-importable
with COPY FROM.

Skips LangChain embedding tables by default (use existing Parquet backup
system for those — see services/pipeline/embeddings/export_embeddings.py).

Usage:
    # Export using .env defaults
    python scripts/db_export_csv.py --output-dir ./db_csv_export

    # Export from Docker container
    python scripts/db_export_csv.py --output-dir ./db_csv_export --docker-container softpower_db

    # Include embedding tables (large!)
    python scripts/db_export_csv.py --output-dir ./db_csv_export --include-embeddings

    # Export specific tables only
    python scripts/db_export_csv.py --output-dir ./db_csv_export --tables documents categories

Import with:
    python scripts/db_import_csv.py --input-dir ./db_csv_export
"""

import argparse
import json
import os
import subprocess
import sys
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

# Tables to skip by default (embedding vectors are huge in CSV)
SKIP_TABLES = {
    "langchain_pg_embedding",
    "langchain_pg_collection",
}


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


def build_psql_cmd(conn, docker_container=None):
    """Build a psql command for querying metadata.

    When docker_container is set, uses an ephemeral container on the
    softpower_net network instead of docker exec (enterprise compatibility).
    """
    if docker_container:
        db_image = os.getenv("DB_IMAGE", "pgvector/pgvector:0.8.1-pg17")
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


def get_tables(conn, docker_container=None):
    """Get all user table names with row counts."""
    query = (
        "SELECT n.nspname, c.relname, c.reltuples::bigint "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' "
        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY n.nspname, c.relname;"
    )

    cmd = build_psql_cmd(conn, docker_container) + ["-c", query]
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    if result.returncode != 0:
        print(f"ERROR: Could not query tables: {result.stderr.strip()}")
        sys.exit(1)

    tables = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("("):
            continue
        parts = line.split("|")
        if len(parts) == 3:
            schema = parts[0].strip()
            name = parts[1].strip()
            try:
                rows = int(parts[2].strip())
            except ValueError:
                rows = -1
            tables.append({"schema": schema, "name": name, "rows": rows})
    return tables


def export_table_csv(conn, schema, table, output_path, docker_container=None):
    """Export a single table to CSV using COPY TO."""
    qualified = f'"{schema}"."{table}"'
    copy_cmd = f"\\COPY {qualified} TO STDOUT WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"

    psql_base = build_psql_cmd(conn, docker_container)
    cmd = psql_base + ["-c", copy_cmd]

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        process = subprocess.Popen(
            cmd, stdout=f, stderr=subprocess.PIPE, env=env
        )
        _, stderr = process.communicate()

    if process.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip()
        # Filter out collation warnings
        error_lines = [l for l in err_text.split("\n")
                       if l.strip() and "collation version" not in l.lower()]
        if error_lines:
            return False, "\n".join(error_lines)
    return True, None


def get_table_size(conn, schema, table, docker_container=None):
    """Get table size on disk."""
    query = f"SELECT pg_size_pretty(pg_total_relation_size('\"{schema}\".\"{table}\"'));"
    cmd = build_psql_cmd(conn, docker_container) + ["-c", query]
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "?"


def export_csv(args):
    """Main CSV export logic."""
    output_dir = Path(args.output_dir).resolve()
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

    # Display config
    print("=" * 60)
    print("  DATABASE CSV EXPORT")
    print("=" * 60)
    if docker_container:
        print(f"  Source:     docker container {docker_container} (via network)")
    else:
        print(f"  Source:     {conn['host']}:{conn['port']}")
    print(f"  Database:  {conn['dbname']}")
    print(f"  User:      {conn['user']}")
    print(f"  Output:    {output_dir}")
    print()

    # Get table list
    print("  Querying tables...")
    all_tables = get_tables(conn, docker_container)
    if not all_tables:
        print("ERROR: No tables found")
        sys.exit(1)

    # Filter tables
    if args.tables:
        # Export only specified tables
        requested = set(args.tables)
        tables = [t for t in all_tables if t["name"] in requested]
        missing = requested - {t["name"] for t in tables}
        if missing:
            print(f"  Warning: tables not found: {', '.join(sorted(missing))}")
    else:
        # Export all, with skip list
        skip = set() if args.include_embeddings else SKIP_TABLES
        tables = [t for t in all_tables if t["name"] not in skip]
        skipped = [t for t in all_tables if t["name"] in skip]
        if skipped:
            print(f"  Skipping embedding tables (use --include-embeddings to include):")
            for t in skipped:
                print(f"    {t['name']}: ~{t['rows']:,} rows")

    total_rows = sum(t["rows"] for t in tables if t["rows"] >= 0)
    print(f"  Exporting {len(tables)} tables (~{total_rows:,} total rows)")
    print()

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing manifest
    manifest_path = output_dir / "csv_manifest.json"
    if manifest_path.exists():
        print(f"ERROR: csv_manifest.json already exists in {output_dir}")
        print("  Remove the directory or choose a different output path.")
        sys.exit(1)

    # Export each table
    exported = []
    errors = []
    for i, t in enumerate(tables, 1):
        schema, name, approx_rows = t["schema"], t["name"], t["rows"]
        csv_filename = f"{name}.csv"
        csv_path = output_dir / csv_filename

        row_str = f"~{approx_rows:,} rows" if approx_rows >= 0 else "? rows"
        print(f"  [{i}/{len(tables)}] {schema}.{name} ({row_str})...",
              end="", flush=True)

        ok, err = export_table_csv(conn, schema, name, csv_path, docker_container)

        if not ok:
            print(f" FAILED")
            print(f"    {err}")
            errors.append({"table": f"{schema}.{name}", "error": err})
            if csv_path.exists():
                csv_path.unlink()
            continue

        file_size = csv_path.stat().st_size
        # Count actual rows (subtract 1 for header)
        with open(csv_path, "r", encoding="utf-8") as f:
            actual_rows = sum(1 for _ in f) - 1
            actual_rows = max(0, actual_rows)

        size_str = format_size(file_size)
        print(f" {actual_rows:,} rows, {size_str}")

        exported.append({
            "file": csv_filename,
            "schema": schema,
            "table": name,
            "rows": actual_rows,
            "size_bytes": file_size,
        })

    print()

    # Write manifest
    total_size = sum(e["size_bytes"] for e in exported)
    manifest = {
        "version": 1,
        "format": "csv",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_name": conn["dbname"],
        "tables": exported,
        "total_size_bytes": total_size,
        "errors": errors,
        "skipped_embedding_tables": not args.include_embeddings,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    # Summary
    total_rows_exported = sum(e["rows"] for e in exported)
    print("=" * 60)
    print("  CSV EXPORT COMPLETE")
    print("=" * 60)
    print(f"  Output:    {output_dir}")
    print(f"  Tables:    {len(exported)}")
    print(f"  Total rows: {total_rows_exported:,}")
    print(f"  Total size: {format_size(total_size)}")
    if errors:
        print(f"  Errors:    {len(errors)}")
    print(f"  Manifest:  csv_manifest.json")
    print()

    # List files sorted by size
    print("  Files:")
    for e in sorted(exported, key=lambda x: x["size_bytes"], reverse=True):
        print(f"    {e['file']:<45} {e['rows']:>10,} rows  {format_size(e['size_bytes']):>10}")
    print()

    if not args.include_embeddings:
        print("  Note: Embedding tables skipped. For embeddings, use:")
        print("    python services/pipeline/embeddings/export_embeddings.py")
    print()
    print("  To import on target system:")
    print(f"    python scripts/db_import_csv.py --input-dir {output_dir.name}")


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


def main():
    parser = argparse.ArgumentParser(
        description="Export SoftPower database tables to CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export all tables (skip embeddings)
  python scripts/db_export_csv.py --output-dir ./db_csv_export

  # Export from Docker container
  python scripts/db_export_csv.py --output-dir ./db_csv_export --docker-container softpower_db

  # Include embedding tables
  python scripts/db_export_csv.py --output-dir ./db_csv_export --include-embeddings

  # Export specific tables
  python scripts/db_export_csv.py --output-dir ./db_csv_export --tables documents categories
        """,
    )
    parser.add_argument("--output-dir", required=True,
                        help="Directory to write CSV files and manifest")
    parser.add_argument("--include-embeddings", action="store_true",
                        help="Include langchain embedding tables (very large)")
    parser.add_argument("--tables", nargs="+",
                        help="Export only these tables (by name, without schema)")

    # Connection params
    parser.add_argument("--host", help="Database host (default: from .env or localhost)")
    parser.add_argument("--port", help="Database port (default: from .env or 5432)")
    parser.add_argument("--user", help="Database user (default: from .env)")
    parser.add_argument("--password", help="Database password (default: from .env)")
    parser.add_argument("--dbname", help="Database name (default: from .env)")

    # Docker
    parser.add_argument("--docker-container",
                        nargs="?", const="auto", default=None,
                        help="Run psql inside this Docker container "
                             "(omit value to auto-detect)")

    args = parser.parse_args()
    export_csv(args)


if __name__ == "__main__":
    main()
