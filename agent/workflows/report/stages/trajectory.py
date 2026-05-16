"""Stage 6: Trajectory.

Compares the current period to the prior period of equal length and labels
direction: accelerating / steady / cooling. Surfaces the evidence behind
the label so downstream stages and analysts can audit.

LLM role: pick the label from quantitative inputs + write a 1-sentence
trajectory summary.
TODO: implement prior-period roll-up.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class TrajectoryStage(Stage):
    name = "trajectory"
    description = "Label direction (accelerating/steady/cooling) vs prior period of equal length."
    required = False
    depends_on = ["query_interpreter", "data_qa"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: roll up prior-period counts, compute deltas, label direction
        return StageResult(
            ok=True,
            data={
                "direction": "steady",
                "confidence": "LOW",
                "evidence": [],
                "prior_period_summary": None,
            },
            confidence=0.0,
            summary="trajectory: stub (steady, low confidence)",
            notes=["stage body not yet implemented"],
        )


STAGE = TrajectoryStage()
