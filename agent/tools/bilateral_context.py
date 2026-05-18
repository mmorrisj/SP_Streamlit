"""Return pre-computed bilateral relationship summary + metrics for an influencer-recipient pair.

TODO: Query BilateralRelationshipSummary (shared/models/models.py) and
related metrics. Read-only.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


class BilateralContextTool(Tool):
    name = "bilateral_context"
    description = (
        "Return the pre-computed bilateral relationship summary and key metrics "
        "for an influencer-recipient country pair."
    )
    foundation_dependency = "shared/models/models.py::BilateralRelationshipSummary"
    input_schema = {
        "type": "object",
        "properties": {
            "influencer": {"type": "string"},
            "recipient": {"type": "string"},
        },
        "required": ["influencer", "recipient"],
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="bilateral_context stub")


TOOL = BilateralContextTool()
