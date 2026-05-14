"""Synthesize gathered evidence into a structured analyst briefing.

TODO: Compose the Briefing schema (agent/schemas.py) from the orchestrator's
accumulated context — workflow results, evidence, entities, timeline.
LLM-driven; uses the provider configured in agent/llm/provider.py.

Output sections must include: Title, Executive Summary, Key Judgments,
Timeline, Key Entities, Evidence, Confidence Assessment, Information Gaps,
Recommended Analyst Follow-up.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


class BriefingGeneratorTool(Tool):
    name = "briefing_generator"
    description = (
        "Synthesize gathered evidence, entities, and timeline into a structured "
        "analyst briefing with key judgments, confidence, gaps, and follow-ups."
    )
    foundation_dependency = "server/report_generator.py (composition patterns)"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "object"}},
            "entities": {"type": "array", "items": {"type": "object"}},
            "timeline": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["query"],
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="briefing_generator stub")


TOOL = BriefingGeneratorTool()
