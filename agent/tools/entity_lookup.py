"""Resolve a name or alias to a canonical entity profile.

Queries CanonicalEntity (shared/models/models.py::CanonicalEntity) by
canonical_name or alternative_names (aliases). Read-only. Returns the
best-matching master entities (master_entity_id IS NULL), ranked exact match
first, then by document volume.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_SQL = """
    SELECT id::text                AS canonical_id,
           canonical_name          AS name,
           entity_type::text       AS entity_type,
           primary_role::text      AS primary_role,
           initiating_country,
           country_affiliations,
           alternative_names,
           entity_description,
           total_documents,
           total_mention_days,
           first_mention_date,
           last_mention_date
    FROM canonical_entities
    WHERE master_entity_id IS NULL
      AND (
            lower(canonical_name) = lower(:name)
            OR canonical_name ILIKE :ilike
            OR EXISTS (
                SELECT 1 FROM unnest(alternative_names) a
                WHERE lower(a) = lower(:name) OR a ILIKE :ilike
            )
          )
      {etype_clause}
    ORDER BY (lower(canonical_name) = lower(:name)) DESC,
             total_documents DESC NULLS LAST,
             total_mention_days DESC NULLS LAST
    LIMIT :limit
"""


class EntityLookupTool(Tool):
    name = "entity_lookup"
    description = (
        "Resolve a name or alias to a canonical entity record. Returns the "
        "canonical_id, entity_type, country affiliations, and aliases."
    )
    foundation_dependency = "shared/models/models.py::CanonicalEntity"
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "entity_type": {
                "type": "string",
                "enum": ["person", "organization", "location", "media_figure", "other"],
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5},
        },
        "required": ["name"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        name = (kwargs.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, error="name is required")
        entity_type = kwargs.get("entity_type")
        limit = max(1, min(int(kwargs.get("limit") or 5), 25))

        try:
            from sqlalchemy import text
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        params: dict[str, Any] = {"name": name, "ilike": f"%{name}%", "limit": limit}
        etype_clause = ""
        if entity_type:
            etype_clause = "AND lower(entity_type::text) = lower(:etype)"
            params["etype"] = entity_type
        sql = _SQL.format(etype_clause=etype_clause)

        try:
            with get_session() as session:
                rows = session.execute(text(sql), params).mappings().all()
        except Exception as e:
            logger.exception("entity_lookup query failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        matches = [_shape(r) for r in rows]
        if not matches:
            return ToolResult(
                ok=True, data={"matches": []},
                summary=f"entity_lookup: no match for '{name}'",
            )
        return ToolResult(
            ok=True,
            data={"matches": matches},
            summary=f"entity_lookup: {len(matches)} match(es) for '{name}'; "
            f"top='{matches[0]['name']}'",
        )


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_id": r.get("canonical_id"),
        "name": r.get("name"),
        "entity_type": r.get("entity_type"),
        "primary_role": r.get("primary_role"),
        "initiating_country": r.get("initiating_country"),
        "country_affiliations": list(r.get("country_affiliations") or []),
        "aliases": list(r.get("alternative_names") or []),
        "description": r.get("entity_description"),
        "total_documents": r.get("total_documents"),
        "total_mention_days": r.get("total_mention_days"),
        "first_mention_date": _d(r.get("first_mention_date")),
        "last_mention_date": _d(r.get("last_mention_date")),
    }


def _d(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


TOOL = EntityLookupTool()
