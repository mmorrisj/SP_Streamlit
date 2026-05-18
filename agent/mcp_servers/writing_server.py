"""MCP server: writing-product catalog.

Exposes five analyst output products as MCP **prompts** (the parameterized-
template primitive of MCP, distinct from tools). Each prompt returns a
ready-to-use composition instruction set: system rules + output JSON schema
+ the user's query + any supplied evidence summary.

Also exposes two tools:
  * `list_writing_products` — same catalog accessible via the tools API for
    hosts that don't speak the prompts primitive.
  * `recommend_product` — heuristic router that suggests the best-fit
    product for a given query.

Run standalone:
    python -m agent.mcp_servers.writing_server
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger("agent.mcp.writing")

SERVER_NAME = "softpower-writing"


# ---------------------------------------------------------------------------
# Product catalog
# ---------------------------------------------------------------------------

PRODUCTS: dict[str, dict[str, Any]] = {
    "quick_summary": {
        "description": "Three-bullet executive summary, ≤25 words per bullet, no citations required.",
        "system": (
            "You are producing a QUICK SUMMARY product.\n"
            "Rules:\n"
            "  - Output exactly three bullet points.\n"
            "  - Each bullet must be 25 words or fewer.\n"
            "  - Lead with the most actionable / consequential point.\n"
            "  - Citations are not required.\n"
            "  - State conclusions confidently; skip equivocation and caveats."
        ),
        "schema": {
            "product_type": "quick_summary",
            "topic": "<one-sentence framing>",
            "bullets": [
                {"point": "<≤25 words>"},
                {"point": "<≤25 words>"},
                {"point": "<≤25 words>"},
            ],
        },
    },
    "sourced_report": {
        "description": "Full analyst briefing with inline source IDs, confidence levels, gaps, and follow-ups.",
        "system": (
            "You are producing a SOURCED REPORT — a full analyst briefing with "
            "verifiable citations.\n"
            "Rules:\n"
            "  - Only use facts from the provided evidence. Do not invent\n"
            "    doc_ids, dates, or attributions.\n"
            "  - Every key judgment must reference at least one source_id.\n"
            "  - Confidence levels are LOW, MED, or HIGH.\n"
            "  - If evidence is thin, say so explicitly under information_gaps."
        ),
        "schema": {
            "product_type": "sourced_report",
            "title": "<short title>",
            "executive_summary": "<3-5 sentences>",
            "key_judgments": [
                {"judgment": "<claim>", "confidence": "LOW|MED|HIGH", "source_ids": ["<doc_id>"]}
            ],
            "timeline": [
                {"timestamp": "<ISO date>", "event": "<short>", "source_ids": ["<doc_id>"]}
            ],
            "key_entities": [
                {"name": "<entity>", "entity_type": "person|organization|location", "role": "<role>"}
            ],
            "evidence": [{"source_id": "<doc_id>", "title": "<title>", "snippet": "<short>"}],
            "confidence_assessment": "<paragraph>",
            "information_gaps": ["<gap>"],
            "recommended_followup": ["<follow-up>"],
        },
    },
    "metrics_focused": {
        "description": "Numbers-first output: headline metric, comparison table, trend, anomalies.",
        "system": (
            "You are producing a METRICS-FOCUSED product. Lead with quantitative "
            "findings.\n"
            "Rules:\n"
            "  - Open with a single headline metric that frames the answer.\n"
            "  - Use tables. Numbers beat adjectives.\n"
            "  - Show comparisons (vs prior period, vs peers) when possible.\n"
            "  - Flag anomalies separately from the main metrics table."
        ),
        "schema": {
            "product_type": "metrics_focused",
            "headline_metric": {
                "label": "<metric name>",
                "value": "<number>",
                "unit": "<unit>",
                "context": "<one-sentence framing>",
            },
            "metrics_table": [
                {"dimension": "<row label>", "value": "<number>", "delta": "<vs comparison>"}
            ],
            "trend_analysis": "<2-3 sentences>",
            "anomalies": [{"observation": "<what>", "magnitude": "<how much>"}],
        },
    },
    "entity_profile": {
        "description": "Structured profile of one canonical entity: TL;DR, key facts, relationships, recent activity.",
        "system": (
            "You are producing an ENTITY PROFILE for a single canonical entity.\n"
            "Rules:\n"
            "  - One profile per call. Stay tightly focused on the target entity.\n"
            "  - Lead with a 30-second TL;DR.\n"
            "  - Relationships matter as much as biographical facts."
        ),
        "schema": {
            "product_type": "entity_profile",
            "name": "<entity name>",
            "entity_type": "person|organization|location|other",
            "tldr": "<one sentence>",
            "summary": "<paragraph>",
            "key_facts": [{"fact": "<statement>", "source_ids": ["<doc_id>"]}],
            "relationships": [
                {"related_entity": "<name>", "relationship": "<type>", "strength": "low|med|high"}
            ],
            "recent_activity": [
                {"date": "<ISO>", "event": "<short>", "source_ids": ["<doc_id>"]}
            ],
        },
    },
    "bilateral_assessment": {
        "description": "Influencer→recipient relationship assessment with trajectory and implications.",
        "system": (
            "You are producing a BILATERAL ASSESSMENT between two countries.\n"
            "Rules:\n"
            "  - Frame from the influencer's perspective: what the influencer is\n"
            "    doing to / with the recipient.\n"
            "  - Distinguish stated intent from observed behavior.\n"
            "  - Surface trajectory: accelerating, steady, or cooling."
        ),
        "schema": {
            "product_type": "bilateral_assessment",
            "influencer": "<country>",
            "recipient": "<country>",
            "tldr": "<one sentence>",
            "summary": "<paragraph>",
            "key_engagements": [
                {"category": "<theme>", "description": "<what>", "source_ids": ["<doc_id>"]}
            ],
            "trajectory": "accelerating|steady|cooling",
            "trajectory_evidence": ["<observation>"],
            "implications": ["<implication>"],
        },
    },
}


# ---------------------------------------------------------------------------
# Heuristic product router
# ---------------------------------------------------------------------------

# Country list kept short — the recommender only needs enough to detect the
# bilateral pattern. Full canonical list lives in shared/config/config.yaml.
_KNOWN_COUNTRIES = {
    "china", "russia", "iran", "turkey", "united states", "usa", "us",
    "egypt", "saudi arabia", "uae", "israel", "india", "pakistan",
    "indonesia", "vietnam", "thailand", "kenya", "ethiopia", "nigeria",
    "south africa", "brazil", "mexico", "venezuela", "cuba",
}

_METRICS_HINTS = (
    "metric", "stat", "compare", "trend", "how many", "how much",
    "percentage", "growth", "rate", "volume", "count", "rank",
)
_BREVITY_HINTS = ("quick", "brief", "summarize", "tldr", "bullet", "one-liner")
_ENTITY_HINTS = ("who is", "tell me about", "profile of", "bio of")


def _recommend(query: str, evidence_summary: str = "") -> dict[str, str]:
    q = (query or "").lower()

    countries = [c for c in _KNOWN_COUNTRIES if c in q]
    if len(countries) >= 2:
        return {
            "product": "bilateral_assessment",
            "reason": f"Two countries detected: {', '.join(sorted(set(countries))[:2])}",
        }

    if any(h in q for h in _METRICS_HINTS):
        return {"product": "metrics_focused", "reason": "Quantitative framing in query"}

    if any(q.startswith(h) for h in _ENTITY_HINTS):
        return {"product": "entity_profile", "reason": "Query targets a specific entity"}

    if any(h in q for h in _BREVITY_HINTS):
        return {"product": "quick_summary", "reason": "Brevity explicitly requested"}

    return {"product": "sourced_report", "reason": "Default product for analyst briefings"}


# ---------------------------------------------------------------------------
# MCP server wiring
# ---------------------------------------------------------------------------

server: Server = Server(SERVER_NAME)


@server.list_prompts()
async def _list_prompts() -> list[types.Prompt]:
    """Expose each product as a parameterized MCP prompt."""
    prompts: list[types.Prompt] = []
    for name, spec in PRODUCTS.items():
        prompts.append(
            types.Prompt(
                name=name,
                description=spec["description"],
                arguments=[
                    types.PromptArgument(
                        name="query",
                        description="The analyst's original question.",
                        required=True,
                    ),
                    types.PromptArgument(
                        name="evidence_summary",
                        description="Short summary of the evidence gathered so far.",
                        required=False,
                    ),
                ],
            )
        )
    return prompts


@server.get_prompt()
async def _get_prompt(name: str, arguments: dict | None = None) -> types.GetPromptResult:
    spec = PRODUCTS.get(name)
    if spec is None:
        raise ValueError(f"unknown product: {name}")

    args = arguments or {}
    query = args.get("query", "")
    evidence_summary = args.get("evidence_summary", "")

    composed = _compose_prompt_text(
        system=spec["system"],
        schema=spec["schema"],
        query=query,
        evidence_summary=evidence_summary,
    )

    return types.GetPromptResult(
        description=spec["description"],
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=composed),
            )
        ],
    )


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_writing_products",
            description=(
                "List the available writing-product types with their descriptions. "
                "Use this to discover what output formats the analyst can request."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        types.Tool(
            name="recommend_product",
            description=(
                "Recommend the best-fit writing product for a given query. Returns "
                "{product, reason}. Heuristic — host may override."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The analyst's question."},
                    "evidence_summary": {
                        "type": "string",
                        "description": "Optional summary of evidence gathered so far.",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "list_writing_products":
        payload = {
            "ok": True,
            "products": [
                {"name": n, "description": s["description"]}
                for n, s in PRODUCTS.items()
            ],
        }
    elif name == "recommend_product":
        query = (arguments or {}).get("query", "")
        if not query:
            payload = {"ok": False, "error": "query is required"}
        else:
            rec = _recommend(query, (arguments or {}).get("evidence_summary", ""))
            payload = {"ok": True, **rec}
    else:
        raise ValueError(f"unknown tool: {name}")

    return [types.TextContent(type="text", text=json.dumps(payload, default=str))]


def _compose_prompt_text(*, system: str, schema: dict, query: str, evidence_summary: str) -> str:
    parts = [
        system,
        "",
        "Output JSON matching this schema exactly. No prose, no code fences:",
        json.dumps(schema, indent=2),
        "",
        f"Analyst query:\n{query}",
    ]
    if evidence_summary:
        parts += ["", f"Evidence summary:\n{evidence_summary}"]
    return "\n".join(parts)


async def _main() -> None:
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
