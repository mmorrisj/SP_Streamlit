"""Stage 2: Data Quality Assessment.

Queries the foundational database to characterize what's available for the
requested scope and period:
  * document count
  * event count
  * materiality distribution
  * top categories
  * gaps (e.g. months with no coverage)
  * sufficient? boolean
  * suggested_actions if data is thin

LLM role: optional summarization of gaps. Core computation is SQL.
TODO: wire to shared/database/database.py queries.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class DataQAStage(Stage):
    name = "data_qa"
    description = "Characterize data availability and quality for the requested scope."
    required = True
    depends_on = ["query_interpreter"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: implement against documents / canonical_events / event_summaries
        intent = ctx.require("query_interpreter").data
        stub_data = {
            "doc_count": 0,
            "event_count": 0,
            "materiality_distribution": {},
            "top_categories": [],
            "gaps": ["not_implemented: SQL queries pending"],
            "sufficient": False,
            "suggested_actions": [],
            "scope_evaluated": intent.get("scope"),
        }
        return StageResult(
            ok=True,
            data=stub_data,
            confidence=0.0,
            summary="data_qa: stub",
            notes=["stage body not yet implemented"],
        )


STAGE = DataQAStage()
