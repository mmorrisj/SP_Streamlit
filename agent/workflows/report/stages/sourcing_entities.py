"""Stage 11: Sourcing — Entities pass.

For each curated entity, attach 1-3 doc_ids that substantiate the role
synopsis. Mirrors sourcing_claims but per-entity instead of per-event.

Candidate documents:
  Pulled from daily_entity_mentions.doc_ids for the canonical_entity_id,
  joined to documents for title / source / date / snippet. Limited to
  CANDIDATE_DOCS_PER_ENTITY most-recent distinct docs.

Allow-list enforcement:
  cited_doc_ids not in the candidate set are stripped post-LLM and
  surfaced as hallucinated_doc_ids per entity.

One LLM call per entity. Per-entity failures isolated; stage as a whole
only fails if every entity fails.

Output:
  sourced_entities: [
    {canonical_id, name, role_synopsis (echoed), cited_doc_ids,
     hallucinated_doc_ids, confidence (LOW|MED|HIGH), sourcing_notes,
     ok, failure_reason?}
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

CANDIDATE_DOCS_PER_ENTITY = 15
SNIPPET_CHAR_LIMIT = 500

SOURCING_SYSTEM_PROMPT = """\
You are a sourcing agent for an analyst report. You receive one entity's
role synopsis and a list of candidate source documents. Attach 1-3
doc_ids from the candidates that best substantiate the synopsis.

Selection criteria, in order:
  1. Direct relevance — does the document text actually attest to the
     role / impact described in the synopsis?
  2. Specificity — prefer documents that name the entity and describe
     concrete actions, not just passing mentions.
  3. Source quality — prefer named, reputable outlets over aggregators.
  4. Recency — prefer more recent sources for current-state assertions.

Hard rules:
  - Only use doc_ids that appear in the provided candidates list. Never
    invent a doc_id.
  - If no candidate substantiates the synopsis, return empty
    cited_doc_ids and explain in sourcing_notes.
  - Most entities need 1-2 citations; only use 3 when distinct sources
    add corroboration.

Confidence levels:
  HIGH   one or more documents directly attest the entity's role
  MED    documents support the gist but not the exact role framing
  LOW    documents are adjacent; the citation is best-available

Output JSON only — no markdown, no code fences:
{
  "cited_doc_ids": ["<doc_id>", ...],
  "confidence": "LOW|MED|HIGH",
  "sourcing_notes": "<one short sentence>"
}
"""


class SourcingEntitiesStage(Stage):
    name = "sourcing_entities"
    description = "Attach best-fit document citations to each curated entity synopsis."
    required = False
    depends_on = ["entity_curator"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        curated = ctx.get("entity_curator")
        entities = (curated.data.get("entities") if curated and curated.ok else []) or []
        if not entities:
            return StageResult(
                ok=True,
                data={"sourced_entities": []},
                confidence=0.0,
                summary="sourcing_entities: no curated entities to source",
            )

        try:
            from shared.database.database import get_session
            from agent.llm.provider import get_provider, LLMMessage
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"runtime layer unavailable: {e}")

        provider = get_provider()
        sourced: list[dict[str, Any]] = []
        successes = 0
        failures: list[str] = []
        all_cites: list[str] = []

        for entity in entities:
            cid = entity.get("canonical_id")
            if not cid:
                continue

            try:
                with get_session() as session:
                    candidates = _fetch_entity_docs(
                        session, cid, limit=CANDIDATE_DOCS_PER_ENTITY
                    )
            except Exception as e:
                logger.exception("doc fetch failed for entity %s", cid)
                sourced.append(_failed(entity, f"candidate fetch failed: {e}"))
                failures.append(cid)
                continue

            if not candidates:
                sourced.append(_failed(entity, "no candidate documents available"))
                failures.append(cid)
                continue

            try:
                record = _source_one_entity(
                    provider=provider,
                    LLMMessage=LLMMessage,
                    entity=entity,
                    candidates=candidates,
                )
            except Exception as e:
                logger.exception("LLM sourcing failed for entity %s", cid)
                sourced.append(_failed(entity, f"LLM call failed: {e}"))
                failures.append(cid)
                continue

            sourced.append(record)
            successes += 1
            all_cites.extend(record.get("cited_doc_ids") or [])

        total = len(entities)
        ok = successes > 0 or total == 0
        confidence = (
            sum(1 for s in sourced if s.get("cited_doc_ids")) / len(sourced)
            if sourced else 0.0
        )
        summary = f"sourcing_entities: {successes}/{total} entities sourced"
        notes = [f"{len(failures)} entity(ies) failed sourcing: {failures}"] if failures else []

        return StageResult(
            ok=ok,
            data={"sourced_entities": sourced},
            confidence=confidence,
            summary=summary,
            citations=list(dict.fromkeys(all_cites)),
            notes=notes,
            error=None if ok else "all entities failed sourcing",
        )


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def _fetch_entity_docs(
    session, canonical_entity_id: str, limit: int
) -> list[dict[str, Any]]:
    sql = """
        SELECT DISTINCT ON (d.doc_id)
            d.doc_id,
            d.title,
            d.source_name,
            d.date,
            d.distilled_text
        FROM daily_entity_mentions dem
        JOIN documents d ON d.doc_id = ANY(dem.doc_ids)
        WHERE dem.canonical_entity_id = :entity_id
        ORDER BY d.doc_id, d.date DESC
        LIMIT :limit
    """
    rows = session.execute(
        text(sql), {"entity_id": canonical_entity_id, "limit": limit}
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        snippet = (r.distilled_text or "")[:SNIPPET_CHAR_LIMIT]
        out.append(
            {
                "doc_id": r.doc_id,
                "title": r.title,
                "source_name": r.source_name,
                "date": str(r.date) if r.date else None,
                "snippet": snippet,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-entity LLM call
# ---------------------------------------------------------------------------

def _source_one_entity(
    *,
    provider,
    LLMMessage,
    entity: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed = {d["doc_id"] for d in candidates if d.get("doc_id")}
    user_payload = _compose_user_payload(entity, candidates)

    messages = [
        LLMMessage(role="system", content=SOURCING_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_payload),
    ]
    response = provider.complete(
        messages=messages,
        tools=None,
        temperature=0.1,
        max_tokens=600,
    )

    parsed = _parse_json_response(response.text)
    raw_cites = parsed.get("cited_doc_ids") or []
    validated = [d for d in raw_cites if d in allowed]
    hallucinated = [d for d in raw_cites if d not in allowed]

    confidence = (parsed.get("confidence") or "LOW").upper()
    if confidence not in {"LOW", "MED", "HIGH"}:
        confidence = "LOW"

    notes = (parsed.get("sourcing_notes") or "").strip() or None

    return {
        "canonical_id": entity["canonical_id"],
        "name": entity["name"],
        "entity_type": entity["entity_type"],
        "role_synopsis": entity["role_synopsis"],
        "cited_doc_ids": list(dict.fromkeys(validated)),
        "hallucinated_doc_ids": hallucinated,
        "confidence": confidence,
        "sourcing_notes": notes,
        "ok": True,
    }


def _compose_user_payload(
    entity: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        "ENTITY TO SOURCE:",
        f"  canonical_id: {entity['canonical_id']}",
        f"  name: {entity['name']}",
        f"  type: {entity.get('entity_type')}",
        f"  primary_role: {entity.get('primary_role') or '-'}",
        f"  role_synopsis: {entity['role_synopsis']}",
    ]
    if entity.get("influence_rationale"):
        lines.append(f"  influence_rationale: {entity['influence_rationale']}")

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
        "Attach 1-3 doc_ids that substantiate the role_synopsis. Output JSON only.",
    ]
    return "\n".join(lines)


def _failed(entity: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "canonical_id": entity["canonical_id"],
        "name": entity["name"],
        "entity_type": entity["entity_type"],
        "role_synopsis": entity["role_synopsis"],
        "cited_doc_ids": [],
        "hallucinated_doc_ids": [],
        "confidence": "LOW",
        "sourcing_notes": None,
        "ok": False,
        "failure_reason": reason,
    }


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


STAGE = SourcingEntitiesStage()
