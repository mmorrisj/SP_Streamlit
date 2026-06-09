"""Shared module-level config and helpers for the API layer.

Extracted from ``server/main.py`` so that router modules under
``server/routers/`` can reuse configuration and common helpers without
importing ``server.main`` (which would create a circular import).
"""
from pathlib import Path

import yaml

# Load config.yaml for influencers and recipients lists
CONFIG_PATH = Path(__file__).parent.parent / "shared" / "config" / "config.yaml"
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

INFLUENCERS = CONFIG.get('influencers', [])
RECIPIENTS = CONFIG.get('recipients', [])


def _get_narrative_for_events(session, event_names: list, country: str) -> dict:
    """
    Batch-load the most recent EventSummary narrative for each event name.
    Returns {event_name: {overview, outcomes, source_link, source_count, citations}}.
    """
    if not event_names:
        return {}

    from sqlalchemy import text as sql_text
    rows = session.execute(sql_text("""
        SELECT DISTINCT ON (event_name)
            event_name,
            narrative_summary,
            material_score,
            material_justification
        FROM event_summaries
        WHERE initiating_country = :country
          AND event_name = ANY(:names)
          AND is_deleted = false
        ORDER BY event_name, period_start DESC
    """), {"country": country, "names": event_names}).fetchall()

    result = {}
    for row in rows:
        ns = row.narrative_summary or {}
        result[row.event_name] = {
            "overview": ns.get("overview"),
            "outcomes": ns.get("outcomes"),
            "source_link": ns.get("source_link"),
            "source_count": ns.get("source_count"),
            "citations": ns.get("citations", []),
        }
    return result
