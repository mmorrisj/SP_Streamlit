"""Agent package: MCP-style modular tools, orchestrator, and provider-agnostic LLM gateway.

This package is intentionally self-contained. It imports read-only from `shared/`
and `services/` but does not modify foundational code paths. Each tool in
`agent/tools/` is structured so it can later be hoisted into its own MCP server.
"""

__all__ = ["router"]
