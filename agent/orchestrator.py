"""Orchestrator: plan -> execute -> trace.

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
    ChatScope,
    ChatTurn,
    ChatTurnRequest,
    ChatTurnResponse,
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

    # ----- chat intent classifier ------------------------------------------

    def classify_intent(self, request: ChatTurnRequest) -> ChatTurnResponse:
        """Single LLM call: classify a chat turn into an action + scope diff.

        Routes a natural-language message to one of four actions:
          propose_run    workflow + complete params; analyst clicks Run.
          update_scope   partial filter update without committing to a run.
          clarify        one focused question about a missing dimension.
          chat           small talk / help / off-topic; no scope change.

        Stateless: client maintains the thread + scope, server is pure
        function of (message, history, current_scope).
        """
        provider = get_provider()

        scope_dict = request.current_scope.model_dump()
        scope_json = json.dumps(scope_dict, indent=2)

        history_lines = []
        for turn in request.history[-12:]:  # cap context -- last 12 turns
            history_lines.append(f"{turn.role.upper()}: {turn.content}")
        history_dump = "\n".join(history_lines) if history_lines else "(no prior turns)"

        today = datetime.utcnow().date().isoformat()
        system_prompt = _build_intent_system_prompt(today=today)

        user_prompt = (
            f"CURRENT SCOPE (JSON):\n{scope_json}\n\n"
            f"CHAT HISTORY:\n{history_dump}\n\n"
            f"NEW USER MESSAGE:\n{request.message}\n\n"
            "Respond with JSON only, matching the schema in the system prompt."
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        try:
            response = provider.complete(
                messages=messages,
                tools=None,
                temperature=0.1,
                max_tokens=600,
            )
        except Exception as e:
            logger.exception("classify_intent LLM call failed")
            return ChatTurnResponse(
                action="chat",
                scope=request.current_scope,
                message=f"Sorry -- the classifier couldn't reach the LLM: {e}",
            )

        return _parse_intent_response(response.text, fallback_scope=request.current_scope)

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

            # Echo the assistant turn that requested the tool calls, including
            # the tool_calls list itself — OpenAI-compatible servers reject
            # role="tool" messages whose tool_call_id doesn't match a tool_calls
            # entry on the preceding assistant message.
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.text or "",
                    tool_calls=response.tool_calls,
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


# ---------------------------------------------------------------------------
# Intent classifier -- system prompt + response parsing.
# ---------------------------------------------------------------------------

_INTENT_SCHEMA_BLOCK = """\
Return STRICT JSON only -- no prose, no markdown fences. Schema:

{
  "action": "propose_run" | "update_scope" | "clarify" | "chat",
  "workflow": "report" | null,
  "scope": {
    "influencer": string | null,
    "recipient": string | null,
    "region": string | null,
    "start_date": "YYYY-MM-DD" | null,
    "end_date": "YYYY-MM-DD" | null,
    "category": "Economic" | "Diplomacy" | "Social" | "Military" | null,
    "subcategory": string | null,
    "category_mode": "flat" | "filter"
  },
  "message": "<assistant reply text, 1-3 sentences, plain prose>",
  "ready_to_run": true | false
}

The "scope" object is the FULL scope after applying any updates you inferred --
not a diff. Carry forward every field from CURRENT SCOPE that you didn't
change. The UI replaces its filter state with this object verbatim.

"ready_to_run" is true only when action == "propose_run" AND every required
param for the workflow is set.
"""


def _build_intent_system_prompt(today: str) -> str:
    return f"""\
You are an intent classifier for a soft-power analytics workflow runner.
Today's date is {today} (use this for relative time references like
"this quarter", "last month", "recent").

AVAILABLE WORKFLOWS

report -- generates a multi-stage soft-power report for one country pair
  or one country into a region.
  Required:
    influencer  country (e.g. "China", "Russia", "United States")
    Exactly one of:
      recipient  country (for bilateral analysis)
      region     region name (for regional analysis, e.g. "Middle East", "Africa")
    start_date   YYYY-MM-DD
    end_date     YYYY-MM-DD
  Optional:
    category        one of: Economic, Diplomacy, Social, Military
    subcategory     free-text (rarely used; only when analyst is precise)
    category_mode   "flat" (no filtering) | "filter" (single-category scope,
                    requires category to be set)

CONVENTIONS (apply silently -- do NOT ask about these)

- "X-Y" or "X-Y" or "X to Y" or "X in Y" or "X toward Y" or "X into Y"
  means X is the INFLUENCER, Y is the RECIPIENT. This is the standard
  soft-power framing: the influencer is the country whose outbound
  activity is being studied; the recipient is the destination of that
  activity.
    "China-Egypt" -> influencer=China, recipient=Egypt
    "Russia in Africa" -> influencer=Russia, region=Africa
    "what is China doing in the Middle East" -> influencer=China, region=Middle East

- Categorical phrases map to category + category_mode="filter":
    "economic activity" / "economic engagements" -> Economic
    "diplomatic activity" / "diplomatic engagements" -> Diplomacy
    "social initiatives" / "soft outreach" / "people-to-people" -> Social
    "military cooperation" / "defense activity" -> Military

- Time phrases (relative to today's date {today}):
    "this quarter" / "current quarter" -> current calendar quarter
    "last quarter" -> previous calendar quarter
    "last month" / "recent" / "past 30 days" -> last 30 days ending today
    "year-to-date" / "YTD" -> Jan 1 of current year through today
    "<year>" alone -> full calendar year

ACTIONS

1. propose_run -- analyst is ready to run. All required params present
   (after inferring sensible defaults). Set workflow + complete scope.
   Set ready_to_run=true. message: one-sentence acknowledgement like
   "Set scope to China -> Egypt, 2026-01-01 to 2026-03-31. Run when ready."

2. update_scope -- analyst is adjusting filters without explicitly asking
   to run (e.g. "actually make it Q2", "only economic activity"). Update
   only the relevant fields in scope; carry the rest forward. Set
   ready_to_run=false. message: brief acknowledgement of what changed.

3. clarify -- a required dimension is genuinely ambiguous AND cannot be
   resolved by the CONVENTIONS above. Ask ONE focused question. Do not
   update scope. Set workflow=null, ready_to_run=false.

4. chat -- greeting, help request, or off-topic. No scope change. Set
   workflow=null, ready_to_run=false. Be brief and helpful.

CLARIFICATION PRIORITY (only ask for the SINGLE most impactful gap)

  1. influencer (which country's outbound activity? -- but apply the
     CONVENTIONS first; only ask if the message genuinely doesn't name
     a country or names countries in a way conventions don't resolve)
  2. recipient vs region (bilateral or regional analysis?)
  3. date range (only if no defaults could be reasonably inferred)
  4. category (only if analyst hinted at filtering but was vague)

Never ask more than one question in a single turn. If multiple things are
missing, ask about the highest-priority one and leave the rest unset.

EXAMPLES

Input: "brief on China-Egypt economic activity this quarter"
  -> action=propose_run, influencer=China, recipient=Egypt,
    category=Economic, category_mode=filter,
    start_date+end_date = current calendar quarter,
    ready_to_run=true.

Input: "what's China doing in the Middle East?"
  -> action=propose_run, influencer=China, region=Middle East,
    start_date+end_date = current calendar quarter (default time scope),
    category=null, category_mode=flat, ready_to_run=true.

Input: "give me a brief"
  -> action=clarify, message=Which country's outbound activity should I
    look at?

Input: "actually only economic"
  (current scope has influencer=China, recipient=Egypt, dates set)
  -> action=update_scope, category=Economic, category_mode=filter,
    everything else carried forward, ready_to_run=false.

{_INTENT_SCHEMA_BLOCK}
"""


def _parse_intent_response(
    raw_text: str, fallback_scope: ChatScope
) -> ChatTurnResponse:
    """Parse the LLM's JSON response into a ChatTurnResponse.

    Tolerates surrounding whitespace, leading prose, and accidental
    markdown fences. On any parse failure returns a `chat` action that
    echoes the raw text so the user at least sees something.
    """
    text = (raw_text or "").strip()
    if not text:
        return ChatTurnResponse(
            action="chat",
            scope=fallback_scope,
            message="(empty response from classifier)",
        )

    # Strip ```json fences and find the first {...} block.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ChatTurnResponse(
            action="chat",
            scope=fallback_scope,
            message=text,
        )
    blob = text[start : end + 1]

    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return ChatTurnResponse(
            action="chat",
            scope=fallback_scope,
            message=text,
        )

    action = (data.get("action") or "chat").strip()
    if action not in {"propose_run", "update_scope", "clarify", "chat"}:
        action = "chat"

    raw_scope = data.get("scope") or {}
    # Merge against fallback so missing fields fall back to current scope
    # rather than being nulled out by an LLM that returned a partial object.
    merged_scope = fallback_scope.model_dump()
    for k, v in raw_scope.items():
        if k in merged_scope:
            merged_scope[k] = v
    if not merged_scope.get("category_mode"):
        merged_scope["category_mode"] = "flat"

    return ChatTurnResponse(
        action=action,
        workflow=data.get("workflow"),
        scope=ChatScope(**merged_scope),
        message=(data.get("message") or "").strip() or "(no message)",
        ready_to_run=bool(data.get("ready_to_run")),
    )
