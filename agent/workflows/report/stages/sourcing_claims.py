"""Stage 9: Sourcing — Claims pass.

For each extracted claim, finds the best doc_ids that support it and emits
inline citation placeholders. The selection prefers documents that:
  * are aligned to the same event/entity referent
  * are higher-confidence sources (source_name reputation, salience)
  * have a higher semantic match to the claim text

LLM role: rank candidate documents. Tool access: rag_service (already MCP).
TODO: implement candidate fetch + LLM ranker.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class SourcingClaimsStage(Stage):
    name = "sourcing_claims"
    description = "Attach best-fit document citations to each extracted claim."
    required = True
    depends_on = ["claim_extractor", "event_prioritizer"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        claims = ctx.require("claim_extractor").data.get("claims", [])
        # TODO: for each claim, fetch doc_ids aligned to referent + semantic match,
        # call LLM ranker, attach top citations.
        sourced = [{"claim_id": c.get("claim_id"), "cited_doc_ids": [],
                    "confidence": "LOW"} for c in claims]
        return StageResult(
            ok=True,
            data={"sourced_claims": sourced},
            confidence=0.0,
            summary=f"sourcing_claims: stub ({len(sourced)} claims)",
            notes=["stage body not yet implemented"],
        )


STAGE = SourcingClaimsStage()
