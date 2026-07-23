"""Semantic + lexical document search.

Two execution paths:

  * **MCP mode** (default when AGENT_DOCUMENT_SEARCH_USE_MCP is truthy):
    forwards the call over the MCP wire protocol to a standalone server
    in agent/mcp_servers/document_search_server.py. This is a real MCP
    invocation — JSON-RPC over stdio, initialize handshake, tools/call.

  * **In-process mode**: calls services/chat/rag_service.intelligent_search
    directly in the orchestrator's process. Kept as a fallback so the
    agent still works if the MCP subprocess fails to start.

Both paths return the same ToolResult shape; the orchestrator does not need
to know which transport was used.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "softpower-document-search"
MCP_TOOL_NAME = "document_search"


def _use_mcp() -> bool:
    return os.getenv("AGENT_DOCUMENT_SEARCH_USE_MCP", "true").lower() in (
        "1", "true", "yes", "on",
    )


class DocumentSearchTool(Tool):
    name = "document_search"
    description = (
        "Retrieve relevant documents for a natural-language query using hybrid "
        "BM25 + vector search with reranking. Returns ranked chunks with doc_ids, "
        "titles, dates, sources, and relevance scores."
    )
    foundation_dependency = "services/chat/rag_service.py::intelligent_search"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query."},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            "influencer": {"type": "string", "description": "Filter by initiating country."},
            "recipient": {"type": "string", "description": "Filter by recipient country."},
            "category": {"type": "string"},
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
        },
        "required": ["query"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query is required")

        if _use_mcp():
            return self._run_via_mcp(kwargs)
        return self._run_in_process(kwargs)

    # ----- MCP path ------------------------------------------------------
    def _run_via_mcp(self, kwargs: dict[str, Any]) -> ToolResult:
        try:
            from agent.mcp.client import get_mcp_client
        except Exception as e:  # pragma: no cover
            logger.exception("MCP client import failed; falling back to in-process")
            return self._run_in_process(kwargs, fallback_reason=str(e))

        try:
            payload = get_mcp_client().call_tool(
                server_name=MCP_SERVER_NAME,
                tool_name=MCP_TOOL_NAME,
                arguments=_clean_args(kwargs),
            )
        except Exception as e:
            logger.exception("MCP call_tool failed; falling back to in-process")
            return self._run_in_process(kwargs, fallback_reason=str(e))

        if not payload.get("ok"):
            return ToolResult(
                ok=False,
                error=payload.get("error") or "MCP server returned ok=false",
                summary="document_search [mcp]: failed",
            )

        results = payload.get("results") or []
        return ToolResult(
            ok=True,
            data={"results": results, "metadata": payload.get("metadata") or {}},
            citations=payload.get("citations") or [],
            summary=f"document_search [mcp]: {len(results)} hits",
        )

    # ----- in-process fallback ------------------------------------------
    def _run_in_process(
        self,
        kwargs: dict[str, Any],
        fallback_reason: str | None = None,
    ) -> ToolResult:
        try:
            from services.chat.rag_service import intelligent_search
        except Exception as e:  # pragma: no cover
            logger.exception("rag_service import failed")
            return ToolResult(ok=False, error=f"rag_service unavailable: {e}")

        try:
            results, metadata = intelligent_search(
                query=kwargs["query"],
                k=int(kwargs.get("top_k") or 25),
                influencer=kwargs.get("influencer"),
                recipient=kwargs.get("recipient"),
                category=kwargs.get("category"),
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
            )
        except Exception as e:
            logger.exception("intelligent_search failed")
            return ToolResult(ok=False, error=f"search failed: {e}")

        trimmed = [_trim_result(r) for r in results]
        citations = [r["doc_id"] for r in trimmed if r.get("doc_id")]
        tag = "[in-process fallback]" if fallback_reason else "[in-process]"
        return ToolResult(
            ok=True,
            data={"results": trimmed, "metadata": metadata},
            citations=citations,
            summary=f"document_search {tag}: {len(trimmed)} hits",
        )


def _clean_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so the MCP server sees only explicitly-set arguments."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _trim_result(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content") or ""
    return {
        "doc_id": row.get("doc_id"),
        "title": row.get("title"),
        "source_name": row.get("source_name"),
        "date": row.get("date"),
        "initiating_country": row.get("initiating_country"),
        "recipient_country": row.get("recipient_country"),
        "category": row.get("category"),
        "salience": row.get("salience"),
        "relevance_score": row.get("relevance_score"),
        "snippet": content if len(content) <= 2500 else content[:2500] + "…",
    }


TOOL = DocumentSearchTool()
