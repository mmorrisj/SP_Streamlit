"""Hydrate a list of doc_ids into formatted citations.

TODO: Wrap shared/utils/citation_utils.py to return source_name, ATOM ID,
title, date, and a clickable URL for each doc_id.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


class CitationResolverTool(Tool):
    name = "citation_resolver"
    description = "Hydrate a list of doc_ids into formatted citations with source metadata."
    foundation_dependency = "shared/utils/citation_utils.py"
    input_schema = {
        "type": "object",
        "properties": {
            "doc_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["doc_ids"],
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="citation_resolver stub")


TOOL = CitationResolverTool()
