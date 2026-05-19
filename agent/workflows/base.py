"""Stage / Runner primitives for structured workflows.

Design constraints:
  * Each Stage has a name, a typed run() method, and a `required` flag.
  * The WorkflowContext accumulates per-stage outputs; later stages read
    earlier outputs by stage name.
  * The Runner persists every stage's input, output, status, and timing
    so a workflow run is fully replayable / auditable.
  * Stage failures: if required, the run fails; if optional, the run
    continues with the stage's slot marked as `skipped_due_to_error`.
  * Confidence is a first-class output of every stage and propagates
    into the final assembled report.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Streaming callback signature. Receives one event dict per emission.
# Caller is responsible for non-blocking handling (e.g. putting on a queue).
WorkflowEventCallback = Callable[[dict[str, Any]], None]


@dataclass
class StageResult:
    """Output of a single stage. The orchestrator persists this verbatim."""
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None              # 0.0–1.0
    summary: str | None = None                   # one-line for the trace
    citations: list[str] = field(default_factory=list)  # doc_ids touched
    notes: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class WorkflowContext:
    """Shared state across stages.

    Stages should read `inputs` and `outputs[<prior_stage_name>]`. They
    should NOT mutate other stages' outputs.
    """
    run_id: UUID
    inputs: dict[str, Any]
    outputs: dict[str, StageResult] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def get(self, stage_name: str) -> StageResult | None:
        return self.outputs.get(stage_name)

    def require(self, stage_name: str) -> StageResult:
        result = self.outputs.get(stage_name)
        if result is None:
            raise KeyError(f"required upstream stage missing: {stage_name}")
        if not result.ok:
            raise RuntimeError(f"required upstream stage failed: {stage_name}")
        return result


class Stage(ABC):
    """Base class for a workflow stage."""

    name: str
    description: str
    required: bool = True
    # If a non-required dependency is missing, the stage may still run.
    # If a required dependency is missing, the stage is skipped.
    depends_on: list[str] = []

    def should_run(self, ctx: WorkflowContext) -> bool:
        """Hook: opt out of running based on context (e.g. data too sparse)."""
        return True

    @abstractmethod
    def run(self, ctx: WorkflowContext) -> StageResult:
        ...


class WorkflowRunner:
    """Executes a fixed sequence of stages and persists every step."""

    def __init__(self, stages: list[Stage], workflow_name: str) -> None:
        self.stages = stages
        self.workflow_name = workflow_name

    def run(
        self,
        inputs: dict[str, Any],
        *,
        on_event: WorkflowEventCallback | None = None,
    ) -> WorkflowContext:
        """Execute the DAG and return the accumulated context.

        If `on_event` is provided, it is invoked at five points so callers
        (e.g. an SSE endpoint) can stream progress without waiting for the
        full run to finish. Event kinds emitted (all dicts):

          workflow_started   {run_id, workflow, inputs, stage_names}
          stage_started      {run_id, stage_name, index, total}
          stage_skipped      {run_id, stage_name, index, total, reason}
          stage_complete     {run_id, stage_name, index, total, status,
                              summary, confidence, notes, output, error,
                              latency_ms}
          workflow_complete  {run_id, status, skipped_stages, error}

        Callback exceptions are swallowed so a broken consumer can't crash
        the workflow itself.
        """
        run_id = uuid4()
        ctx = WorkflowContext(run_id=run_id, inputs=inputs)

        self._persist_run_start(run_id, inputs)

        total = len(self.stages)
        self._emit(
            on_event,
            "workflow_started",
            {
                "run_id": str(run_id),
                "workflow": self.workflow_name,
                "inputs": inputs,
                "stage_names": [s.name for s in self.stages],
            },
        )

        run_started = time.monotonic()
        run_status = "succeeded"
        run_error: str | None = None

        for index, stage in enumerate(self.stages):
            if not self._dependencies_satisfied(stage, ctx):
                ctx.skipped.append(stage.name)
                self._persist_step(
                    run_id=run_id,
                    stage=stage,
                    started_at=datetime.utcnow(),
                    finished_at=datetime.utcnow(),
                    latency_ms=0.0,
                    result=StageResult(ok=False, error="upstream dependency unmet"),
                    status="skipped",
                )
                self._emit(
                    on_event,
                    "stage_skipped",
                    {
                        "run_id": str(run_id),
                        "stage_name": stage.name,
                        "index": index,
                        "total": total,
                        "reason": "upstream dependency unmet",
                    },
                )
                continue

            if not stage.should_run(ctx):
                ctx.skipped.append(stage.name)
                self._persist_step(
                    run_id=run_id,
                    stage=stage,
                    started_at=datetime.utcnow(),
                    finished_at=datetime.utcnow(),
                    latency_ms=0.0,
                    result=StageResult(ok=True, summary="opted out"),
                    status="skipped",
                )
                self._emit(
                    on_event,
                    "stage_skipped",
                    {
                        "run_id": str(run_id),
                        "stage_name": stage.name,
                        "index": index,
                        "total": total,
                        "reason": "opted out",
                    },
                )
                continue

            self._emit(
                on_event,
                "stage_started",
                {
                    "run_id": str(run_id),
                    "stage_name": stage.name,
                    "index": index,
                    "total": total,
                },
            )

            t0 = time.monotonic()
            started = datetime.utcnow()
            try:
                result = stage.run(ctx)
            except Exception as e:
                logger.exception("stage %s raised", stage.name)
                result = StageResult(ok=False, error=str(e))
            latency_ms = (time.monotonic() - t0) * 1000.0
            finished = datetime.utcnow()

            ctx.outputs[stage.name] = result

            status = "succeeded" if result.ok else "failed"
            self._persist_step(
                run_id=run_id,
                stage=stage,
                started_at=started,
                finished_at=finished,
                latency_ms=latency_ms,
                result=result,
                status=status,
            )
            self._emit(
                on_event,
                "stage_complete",
                {
                    "run_id": str(run_id),
                    "stage_name": stage.name,
                    "index": index,
                    "total": total,
                    "status": status,
                    "summary": result.summary,
                    "confidence": result.confidence,
                    "notes": result.notes or None,
                    "output": result.data or None,
                    "error": result.error,
                    "latency_ms": latency_ms,
                },
            )

            if not result.ok and stage.required:
                run_status = "failed"
                run_error = f"required stage {stage.name} failed: {result.error}"
                break

        self._persist_run_end(
            run_id=run_id,
            status=run_status,
            error=run_error,
            ctx=ctx,
            latency_ms=int((time.monotonic() - run_started) * 1000),
        )
        self._emit(
            on_event,
            "workflow_complete",
            {
                "run_id": str(run_id),
                "status": run_status,
                "skipped_stages": ctx.skipped,
                "error": run_error,
            },
        )
        return ctx

    @staticmethod
    def _emit(cb: WorkflowEventCallback | None, kind: str, payload: dict[str, Any]) -> None:
        if cb is None:
            return
        try:
            cb({"type": kind, **payload})
        except Exception:
            logger.exception("workflow event callback raised for %s", kind)

    # ----- helpers --------------------------------------------------------

    def _dependencies_satisfied(self, stage: Stage, ctx: WorkflowContext) -> bool:
        for dep in stage.depends_on or []:
            result = ctx.outputs.get(dep)
            if result is None or not result.ok:
                if stage.required:
                    return False
        return True

    # ----- persistence (lazy imports keep this module light) --------------

    def _persist_run_start(self, run_id: UUID, inputs: dict[str, Any]) -> None:
        try:
            from shared.database.database import get_session
            from agent.models.agent_models import AgentWorkflowRun
        except Exception:
            logger.warning("workflow persistence unavailable", exc_info=True)
            return
        try:
            with get_session() as session:
                session.add(
                    AgentWorkflowRun(
                        id=run_id,
                        workflow_name=self.workflow_name,
                        inputs=inputs,
                        status="running",
                    )
                )
        except Exception:
            logger.exception("failed to insert agent_workflow_runs row")

    def _persist_step(
        self,
        run_id: UUID,
        stage: Stage,
        started_at: datetime,
        finished_at: datetime,
        latency_ms: float,
        result: StageResult,
        status: str,
    ) -> None:
        try:
            from shared.database.database import get_session
            from agent.models.agent_models import AgentWorkflowStep
        except Exception:
            return
        try:
            with get_session() as session:
                session.add(
                    AgentWorkflowStep(
                        run_id=run_id,
                        stage_name=stage.name,
                        status=status,
                        summary=result.summary,
                        confidence=result.confidence,
                        citations=result.citations or None,
                        output=result.data or None,
                        error=result.error,
                        notes=result.notes or None,
                        started_at=started_at,
                        finished_at=finished_at,
                        latency_ms=latency_ms,
                    )
                )
        except Exception:
            logger.exception("failed to insert agent_workflow_steps row")

    def _persist_run_end(
        self,
        run_id: UUID,
        status: str,
        error: str | None,
        ctx: WorkflowContext,
        latency_ms: int,
    ) -> None:
        try:
            from shared.database.database import get_session
            from agent.models.agent_models import AgentWorkflowRun
        except Exception:
            return
        try:
            with get_session() as session:
                row = session.get(AgentWorkflowRun, run_id)
                if row is None:
                    return
                row.status = status
                row.error = error
                row.finished_at = datetime.utcnow()
                row.latency_ms = latency_ms
                row.skipped_stages = ctx.skipped or None
                row.confidence_summary = {
                    name: r.confidence
                    for name, r in ctx.outputs.items()
                    if r.confidence is not None
                } or None
        except Exception:
            logger.exception("failed to finalize agent_workflow_runs row")
