"""Provenance-corrected volume statistics for an initiator (-> recipient).

THE bias-control tool: splits media volume into self-reported (the
initiator's own media ecosystem, via source_geofocus) vs third-party
coverage. Prefers the precomputed analytics.provenance_intensity table;
falls back to computing directly from the raw tables when the analytics
schema is not built.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools._analytics import analytics_table_exists, validate_recipient
from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class ProvenanceStatsTool(Tool):
    name = "provenance_stats"
    description = (
        "Bias control: split media volume for an initiating country (optionally "
        "toward one recipient) into self-reported (initiator's own media) vs "
        "third-party coverage, with per-category breakdown. Use this before "
        "quoting any raw volume number — raw counts measure media attention, "
        "not activity, and the corpus over-indexes on Iranian state media."
    )
    foundation_dependency = "analytics.provenance_intensity | documents"
    input_schema = {
        "type": "object",
        "properties": {
            "initiating_country": {
                "type": "string",
                "description": "China | Iran | Russia | Turkey (United States has no self-report signal)",
            },
            "recipient_country": {"type": "string", "description": "optional recipient filter"},
            "start_date": {"type": "string", "description": "YYYY-MM-DD (optional)"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD (optional)"},
        },
        "required": ["initiating_country"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        initiator = (kwargs.get("initiating_country") or "").strip()
        recipient, recip_err = validate_recipient(kwargs.get("recipient_country"))
        if recip_err:
            return ToolResult(ok=False, error=recip_err)
        start = kwargs.get("start_date")
        end = kwargs.get("end_date")
        if not initiator:
            return ToolResult(ok=False, error="initiating_country is required")

        try:
            from sqlalchemy import text
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        use_analytics = analytics_table_exists("provenance_intensity")
        try:
            with get_session() as session:
                if use_analytics:
                    rows = session.execute(text("""
                        SELECT pi.category,
                               sum(pi.raw_docs)            AS raw_docs,
                               sum(pi.self_reported_docs)  AS self_docs,
                               sum(pi.third_party_docs)    AS third_docs
                        FROM analytics.provenance_intensity pi
                        LEFT JOIN analytics.recipient_alias ra
                               ON ra.alias = pi.recipient_country
                        WHERE pi.initiating_country = :init
                          AND (:recip IS NULL
                               OR coalesce(ra.canonical, pi.recipient_country) = :recip)
                          AND (:start IS NULL OR pi.month >= CAST(:start AS date))
                          AND (:end   IS NULL OR pi.month <= CAST(:end AS date))
                        GROUP BY 1 ORDER BY 2 DESC
                    """), {"init": initiator, "recip": recipient,
                           "start": start, "end": end}).mappings().all()
                else:
                    rows = session.execute(text("""
                        SELECT c.category,
                               count(DISTINCT d.doc_id) AS raw_docs,
                               count(DISTINCT d.doc_id) FILTER
                                 (WHERE d.source_geofocus ILIKE '%' || :init || '%') AS self_docs,
                               count(DISTINCT d.doc_id) FILTER
                                 (WHERE d.source_geofocus IS NULL
                                    OR d.source_geofocus NOT ILIKE '%' || :init || '%') AS third_docs
                        FROM documents d
                        JOIN initiating_countries ic ON ic.doc_id = d.doc_id
                        JOIN recipient_countries  rc ON rc.doc_id = d.doc_id
                        JOIN categories           c  ON c.doc_id = d.doc_id
                        WHERE ic.initiating_country = :init
                          AND ic.initiating_country <> rc.recipient_country
                          AND (:recip IS NULL OR rc.recipient_country IN (:recip, :recip_alt))
                          AND (:start IS NULL OR d.date >= CAST(:start AS date))
                          AND (:end   IS NULL OR d.date <= CAST(:end AS date))
                          AND c.category IN ('Economic','Social','Military','Diplomacy')
                        GROUP BY 1 ORDER BY 2 DESC
                    """), {"init": initiator, "recip": recipient,
                           "recip_alt": "UAE" if recipient == "United Arab Emirates" else recipient,
                           "start": start, "end": end}).mappings().all()
        except Exception as e:
            logger.exception("provenance_stats query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        by_category = [
            {
                "category": r["category"],
                "raw_docs": int(r["raw_docs"] or 0),
                "self_reported_docs": int(r["self_docs"] or 0),
                "third_party_docs": int(r["third_docs"] or 0),
            }
            for r in rows
        ]
        raw = sum(r["raw_docs"] for r in by_category)
        self_docs = sum(r["self_reported_docs"] for r in by_category)
        third = sum(r["third_party_docs"] for r in by_category)

        caveat = (
            "self_report_share is a valid narrative-projection signal only for Iran "
            "(and weakly China); Russia/Turkey have no domestic outlets in the corpus, "
            "so for them third_party_docs is simply the intensity measure."
        )
        data = {
            "initiating_country": initiator,
            "recipient_country": recipient,
            "window": {"start": start, "end": end},
            "raw_docs": raw,
            "self_reported_docs": self_docs,
            "third_party_docs": third,
            "self_report_share": round(self_docs / raw, 3) if raw else None,
            "by_category": by_category,
            "basis": "analytics.provenance_intensity" if use_analytics
                     else "computed from raw tables (analytics schema not built)",
            "caveat": caveat,
        }
        target = f"{initiator}→{recipient}" if recipient else initiator
        return ToolResult(
            ok=True,
            data=data,
            summary=(
                f"provenance_stats {target}: raw={raw:,} third-party={third:,} "
                f"({(self_docs / raw * 100):.0f}% self-reported)" if raw else
                f"provenance_stats {target}: no documents in scope"
            ),
        )


TOOL = ProvenanceStatsTool()
