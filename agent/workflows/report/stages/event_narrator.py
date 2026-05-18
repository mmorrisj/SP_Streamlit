"""Stage 7: Event Narrator.

For each top-priority event from event_prioritizer, fetch context and ask
an LLM to draft a re-framed overview + outcomes for THIS report's scope.

Context strategy (cheapest-and-best-grounded first):
  1. Pull the highest-period event_summary tied to canonical_event_id —
     monthly/yearly summaries already have grounded LLM narratives the
     publication workflow produced. Reuse that as primary context.
  2. Supplement with the most recent source documents (title, source,
     date, distilled snippet) from daily_event_mentions.doc_ids so the
     narrator can cite specific doc_ids.
  3. If no event_summary exists, fall back to source docs alone.

The narrator's job is RE-FRAMING for the analyst's scope, not generating
from scratch. Grounding is enforced via an explicit allow-list of doc_ids
in the context and a post-LLM hallucination check (cited_doc_ids that
weren't in the context are stripped).

Per-event LLM call: ~5k input tokens, ~500 output tokens. Sequential
for v1; parallelizing across events is straightforward in a follow-up.

Output:
    narratives: [
        {event_id, event_name, overview, outcomes,
         cited_doc_ids, hallucinated_doc_ids, used_existing_summary,
         context_doc_count}
    ]
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text

from agent.workflows.base import Stage, StageResult, WorkflowContext

logger = logging.getLogger(__name__)

# Per-event context budgets.
MAX_SOURCE_DOCS_PER_EVENT = 6
SNIPPET_CHAR_LIMIT = 600

NARRATOR_SYSTEM_PROMPT = """\
You are an event narrator drafting one section of a soft-power analyst report.

You will receive context about a single event: an existing narrative summary
(if available) and a set of source documents. Your job is to produce a
focused overview + outcomes for THIS report's scope.

Rules:
  - Stay grounded. Use only facts present in the supplied context.
  - Cite source documents inline using bracketed doc_ids: [doc_id]
  - Cite doc_ids using their FULL UUID exactly as shown in the sources
    list. Never abbreviate, shorten, truncate, or split doc_ids.
    Wrong: [0e7f341f]. Right: [0e7f341f-1234-5678-90ab-cdef12345678]
  - Only cite doc_ids that appear in the provided sources list. Never
    invent a doc_id.
  - Overview: 3-5 sentences. What happened, who was involved, when, where.
  - Outcomes: 2-4 sentences. What changed, what's still in motion, what
    secondary effects emerged.
  - Be specific. Name actors, give dates, cite amounts.
  - Skip caveats unless they're substantive.

Output JSON only — no prose, no code fences, no markdown:
{
  "overview": "<3-5 sentences with inline [doc_id] citations>",
  "outcomes": "<2-4 sentences with inline [doc_id] citations>",
  "cited_doc_ids": ["<every doc_id you cited, deduplicated>"]
}
"""


class EventNarratorStage(Stage):
    name = "event_narrator"
    description = "Draft overview + outcomes narrative for each top-priority event."
    required = True
    depends_on = ["event_prioritizer"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        intent = ctx.require("query_interpreter").data
        prioritized = ctx.require("event_prioritizer").data
        events = prioritized.get("events") or []

        if not events:
            return StageResult(
                ok=True,
                data={"narratives": []},
                confidence=0.0,
                summary="event_narrator: no events to narrate",
                notes=["upstream produced 0 events; skipping LLM calls"],
            )

        try:
            from shared.database.database import get_session
            from agent.llm.provider import get_provider, LLMMessage
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"runtime layer unavailable: {e}")

        provider = get_provider()
        narratives: list[dict[str, Any]] = []
        successes = 0
        failures: list[str] = []

        for event in events:
            event_id = event.get("event_id")
            if not event_id:
                failures.append("missing event_id in prioritized event")
                continue

            try:
                with get_session() as session:
                    context = _fetch_event_context(session, event_id)
            except Exception as e:
                logger.exception("event context fetch failed for %s", event_id)
                narratives.append(_failed_narrative(event, f"context fetch failed: {e}"))
                failures.append(event_id)
                continue

            if not context["allowed_doc_ids"] and not context["existing_narrative"]:
                # Nothing to ground on — flag, don't hallucinate.
                narratives.append(_failed_narrative(
                    event,
                    "no source documents or existing narrative available",
                ))
                failures.append(event_id)
                continue

            try:
                result = _narrate_one(
                    provider=provider,
                    LLMMessage=LLMMessage,
                    analyst_query=_compose_analyst_query(intent),
                    event=event,
                    context=context,
                )
            except Exception as e:
                logger.exception("LLM narration failed for %s", event_id)
                narratives.append(_failed_narrative(event, f"LLM call failed: {e}"))
                failures.append(event_id)
                continue

            narratives.append(result)
            successes += 1

        ok = successes > 0
        total = len(events)
        confidence = successes / total if total > 0 else 0.0
        summary = f"event_narrator: {successes}/{total} narrated"
        if failures:
            summary += f" ({len(failures)} failed)"

        all_citations: list[str] = []
        for n in narratives:
            all_citations.extend(n.get("cited_doc_ids") or [])

        return StageResult(
            ok=ok,
            data={"narratives": narratives},
            confidence=confidence,
            summary=summary,
            citations=list(dict.fromkeys(all_citations)),
            notes=[f"{len(failures)} event(s) failed: {failures}"] if failures else [],
            error=None if ok else "all events failed to narrate",
        )


# ---------------------------------------------------------------------------
# Context fetch
# ---------------------------------------------------------------------------

def _fetch_event_context(session, event_id: str) -> dict[str, Any]:
    """Pull existing narrative (if any) + recent source docs for one event."""
    existing = _fetch_best_event_summary(session, event_id)
    docs = _fetch_event_docs(session, event_id, limit=MAX_SOURCE_DOCS_PER_EVENT)
    allowed = [d["doc_id"] for d in docs if d.get("doc_id")]
    return {
        "existing_narrative": existing,
        "source_docs": docs,
        "allowed_doc_ids": allowed,
    }


def _fetch_best_event_summary(session, canonical_event_id: str) -> dict[str, Any] | None:
    """Return the highest-period event_summary tied to this canonical event.

    Period ordering: yearly > monthly > weekly > daily. Within the same
    period type, prefer the most recent."""
    sql = """
        SELECT
            period_type,
            period_start,
            period_end,
            overall_summary,
            outcomes_summary
        FROM event_summaries
        WHERE canonical_event_id = :event_id
          AND is_deleted = FALSE
          AND (overall_summary IS NOT NULL OR outcomes_summary IS NOT NULL)
        ORDER BY
            CASE period_type
                WHEN 'YEARLY'  THEN 1
                WHEN 'MONTHLY' THEN 2
                WHEN 'WEEKLY'  THEN 3
                WHEN 'DAILY'   THEN 4
                ELSE 5
            END,
            period_end DESC
        LIMIT 1
    """
    row = session.execute(text(sql), {"event_id": canonical_event_id}).first()
    if row is None:
        return None
    return {
        "period_type": str(row.period_type),
        "period_start": str(row.period_start) if row.period_start else None,
        "period_end": str(row.period_end) if row.period_end else None,
        "overall_summary": row.overall_summary,
        "outcomes_summary": row.outcomes_summary,
    }


def _fetch_event_docs(session, canonical_event_id: str, limit: int) -> list[dict[str, Any]]:
    """Recent source documents for this event, via daily_event_mentions.doc_ids."""
    sql = """
        SELECT DISTINCT ON (d.doc_id)
            d.doc_id,
            d.title,
            d.source_name,
            d.date,
            d.distilled_text
        FROM daily_event_mentions dem
        JOIN documents d ON d.doc_id = ANY(dem.doc_ids)
        WHERE dem.canonical_event_id = :event_id
        ORDER BY d.doc_id, d.date DESC
        LIMIT :limit
    """
    rows = session.execute(text(sql), {"event_id": canonical_event_id, "limit": limit}).fetchall()
    docs: list[dict[str, Any]] = []
    for r in rows:
        snippet = (r.distilled_text or "")[:SNIPPET_CHAR_LIMIT]
        docs.append(
            {
                "doc_id": r.doc_id,
                "title": r.title,
                "source_name": r.source_name,
                "date": str(r.date) if r.date else None,
                "snippet": snippet,
            }
        )
    return docs


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _narrate_one(
    *,
    provider,
    LLMMessage,
    analyst_query: str,
    event: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    user_payload = _compose_user_payload(analyst_query, event, context)

    messages = [
        LLMMessage(role="system", content=NARRATOR_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_payload),
    ]
    response = provider.complete(
        messages=messages,
        tools=None,
        temperature=0.2,
        max_tokens=900,
    )

    parsed = _parse_narrator_response(response.text)
    overview = (parsed.get("overview") or "").strip()
    outcomes = (parsed.get("outcomes") or "").strip()
    claimed_cites = parsed.get("cited_doc_ids") or []

    # Hallucination check: keep only doc_ids that were in the allow-list.
    allowed = set(context["allowed_doc_ids"])
    actual_cites = [c for c in _extract_inline_citations(overview + " " + outcomes) if c in allowed]
    hallucinated = [c for c in claimed_cites if c not in allowed]

    return {
        "event_id": event.get("event_id"),
        "event_name": event.get("event_name"),
        "overview": overview,
        "outcomes": outcomes,
        "cited_doc_ids": list(dict.fromkeys(actual_cites)),
        "hallucinated_doc_ids": hallucinated,
        "used_existing_summary": context["existing_narrative"] is not None,
        "context_doc_count": len(context["source_docs"]),
        "ok": bool(overview or outcomes),
    }


def _compose_analyst_query(intent: dict[str, Any]) -> str:
    parts = [f"Report scope: {intent.get('scope')}."]
    if intent.get("influencer"):
        parts.append(f"Influencer: {intent['influencer']}.")
    if intent.get("recipient"):
        parts.append(f"Recipient: {intent['recipient']}.")
    if intent.get("region"):
        parts.append(f"Region: {intent['region']}.")
    parts.append(f"Date range: {intent.get('start_date')} to {intent.get('end_date')}.")
    return " ".join(parts)


def _compose_user_payload(
    analyst_query: str,
    event: dict[str, Any],
    context: dict[str, Any],
) -> str:
    """Flatten the context into a single user message for the narrator."""
    lines: list[str] = [
        f"ANALYST QUERY: {analyst_query}",
        "",
        "EVENT:",
        f"  event_id: {event.get('event_id')}",
        f"  event_name: {event.get('event_name')}",
        f"  date_span: {event.get('date_span')}",
        f"  initiating_country: {event.get('initiating_country')}",
        f"  categories: {', '.join(event.get('categories') or []) or '-'}",
        f"  materiality_score: {event.get('materiality_score')}",
        f"  coverage (articles): {event.get('coverage_score')}",
        f"  story_phase: {event.get('story_phase')}",
    ]

    existing = context.get("existing_narrative")
    if existing:
        lines += [
            "",
            f"EXISTING NARRATIVE (period: {existing.get('period_type')}, "
            f"{existing.get('period_start')} to {existing.get('period_end')}):",
            f"  overall: {existing.get('overall_summary') or '-'}",
            f"  outcomes: {existing.get('outcomes_summary') or '-'}",
        ]
    else:
        lines += ["", "EXISTING NARRATIVE: none available"]

    docs = context.get("source_docs") or []
    if docs:
        lines += ["", f"SOURCE DOCUMENTS ({len(docs)} most recent, you may cite these doc_ids):"]
        for d in docs:
            lines += [
                f"  - doc_id: {d['doc_id']}",
                f"    title: {d.get('title') or '-'}",
                f"    source: {d.get('source_name') or '-'}",
                f"    date: {d.get('date') or '-'}",
                f"    snippet: {d.get('snippet') or '-'}",
            ]
    else:
        lines += ["", "SOURCE DOCUMENTS: none available"]

    lines += [
        "",
        "Produce overview + outcomes for this event, re-framed for the analyst's scope.",
        "Output JSON only.",
    ]
    return "\n".join(lines)


def _parse_narrator_response(text_response: str) -> dict[str, Any]:
    """Tolerate code fences and surrounding prose; return the first JSON object."""
    if not text_response:
        return {}
    cleaned = text_response.strip()
    if cleaned.startswith("```"):
        # strip a leading fence if the model ignored the no-fences rule
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


def _failed_narrative(event: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "event_name": event.get("event_name"),
        "overview": "",
        "outcomes": "",
        "cited_doc_ids": [],
        "hallucinated_doc_ids": [],
        "used_existing_summary": False,
        "context_doc_count": 0,
        "ok": False,
        "failure_reason": reason,
    }


STAGE = EventNarratorStage()
