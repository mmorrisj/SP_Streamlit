"""Data-coverage awareness: what date range does the corpus actually cover?

Ingestion lags the wall clock, so any feature that translates relative time
("recently", "last 30 days") must anchor to the corpus's max document date,
not today — otherwise a lagging deployment answers "recent" questions with an
empty window. This module is the single source of truth, cached in-process.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600  # coverage moves at ingestion cadence; 10 min is plenty
_cache: dict | None = None
_cache_at: float = 0.0


class DataCoverage(TypedDict):
    min_date: Optional[str]   # YYYY-MM-DD
    max_date: Optional[str]   # YYYY-MM-DD
    total_documents: int
    days_behind: Optional[int]  # today - max_date (calendar days)


def get_data_coverage(force_refresh: bool = False) -> DataCoverage:
    """Return corpus coverage (min/max document date, doc count, lag vs today).

    Cached in-process for 10 minutes. On DB failure returns the last cached
    value if any, else an empty coverage object — callers must tolerate None
    dates.
    """
    global _cache, _cache_at
    now = time.monotonic()
    if not force_refresh and _cache is not None and (now - _cache_at) < _CACHE_TTL_SECONDS:
        return _cache  # type: ignore[return-value]

    try:
        from sqlalchemy import text
        from shared.database.database import get_session

        with get_session() as session:
            row = session.execute(
                text("SELECT min(date) AS min_d, max(date) AS max_d, count(*) AS n FROM documents")
            ).mappings().first()
        max_d: Optional[date] = row["max_d"] if row else None
        coverage: DataCoverage = {
            "min_date": str(row["min_d"]) if row and row["min_d"] else None,
            "max_date": str(max_d) if max_d else None,
            "total_documents": int(row["n"] or 0) if row else 0,
            "days_behind": (datetime.utcnow().date() - max_d).days if max_d else None,
        }
        _cache, _cache_at = coverage, now
        return coverage
    except Exception:
        logger.warning("data coverage query failed", exc_info=True)
        if _cache is not None:
            return _cache  # type: ignore[return-value]
        return {"min_date": None, "max_date": None, "total_documents": 0, "days_behind": None}


def temporal_anchor() -> date:
    """The date relative time references should anchor to: the corpus max
    date when it trails today, else today."""
    today = datetime.utcnow().date()
    cov = get_data_coverage()
    if cov["max_date"]:
        try:
            max_d = date.fromisoformat(cov["max_date"])
            return min(today, max_d)
        except ValueError:
            pass
    return today


def coverage_note() -> str:
    """One-line human/LLM-readable coverage statement."""
    cov = get_data_coverage()
    if not cov["max_date"]:
        return "Data coverage is unknown (coverage query unavailable)."
    note = f"The corpus contains documents from {cov['min_date']} through {cov['max_date']}."
    if cov["days_behind"] and cov["days_behind"] > 1:
        note += (
            f" That is {cov['days_behind']} days behind today — there is no data yet "
            f"for the most recent {cov['days_behind']} days."
        )
    return note
