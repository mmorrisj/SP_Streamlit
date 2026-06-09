"""Synthesize gathered evidence into a structured analyst briefing.

LLM-driven: composes the Briefing schema (agent/schemas.py) from evidence,
entities, and timeline the orchestrator has already gathered via other tools.
Returns the briefing as a JSON-serializable dict. Uses the provider configured
in agent/llm/provider.py.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are an OSINT analyst composing a structured briefing for a senior reader,
synthesizing ONLY the evidence, entities, and timeline provided. Do not invent
doc_ids, dates, or facts. If the evidence is thin, say so in information_gaps.

Respond with STRICT JSON only — no prose, no code fences — matching:

{
  "title": "<short title>",
  "executive_summary": "<3-5 sentences>",
  "key_judgments": [{"judgment": "<claim>", "confidence": "LOW|MED|HIGH"}],
  "timeline": [{"timestamp": "<ISO date>", "event": "<desc>", "source_ids": ["<doc_id>"]}],
  "key_entities": [{"name": "<entity>", "entity_type": "person|organization|location", "role": "<role>"}],
  "evidence": [{"source_id": "<doc_id>", "title": "<title>", "snippet": "<short>"}],
  "confidence_assessment": "<paragraph>",
  "information_gaps": ["<gap>"],
  "recommended_followup": ["<step>"]
}
"""

_BRIEFING_KEYS = (
    "title", "executive_summary", "key_judgments", "timeline", "key_entities",
    "evidence", "confidence_assessment", "information_gaps", "recommended_followup",
)


class BriefingGeneratorTool(Tool):
    name = "briefing_generator"
    description = (
        "Synthesize gathered evidence, entities, and timeline into a structured "
        "analyst briefing with key judgments, confidence, gaps, and follow-ups."
    )
    foundation_dependency = "agent/llm/provider.py"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "object"}},
            "entities": {"type": "array", "items": {"type": "object"}},
            "timeline": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["query"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query is required")

        evidence = kwargs.get("evidence") or []
        entities = kwargs.get("entities") or []
        timeline = kwargs.get("timeline") or []

        try:
            from agent.llm.provider import LLMMessage, get_provider
            provider = get_provider()
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"LLM provider unavailable: {e}")

        user = (
            f"ANALYST QUESTION:\n{query}\n\n"
            f"EVIDENCE (JSON):\n{json.dumps(evidence, default=str)[:12000]}\n\n"
            f"ENTITIES (JSON):\n{json.dumps(entities, default=str)[:4000]}\n\n"
            f"TIMELINE (JSON):\n{json.dumps(timeline, default=str)[:4000]}\n\n"
            "Compose the briefing as STRICT JSON per the schema."
        )

        try:
            resp = provider.complete(
                messages=[
                    LLMMessage(role="system", content=_SYSTEM),
                    LLMMessage(role="user", content=user),
                ],
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception as e:
            logger.exception("briefing_generator LLM call failed")
            return ToolResult(ok=False, error=f"LLM call failed: {e}")

        briefing = _parse_briefing(resp.text, fallback_title=query)
        citations = [
            e.get("source_id") for e in briefing.get("evidence", [])
            if isinstance(e, dict) and e.get("source_id")
        ]
        return ToolResult(
            ok=True,
            data={"briefing": briefing},
            citations=citations,
            summary=f"briefing_generator: '{briefing.get('title')}' "
            f"({len(briefing.get('key_judgments', []))} judgments)",
        )


def _parse_briefing(raw: str, fallback_title: str) -> dict[str, Any]:
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    parsed: dict[str, Any] | None = None
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            parsed = None

    if parsed is None:
        # Model returned prose; wrap it as the executive summary so the caller
        # still gets a well-formed briefing.
        return {
            "title": fallback_title[:120],
            "executive_summary": text or "(no briefing produced)",
            "key_judgments": [], "timeline": [], "key_entities": [], "evidence": [],
            "confidence_assessment": None, "information_gaps": [], "recommended_followup": [],
        }

    out: dict[str, Any] = {}
    for key in _BRIEFING_KEYS:
        out[key] = parsed.get(key)
    out["title"] = out.get("title") or fallback_title[:120]
    out["executive_summary"] = out.get("executive_summary") or ""
    for list_key in ("key_judgments", "timeline", "key_entities", "evidence",
                     "information_gaps", "recommended_followup"):
        if not isinstance(out.get(list_key), list):
            out[list_key] = []
    return out


TOOL = BriefingGeneratorTool()
