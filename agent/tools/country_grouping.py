"""Group events by initiating/recipient country.

Country-level stand-in for a future geospatial tool. Given a candidate set of
canonical_event ids, returns counts and material_score aggregates grouped by
initiating country, recipient country, or initiator->recipient pair. Recipients
are read from the primary_recipients JSONB map on CanonicalEvent and aggregated
in Python. Read-only.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_SQL = """
    SELECT id::text           AS event_id,
           initiating_country,
           primary_recipients,
           material_score
    FROM canonical_events
    WHERE id::text = ANY(:event_ids)
"""


class CountryGroupingTool(Tool):
    name = "country_grouping"
    description = (
        "Group a candidate set of events by initiating and recipient country, "
        "with counts and materiality aggregates. Country-level stand-in for "
        "geospatial analysis."
    )
    foundation_dependency = "shared/models/models.py::CanonicalEvent"
    input_schema = {
        "type": "object",
        "properties": {
            "event_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "group_by": {
                "type": "string",
                "enum": ["initiator", "recipient", "pair"],
                "default": "pair",
            },
        },
        "required": ["event_ids"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        event_ids = kwargs.get("event_ids") or []
        if not event_ids:
            return ToolResult(ok=False, error="event_ids is required (non-empty)")
        group_by = kwargs.get("group_by") or "pair"
        if group_by not in {"initiator", "recipient", "pair"}:
            group_by = "pair"

        try:
            from sqlalchemy import bindparam, text
            from sqlalchemy.dialects.postgresql import ARRAY
            from sqlalchemy.types import String as SAString
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        stmt = text(_SQL).bindparams(bindparam("event_ids", type_=ARRAY(SAString)))
        try:
            with get_session() as session:
                rows = session.execute(stmt, {"event_ids": list(event_ids)}).mappings().all()
        except Exception as e:
            logger.exception("country_grouping query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        groups = _aggregate(rows, group_by)
        return ToolResult(
            ok=True,
            data={"group_by": group_by, "groups": groups, "event_count": len(rows)},
            summary=f"country_grouping[{group_by}]: {len(groups)} group(s) "
            f"over {len(rows)} event(s)",
        )


def _aggregate(rows: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    # key -> [event_count, summed_material_score, count_with_score]
    buckets: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    for r in rows:
        initiator = r.get("initiating_country") or "Unknown"
        score = r.get("material_score")
        score = float(score) if score is not None else None
        recipients = list((r.get("primary_recipients") or {}).keys()) or ["Unknown"]

        if group_by == "initiator":
            keys = [initiator]
        elif group_by == "recipient":
            keys = recipients
        else:  # pair
            keys = [f"{initiator} -> {rec}" for rec in recipients]

        for key in keys:
            b = buckets[key]
            b[0] += 1
            if score is not None:
                b[1] += score
                b[2] += 1

    groups = []
    for key, (count, score_sum, scored) in buckets.items():
        groups.append({
            "group": key,
            "event_count": int(count),
            "avg_material_score": round(score_sum / scored, 2) if scored else None,
        })
    groups.sort(key=lambda g: (g["event_count"], g["avg_material_score"] or 0), reverse=True)
    return groups


TOOL = CountryGroupingTool()
