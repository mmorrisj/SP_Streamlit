"""Stage 3: Event Prioritizer.

Ranks events in scope by a composite of (materiality_score × coverage). Top-N
events are surfaced; the rest are summarized in aggregate.

LLM role: minimal — primarily a deterministic ranking.
TODO: wire to canonical_events + daily_event_mentions counts.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext

DEFAULT_TOP_N = 8


class EventPrioritizerStage(Stage):
    name = "event_prioritizer"
    description = "Rank events by composite (materiality × coverage); return top-N."
    required = True
    depends_on = ["query_interpreter", "data_qa"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: SELECT events in scope, ORDER BY materiality * mention_count DESC
        return StageResult(
            ok=True,
            data={"events": [], "method": "materiality_x_coverage", "top_n": DEFAULT_TOP_N},
            confidence=0.0,
            summary="event_prioritizer: stub (0 events)",
            notes=["stage body not yet implemented"],
        )


STAGE = EventPrioritizerStage()
