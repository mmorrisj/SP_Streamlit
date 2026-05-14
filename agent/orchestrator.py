"""Orchestrator: plan → execute → trace.

The orchestrator owns three responsibilities:
    1. Plan: emit a `workflow` list before any tool is executed.
    2. Execute: dispatch tool calls (native or json_fallback mode).
    3. Trace: record every tool call into agent_tool_calls for replay/audit.

Design is mode-agnostic — the same orchestrator drives commercial APIs and
enterprise on-prem LLMs through the provider interface in agent/llm/provider.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from agent.schemas import AnalyzeRequest, AnalyzeResponse, WorkflowStep
from agent.tools import get_registry

logger = logging.getLogger(__name__)


@dataclass
class RunContext:
    run_id: UUID
    request: AnalyzeRequest
    workflow: list[WorkflowStep] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)


class Orchestrator:
    def __init__(self) -> None:
        self.tools = get_registry()

    def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        ctx = RunContext(run_id=uuid4(), request=request)

        # TODO: replace deterministic plan with LLM-emitted plan once
        # agent/llm/provider.py providers are implemented.
        ctx.workflow = self._default_plan()

        # TODO: execute each step, persist agent_tool_calls rows, update
        # WorkflowStep.status/output_summary as tools run.

        return AnalyzeResponse(
            run_id=ctx.run_id,
            briefing=None,
            workflow=ctx.workflow,
            evidence=[],
            entities=[],
            timeline=[],
        )

    def _default_plan(self) -> list[WorkflowStep]:
        """Static fallback plan used until the LLM planner is wired."""
        now = datetime.now(timezone.utc)
        steps = [
            ("document_search", "Find relevant written reporting"),
            ("entity_lookup", "Resolve actors, organizations, and locations"),
            ("entity_graph", "Expand entity neighborhood for context"),
            ("event_timeline", "Order events chronologically"),
            ("corroboration_check", "Identify corroborating and conflicting sources"),
            ("country_grouping", "Group events by initiating and recipient country"),
            ("materiality_filter", "Focus on high-signal events"),
            ("citation_resolver", "Hydrate citations with source metadata"),
            ("briefing_generator", "Synthesize the analyst briefing"),
        ]
        return [
            WorkflowStep(step=i + 1, tool=name, reason=reason, status="pending")
            for i, (name, reason) in enumerate(steps)
        ]
