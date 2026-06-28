"""
Post-rebuild data validation battery.

Runs a series of structural + correctness + scope checks across every layer the
pipeline produces (embeddings -> events -> summaries -> entities), each with a
clear PASS / FAIL / WARN verdict. Read-only; safe to run anytime.

Usage (inside the embed/preprocessing container):
    python services/pipeline/diagnostics/validate_rebuild.py
    python services/pipeline/diagnostics/validate_rebuild.py --country China
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from sqlalchemy import text

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session

PASS, FAIL, WARN, SKIP = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m", "\033[93mWARN\033[0m", "SKIP"
_counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}


def _load_config():
    cfg_path = project_root / "shared" / "config" / "config.yaml"
    with cfg_path.open() as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("influencers", []), cfg.get("recipients", [])


def _table_exists(session, name: str) -> bool:
    return session.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar() is not None


def check(label: str, verdict: str, detail: str = ""):
    tag = {"PASS": PASS, "FAIL": FAIL, "WARN": WARN, "SKIP": SKIP}[verdict]
    _counts[verdict] += 1
    print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))


def section(title: str):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def scalar(session, sql, **params):
    return session.execute(text(sql), params).scalar()


def main():
    ap = argparse.ArgumentParser(description="Validate rebuilt pipeline data")
    ap.add_argument("--country", help="Restrict country-scoped checks to one country")
    args = ap.parse_args()

    influencers, recipients = _load_config()
    country_filter = " AND initiating_country = :c" if args.country else ""
    cp = {"c": args.country} if args.country else {}

    with get_session() as session:
        # ---- Layer 0: embeddings ----
        section("LAYER 0 — Document embeddings (the original fix)")
        total_emb = scalar(session, """
            SELECT count(*) FROM langchain_pg_embedding e
            JOIN langchain_pg_collection c ON e.collection_id=c.uuid
            WHERE c.name='chunk_embeddings'""")
        check("chunk_embeddings present", PASS if total_emb else FAIL, f"{total_emb:,} rows")
        dims = session.execute(text("""
            SELECT DISTINCT vector_dims(embedding) FROM langchain_pg_embedding e
            JOIN langchain_pg_collection c ON e.collection_id=c.uuid
            WHERE c.name='chunk_embeddings'""")).scalars().all()
        check("all chunk vectors are 768-dim", PASS if dims == [768] else FAIL, f"dims={dims}")

        # ---- Layer 1: events ----
        section("LAYER 1 — Event clustering & deconfliction")
        undecon = scalar(session, f"SELECT count(*) FROM event_clusters WHERE llm_deconflicted=false{country_filter}", **cp)
        check("all event_clusters deconflicted", PASS if undecon == 0 else WARN, f"{undecon:,} still pending")

        n_canon = scalar(session, f"SELECT count(*) FROM canonical_events WHERE 1=1{country_filter}", **cp)
        check("canonical_events present", PASS if n_canon else FAIL, f"{n_canon:,} events")

        # orphan canonical_events (no mentions) — the known historical bug
        orphans = scalar(session, f"""
            SELECT count(*) FROM canonical_events ce
            WHERE NOT EXISTS (SELECT 1 FROM daily_event_mentions m WHERE m.canonical_event_id=ce.id)
            {country_filter}""", **cp)
        check("no orphan canonical_events (every event has mentions)", PASS if orphans == 0 else FAIL, f"{orphans:,} orphans")

        # orphan mentions (point to a missing event)
        orphan_m = scalar(session, """
            SELECT count(*) FROM daily_event_mentions m
            WHERE NOT EXISTS (SELECT 1 FROM canonical_events ce WHERE ce.id=m.canonical_event_id)""")
        check("no orphan daily_event_mentions", PASS if orphan_m == 0 else FAIL, f"{orphan_m:,} dangling")

        # master/child integrity
        bad_master = scalar(session, """
            SELECT count(*) FROM canonical_events c
            WHERE c.master_event_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM canonical_events m WHERE m.id=c.master_event_id)""")
        check("master_event_id references valid masters", PASS if bad_master == 0 else FAIL, f"{bad_master:,} broken")

        n_master = scalar(session, f"SELECT count(*) FROM canonical_events WHERE master_event_id IS NULL{country_filter}", **cp)
        check("multi-day consolidation ran (master events exist)", PASS if n_master else WARN, f"{n_master:,} masters")

        validated = scalar(session, f"SELECT count(*) FROM canonical_events WHERE llm_validated=true{country_filter}", **cp)
        check("canonical_deconflict ran (events validated)", PASS if validated else WARN, f"{validated:,} validated")

        # embeddings on canonical events (768-dim, set during deconflict)
        emb_dims = session.execute(text("""
            SELECT DISTINCT array_length(embedding_vector,1) FROM canonical_events
            WHERE embedding_vector IS NOT NULL""")).scalars().all()
        check("canonical_event embeddings are 768-dim", PASS if emb_dims in ([768], []) else WARN, f"dims={emb_dims}")

        # ---- Layer 2: scope correctness (MENA) ----
        section("LAYER 2 — Scope correctness (MENA recipients / influencer initiators)")
        bad_init = session.execute(text(f"""
            SELECT DISTINCT initiating_country FROM canonical_events
            WHERE initiating_country <> ALL(:inf){country_filter}"""), {"inf": influencers, **cp}).scalars().all()
        check("all initiating_country in config influencers", PASS if not bad_init else FAIL, f"unexpected: {bad_init}")

        bad_recip = session.execute(text(f"""
            SELECT DISTINCT k FROM canonical_events ce, jsonb_object_keys(ce.primary_recipients) AS k
            WHERE k <> ALL(:rec){country_filter}"""), {"rec": recipients, **cp}).scalars().all()
        check("all recipients in config MENA list", PASS if not bad_recip else FAIL, f"unexpected: {bad_recip[:10]}")

        self_dir = scalar(session, f"""
            SELECT count(*) FROM canonical_events ce
            WHERE ce.primary_recipients ? ce.initiating_country{country_filter}""", **cp)
        check("no self-directed events (recipient == initiator)", PASS if self_dir == 0 else WARN, f"{self_dir:,} found")

        # ---- Layer 3: summaries & materiality ----
        section("LAYER 3 — Summaries & materiality")
        for period in ("daily", "weekly", "monthly"):
            n = scalar(session, f"SELECT count(*) FROM event_summaries WHERE period_type=:p{country_filter}", p=period, **cp)
            check(f"{period} event_summaries present", PASS if n else WARN, f"{n:,}")
        scored = scalar(session, f"SELECT count(*) FROM event_summaries WHERE material_score IS NOT NULL{country_filter}", **cp)
        tot_sum = scalar(session, f"SELECT count(*) FROM event_summaries WHERE 1=1{country_filter}", **cp)
        check("summary materiality scored", PASS if scored else WARN, f"{scored:,}/{tot_sum:,} scored")
        ev_scored = scalar(session, f"SELECT count(*) FROM canonical_events WHERE material_score IS NOT NULL{country_filter}", **cp)
        check("event materiality scored", PASS if ev_scored else WARN, f"{ev_scored:,} events scored")
        if _table_exists(session, "event_source_links"):
            linked = scalar(session, "SELECT count(DISTINCT event_summary_id) FROM event_source_links")
            check("summaries have source attribution (EventSourceLink)", PASS if linked else WARN, f"{linked:,} summaries linked")
        else:
            check("event_source_links table", SKIP, "table absent")

        # ---- Layer 4: entities ----
        section("LAYER 4 — Entities")
        if _table_exists(session, "canonical_entities"):
            n_ent = scalar(session, f"SELECT count(*) FROM canonical_entities WHERE 1=1{country_filter}", **cp)
            check("canonical_entities present", PASS if n_ent else WARN, f"{n_ent:,}")
            ent_dims = session.execute(text("""
                SELECT DISTINCT array_length(embedding_vector,1) FROM canonical_entities
                WHERE embedding_vector IS NOT NULL""")).scalars().all()
            check("entity embeddings are 768-dim (not stale 384)", PASS if ent_dims in ([768], []) else FAIL, f"dims={ent_dims}")
            if _table_exists(session, "daily_entity_mentions"):
                e_orph = scalar(session, """
                    SELECT count(*) FROM daily_entity_mentions m
                    WHERE NOT EXISTS (SELECT 1 FROM canonical_entities e WHERE e.id=m.canonical_entity_id)""")
                check("no orphan daily_entity_mentions", PASS if e_orph == 0 else FAIL, f"{e_orph:,} dangling")
            if _table_exists(session, "raw_entities"):
                raw = scalar(session, "SELECT count(*) FROM raw_entities")
                check("raw_entities preserved", PASS if raw else WARN, f"{raw:,}")
            if _table_exists(session, "entity_relationships"):
                rel = scalar(session, "SELECT count(*) FROM entity_relationships")
                check("entity_relationships present", PASS if rel else WARN, f"{rel:,}")
        else:
            check("entity layer", SKIP, "canonical_entities table absent (entities not run)")

        # ---- Cross-cutting: batch jobs drained ----
        section("CROSS-CUTTING — batch jobs")
        if _table_exists(session, "batch_jobs"):
            rows = session.execute(text("SELECT status, count(*) FROM batch_jobs GROUP BY status ORDER BY status")).all()
            stuck = sum(c for s, c in rows if s in ("preparing", "submitted", "in_progress", "failed"))
            check("no stuck/failed batch jobs", PASS if stuck == 0 else WARN,
                  ", ".join(f"{s}={c}" for s, c in rows) or "none")
        else:
            check("batch_jobs table", SKIP, "absent")

        # ---- Summary ----
        section("SUMMARY")
        print(f"  PASS={_counts['PASS']}  FAIL={_counts['FAIL']}  WARN={_counts['WARN']}  SKIP={_counts['SKIP']}")
        if _counts["FAIL"]:
            print("\n  ❌ One or more FAIL checks — investigate before trusting the rebuild.")
            sys.exit(1)
        elif _counts["WARN"]:
            print("\n  ⚠️  No failures, but WARN items worth a look (often a stage you chose to skip).")
        else:
            print("\n  ✅ All checks passed.")


if __name__ == "__main__":
    main()
