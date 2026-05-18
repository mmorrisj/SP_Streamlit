"""Stage 9: Sourcing — Claims pass.

For every atomic claim from claim_extractor, attach 1-3 doc_ids from the
event's candidate documents. One LLM call per event (batches claims
together) for cost efficiency and consistent reasoning across an event's
claim set.

Candidate documents:
  Same source as event_narrator's _fetch_event_docs, but with a larger
  limit (15 vs 6) — sourcing needs more candidates to find specific
  evidence for specific claims, where the narrator only needed enough
  context to re-frame the existing summary.

Allow-list enforcement:
  cited_doc_ids that don't appear in the candidate set are stripped post-
  LLM (drop, don't trust). Stripped IDs are surfaced in
  hallucinated_doc_ids per claim for the validator stage and analyst review.

Per-claim output:
  claim_id (back-reference to claim_extractor)
  cited_doc_ids   validated subset only
  confidence      LOW | MED | HIGH (from the LLM ranker)
  sourcing_notes  one-line rationale
  hallucinated_doc_ids
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from agent.workflows.base import Stage, StageResult, WorkflowContext
from agent.workflows.report.stages.event_narrator import _fetch_event_docs

logger = logging.getLogger(__name__)

CANDIDATE_DOCS_PER_EVENT = 15
SNIPPET_CHAR_LIMIT = 500

SOURCING_SYSTEM_PROMPT = """\
You are a sourcing agent for an analyst report. You receive a list of
atomic factual claims about one event and a candidate list of source
documents. Attach 1-3 doc_ids to each claim — the best-fit documents
that support that specific claim.

Selection criteria, in order:
  1. Direct relevance — does the document's text support the specific
     fact in the claim? Reject documents that merely touch on the topic.
  2. Specificity — prefer documents that mention the exact numbers,
     dates, or actors named in the claim.
  3. Source quality — prefer named, reputable outlets over aggregators
     or wire repackages.
  4. Recency — for current-state claims, prefer more recent sources.

Hard rules:
  - Use doc_ids EXACTLY as shown in the candidates list — full UUIDs.
    Never abbreviate, shorten, truncate, or split a doc_id.
    Wrong: "0e7f341f". Right: "0e7f341f-1234-5678-90ab-cdef12345678".
  - Only use doc_ids that appear in the provided candidates list. Never
    invent a doc_id.
  - If no candidate truly supports a claim, return an empty
    cited_doc_ids and explain in sourcing_notes. Do not stretch.
  - Most claims need 1-2 citations; only attach 3 when multiple sources
    add distinct corroboration.

Confidence levels:
  HIGH   one or more documents directly attest the exact fact
  MED    documents support the gist but not the exact phrasing
  LOW    documents are adjacent; the citation is best-available, not strong

Output JSON only — no markdown, no code fences:
{
  "sourced_claims": [
    {
      "claim_id": "<claim_id>",
      "cited_doc_ids": ["<doc_id>", ...],
      "confidence": "LOW|MED|HIGH",
      "sourcing_notes": "<one short sentence>"
    }
  ]
}
"""


class SourcingClaimsStage(Stage):
    name = "sourcing_claims"
    description = "Attach best-fit document citations to each extracted claim."
    required = True
    depends_on = ["claim_extractor", "event_prioritizer"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        claims = ctx.require("claim_extractor").data.get("claims") or []
        if not claims:
            return StageResult(
                ok=True,
                data={"sourced_claims": []},
                confidence=0.0,
                summary="sourcing_claims: no claims to source",
            )

        try:
            from shared.database.database import get_session
            from agent.llm.provider import get_provider, LLMMessage
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"runtime layer unavailable: {e}")

        # Group claims by event so we can batch one LLM call per event.
        claims_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in claims:
            event_id = c.get("referent_id")
            if event_id:
                claims_by_event[event_id].append(c)

        provider = get_provider()
        sourced: list[dict[str, Any]] = []
        successes = 0
        failures: list[str] = []
        all_cites: list[str] = []

        for event_id, event_claims in claims_by_event.items():
            try:
                with get_session() as session:
                    candidates = _fetch_event_docs(
                        session, event_id, limit=CANDIDATE_DOCS_PER_EVENT
                    )
            except Exception as e:
                logger.exception("candidate fetch failed for %s", event_id)
                sourced.extend(_failed_sourcing(event_claims, f"candidate fetch failed: {e}"))
                failures.append(event_id)
                continue

            if not candidates:
                sourced.extend(_failed_sourcing(event_claims, "no candidate documents available"))
                failures.append(event_id)
                continue

            try:
                event_sourced = _source_one_event(
                    provider=provider,
                    LLMMessage=LLMMessage,
                    claims=event_claims,
                    candidates=candidates,
                )
            except Exception as e:
                logger.exception("LLM sourcing failed for event %s", event_id)
                sourced.extend(_failed_sourcing(event_claims, f"LLM call failed: {e}"))
                failures.append(event_id)
                continue

            sourced.extend(event_sourced)
            successes += 1
            for s in event_sourced:
                all_cites.extend(s.get("cited_doc_ids") or [])

        total_events = len(claims_by_event)
        ok = successes > 0 or total_events == 0
        confidence = (
            sum(1 for s in sourced if s.get("cited_doc_ids")) / len(sourced)
            if sourced else 0.0
        )
        summary = (
            f"sourcing_claims: {len(sourced)} claims sourced across "
            f"{successes}/{total_events} events"
        )
        notes = [f"{len(failures)} event(s) failed sourcing: {failures}"] if failures else []

        return StageResult(
            ok=ok,
            data={"sourced_claims": sourced},
            confidence=confidence,
            summary=summary,
            citations=list(dict.fromkeys(all_cites)),
            notes=notes,
            error=None if ok else "all events failed claim sourcing",
        )


# ---------------------------------------------------------------------------
# Per-event sourcing
# ---------------------------------------------------------------------------

def _source_one_event(
    *,
    provider,
    LLMMessage,
    claims: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = {d["doc_id"] for d in candidates if d.get("doc_id")}
    user_payload = _compose_user_payload(claims, candidates)

    messages = [
        LLMMessage(role="system", content=SOURCING_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_payload),
    ]
    response = provider.complete(
        messages=messages,
        tools=None,
        temperature=0.1,
        max_tokens=1500,
    )

    parsed = _parse_json_response(response.text)
    raw = parsed.get("sourced_claims") or []
    raw_by_id: dict[str, dict[str, Any]] = {
        str(r.get("claim_id")): r for r in raw if r.get("claim_id")
    }

    out: list[dict[str, Any]] = []
    for claim in claims:
        cid = claim["claim_id"]
        record = raw_by_id.get(cid, {})
        raw_cites = record.get("cited_doc_ids") or []
        validated = [d for d in raw_cites if d in allowed]
        hallucinated = [d for d in raw_cites if d not in allowed]

        confidence = (record.get("confidence") or "LOW").upper()
        if confidence not in {"LOW", "MED", "HIGH"}:
            confidence = "LOW"

        out.append(
            {
                "claim_id": cid,
                "referent_id": claim.get("referent_id"),
                "claim_text": claim["text"],
                "claim_type": claim["claim_type"],
                "cited_doc_ids": list(dict.fromkeys(validated)),
                "hallucinated_doc_ids": hallucinated,
                "confidence": confidence,
                "sourcing_notes": (record.get("sourcing_notes") or "").strip() or None,
                "ok": True,
            }
        )
    return out


def _compose_user_payload(
    claims: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    lines: list[str] = ["CLAIMS TO SOURCE:"]
    for c in claims:
        lines += [
            f"  - claim_id: {c['claim_id']}",
            f"    type: {c['claim_type']}",
            f"    text: {c['text']}",
        ]
        if c.get("inline_citations"):
            lines.append(f"    narrator_inline_citations: {c['inline_citations']}")

    lines += ["", f"CANDIDATE DOCUMENTS ({len(candidates)}, you may only cite these doc_ids):"]
    for d in candidates:
        snippet = (d.get("snippet") or "")[:SNIPPET_CHAR_LIMIT]
        lines += [
            f"  - doc_id: {d['doc_id']}",
            f"    title: {d.get('title') or '-'}",
            f"    source: {d.get('source_name') or '-'}",
            f"    date: {d.get('date') or '-'}",
            f"    snippet: {snippet or '-'}",
        ]

    lines += [
        "",
        "Attach 1-3 doc_ids to each claim per the rules. Output JSON only.",
    ]
    return "\n".join(lines)


def _failed_sourcing(claims: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": c["claim_id"],
            "referent_id": c.get("referent_id"),
            "claim_text": c["text"],
            "claim_type": c["claim_type"],
            "cited_doc_ids": [],
            "hallucinated_doc_ids": [],
            "confidence": "LOW",
            "sourcing_notes": None,
            "ok": False,
            "failure_reason": reason,
        }
        for c in claims
    ]


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


STAGE = SourcingClaimsStage()
