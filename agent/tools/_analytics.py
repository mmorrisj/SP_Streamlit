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


#: Valid MENA recipients (matches shared/config recipient set).
KNOWN_RECIPIENTS = {
    "Bahrain", "Cyprus", "Egypt", "Iraq", "Israel", "Jordan", "Kuwait",
    "Lebanon", "Libya", "Oman", "Palestine", "Qatar", "Saudi Arabia",
    "Syria", "United Arab Emirates", "Yemen", "Iran", "Turkey",
}

#: Country groups analysts commonly ask about — not queryable directly.
GROUP_MEMBERS = {
    "gulf": ["Bahrain", "Kuwait", "Oman", "Qatar", "Saudi Arabia", "United Arab Emirates"],
    "gulf states": ["Bahrain", "Kuwait", "Oman", "Qatar", "Saudi Arabia", "United Arab Emirates"],
    "gcc": ["Bahrain", "Kuwait", "Oman", "Qatar", "Saudi Arabia", "United Arab Emirates"],
    "levant": ["Israel", "Jordan", "Lebanon", "Palestine", "Syria"],
    "maghreb": ["Libya"],
    "north africa": ["Egypt", "Libya"],
    "middle east": sorted(KNOWN_RECIPIENTS),
    "mena": sorted(KNOWN_RECIPIENTS),
}


def canon_recipient(name: str | None) -> str | None:
    if not name:
        return name
    return RECIPIENT_ALIASES.get(name.strip(), name.strip())


def validate_recipient(name: str | None) -> tuple[str | None, str | None]:
    """Return (canonical_recipient, error). Unknown names error loudly instead
    of silently matching nothing — an empty result for a misspelled or group
    recipient reads as 'no activity', which is analytically wrong."""
    if not name:
        return None, None
    canon = canon_recipient(name)
    if canon in KNOWN_RECIPIENTS:
        return canon, None
    members = GROUP_MEMBERS.get(name.strip().lower())
    if members:
        return None, (
            f"'{name}' is a country group, not a recipient. Query each member "
            f"separately and aggregate: {', '.join(members)}. Or omit "
            f"recipient_country to get the initiator's regional total."
        )
    return None, (
        f"Unknown recipient '{name}'. Valid recipients: "
        f"{', '.join(sorted(KNOWN_RECIPIENTS))}."
    )


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
