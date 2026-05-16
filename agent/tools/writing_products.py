"""Tools that surface the softpower-writing MCP server to the orchestrator.

The Writing MCP server's canonical surface is prompts (parameterized
templates), but the current orchestrator only knows how to expose tools to
the LLM. These three tools bridge that gap by wrapping the MCP server's
prompts and tools as plain tools the LLM can call:

  * `list_writing_products`   -> MCP tool of the same name
  * `recommend_product`       -> MCP tool of the same name
  * `get_writing_template`    -> MCP `prompts/get` for one product

When the orchestrator is later extended to natively support MCP prompts,
`get_writing_template` becomes unnecessary and the orchestrator can fetch
templates directly via the MCP client.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

WRITING_SERVER = "softpower-writing"


class ListWritingProductsTool(Tool):
    name = "list_writing_products"
    description = (
        "List the available analyst writing-product types (quick_summary, "
        "sourced_report, metrics_focused, entity_profile, bilateral_assessment) "
        "with their descriptions. Call this first when you're deciding what "
        "kind of output to produce."
    )
    foundation_dependency = "agent/mcp_servers/writing_server.py"
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def run(self, **kwargs: Any) -> ToolResult:
        try:
            from agent.mcp.client import get_mcp_client
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"MCP client unavailable: {e}")

        try:
            payload = get_mcp_client().call_tool(
                server_name=WRITING_SERVER,
                tool_name="list_writing_products",
                arguments={},
            )
        except Exception as e:
            logger.exception("list_writing_products MCP call failed")
            return ToolResult(ok=False, error=str(e))

        if not payload.get("ok"):
            return ToolResult(ok=False, error=payload.get("error") or "writing server returned ok=false")

        products = payload.get("products") or []
        return ToolResult(
            ok=True,
            data={"products": products},
            summary=f"list_writing_products: {len(products)} available",
        )


class RecommendProductTool(Tool):
    name = "recommend_product"
    description = (
        "Given the analyst's query (and optionally a summary of evidence "
        "gathered so far), recommend the best-fit writing product. Returns "
        "{product, reason}. Use this when you're unsure which product type fits."
    )
    foundation_dependency = "agent/mcp_servers/writing_server.py"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The analyst's question."},
            "evidence_summary": {
                "type": "string",
                "description": "Optional summary of evidence gathered so far.",
            },
        },
        "required": ["query"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query is required")

        try:
            from agent.mcp.client import get_mcp_client
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"MCP client unavailable: {e}")

        args = {"query": query}
        if kwargs.get("evidence_summary"):
            args["evidence_summary"] = kwargs["evidence_summary"]

        try:
            payload = get_mcp_client().call_tool(
                server_name=WRITING_SERVER,
                tool_name="recommend_product",
                arguments=args,
            )
        except Exception as e:
            logger.exception("recommend_product MCP call failed")
            return ToolResult(ok=False, error=str(e))

        if not payload.get("ok"):
            return ToolResult(ok=False, error=payload.get("error") or "writing server returned ok=false")

        return ToolResult(
            ok=True,
            data={"product": payload.get("product"), "reason": payload.get("reason")},
            summary=f"recommend_product: {payload.get('product')}",
        )


class GetWritingTemplateTool(Tool):
    name = "get_writing_template"
    description = (
        "Fetch the full composition template for a writing product. Returns "
        "the system instructions, output JSON schema, query restatement, and "
        "evidence summary, all flattened into a single text block. Use this "
        "immediately before you produce the final structured answer, so your "
        "output conforms to the product's schema."
    )
    foundation_dependency = "agent/mcp_servers/writing_server.py (prompts API)"
    input_schema = {
        "type": "object",
        "properties": {
            "product": {
                "type": "string",
                "description": "Product name, e.g. 'sourced_report'.",
                "enum": [
                    "quick_summary",
                    "sourced_report",
                    "metrics_focused",
                    "entity_profile",
                    "bilateral_assessment",
                ],
            },
            "query": {"type": "string", "description": "The analyst's original question."},
            "evidence_summary": {
                "type": "string",
                "description": "Short summary of evidence gathered so far (optional).",
            },
        },
        "required": ["product", "query"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        product = (kwargs.get("product") or "").strip()
        query = (kwargs.get("query") or "").strip()
        if not product:
            return ToolResult(ok=False, error="product is required")
        if not query:
            return ToolResult(ok=False, error="query is required")

        try:
            from agent.mcp.client import get_mcp_client
        except Exception as e:  # pragma: no cover
            return ToolResult(ok=False, error=f"MCP client unavailable: {e}")

        args: dict[str, Any] = {"query": query}
        if kwargs.get("evidence_summary"):
            args["evidence_summary"] = kwargs["evidence_summary"]

        try:
            payload = get_mcp_client().get_prompt(
                server_name=WRITING_SERVER,
                prompt_name=product,
                arguments=args,
            )
        except ValueError as e:
            return ToolResult(ok=False, error=f"unknown product: {product} ({e})")
        except Exception as e:
            logger.exception("get_prompt MCP call failed")
            return ToolResult(ok=False, error=str(e))

        return ToolResult(
            ok=True,
            data={
                "product": product,
                "description": payload.get("description"),
                "template": payload.get("text"),
            },
            summary=f"get_writing_template: {product}",
        )


LIST_TOOL = ListWritingProductsTool()
RECOMMEND_TOOL = RecommendProductTool()
GET_TEMPLATE_TOOL = GetWritingTemplateTool()
