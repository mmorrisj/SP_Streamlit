"""Monthly activity tempo for a relationship, with detected changepoints.

Returns the raw and third-party-corroborated monthly document series for an
initiator (optionally -> recipient), plus statistically detected changepoints
(binary segmentation, |z| >= 2.5) when analytics.relationship_changepoints is
available. This replaces eyeballed trend claims with measured inflections.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools._analytics import analytics_table_exists, validate_recipient
from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class ActivitySeriesTool(Tool):
    name = "activity_series"
    description = (
        "Monthly activity tempo (raw and third-party-corroborated document "
        "counts) for an initiating country, optionally toward one recipient, "
        "plus statistically detected changepoints (surges/declines) when "
        "available. Use for trend/trajectory questions instead of guessing "
        "from totals."
    )
    foundation_dependency = "analytics.provenance_intensity | documents"
    input_schema = {
        "type": "object",
        "properties": {
            "initiating_country": {"type": "string"},
            "recipient_country": {"type": "string"},
            "category": {
                "type": "string",
                "enum": ["Economic", "Social", "Military", "Diplomacy"],
            },
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
        category = kwargs.get("category")
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
        params = {"init": initiator, "recip": recipient, "cat": category,
                  "start": start, "end": end}
        try:
            with get_session() as session:
                if use_analytics:
                    rows = session.execute(text("""
                        SELECT pi.month,
                               sum(pi.raw_docs)         AS raw_docs,
                               sum(pi.third_party_docs) AS third_docs
                        FROM analytics.provenance_intensity pi
                        LEFT JOIN analytics.recipient_alias ra
                               ON ra.alias = pi.recipient_country
                        WHERE pi.initiating_country = :init
                          AND (:recip IS NULL
                               OR coalesce(ra.canonical, pi.recipient_country) = :recip)
                          AND (:cat IS NULL OR pi.category = :cat)
                          AND (:start IS NULL OR pi.month >= CAST(:start AS date))
                          AND (:end   IS NULL OR pi.month <= CAST(:end AS date))
                        GROUP BY 1 ORDER BY 1
                    """), params).mappings().all()
                    basis = "analytics.provenance_intensity"
                else:
                    rows = session.execute(text("""
                        SELECT date_trunc('month', d.date)::date AS month,
                               count(DISTINCT d.doc_id) AS raw_docs,
                               count(DISTINCT d.doc_id) FILTER
                                 (WHERE d.source_geofocus IS NULL
                                    OR d.source_geofocus NOT ILIKE '%' || :init || '%') AS third_docs
                        FROM documents d
                        JOIN initiating_countries ic ON ic.doc_id = d.doc_id
                        JOIN recipient_countries  rc ON rc.doc_id = d.doc_id
                        LEFT JOIN categories      c  ON c.doc_id = d.doc_id
                        WHERE ic.initiating_country = :init
                          AND ic.initiating_country <> rc.recipient_country
                          AND (:recip IS NULL OR rc.recipient_country IN (:recip, :recip_alt))
                          AND (:cat IS NULL OR c.category = :cat)
                          AND (:start IS NULL OR d.date >= CAST(:start AS date))
                          AND (:end   IS NULL OR d.date <= CAST(:end AS date))
                        GROUP BY 1 ORDER BY 1
                    """), {**params,
                           "recip_alt": "UAE" if recipient == "United Arab Emirates" else recipient,
                           }).mappings().all()
                    basis = "computed from raw tables (analytics schema not built)"

                changepoints: list[dict[str, Any]] = []
                if recipient and analytics_table_exists("relationship_changepoints"):
                    cps = session.execute(text("""
                        SELECT cp_month, direction, pre_mean, post_mean, z_score
                        FROM analytics.relationship_changepoints
                        WHERE initiating_country = :init AND recipient = :recip
                          AND metric = 'third_party_docs'
                        ORDER BY z_score DESC
                    """), {"init": initiator, "recip": recipient}).mappings().all()
                    changepoints = [
                        {
                            "month": str(c["cp_month"]),
                            "direction": c["direction"],
                            "pre_mean": float(c["pre_mean"]),
                            "post_mean": float(c["post_mean"]),
                            "z_score": float(c["z_score"]),
                        }
                        for c in cps
                    ]
        except Exception as e:
            logger.exception("activity_series query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        series = [
            {
                "month": str(r["month"]),
                "raw_docs": int(r["raw_docs"] or 0),
                "third_party_docs": int(r["third_docs"] or 0),
            }
            for r in rows
        ]
        target = f"{initiator}→{recipient}" if recipient else initiator
        if category:
            target += f" [{category}]"
        return ToolResult(
            ok=True,
            data={
                "target": target,
                "series": series,
                "changepoints": changepoints,
                "basis": basis,
                "note": "third_party_docs is the trustworthy intensity signal; "
                        "raw_docs includes the initiator's own media.",
            },
            summary=(
                f"activity_series {target}: {len(series)} months, "
                f"{len(changepoints)} changepoints"
            ),
        )


TOOL = ActivitySeriesTool()
