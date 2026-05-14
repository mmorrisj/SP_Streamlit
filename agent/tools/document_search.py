"""Semantic + lexical document search.

TODO: Wrap services/chat/rag_service.py hybrid retrieval (BM25 + pgvector + reranker).
Read-only against the documents table.
"""
from __future__ import annotations

from agent.tools.base import Tool, ToolResult


class DocumentSearchTool(Tool):
    name = "document_search"
    description = (
        "Retrieve relevant documents for a natural-language query using hybrid "
        "BM25 + vector search with reranking. Returns ranked chunks with doc_ids."
    )
    foundation_dependency = "services/chat/rag_service.py"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
            "influencers": {"type": "array", "items": {"type": "string"}},
            "recipients": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
    }

    def run(self, **kwargs):
        return ToolResult(ok=False, error="not_implemented", summary="document_search stub")


TOOL = DocumentSearchTool()
