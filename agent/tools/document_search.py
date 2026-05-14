"""Semantic + lexical document search.

Wraps services/chat/rag_service.py::intelligent_search to give the agent the
full production retrieval stack (HyDE expansion, hybrid BM25 + pgvector,
cross-encoder reranking, entity-aware boost) without re-implementing it.

TODO (future MCP hoist): this body is the canonical implementation. To turn
into a standalone MCP server, lift `run` into a JSON-RPC handler and keep
the same input/output schemas declared on this class.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


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
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
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

        top_k = int(kwargs.get("top_k") or 10)

        try:
            # Lazy import: rag_service pulls in heavy ML deps (torch, sentence-transformers).
            from services.chat.rag_service import intelligent_search
        except Exception as e:  # pragma: no cover - environment-dependent
            logger.exception("rag_service import failed")
            return ToolResult(ok=False, error=f"rag_service unavailable: {e}")

        try:
            results, metadata = intelligent_search(
                query=query,
                k=top_k,
                influencer=kwargs.get("influencer"),
                recipient=kwargs.get("recipient"),
                category=kwargs.get("category"),
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
            )
        except Exception as e:
            logger.exception("intelligent_search failed")
            return ToolResult(ok=False, error=f"search failed: {e}")

        # Trim each result to a model-friendly payload. The full content can
        # be fetched separately via citation_resolver if the briefing needs it.
        trimmed = [_trim_result(r) for r in results]
        citations = [r["doc_id"] for r in trimmed if r.get("doc_id")]

        summary = (
            f"document_search: {len(trimmed)} hits"
            + (f", filters={list(metadata.get('applied_filters', {}).keys())}"
               if metadata.get("applied_filters") else "")
        )

        return ToolResult(
            ok=True,
            data={"results": trimmed, "metadata": metadata},
            citations=citations,
            summary=summary,
        )


def _trim_result(row: dict[str, Any]) -> dict[str, Any]:
    """Keep the structured fields, truncate long content for prompt budget."""
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
        "snippet": content if len(content) <= 800 else content[:800] + "…",
    }


TOOL = DocumentSearchTool()
