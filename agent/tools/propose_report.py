"""Offer the full validated report pipeline for a scope.

This tool performs no work — it validates and echoes a report scope. The
conversational orchestrator turns a successful call into a `report_offer`
event, which the UI renders as an explicit "Run full report" action. The
pipeline itself (12 validated stages, ~minutes) only runs when the analyst
clicks — never as a side effect of conversation.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent.tools.base import Tool, ToolResult

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "shared" / "config" / "config.yaml"


@lru_cache(maxsize=1)
def _tracked_influencers() -> tuple[str, ...]:
    """Initiators the event pipeline actually builds events for.

    Extraction records ANY initiating country on documents, but events are
    only clustered/consolidated for the configured influencers — a report
    scoped to any other initiator finds documents but zero events and fails
    validation downstream.
    """
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return tuple(str(c) for c in (cfg.get("influencers") or []))
    except FileNotFoundError:
        return ()


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
            "influencer": {"type": "string", "description": "initiating country (required; must be a tracked initiator — China, Iran, Russia, Turkey, or United States)"},
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
        tracked = _tracked_influencers()
        if tracked and influencer not in tracked:
            return ToolResult(
                ok=False,
                error=(
                    f"'{influencer}' is not a tracked initiator. The event pipeline only "
                    f"builds events for: {', '.join(tracked)}. A report scoped to "
                    f"'{influencer} →' would retrieve documents but zero events, so every "
                    "narrative stage would come back empty and validation would fail — no "
                    "date range fixes this. If the question is about activity TOWARD "
                    f"{influencer}, reframe recipient-side: offer a bilateral report "
                    f"(<tracked influencer> → {influencer}) or answer conversationally "
                    "using provenance_stats / initiative_ledger / document_search with "
                    f"{influencer} as the recipient."
                ),
            )
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
