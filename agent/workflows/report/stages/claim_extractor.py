"""Stage 8: Claim Extractor.

Reads the Event Narrator's prose and emits a structured list of atomic
factual claims. Without this, sourcing has to do claim-detection AND
source-finding in the same step and one will be done poorly.

Each claim has:
  claim_id   stable identifier
  text       the verbatim claim
  claim_type one of: stat, event, attribution, date, judgment
  source_stage which prior stage produced this claim's host text
  referent_id  the event_id or entity the claim is about (if known)

LLM role: substantive — claim detection is non-trivial. Output is rigid JSON.
TODO: implement via a focused extractor prompt.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class ClaimExtractorStage(Stage):
    name = "claim_extractor"
    description = "Split narrative prose into atomic claims for downstream sourcing."
    required = True
    depends_on = ["event_narrator"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: feed event_narrator output to an extractor LLM call
        return StageResult(
            ok=True,
            data={"claims": []},
            confidence=0.0,
            summary="claim_extractor: stub (0 claims)",
            notes=["stage body not yet implemented"],
        )


STAGE = ClaimExtractorStage()
