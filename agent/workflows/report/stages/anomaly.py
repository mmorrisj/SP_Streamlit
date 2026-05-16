"""Stage 4: Anomaly / Signal Detector.

Identifies items that stand out relative to baseline:
  * new entities first-appearing in this period
  * categories spiking vs prior period
  * materiality outliers within the scope
  * unusual entity / category co-occurrences

These are the report's "lead" items — what an experienced analyst would
mention up top.

LLM role: classify and write 1-sentence justifications for each anomaly.
TODO: implement signal detectors against historical baselines.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class AnomalyStage(Stage):
    name = "anomaly"
    description = "Flag new entities, category spikes, materiality outliers, unusual co-occurrences."
    required = False
    depends_on = ["query_interpreter", "data_qa", "event_prioritizer"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: compare current-period aggregates against prior-period baselines
        return StageResult(
            ok=True,
            data={"anomalies": []},
            confidence=0.0,
            summary="anomaly: stub (0 signals)",
            notes=["stage body not yet implemented"],
        )


STAGE = AnomalyStage()
