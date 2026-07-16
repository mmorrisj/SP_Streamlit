"""Offer the full validated report pipeline for a scope.

This tool performs no work — it validates and echoes a report scope. The
conversational orchestrator turns a successful call into a `report_offer`
event, which the UI renders as an explicit "Run full report" action. The
pipeline itself (12 validated stages, ~minutes) only runs when the analyst
clicks — never as a side effect of conversation.
"""
from __future__ import annotations

import re
from typing import Any

from agent.tools.base import Tool, ToolResult

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ProposeReportTool(Tool):
    name = "propose_report"
    description = (
        "Offer the analyst the full validated report pipeline (12 stages: "
        "retrieval, event narration, sourcing, QA, hallucination validation) "
        "for a specific scope. Call this when the question is really a "
        "report-sized request (a full brief on a relationship or region over "
        "a period) or when the analyst asks for a report. It does NOT run the "
        "pipeline — the analyst confirms with a click. Continue answering "
        "conversationally alongside the offer."
    )
    foundation_dependency = "agent/workflows/report"
    input_schema = {
        "type": "object",
        "properties": {
            "influencer": {"type": "string", "description": "initiating country (required)"},
            "recipient": {"type": "string", "description": "recipient country (bilateral)"},
            "region": {"type": "string", "description": "region name (regional; e.g. Middle East)"},
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "category": {
                "type": "string",
                "enum": ["Economic", "Diplomacy", "Social", "Military"],
            },
            "reason": {"type": "string", "description": "one sentence: why the full pipeline fits"},
        },
        "required": ["influencer", "start_date", "end_date"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        influencer = (kwargs.get("influencer") or "").strip()
        recipient = (kwargs.get("recipient") or "").strip() or None
        region = (kwargs.get("region") or "").strip() or None
        start = (kwargs.get("start_date") or "").strip()
        end = (kwargs.get("end_date") or "").strip()
        category = kwargs.get("category")

        if not influencer:
            return ToolResult(ok=False, error="influencer is required")
        if not recipient and not region:
            return ToolResult(ok=False, error="supply recipient (bilateral) or region (regional)")
        if not (_DATE_RE.match(start) and _DATE_RE.match(end)):
            return ToolResult(ok=False, error="start_date and end_date must be YYYY-MM-DD")

        scope = {
            "influencer": influencer,
            "recipient": recipient,
            "region": region,
            "start_date": start,
            "end_date": end,
            "category": category,
            "category_mode": "filter" if category else "flat",
            "reason": kwargs.get("reason"),
        }
        target = recipient or region
        return ToolResult(
            ok=True,
            data=scope,
            summary=f"report offer: {influencer} → {target}, {start}..{end}"
                    + (f" [{category}]" if category else ""),
        )


TOOL = ProposeReportTool()
