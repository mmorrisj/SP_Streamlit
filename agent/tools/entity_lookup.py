"""Resolve a name or alias to a canonical entity profile.

TODO: Query CanonicalEntity (shared/models/models.py:1180) by name/aliases,
return profile (entity_type, country affiliations, embedding-based nearest neighbors).
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


class EntityLookupTool(Tool):
    name = "entity_lookup"
    description = (
        "Resolve a name or alias to a canonical entity record. Returns the "
        "canonical_id, entity_type, country affiliations, and aliases."
    )
    foundation_dependency = "shared/models/models.py::CanonicalEntity"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "entity_type": {
                "type": "string",
                "enum": ["person", "organization", "location", "media_figure", "other"],
            },
        },
        "required": ["name"],
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="entity_lookup stub")


TOOL = EntityLookupTool()
