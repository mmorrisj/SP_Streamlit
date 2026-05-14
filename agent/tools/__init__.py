"""MCP-style tools.

Each module exposes a single `TOOL` instance (subclass of `agent.tools.base.Tool`).
The registry below is the single source of truth for what the orchestrator can call.

TODO: Each tool in this package is structured so it can later be hoisted into
its own MCP server (separate process / endpoint). The `Tool` base class already
emits both JSON-Schema and Anthropic-style tool definitions to make that
migration mechanical.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.tools.base import Tool


def get_registry() -> dict[str, "Tool"]:
    """Return the active tool registry.

    Lazy import keeps the package importable even when individual tools have
    unresolved foundation dependencies during scaffolding.
    """
    from agent.tools import (
        briefing_generator,
        bilateral_context,
        citation_resolver,
        corroboration_check,
        country_grouping,
        document_search,
        entity_graph,
        entity_lookup,
        event_timeline,
        materiality_filter,
    )

    tools = [
        document_search.TOOL,
        entity_lookup.TOOL,
        entity_graph.TOOL,
        event_timeline.TOOL,
        bilateral_context.TOOL,
        citation_resolver.TOOL,
        materiality_filter.TOOL,
        corroboration_check.TOOL,
        country_grouping.TOOL,
        briefing_generator.TOOL,
    ]
    return {t.name: t for t in tools}
