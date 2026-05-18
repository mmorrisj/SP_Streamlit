# Soft Power MCP servers

This directory contains standalone Model Context Protocol servers. Each
server is a separate process that speaks JSON-RPC over stdio per the MCP
specification. The agent orchestrator (`agent/orchestrator.py`) talks to
these servers via `agent/mcp/client.py`; the same servers can also be
registered in any other MCP host (Claude Desktop, MCP Inspector, IDE
plugins).

## Current servers

| Server | Module | Primitives |
|---|---|---|
| `softpower-document-search` | `agent.mcp_servers.document_search_server` | Tools: `document_search` |
| `softpower-writing` | `agent.mcp_servers.writing_server` | Prompts: `quick_summary`, `sourced_report`, `metrics_focused`, `entity_profile`, `bilateral_assessment`. Tools: `list_writing_products`, `recommend_product` |

### MCP primitives used

The writing server exercises MCP's **prompts** primitive (parameterized
templates), not just tools. Prompts are how MCP expresses
"reusable composition recipes" — each product type returns a fully-
composed system prompt + output schema + the analyst's query + any
evidence summary, ready for the LLM to consume. Hosts can discover them
via `prompts/list` and fetch via `prompts/get`. Claude Desktop surfaces
them in its slash-command picker.

## Running a server directly

```bash
# From the project root (with the project's venv active):
python -m agent.mcp_servers.document_search_server
```

The server reads JSON-RPC requests on stdin and writes responses on
stdout. Logs go to stderr to keep stdout clean. The process exits when
its stdin is closed.

## Debugging with MCP Inspector

```bash
# Document search (tools)
npx @modelcontextprotocol/inspector \
  python -m agent.mcp_servers.document_search_server

# Writing products (prompts + tools)
npx @modelcontextprotocol/inspector \
  python -m agent.mcp_servers.writing_server
```

Inspector's UI has separate panes for **Tools**, **Prompts**, and
**Resources** — useful for verifying that the writing server exposes its
products as proper prompts rather than just tool calls.

Inspector opens a browser UI where you can call `tools/list` and
`tools/call` interactively. Database environment variables
(`DB_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`,
`OPENAI_PROJ_API` / `CLAUDE_KEY`) must be exported in the shell that
launches Inspector — the server inherits them.

## Claude Desktop integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or the equivalent on your OS:

```json
{
  "mcpServers": {
    "softpower-document-search": {
      "command": "python",
      "args": ["-m", "agent.mcp_servers.document_search_server"],
      "cwd": "/absolute/path/to/SoftPower_Analytics",
      "env": {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "POSTGRES_USER": "...",
        "POSTGRES_PASSWORD": "...",
        "POSTGRES_DB": "...",
        "OPENAI_PROJ_API": "..."
      }
    }
  }
}
```

After restarting Claude Desktop, the `document_search` tool appears in
the tool picker and Claude can call it against the live database.

## Agent orchestrator integration

The orchestrator routes `document_search` through MCP by default. To
fall back to the in-process implementation (useful for performance
comparisons or when the subprocess can't start):

```bash
AGENT_DOCUMENT_SEARCH_USE_MCP=false
```

The MCP client (`agent/mcp/client.py`) opens one persistent stdio
session per server on first use and reuses it for subsequent calls — so
the rag_service / torch import cost is paid once per orchestrator
process, not once per tool call.

## Adding another tool as an MCP server

1. Copy `document_search_server.py` as `<your_tool>_server.py`.
2. Replace the `_run_search` body with your tool's logic.
3. Update `INPUT_SCHEMA` and the `_list_tools` description.
4. Register the server in `agent/mcp/client.py::MCP_SERVERS`.
5. Update the corresponding `agent/tools/<your_tool>.py` to route via
   `get_mcp_client().call_tool(...)` like `document_search.py` does.
