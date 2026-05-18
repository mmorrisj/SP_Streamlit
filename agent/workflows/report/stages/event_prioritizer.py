"""Stage 3: Event Prioritizer.

Ranks canonical events in scope by a composite of materiality and coverage,
returning the top-N for downstream narration. Same SQL universe as data_qa
(master events only, same scope filters, same date-overlap logic).

Composite score:
    composite = COALESCE(material_score, 0) * LN(total_articles + 1)

Rationale: material_score (0..10) captures concrete vs symbolic; LN of
article count rewards reach without letting a single high-coverage event
swamp the ranking. Events with no material_score still get a finite
ranking via the COALESCE so they aren't silently dropped.

No LLM call in v1 — prioritization is a deterministic SQL operation. A
future iteration may add an LLM re-rank pass for cases where the analyst
wants the events ordered by narrative importance rather than raw signal.

Inputs (from query_interpreter):
    scope, influencer, recipient, start_date, end_date

Outputs:
    events: list of PrioritizedEvent (top N by composite_score)
        event_id, event_name, materiality_score, coverage_score,
        composite_score, categories (top 3 from primary_categories JSONB),
        date_span (YYYY-MM-DD or YYYY-MM-DD to YYYY-MM-DD)
    method: 'materiality_x_log_coverage'
    top_n: N actually returned
    total_in_scope: total events that matched, before truncation

Confidence:
    1.0  if total_in_scope >= 2 * top_n  (clear ranking signal)
    0.7  if total_in_scope >= top_n
    0.4  if total_in_scope >= 3
    0.1  if fewer than 3 — ranking is meaningless with this little data
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from agent.workflows.base import Stage, StageResult, WorkflowContext
from agent.workflows.report.stages.data_qa import _event_scope_filters

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 8


class EventPrioritizerStage(Stage):
    name = "event_prioritizer"
    description = "Rank events by composite (materiality x log coverage); return top-N."
    required = True
    depends_on = ["query_interpreter", "data_qa"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        intent = ctx.require("query_interpreter").data
        qa = ctx.require("data_qa").data

        influencer = intent.get("influencer")
        recipient = intent.get("recipient")
        start_date = intent.get("start_date")
        end_date = intent.get("end_date")
        category = intent.get("category")
        region_recipients = intent.get("region_recipients")

        if not start_date or not end_date:
            return StageResult(ok=False, error="start_date and end_date required")

        try:
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"database layer unavailable: {e}")

        top_n = DEFAULT_TOP_N
        total_in_scope = int(qa.get("event_count") or 0)

        try:
            with get_session() as session:
                rows = _query_top_events(
                    session,
                    influencer=influencer,
                    recipient=recipient,
                    start_date=start_date,
                    end_date=end_date,
                    limit=top_n,
                    category=category,
                    region_recipients=region_recipients,
                )
        except Exception as e:
            logger.exception("event_prioritizer SQL failed")
            return StageResult(ok=False, error=f"event prioritizer query failed: {e}")

        events = [_row_to_event(r) for r in rows]
        confidence = _confidence(total_in_scope=total_in_scope, returned=len(events), top_n=top_n)

        data: dict[str, Any] = {
            "events": events,
            "method": "materiality_x_log_coverage",
            "top_n": top_n,
            "total_in_scope": total_in_scope,
        }
        return StageResult(
            ok=True,
            data=data,
            confidence=confidence,
            summary=f"event_prioritizer: top {len(events)} of {total_in_scope} events",
        )


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def _query_top_events(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
    limit: int,
    category: str | None = None,
    region_recipients: list[str] | None = None,
) -> list[Any]:
    where, params = _event_scope_filters(
        influencer, recipient,
        category=category, region_recipients=region_recipients,
    )
    params.update({"start_date": start_date, "end_date": end_date, "limit": limit})

    sql = f"""
        SELECT
            id::text                 AS event_id,
            canonical_name           AS event_name,
            initiating_country       AS initiating_country,
            first_mention_date       AS first_mention_date,
            last_mention_date        AS last_mention_date,
            total_mention_days       AS total_mention_days,
            total_articles           AS total_articles,
            story_phase              AS story_phase,
            primary_categories       AS primary_categories,
            primary_recipients       AS primary_recipients,
            material_score           AS material_score,
            COALESCE(material_score, 0) * LN(total_articles + 1) AS composite_score
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND NOT (last_mention_date < :start_date OR first_mention_date > :end_date)
          {where}
        ORDER BY composite_score DESC, total_articles DESC, last_mention_date DESC
        LIMIT :limit
    """
    return session.execute(text(sql), params).fetchall()


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------

def _row_to_event(row: Any) -> dict[str, Any]:
    primary_categories = row.primary_categories or {}
    if not isinstance(primary_categories, dict):
        primary_categories = {}

    top_categories = [
        c for c, _ in sorted(
            primary_categories.items(), key=lambda kv: kv[1], reverse=True
        )[:3]
    ]

    coverage_score = int(row.total_articles or 0)
    materiality_score = float(row.material_score) if row.material_score is not None else None
    composite_score = float(row.composite_score) if row.composite_score is not None else 0.0

    return {
        "event_id": row.event_id,
        "event_name": row.event_name,
        "initiating_country": row.initiating_country,
        "materiality_score": materiality_score,
        "coverage_score": coverage_score,
        "composite_score": round(composite_score, 3),
        "categories": top_categories,
        "date_span": _date_span(row.first_mention_date, row.last_mention_date),
        "total_mention_days": int(row.total_mention_days or 0),
        "story_phase": row.story_phase,
    }


def _date_span(first, last) -> str | None:
    if first is None and last is None:
        return None
    if first == last:
        return str(first)
    return f"{first} to {last}"


def _confidence(total_in_scope: int, returned: int, top_n: int) -> float:
    if total_in_scope >= 2 * top_n:
        return 1.0
    if total_in_scope >= top_n:
        return 0.7
    if total_in_scope >= 3:
        return 0.4
    return 0.1


STAGE = EventPrioritizerStage()
