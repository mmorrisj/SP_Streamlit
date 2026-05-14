"""MCP server exposing document_search over stdio JSON-RPC.

This is a real Model Context Protocol server. It speaks the MCP wire
protocol (initialize / tools/list / tools/call) on stdin/stdout and can be
invoked by any MCP-compliant host:

    # Direct invocation (or via MCP Inspector for debugging)
    python -m agent.mcp_servers.document_search_server

    # Or registered in a Claude Desktop / MCP Inspector config:
    {
      "mcpServers": {
        "softpower-document-search": {
          "command": "python",
          "args": ["-m", "agent.mcp_servers.document_search_server"],
          "cwd": "/path/to/SoftPower_Analytics",
          "env": {"DB_HOST": "...", "POSTGRES_USER": "...", ...}
        }
      }
    }

The agent orchestrator connects to this same binary via agent/mcp/client.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger("agent.mcp.document_search")

SERVER_NAME = "softpower-document-search"
TOOL_NAME = "document_search"

INPUT_SCHEMA: dict = {
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

server: Server = Server(SERVER_NAME)


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=TOOL_NAME,
            description=(
                "Retrieve relevant documents for a natural-language query using "
                "hybrid BM25 + vector search with reranking, HyDE expansion, and "
                "entity-aware boost. Returns ranked chunks with doc_ids, titles, "
                "dates, sources, and relevance scores."
            ),
            inputSchema=INPUT_SCHEMA,
        )
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != TOOL_NAME:
        raise ValueError(f"unknown tool: {name}")

    # Run the synchronous retrieval pipeline off the asyncio loop so we don't
    # block the MCP server's IO. rag_service is heavy (torch + reranker) so
    # we accept the thread-pool dispatch cost.
    payload = await asyncio.to_thread(_run_search, arguments or {})
    return [types.TextContent(type="text", text=json.dumps(payload, default=str))]


def _run_search(arguments: dict) -> dict:
    query = (arguments.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}

    top_k = int(arguments.get("top_k") or 10)

    try:
        from services.chat.rag_service import intelligent_search
    except Exception as e:  # pragma: no cover - environment-dependent
        logger.exception("rag_service import failed")
        return {"ok": False, "error": f"rag_service unavailable: {e}"}

    try:
        results, metadata = intelligent_search(
            query=query,
            k=top_k,
            influencer=arguments.get("influencer"),
            recipient=arguments.get("recipient"),
            category=arguments.get("category"),
            start_date=arguments.get("start_date"),
            end_date=arguments.get("end_date"),
        )
    except Exception as e:
        logger.exception("intelligent_search failed")
        return {"ok": False, "error": f"search failed: {e}"}

    trimmed = [_trim_result(r) for r in results]
    return {
        "ok": True,
        "results": trimmed,
        "metadata": metadata,
        "citations": [r["doc_id"] for r in trimmed if r.get("doc_id")],
        "summary": f"document_search: {len(trimmed)} hits",
    }


def _trim_result(row: dict) -> dict:
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


async def _main() -> None:
    # MCP servers log to stderr so stdout stays clean for JSON-RPC.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logger.info("starting %s MCP server on stdio", SERVER_NAME)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
