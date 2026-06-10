"""Return canonical events ordered chronologically for a country/entity/date range.

Queries CanonicalEvent (shared/models/models.py::CanonicalEvent), master events
only (master_event_id IS NULL), overlapping the requested window. Recipients
live in the primary_recipients JSONB map (CanonicalEvent has no recipient
column); an optional canonical_entity_id filter restricts to that entity's
associated_events. Read-only.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_SQL = """
    SELECT id::text                AS event_id,
           canonical_name          AS event_name,
           initiating_country,
           first_mention_date,
           last_mention_date,
           story_phase,
           total_articles,
           source_count,
           primary_categories,
           primary_recipients,
           material_score,
           consolidated_description
    FROM canonical_events
    WHERE master_event_id IS NULL
      AND NOT (last_mention_date < :start_date OR first_mention_date > :end_date)
      AND COALESCE(material_score, 0) >= :min_materiality
      {influencer_clause}
      {recipient_clause}
      {entity_clause}
    ORDER BY first_mention_date ASC, total_articles DESC
    LIMIT :limit
"""


class EventTimelineTool(Tool):
    name = "event_timeline"
    description = (
        "Return canonical events within a date range, optionally scoped to an "
        "influencer, recipient, or canonical entity. Ordered chronologically."
    )
    foundation_dependency = "shared/models/models.py::CanonicalEvent"
    input_schema = {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
            "influencer": {"type": "string"},
            "recipient": {"type": "string"},
            "canonical_entity_id": {"type": "string"},
            "min_materiality": {"type": "number", "minimum": 0, "maximum": 10},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        },
        "required": ["start_date", "end_date"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        if not start_date or not end_date:
            return ToolResult(ok=False, error="start_date and end_date are required")
        limit = max(1, min(int(kwargs.get("limit") or 50), 200))

        try:
            from sqlalchemy import text
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "min_materiality": float(kwargs.get("min_materiality") or 0),
            "limit": limit,
        }
        influencer_clause = recipient_clause = entity_clause = ""
        if kwargs.get("influencer"):
            influencer_clause = "AND lower(initiating_country) = lower(:influencer)"
            params["influencer"] = kwargs["influencer"]
        if kwargs.get("recipient"):
            # primary_recipients is a JSONB object keyed by country name; match
            # keys case-insensitively to stay consistent with the influencer
            # filter ("egypt" should match "Egypt").
            recipient_clause = (
                "AND EXISTS (SELECT 1 FROM jsonb_object_keys(primary_recipients) rk "
                "WHERE lower(rk) = lower(:recipient))"
            )
            params["recipient"] = kwargs["recipient"]
        if kwargs.get("canonical_entity_id"):
            entity_clause = (
                "AND id::text IN ("
                "  SELECT unnest(associated_events) FROM canonical_entities"
                "  WHERE id::text = :entity_id)"
            )
            params["entity_id"] = kwargs["canonical_entity_id"]

        sql = _SQL.format(
            influencer_clause=influencer_clause,
            recipient_clause=recipient_clause,
            entity_clause=entity_clause,
        )

        try:
            with get_session() as session:
                rows = session.execute(text(sql), params).mappings().all()
        except Exception as e:
            logger.exception("event_timeline query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        events = [_shape(r) for r in rows]
        return ToolResult(
            ok=True,
            data={"events": events, "window": {"start": start_date, "end": end_date}},
            summary=f"event_timeline: {len(events)} event(s) {start_date}..{end_date}",
        )


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    desc = r.get("consolidated_description") or ""
    score = r.get("material_score")
    return {
        "event_id": r.get("event_id"),
        "event_name": r.get("event_name"),
        "initiating_country": r.get("initiating_country"),
        "first_mention_date": _d(r.get("first_mention_date")),
        "last_mention_date": _d(r.get("last_mention_date")),
        "story_phase": r.get("story_phase"),
        "total_articles": r.get("total_articles"),
        "source_count": r.get("source_count"),
        "categories": r.get("primary_categories") or {},
        "recipients": r.get("primary_recipients") or {},
        "material_score": float(score) if score is not None else None,
        "summary": desc if len(desc) <= 600 else desc[:600] + "…",
    }


def _d(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


TOOL = EventTimelineTool()
