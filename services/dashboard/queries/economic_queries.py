"""
Query functions for public economic indicator data (economic_indicators table).

Callers pass config-style country names ("China", "UAE", "Egypt"); conversion
to ISO-3 happens here via shared.utils.countries.
"""

from typing import Dict, List, Optional

from shared.database.database import get_session
from shared.models.models import EconomicIndicator
from shared.utils.countries import to_iso3


def _row_to_dict(row: EconomicIndicator) -> Dict:
    return {
        'source': row.source,
        'indicator_code': row.indicator_code,
        'indicator_name': row.indicator_name,
        'country_iso3': row.country_iso3,
        'counterpart_iso3': row.counterpart_iso3,
        'frequency': row.frequency,
        'period': row.period,
        'period_date': row.period_date,
        'value': row.value,
        'unit': row.unit,
    }


def get_bilateral_trade_series(
    initiating_country: str,
    recipient_country: str,
    indicator_code: Optional[str] = None,
) -> List[Dict]:
    """
    Bilateral trade series (IMF DOTS/IMTS) from an initiating country to a
    recipient, ordered by period. Optionally filter to one indicator
    (e.g. 'XG_FOB_USD' for exports).
    """
    reporter = to_iso3(initiating_country)
    counterpart = to_iso3(recipient_country)
    if not reporter or not counterpart:
        return []

    with get_session() as session:
        query = session.query(EconomicIndicator).filter(
            EconomicIndicator.source == 'IMF_IMTS',
            EconomicIndicator.country_iso3 == reporter,
            EconomicIndicator.counterpart_iso3 == counterpart,
        )
        if indicator_code:
            query = query.filter(EconomicIndicator.indicator_code == indicator_code)
        rows = query.order_by(
            EconomicIndicator.indicator_code, EconomicIndicator.period_date
        ).all()
        return [_row_to_dict(r) for r in rows]


def get_country_indicator_series(
    country: str,
    indicator_code: str,
) -> List[Dict]:
    """Country-level WDI series (GDP, FDI, ...) ordered by period."""
    iso3 = to_iso3(country)
    if not iso3:
        return []

    with get_session() as session:
        rows = (
            session.query(EconomicIndicator)
            .filter(
                EconomicIndicator.source == 'WDI',
                EconomicIndicator.country_iso3 == iso3,
                EconomicIndicator.indicator_code == indicator_code,
            )
            .order_by(EconomicIndicator.period_date)
            .all()
        )
        return [_row_to_dict(r) for r in rows]


def get_latest_country_indicators(country: str) -> List[Dict]:
    """Most recent observation of every WDI indicator for a country."""
    iso3 = to_iso3(country)
    if not iso3:
        return []

    with get_session() as session:
        rows = (
            session.query(EconomicIndicator)
            .filter(
                EconomicIndicator.source == 'WDI',
                EconomicIndicator.country_iso3 == iso3,
            )
            .order_by(
                EconomicIndicator.indicator_code,
                EconomicIndicator.period_date.desc(),
            )
            .all()
        )
        latest: Dict[str, Dict] = {}
        for row in rows:
            if row.indicator_code not in latest:
                latest[row.indicator_code] = _row_to_dict(row)
        return list(latest.values())
