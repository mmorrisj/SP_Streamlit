"""FastAPI router for the agent runtime.

Mounted at /api/agent/* from server/main.py. The agent page hits only
endpoints in this router; no foundational handlers are modified.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
from typing import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

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


# ---------- Structured workflows ------------------------------------------
# Distinct from /analyze (open-ended ReAct loop). Workflows are fixed DAGs.

class ReportWorkflowRequest(BaseModel):
    recipient: str | None = None
    region: str | None = None
    influencer: str | None = None
    start_date: str
    end_date: str
    requested_product: str | None = None


class WorkflowStepView(BaseModel):
    stage_name: str
    status: str
    summary: str | None = None
    confidence: float | None = None
    notes: list[str] | None = None
    error: str | None = None
    output: dict | None = None
    latency_ms: float | None = None


class ReportWorkflowResponse(BaseModel):
    run_id: str
    workflow: str
    status: str
    skipped_stages: list[str]
    steps: list[WorkflowStepView]


@router.post("/workflows/report", response_model=ReportWorkflowResponse)
def run_report_workflow(req: ReportWorkflowRequest) -> ReportWorkflowResponse:
    """Run the report-generation workflow (12-stage DAG).

    Stages are currently stubbed; the DAG runs end-to-end and persists per-stage
    rows to agent_workflow_steps so the architecture is exercised even before
    individual stage bodies are filled in.
    """
    if not (req.recipient or req.region):
        raise HTTPException(
            status_code=400,
            detail="Must supply at least one of: recipient, region.",
        )
    if not req.start_date or not req.end_date:
        raise HTTPException(status_code=400, detail="start_date and end_date are required.")

    # Lazy import keeps the heavy workflow package off the router import path
    # in environments where it's not used.
    from agent.workflows.report.pipeline import run_report

    ctx = run_report(req.model_dump(exclude_none=True))

    steps: list[WorkflowStepView] = []
    for stage_name, result in ctx.outputs.items():
        steps.append(
            WorkflowStepView(
                stage_name=stage_name,
                status="succeeded" if result.ok else "failed",
                summary=result.summary,
                confidence=result.confidence,
                notes=result.notes or None,
                error=result.error,
                output=result.data or None,
            )
        )

    overall_status = "succeeded" if all(r.ok for r in ctx.outputs.values()) else "failed"
    return ReportWorkflowResponse(
        run_id=str(ctx.run_id),
        workflow="report",
        status=overall_status,
        skipped_stages=ctx.skipped,
        steps=steps,
    )


# ---------- Streaming variant --------------------------------------------
# Same DAG as /workflows/report, but emits SSE events as stages start /
# complete so the UI can render progress incrementally instead of waiting
# ~5 minutes for the full response. Event shape is documented on
# WorkflowRunner.run().


@router.post("/workflows/report/stream")
def stream_report_workflow(req: ReportWorkflowRequest):
    if not (req.recipient or req.region):
        raise HTTPException(
            status_code=400,
            detail="Must supply at least one of: recipient, region.",
        )
    if not req.start_date or not req.end_date:
        raise HTTPException(status_code=400, detail="start_date and end_date are required.")

    inputs = req.model_dump(exclude_none=True)
    event_q: queue.Queue = queue.Queue()
    SENTINEL = object()

    def on_event(event: dict) -> None:
        event_q.put(event)

    def worker() -> None:
        # Lazy import keeps the workflow package off the router import path
        # for unrelated requests.
        try:
            from agent.workflows.report.pipeline import REPORT_PIPELINE

            REPORT_PIPELINE.run(inputs, on_event=on_event)
        except Exception as e:
            logger.exception("streaming workflow worker crashed")
            event_q.put({"type": "workflow_error", "message": str(e)})
        finally:
            event_q.put(SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    def event_generator() -> Iterator[str]:
        while True:
            event = event_q.get()
            if event is SENTINEL:
                break
            event_type = event.pop("type", "message")
            # default=str so UUIDs / datetimes serialize without manual coercion
            payload = json.dumps(event, default=str)
            yield f"event: {event_type}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
