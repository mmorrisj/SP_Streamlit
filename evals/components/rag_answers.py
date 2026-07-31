"""End-to-end answer-quality evals (LLM-gated).

rag_answers (--llm)
    Runs the full chat path (intelligent_search -> build_context_prompt ->
    generate_response) on a fixed question set and scores:
      * citation validity  (deterministic): every [N] in the answer must map
        to a returned source; answers with zero citations are flagged.
      * groundedness       (LLM judge): each answer sentence bearing a
        citation is checked against the cited document's retrieved content.
      * refusal correctness: out-of-corpus questions must produce the
        mandated no-context response, not a fabricated answer.

converse_behavior (--llm)
    Drives Orchestrator.converse on prompts engineered to test the ANALYTIC
    DOCTRINE in the system prompt:
      * cross-actor volume comparison  -> should call provenance_stats
      * trend question                 -> should call activity_series
      * strategic question             -> should consult search_insight_reports
      * entity question                -> entity_lookup before claims
      * every answer                   -> emits sources; no invented doc ids
    Also probes classify_intent on a small labeled set (action + scope).
"""
from __future__ import annotations

import json
import re

from evals.core.runner import EvalResult, register

CITE_RE = re.compile(r"\[(\d{1,3})\]")

QUESTIONS = [
    {"q": "What infrastructure projects has China financed in Egypt since 2025?",
     "kind": "grounded"},
    {"q": "How has Iran used cultural and religious outreach in Lebanon recently?",
     "kind": "grounded"},
    {"q": "Compare Russia's military cooperation with Syria and Libya.",
     "kind": "grounded"},
    {"q": "What role does TIKA play in Turkey's activities in Libya?",
     "kind": "grounded"},
    {"q": "What did the King of Sweden announce about Nordic defense articles in the Baltic Assembly?",
     "kind": "out_of_corpus"},
    {"q": "Summarize Brazil's soft-power lending programs in Paraguay in 2025.",
     "kind": "out_of_corpus"},
]

NO_CONTEXT_MARKERS = [
    "does not contain information",
    "no documents",
    "not contain relevant",
    "couldn't find", "could not find",
]

JUDGE_PROMPT = """You are grading a retrieval-augmented answer for groundedness.
You will get: the answer sentence, the citation number it carries, and the text
of the cited source document. Decide whether the sentence's factual content is
supported by that source text. Reply ONLY with JSON:
{"supported": true|false, "reason": "<one short sentence>"}"""


@register("rag_answers")
def rag_answers(llm: bool = False, **kwargs) -> EvalResult:
    res = EvalResult(component="rag_answers")
    if not llm:
        res.notes.append("Skipped (pass --llm): needs generation + judge calls.")
        return res

    import services.chat.rag_service as rag
    from shared.utils.utils import gai, fetch_gai_content

    grounded_scores, cite_valid, refusal_ok = [], [], []
    for item in QUESTIONS:
        q = item["q"]
        try:
            docs, meta = rag.intelligent_search(q)
            answer = rag.generate_response(
                q, docs,
                matched_entities=meta.get("_matched_entities_full"),
                strategic_context=meta.get("_strategic_context"),
                event_context=meta.get("_event_context"),
            )
        except Exception as e:
            res.cases.append({"q": q[:80], "error": str(e)[:200]})
            continue

        cites = [int(n) for n in CITE_RE.findall(answer)]
        valid = [n for n in cites if 1 <= n <= len(docs)]
        case = {"q": q[:80], "kind": item["kind"], "n_sources": len(docs),
                "n_citations": len(cites),
                "invalid_citations": len(cites) - len(valid)}

        if item["kind"] == "out_of_corpus":
            low = answer.lower()
            refused = any(m in low for m in NO_CONTEXT_MARKERS) or len(cites) == 0
            refusal_ok.append(1.0 if refused else 0.0)
            case["refused"] = refused
            if not refused:
                case["answer_head"] = answer[:200]
        else:
            cite_valid.append(1.0 if cites and not (len(cites) - len(valid)) else 0.0)
            # judge up to 4 cited sentences per answer
            by_num = {d["citation_number"]: d for d in docs}
            sentences = re.split(r"(?<=[.!?])\s+", answer)
            judged = 0
            supported = 0
            for sent in sentences:
                ns = [int(x) for x in CITE_RE.findall(sent) if int(x) in by_num]
                if not ns or judged >= 4:
                    continue
                src = by_num[ns[0]]["content"][:3000]
                try:
                    resp = gai(
                        JUDGE_PROMPT,
                        json.dumps({"sentence": sent[:600], "citation": ns[0],
                                    "source_text": src}),
                        model="gpt-4o-mini")
                    # gai() returns parsed JSON on the proxy path, a raw
                    # OpenAI envelope elsewhere, or a plain string.
                    if isinstance(resp, dict) and "choices" in resp:
                        verdict = fetch_gai_content(resp)
                    elif isinstance(resp, str):
                        s0, s1 = resp.find("{"), resp.rfind("}")
                        verdict = json.loads(resp[s0:s1 + 1]) if s0 >= 0 else {}
                    else:
                        verdict = resp
                    if isinstance(verdict, list) and verdict:
                        verdict = verdict[0]
                    ok = bool(verdict.get("supported"))
                except Exception:
                    continue
                judged += 1
                supported += 1 if ok else 0
                if not ok:
                    res.cases.append({"q": q[:60], "unsupported": sent[:160],
                                      "reason": str(verdict.get("reason"))[:120]})
            if judged:
                grounded_scores.append(supported / judged)
                case["groundedness"] = supported / judged
        res.cases.append(case)

    if grounded_scores:
        res.metrics["groundedness_mean"] = sum(grounded_scores) / len(grounded_scores)
    if cite_valid:
        res.metrics["citation_validity_rate"] = sum(cite_valid) / len(cite_valid)
    if refusal_ok:
        res.metrics["out_of_corpus_refusal_rate"] = sum(refusal_ok) / len(refusal_ok)
    res.caveats.append(
        "Groundedness judge sees only the retrieved snippet, not the full "
        "document; a sentence supported by unretrieved text scores as "
        "unsupported. Judge model shares family with the generator (both "
        "GPT-4o-mini class) — same-family leniency bias applies."
    )
    res.caveats.append(
        "Bias framing: groundedness measures faithfulness to the corpus. A "
        "perfectly grounded answer still inherits the corpus's media lens "
        "(Iranian state-media over-representation); provenance caveats are "
        "evaluated in converse_behavior, not here."
    )
    return res


# Valid actions: propose_run | update_scope | clarify | chat
# (orchestrator coerces anything else to "chat"). Accept-sets, not single
# labels: "clarify" is a defensible response to underspecified questions.
INTENT_CASES = [
    {"msg": "Give me a report on China in Egypt for the first half of 2025",
     "expect_actions": {"propose_run"}},
    {"msg": "What's the latest on Turkish drone diplomacy?",
     "expect_actions": {"chat", "clarify"}},
    {"msg": "hi", "expect_actions": {"chat"}},
    {"msg": "Run a report on Brazil in Argentina for 2025",
     "expect_actions": {"clarify", "chat"}},  # untracked initiator: must NOT propose_run
]

CONVERSE_PROBES = [
    {"msg": "Who is more active in Lebanon, Iran or China? Compare their volumes.",
     "want_tools": ["provenance_stats"], "label": "volume_comparison_uses_provenance"},
    {"msg": "How has China's engagement with Egypt trended over the past year?",
     "want_tools": ["activity_series"], "label": "trend_uses_series"},
    {"msg": "Who is Hassan Nasrallah and what role does he play?",
     "want_tools": ["entity_lookup"], "label": "entity_question_uses_lookup"},
]


@register("converse_behavior")
def converse_behavior(llm: bool = False, **kwargs) -> EvalResult:
    res = EvalResult(component="converse_behavior")
    if not llm:
        res.notes.append("Skipped (pass --llm): drives the live agent loop.")
        return res
    import os

    os.environ["AGENT_DOCUMENT_SEARCH_USE_MCP"] = "false"
    from agent.orchestrator import Orchestrator
    from agent.schemas import ConverseRequest, ChatTurnRequest, ChatScope

    orch = Orchestrator()

    # --- intent classification -----------------------------------------
    intent_hits = 0
    for c in INTENT_CASES:
        try:
            out = orch.classify_intent(
                ChatTurnRequest(message=c["msg"], history=[],
                                current_scope=ChatScope()))
            got = out.action
        except Exception as e:
            res.cases.append({"intent": c["msg"][:60], "error": str(e)[:150]})
            continue
        ok = got in c["expect_actions"]
        intent_hits += ok
        res.cases.append({"intent": c["msg"][:60],
                          "expected": sorted(c["expect_actions"]),
                          "got": got, "verdict": "pass" if ok else "FAIL"})
    res.metrics["intent_accuracy"] = intent_hits / max(len(INTENT_CASES), 1)

    # --- converse doctrine probes ---------------------------------------
    doctrine_hits = 0
    for probe in CONVERSE_PROBES:
        events: list[dict] = []
        try:
            orch.converse(ConverseRequest(message=probe["msg"], history=[]),
                          on_event=events.append)
        except Exception as e:
            res.cases.append({"probe": probe["label"], "error": str(e)[:200]})
            continue
        tools_used = [e.get("tool") for e in events if e.get("type") == "tool_call"
                      or "tool" in e and e.get("step") is not None]
        tools_used = [e["tool"] for e in events if e.get("tool")]
        answer_ev = next((e for e in events if e.get("text")), {})
        sources_ev = next((e for e in events if e.get("documents") is not None), {})
        hit = any(t in tools_used for t in probe["want_tools"])
        doctrine_hits += hit
        res.cases.append({
            "probe": probe["label"],
            "verdict": "pass" if hit else "FAIL",
            "tools_used": tools_used,
            "n_sources": len(sources_ev.get("documents") or []),
            "answer_head": (answer_ev.get("text") or "")[:160],
        })
    res.metrics["doctrine_adherence"] = doctrine_hits / max(len(CONVERSE_PROBES), 1)
    res.caveats.append(
        "Tool-routing assertions are necessary-condition checks (the doctrine "
        "says these tools SHOULD be consulted); a pass does not certify the "
        "final prose used the numbers correctly. Small probe set — treat as "
        "smoke-level, expand before drawing trends."
    )
    return res
