"""Orchestrator: plan → execute → trace.

Runs an LLM tool-dispatch loop against the provider configured in
agent/llm/provider.py. Each tool invocation is persisted to
agent_tool_calls so the UI can render a workflow trace and so runs are
auditable after the fact.

Flow:
    1. Insert AgentRun row (status=running)
    2. Seed message history with the planner system prompt + user query
    3. Loop up to MAX_TURNS:
         a. Call provider.complete(messages, tools)
         b. If response has tool_calls -> dispatch each, append tool messages
         c. Else -> treat content as the final answer, persist briefing JSON
    4. Mark run succeeded/failed, return AnalyzeResponse
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from agent.llm.provider import LLMMessage, ToolCall, get_provider, get_tool_mode
from agent.prompts import BRIEFING_SYSTEM
from agent.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    Briefing,
    EvidenceItem,
    WorkflowStep,
)
from agent.tools import get_registry
from agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "8"))


@dataclass
class _RunCtx:
    run_id: UUID
    request: AnalyzeRequest
    workflow: list[WorkflowStep] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    step_counter: int = 0


class Orchestrator:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = get_registry()

    # ----- public -----------------------------------------------------------

    def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        ctx = _RunCtx(run_id=uuid4(), request=request)
        provider = get_provider()
        tool_mode = get_tool_mode()

        run_started = time.monotonic()
        self._insert_run(
            ctx,
            provider_name=provider.name,
            model=getattr(provider, "model", None),
            tool_mode=tool_mode,
        )

        try:
            briefing = self._run_loop(ctx, provider)
            self._finalize_run(
                ctx,
                status="succeeded",
                briefing=briefing,
                latency_ms=int((time.monotonic() - run_started) * 1000),
            )
            return AnalyzeResponse(
                run_id=ctx.run_id,
                briefing=briefing,
                workflow=ctx.workflow,
                evidence=[],
                entities=[],
                timeline=[],
            )
        except Exception as e:
            logger.exception("agent run failed")
            self._finalize_run(
                ctx,
                status="failed",
                error=str(e),
                latency_ms=int((time.monotonic() - run_started) * 1000),
            )
            return AnalyzeResponse(
                run_id=ctx.run_id,
                briefing=None,
                workflow=ctx.workflow,
                evidence=[],
                entities=[],
                timeline=[],
            )

    # ----- main loop --------------------------------------------------------

    def _run_loop(self, ctx: _RunCtx, provider: Any) -> Briefing | None:
        tool_specs = [t.as_openai_tool() for t in self.tools.values()]
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=BRIEFING_SYSTEM),
            LLMMessage(role="user", content=ctx.request.query),
        ]

        for turn in range(MAX_TURNS):
            response = provider.complete(messages=messages, tools=tool_specs)

            if not response.tool_calls:
                # Model produced final answer.
                return self._parse_final_briefing(response.text, ctx)

            # Echo the assistant turn that requested the tool calls so the
            # follow-up tool messages have the right linkage.
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.text or "",
                )
            )

            for call in response.tool_calls:
                result = self._dispatch(ctx, call)
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=_serialize_result_for_model(result),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

        logger.warning("agent hit MAX_TURNS=%d without a final answer", MAX_TURNS)
        return None

    def _dispatch(self, ctx: _RunCtx, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        ctx.step_counter += 1
        step_no = ctx.step_counter
        started = datetime.utcnow()
        t0 = time.monotonic()

        if tool is None:
            result = ToolResult(ok=False, error=f"unknown tool: {call.name}")
        else:
            try:
                result = tool.run(**call.arguments)
            except Exception as e:
                logger.exception("tool %s raised", call.name)
                result = ToolResult(ok=False, error=str(e))

        latency_ms = (time.monotonic() - t0) * 1000.0
        finished = datetime.utcnow()

        ws = WorkflowStep(
            step=step_no,
            tool=call.name,
            reason="model-selected",
            status="succeeded" if result.ok else "failed",
            started_at=started,
            finished_at=finished,
            output_summary=result.summary or (result.error if not result.ok else None),
        )
        ctx.workflow.append(ws)
        if result.citations:
            ctx.citations.extend(result.citations)

        self._insert_tool_call(
            ctx=ctx,
            step=step_no,
            tool_name=call.name,
            input_args=call.arguments,
            result=result,
            started_at=started,
            finished_at=finished,
            latency_ms=latency_ms,
        )
        return result

    # ----- briefing parsing -------------------------------------------------

    def _parse_final_briefing(self, text: str, ctx: _RunCtx) -> Briefing:
        """Best-effort: if the model emitted a JSON briefing, parse it.
        Otherwise wrap the freeform text as the executive summary."""
        text = (text or "").strip()
        parsed: dict[str, Any] | None = None
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None

        if parsed is None:
            return Briefing(
                title=_default_title(ctx.request.query),
                executive_summary=text or "(no answer produced)",
                evidence=[
                    EvidenceItem(source_id=did) for did in dict.fromkeys(ctx.citations)
                ],
            )

        return Briefing(
            title=parsed.get("title") or _default_title(ctx.request.query),
            executive_summary=parsed.get("executive_summary", ""),
            key_judgments=parsed.get("key_judgments", []) or [],
            timeline=parsed.get("timeline", []) or [],
            key_entities=parsed.get("key_entities", []) or [],
            evidence=parsed.get("evidence", []) or [
                EvidenceItem(source_id=did) for did in dict.fromkeys(ctx.citations)
            ],
            confidence_assessment=parsed.get("confidence_assessment"),
            information_gaps=parsed.get("information_gaps", []) or [],
            recommended_followup=parsed.get("recommended_followup", []) or [],
        )

    # ----- persistence ------------------------------------------------------

    def _insert_run(
        self,
        ctx: _RunCtx,
        provider_name: str,
        model: str | None,
        tool_mode: str,
    ) -> None:
        try:
            from shared.database.database import get_session
            from agent.models.agent_models import AgentRun
        except Exception:  # pragma: no cover
            logger.warning("agent_runs persistence unavailable", exc_info=True)
            return

        try:
            with get_session() as session:
                session.add(
                    AgentRun(
                        id=ctx.run_id,
                        session_id=ctx.request.session_id,
                        query=ctx.request.query,
                        time_window_hours=ctx.request.time_window_hours,
                        status="running",
                        provider=provider_name,
                        model=model,
                        tool_mode=tool_mode,
                    )
                )
        except Exception:  # pragma: no cover
            logger.exception("failed to insert agent_runs row")

    def _insert_tool_call(
        self,
        ctx: _RunCtx,
        step: int,
        tool_name: str,
        input_args: dict[str, Any],
        result: ToolResult,
        started_at: datetime,
        finished_at: datetime,
        latency_ms: float,
    ) -> None:
        try:
            from shared.database.database import get_session
            from agent.models.agent_models import AgentToolCall
        except Exception:  # pragma: no cover
            return
        try:
            with get_session() as session:
                session.add(
                    AgentToolCall(
                        run_id=ctx.run_id,
                        step=step,
                        tool_name=tool_name,
                        reason="model-selected",
                        input_args=input_args,
                        output_summary=result.summary,
                        output_payload=_jsonable(result.data),
                        citations=result.citations or None,
                        status="succeeded" if result.ok else "failed",
                        error=result.error,
                        started_at=started_at,
                        finished_at=finished_at,
                        latency_ms=latency_ms,
                    )
                )
        except Exception:  # pragma: no cover
            logger.exception("failed to insert agent_tool_calls row")

    def _finalize_run(
        self,
        ctx: _RunCtx,
        status: str,
        briefing: Briefing | None = None,
        error: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        try:
            from shared.database.database import get_session
            from agent.models.agent_models import AgentRun
        except Exception:  # pragma: no cover
            return
        try:
            with get_session() as session:
                row = session.get(AgentRun, ctx.run_id)
                if row is None:
                    return
                row.status = status
                row.error = error
                row.workflow = [_jsonable(ws.model_dump()) for ws in ctx.workflow]
                if briefing is not None:
                    row.briefing = _jsonable(briefing.model_dump())
                row.finished_at = datetime.utcnow()
                row.latency_ms = latency_ms
        except Exception:  # pragma: no cover
            logger.exception("failed to finalize agent_runs row")


# ----- helpers --------------------------------------------------------------


def _serialize_result_for_model(result: ToolResult) -> str:
    payload = {
        "ok": result.ok,
        "summary": result.summary,
        "data": _jsonable(result.data),
    }
    if not result.ok:
        payload["error"] = result.error
    return json.dumps(payload, default=str)


def _jsonable(obj: Any) -> Any:
    """Coerce arbitrary tool output to JSON-serializable form for storage."""
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return json.loads(json.dumps(obj, default=str))


def _default_title(query: str) -> str:
    q = query.strip()
    return q if len(q) <= 120 else q[:117] + "…"
