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
    ChatTurnRequest,
    ChatTurnResponse,
    ConverseRequest,
    ToolDescriptor,
    ToolListResponse,
)
from agent.tools import get_registry

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/health")
def agent_health() -> dict:
    """Agent runtime health, including WHERE LLM calls are routed.

    `llm_source`/`llm_target` are the operational facts an operator needs when
    diagnosing connection errors: the agent follows the same routing contract
    as the rest of the app (GAI_DEFAULT_SOURCE; proxy by default), so on
    enterprise deployments this should show source=proxy targeting API_URL.
    """
    try:
        from agent.llm.provider import get_provider
        provider = get_provider()
        resolved_model = getattr(provider, "model", None)
        llm_source = getattr(provider, "source", None)
        llm_target = getattr(provider, "target", None)
        provider_error = None
    except Exception as e:  # pragma: no cover - defensive
        resolved_model, llm_source, llm_target = None, None, None
        provider_error = str(e)
    return {
        "status": "ok" if provider_error is None else "degraded",
        "provider": os.getenv("AGENT_LLM_PROVIDER", "openai_compat"),
        "model": os.getenv("AGENT_LLM_MODEL") or resolved_model,
        "tool_mode": os.getenv("AGENT_LLM_TOOL_MODE", "native"),
        "llm_source": llm_source,
        "llm_target": llm_target,
        "provider_error": provider_error,
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

    Drives the LLM tool-dispatch loop in Orchestrator.analyze: the model selects
    from the agent tool registry (document_search, entity_lookup, entity_graph,
    event_timeline, bilateral_context, materiality_filter, country_grouping,
    corroboration_check, citation_resolver, briefing_generator, writing
    products), each call is persisted to agent_tool_calls, and the run ends with
    a structured briefing.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    return Orchestrator().analyze(request)


@router.post("/chat", response_model=ChatTurnResponse)
def agent_chat(request: ChatTurnRequest) -> ChatTurnResponse:
    """Natural-language entry point to the workflow runner.

    One LLM call: classify the user's message into an action (propose_run /
    update_scope / clarify / chat) and a complete scope object. The client
    reflects the returned scope into its filter panel and decides whether
    to run the workflow (always explicit — no auto-run from a chat turn).
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    return Orchestrator().classify_intent(request)


# ---------- Conversational agent (streaming) -------------------------------
# The primary Agent-page experience: free-form conversation where the model
# pulls data with tools and answers in whatever form the question calls for.
# Tool activity streams as it happens; the full report pipeline is only ever
# an explicit offer (report_offer event -> analyst clicks Run).


@router.post("/converse/stream")
def converse_stream(req: ConverseRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    event_q: queue.Queue = queue.Queue()
    SENTINEL = object()

    # LLM calls run in a worker thread; contextvars don't cross threads, so
    # capture the gateway JWT here and re-set it inside the worker (same
    # pattern as the workflow stream below).
    from shared.utils.request_context import get_gateway_jwt, set_gateway_jwt
    gateway_jwt = get_gateway_jwt()

    def on_event(event: dict) -> None:
        event_q.put(event)

    def worker() -> None:
        set_gateway_jwt(gateway_jwt)
        try:
            Orchestrator().converse(req, on_event=on_event)
        except Exception as e:  # pragma: no cover - converse() catches internally
            logger.exception("converse worker crashed")
            event_q.put({"type": "error", "message": str(e)})
        finally:
            event_q.put(SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    def event_generator() -> Iterator[str]:
        while True:
            event = event_q.get()
            if event is SENTINEL:
                break
            event_type = event.pop("type", "message")
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


# ---------- Structured workflows ------------------------------------------
# Distinct from /analyze (open-ended ReAct loop). Workflows are fixed DAGs.

class ReportWorkflowRequest(BaseModel):
    recipient: str | None = None
    region: str | None = None
    influencer: str | None = None
    start_date: str
    end_date: str
    requested_product: str | None = None
    # Category dimension. Phase 1 supports "flat" (no filter) and "filter"
    # (single-category scope). "breakdown" is reserved for Phase 2 — passed
    # through as metadata but currently behaves like "flat".
    category: str | None = None
    subcategory: str | None = None
    category_mode: str | None = "flat"


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

    Stages perform real DB queries and LLM calls. LLM stages authenticate via
    the enterprise gateway JWT (see agent/llm/openai_compat.py); per-stage rows
    are persisted to agent_workflow_steps for the UI trace.
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

    # The DAG runs in a worker thread; contextvars don't propagate across a
    # manually-spawned thread, so capture the gateway JWT here and re-set it
    # inside the worker so the LLM stages can authenticate to LiteLLM.
    from shared.utils.request_context import get_gateway_jwt, set_gateway_jwt
    gateway_jwt = get_gateway_jwt()

    def on_event(event: dict) -> None:
        event_q.put(event)

    def worker() -> None:
        set_gateway_jwt(gateway_jwt)
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
