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

    Lazy import keeps the package importable even when an individual tool's
    foundation dependency (DB, rag_service, LLM provider) is unavailable in a
    given environment.
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
        writing_products,
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
        writing_products.LIST_TOOL,
        writing_products.RECOMMEND_TOOL,
        writing_products.GET_TEMPLATE_TOOL,
    ]
    return {t.name: t for t in tools}


def get_converse_registry() -> dict[str, "Tool"]:
    """Tool registry for the conversational agent (/converse/stream).

    Data-pull tools only — the model composes the answer itself, so the
    briefing/writing synthesis tools are omitted. Adds the doctrine tools
    (provenance, initiative gate, tempo, verified reports) and the
    propose_report action.
    """
    from agent.tools import (
        activity_series,
        bilateral_context,
        citation_resolver,
        corroboration_check,
        country_grouping,
        document_search,
        entity_graph,
        entity_lookup,
        event_timeline,
        initiative_ledger,
        insight_reports,
        materiality_filter,
        propose_report,
        provenance_stats,
    )

    tools = [
        # retrieval over the corpus
        document_search.TOOL,
        entity_lookup.TOOL,
        entity_graph.TOOL,
        event_timeline.TOOL,
        bilateral_context.TOOL,
        citation_resolver.TOOL,
        materiality_filter.TOOL,
        corroboration_check.TOOL,
        country_grouping.TOOL,
        # doctrine / derived analytics
        provenance_stats.TOOL,
        initiative_ledger.TOOL,
        activity_series.TOOL,
        insight_reports.TOOL,
        # explicit action offer (never auto-runs)
        propose_report.TOOL,
    ]
    return {t.name: t for t in tools}
