"""Stage 6: Trajectory.

Labels the direction of the requested scope vs the immediately-preceding
window of equal length: accelerating / steady / cooling.

Four signals voted on:
  - document volume delta
  - event count delta
  - average materiality delta (relative to prior period mean)
  - total article coverage delta (sum of total_articles in scope)

Each signal votes weighted (+2 strong, +1 moderate, 0 steady, -1 moderate
cool, -2 strong cool). Final direction is the sign of the weighted sum.
Confidence is derived from the magnitude of the sum and whether the
prior period had enough data to compare against.

No LLM call. Evidence strings are composed deterministically from the
numbers so the same inputs always produce the same trajectory readout.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from agent.workflows.base import Stage, StageResult, WorkflowContext
from agent.workflows.report.stages.data_qa import (
    _doc_scope_filters,
    _event_scope_filters,
)

logger = logging.getLogger(__name__)

# Per-signal thresholds (fraction). Anything in [-MODERATE, MODERATE] is "steady."
SIGNAL_MODERATE_THRESHOLD = 0.20
SIGNAL_STRONG_THRESHOLD = 0.50

# For materiality (bounded 0-10), use absolute-point thresholds since
# percentage deltas are misleading near zero.
MATERIALITY_MODERATE_POINTS = 0.5
MATERIALITY_STRONG_POINTS = 1.5

# Minimum prior-period documents to trust the comparison.
PRIOR_PERIOD_MIN_DOCS = 5


class TrajectoryStage(Stage):
    name = "trajectory"
    description = "Label direction (accelerating/steady/cooling) vs prior period of equal length."
    required = False
    depends_on = ["query_interpreter", "data_qa"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        intent = ctx.require("query_interpreter").data
        qa = ctx.require("data_qa").data

        influencer = intent.get("influencer")
        recipient = intent.get("recipient")
        start_date = intent.get("start_date")
        end_date = intent.get("end_date")
        category = intent.get("category")
        if not start_date or not end_date:
            return StageResult(ok=False, error="start_date and end_date required")

        prior_start, prior_end = _compute_prior_period(start_date, end_date)

        # Current numbers are already in data_qa's output; no need to re-query.
        current = {
            "doc_count": int(qa.get("doc_count") or 0),
            "event_count": int(qa.get("event_count") or 0),
            "total_articles": int(
                (qa.get("event_aggregates") or {}).get("total_articles") or 0
            ),
            "avg_materiality": (qa.get("event_aggregates") or {}).get("avg_materiality"),
        }

        try:
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"database layer unavailable: {e}")

        try:
            with get_session() as session:
                prior = _fetch_period_totals(
                    session, influencer, recipient, prior_start, prior_end,
                    category=category,
                )
        except Exception as e:
            logger.exception("trajectory prior-period query failed")
            return StageResult(ok=False, error=f"prior-period query failed: {e}")

        prior_has_data = prior["doc_count"] >= PRIOR_PERIOD_MIN_DOCS

        if not prior_has_data:
            return StageResult(
                ok=True,
                data={
                    "direction": "steady",
                    "confidence": "LOW",
                    "evidence": [],
                    "prior_period": {"start": prior_start, "end": prior_end},
                    "prior_period_summary": _format_period_summary(prior, prior_start, prior_end),
                    "current_period_summary": _format_period_summary(
                        current, start_date, end_date
                    ),
                    "reason": (
                        f"Prior period has only {prior['doc_count']} docs "
                        f"(floor: {PRIOR_PERIOD_MIN_DOCS}); trajectory cannot be reliably computed"
                    ),
                },
                confidence=0.2,
                summary="trajectory: steady (LOW — prior period too sparse to compare)",
                notes=[
                    f"prior period {prior_start} to {prior_end} had {prior['doc_count']} docs; "
                    f"need at least {PRIOR_PERIOD_MIN_DOCS}"
                ],
            )

        signals = _compute_signals(current, prior)
        direction, label_confidence, score = _label_direction(signals)
        evidence = _format_evidence(signals)

        data = {
            "direction": direction,
            "confidence": label_confidence,
            "score": score,
            "evidence": evidence,
            "signals": signals,
            "prior_period": {"start": prior_start, "end": prior_end},
            "prior_period_summary": _format_period_summary(prior, prior_start, prior_end),
            "current_period_summary": _format_period_summary(current, start_date, end_date),
        }

        return StageResult(
            ok=True,
            data=data,
            confidence=_stage_confidence(label_confidence),
            summary=f"trajectory: {direction} ({label_confidence}, score={score:+d})",
        )


# ---------------------------------------------------------------------------
# SQL: prior-period totals
# ---------------------------------------------------------------------------

def _fetch_period_totals(
    session,
    influencer: str | None,
    recipient: str | None,
    start_date: str,
    end_date: str,
    category: str | None = None,
) -> dict[str, Any]:
    """Mirror data_qa's current-period numbers for any [start, end] window.

    Two queries — one against documents (for doc_count), one against
    canonical_events (for event_count + aggregates). Same scope filter
    helpers used by data_qa and anomaly.
    """
    # Documents
    doc_joins, doc_where, doc_params = _doc_scope_filters(
        influencer, recipient, category=category
    )
    doc_params.update({"start_date": start_date, "end_date": end_date})
    doc_row = session.execute(
        text(f"""
            SELECT COUNT(DISTINCT d.doc_id) AS cnt
            FROM documents d
            {doc_joins}
            WHERE d.date BETWEEN :start_date AND :end_date
              {doc_where}
        """),
        doc_params,
    ).first()
    doc_count = int(doc_row.cnt) if doc_row and doc_row.cnt else 0

    # Events
    event_where, event_params = _event_scope_filters(
        influencer, recipient, category=category
    )
    event_params.update({"start_date": start_date, "end_date": end_date})
    event_row = session.execute(
        text(f"""
            SELECT
                COUNT(*)                     AS event_count,
                SUM(total_articles)          AS total_articles,
                AVG(material_score)          AS avg_materiality
            FROM canonical_events
            WHERE master_event_id IS NULL
              AND NOT (last_mention_date < :start_date OR first_mention_date > :end_date)
              {event_where}
        """),
        event_params,
    ).first()

    return {
        "doc_count": doc_count,
        "event_count": int(event_row.event_count) if event_row and event_row.event_count else 0,
        "total_articles": (
            int(event_row.total_articles) if event_row and event_row.total_articles else 0
        ),
        "avg_materiality": (
            float(event_row.avg_materiality)
            if event_row and event_row.avg_materiality is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Signal computation + voting
# ---------------------------------------------------------------------------

def _compute_signals(current: dict[str, Any], prior: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute the four signals with their per-signal votes (-2..+2)."""
    signals: list[dict[str, Any]] = []

    signals.append(_pct_signal(
        label="document volume",
        current=current["doc_count"],
        prior=prior["doc_count"],
    ))
    signals.append(_pct_signal(
        label="event count",
        current=current["event_count"],
        prior=prior["event_count"],
    ))
    signals.append(_pct_signal(
        label="article coverage",
        current=current["total_articles"],
        prior=prior["total_articles"],
    ))
    signals.append(_materiality_signal(
        current=current.get("avg_materiality"),
        prior=prior.get("avg_materiality"),
    ))
    return signals


def _pct_signal(label: str, current: int, prior: int) -> dict[str, Any]:
    if prior == 0 and current == 0:
        return {
            "label": label, "current": current, "prior": prior,
            "delta_pct": None, "vote": 0, "available": False,
        }
    if prior == 0:
        # All-new — treat as strongly accelerating.
        return {
            "label": label, "current": current, "prior": prior,
            "delta_pct": None, "vote": 2, "available": True,
            "note": "no prior-period baseline; entirely new this period",
        }
    delta = (current - prior) / prior
    vote = _vote_from_delta(delta, SIGNAL_MODERATE_THRESHOLD, SIGNAL_STRONG_THRESHOLD)
    return {
        "label": label, "current": current, "prior": prior,
        "delta_pct": round(delta, 3), "vote": vote, "available": True,
    }


def _materiality_signal(current: float | None, prior: float | None) -> dict[str, Any]:
    """Materiality is bounded 0-10; use absolute-point thresholds, not pct."""
    if current is None and prior is None:
        return {
            "label": "average materiality", "current": None, "prior": None,
            "delta_points": None, "vote": 0, "available": False,
        }
    if current is None:
        return {
            "label": "average materiality", "current": None, "prior": prior,
            "delta_points": None, "vote": -1, "available": True,
            "note": "no scored events this period",
        }
    if prior is None:
        return {
            "label": "average materiality", "current": current, "prior": None,
            "delta_points": None, "vote": 1, "available": True,
            "note": "no scored events in prior period for comparison",
        }
    delta = current - prior
    vote = _vote_from_delta(
        delta, MATERIALITY_MODERATE_POINTS, MATERIALITY_STRONG_POINTS
    )
    return {
        "label": "average materiality",
        "current": round(current, 3),
        "prior": round(prior, 3),
        "delta_points": round(delta, 3),
        "vote": vote,
        "available": True,
    }


def _vote_from_delta(delta: float, moderate: float, strong: float) -> int:
    if delta >= strong:
        return 2
    if delta >= moderate:
        return 1
    if delta <= -strong:
        return -2
    if delta <= -moderate:
        return -1
    return 0


def _label_direction(signals: list[dict[str, Any]]) -> tuple[str, str, int]:
    """Return (direction, confidence, score).

    direction  accelerating | steady | cooling
    confidence LOW | MED | HIGH (string label for the report)
    score      signed weighted sum (sign drives direction, magnitude
               drives confidence)
    """
    score = sum(int(s.get("vote") or 0) for s in signals)
    available_signals = sum(1 for s in signals if s.get("available"))

    if score >= 2:
        direction = "accelerating"
    elif score <= -2:
        direction = "cooling"
    else:
        direction = "steady"

    abs_score = abs(score)
    if available_signals >= 3 and abs_score >= 5:
        confidence = "HIGH"
    elif available_signals >= 2 and abs_score >= 2:
        confidence = "MED"
    else:
        confidence = "LOW"

    return direction, confidence, score


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_evidence(signals: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for s in signals:
        if not s.get("available"):
            continue
        if "delta_pct" in s and s.get("delta_pct") is not None:
            out.append(
                f"{s['label'].capitalize()} {_pct_phrase(s['delta_pct'])} "
                f"({s['current']} vs {s['prior']} prior)"
            )
        elif "delta_points" in s and s.get("delta_points") is not None:
            sign = "+" if s["delta_points"] >= 0 else ""
            out.append(
                f"{s['label'].capitalize()} {sign}{s['delta_points']:.2f} points "
                f"({s['current']} vs {s['prior']} prior)"
            )
        elif s.get("note"):
            out.append(f"{s['label'].capitalize()}: {s['note']}")
    return out


def _pct_phrase(delta: float) -> str:
    if delta >= 0:
        return f"up {delta:.0%}"
    return f"down {abs(delta):.0%}"


def _format_period_summary(period: dict[str, Any], start: str, end: str) -> str:
    avg = period.get("avg_materiality")
    avg_str = f"avg materiality {avg:.2f}" if avg is not None else "no materiality scores"
    return (
        f"{start} to {end}: {period['doc_count']} docs across "
        f"{period['event_count']} events ({period['total_articles']} total articles, {avg_str})"
    )


def _stage_confidence(label: str) -> float:
    """Map the label confidence (LOW/MED/HIGH) into the 0..1 stage confidence."""
    return {"HIGH": 1.0, "MED": 0.7, "LOW": 0.4}.get(label, 0.4)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _compute_prior_period(start_date_str: str, end_date_str: str) -> tuple[str, str]:
    start = _parse_date(start_date_str)
    end = _parse_date(end_date_str)
    length_days = max(1, (end - start).days)
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=length_days)
    return prior_start.isoformat(), prior_end.isoformat()


def _parse_date(d: str) -> date:
    if "T" in d:
        return datetime.fromisoformat(d).date()
    return date.fromisoformat(d)


STAGE = TrajectoryStage()
