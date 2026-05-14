"""Filter and rank a candidate set by materiality_score.

TODO: Accept a list of event_ids or doc_ids, return them ranked/filtered
by the materiality_score field on EventSummary / CanonicalEvent.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


class MaterialityFilterTool(Tool):
    name = "materiality_filter"
    description = (
        "Filter and rank a candidate set of events or documents by materiality "
        "score. Used to focus on high-signal items."
    )
    foundation_dependency = "shared/models/models.py::EventSummary.materiality_score"
    input_schema = {
        "type": "object",
        "properties": {
            "event_ids": {"type": "array", "items": {"type": "string"}},
            "min_score": {"type": "number", "minimum": 0, "maximum": 10, "default": 5},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="materiality_filter stub")


TOOL = MaterialityFilterTool()
