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
def _load_country_config() -> dict:
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _tracked_influencers() -> tuple[str, ...]:
    """Initiators the event pipeline actually builds events for.

    Extraction records ANY initiating country on documents, but events are
    only clustered/consolidated for the configured influencers — a report
    scoped to any other initiator finds documents but zero events and fails
    validation downstream.
    """
    return tuple(str(c) for c in (_load_country_config().get("influencers") or []))


def _known_recipients() -> tuple[str, ...]:
    return tuple(str(c) for c in (_load_country_config().get("recipients") or []))


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
            "influencer": {"type": "string", "description": "initiating country (required). Tracked initiators: China, Iran, Russia, Turkey, United States. If a tracked RECIPIENT is named here instead (e.g. Saudi Arabia), the offer is automatically reframed as a recipient-centric report covering all tracked initiators' interactions with it."},
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

        # Untracked initiator: the event pipeline only builds events for the
        # configured influencers, so an '<untracked> →' report would retrieve
        # documents but zero events and fail validation. When the country is a
        # known recipient, PIVOT instead of refusing: reframe as a
        # recipient-centric report — all tracked initiators' interactions with
        # that country (query_interpreter's recipient-without-influencer mode).
        pivot_note = None
        tracked = _tracked_influencers()
        if tracked and influencer not in tracked:
            if influencer in _known_recipients():
                pivot_note = (
                    f"{influencer} is not a tracked initiator (events are built only for "
                    f"{', '.join(tracked)}), so this is reframed as a recipient-centric "
                    f"report: all tracked initiators' interactions with {influencer}."
                )
                recipient = influencer
                region = None
                influencer = None
            else:
                return ToolResult(
                    ok=False,
                    error=(
                        f"'{influencer}' is neither a tracked initiator "
                        f"({', '.join(tracked)}) nor a tracked recipient — the corpus "
                        "cannot support a report scoped to it. Answer conversationally "
                        "with document_search instead, and say what the data does and "
                        "does not cover."
                    ),
                )
        if not recipient and not region:
            return ToolResult(ok=False, error="supply recipient (bilateral) or region (regional)")
        if not (_DATE_RE.match(start) and _DATE_RE.match(end)):
            return ToolResult(ok=False, error="start_date and end_date must be YYYY-MM-DD")

        reason = kwargs.get("reason")
        if pivot_note:
            reason = f"{reason} {pivot_note}".strip() if reason else pivot_note

        scope = {
            "influencer": influencer,
            "recipient": recipient,
            "region": region,
            "start_date": start,
            "end_date": end,
            "category": category,
            "category_mode": "filter" if category else "flat",
            "reason": reason,
        }
        target = recipient or region
        actor = influencer or "All tracked initiators"
        return ToolResult(
            ok=True,
            data=scope,
            summary=f"report offer: {actor} → {target}, {start}..{end}"
                    + (f" [{category}]" if category else ""),
        )


TOOL = ProposeReportTool()
