"""Find supporting vs. conflicting documents for a claim or event.

Two steps:
  1. Retrieve semantically similar documents via
     services/chat/rag_service.intelligent_search.
  2. Classify each candidate's stance toward the claim
     (supports / conflicts / unrelated) with a single LLM call, and summarize
     source diversity (distinct sources and countries).

If the LLM is unavailable the tool still returns the retrieved candidates and
the diversity summary, with stance left unclassified — so it degrades to a
plain corroboration retrieval rather than failing.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_STANCE_SYSTEM = (
    "You are a fact-checking assistant. Given a CLAIM and a numbered list of "
    "document snippets, classify each snippet's stance toward the claim. "
    "Respond with STRICT JSON only: "
    '{"stances": [{"n": <int>, "stance": "supports|conflicts|unrelated", '
    '"why": "<one short clause>"}]}. Use \"conflicts\" only when the snippet '
    "directly contradicts the claim; use \"unrelated\" when it neither supports "
    "nor contradicts it."
)


class CorroborationCheckTool(Tool):
    name = "corroboration_check"
    description = (
        "Given a claim or canonical event, return documents that corroborate or "
        "conflict with it, grouped by source diversity."
    )
    foundation_dependency = "services/chat/rag_service.py"
    input_schema = {
        "type": "object",
        "properties": {
            "claim": {"type": "string"},
            "canonical_event_id": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
        },
    }

    def run(self, **kwargs: Any) -> ToolResult:
        claim = (kwargs.get("claim") or "").strip()
        event_id = (kwargs.get("canonical_event_id") or "").strip()
        top_k = max(1, min(int(kwargs.get("top_k") or 15), 50))

        if not claim and event_id:
            claim = self._claim_from_event(event_id)
        if not claim:
            return ToolResult(
                ok=False, error="provide either 'claim' or a resolvable 'canonical_event_id'"
            )

        try:
            from services.chat.rag_service import intelligent_search
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"rag_service unavailable: {e}")

        try:
            results, _meta = intelligent_search(query=claim, k=top_k)
        except Exception as e:
            logger.exception("corroboration retrieval failed")
            return ToolResult(ok=False, error=f"retrieval failed: {e}")

        candidates = [_trim(r) for r in results]
        if not candidates:
            return ToolResult(
                ok=True, data={"claim": claim, "candidates": [], "diversity": {}},
                summary="corroboration_check: no candidate documents found",
            )

        stances = self._classify_stances(claim, candidates)
        for i, cand in enumerate(candidates):
            s = stances.get(i)
            cand["stance"] = s.get("stance") if s else None
            cand["stance_reason"] = s.get("why") if s else None

        diversity = _diversity(candidates)
        tally = _tally_stances(candidates)
        citations = [c["doc_id"] for c in candidates if c.get("doc_id")]
        return ToolResult(
            ok=True,
            data={
                "claim": claim,
                "candidates": candidates,
                "diversity": diversity,
                "stance_tally": tally,
            },
            citations=citations,
            summary=(
                f"corroboration_check: {len(candidates)} docs "
                f"({tally['supports']} support / {tally['conflicts']} conflict / "
                f"{tally['unrelated']} unrelated), {diversity['distinct_sources']} sources"
            ),
        )

    # ----- helpers ------------------------------------------------------

    def _claim_from_event(self, event_id: str) -> str:
        try:
            from sqlalchemy import text
            from shared.database.database import get_session
            with get_session() as session:
                row = session.execute(
                    text(
                        "SELECT canonical_name, consolidated_description "
                        "FROM canonical_events WHERE id::text = :id"
                    ),
                    {"id": event_id},
                ).mappings().first()
        except Exception:
            logger.warning("could not resolve canonical_event_id=%s", event_id, exc_info=True)
            return ""
        if not row:
            return ""
        return (row.get("consolidated_description") or row.get("canonical_name") or "").strip()

    def _classify_stances(
        self, claim: str, candidates: list[dict[str, Any]]
    ) -> dict[int, dict[str, Any]]:
        try:
            from agent.llm.provider import LLMMessage, get_provider
            provider = get_provider()
        except Exception:  # pragma: no cover
            logger.warning("LLM provider unavailable; skipping stance classification")
            return {}

        listing = "\n".join(
            f"{i}. [{c.get('source_name') or 'unknown'}] {c.get('snippet') or ''}"
            for i, c in enumerate(candidates)
        )
        user = f"CLAIM:\n{claim}\n\nSNIPPETS:\n{listing}\n\nClassify each by its index n."
        try:
            resp = provider.complete(
                messages=[
                    LLMMessage(role="system", content=_STANCE_SYSTEM),
                    LLMMessage(role="user", content=user),
                ],
                temperature=0.0,
                max_tokens=900,
            )
            return _parse_stances(resp.text)
        except Exception:
            logger.warning("stance classification failed; returning unclassified", exc_info=True)
            return {}


def _parse_stances(raw: str) -> dict[int, dict[str, Any]]:
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for item in data.get("stances", []):
        try:
            n = int(item["n"])
        except (KeyError, ValueError, TypeError):
            continue
        stance = item.get("stance")
        if stance not in {"supports", "conflicts", "unrelated"}:
            stance = "unrelated"
        out[n] = {"stance": stance, "why": item.get("why")}
    return out


def _trim(r: dict[str, Any]) -> dict[str, Any]:
    content = r.get("content") or ""
    return {
        "doc_id": r.get("doc_id"),
        "title": r.get("title"),
        "source_name": r.get("source_name"),
        "date": r.get("date"),
        "initiating_country": r.get("initiating_country"),
        "recipient_country": r.get("recipient_country"),
        "relevance_score": r.get("relevance_score"),
        "snippet": content if len(content) <= 1200 else content[:1200] + "…",
    }


def _diversity(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    sources = {c.get("source_name") for c in candidates if c.get("source_name")}
    countries = set()
    for c in candidates:
        for key in ("initiating_country", "recipient_country"):
            if c.get(key):
                countries.add(c[key])
    return {
        "distinct_sources": len(sources),
        "distinct_countries": len(countries),
        "sources": sorted(sources),
    }


def _tally_stances(candidates: list[dict[str, Any]]) -> dict[str, int]:
    tally = {"supports": 0, "conflicts": 0, "unrelated": 0, "unclassified": 0}
    for c in candidates:
        stance = c.get("stance")
        tally[stance if stance in tally else "unclassified"] += 1
    return tally


TOOL = CorroborationCheckTool()
