"""Agent tool-layer evals (no LLM, live DB).

agent_tools_contract
    Drives every DB-backed converse/analyze tool with realistic arguments
    against the live database and checks the contract each tool promises:
    ok-flag semantics, result shape, citation emission, latency, and the
    documented edge behaviors (empty match => ok=True, missing arg =>
    ok=False, unknown recipient => loud error).

report_scope_matrix
    Exhaustive branch coverage of propose_report's scope validation:
    tracked initiator, tracked-recipient pivot, unknown country rejection,
    date-format rejection, missing-target rejection. Plus
    _analytics.validate_recipient alias/group/unknown handling.
"""
from __future__ import annotations

import time

from sqlalchemy import text

from evals.core.runner import EvalResult, register
from shared.database.database import get_session


def _run(res: EvalResult, label: str, tool, expect_ok=True, check=None, **args):
    t0 = time.time()
    try:
        out = tool.run(**args)
    except Exception as e:
        res.cases.append({"case": label, "verdict": "EXCEPTION", "error": str(e)[:200]})
        return None
    ms = round((time.time() - t0) * 1000)
    verdict = "pass"
    detail = None
    if bool(out.ok) != expect_ok:
        verdict = "FAIL"
        detail = f"expected ok={expect_ok}, got ok={out.ok} error={out.error}"
    elif check is not None:
        try:
            problem = check(out)
            if problem:
                verdict, detail = "FAIL", problem
        except Exception as e:
            verdict, detail = "FAIL", f"shape check raised: {e}"
    res.cases.append({"case": label, "verdict": verdict, "latency_ms": ms,
                      **({"detail": detail} if detail else {})})
    return out


@register("agent_tools_contract")
def agent_tools_contract(**kwargs) -> EvalResult:
    import os

    os.environ["AGENT_DOCUMENT_SEARCH_USE_MCP"] = "false"
    res = EvalResult(component="agent_tools_contract")

    # seed data pulled once so tool args are real
    with get_session() as s:
        ev_ids = [r[0] for r in s.execute(text(
            "SELECT id::text FROM canonical_events WHERE master_event_id IS NULL "
            "AND material_score IS NOT NULL AND initiating_country='China' "
            "ORDER BY total_articles DESC LIMIT 12")).fetchall()]
        doc_ids = [r[0] for r in s.execute(text(
            "SELECT doc_id FROM documents ORDER BY md5(doc_id || 'ct') LIMIT 5")).fetchall()]
        ent_row = s.execute(text(
            "SELECT id::text, canonical_name FROM canonical_entities "
            "WHERE master_entity_id IS NULL ORDER BY total_documents DESC LIMIT 1"
        )).fetchone()

    from agent.tools.entity_lookup import TOOL as entity_lookup
    from agent.tools.entity_graph import TOOL as entity_graph
    from agent.tools.event_timeline import TOOL as event_timeline
    from agent.tools.bilateral_context import TOOL as bilateral_context
    from agent.tools.citation_resolver import TOOL as citation_resolver
    from agent.tools.materiality_filter import TOOL as materiality_filter
    from agent.tools.country_grouping import TOOL as country_grouping
    from agent.tools.provenance_stats import TOOL as provenance_stats
    from agent.tools.initiative_ledger import TOOL as initiative_ledger
    from agent.tools.activity_series import TOOL as activity_series
    from agent.tools.insight_reports import TOOL as insight_reports

    _run(res, "entity_lookup/top_entity", entity_lookup,
         check=lambda o: None if o.data["matches"] else "no matches for most-documented entity",
         name=ent_row[1])
    _run(res, "entity_lookup/no_match_is_ok", entity_lookup,
         check=lambda o: None if o.data["matches"] == [] else "expected empty",
         name="Zxqv Plimtor")
    _run(res, "entity_lookup/missing_arg", entity_lookup, expect_ok=False)

    _run(res, "entity_graph/one_hop", entity_graph, canonical_id=ent_row[0],
         check=lambda o: None if "nodes" in o.data and "edges" in o.data else "shape")
    _run(res, "event_timeline/china_q1_2025", event_timeline,
         start_date="2025-01-01", end_date="2025-03-31", influencer="China",
         check=lambda o: None if o.data["events"] else "no events in a 3-month China window")
    _run(res, "event_timeline/missing_dates", event_timeline, expect_ok=False,
         influencer="China")
    _run(res, "bilateral_context/china_egypt", bilateral_context,
         influencer="China", recipient="Egypt")
    _run(res, "citation_resolver/real_docs", citation_resolver, doc_ids=doc_ids,
         check=lambda o: None if not o.data["missing"] else f"missing={o.data['missing']}")
    if ev_ids:
        _run(res, "materiality_filter/bands", materiality_filter, event_ids=ev_ids,
             check=lambda o: None if o.data["events"] else "no events returned")
        _run(res, "country_grouping/pair", country_grouping, event_ids=ev_ids,
             group_by="pair",
             check=lambda o: None if o.data["groups"] else "no groups")
    _run(res, "provenance_stats/iran_lebanon", provenance_stats,
         initiating_country="Iran", recipient_country="Lebanon",
         check=lambda o: None if o.data.get("raw_docs", 0) > 0 else "raw_docs=0")
    _run(res, "provenance_stats/unknown_recipient_loud", provenance_stats,
         expect_ok=False, initiating_country="Iran", recipient_country="Atlantis")
    _run(res, "activity_series/iran_lebanon", activity_series,
         initiating_country="Iran", recipient_country="Lebanon",
         check=lambda o: None if o.data.get("series") else "empty series")
    _run(res, "activity_series/group_rejected", activity_series, expect_ok=False,
         initiating_country="Iran", recipient_country="the Gulf")
    _run(res, "initiative_ledger/china", initiative_ledger,
         initiating_country="China")
    _run(res, "insight_reports/query", insight_reports, query="China influence Egypt")

    n_fail = sum(1 for c in res.cases if c["verdict"] != "pass")
    res.metrics["cases"] = len(res.cases)
    res.metrics["failures"] = n_fail
    lat = [c["latency_ms"] for c in res.cases if "latency_ms" in c]
    if lat:
        res.metrics["latency_ms_max"] = max(lat)
        res.metrics["latency_ms_mean"] = sum(lat) / len(lat)
    res.caveats.append(
        "Contract checks assert tool-level behavior against live data; they do "
        "not judge whether the LLM picks the right tool (see converse_behavior)."
    )
    return res


@register("report_scope_matrix")
def report_scope_matrix(**kwargs) -> EvalResult:
    res = EvalResult(component="report_scope_matrix")
    from agent.tools.propose_report import TOOL as propose_report
    from agent.tools._analytics import validate_recipient

    base = {"start_date": "2025-01-01", "end_date": "2025-03-31"}

    out = _run(res, "tracked_initiator", propose_report,
               influencer="China", recipient="Egypt", **base,
               check=lambda o: None if o.data["influencer"] == "China" else "scope mangled")
    out = _run(res, "recipient_pivot", propose_report,
               influencer="Saudi Arabia", recipient=None, region="gulf", **base)
    if out is not None and out.ok:
        d = out.data
        if d.get("influencer") is None and d.get("recipient") == "Saudi Arabia":
            res.notes.append("Pivot branch confirmed: untracked-but-known initiator "
                             "re-scoped to recipient-centric report.")
        else:
            res.cases.append({"case": "recipient_pivot_shape", "verdict": "FAIL",
                              "detail": f"data={d}"})
    _run(res, "unknown_country_rejected", propose_report, expect_ok=False,
         influencer="Brazil", recipient="Egypt", **base)
    _run(res, "bad_date_rejected", propose_report, expect_ok=False,
         influencer="China", recipient="Egypt",
         start_date="Jan 1 2025", end_date="2025-03-31")
    _run(res, "no_target_rejected", propose_report, expect_ok=False,
         influencer="China", **base)

    # validate_recipient behaviors
    vr_cases = [
        ("UAE", "alias_resolves", lambda c, e: c is not None and e is None),
        ("gulf", "group_errors_loud", lambda c, e: c is None and e and "member" in e.lower()),
        ("Atlantis", "unknown_errors_loud", lambda c, e: c is None and e is not None),
        ("Egypt", "known_passthrough", lambda c, e: c == "Egypt"),
    ]
    # Documented gap probe (not a hard failure): natural phrasing with a
    # leading article misses the group table and reads as 'unknown'.
    try:
        canon, err = validate_recipient("the Gulf")
        if err and "member" not in err.lower():
            res.notes.append(
                "validate_recipient('the Gulf') falls through to the generic "
                "unknown-recipient error — GROUP_MEMBERS keys are exact "
                "lowercase; leading articles are not stripped."
            )
    except Exception:
        pass
    for name, label, pred in vr_cases:
        try:
            canon, err = validate_recipient(name)
            res.cases.append({"case": f"validate_recipient/{label}",
                              "verdict": "pass" if pred(canon, err) else "FAIL",
                              "detail": f"canonical={canon!r} err={str(err)[:80]!r}"})
        except Exception as e:
            res.cases.append({"case": f"validate_recipient/{label}",
                              "verdict": "EXCEPTION", "error": str(e)[:150]})

    res.metrics["cases"] = len(res.cases)
    res.metrics["failures"] = sum(1 for c in res.cases if c["verdict"] != "pass")
    return res
