"""Report-workflow evals.

report_deterministic_stages (live DB, no LLM)
    Runs the seven deterministic stages (query_interpreter, data_qa,
    event_prioritizer, anomaly, comparative_context, trajectory) in order
    against the real database for a canonical bilateral scope, asserting each
    stage's contract (ok, confidence, key fields) and cross-stage coherence
    (prioritizer count <= data_qa event_count, trajectory reuses data_qa).

report_validator_rules (pure, no DB, no LLM)
    Exercises the validator's rule table with hand-built WorkflowContexts:
    a clean run must PASS; hallucinated citations, empty prioritization, and
    zero citation coverage must each FAIL with the right rule; sub-threshold
    coverage must WARN but pass. This is the guardrail that decides whether
    a generated report is analyst-ready, so its rules get direct coverage.

report_full_run (LLM, opt-in via llm=True)
    One end-to-end REPORT_PIPELINE.run for a small scope; scores the run by
    the validator's own metrics (citation coverage, hallucination counts,
    narrative success rate) — the system grading its flagship product.
"""
from __future__ import annotations

from uuid import uuid4

from evals.core.runner import EvalResult, register

SCOPE = {
    "influencer": "China",
    "recipient": "Egypt",
    "start_date": "2025-01-01",
    "end_date": "2025-06-30",
}


@register("report_deterministic_stages")
def report_deterministic_stages(**kwargs) -> EvalResult:
    res = EvalResult(component="report_deterministic_stages")
    from agent.workflows.base import WorkflowContext
    from agent.workflows.report.stages import (
        query_interpreter, data_qa, event_prioritizer, anomaly,
        comparative_context, trajectory,
    )

    ctx = WorkflowContext(run_id=uuid4(), inputs=dict(SCOPE))
    stages = [query_interpreter.STAGE, data_qa.STAGE, event_prioritizer.STAGE,
              anomaly.STAGE, comparative_context.STAGE, trajectory.STAGE]
    for stage in stages:
        try:
            out = stage.run(ctx)
        except Exception as e:
            res.cases.append({"stage": stage.name, "verdict": "EXCEPTION",
                              "error": str(e)[:300]})
            out = None
        if out is not None:
            ctx.outputs[stage.name] = out
            res.cases.append({
                "stage": stage.name,
                "verdict": "pass" if out.ok else "FAIL",
                "confidence": out.confidence,
                "summary": (out.summary or "")[:140],
                **({"error": out.error} if out.error else {}),
            })

    qi = ctx.get("query_interpreter")
    dq = ctx.get("data_qa")
    pri = ctx.get("event_prioritizer")
    tra = ctx.get("trajectory")
    if qi and qi.ok and qi.data.get("scope") != "bilateral":
        res.notes.append(f"scope resolved to {qi.data.get('scope')!r}, expected bilateral")
    if dq and dq.ok:
        res.metrics["data_qa_doc_count"] = dq.data.get("doc_count")
        res.metrics["data_qa_event_count"] = dq.data.get("event_count")
        res.metrics["data_qa_sufficient"] = dq.data.get("sufficient")
        res.metrics["data_qa_gap_months"] = len(dq.data.get("gaps") or [])
    if pri and pri.ok:
        n = len(pri.data.get("events") or [])
        res.metrics["prioritized_events"] = n
        if dq and dq.ok and n > (dq.data.get("event_count") or 0):
            res.notes.append("prioritizer returned more events than data_qa scope count")
    if tra and tra.ok:
        res.metrics["trajectory_direction"] = tra.data.get("direction")
        res.metrics["trajectory_confidence"] = tra.data.get("confidence")
    res.metrics["stages_ok"] = sum(1 for c in res.cases if c.get("verdict") == "pass")
    res.metrics["stages_total"] = len(stages)
    res.caveats.append(f"Scope under test: {SCOPE}")
    return res


def _ctx(outputs: dict) -> "object":
    from agent.workflows.base import WorkflowContext, StageResult

    ctx = WorkflowContext(run_id=uuid4(), inputs={})
    for name, data in outputs.items():
        ctx.outputs[name] = StageResult(ok=True, data=data, confidence=1.0)
    return ctx


def _base_outputs() -> dict:
    return {
        "query_interpreter": {"category": None},
        "data_qa": {"doc_count": 500, "event_count": 12, "sufficient": True,
                    "gaps": [], "top_categories": [
                        {"category": "Economic", "doc_count": 200},
                        {"category": "Diplomacy", "doc_count": 180}]},
        "event_prioritizer": {"events": [{"event_id": "e1"}, {"event_id": "e2"}]},
        "event_narrator": {"narratives": [
            {"event_id": "e1", "ok": True, "cited_doc_ids": ["d1"],
             "hallucinated_doc_ids": []},
            {"event_id": "e2", "ok": True, "cited_doc_ids": ["d2"],
             "hallucinated_doc_ids": []}]},
        "claim_extractor": {"claims": [
            {"claim_id": "c1"}, {"claim_id": "c2"}, {"claim_id": "c3"}]},
        "sourcing_claims": {"sourced_claims": [
            {"claim_id": "c1", "cited_doc_ids": ["d1"], "hallucinated_doc_ids": []},
            {"claim_id": "c2", "cited_doc_ids": ["d2"], "hallucinated_doc_ids": []},
            {"claim_id": "c3", "cited_doc_ids": ["d1"], "hallucinated_doc_ids": []}]},
        "entity_curator": {"entities": [{"canonical_id": "x1", "name": "A"}]},
        "sourcing_entities": {"sourced_entities": [
            {"canonical_id": "x1", "cited_doc_ids": ["d1"],
             "hallucinated_doc_ids": [], "ok": True}]},
    }


@register("report_validator_rules")
def report_validator_rules(**kwargs) -> EvalResult:
    res = EvalResult(component="report_validator_rules")
    from agent.workflows.report.stages.validator import STAGE as validator

    def check(label, outputs, expect_pass, expect_rules=()):
        out = validator.run(_ctx(outputs))
        rules = {f["rule"] for f in out.data["findings"]}
        problems = []
        if out.data["passed"] != expect_pass:
            problems.append(f"passed={out.data['passed']}, expected {expect_pass}")
        for r in expect_rules:
            if r not in rules:
                problems.append(f"rule {r!r} not raised (got {sorted(rules)})")
        res.cases.append({
            "case": label,
            "verdict": "pass" if not problems else "FAIL",
            **({"detail": "; ".join(problems)} if problems else {}),
            "coverage": out.data["metrics"].get("citation_coverage_pct"),
        })

    check("clean_run_passes", _base_outputs(), True)

    o = _base_outputs()
    o["event_narrator"]["narratives"][0]["hallucinated_doc_ids"] = ["fake-1"]
    check("narrator_hallucination_fails", o, False, ["hallucinated_doc_ids"])

    o = _base_outputs()
    o["event_prioritizer"]["events"] = []
    check("empty_priority_fails", o, False, ["empty_priority"])

    o = _base_outputs()
    for s in o["sourcing_claims"]["sourced_claims"]:
        s["cited_doc_ids"] = []
    check("zero_coverage_fails", o, False, ["zero_citation_coverage"])

    o = _base_outputs()
    o["sourcing_claims"]["sourced_claims"][1]["cited_doc_ids"] = []
    o["sourcing_claims"]["sourced_claims"][2]["cited_doc_ids"] = []
    check("low_coverage_warns_but_passes", o, True, ["low_citation_coverage"])

    o = _base_outputs()
    o["data_qa"]["sufficient"] = False
    check("insufficient_data_warns_but_passes", o, True, ["data_sufficiency"])

    o = _base_outputs()
    del o["sourcing_claims"]
    check("missing_sourcing_fails", o, False, ["missing_sourcing"])

    res.metrics["cases"] = len(res.cases)
    res.metrics["failures"] = sum(1 for c in res.cases if c["verdict"] != "pass")
    return res


@register("report_full_run")
def report_full_run(llm: bool = False, **kwargs) -> EvalResult:
    res = EvalResult(component="report_full_run")
    if not llm:
        res.notes.append("Skipped (pass --llm): a full run costs ~31 LLM calls.")
        return res
    from agent.workflows.report.pipeline import run_report

    ctx = run_report(dict(SCOPE))
    for name, out in ctx.outputs.items():
        res.cases.append({"stage": name, "ok": out.ok,
                          "confidence": out.confidence,
                          "summary": (out.summary or "")[:140]})
    val = ctx.get("validator")
    if val is not None:
        res.metrics.update({k: v for k, v in val.data.get("metrics", {}).items()})
        res.metrics["validator_passed"] = val.data.get("passed")
        res.metrics["error_count"] = val.data.get("error_count")
        res.metrics["warning_count"] = val.data.get("warning_count")
    res.metrics["skipped_stages"] = ",".join(ctx.skipped) or "none"
    res.caveats.append(
        "Single-scope run; validator metrics (citation coverage, hallucination "
        "counts) are the primary quality signal. Repeat across scopes before "
        "treating numbers as representative."
    )
    return res
