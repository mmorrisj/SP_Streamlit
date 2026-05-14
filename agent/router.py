"""FastAPI router for the agent runtime.

Mounted at /api/agent/* from server/main.py. The agent page hits only
endpoints in this router; no foundational handlers are modified.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from agent.orchestrator import Orchestrator
from agent.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ToolDescriptor,
    ToolListResponse,
)
from agent.tools import get_registry

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/health")
def agent_health() -> dict:
    return {
        "status": "ok",
        "provider": os.getenv("AGENT_LLM_PROVIDER", "openai_compat"),
        "model": os.getenv("AGENT_LLM_MODEL"),
        "tool_mode": os.getenv("AGENT_LLM_TOOL_MODE", "native"),
    }


@router.get("/tools", response_model=ToolListResponse)
def list_tools() -> ToolListResponse:
    """Return the available MCP-style tools and their schemas."""
    registry = get_registry()
    return ToolListResponse(
        tools=[
            ToolDescriptor(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
                foundation_dependency=t.foundation_dependency,
            )
            for t in registry.values()
        ]
    )


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Run the planner → tools → briefing pipeline.

    Currently returns a static workflow plan; tool execution and briefing
    generation are TODO until the LLM providers and tool bodies are wired.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    return Orchestrator().analyze(request)
