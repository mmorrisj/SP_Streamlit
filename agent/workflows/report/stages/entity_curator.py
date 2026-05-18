"""Stage 10: Entity Curator.

Picks influential entities from the top events, drops generics, and writes
role synopses grounded in the narrator's prose.

Two-pass funnel:
  1. SQL pre-filter — pulls canonical entities tied to the top-N events
     via array intersection on canonical_entities.associated_events.
     Sorted by entity volume (total_documents) and limited to a
     candidate pool (~20).
  2. Heuristic generics drop — strips obvious collective nouns and
     'the X' patterns before paying for LLM tokens. Conservative on
     purpose (false negatives are recoverable; false positives are not).
  3. LLM curates — picks the most influential 5-8 from the survivors,
     drops any remaining generics, and writes a 1-2 sentence role
     synopsis per entity grounded in the supplied event narratives plus
     the entity's stored entity_description.

Output:
    entities: [
        {canonical_id, name, entity_type, country_affiliations,
         role_synopsis, influence_rationale, associated_event_ids,
         total_documents}
    ]
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

from agent.workflows.base import Stage, StageResult, WorkflowContext

logger = logging.getLogger(__name__)

CANDIDATE_LIMIT = 20
TARGET_CURATED_COUNT = 6   # the LLM aims for ~5-8

# Words that signal a name is a collective, not a specific entity.
_GENERIC_TAIL_TOKENS: frozenset[str] = frozenset({
    "companies", "firms", "enterprises", "officials", "leaders",
    "representatives", "delegations", "delegation", "ministries",
    "agencies", "governments", "authorities", "troops", "forces",
    "workers", "investors", "businesses", "institutions",
    "organizations", "partners", "parties", "allies", "powers",
    "states", "regimes", "diplomats", "ambassadors", "ministers",
    "executives", "groups", "coalitions",
})
_GENERIC_NAME_RE = re.compile(r"^\s*the\s+", re.IGNORECASE)


CURATOR_SYSTEM_PROMPT = """\
You are an entity curator for an analyst report. You will receive a list
of candidate entities and the narratives of the top events they appear in.

Your job:
  1. Select the 5-8 most influential entities for this report. Influence
     means they had concrete agency in one or more of the events — they
     made decisions, signed agreements, negotiated, funded, deployed.
     Background mentions and passing references don't count.
  2. Drop generic or collective entities ("Chinese companies",
     "the government", "Western leaders") that aren't specific actors.
     Keep specific organizations even if they sound generic at first
     ("Belt and Road Initiative", "Export-Import Bank of China").
  3. For each selected entity, write a one-or-two-sentence role synopsis
     describing their concrete role and impact in the referenced events.
     Be specific. Name the action, not the category.

Hard rules:
  - Use only the entities in the provided candidates list. Do not invent
    entities. Reference them by canonical_id.
  - Ground every synopsis in the supplied event narratives or the
    entity's stored description. Do not fabricate roles.
  - If fewer than 5 candidates are truly influential, return fewer
    rather than padding with weak picks.

Output JSON only — no markdown, no code fences:
{
  "entities": [
    {
      "canonical_id": "<id>",
      "role_synopsis": "<1-2 sentences naming concrete actions>",
      "influence_rationale": "<one short sentence on why they made the cut>"
    }
  ]
}
"""


class EntityCuratorStage(Stage):
    name = "entity_curator"
    description = "Pick influential entities, drop generics, write role synopses."
    required = False
    depends_on = ["event_prioritizer", "event_narrator"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        prioritized = ctx.require("event_prioritizer").data.get("events") or []
        if not prioritized:
            return StageResult(
                ok=True,
                data={"entities": []},
                confidence=0.0,
                summary="entity_curator: no events to curate from",
            )

        narratives = ctx.require("event_narrator").data.get("narratives") or []
        narrative_by_event = {
            n["event_id"]: n for n in narratives if n.get("event_id")
        }

        event_ids = [e["event_id"] for e in prioritized if e.get("event_id")]
        if not event_ids:
            return StageResult(
                ok=True,
                data={"entities": []},
                confidence=0.0,
                summary="entity_curator: no event IDs to query against",
            )

        try:
            from shared.database.database import get_session
            from agent.llm.provider import get_provider, LLMMessage
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"runtime layer unavailable: {e}")

        try:
            with get_session() as session:
                candidates = _fetch_candidate_entities(session, event_ids, limit=CANDIDATE_LIMIT)
        except Exception as e:
            logger.exception("entity candidate fetch failed")
            return StageResult(ok=False, error=f"candidate fetch failed: {e}")

        filtered = [c for c in candidates if not _is_generic_name(c["name"], c["entity_type"])]

        if not filtered:
            return StageResult(
                ok=True,
                data={"entities": []},
                confidence=0.0,
                summary=f"entity_curator: {len(candidates)} candidates, all generic — none curated",
                notes=[f"dropped as generic: {[c['name'] for c in candidates][:10]}"],
            )

        provider = get_provider()
        try:
            curated = _curate_with_llm(
                provider=provider,
                LLMMessage=LLMMessage,
                candidates=filtered,
                event_ids=event_ids,
                narrative_by_event=narrative_by_event,
            )
        except Exception as e:
            logger.exception("entity curation LLM call failed")
            return StageResult(ok=False, error=f"LLM curation failed: {e}")

        confidence = (
            min(1.0, len(curated) / TARGET_CURATED_COUNT) if filtered else 0.0
        )
        summary = (
            f"entity_curator: {len(curated)} curated from "
            f"{len(filtered)} non-generic candidates ({len(candidates)} raw)"
        )

        return StageResult(
            ok=True,
            data={"entities": curated},
            confidence=confidence,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def _fetch_candidate_entities(
    session, event_ids: list[str], limit: int
) -> list[dict[str, Any]]:
    """Master entities linked to the top event set via shared documents.

    Linkage strategy (verified against live data 2026-05-18):
      - canonical_entities.associated_events: unpopulated for this corpus.
      - daily_entity_mentions.associated_event_ids: also unpopulated.
      - canonical_events.entities_mentioned (JSONB): also empty.

    The only reliable bridge is documents: both daily_event_mentions and
    daily_entity_mentions carry doc_ids arrays, and an entity is "in
    scope" if any of its mentions share a document with any of the top
    events. event_id arrives as a string list from event_prioritizer;
    cast canonical_event_id to text for the comparison.
    """
    sql = """
        WITH event_docs AS (
            SELECT
                dem.canonical_event_id::text AS event_id,
                unnest(dem.doc_ids)          AS doc_id
            FROM daily_event_mentions dem
            WHERE dem.canonical_event_id::text = ANY(:event_ids)
        ),
        entity_links AS (
            SELECT
                dey.canonical_entity_id              AS entity_id,
                array_agg(DISTINCT ed.event_id)       AS in_scope_events,
                COUNT(DISTINCT ed.doc_id)             AS in_scope_doc_count
            FROM daily_entity_mentions dey
            JOIN event_docs ed ON ed.doc_id = ANY(dey.doc_ids)
            GROUP BY dey.canonical_entity_id
        )
        SELECT
            ce.id::text                     AS canonical_id,
            ce.canonical_name               AS name,
            ce.entity_type                  AS entity_type,
            ce.initiating_country           AS initiating_country,
            ce.country_affiliations         AS country_affiliations,
            ce.alternative_names            AS alternative_names,
            ce.entity_description           AS entity_description,
            ce.primary_role                 AS primary_role,
            ce.total_documents              AS total_documents,
            ce.total_mention_days           AS total_mention_days,
            el.in_scope_events              AS in_scope_events,
            el.in_scope_doc_count           AS in_scope_doc_count
        FROM canonical_entities ce
        JOIN entity_links el ON el.entity_id = ce.id
        WHERE ce.master_entity_id IS NULL
        ORDER BY
            el.in_scope_doc_count DESC,
            ce.total_documents DESC NULLS LAST,
            ce.total_mention_days DESC NULLS LAST
        LIMIT :limit
    """
    # Explicit ARRAY(String) binding: without it SQLAlchemy/psycopg passes
    # the Python list to ANY(:event_ids) in a form Postgres treats as
    # zero-element-matching. Verified against live data 2026-05-18: the
    # same SQL with hardcoded IN(...) returns 16 entities; the list-bound
    # version returned 0.
    stmt = text(sql).bindparams(
        bindparam("event_ids", type_=ARRAY(String)),
    )
    rows = session.execute(
        stmt, {"event_ids": event_ids, "limit": limit}
    ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        in_scope = list(r.in_scope_events or [])
        out.append(
            {
                "canonical_id": r.canonical_id,
                "name": r.name,
                "entity_type": _enum_value(r.entity_type),
                "initiating_country": r.initiating_country,
                "country_affiliations": list(r.country_affiliations or []),
                "alternative_names": list(r.alternative_names or []),
                "entity_description": r.entity_description,
                "primary_role": _enum_value(r.primary_role),
                "total_documents": int(r.total_documents or 0),
                "total_mention_days": int(r.total_mention_days or 0),
                "associated_event_ids_in_scope": in_scope,
                "event_overlap_count": len(in_scope),
                "in_scope_doc_count": int(r.in_scope_doc_count or 0),
            }
        )
    return out


def _enum_value(v: Any) -> str | None:
    if v is None:
        return None
    return getattr(v, "value", None) or str(v)


# ---------------------------------------------------------------------------
# Heuristic generics drop
# ---------------------------------------------------------------------------

def _is_generic_name(name: str, entity_type: str | None) -> bool:
    """Lightweight pre-filter; LLM has the final say.

    Catches the obvious cases ('Chinese companies', 'the government') so
    the LLM doesn't waste tokens on them. Deliberately conservative:
    when in doubt, KEEP the entity and let the LLM judge."""
    if not name:
        return True
    cleaned = name.strip()
    if _GENERIC_NAME_RE.match(cleaned):
        return True
    tokens = re.findall(r"[A-Za-z]+", cleaned)
    if not tokens:
        return True
    last = tokens[-1].lower()
    if last in _GENERIC_TAIL_TOKENS:
        return True
    # Locations that are bare country names: country is already the report's
    # scope, so dropping them avoids redundant 'China' entity entries.
    if entity_type == "location" and len(tokens) == 1:
        return True
    return False


# ---------------------------------------------------------------------------
# LLM curation
# ---------------------------------------------------------------------------

def _curate_with_llm(
    *,
    provider,
    LLMMessage,
    candidates: list[dict[str, Any]],
    event_ids: list[str],
    narrative_by_event: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    user_payload = _compose_user_payload(candidates, event_ids, narrative_by_event)

    messages = [
        LLMMessage(role="system", content=CURATOR_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_payload),
    ]
    response = provider.complete(
        messages=messages,
        tools=None,
        temperature=0.2,
        max_tokens=1500,
    )

    parsed = _parse_json_response(response.text)
    raw = parsed.get("entities") or []

    by_id = {c["canonical_id"]: c for c in candidates}
    out: list[dict[str, Any]] = []
    for r in raw:
        cid = str(r.get("canonical_id") or "")
        candidate = by_id.get(cid)
        if not candidate:
            continue  # drop hallucinated entities
        role = (r.get("role_synopsis") or "").strip()
        why = (r.get("influence_rationale") or "").strip()
        if not role:
            continue
        out.append(
            {
                "canonical_id": cid,
                "name": candidate["name"],
                "entity_type": candidate["entity_type"],
                "primary_role": candidate["primary_role"],
                "country_affiliations": candidate["country_affiliations"],
                "alternative_names": candidate["alternative_names"],
                "role_synopsis": role,
                "influence_rationale": why or None,
                "associated_event_ids": candidate["associated_event_ids_in_scope"],
                "total_documents": candidate["total_documents"],
            }
        )
    return out


def _compose_user_payload(
    candidates: list[dict[str, Any]],
    event_ids: list[str],
    narrative_by_event: dict[str, dict[str, Any]],
) -> str:
    lines: list[str] = ["CANDIDATE ENTITIES:"]
    for c in candidates:
        lines += [
            f"  - canonical_id: {c['canonical_id']}",
            f"    name: {c['name']}",
            f"    type: {c['entity_type']}",
            f"    primary_role: {c.get('primary_role') or '-'}",
            f"    country_affiliations: {', '.join(c['country_affiliations']) or '-'}",
            f"    appears_in_events: {len(c['associated_event_ids_in_scope'])} of {len(event_ids)} top events",
            f"    total_documents: {c['total_documents']}",
        ]
        if c.get("entity_description"):
            desc = c["entity_description"][:400]
            lines.append(f"    description: {desc}")
        if c.get("alternative_names"):
            lines.append(f"    aliases: {c['alternative_names'][:5]}")

    lines += ["", "EVENT NARRATIVES (for grounding):"]
    for eid in event_ids:
        n = narrative_by_event.get(eid)
        if not n or not n.get("ok"):
            continue
        lines += [
            f"  - event_id: {eid}",
            f"    event_name: {n.get('event_name')}",
            f"    overview: {(n.get('overview') or '')[:400]}",
            f"    outcomes: {(n.get('outcomes') or '')[:400]}",
        ]

    lines += [
        "",
        "Select 5-8 most influential, drop generics, write role synopses.",
        "Output JSON only.",
    ]
    return "\n".join(lines)


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


STAGE = EntityCuratorStage()
