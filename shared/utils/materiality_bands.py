"""Canonical materiality bands.

Materiality is a 1.0-10.0 significance scale (see the white paper and
MATERIALITY_SCORE_PROMPT). These bands are the single shared bucketing used
across the API, report pipeline, and agent tools — symbolic activity is a
real soft-power signal (narrative projection, signaling), not noise, so the
platform surfaces all three bands rather than only ranking by score.

Client-side mirror: client/src/components/materialityBands.ts
"""
from __future__ import annotations

# Band boundaries: [lower, upper) — upper bound exclusive except the last.
SYMBOLIC_MAX = 4.0      # 1.0-3.9: visits, statements, ceremonies, gestures
DEVELOPING_MAX = 7.0    # 4.0-6.9: MOUs, pilots, training — commitments not delivery
                        # 7.0-10:  funded projects, signed deals, delivered hardware

BANDS = ("symbolic", "developing", "substantive")


def band_for(score: float | None) -> str | None:
    """Return the band name for a materiality score, or None if unscored."""
    if score is None:
        return None
    if score < SYMBOLIC_MAX:
        return "symbolic"
    if score < DEVELOPING_MAX:
        return "developing"
    return "substantive"


def band_bounds(band: str) -> tuple[float | None, float | None]:
    """(min_inclusive, max_exclusive) score bounds for a band name."""
    if band == "symbolic":
        return (None, SYMBOLIC_MAX)
    if band == "developing":
        return (SYMBOLIC_MAX, DEVELOPING_MAX)
    if band == "substantive":
        return (DEVELOPING_MAX, None)
    raise ValueError(f"unknown materiality band: {band!r}")


# SQL CASE fragment classifying a score column into a band label.
def band_sql(column: str = "material_score") -> str:
    return (
        f"CASE WHEN {column} IS NULL THEN NULL "
        f"WHEN {column} < {SYMBOLIC_MAX} THEN 'symbolic' "
        f"WHEN {column} < {DEVELOPING_MAX} THEN 'developing' "
        f"ELSE 'substantive' END"
    )
