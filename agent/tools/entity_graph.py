"""Return N-hop neighbors and relationships for an entity.

TODO: Query EntityRelationship (shared/models/models.py:1343). Default to 1-hop
neighbors; support directed traversal and co-occurrence thresholding.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


class EntityGraphTool(Tool):
    name = "entity_graph"
    description = (
        "Return related entities and relationships for a canonical entity. "
        "Supports N-hop traversal and co-occurrence filtering."
    )
    foundation_dependency = "shared/models/models.py::EntityRelationship"
    input_schema = {
        "type": "object",
        "properties": {
            "canonical_id": {"type": "string"},
            "hops": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
            "min_cooccurrences": {"type": "integer", "minimum": 1, "default": 2},
            "relationship_types": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["canonical_id"],
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="entity_graph stub")


TOOL = EntityGraphTool()
