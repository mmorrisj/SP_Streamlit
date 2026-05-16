"""Stage 5: Comparative Context.

Turns descriptive into analytical. For bilateral scope, computes:
  * Same influencer's activity in peer recipients (is this unusual?)
  * Recipient's activity with other influencers (where does this fit?)
  * Prior period of same length (baseline)

For regional scope:
  * Per-country breakdown vs regional median
  * Region vs adjacent regions

LLM role: write 1-2 sentence interpretation for each comparison point.
TODO: implement aggregation queries against event_summaries.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class ComparativeContextStage(Stage):
    name = "comparative_context"
    description = "Compute peer, prior-period, and regional comparisons; interpret each."
    required = False
    depends_on = ["query_interpreter", "data_qa"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: implement against bilateral_relationship_summaries +
        # country_category_summaries
        return StageResult(
            ok=True,
            data={"comparisons": []},
            confidence=0.0,
            summary="comparative_context: stub",
            notes=["stage body not yet implemented"],
        )


STAGE = ComparativeContextStage()
