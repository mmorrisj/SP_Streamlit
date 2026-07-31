"""Re-embed canonical_events.embedding_vector with the current model + prefix.

Event vectors feed Stage-2 consolidation (consolidate_all_events.py /
layered_consolidate_events.py) and any similarity lookup against them. The
legacy creation path wrote raw ``encode()`` vectors (no ``search_document:``
prefix, not normalized), which live in a different similarity space from the
prefixed vectors retrieval and reembed_entities.py produce. This tool
rebuilds all master event vectors with the correct prefix so consolidation
thresholds behave consistently across rows.

Source rows are untouched; only embedding_vector is rewritten.

Modes mirror reembed_entities.py:
  default         re-embed masters whose stored dim != the current model
  --include-null  also embed masters with no vector yet
  --all           re-embed every master (use after a model/prefix change)

Run inside the app image (model baked in):
    docker exec sp_laptop_app python -m services.pipeline.embeddings.reembed_events --status
    docker exec sp_laptop_app python -m services.pipeline.embeddings.reembed_events --all
"""
from __future__ import annotations

import argparse
import json
import logging

from sqlalchemy import text

from shared.database.database import get_session

logger = logging.getLogger(__name__)

BATCH_SIZE = 256


def _embedder():
    from shared.utils.model_cache import get_hf_embeddings
    return get_hf_embeddings()


def status() -> dict:
    with get_session() as session:
        rows = session.execute(text(
            """
            SELECT array_length(embedding_vector, 1) AS dim, count(*) AS n
            FROM canonical_events
            WHERE master_event_id IS NULL AND embedding_vector IS NOT NULL
            GROUP BY 1 ORDER BY 1
            """
        )).fetchall()
        nulls = session.execute(text(
            "SELECT count(*) FROM canonical_events "
            "WHERE master_event_id IS NULL AND embedding_vector IS NULL"
        )).scalar()
    return {
        "by_dim": {(int(r.dim) if r.dim is not None else None): int(r.n) for r in rows},
        "null_embedding": int(nulls or 0),
    }


def reembed(
    batch_size: int = BATCH_SIZE,
    include_null: bool = False,
    force_all: bool = False,
    dry_run: bool = False,
) -> dict:
    emb = _embedder()
    dim = len(emb.embed_documents(["dimension probe"])[0])

    if force_all:
        where = "master_event_id IS NULL AND canonical_name IS NOT NULL"
    else:
        where = (
            "master_event_id IS NULL AND ("
            "(embedding_vector IS NOT NULL AND array_length(embedding_vector, 1) <> :dim)"
        )
        if include_null:
            where += " OR embedding_vector IS NULL"
        where += ")"

    params = {} if force_all else {"dim": dim}
    with get_session() as session:
        rows = session.execute(
            text(f"SELECT id::text AS id, canonical_name FROM canonical_events WHERE {where}"),
            params,
        ).fetchall()

    total = len(rows)
    logger.info("Re-embedding %d events at %d-dim (search_document prefix)%s",
                total, dim, " (dry run)" if dry_run else "")
    if dry_run or total == 0:
        return {"target_dim": dim, "to_reembed": total, "updated": 0}

    updated = 0
    with get_session() as session:
        for start in range(0, total, batch_size):
            chunk = rows[start:start + batch_size]
            names = [r.canonical_name or "" for r in chunk]
            vectors = emb.embed_documents(names)
            for row, vec in zip(chunk, vectors):
                session.execute(
                    text(
                        "UPDATE canonical_events "
                        "SET embedding_vector = CAST(:vec AS double precision[]) "
                        "WHERE id = :id"
                    ),
                    {"vec": vec, "id": row.id},
                )
            session.commit()
            updated += len(chunk)
            if updated % 5120 == 0 or updated == total:
                logger.info("  %d / %d", updated, total)

    return {"target_dim": dim, "to_reembed": total, "updated": updated}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Re-embed canonical_events with the current model + prefix")
    p.add_argument("--status", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--include-null", action="store_true")
    p.add_argument("--all", dest="force_all", action="store_true")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = p.parse_args()

    if args.status:
        print(json.dumps(status(), indent=2))
        return

    summary = reembed(
        batch_size=args.batch_size,
        include_null=args.include_null,
        force_all=args.force_all,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
