"""MCP client manager: persistent stdio sessions to MCP servers.

The orchestrator's tool dispatch is synchronous (FastAPI handler runs in a
thread pool), but the MCP Python SDK is async. We bridge by running a
dedicated asyncio event loop on a background thread and submitting work to
it with `run_coroutine_threadsafe`.

Server subprocesses are spawned lazily on first use and kept alive for the
lifetime of the process, so repeated tool calls reuse a single
ClientSession instead of paying the rag_service import cost (torch +
sentence-transformers, ~5–10s) on every request.

Configuration: servers are registered in MCP_SERVERS below. The mapping is
intentionally explicit rather than file-driven for the proof-of-concept;
swap in a JSON config in a follow-up if more servers land.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPServerSpec:
    """How to spawn a particular MCP server subprocess."""
    name: str
    command: str
    args: list[str]
    env: dict[str, str] | None = None


# Single registry of MCP servers this orchestrator knows how to launch.
# When you promote another tool to a standalone MCP server, add an entry here.
MCP_SERVERS: dict[str, MCPServerSpec] = {
    "softpower-document-search": MCPServerSpec(
        name="softpower-document-search",
        command=sys.executable,
        args=["-m", "agent.mcp_servers.document_search_server"],
    ),
    "softpower-writing": MCPServerSpec(
        name="softpower-writing",
        command=sys.executable,
        args=["-m", "agent.mcp_servers.writing_server"],
    ),
}


class MCPClientManager:
    """Singleton: holds the background event loop and a session per server."""

    _instance: "MCPClientManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, Any] = {}            # name -> ClientSession
        self._exit_stacks: dict[str, Any] = {}         # name -> AsyncExitStack
        self._session_lock = threading.Lock()

    # ----- singleton accessor --------------------------------------------
    @classmethod
    def instance(cls) -> "MCPClientManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ----- public API ----------------------------------------------------
    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Synchronous entry point. Returns the tool's parsed JSON payload."""
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(server_name, tool_name, arguments),
            loop,
        )
        return fut.result(timeout=timeout)

    def list_prompts(self, server_name: str, timeout: float = 30.0) -> list[dict[str, Any]]:
        """Return the list of prompts exposed by an MCP server."""
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(
            self._list_prompts_async(server_name),
            loop,
        )
        return fut.result(timeout=timeout)

    def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch a parameterized prompt as a flattened {description, text} dict.

        The text is the concatenation of all message contents in order — for
        prompts that return a single user-role message (our convention), the
        text is exactly the composition instructions the LLM should consume.
        """
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(
            self._get_prompt_async(server_name, prompt_name, arguments or {}),
            loop,
        )
        return fut.result(timeout=timeout)

    # ----- internals -----------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        with self._session_lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            t = threading.Thread(target=loop.run_forever, name="mcp-client", daemon=True)
            t.start()
            self._loop = loop
            self._thread = t
            return loop

    async def _get_session(self, server_name: str) -> Any:
        if server_name in self._sessions:
            return self._sessions[server_name]

        spec = MCP_SERVERS.get(server_name)
        if spec is None:
            raise ValueError(f"unknown MCP server: {server_name!r}")

        # Lazy import so this module doesn't hard-require the mcp package
        # at process start.
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=spec.command,
            args=spec.args,
            env={**os.environ, **(spec.env or {})},
        )

        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        self._sessions[server_name] = session
        self._exit_stacks[server_name] = stack
        logger.info("MCP session opened: %s", server_name)
        return session

    async def _call_tool_async(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        session = await self._get_session(server_name)
        result = await session.call_tool(tool_name, arguments=arguments)

        # MCP tool results are a list of content blocks. Our servers return
        # a single TextContent with JSON; decode it back to a dict.
        if not result.content:
            return {"ok": False, "error": "empty tool result"}
        block = result.content[0]
        text = getattr(block, "text", None)
        if text is None:
            return {"ok": False, "error": "non-text content block returned"}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"ok": False, "error": "tool returned non-JSON text", "raw": text}

    async def _list_prompts_async(self, server_name: str) -> list[dict[str, Any]]:
        session = await self._get_session(server_name)
        result = await session.list_prompts()
        out: list[dict[str, Any]] = []
        for p in result.prompts:
            out.append(
                {
                    "name": p.name,
                    "description": p.description,
                    "arguments": [
                        {
                            "name": a.name,
                            "description": a.description,
                            "required": a.required,
                        }
                        for a in (p.arguments or [])
                    ],
                }
            )
        return out

    async def _get_prompt_async(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        session = await self._get_session(server_name)
        result = await session.get_prompt(prompt_name, arguments=arguments)

        # Concatenate the text of every message in the prompt; preserves
        # multi-message templates while keeping our single-message convention
        # working unchanged.
        parts: list[str] = []
        for msg in result.messages:
            content = msg.content
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
        return {
            "description": result.description,
            "text": "\n\n".join(parts),
            "messages": [
                {
                    "role": m.role,
                    "text": getattr(m.content, "text", None),
                }
                for m in result.messages
            ],
        }


def get_mcp_client() -> MCPClientManager:
    return MCPClientManager.instance()
