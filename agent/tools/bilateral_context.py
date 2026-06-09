"""Return pre-computed bilateral relationship summary + metrics for an influencer-recipient pair.

Queries BilateralRelationshipSummary (shared/models/models.py:747). The
AI-generated narrative lives in the relationship_summary JSONB (overview,
key_themes, major_initiatives, trend_analysis, current_status,
notable_developments, material_assessment). When more than one summary exists
for a pair the most recently generated one is returned. Read-only.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_SQL = """
    SELECT initiating_country,
           recipient_country,
           first_interaction_date,
           last_interaction_date,
           analysis_generated_at,
           total_documents,
           total_daily_events,
           count_by_category,
           count_by_source,
           activity_by_month,
           relationship_summary,
           material_score_avg,
           material_score_median
    FROM bilateral_relationship_summaries
    WHERE lower(initiating_country) = lower(:influencer)
      AND lower(recipient_country) = lower(:recipient)
    ORDER BY analysis_generated_at DESC NULLS LAST
    LIMIT 1
"""


def _top_n(d: dict[str, Any] | None, n: int = 8) -> dict[str, Any]:
    if not d:
        return {}
    items = sorted(d.items(), key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 0,
                   reverse=True)
    return dict(items[:n])


class BilateralContextTool(Tool):
    name = "bilateral_context"
    description = (
        "Return the pre-computed bilateral relationship summary and key metrics "
        "for an influencer-recipient country pair."
    )
    foundation_dependency = "shared/models/models.py::BilateralRelationshipSummary"
    input_schema = {
        "type": "object",
        "properties": {
            "influencer": {"type": "string"},
            "recipient": {"type": "string"},
        },
        "required": ["influencer", "recipient"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        influencer = (kwargs.get("influencer") or "").strip()
        recipient = (kwargs.get("recipient") or "").strip()
        if not influencer or not recipient:
            return ToolResult(ok=False, error="influencer and recipient are required")

        try:
            from sqlalchemy import text
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        try:
            with get_session() as session:
                row = session.execute(
                    text(_SQL), {"influencer": influencer, "recipient": recipient}
                ).mappings().first()
        except Exception as e:
            logger.exception("bilateral_context query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        if row is None:
            return ToolResult(
                ok=True, data={"found": False},
                summary=f"bilateral_context: no summary for {influencer} -> {recipient}",
            )

        score = row.get("material_score_avg")
        data = {
            "found": True,
            "influencer": row.get("initiating_country"),
            "recipient": row.get("recipient_country"),
            "first_interaction_date": _d(row.get("first_interaction_date")),
            "last_interaction_date": _d(row.get("last_interaction_date")),
            "analysis_generated_at": _d(row.get("analysis_generated_at")),
            "total_documents": row.get("total_documents"),
            "total_daily_events": row.get("total_daily_events"),
            "count_by_category": row.get("count_by_category") or {},
            "top_sources": _top_n(row.get("count_by_source")),
            "activity_by_month": row.get("activity_by_month") or {},
            "summary": row.get("relationship_summary") or {},
            "material_score_avg": float(score) if score is not None else None,
            "material_score_median": _maybe_float(row.get("material_score_median")),
        }
        return ToolResult(
            ok=True,
            data=data,
            summary=f"bilateral_context: {influencer} -> {recipient}, "
            f"{row.get('total_documents')} docs",
        )


def _maybe_float(v: Any) -> float | None:
    return float(v) if v is not None else None


def _d(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


TOOL = BilateralContextTool()
