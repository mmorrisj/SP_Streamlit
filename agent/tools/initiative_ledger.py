"""Corroboration-gated named initiatives — the honest unit of analysis.

Returns canonical events (named initiatives) for a scope, preferring the
analytics.initiative_ledger view which carries per-event provenance
(corroboration_share, distinct_sources). The doctrine gate is
corroboration_share >= 0.5 AND distinct_sources >= 3; article counts measure
attention, gated initiatives measure independently attested activity.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools._analytics import analytics_table_exists, validate_recipient
from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class InitiativeLedgerTool(Tool):
    name = "initiative_ledger"
    description = (
        "List named initiatives (canonical events) for an initiator and/or "
        "recipient, ranked by materiality. By default applies the corroboration "
        "gate (>=50% third-party coverage from >=3 independent outlets) — the "
        "platform's honest unit of analysis. Set apply_gate=false to see the "
        "raw, ungated event list for contrast."
    )
    foundation_dependency = "analytics.initiative_ledger | canonical_events"
    input_schema = {
        "type": "object",
        "properties": {
            "initiating_country": {"type": "string"},
            "recipient_country": {"type": "string"},
            "start_date": {"type": "string", "description": "first_mention_date >= (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "first_mention_date <= (YYYY-MM-DD)"},
            "min_material_score": {"type": "number", "minimum": 1, "maximum": 10},
            "apply_gate": {"type": "boolean", "default": True},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
        },
    }

    def run(self, **kwargs: Any) -> ToolResult:
        initiator = (kwargs.get("initiating_country") or "").strip() or None
        recipient, recip_err = validate_recipient(kwargs.get("recipient_country"))
        if recip_err:
            return ToolResult(ok=False, error=recip_err)
        start = kwargs.get("start_date")
        end = kwargs.get("end_date")
        min_score = kwargs.get("min_material_score")
        apply_gate = kwargs.get("apply_gate", True)
        limit = max(1, min(int(kwargs.get("limit") or 15), 50))
        if not initiator and not recipient:
            return ToolResult(ok=False, error="supply initiating_country and/or recipient_country")

        try:
            from sqlalchemy import text
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        use_analytics = analytics_table_exists("initiative_ledger")
        params = {
            "init": initiator, "recip": recipient, "start": start, "end": end,
            "min_score": min_score, "limit": limit,
        }
        try:
            with get_session() as session:
                if use_analytics:
                    gate_sql = (
                        "AND il.corroboration_share >= 0.5 AND il.distinct_sources >= 3"
                        if apply_gate else ""
                    )
                    rows = session.execute(text(f"""
                        SELECT il.event_id::text AS event_id, il.canonical_name,
                               il.initiating_country, il.mena_recipients,
                               il.first_mention_date, il.last_mention_date,
                               il.material_score, il.linked_docs, il.distinct_sources,
                               il.third_docs, il.corroboration_share
                        FROM analytics.initiative_ledger il
                        WHERE (:init  IS NULL OR il.initiating_country = :init)
                          AND (:recip IS NULL OR :recip = ANY(il.mena_recipients))
                          AND (:start IS NULL OR il.first_mention_date >= CAST(:start AS date))
                          AND (:end   IS NULL OR il.first_mention_date <= CAST(:end AS date))
                          AND (:min_score IS NULL OR il.material_score >= :min_score)
                          {gate_sql}
                        ORDER BY il.material_score DESC NULLS LAST, il.distinct_sources DESC
                        LIMIT :limit
                    """), params).mappings().all()
                    basis = "analytics.initiative_ledger (per-event provenance)"
                else:
                    rows = session.execute(text("""
                        SELECT ce.id::text AS event_id, ce.canonical_name,
                               ce.initiating_country, NULL AS mena_recipients,
                               ce.first_mention_date, ce.last_mention_date,
                               ce.material_score, ce.total_articles AS linked_docs,
                               ce.source_count AS distinct_sources,
                               NULL AS third_docs, NULL AS corroboration_share
                        FROM canonical_events ce
                        WHERE (:init IS NULL OR ce.initiating_country = :init)
                          AND (:recip IS NULL OR ce.primary_recipients ? :recip)
                          AND (:start IS NULL OR ce.first_mention_date >= CAST(:start AS date))
                          AND (:end   IS NULL OR ce.first_mention_date <= CAST(:end AS date))
                          AND (:min_score IS NULL OR ce.material_score >= :min_score)
                        ORDER BY ce.material_score DESC NULLS LAST, ce.source_count DESC NULLS LAST
                        LIMIT :limit
                    """), params).mappings().all()
                    basis = ("canonical_events (analytics schema not built — corroboration "
                             "gate UNAVAILABLE; treat volumes as attention, not attested activity)")
                    apply_gate = False
        except Exception as e:
            logger.exception("initiative_ledger query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        initiatives = []
        for r in rows:
            initiatives.append({
                "event_id": r["event_id"],
                "name": r["canonical_name"],
                "initiating_country": r["initiating_country"],
                "recipients": list(r["mena_recipients"] or []) or None,
                "first_mention": str(r["first_mention_date"]) if r["first_mention_date"] else None,
                "last_mention": str(r["last_mention_date"]) if r["last_mention_date"] else None,
                "material_score": float(r["material_score"]) if r["material_score"] is not None else None,
                "linked_docs": int(r["linked_docs"] or 0),
                "distinct_sources": int(r["distinct_sources"] or 0),
                "corroboration_share": (
                    float(r["corroboration_share"])
                    if r["corroboration_share"] is not None else None
                ),
            })

        scope = " ".join(filter(None, [initiator, f"→{recipient}" if recipient else None]))
        return ToolResult(
            ok=True,
            data={
                "initiatives": initiatives,
                "gate_applied": bool(apply_gate),
                "basis": basis,
            },
            citations=[i["event_id"] for i in initiatives],
            summary=(
                f"initiative_ledger {scope or 'all'}: {len(initiatives)} initiatives"
                f"{' (corroboration-gated)' if apply_gate else ' (UNGATED)'}"
            ),
        )


TOOL = InitiativeLedgerTool()
