"""Stage 4: Anomaly / Signal Detector.

Surfaces what's unusual about this period relative to baseline. These are
the report's "lead items" — what an experienced analyst would mention up
top, distinct from the routine top-N event coverage.

Three deterministic signals, no LLM call:

  1. new_entity        canonical entities whose first_mention_date falls
                       inside the requested period AND are tied to one of
                       the top-N events. Filter floor: total_documents >= 3
                       so we skip incidental one-off mentions.

  2. category_spike    categories whose distinct-doc count in the current
                       period is >= 50% above the immediately-preceding
                       window of equal length, AND has >= 5 docs current.
                       Catches "X is suddenly all over the news."

  3. materiality_outlier  events whose material_score is more than
                       1.5 standard deviations above the in-scope mean.
                       Catches the disproportionate-impact events that
                       might not otherwise lead the rankings.

Co-occurrence anomalies (entity x category) are deliberately deferred —
high implementation cost, low signal-to-noise without careful
normalization. Add as a follow-up.

Each anomaly carries:
  kind         new_entity | category_spike | materiality_outlier
  description  human-readable lead-line, composed from the math
  magnitude    normalized strength (used for sorting; not a probability)
  evidence_ids doc_ids, entity_ids, or event_ids the analyst can drill into

Confidence:
  1.0  if the prior-period comparison had non-trivial data to compare against
  0.6  if prior-period was empty/sparse (current-period checks still ran)
  0.1  if no scope to evaluate
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from agent.workflows.base import Stage, StageResult, WorkflowContext
from agent.workflows.report.stages.data_qa import (
    _doc_scope_filters,
    _event_scope_filters,
)

logger = logging.getLogger(__name__)

NEW_ENTITY_MIN_DOCS = 3
CATEGORY_SPIKE_MIN_CURRENT_DOCS = 5
CATEGORY_SPIKE_MIN_DELTA_PCT = 0.5
MATERIALITY_Z_THRESHOLD = 1.5
MATERIALITY_SAMPLE_MINIMUM = 5  # below this, std dev isn't meaningful


class AnomalyStage(Stage):
    name = "anomaly"
    description = "Flag new entities, category spikes, and materiality outliers."
    required = False
    depends_on = ["query_interpreter", "data_qa", "event_prioritizer"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        intent = ctx.require("query_interpreter").data
        prioritized = ctx.require("event_prioritizer").data

        influencer = intent.get("influencer")
        recipient = intent.get("recipient")
        start_date = intent.get("start_date")
        end_date = intent.get("end_date")
        if not start_date or not end_date:
            return StageResult(ok=False, error="start_date and end_date required")

        top_event_ids = [
            e["event_id"]
            for e in (prioritized.get("events") or [])
            if e.get("event_id")
        ]

        prior_start, prior_end = _compute_prior_period(start_date, end_date)

        try:
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"database layer unavailable: {e}")

        anomalies: list[dict[str, Any]] = []
        prior_data_available = False

        try:
            with get_session() as session:
                if top_event_ids:
                    anomalies += _detect_new_entities(
                        session,
                        top_event_ids=top_event_ids,
                        start_date=start_date,
                        end_date=end_date,
                    )

                spikes, had_prior_data = _detect_category_spikes(
                    session,
                    influencer=influencer,
                    recipient=recipient,
                    current_start=start_date,
                    current_end=end_date,
                    prior_start=prior_start,
                    prior_end=prior_end,
                )
                anomalies += spikes
                prior_data_available = had_prior_data

                anomalies += _detect_materiality_outliers(
                    session,
                    influencer=influencer,
                    recipient=recipient,
                    start_date=start_date,
                    end_date=end_date,
                )
        except Exception as e:
            logger.exception("anomaly SQL failed")
            return StageResult(ok=False, error=f"anomaly query failed: {e}")

        # Highest-magnitude signals first.
        anomalies.sort(key=lambda a: a.get("magnitude") or 0.0, reverse=True)

        confidence = _confidence(
            scope_empty=not top_event_ids and not influencer and not recipient,
            prior_data_available=prior_data_available,
        )

        data: dict[str, Any] = {
            "anomalies": anomalies,
            "prior_period": {"start": prior_start, "end": prior_end},
            "method": "sql_baseline_v1",
            "counts_by_kind": _count_by_kind(anomalies),
        }
        return StageResult(
            ok=True,
            data=data,
            confidence=confidence,
            summary=f"anomaly: {len(anomalies)} signal(s) detected",
            notes=(
                ["prior-period baseline had no data; category_spike skipped"]
                if not prior_data_available else []
            ),
        )


# ---------------------------------------------------------------------------
# Detector: new entities
# ---------------------------------------------------------------------------

def _detect_new_entities(
    session,
    *,
    top_event_ids: list[str],
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            id::text                AS canonical_id,
            canonical_name          AS name,
            entity_type             AS entity_type,
            first_mention_date      AS first_mention_date,
            total_documents         AS total_documents,
            total_mention_days      AS total_mention_days
        FROM canonical_entities
        WHERE master_entity_id IS NULL
          AND first_mention_date BETWEEN :start_date AND :end_date
          AND associated_events && :event_ids
          AND total_documents >= :min_docs
        ORDER BY total_documents DESC
        LIMIT 12
    """
    rows = session.execute(
        text(sql),
        {
            "start_date": start_date,
            "end_date": end_date,
            "event_ids": top_event_ids,
            "min_docs": NEW_ENTITY_MIN_DOCS,
        },
    ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        entity_type = getattr(r.entity_type, "value", None) or str(r.entity_type)
        magnitude = float(min(1.0, (r.total_documents or 0) / 25.0))  # cap for sort
        out.append(
            {
                "kind": "new_entity",
                "description": (
                    f"New entity: {r.name} ({entity_type}) first appeared "
                    f"{r.first_mention_date} with {r.total_documents} doc(s) "
                    f"across {r.total_mention_days} day(s)"
                ),
                "magnitude": magnitude,
                "evidence_ids": [r.canonical_id],
                "entity_id": r.canonical_id,
                "entity_name": r.name,
                "entity_type": entity_type,
                "first_mention_date": str(r.first_mention_date),
                "total_documents": int(r.total_documents or 0),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Detector: category spikes vs prior period
# ---------------------------------------------------------------------------

def _detect_category_spikes(
    session,
    *,
    influencer: str | None,
    recipient: str | None,
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Returns (spikes, prior_data_available).

    Two queries — one per period — joined client-side. Could be a single
    query with a CTE but staying simple keeps each query plan obvious.
    """
    current_counts = _category_counts(
        session, influencer, recipient, current_start, current_end
    )
    prior_counts = _category_counts(
        session, influencer, recipient, prior_start, prior_end
    )
    prior_data_available = bool(prior_counts and sum(prior_counts.values()) > 0)

    if not prior_data_available:
        return [], False

    out: list[dict[str, Any]] = []
    for cat, curr in current_counts.items():
        if curr < CATEGORY_SPIKE_MIN_CURRENT_DOCS:
            continue
        prior = prior_counts.get(cat, 0)
        # Use 0.5 as floor to avoid div-by-zero ballooning the delta for
        # categories that simply didn't exist before.
        delta_pct = (curr - prior) / max(prior, 0.5)
        if delta_pct < CATEGORY_SPIKE_MIN_DELTA_PCT:
            continue

        # New-this-period categories get a small bonus to surface them.
        kind_note = "first appearance this period" if prior == 0 else f"vs {prior} prior"
        out.append(
            {
                "kind": "category_spike",
                "description": (
                    f"Category spike: {cat} — {curr} docs in current period "
                    f"({delta_pct:+.0%} {kind_note})"
                ),
                "magnitude": float(min(1.0, delta_pct / 2.0)),  # cap for sort
                "evidence_ids": [],  # filled by validator/UI on demand
                "category": cat,
                "current_count": curr,
                "prior_count": prior,
                "delta_pct": round(delta_pct, 3),
            }
        )
    return out, True


def _category_counts(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
) -> dict[str, int]:
    joins, where, params = _doc_scope_filters(influencer, recipient)
    params.update({"start_date": start_date, "end_date": end_date})
    sql = f"""
        SELECT c.category AS category, COUNT(DISTINCT d.doc_id) AS cnt
        FROM documents d
        JOIN categories c ON c.doc_id = d.doc_id
        {joins}
        WHERE d.date BETWEEN :start_date AND :end_date
          {where}
        GROUP BY c.category
    """
    rows = session.execute(text(sql), params).fetchall()
    return {r.category: int(r.cnt) for r in rows if r.category}


# ---------------------------------------------------------------------------
# Detector: materiality outliers
# ---------------------------------------------------------------------------

def _detect_materiality_outliers(
    session,
    *,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    where, params = _event_scope_filters(influencer, recipient)
    params.update({"start_date": start_date, "end_date": end_date})
    sql = f"""
        SELECT
            id::text             AS event_id,
            canonical_name       AS event_name,
            material_score       AS material_score,
            total_articles       AS total_articles,
            first_mention_date   AS first_mention_date,
            last_mention_date    AS last_mention_date
        FROM canonical_events
        WHERE master_event_id IS NULL
          AND NOT (last_mention_date < :start_date OR first_mention_date > :end_date)
          AND material_score IS NOT NULL
          {where}
    """
    rows = session.execute(text(sql), params).fetchall()
    scores = [float(r.material_score) for r in rows if r.material_score is not None]
    if len(scores) < MATERIALITY_SAMPLE_MINIMUM:
        # Not enough data to define an outlier — bail rather than fabricate
        # a baseline.
        return []

    mean = statistics.mean(scores)
    try:
        std = statistics.stdev(scores)
    except statistics.StatisticsError:
        return []
    if std == 0:
        return []

    threshold = mean + MATERIALITY_Z_THRESHOLD * std
    outliers: list[dict[str, Any]] = []
    for r in rows:
        score = float(r.material_score) if r.material_score is not None else None
        if score is None or score < threshold:
            continue
        z = (score - mean) / std
        outliers.append(
            {
                "kind": "materiality_outlier",
                "description": (
                    f"Materiality outlier: {r.event_name} — score {score:.1f} "
                    f"(z={z:.2f}, scope mean={mean:.2f}, std={std:.2f})"
                ),
                "magnitude": float(min(1.0, z / 3.0)),
                "evidence_ids": [r.event_id],
                "event_id": r.event_id,
                "event_name": r.event_name,
                "material_score": score,
                "z_score": round(z, 3),
                "scope_mean": round(mean, 3),
                "scope_std": round(std, 3),
                "total_articles": int(r.total_articles or 0),
            }
        )
    # Highest z first within materiality outliers.
    outliers.sort(key=lambda a: a["z_score"], reverse=True)
    return outliers[:6]  # cap so a flat-distribution scope doesn't flood


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_prior_period(start_date_str: str, end_date_str: str) -> tuple[str, str]:
    """Equal-length window immediately preceding [start, end]."""
    start = _parse_date(start_date_str)
    end = _parse_date(end_date_str)
    length_days = max(1, (end - start).days)
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=length_days)
    return prior_start.isoformat(), prior_end.isoformat()


def _parse_date(d: str) -> date:
    # Accept "YYYY-MM-DD" or full ISO datetime.
    if "T" in d:
        return datetime.fromisoformat(d).date()
    return date.fromisoformat(d)


def _count_by_kind(anomalies: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in anomalies:
        kind = a.get("kind") or "other"
        out[kind] = out.get(kind, 0) + 1
    return out


def _confidence(scope_empty: bool, prior_data_available: bool) -> float:
    if scope_empty:
        return 0.1
    if prior_data_available:
        return 1.0
    return 0.6


STAGE = AnomalyStage()
