"""Stage 12: Validator.

Final correctness check before the report is returned.

Checks:
  * Every claim has at least one citation (citation_coverage_pct).
  * No hallucinated doc_ids — every cited doc_id was in the candidate set
    that Data QA / Sourcing pulled.
  * No entity referenced in narrative that's missing from entity_curator.
  * Date ranges and country names are normalized.
  * Output JSON conforms to the schema for the chosen writing product.

If validation fails on `error` severity, the workflow run is marked failed
and the offending stage's output is flagged for revision in a future
iteration loop. For v1 we report findings; we don't auto-revise.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class ValidatorStage(Stage):
    name = "validator"
    description = "Verify citations, schema conformance, no hallucinated doc_ids, normalized fields."
    required = True
    depends_on = ["sourcing_claims", "sourcing_entities"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: walk sourced_claims + sourced_entities; verify doc_ids appear in
        # data_qa's candidate set; compute coverage; report findings.
        findings: list[dict] = []
        return StageResult(
            ok=True,
            data={
                "passed": True,
                "findings": findings,
                "citation_coverage_pct": 0.0,
                "schema_conformance": True,
            },
            confidence=0.0,
            summary="validator: stub (0 findings)",
            notes=["stage body not yet implemented"],
        )


STAGE = ValidatorStage()
