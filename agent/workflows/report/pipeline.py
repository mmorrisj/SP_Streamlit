"""Report-workflow DAG definition.

Execution order is fixed and shown below. Each stage's `depends_on` is
declared on the stage class; the runner enforces that dependencies have
succeeded before running a dependent stage. Optional stages are marked
`required = False` and won't fail the run if they error out.

DAG:

    query_interpreter
            │
            ▼
        data_qa
            │
   ┌────────┼────────────────┐
   ▼        ▼                ▼
 event_   comparative_   trajectory
prioritizer  context
   │
   ├──► anomaly
   │
   ▼
event_narrator
   │
   ▼
claim_extractor
   │
   ▼
sourcing_claims
   │
   ▼
entity_curator
   │
   ▼
sourcing_entities
   │
   ▼
validator
"""
from __future__ import annotations

from agent.workflows.base import WorkflowContext, WorkflowRunner
from agent.workflows.report.stages import (
    anomaly,
    claim_extractor,
    comparative_context,
    data_qa,
    entity_curator,
    event_narrator,
    event_prioritizer,
    query_interpreter,
    sourcing_claims,
    sourcing_entities,
    trajectory,
    validator,
)

REPORT_STAGES = [
    query_interpreter.STAGE,
    data_qa.STAGE,
    event_prioritizer.STAGE,
    anomaly.STAGE,
    comparative_context.STAGE,
    trajectory.STAGE,
    event_narrator.STAGE,
    claim_extractor.STAGE,
    sourcing_claims.STAGE,
    entity_curator.STAGE,
    sourcing_entities.STAGE,
    validator.STAGE,
]

REPORT_PIPELINE = WorkflowRunner(stages=REPORT_STAGES, workflow_name="report")


def run_report(inputs: dict) -> WorkflowContext:
    """Synchronous entry point. Runs the full DAG and returns the
    accumulated WorkflowContext including all stage outputs."""
    return REPORT_PIPELINE.run(inputs)
