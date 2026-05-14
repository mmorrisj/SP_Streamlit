"""Group events by initiating/recipient country.

TODO: Country-level stand-in for a future geospatial tool. Returns counts
and materiality aggregates per country. Add lat/lon support when the
document/event schema gains coordinates.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


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
            "event_ids": {"type": "array", "items": {"type": "string"}},
            "group_by": {
                "type": "string",
                "enum": ["initiator", "recipient", "pair"],
                "default": "pair",
            },
        },
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="country_grouping stub")


TOOL = CountryGroupingTool()
