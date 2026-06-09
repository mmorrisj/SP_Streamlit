"""Filter and rank a candidate set of canonical events by material_score.

Takes a list of canonical_event ids (typically from event_timeline or
document_search) and returns them filtered to material_score >= min_score,
ranked highest-first. The score column is `material_score` on CanonicalEvent
(shared/models/models.py:628), Numeric(3,1). Read-only.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_SQL = """
    SELECT id::text           AS event_id,
           canonical_name     AS event_name,
           initiating_country,
           material_score,
           material_justification,
           total_articles,
           first_mention_date,
           last_mention_date
    FROM canonical_events
    WHERE id::text = ANY(:event_ids)
      AND COALESCE(material_score, 0) >= :min_score
    ORDER BY material_score DESC NULLS LAST, total_articles DESC
    LIMIT :limit
"""


class MaterialityFilterTool(Tool):
    name = "materiality_filter"
    description = (
        "Filter and rank a candidate set of events by materiality "
        "score. Used to focus on high-signal items."
    )
    foundation_dependency = "shared/models/models.py::CanonicalEvent.material_score"
    input_schema = {
        "type": "object",
        "properties": {
            "event_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "min_score": {"type": "number", "minimum": 0, "maximum": 10, "default": 5},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "required": ["event_ids"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        event_ids = kwargs.get("event_ids") or []
        if not event_ids:
            return ToolResult(ok=False, error="event_ids is required (non-empty)")
        min_score = float(kwargs.get("min_score") if kwargs.get("min_score") is not None else 5)
        top_k = int(kwargs.get("top_k") or len(event_ids))
        top_k = max(1, min(top_k, 100))

        try:
            from sqlalchemy import bindparam, text
            from sqlalchemy.dialects.postgresql import ARRAY
            from sqlalchemy.types import String as SAString
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        stmt = text(_SQL).bindparams(bindparam("event_ids", type_=ARRAY(SAString)))
        params = {"event_ids": list(event_ids), "min_score": min_score, "limit": top_k}

        try:
            with get_session() as session:
                rows = session.execute(stmt, params).mappings().all()
        except Exception as e:
            logger.exception("materiality_filter query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        kept = [_shape(r) for r in rows]
        return ToolResult(
            ok=True,
            data={"events": kept, "input_count": len(event_ids), "min_score": min_score},
            summary=f"materiality_filter: {len(kept)}/{len(event_ids)} kept "
            f"(material_score >= {min_score})",
        )


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    score = r.get("material_score")
    return {
        "event_id": r.get("event_id"),
        "event_name": r.get("event_name"),
        "initiating_country": r.get("initiating_country"),
        "material_score": float(score) if score is not None else None,
        "material_justification": r.get("material_justification"),
        "total_articles": r.get("total_articles"),
        "first_mention_date": _d(r.get("first_mention_date")),
        "last_mention_date": _d(r.get("last_mention_date")),
    }


def _d(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


TOOL = MaterialityFilterTool()
