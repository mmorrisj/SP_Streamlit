"""Return canonical events ordered chronologically for a country/entity/date range.

TODO: Wrap /api/events/timeline logic (server/main.py:3230) and CanonicalEvent.
Read-only.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


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
        },
        "required": ["start_date", "end_date"],
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="event_timeline stub")


TOOL = EventTimelineTool()
