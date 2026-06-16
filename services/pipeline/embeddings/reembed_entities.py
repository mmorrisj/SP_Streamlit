"""Re-embed canonical_entities.embedding_vector with the current model.

Entity vectors feed the entity-matching step of RAG (services/chat/rag_service.py),
where the *query* is embedded with nomic's ``search_query:`` prefix
(embed_query). For the asymmetric match to work well, the stored entity
vectors must be produced with the matching ``search_document:`` prefix
(embed_documents) — not a raw ``encode()`` (no prefix), which the legacy
consolidation path used. This tool rebuilds them with the correct prefix.

It also fixes the dimension migration: datasets built before
nomic-embed-text-v1.5 carry 384-dim vectors (old all-MiniLM-L6-v2), which
fail pgvector search with "different vector dimensions 384 and 768".

Source rows are untouched; only embedding_vector is rewritten.

Modes:
  default       re-embed masters whose stored dim != the current model
  --include-null  also embed masters with no vector yet
  --all         re-embed every master with a name (use after a model/prefix
                change, to overwrite no-prefix or stale vectors) + fills nulls

Run inside the app image (model baked in, services/pipeline present in 1.8.14+):
    docker exec sp_laptop_app python -m services.pipeline.embeddings.reembed_entities --status
    docker exec sp_laptop_app python -m services.pipeline.embeddings.reembed_entities --all
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
    """nomic embeddings wrapper: embed_documents applies the search_document prefix."""
    from shared.utils.model_cache import get_hf_embeddings
    return get_hf_embeddings()


def status() -> dict:
    """Report the current embedding-dimension distribution for master entities."""
    with get_session() as session:
        rows = session.execute(text(
            """
            SELECT array_length(embedding_vector, 1) AS dim, count(*) AS n
            FROM canonical_entities
            WHERE master_entity_id IS NULL AND embedding_vector IS NOT NULL
            GROUP BY 1 ORDER BY 1
            """
        )).fetchall()
        nulls = session.execute(text(
            "SELECT count(*) FROM canonical_entities "
            "WHERE master_entity_id IS NULL AND embedding_vector IS NULL"
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
    """Re-embed master canonical entities using the search_document prefix.

    force_all: re-embed every master with a name (overwrite no-prefix/stale).
    include_null: also embed masters with no vector yet.
    default: only masters whose stored dim differs from the current model.
    """
    emb = _embedder()
    dim = len(emb.embed_documents(["dimension probe"])[0])

    if force_all:
        where = "master_entity_id IS NULL AND canonical_name IS NOT NULL"
    else:
        where = (
            "master_entity_id IS NULL AND ("
            "(embedding_vector IS NOT NULL AND array_length(embedding_vector, 1) <> :dim)"
        )
        if include_null:
            where += " OR embedding_vector IS NULL"
        where += ")"

    params = {} if force_all else {"dim": dim}
    with get_session() as session:
        rows = session.execute(
            text(f"SELECT id::text AS id, canonical_name FROM canonical_entities WHERE {where}"),
            params,
        ).fetchall()

    total = len(rows)
    logger.info("Re-embedding %d entities at %d-dim (search_document prefix)%s",
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
                        "UPDATE canonical_entities "
                        "SET embedding_vector = CAST(:vec AS double precision[]) "
                        "WHERE id = :id"
                    ),
                    {"vec": vec, "id": row.id},
                )
            session.commit()
            updated += len(chunk)
            logger.info("  %d / %d", updated, total)

    return {"target_dim": dim, "to_reembed": total, "updated": updated}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Re-embed canonical_entities with the current model + prefix")
    p.add_argument("--status", action="store_true", help="Report dimension distribution and exit")
    p.add_argument("--dry-run", action="store_true", help="Report how many would be re-embedded, no writes")
    p.add_argument("--include-null", action="store_true", help="Also embed masters with no vector yet")
    p.add_argument("--all", dest="force_all", action="store_true",
                   help="Re-embed every master with a name (overwrite no-prefix/stale + fill nulls)")
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
