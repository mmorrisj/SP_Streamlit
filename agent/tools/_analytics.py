"""Shared helpers for tools that prefer the derived `analytics` schema.

The analytics schema (provenance_intensity, initiative_ledger,
relationship_changepoints, recipient_alias) is built by
docs/reports/_derived/build_analytics.py + build_theater.py. It may be absent
on deployments that never ran a report build, so every consumer must degrade
gracefully to the raw public tables.
"""
from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

#: Canonical MENA recipient aliases (mirror of analytics.recipient_alias).
RECIPIENT_ALIASES: dict[str, str] = {
    "UAE": "United Arab Emirates",
    "Palestinian Territories": "Palestine",
    "Palestinian Authority": "Palestine",
    "Gaza": "Palestine",
    "Gaza Strip": "Palestine",
    "West Bank": "Palestine",
}


def canon_recipient(name: str | None) -> str | None:
    if not name:
        return name
    return RECIPIENT_ALIASES.get(name.strip(), name.strip())


@lru_cache(maxsize=32)
def analytics_table_exists(table: str) -> bool:
    """True when analytics.<table> exists in the connected database."""
    try:
        from sqlalchemy import text
        from shared.database.database import get_session

        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'analytics' AND table_name = :t"
                ),
                {"t": table},
            ).first()
        return row is not None
    except Exception:
        logger.warning("analytics schema check failed for %s", table, exc_info=True)
        return False
