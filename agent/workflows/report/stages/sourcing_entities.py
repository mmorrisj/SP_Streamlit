"""Stage 11: Sourcing — Entities pass.

Mirrors Sourcing #1 but for entity synopses. For each curated entity, finds
the best doc_ids that substantiate the role/impact claims in its synopsis.

LLM role: rank candidate documents per entity.
TODO: same shape as sourcing_claims.py, scoped to entities.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class SourcingEntitiesStage(Stage):
    name = "sourcing_entities"
    description = "Attach best-fit document citations to each curated entity synopsis."
    required = False
    depends_on = ["entity_curator"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        entity_payload = ctx.get("entity_curator")
        entities = (entity_payload.data.get("entities") if entity_payload and entity_payload.ok else []) or []
        # TODO: per entity, fetch supporting docs, rank, attach citations.
        sourced = [
            {"canonical_id": e.get("canonical_id"), "cited_doc_ids": []}
            for e in entities
        ]
        return StageResult(
            ok=True,
            data={"sourced_entities": sourced},
            confidence=0.0,
            summary=f"sourcing_entities: stub ({len(sourced)} entities)",
            notes=["stage body not yet implemented"],
        )


STAGE = SourcingEntitiesStage()
