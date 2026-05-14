"""Standalone MCP servers extracted from in-process tools.

Each module here implements the Model Context Protocol over stdio and can be
invoked directly:

    python -m agent.mcp_servers.document_search_server

The same servers can be registered in any MCP host (Claude Desktop, MCP
Inspector, IDE plugins) via a standard `mcpServers` config entry.
"""
