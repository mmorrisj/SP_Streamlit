"""
Embed AidData GCDF 3.0 Projects into pgvector

Embeds project title + description + location narrative into the
chunk_embeddings collection so the RAG chat system can find AidData
projects alongside regular documents.

Projects are tagged with source='aiddata' in cmetadata for filtering.
Embedding IDs (custom_id) are stable: aiddata_{record_id} — safe to re-run.

Usage:
    python services/pipeline/embeddings/embed_aiddata.py
    python services/pipeline/embeddings/embed_aiddata.py --status
    python services/pipeline/embeddings/embed_aiddata.py --dry-run
    python services/pipeline/embeddings/embed_aiddata.py --batch-size 25
    python services/pipeline/embeddings/embed_aiddata.py --recommended-only
    python services/pipeline/embeddings/embed_aiddata.py --limit 100
"""

import argparse
import json
import sys
import uuid as uuid_lib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import text
from shared.database.database import get_session, get_engine
from shared.models.models import AidDataProject
from shared.utils.model_cache import get_hf_embeddings

COLLECTION_NAME = 'chunk_embeddings'
MAX_DESCRIPTION_CHARS = 1800  # ~512 tokens for all-MiniLM-L6-v2


# ---------------------------------------------------------------------------
# Text / metadata builders
# ---------------------------------------------------------------------------

def build_embed_text(project: AidDataProject) -> str:
    parts = []
    if project.title:
        parts.append(project.title)
    if project.description:
        desc = project.description.strip()
        if len(desc) > MAX_DESCRIPTION_CHARS:
            desc = desc[:MAX_DESCRIPTION_CHARS] + '...'
        parts.append(desc)
    if project.location_narrative:
        loc = project.location_narrative.strip()
        if loc:
            parts.append(f"Location: {loc[:400]}")
    return '\n\n'.join(parts)


def build_metadata(project: AidDataProject) -> dict:
    return {
        'source':               'aiddata',
        'aiddata_record_id':    str(project.aiddata_record_id),
        'recipient':            project.recipient or '',
        'recipient_iso3':       project.recipient_iso3 or '',
        'recipient_region':     project.recipient_region or '',
        'commitment_year':      str(project.commitment_year) if project.commitment_year else '',
        'flow_type_simplified': project.flow_type_simplified or '',
        'flow_class':           project.flow_class or '',
        'sector_name':          project.sector_name or '',
        'sector_code':          str(project.sector_code) if project.sector_code else '',
        'amount_usd_2021':      str(project.amount_usd_2021) if project.amount_usd_2021 else '',
        'infrastructure':       str(project.infrastructure) if project.infrastructure is not None else '',
        'status':               project.status or '',
        'funding_agencies':     project.funding_agencies or '',
        'title':                project.title or '',
    }


# ---------------------------------------------------------------------------
# DB helpers — works with the actual schema (uuid PK + custom_id varchar)
# ---------------------------------------------------------------------------

def get_collection_uuid(engine) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT uuid FROM langchain_pg_collection WHERE name = :name"),
            {"name": COLLECTION_NAME}
        ).fetchone()
    if row is None:
        raise RuntimeError(
            f"Collection '{COLLECTION_NAME}' not found in langchain_pg_collection. "
            "Run the main document embedding pipeline first to create it."
        )
    return str(row[0])


def get_already_embedded_ids(engine) -> set:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT custom_id
            FROM langchain_pg_embedding
            WHERE custom_id LIKE 'aiddata_%'
            AND collection_id = (
                SELECT uuid FROM langchain_pg_collection WHERE name = :name
            )
        """), {"name": COLLECTION_NAME}).fetchall()
    return {row[0] for row in rows if row[0]}


def insert_batch(engine, collection_uuid: str, texts, metadatas, custom_ids, embeddings):
    """Insert a batch directly using the actual table schema via raw psycopg2."""
    rows = []
    for text_val, meta, cid, emb in zip(texts, metadatas, custom_ids, embeddings):
        rows.append((
            str(uuid_lib.uuid4()),             # uuid
            collection_uuid,                   # collection_id
            '[' + ','.join(str(x) for x in emb) + ']',  # embedding
            text_val,                          # document
            json.dumps(meta),                  # cmetadata
            cid,                               # custom_id
        ))

    sql = """
        INSERT INTO langchain_pg_embedding
            (uuid, collection_id, embedding, document, cmetadata, custom_id)
        VALUES
            (%s::uuid, %s::uuid, %s::vector, %s, %s::json, %s)
        ON CONFLICT (uuid) DO NOTHING
    """
    with engine.connect() as conn:
        raw = conn.connection.cursor()
        raw.executemany(sql, rows)
        conn.connection.commit()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_embedding_status(engine):
    print(f"\n{'='*70}")
    print("AidData Embedding Status")
    print(f"{'='*70}")

    with get_session() as session:
        total       = session.query(AidDataProject).count()
        recommended = session.query(AidDataProject).filter(
            AidDataProject.recommended_for_aggregates == True
        ).count()

    already = len(get_already_embedded_ids(engine))
    print(f"  Total projects in DB:       {total:,}")
    print(f"  Recommended for aggregates: {recommended:,}")
    print(f"  Already embedded:           {already:,}")
    print(f"  Remaining:                  {total - already:,}")
    if total > 0:
        print(f"  Coverage:                   {already/total*100:.1f}%")
    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# Main embedding loop
# ---------------------------------------------------------------------------

def embed_aiddata_projects(
    dry_run: bool = False,
    batch_size: int = 50,
    recommended_only: bool = False,
    limit: int = None,
):
    engine = get_engine()
    already_embedded = get_already_embedded_ids(engine)
    print(f"  {len(already_embedded):,} projects already embedded — skipping")

    with get_session() as session:
        query = session.query(AidDataProject)
        if recommended_only:
            query = query.filter(AidDataProject.recommended_for_aggregates == True)
        query = query.order_by(AidDataProject.commitment_year.desc())
        projects = query.all()

    to_embed = [p for p in projects if f"aiddata_{p.aiddata_record_id}" not in already_embedded]
    if limit:
        to_embed = to_embed[:limit]

    total = len(to_embed)
    print(f"  {total:,} projects to embed")

    if total == 0:
        print("  Nothing to do.")
        return 0

    if dry_run:
        print(f"\n  [DRY RUN] Would embed {total:,} projects in batches of {batch_size}")
        for p in to_embed[:3]:
            t = build_embed_text(p)
            print(f"\n  --- Record {p.aiddata_record_id} ({p.recipient}, {p.commitment_year}) ---")
            print(f"  Text length: {len(t)} chars")
            print(f"  Preview: {t[:200]}...")
        return 0

    collection_uuid = get_collection_uuid(engine)
    print(f"  Collection UUID: {collection_uuid}")

    embedding_fn = get_hf_embeddings()
    embedded = skipped = errors = 0
    start = datetime.now()

    for i in range(0, total, batch_size):
        batch = to_embed[i:i + batch_size]
        texts, metadatas, custom_ids = [], [], []

        for project in batch:
            embed_text = build_embed_text(project)
            if not embed_text.strip():
                skipped += 1
                continue
            texts.append(embed_text)
            metadatas.append(build_metadata(project))
            custom_ids.append(f"aiddata_{project.aiddata_record_id}")

        if not texts:
            continue

        try:
            embeddings = embedding_fn.embed_documents(texts)
            insert_batch(engine, collection_uuid, texts, metadatas, custom_ids, embeddings)
            embedded += len(texts)
            elapsed = (datetime.now() - start).total_seconds()
            rate = embedded / elapsed if elapsed > 0 else 0
            remaining_secs = (total - embedded) / rate if rate > 0 else 0
            print(
                f"  [{embedded:>6,}/{total:,}]  {rate:.1f}/s  ~{remaining_secs/60:.1f}min remaining   ",
                end='\r'
            )
        except Exception as e:
            print(f"\n  [ERROR] batch starting at {i}: {e}")
            errors += 1

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n  Done — {embedded:,} embedded, {skipped} skipped (no text), {errors} batch errors")
    print(f"  Total time: {elapsed:.0f}s  ({embedded/elapsed:.1f}/s avg)")
    return embedded


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Embed AidData GCDF 3.0 projects into pgvector")
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--status', action='store_true', help='Show coverage and exit')
    parser.add_argument('--batch-size', type=int, default=50)
    parser.add_argument('--recommended-only', action='store_true',
                        help='Only embed projects flagged Recommended For Aggregates')
    parser.add_argument('--limit', type=int, help='Cap number of projects (for testing)')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation')
    args = parser.parse_args()

    engine = get_engine()
    get_embedding_status(engine)

    if args.status:
        sys.exit(0)

    scope = 'recommended' if args.recommended_only else 'all'
    print(f"  Scope: {scope} | Batch size: {args.batch_size}")
    if args.limit:
        print(f"  Limit: {args.limit}")

    if not args.dry_run and not args.yes:
        resp = input("\nProceed with embedding? [y/N]: ").strip().lower()
        if resp != 'y':
            print("Cancelled.")
            sys.exit(0)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Starting — {datetime.now():%Y-%m-%d %H:%M:%S}")

    embed_aiddata_projects(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        recommended_only=args.recommended_only,
        limit=args.limit,
    )

    if not args.dry_run:
        print()
        get_embedding_status(engine)


if __name__ == '__main__':
    main()
