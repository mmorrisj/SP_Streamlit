"""Stage 5: Comparative Context.

Turns descriptive into analytical by ranking the report's focal pair
against comparable scopes in the same period.

Two comparison axes, each runs when its required filter is present:

  peer_recipient   influencer is fixed; compare across all recipients.
                   "China's engagement with Egypt is its #1 most active
                    relationship (47 docs vs median 18 across 12
                    recipient countries — 2.6x median)."

  peer_influencer  recipient is fixed; compare across all influencers.
                   "Egypt receives more documents from China (47) than
                    from any other influencer; next is Russia at 28."

For bilateral scope (both set) both axes run. For recipient-centric
regional, only peer_influencer runs. For influencer-centric regional,
only peer_recipient runs. If neither filter is set, the stage produces
zero comparisons with an info-level note.

Per-comparison output:
  comparison_type
  axis_label                "China across recipients"
  focal_label               "Egypt"
  focal_value               int
  peer_count                int (peers other than focal)
  rank                      1..N where 1 = highest
  percentile                0..100 rank percentile within full cohort
  median, mean              cohort statistics
  delta_vs_median_pct       (focal - median) / median, signed
  top_peers                 up to 10 ranked
  interpretation            deterministic prose
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from sqlalchemy import text

from agent.workflows.base import Stage, StageResult, WorkflowContext

logger = logging.getLogger(__name__)

TOP_PEERS_KEEP = 10
COHORT_MIN_FOR_HIGH_CONFIDENCE = 4


class ComparativeContextStage(Stage):
    name = "comparative_context"
    description = "Rank the focal scope against peer recipients and peer influencers."
    required = False
    depends_on = ["query_interpreter", "data_qa"]

    def run(self, ctx: WorkflowContext) -> StageResult:
        intent = ctx.require("query_interpreter").data
        influencer = intent.get("influencer")
        recipient = intent.get("recipient")
        start_date = intent.get("start_date")
        end_date = intent.get("end_date")

        if not start_date or not end_date:
            return StageResult(ok=False, error="start_date and end_date required")

        if not influencer and not recipient:
            return StageResult(
                ok=True,
                data={"comparisons": []},
                confidence=0.1,
                summary="comparative_context: no influencer or recipient — nothing to compare",
                notes=["scope has neither influencer nor recipient; comparisons require at least one"],
            )

        try:
            from shared.database.database import get_session
        except Exception as e:  # pragma: no cover
            return StageResult(ok=False, error=f"database layer unavailable: {e}")

        comparisons: list[dict[str, Any]] = []
        peer_counts: list[int] = []

        try:
            with get_session() as session:
                if influencer:
                    cohort = _fetch_peer_recipients(
                        session, influencer=influencer, start_date=start_date, end_date=end_date,
                    )
                    rec = _build_comparison(
                        comparison_type="peer_recipient",
                        axis_label=f"{influencer} across recipients",
                        focal_label=recipient or "(no focal recipient)",
                        focal_present=bool(recipient),
                        cohort=cohort,
                    )
                    if rec is not None:
                        comparisons.append(rec)
                        peer_counts.append(rec["peer_count"])

                if recipient:
                    cohort = _fetch_peer_influencers(
                        session, recipient=recipient, start_date=start_date, end_date=end_date,
                    )
                    rec = _build_comparison(
                        comparison_type="peer_influencer",
                        axis_label=f"{recipient} under influencers",
                        focal_label=influencer or "(no focal influencer)",
                        focal_present=bool(influencer),
                        cohort=cohort,
                    )
                    if rec is not None:
                        comparisons.append(rec)
                        peer_counts.append(rec["peer_count"])
        except Exception as e:
            logger.exception("comparative_context SQL failed")
            return StageResult(ok=False, error=f"comparison query failed: {e}")

        confidence = _confidence(comparisons, peer_counts)
        summary = (
            f"comparative_context: {len(comparisons)} axis comparison(s); "
            + ", ".join(
                f"{c['focal_label']} ranks #{c['rank']} of {c['peer_count'] + 1}"
                for c in comparisons
                if c.get("rank") is not None
            )
        )

        return StageResult(
            ok=True,
            data={"comparisons": comparisons},
            confidence=confidence,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# SQL: cohort fetch
# ---------------------------------------------------------------------------

def _fetch_peer_recipients(
    session, *, influencer: str, start_date: str, end_date: str,
) -> list[tuple[str, int]]:
    """All recipients of `influencer` in the period, by distinct-doc count."""
    sql = """
        SELECT rc.recipient_country AS name,
               COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN initiating_countries ic
            ON ic.doc_id = d.doc_id
           AND ic.initiating_country = :influencer
        JOIN recipient_countries rc
            ON rc.doc_id = d.doc_id
        WHERE d.date BETWEEN :start_date AND :end_date
          AND rc.recipient_country IS NOT NULL
          AND rc.recipient_country <> ''
        GROUP BY rc.recipient_country
        ORDER BY doc_count DESC
    """
    rows = session.execute(
        text(sql),
        {"influencer": influencer, "start_date": start_date, "end_date": end_date},
    ).fetchall()
    return [(r.name, int(r.doc_count)) for r in rows]


def _fetch_peer_influencers(
    session, *, recipient: str, start_date: str, end_date: str,
) -> list[tuple[str, int]]:
    """All influencers acting on `recipient` in the period, by distinct-doc count."""
    sql = """
        SELECT ic.initiating_country AS name,
               COUNT(DISTINCT d.doc_id) AS doc_count
        FROM documents d
        JOIN recipient_countries rc
            ON rc.doc_id = d.doc_id
           AND rc.recipient_country = :recipient
        JOIN initiating_countries ic
            ON ic.doc_id = d.doc_id
        WHERE d.date BETWEEN :start_date AND :end_date
          AND ic.initiating_country IS NOT NULL
          AND ic.initiating_country <> ''
        GROUP BY ic.initiating_country
        ORDER BY doc_count DESC
    """
    rows = session.execute(
        text(sql),
        {"recipient": recipient, "start_date": start_date, "end_date": end_date},
    ).fetchall()
    return [(r.name, int(r.doc_count)) for r in rows]


# ---------------------------------------------------------------------------
# Comparison building
# ---------------------------------------------------------------------------

def _build_comparison(
    *,
    comparison_type: str,
    axis_label: str,
    focal_label: str,
    focal_present: bool,
    cohort: list[tuple[str, int]],
) -> dict[str, Any] | None:
    """Assemble a single comparison record, or None if the cohort is empty."""
    if not cohort:
        return None

    cohort = sorted(cohort, key=lambda x: x[1], reverse=True)
    full_values = [v for _, v in cohort]

    if focal_present:
        focal_value = next((v for n, v in cohort if n == focal_label), 0)
    else:
        focal_value = 0  # focal not in this axis; cohort still useful

    peers = [(n, v) for n, v in cohort if n != focal_label]
    peer_values = [v for _, v in peers]

    median_val = float(statistics.median(full_values)) if full_values else 0.0
    mean_val = float(statistics.mean(full_values)) if full_values else 0.0

    rank = _rank_of(focal_label, cohort) if focal_present else None
    percentile = _percentile_of(focal_value, full_values) if focal_present and full_values else None
    delta_vs_median = (
        (focal_value - median_val) / median_val
        if focal_present and median_val > 0
        else None
    )

    top_peers = [
        {"name": n, "value": v} for n, v in peers[:TOP_PEERS_KEEP]
    ]

    interpretation = _format_interpretation(
        comparison_type=comparison_type,
        focal_label=focal_label,
        focal_present=focal_present,
        focal_value=focal_value,
        rank=rank,
        full_cohort_size=len(cohort),
        peer_count=len(peers),
        median=median_val,
        mean=mean_val,
        delta_vs_median=delta_vs_median,
        top_peers=peers[:3],
    )

    return {
        "comparison_type": comparison_type,
        "axis_label": axis_label,
        "focal_label": focal_label,
        "focal_present": focal_present,
        "focal_value": focal_value,
        "peer_count": len(peers),
        "cohort_size": len(cohort),
        "rank": rank,
        "percentile": round(percentile, 1) if percentile is not None else None,
        "median": round(median_val, 2),
        "mean": round(mean_val, 2),
        "delta_vs_median_pct": (
            round(delta_vs_median, 3) if delta_vs_median is not None else None
        ),
        "top_peers": top_peers,
        "interpretation": interpretation,
    }


def _rank_of(focal_label: str, cohort: list[tuple[str, int]]) -> int | None:
    """1-based dense rank of focal in cohort (cohort already sorted desc)."""
    for i, (name, _) in enumerate(cohort, start=1):
        if name == focal_label:
            return i
    return None


def _percentile_of(value: int, values: list[int]) -> float:
    """Percent of cohort values strictly below `value` (0..100)."""
    if not values:
        return 0.0
    below = sum(1 for v in values if v < value)
    return 100.0 * below / len(values)


# ---------------------------------------------------------------------------
# Interpretation prose (deterministic)
# ---------------------------------------------------------------------------

def _format_interpretation(
    *,
    comparison_type: str,
    focal_label: str,
    focal_present: bool,
    focal_value: int,
    rank: int | None,
    full_cohort_size: int,
    peer_count: int,
    median: float,
    mean: float,
    delta_vs_median: float | None,
    top_peers: list[tuple[str, int]],
) -> str:
    if not focal_present:
        # No focal — describe the cohort itself.
        if not top_peers:
            return "No cohort members in scope."
        lead = top_peers[0]
        return (
            f"Top of cohort: {lead[0]} ({lead[1]} docs). "
            f"Median across {full_cohort_size} members: {median:.0f}."
        )

    if focal_value == 0:
        return (
            f"{focal_label} has zero documents in this axis; cohort median is "
            f"{median:.0f} across {peer_count} peers."
        )

    # Rank narrative
    if rank == 1:
        rank_phrase = f"the #1 highest of {full_cohort_size}"
    elif rank is not None and rank <= 3:
        rank_phrase = f"#{rank} of {full_cohort_size}"
    elif rank is not None:
        rank_phrase = f"ranked #{rank} of {full_cohort_size}"
    else:
        rank_phrase = "unranked"

    # Magnitude vs median
    if delta_vs_median is None:
        magnitude_phrase = ""
    else:
        ratio = focal_value / median if median > 0 else 0
        if delta_vs_median >= 1.0:
            magnitude_phrase = f" — {ratio:.1f}x the median ({median:.0f})"
        elif delta_vs_median >= 0.2:
            magnitude_phrase = f" — {delta_vs_median:+.0%} vs median ({median:.0f})"
        elif delta_vs_median <= -0.5:
            magnitude_phrase = f" — well below median ({delta_vs_median:+.0%} vs {median:.0f})"
        elif delta_vs_median <= -0.2:
            magnitude_phrase = f" — {delta_vs_median:+.0%} vs median ({median:.0f})"
        else:
            magnitude_phrase = f" — near median ({median:.0f})"

    # Peer name dropping for color (only mention if peers are meaningfully different)
    peer_phrase = ""
    if top_peers and rank == 1 and len(top_peers) >= 1:
        next_peer = top_peers[0]
        if next_peer[1] > 0:
            peer_phrase = f". Next: {next_peer[0]} at {next_peer[1]}."

    axis_phrase = {
        "peer_recipient": "as a recipient",
        "peer_influencer": "as an influencer",
    }.get(comparison_type, "")
    return (
        f"{focal_label} ranks {rank_phrase} {axis_phrase} "
        f"({focal_value} docs{magnitude_phrase}){peer_phrase}"
    ).strip()


# ---------------------------------------------------------------------------
# Stage confidence
# ---------------------------------------------------------------------------

def _confidence(
    comparisons: list[dict[str, Any]], peer_counts: list[int]
) -> float:
    if not comparisons:
        return 0.1
    has_focal = any(c.get("focal_present") for c in comparisons)
    if not has_focal:
        # Cohort-only context is informational but not analytical
        return 0.4
    if any(pc >= COHORT_MIN_FOR_HIGH_CONFIDENCE for pc in peer_counts):
        return 1.0
    if any(pc >= 2 for pc in peer_counts):
        return 0.7
    return 0.4


STAGE = ComparativeContextStage()
