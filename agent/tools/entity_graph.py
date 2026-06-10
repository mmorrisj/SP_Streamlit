"""Return N-hop neighbors and relationships for an entity.

Queries EntityRelationship (shared/models/models.py::EntityRelationship),
which is undirected co-occurrence (entity_from_id / entity_to_id) weighted by
co_occurrence_count. Default 1-hop; supports up to 3 hops via breadth-first
expansion with co-occurrence thresholding and optional relationship-type
filtering. Read-only.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

# Per-hop fan-out cap so a high-degree node can't explode the traversal.
_MAX_EDGES_PER_HOP = 200

_SQL = """
    SELECT er.entity_from_id::text     AS from_id,
           er.entity_to_id::text       AS to_id,
           er.relationship_type        AS relationship_type,
           er.co_occurrence_count      AS weight,
           er.relationship_description AS description,
           ef.canonical_name           AS from_name,
           et.canonical_name           AS to_name,
           ef.entity_type::text        AS from_type,
           et.entity_type::text        AS to_type
    FROM entity_relationships er
    JOIN canonical_entities ef ON ef.id = er.entity_from_id
    JOIN canonical_entities et ON et.id = er.entity_to_id
    WHERE (er.entity_from_id::text = ANY(:ids)
           OR er.entity_to_id::text = ANY(:ids))
      AND er.co_occurrence_count >= :minco
      {type_clause}
    ORDER BY er.co_occurrence_count DESC
    LIMIT :hop_limit
"""


class EntityGraphTool(Tool):
    name = "entity_graph"
    description = (
        "Return related entities and relationships for a canonical entity. "
        "Supports N-hop traversal and co-occurrence filtering."
    )
    foundation_dependency = "shared/models/models.py::EntityRelationship"
    input_schema = {
        "type": "object",
        "properties": {
            "canonical_id": {"type": "string"},
            "hops": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
            "min_cooccurrences": {"type": "integer", "minimum": 1, "default": 2},
            "relationship_types": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["canonical_id"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        root = (kwargs.get("canonical_id") or "").strip()
        if not root:
            return ToolResult(ok=False, error="canonical_id is required")
        hops = max(1, min(int(kwargs.get("hops") or 1), 3))
        minco = max(1, int(kwargs.get("min_cooccurrences") or 2))
        rel_types = kwargs.get("relationship_types") or None

        try:
            from sqlalchemy import bindparam, text
            from sqlalchemy.dialects.postgresql import ARRAY
            from sqlalchemy.types import String as SAString
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"database unavailable: {e}")

        type_clause = "AND er.relationship_type = ANY(:rtypes)" if rel_types else ""
        sql = _SQL.format(type_clause=type_clause)
        binds = [bindparam("ids", type_=ARRAY(SAString))]
        if rel_types:
            binds.append(bindparam("rtypes", type_=ARRAY(SAString)))
        stmt = text(sql).bindparams(*binds)

        nodes: dict[str, dict[str, Any]] = {
            root: {"canonical_id": root, "name": None, "entity_type": None, "hop": 0}
        }
        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str]] = set()
        frontier = [root]

        try:
            with get_session() as session:
                for hop in range(1, hops + 1):
                    if not frontier:
                        break
                    params: dict[str, Any] = {
                        "ids": frontier, "minco": minco, "hop_limit": _MAX_EDGES_PER_HOP,
                    }
                    if rel_types:
                        params["rtypes"] = list(rel_types)
                    rows = session.execute(stmt, params).mappings().all()

                    next_frontier: list[str] = []
                    for r in rows:
                        _register_node(nodes, r["from_id"], r["from_name"], r["from_type"], hop)
                        _register_node(nodes, r["to_id"], r["to_name"], r["to_type"], hop)
                        key = (r["from_id"], r["to_id"], r["relationship_type"])
                        if key in seen_edges:
                            continue
                        seen_edges.add(key)
                        edges.append({
                            "from": r["from_id"],
                            "to": r["to_id"],
                            "relationship_type": r["relationship_type"],
                            "weight": int(r["weight"]) if r["weight"] is not None else None,
                            "description": r["description"],
                        })
                        for nid in (r["from_id"], r["to_id"]):
                            if nodes[nid]["hop"] == hop and nid not in frontier:
                                next_frontier.append(nid)
                    frontier = list(dict.fromkeys(next_frontier))
        except Exception as e:
            logger.exception("entity_graph traversal failed")
            return ToolResult(ok=False, error=f"query failed: {e}")

        node_list = sorted(nodes.values(), key=lambda n: n["hop"])
        return ToolResult(
            ok=True,
            data={"root": root, "nodes": node_list, "edges": edges},
            summary=f"entity_graph: {len(node_list) - 1} neighbor(s), "
            f"{len(edges)} edge(s) within {hops} hop(s)",
        )


def _register_node(
    nodes: dict[str, dict[str, Any]], nid: str, name: str | None,
    etype: str | None, hop: int,
) -> None:
    existing = nodes.get(nid)
    if existing is None:
        nodes[nid] = {"canonical_id": nid, "name": name, "entity_type": etype, "hop": hop}
    else:
        # Keep the shallowest hop; backfill name/type discovered on a later edge.
        if existing.get("name") is None and name is not None:
            existing["name"] = name
            existing["entity_type"] = etype


TOOL = EntityGraphTool()
