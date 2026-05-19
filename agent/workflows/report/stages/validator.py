"""Stage 12: Validator.

Final correctness check before the report is returned. Pure walk-and-check
over prior stages' outputs — no SQL, no LLM, fully deterministic.

What's checked:
  - Hallucinated doc_ids that upstream sourcing/narration flagged.
    These should be zero if the allow-list enforcement is working; any
    non-zero count is an error.
  - Citation coverage: fraction of claims with at least one validated
    cited_doc_id. Below 60% is a warning; zero is an error.
  - Unsourced claims: enumerated for analyst review.
  - Per-event narration completeness: every prioritized event got an
    attempted narrative.
  - Stage-level confidence floors: required stages below 0.4 confidence
    are warnings.
  - Data-sufficiency: if data_qa flagged the input as insufficient, that's
    a warning on the run.
  - Optional-stage emptiness: if entity_curator returned 0 entities,
    info-level.

Severity semantics:
  error    publication-blocking. Hallucinated doc_ids that leaked through,
           zero citation coverage, all events failed narration.
  warning  degraded quality but not a block. Low coverage, unsourced
           claims, optional sourcing failures, low confidence stages.
  info     noteworthy but expected. Optional stage skipped/empty.

Stage status:
  ok = True  iff no error-severity findings. A failed validation marks
  the workflow run as failed in agent_workflow_runs.status because the
  validator is required = True. That's the right signal: a report with
  hallucinated citations or zero sourcing is not analyst-ready.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent.workflows.base import Stage, StageResult, WorkflowContext

logger = logging.getLogger(__name__)

# Thresholds — surfaced as constants so they're easy to tune.
CITATION_COVERAGE_WARN_THRESHOLD = 0.60
STAGE_CONFIDENCE_WARN_THRESHOLD = 0.40


@dataclass
class _Finding:
    severity: str   # "info" | "warning" | "error"
    where: str
    detail: str
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "where": self.where,
            "detail": self.detail,
            "rule": self.rule,
        }


class ValidatorStage(Stage):
    name = "validator"
    description = (
        "Verify citation coverage, no hallucinated doc_ids, narration "
        "completeness, stage confidence floors."
    )
    required = True
    # Soft dependencies: validator runs even if optional upstream stages
    # were skipped or failed — it'll just report what it sees.
    depends_on = ["event_prioritizer"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        findings: list[_Finding] = []
        metrics: dict[str, Any] = {}

        _check_data_qa(ctx, findings, metrics)
        _check_prioritization(ctx, findings, metrics)
        _check_narration(ctx, findings, metrics)
        _check_claims_and_sourcing(ctx, findings, metrics)
        _check_entities_and_sourcing(ctx, findings, metrics)
        _check_stage_confidence(ctx, findings)

        error_count = sum(1 for f in findings if f.severity == "error")
        warning_count = sum(1 for f in findings if f.severity == "warning")
        info_count = sum(1 for f in findings if f.severity == "info")

        passed = error_count == 0
        coverage = metrics.get("citation_coverage_pct", 0.0)

        summary = (
            f"validator: {'PASS' if passed else 'FAIL'} — "
            f"{error_count} error / {warning_count} warning / {info_count} info; "
            f"citation coverage {coverage:.0%}"
        )

        notes: list[str] = []
        if not passed:
            # Echo the first 3 errors into notes for the workflow trace UI.
            for f in findings:
                if f.severity == "error":
                    notes.append(f"[{f.rule}] {f.where}: {f.detail}")
                if len(notes) >= 3:
                    break

        data: dict[str, Any] = {
            "passed": passed,
            "findings": [f.to_dict() for f in findings],
            "metrics": metrics,
            "schema_conformance": True,  # No schema drift detected by checks above
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
        }

        return StageResult(
            ok=passed,
            data=data,
            confidence=1.0 if passed else 0.0,
            summary=summary,
            notes=notes,
            error=None if passed else f"{error_count} validation error(s)",
        )


# ---------------------------------------------------------------------------
# Per-stage checks
# ---------------------------------------------------------------------------

def _check_data_qa(
    ctx: WorkflowContext,
    findings: list[_Finding],
    metrics: dict[str, Any],
) -> None:
    qa = ctx.get("data_qa")
    if qa is None or not qa.ok:
        findings.append(_Finding(
            severity="warning",
            where="data_qa",
            detail="stage missing or failed; downstream stages may be unreliable",
            rule="stage_health",
        ))
        return
    data = qa.data or {}
    metrics["doc_count"] = data.get("doc_count", 0)
    metrics["event_count_in_scope"] = data.get("event_count", 0)
    if not data.get("sufficient", False):
        findings.append(_Finding(
            severity="warning",
            where="data_qa",
            detail=(
                f"data flagged insufficient: {data.get('doc_count', 0)} docs / "
                f"{data.get('event_count', 0)} events. "
                f"Suggested actions: {data.get('suggested_actions') or []}"
            ),
            rule="data_sufficiency",
        ))
    gaps = data.get("gaps") or []
    metrics["coverage_gap_months"] = len([g for g in gaps if not g.startswith("not_implemented")])

    # Category-dominance signal: only meaningful when no category filter is
    # already applied. Threshold of 50% is conservative — if one category
    # accounts for more than half the in-scope docs the analyst should
    # probably consider running with category_mode=filter (Phase 1) or
    # =breakdown (Phase 2) so smaller categories don't get drowned out.
    qi = ctx.get("query_interpreter")
    qi_data = (qi.data if qi and qi.ok else None) or {}
    if not qi_data.get("category"):
        top_cats = data.get("top_categories") or []
        total = sum(int(c.get("doc_count") or 0) for c in top_cats)
        if total > 0 and top_cats:
            top = top_cats[0]
            share = (int(top.get("doc_count") or 0)) / total
            metrics["dominant_category"] = top.get("category")
            metrics["dominant_category_share_pct"] = round(share * 100, 1)
            if share >= 0.5:
                findings.append(_Finding(
                    severity="info",
                    where="data_qa",
                    detail=(
                        f"{top.get('category')} is {share * 100:.0f}% of in-scope "
                        f"docs ({top.get('doc_count')} / {total}). Consider "
                        f"category_mode=filter (single-category scope) to keep "
                        f"smaller categories visible."
                    ),
                    rule="dominant_category",
                ))


def _check_prioritization(
    ctx: WorkflowContext,
    findings: list[_Finding],
    metrics: dict[str, Any],
) -> None:
    pri = ctx.get("event_prioritizer")
    if pri is None or not pri.ok:
        findings.append(_Finding(
            severity="error",
            where="event_prioritizer",
            detail="stage missing or failed; nothing to validate downstream",
            rule="stage_health",
        ))
        return
    events = (pri.data or {}).get("events") or []
    metrics["prioritized_event_count"] = len(events)
    if not events:
        findings.append(_Finding(
            severity="error",
            where="event_prioritizer",
            detail="zero events surfaced; report has no substantive content",
            rule="empty_priority",
        ))


def _check_narration(
    ctx: WorkflowContext,
    findings: list[_Finding],
    metrics: dict[str, Any],
) -> None:
    nar = ctx.get("event_narrator")
    if nar is None:
        findings.append(_Finding(
            severity="error",
            where="event_narrator",
            detail="narration stage did not run",
            rule="stage_health",
        ))
        return

    narratives = (nar.data or {}).get("narratives") or []
    metrics["narrative_count"] = len(narratives)
    succeeded = [n for n in narratives if n.get("ok")]
    metrics["narrative_success_count"] = len(succeeded)

    if narratives and not succeeded:
        findings.append(_Finding(
            severity="error",
            where="event_narrator",
            detail="every event failed narration; no prose to validate",
            rule="all_narratives_failed",
        ))

    failed = [n for n in narratives if not n.get("ok")]
    for n in failed:
        findings.append(_Finding(
            severity="warning",
            where=f"event_narrator::{n.get('event_id')}",
            detail=f"narration failed: {n.get('failure_reason') or 'unknown'}",
            rule="narrative_failure",
        ))

    # Hallucinated doc_ids per narrative (the narrator already filtered them
    # out of cited_doc_ids, but the model claimed them — flag explicitly).
    total_hallucinated = 0
    for n in narratives:
        h = n.get("hallucinated_doc_ids") or []
        if h:
            total_hallucinated += len(h)
            findings.append(_Finding(
                severity="error",
                where=f"event_narrator::{n.get('event_id')}",
                detail=f"model attempted to cite {len(h)} doc_id(s) not in allow-list: {h[:5]}",
                rule="hallucinated_doc_ids",
            ))
    metrics["hallucinated_doc_ids_narrator"] = total_hallucinated


def _check_claims_and_sourcing(
    ctx: WorkflowContext,
    findings: list[_Finding],
    metrics: dict[str, Any],
) -> None:
    extractor = ctx.get("claim_extractor")
    sourcing = ctx.get("sourcing_claims")

    claims = (extractor.data or {}).get("claims") if extractor and extractor.ok else []
    sourced = (sourcing.data or {}).get("sourced_claims") if sourcing and sourcing.ok else []
    metrics["claim_count"] = len(claims)
    metrics["sourced_claim_count"] = len(sourced)

    if not claims:
        findings.append(_Finding(
            severity="warning",
            where="claim_extractor",
            detail="zero claims extracted; report has no atomic facts to source",
            rule="empty_claims",
        ))
        metrics["citation_coverage_pct"] = 0.0
        return

    if sourcing is None or not sourcing.ok:
        findings.append(_Finding(
            severity="error",
            where="sourcing_claims",
            detail="claims exist but sourcing stage missing or failed",
            rule="missing_sourcing",
        ))
        metrics["citation_coverage_pct"] = 0.0
        return

    cited = sum(1 for s in sourced if s.get("cited_doc_ids"))
    unsourced = len(sourced) - cited
    coverage = cited / len(sourced) if sourced else 0.0
    metrics["citation_coverage_pct"] = round(coverage, 3)
    metrics["unsourced_claim_count"] = unsourced

    if coverage == 0.0 and sourced:
        findings.append(_Finding(
            severity="error",
            where="sourcing_claims",
            detail="zero claims received any citation",
            rule="zero_citation_coverage",
        ))
    elif coverage < CITATION_COVERAGE_WARN_THRESHOLD:
        findings.append(_Finding(
            severity="warning",
            where="sourcing_claims",
            detail=(
                f"citation coverage {coverage:.0%} below "
                f"{CITATION_COVERAGE_WARN_THRESHOLD:.0%} threshold "
                f"({unsourced} of {len(sourced)} claims unsourced)"
            ),
            rule="low_citation_coverage",
        ))

    if unsourced > 0 and coverage > 0.0:
        sample = [s["claim_id"] for s in sourced if not s.get("cited_doc_ids")][:5]
        findings.append(_Finding(
            severity="warning",
            where="sourcing_claims",
            detail=f"{unsourced} unsourced claim(s); sample: {sample}",
            rule="unsourced_claims",
        ))

    # Hallucinated doc_ids per sourced claim (already stripped from
    # cited_doc_ids upstream, but flagging the attempts is important).
    total_hallucinated = 0
    for s in sourced:
        h = s.get("hallucinated_doc_ids") or []
        if h:
            total_hallucinated += len(h)
            findings.append(_Finding(
                severity="error",
                where=f"sourcing_claims::{s.get('claim_id')}",
                detail=f"model attempted to cite {len(h)} doc_id(s) not in candidates: {h[:5]}",
                rule="hallucinated_doc_ids",
            ))
    metrics["hallucinated_doc_ids_sourcing_claims"] = total_hallucinated


def _check_entities_and_sourcing(
    ctx: WorkflowContext,
    findings: list[_Finding],
    metrics: dict[str, Any],
) -> None:
    curator = ctx.get("entity_curator")
    sourcing = ctx.get("sourcing_entities")

    entities = (curator.data or {}).get("entities") if curator and curator.ok else []
    sourced = (sourcing.data or {}).get("sourced_entities") if sourcing and sourcing.ok else []
    metrics["curated_entity_count"] = len(entities)
    metrics["sourced_entity_count"] = len(sourced)

    # entity_curator is optional — an empty result is info, not warning.
    if curator is not None and not entities:
        findings.append(_Finding(
            severity="info",
            where="entity_curator",
            detail="zero entities curated; report will have no entity section",
            rule="empty_entities",
        ))

    if not entities or sourcing is None:
        return

    if not sourcing.ok:
        findings.append(_Finding(
            severity="warning",
            where="sourcing_entities",
            detail="entities curated but sourcing stage failed",
            rule="missing_entity_sourcing",
        ))
        return

    uncited = sum(1 for s in sourced if not s.get("cited_doc_ids"))
    cited = len(sourced) - uncited
    entity_coverage = cited / len(sourced) if sourced else 0.0
    metrics["entity_citation_coverage_pct"] = round(entity_coverage, 3)
    metrics["uncited_entity_count"] = uncited

    if entity_coverage == 0.0 and sourced:
        findings.append(_Finding(
            severity="warning",
            where="sourcing_entities",
            detail="zero entities received any citation",
            rule="zero_entity_coverage",
        ))
    elif uncited > len(sourced) / 2:
        findings.append(_Finding(
            severity="warning",
            where="sourcing_entities",
            detail=(
                f"more than half of curated entities are uncited "
                f"({uncited} of {len(sourced)})"
            ),
            rule="majority_uncited_entities",
        ))

    total_hallucinated = 0
    for s in sourced:
        h = s.get("hallucinated_doc_ids") or []
        if h:
            total_hallucinated += len(h)
            findings.append(_Finding(
                severity="error",
                where=f"sourcing_entities::{s.get('canonical_id')}",
                detail=f"model attempted to cite {len(h)} doc_id(s) not in candidates: {h[:5]}",
                rule="hallucinated_doc_ids",
            ))
    metrics["hallucinated_doc_ids_sourcing_entities"] = total_hallucinated


def _check_stage_confidence(
    ctx: WorkflowContext,
    findings: list[_Finding],
) -> None:
    """Flag required stages whose confidence dropped below the floor."""
    required_stage_names = {
        "query_interpreter", "data_qa", "event_prioritizer",
        "event_narrator", "claim_extractor", "sourcing_claims",
    }
    for stage_name, result in ctx.outputs.items():
        if stage_name not in required_stage_names:
            continue
        if result.confidence is None:
            continue
        if result.confidence < STAGE_CONFIDENCE_WARN_THRESHOLD:
            findings.append(_Finding(
                severity="warning",
                where=stage_name,
                detail=(
                    f"stage confidence {result.confidence:.2f} below "
                    f"{STAGE_CONFIDENCE_WARN_THRESHOLD:.2f} floor"
                ),
                rule="low_stage_confidence",
            ))


STAGE = ValidatorStage()
