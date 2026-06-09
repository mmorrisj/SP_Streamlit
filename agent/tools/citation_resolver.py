"""Hydrate a list of doc_ids into formatted citations.

Wraps shared/utils/citation_utils.py:
  * get_citations_for_doc_ids -> per-doc source_name, title, date, formatted citation
  * build_hyperlink -> a clickable ATOM search URL covering all doc_ids
Read-only.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class CitationResolverTool(Tool):
    name = "citation_resolver"
    description = "Hydrate a list of doc_ids into formatted citations with source metadata."
    foundation_dependency = "shared/utils/citation_utils.py"
    input_schema = {
        "type": "object",
        "properties": {
            "doc_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["doc_ids"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        doc_ids = [d for d in (kwargs.get("doc_ids") or []) if d]
        if not doc_ids:
            return ToolResult(ok=False, error="doc_ids is required (non-empty)")
        # De-dupe while preserving order.
        doc_ids = list(dict.fromkeys(doc_ids))

        try:
            from shared.utils.citation_utils import (
                build_hyperlink,
                get_citations_for_doc_ids,
            )
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"citation_utils unavailable: {e}")

        try:
            citations = get_citations_for_doc_ids(doc_ids)
        except Exception as e:
            logger.exception("get_citations_for_doc_ids failed")
            return ToolResult(ok=False, error=f"citation lookup failed: {e}")

        try:
            hyperlink = build_hyperlink(doc_ids)
        except Exception:  # pragma: no cover - URL build should not block citations
            logger.warning("build_hyperlink failed", exc_info=True)
            hyperlink = None

        resolved_ids = {c.get("doc_id") for c in citations}
        missing = [d for d in doc_ids if d not in resolved_ids]

        return ToolResult(
            ok=True,
            data={"citations": citations, "hyperlink": hyperlink, "missing": missing},
            citations=doc_ids,
            summary=f"citation_resolver: resolved {len(citations)}/{len(doc_ids)} doc_id(s)"
            + (f", {len(missing)} missing" if missing else ""),
        )


TOOL = CitationResolverTool()
