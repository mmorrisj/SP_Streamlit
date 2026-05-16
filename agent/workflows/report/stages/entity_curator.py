"""Stage 10: Entity Curator.

Reviews entities mentioned in the top-priority events and:
  * filters generic / obvious entities ("Chinese companies", "the government")
  * surfaces specific people, organizations, locations, vessels
  * writes a 1-2 sentence role synopsis per entity
  * ranks by influence within the cited events

LLM role: judgment-heavy — distinguishing generic from specific, writing
role descriptions grounded in evidence.

TODO: query canonical_entities + entity_relationships for top events;
filter heuristically (length, type, mention count); pass to LLM curator.
"""
from __future__ import annotations

from agent.workflows.base import Stage, StageResult, WorkflowContext


class EntityCuratorStage(Stage):
    name = "entity_curator"
    description = "Pick influential entities, drop generics, write role synopses."
    required = False
    depends_on = ["event_prioritizer", "event_narrator"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        # TODO: fetch canonical_entities tied to top event_ids, filter, summarize.
        return StageResult(
            ok=True,
            data={"entities": []},
            confidence=0.0,
            summary="entity_curator: stub (0 entities)",
            notes=["stage body not yet implemented"],
        )


STAGE = EntityCuratorStage()
