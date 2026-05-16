"""Stage 7: Event Narrator.

For each top-priority event, drafts a detailed overview and outcomes
narrative pulling from the event's mention documents and any existing
event_summary narratives.

LLM role: substantive — composes prose. Must stay grounded in the supplied
context (no fabrication of dates, actors, or amounts).

TODO: fetch event context per event_id and call the LLM with a focused
narrator system prompt.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class EventNarratorStage(Stage):
    name = "event_narrator"
    description = "Draft overview + outcomes narrative for each top-priority event."
    required = True
    depends_on = ["event_prioritizer"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        prioritized = ctx.require("event_prioritizer").data.get("events", [])
        # TODO: per event, pull mentions, summaries, and call LLM
        narratives = [
            {"event_id": e.get("event_id"), "overview": "", "outcomes": ""}
            for e in prioritized
        ]
        return StageResult(
            ok=True,
            data={"narratives": narratives},
            confidence=0.0,
            summary=f"event_narrator: stub ({len(narratives)} events)",
            notes=["stage body not yet implemented"],
        )


STAGE = EventNarratorStage()
