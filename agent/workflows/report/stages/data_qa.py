"""Stage 2: Data Quality Assessment.

Characterizes data availability for the requested scope and period using
read-only SQL against the foundation tables. No LLM call in v1 — the
output is deterministic from the database state.

Inputs (from query_interpreter):
    scope        bilateral | regional
    influencer   country name or None
    recipient    country name or None
    region       region label or None  (currently treated as 'no extra filter')
    start_date   ISO date string
    end_date     ISO date string

Outputs:
    doc_count                 distinct documents matching scope+dates
    event_count               canonical events overlapping the date range
    materiality_distribution  {low|med|high|unscored: count}
    top_categories            [{category, doc_count}, ...]
    gaps                      [<YYYY-MM string with zero docs>, ...]
    sufficient                bool — meets the threshold for a useful report
    suggested_actions         strings describing remediation if not sufficient
    confidence                0..1, derived from data volume

Confidence heuristic:
    1.0  if doc_count >= 200 and event_count >= 10
    0.7  if doc_count >= 50  and event_count >= 5
    0.4  if doc_count >= 20  and event_count >= 3
    0.1  otherwise (insufficient — body still returns ok=True but flags it)
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from agent.workflows.base import Stage, StageResult, WorkflowContext

logger = logging.getLogger(__name__)

# Sufficiency thresholds — surfaced as constants so they're easy to tune.
_SUFFICIENT_DOC_FLOOR = 20
_SUFFICIENT_EVENT_FLOOR = 3


class DataQAStage(Stage):
    name = "data_qa"
    description = "Characterize data availability and quality for the requested scope."
    required = True
    depends_on = ["query_interpreter"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        intent = ctx.require("query_interpreter").data
        scope = intent.get("scope")
        influencer = intent.get("influencer")
        recipient = intent.get("recipient")
        start_date = intent.get("start_date")
        end_date = intent.get("end_date")

        if not start_date or not end_date:
            return StageResult(
                ok=False,
                error="start_date and end_date are required for data QA",
            )

        try:
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"database layer unavailable: {e}")

        try:
            with get_session() as session:
                doc_count = _doc_count(session, influencer, recipient, start_date, end_date)
                event_stats = _event_stats(session, influencer, recipient, start_date, end_date)
                materiality_distribution = _materiality_buckets(
                    session, influencer, recipient, start_date, end_date
                )
                top_categories = _top_categories(
                    session, influencer, recipient, start_date, end_date, limit=8
                )
                gaps = _monthly_gaps(
                    session, influencer, recipient, start_date, end_date
                )
        except Exception as e:
            logger.exception("data_qa SQL failed")
            return StageResult(ok=False, error=f"data_qa query failed: {e}")

        event_count = event_stats["event_count"]
        sufficient = (
            doc_count >= _SUFFICIENT_DOC_FLOOR and event_count >= _SUFFICIENT_EVENT_FLOOR
        )
        confidence = _confidence(doc_count, event_count)

        suggested_actions: list[str] = []
        if not sufficient:
            if doc_count < _SUFFICIENT_DOC_FLOOR:
                suggested_actions.append(
                    f"Doc count ({doc_count}) below floor ({_SUFFICIENT_DOC_FLOOR}); "
                    "consider broadening the date range or recipient scope."
                )
            if event_count < _SUFFICIENT_EVENT_FLOOR:
                suggested_actions.append(
                    f"Event count ({event_count}) below floor ({_SUFFICIENT_EVENT_FLOOR}); "
                    "consider broadening the date range."
                )
        if gaps:
            suggested_actions.append(
                f"{len(gaps)} month(s) with no coverage in the requested range: "
                + ", ".join(gaps[:6])
                + ("…" if len(gaps) > 6 else "")
            )

        data: dict[str, Any] = {
            "scope": scope,
            "filters": {
                "influencer": influencer,
                "recipient": recipient,
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
            "doc_count": doc_count,
            "event_count": event_count,
            "event_aggregates": event_stats,
            "materiality_distribution": materiality_distribution,
            "top_categories": top_categories,
            "gaps": gaps,
            "sufficient": sufficient,
            "suggested_actions": suggested_actions,
        }

        summary = (
            f"data_qa: {doc_count} docs / {event_count} events"
            + (" — sufficient" if sufficient else " — insufficient")
        )
        return StageResult(
            ok=True,
            data=data,
            confidence=confidence,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _doc_count(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
) -> int:
    """Count distinct documents matching scope + date range.

    Uses the normalized join tables (initiating_countries / recipient_countries)
    because a single document can have multiple initiators or recipients."""
    joins, where, params = _doc_scope_filters(influencer, recipient)
    params.update({"start_date": start_date, "end_date": end_date})

    sql = f"""
        SELECT COUNT(DISTINCT d.doc_id) AS cnt
        FROM documents d
        {joins}
        WHERE d.date BETWEEN :start_date AND :end_date
          {where}
    """
    row = session.execute(text(sql), params).first()
    return int(row.cnt) if row and row.cnt is not None else 0


def _event_stats(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Count canonical events overlapping the date range + aggregate stats."""
    where, params = _event_scope_filters(influencer, recipient)
    params.update({"start_date": start_date, "end_date": end_date})

    sql = f"""
        SELECT
            COUNT(*) AS event_count,
            SUM(total_articles) AS total_articles,
            SUM(total_mention_days) AS total_mention_days,
            AVG(material_score) AS avg_materiality
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND NOT (last_mention_date < :start_date OR first_mention_date > :end_date)
          {where}
    """
    row = session.execute(text(sql), params).first()
    return {
        "event_count": int(row.event_count) if row and row.event_count else 0,
        "total_articles": int(row.total_articles) if row and row.total_articles else 0,
        "total_mention_days": (
            int(row.total_mention_days) if row and row.total_mention_days else 0
        ),
        "avg_materiality": (
            float(row.avg_materiality) if row and row.avg_materiality is not None else None
        ),
    }


def _materiality_buckets(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
) -> dict[str, int]:
    """Bucket overlapping canonical events by material_score."""
    where, params = _event_scope_filters(influencer, recipient)
    params.update({"start_date": start_date, "end_date": end_date})

    sql = f"""
        SELECT
            COUNT(*) FILTER (WHERE material_score < 4)                AS low,
            COUNT(*) FILTER (WHERE material_score >= 4 AND material_score < 7) AS med,
            COUNT(*) FILTER (WHERE material_score >= 7)               AS high,
            COUNT(*) FILTER (WHERE material_score IS NULL)            AS unscored
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND NOT (last_mention_date < :start_date OR first_mention_date > :end_date)
          {where}
    """
    row = session.execute(text(sql), params).first()
    return {
        "low": int(row.low) if row and row.low else 0,
        "med": int(row.med) if row and row.med else 0,
        "high": int(row.high) if row and row.high else 0,
        "unscored": int(row.unscored) if row and row.unscored else 0,
    }


def _top_categories(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Top categories by distinct-document count within the scope."""
    joins, where, params = _doc_scope_filters(influencer, recipient)
    params.update({"start_date": start_date, "end_date": end_date, "limit": limit})

    sql = f"""
        SELECT c.category AS category, COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN categories c ON c.doc_id = d.doc_id
        {joins}
        WHERE d.date BETWEEN :start_date AND :end_date
          {where}
        GROUP BY c.category
        ORDER BY doc_count DESC
        LIMIT :limit
    """
    rows = session.execute(text(sql), params).fetchall()
    return [{"category": r.category, "doc_count": int(r.doc_count)} for r in rows]


def _monthly_gaps(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
) -> list[str]:
    """Return months (YYYY-MM) within [start_date, end_date] that have zero docs."""
    joins, where, params = _doc_scope_filters(influencer, recipient)
    params.update({"start_date": start_date, "end_date": end_date})

    sql = f"""
        WITH months AS (
            SELECT generate_series(
                date_trunc('month', CAST(:start_date AS date)),
                date_trunc('month', CAST(:end_date AS date)),
                interval '1 month'
            )::date AS month_start
        ),
        present AS (
            SELECT date_trunc('month', d.date)::date AS month_start
            FROM documents d
            {joins}
            WHERE d.date BETWEEN :start_date AND :end_date
              {where}
            GROUP BY 1
        )
        SELECT to_char(m.month_start, 'YYYY-MM') AS yyyymm
        FROM months m
        LEFT JOIN present p ON p.month_start = m.month_start
        WHERE p.month_start IS NULL
        ORDER BY m.month_start
    """
    rows = session.execute(text(sql), params).fetchall()
    return [r.yyyymm for r in rows]


# ---------------------------------------------------------------------------
# Scope-filter builders
# ---------------------------------------------------------------------------

def _doc_scope_filters(
    influencer: str | None, recipient: str | None
) -> tuple[str, str, dict[str, Any]]:
    """Build join clauses + where clauses + params for document-level scope.

    Returns (joins_sql, where_sql, params). Where clause starts with 'AND'
    so callers can append it after their own WHERE."""
    joins_parts: list[str] = []
    where_parts: list[str] = []
    params: dict[str, Any] = {}

    if influencer:
        joins_parts.append(
            "JOIN initiating_countries ic ON ic.doc_id = d.doc_id"
        )
        where_parts.append("AND ic.initiating_country = :influencer")
        params["influencer"] = influencer
    if recipient:
        joins_parts.append(
            "JOIN recipient_countries rc ON rc.doc_id = d.doc_id"
        )
        where_parts.append("AND rc.recipient_country = :recipient")
        params["recipient"] = recipient

    return "\n        ".join(joins_parts), "\n          ".join(where_parts), params


def _event_scope_filters(
    influencer: str | None, recipient: str | None
) -> tuple[str, dict[str, Any]]:
    """Build where clauses + params for canonical_event-level scope.

    Returns (where_sql, params). Where clause starts with 'AND'.
    primary_recipients is JSONB {country: mention_count}; we check key presence."""
    where_parts: list[str] = []
    params: dict[str, Any] = {}

    if influencer:
        where_parts.append("AND initiating_country = :influencer")
        params["influencer"] = influencer
    if recipient:
        where_parts.append("AND primary_recipients ? :recipient")
        params["recipient"] = recipient

    return "\n          ".join(where_parts), params


def _confidence(doc_count: int, event_count: int) -> float:
    if doc_count >= 200 and event_count >= 10:
        return 1.0
    if doc_count >= 50 and event_count >= 5:
        return 0.7
    if doc_count >= _SUFFICIENT_DOC_FLOOR and event_count >= _SUFFICIENT_EVENT_FLOOR:
        return 0.4
    return 0.1


STAGE = DataQAStage()
