"""Backfill single-name event clusters the batch deconfliction path skipped.

Diagnosis (2026-07-30): batch_prepare.load_unprocessed_clusters only loads
clusters with >1 unique event name (there is nothing for an LLM to
deconflict in a single-name cluster). The inline path handles that skip case
explicitly — marking the cluster deconflicted and creating its canonical
events — but the batch path has no equivalent, so the June 2026 rebuild left
~89K single-name clusters unprocessed and their events missing from the
event layer entirely.

This script applies the inline path's skip logic in bulk: for every
non-noise, un-deconflicted cluster whose event_names contain exactly one
unique name, it writes the standard "skipped LLM review" payload, sets
llm_deconflicted=True, and creates canonical events via the existing
LLMClusterDeconfliction.create_canonical_events_from_cluster (no LLM calls).

Usage:
    python services/pipeline/events/backfill_single_name_clusters.py --dry-run
    python services/pipeline/events/backfill_single_name_clusters.py
    python services/pipeline/events/backfill_single_name_clusters.py --limit 1000
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import text  # noqa: E402

from shared.database.database import get_session  # noqa: E402

CHECKPOINT_EVERY = 200


def eligible_cluster_ids(session, limit: int | None = None) -> list[str]:
    sql = """
        SELECT ec.id::text
        FROM event_clusters ec
        WHERE NOT ec.llm_deconflicted
          AND NOT ec.is_noise
          AND (SELECT count(DISTINCT n) FROM unnest(ec.event_names) n) = 1
        ORDER BY ec.cluster_date
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in session.execute(text(sql)).fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    from services.pipeline.events.llm_deconflict_clusters import (
        LLMClusterDeconfliction,
    )
    from shared.models.models import EventCluster

    processor = LLMClusterDeconfliction(dry_run=args.dry_run, verbose=False)

    with get_session() as session:
        ids = eligible_cluster_ids(session, args.limit)
    total = len(ids)
    print(f"eligible single-name clusters: {total}")
    if args.dry_run:
        print("dry-run: no changes made")
        return 0
    if not total:
        return 0

    stats = {"processed": 0, "events_created": 0, "events_updated": 0, "errors": 0}
    t0 = time.time()
    with get_session() as session:
        since_commit = 0
        for i, cid in enumerate(ids, 1):
            cluster = session.get(EventCluster, cid)
            if cluster is None or cluster.llm_deconflicted:
                continue
            unique_names = list(set(cluster.event_names or []))
            llm_result = {
                "same_event": True,
                "explanation": "Skipped LLM review - single unique event name "
                               "(batch-path backfill)",
                "original_cluster_size": cluster.cluster_size,
                "unique_event_names": len(unique_names),
                "groups": [[j + 1 for j in range(len(unique_names))]],
                "refined_cluster_ids": [cluster.cluster_id],
                "reviewed_at": datetime.utcnow().isoformat(),
                "unique_names_list": unique_names,
            }
            try:
                cluster.refined_clusters = llm_result
                cluster.llm_deconflicted = True
                canonical_events = processor.create_canonical_events_from_cluster(
                    session, cluster, llm_result
                )
                for ce in canonical_events:
                    if ce.total_mention_days == 1:
                        stats["events_created"] += 1
                    else:
                        stats["events_updated"] += 1
                stats["processed"] += 1
            except Exception as e:
                stats["errors"] += 1
                session.rollback()
                print(f"  error on cluster {cid}: {str(e)[:150]}")
                continue

            since_commit += 1
            if since_commit >= CHECKPOINT_EVERY:
                session.commit()
                since_commit = 0
                rate = i / max(time.time() - t0, 1)
                eta_min = (total - i) / max(rate, 0.1) / 60
                print(f"  [{i}/{total}] committed "
                      f"({rate:.0f}/s, ~{eta_min:.0f} min left)")
        session.commit()

    dt = time.time() - t0
    print(f"done in {dt/60:.1f} min: {stats}")
    return 0 if not stats["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
