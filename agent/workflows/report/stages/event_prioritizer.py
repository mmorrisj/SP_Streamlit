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

# When scope is regional, fetch a larger candidate pool so the per-recipient
# balancing step has room to spread picks across multiple countries. With
# 19 recipients in the Middle East config and per_recipient=2, the upper
# bound on candidates that matter is 38; pulling 50 covers it comfortably
# while staying cheap.
REGIONAL_CANDIDATE_LIMIT = 50

# Max events to pick from any single recipient when balancing. Two leaves
# room for follow-on events on the same story while still forcing the
# remaining slots in top-N to come from other countries.
PER_RECIPIENT_CAP = 2


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

        # Regional scope: fetch a wider candidate pool so the balancing
        # pass downstream has room to spread picks across recipients
        # rather than letting whichever 1-2 countries have the highest
        # composite scores monopolize the slot list. Bilateral scope has
        # only one recipient anyway, so no need to over-fetch.
        candidate_limit = REGIONAL_CANDIDATE_LIMIT if region_recipients else top_n

        try:
            with get_session() as session:
                rows = _query_top_events(
                    session,
                    influencer=influencer,
                    recipient=recipient,
                    start_date=start_date,
                    end_date=end_date,
                    limit=candidate_limit,
                    category=category,
                    region_recipients=region_recipients,
                )
        except Exception as e:
            logger.exception("event_prioritizer SQL failed")
            return StageResult(ok=False, error=f"event prioritizer query failed: {e}")

        candidates = [_row_to_event(r) for r in rows]

        if region_recipients:
            events = _balance_by_recipient(candidates, top_n=top_n, per_recipient=PER_RECIPIENT_CAP)
            method = "materiality_x_log_coverage_balanced_by_recipient"
        else:
            events = candidates[:top_n]
            method = "materiality_x_log_coverage"

        confidence = _confidence(total_in_scope=total_in_scope, returned=len(events), top_n=top_n)

        # Distribution surfaces in the UI so the analyst can see at a
        # glance how the regional pick split across countries.
        distribution: dict[str, int] = {}
        for e in events:
            r = e.get("primary_recipient")
            if r:
                distribution[r] = distribution.get(r, 0) + 1

        data: dict[str, Any] = {
            "events": events,
            "method": method,
            "top_n": top_n,
            "total_in_scope": total_in_scope,
            "candidate_pool_size": len(candidates),
            "recipient_distribution": distribution or None,
            "per_recipient_cap": PER_RECIPIENT_CAP if region_recipients else None,
        }

        summary = f"event_prioritizer: top {len(events)} of {total_in_scope} events"
        if region_recipients and distribution:
            summary += f" (across {len(distribution)} recipients)"

        return StageResult(
            ok=True,
            data=data,
            confidence=confidence,
            summary=summary,
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

    primary_recipients = row.primary_recipients or {}
    if not isinstance(primary_recipients, dict):
        primary_recipients = {}

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
        "primary_recipient": _primary_recipient(primary_recipients),
        "primary_recipients": primary_recipients,
        "date_span": _date_span(row.first_mention_date, row.last_mention_date),
        "total_mention_days": int(row.total_mention_days or 0),
        "story_phase": row.story_phase,
    }


def _primary_recipient(primary_recipients: dict[str, Any]) -> str | None:
    """Return the recipient key with the highest mention count.

    primary_recipients is the canonical_events JSONB column shaped as
    {country: mention_count}. Ties broken alphabetically so picks are
    deterministic across runs.
    """
    if not primary_recipients:
        return None
    try:
        items = sorted(
            primary_recipients.items(),
            key=lambda kv: (-int(kv[1] or 0), kv[0]),
        )
        return items[0][0] if items else None
    except Exception:
        # Pathological JSONB (non-numeric values, etc.); fall back to
        # alphabetic first key rather than crash the stage.
        keys = sorted(primary_recipients.keys())
        return keys[0] if keys else None


def _balance_by_recipient(
    events: list[dict[str, Any]],
    top_n: int,
    per_recipient: int,
) -> list[dict[str, Any]]:
    """Return top_n events balanced across primary recipients.

    Each event is assigned to its primary recipient (highest count in
    primary_recipients JSONB). At most `per_recipient` events per
    recipient are picked from the candidate pool; if that leaves fewer
    than top_n picks, the remaining slots are filled from the global
    composite-score ranking of unpicked candidates. Final list is
    re-sorted by composite_score so the UI's top-down rendering still
    reads as "highest impact first".

    Falls back to plain top_n by composite_score when only zero or one
    recipient is represented in the candidate pool -- balancing has
    nothing to do at that point.
    """
    if not events:
        return []

    by_recipient: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        primary = e.get("primary_recipient")
        if not primary:
            continue
        by_recipient.setdefault(primary, []).append(e)

    if len(by_recipient) <= 1:
        events_sorted = sorted(events, key=_score_key, reverse=True)
        return events_sorted[:top_n]

    # First pass: take up to per_recipient from each, ranked by score
    # within that recipient's bucket.
    balanced: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in by_recipient.values():
        bucket.sort(key=_score_key, reverse=True)
        for ev in bucket[:per_recipient]:
            eid = ev.get("event_id")
            if eid and eid not in seen:
                balanced.append(ev)
                seen.add(eid)

    # Second pass: if we have slack, fill with the next-highest unpicked
    # events globally. Keeps us from under-shooting top_n when only a few
    # recipients have material events.
    if len(balanced) < top_n:
        remaining = [e for e in events if e.get("event_id") not in seen]
        remaining.sort(key=_score_key, reverse=True)
        balanced.extend(remaining[: top_n - len(balanced)])

    balanced.sort(key=_score_key, reverse=True)
    return balanced[:top_n]


def _score_key(event: dict[str, Any]) -> float:
    return float(event.get("composite_score") or 0)


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
