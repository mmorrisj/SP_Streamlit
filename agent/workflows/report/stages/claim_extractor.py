"""Stage 8: Claim Extractor.

Decomposes each event narrative into atomic factual claims so that
sourcing has a structured target rather than free prose. One LLM call
per narrated event.

Why separate this from sourcing:
  Doing claim-detection and citation-finding in a single step makes both
  worse. The model has to juggle "what counts as a claim" alongside
  "which doc supports it" and one will be done poorly. Splitting lets
  each stage have a single, narrow job.

Claim types:
  stat        quantitative facts ("invested $5B", "47 engagements")
  event       discrete occurrences ("met on Feb 14", "signed the MOU")
  attribution someone said / decided / announced something
  date        time references when the date is the core fact
  judgment    evaluative / interpretive statements ("signals a shift")

Inline citations the narrator already attached (the [doc_id] tokens) are
preserved on each claim. Sourcing stage can then either keep, replace,
or supplement them.

Output:
  claims: [
    {claim_id, text, claim_type, source_stage='event_narrator',
     referent_id (event_id), span ('overview'|'outcomes'),
     inline_citations: [<doc_id>...]}
  ]
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent.workflows.base import Stage, StageResult, WorkflowContext

logger = logging.getLogger(__name__)


CLAIM_EXTRACTOR_SYSTEM_PROMPT = """\
You are a claim extractor for an analyst report. Given prose about a
single event, decompose it into atomic factual claims an analyst would
need to verify independently.

Each claim:
  - Is ONE proposition that could be true or false on its own. If a
    sentence contains two facts, split it.
  - Preserves any inline [doc_id] citations from the prose.
  - Has a type:
      stat        quantitative ("X invested $5B in Y")
      event       discrete occurrence ("X and Y signed an MOU")
      attribution someone said / decided ("X announced ...")
      date        time reference when the date is the core fact
      judgment    evaluative / interpretive ("This signals a shift ...")
  - Has a span: "overview" or "outcomes" — which paragraph it came from.

Skip:
  - Filler, transitions, and rhetorical scaffolding
  - Trivial restatements
  - Caveats unless substantive

Output JSON only — no markdown, no code fences:
{
  "claims": [
    {
      "text": "<the claim>",
      "claim_type": "stat|event|attribution|date|judgment",
      "span": "overview|outcomes",
      "inline_citations": ["<doc_id>", ...]
    }
  ]
}
"""


class ClaimExtractorStage(Stage):
    name = "claim_extractor"
    description = "Split narrative prose into atomic claims for downstream sourcing."
    required = True
    depends_on = ["event_narrator"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        narratives = ctx.require("event_narrator").data.get("narratives") or []
        if not narratives:
            return StageResult(
                ok=True,
                data={"claims": []},
                confidence=0.0,
                summary="claim_extractor: no narratives to process",
            )

        try:
            from agent.llm.provider import get_provider, LLMMessage
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"LLM provider unavailable: {e}")

        provider = get_provider()
        all_claims: list[dict[str, Any]] = []
        successes = 0
        failures: list[str] = []
        narrated_events = 0

        for narrative in narratives:
            if not narrative.get("ok"):
                continue
            event_id = narrative.get("event_id")
            overview = narrative.get("overview") or ""
            outcomes = narrative.get("outcomes") or ""
            if not (overview or outcomes):
                continue
            narrated_events += 1

            try:
                claims = _extract_claims_for_event(
                    provider=provider,
                    LLMMessage=LLMMessage,
                    event_id=event_id,
                    event_name=narrative.get("event_name"),
                    overview=overview,
                    outcomes=outcomes,
                )
            except Exception as e:
                logger.exception("claim extraction failed for %s", event_id)
                failures.append(event_id)
                continue

            all_claims.extend(claims)
            successes += 1

        ok = successes > 0 or narrated_events == 0
        confidence = successes / narrated_events if narrated_events > 0 else 0.0

        summary = f"claim_extractor: {len(all_claims)} claims from {successes}/{narrated_events} events"
        notes = [f"{len(failures)} event(s) failed extraction: {failures}"] if failures else []

        return StageResult(
            ok=ok,
            data={"claims": all_claims},
            confidence=confidence,
            summary=summary,
            notes=notes,
            error=None if ok else "all narrated events failed claim extraction",
        )


# ---------------------------------------------------------------------------
# Per-event extraction
# ---------------------------------------------------------------------------

def _extract_claims_for_event(
    *,
    provider,
    LLMMessage,
    event_id: str,
    event_name: str | None,
    overview: str,
    outcomes: str,
) -> list[dict[str, Any]]:
    user_payload = _compose_user_payload(event_name, overview, outcomes)
    messages = [
        LLMMessage(role="system", content=CLAIM_EXTRACTOR_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_payload),
    ]
    response = provider.complete(
        messages=messages,
        tools=None,
        temperature=0.1,
        max_tokens=1200,
    )

    parsed = _parse_json_response(response.text)
    raw_claims = parsed.get("claims") or []

    cleaned: list[dict[str, Any]] = []
    for i, c in enumerate(raw_claims):
        text = (c.get("text") or "").strip()
        if not text:
            continue
        claim_type = (c.get("claim_type") or "judgment").lower()
        if claim_type not in {"stat", "event", "attribution", "date", "judgment"}:
            claim_type = "judgment"
        span = (c.get("span") or "overview").lower()
        if span not in {"overview", "outcomes"}:
            span = "overview"

        # Trust the model's inline_citations only as a hint; re-extract from
        # the claim text itself for ground truth.
        inline = _extract_inline_citations(text)
        if not inline and isinstance(c.get("inline_citations"), list):
            inline = [str(x) for x in c["inline_citations"] if x]

        cleaned.append(
            {
                "claim_id": f"{event_id}::c{i + 1}",
                "text": text,
                "claim_type": claim_type,
                "source_stage": "event_narrator",
                "referent_id": event_id,
                "span": span,
                "inline_citations": list(dict.fromkeys(inline)),
            }
        )

    return cleaned


def _compose_user_payload(event_name: str | None, overview: str, outcomes: str) -> str:
    return (
        f"EVENT: {event_name or '(unnamed)'}\n\n"
        f"OVERVIEW:\n{overview}\n\n"
        f"OUTCOMES:\n{outcomes}\n\n"
        "Extract atomic claims. Output JSON only."
    )


def _parse_json_response(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


_CITATION_RE = re.compile(r"\[([A-Za-z0-9_\-:.]+)\]")


def _extract_inline_citations(text_blob: str) -> list[str]:
    return _CITATION_RE.findall(text_blob or "")


STAGE = ClaimExtractorStage()
