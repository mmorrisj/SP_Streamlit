"""Filter and rank a candidate set of canonical events by materiality band or score.

Takes a list of canonical_event ids (typically from event_timeline or
document_search) and returns them filtered by materiality band (symbolic /
developing / substantive) or explicit score bounds, ranked appropriately.
The score column is `material_score` on CanonicalEvent
(shared/models/models.py:628), Numeric(3,1). Read-only.

No default score floor: symbolic activity (visits, statements, ceremonies) is
a real soft-power signal — narrative projection — and must be reachable, not
silently filtered out. Callers opt into a band or bound explicitly.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult
from shared.utils.materiality_bands import band_bounds, band_for

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
      AND (:min_score IS NULL OR material_score >= :min_score)
      AND (:max_score IS NULL OR material_score < :max_score)
    ORDER BY {order}
    LIMIT :limit
"""

# Within the symbolic band, score can't rank events — coverage volume and
# recency stand in as the importance measure.
_ORDER_BY_SCORE = "material_score DESC NULLS LAST, total_articles DESC"
_ORDER_BY_VOLUME = "total_articles DESC NULLS LAST, last_mention_date DESC"


class MaterialityFilterTool(Tool):
    name = "materiality_filter"
    description = (
        "Filter and rank a candidate set of events by materiality band: "
        "'substantive' (7+: funded projects, signed deals), 'developing' "
        "(4-7: MOUs, pilots, training), or 'symbolic' (<4: visits, "
        "statements, ceremonies — narrative-projection signals, ranked by "
        "coverage volume). Omit band and bounds to rank ALL candidates by "
        "score without dropping any. Explicit min_score/max_score bounds are "
        "also accepted."
    )
    foundation_dependency = "shared/models/models.py::CanonicalEvent.material_score"
    input_schema = {
        "type": "object",
        "properties": {
            "event_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "band": {"type": "string", "enum": ["symbolic", "developing", "substantive"]},
            "min_score": {"type": "number", "minimum": 0, "maximum": 10},
            "max_score": {"type": "number", "minimum": 0, "maximum": 10,
                          "description": "exclusive upper bound"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "required": ["event_ids"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        event_ids = kwargs.get("event_ids") or []
        if not event_ids:
            return ToolResult(ok=False, error="event_ids is required (non-empty)")

        band = kwargs.get("band")
        min_score = kwargs.get("min_score")
        max_score = kwargs.get("max_score")
        if band:
            try:
                band_min, band_max = band_bounds(band)
            except ValueError as e:
                return ToolResult(ok=False, error=str(e))
            min_score = band_min if min_score is None else min_score
            max_score = band_max if max_score is None else max_score

        top_k = int(kwargs.get("top_k") or len(event_ids))
        top_k = max(1, min(top_k, 100))
        order = _ORDER_BY_VOLUME if band == "symbolic" else _ORDER_BY_SCORE

        try:
            from sqlalchemy import bindparam, text
            from sqlalchemy.dialects.postgresql import ARRAY
            from sqlalchemy.types import String as SAString
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        stmt = text(_SQL.format(order=order)).bindparams(
            bindparam("event_ids", type_=ARRAY(SAString))
        )
        params = {
            "event_ids": list(event_ids),
            "min_score": float(min_score) if min_score is not None else None,
            "max_score": float(max_score) if max_score is not None else None,
            "limit": top_k,
        }

        try:
            with get_session() as session:
                rows = session.execute(stmt, params).mappings().all()
        except Exception as e:
            logger.exception("materiality_filter query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        kept = [_shape(r) for r in rows]
        scope_desc = (
            f"band={band}" if band
            else f"score in [{min_score if min_score is not None else '-'}, "
                 f"{max_score if max_score is not None else '-'})"
            if (min_score is not None or max_score is not None)
            else "all bands"
        )
        return ToolResult(
            ok=True,
            data={
                "events": kept,
                "input_count": len(event_ids),
                "band": band,
                "min_score": min_score,
                "max_score": max_score,
            },
            summary=f"materiality_filter: {len(kept)}/{len(event_ids)} kept ({scope_desc})",
        )


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    score = r.get("material_score")
    score_f = float(score) if score is not None else None
    return {
        "event_id": r.get("event_id"),
        "event_name": r.get("event_name"),
        "initiating_country": r.get("initiating_country"),
        "material_score": score_f,
        "materiality_band": band_for(score_f),
        "material_justification": r.get("material_justification"),
        "total_articles": r.get("total_articles"),
        "first_mention_date": _d(r.get("first_mention_date")),
        "last_mention_date": _d(r.get("last_mention_date")),
    }


def _d(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


TOOL = MaterialityFilterTool()
