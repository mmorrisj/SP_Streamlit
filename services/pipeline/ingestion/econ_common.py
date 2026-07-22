"""
Shared helpers for the public economic data ingestion scripts
(wdi.py — World Bank WDI, imf_dots.py — IMF DOTS/IMTS bilateral trade).

Pure functions (period parsing, HTTP retry) live here so they can be unit
tested without a database; the upsert/status/clear helpers take an open
SQLAlchemy session from the calling script.
"""

import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
import yaml

from shared.models.models import EconomicIndicator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / 'shared' / 'config' / 'config.yaml'

BATCH_SIZE = 1000
RETRY_STATUS = {429, 500, 502, 503, 504}


def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def econ_config(config: Optional[dict] = None) -> dict:
    config = config or load_config()
    econ = config.get('economic_data')
    if not econ:
        raise SystemExit(
            "No 'economic_data' section in shared/config/config.yaml — "
            "add one (see CLAUDE.md) before running economic data ingestion."
        )
    return econ


def period_to_date(period: str) -> Optional[date]:
    """
    Normalize a source period label to the first day of the period.

    Handles: '2023' (annual), '2023-07' / '2023-M07' (monthly),
    '2023-Q3' (quarterly). Returns None for unrecognized labels.
    """
    if not period:
        return None
    p = str(period).strip().upper()
    try:
        if len(p) == 4 and p.isdigit():
            return date(int(p), 1, 1)
        if '-Q' in p:
            year, quarter = p.split('-Q')
            return date(int(year), (int(quarter) - 1) * 3 + 1, 1)
        if '-M' in p:
            year, month = p.split('-M')
            return date(int(year), int(month), 1)
        if '-' in p:
            year, month = p.split('-')[:2]
            return date(int(year), int(month), 1)
    except (ValueError, IndexError):
        return None
    return None


def frequency_of_period(period: str) -> str:
    """Infer A/Q/M frequency code from a period label."""
    p = str(period).strip().upper()
    if '-Q' in p:
        return 'Q'
    if '-' in p or '-M' in p:
        return 'M'
    return 'A'


def http_get_json(url: str, params: Optional[dict] = None,
                  headers: Optional[dict] = None,
                  max_retries: int = 3, timeout: int = 60) -> Optional[dict]:
    """
    GET a JSON payload with basic retry/backoff on rate limits and 5xx.
    Returns None on 404 (sources use it for empty result sets).
    """
    attempt = 0
    while True:
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code == 404:
            return None
        if response.status_code in RETRY_STATUS and attempt < max_retries:
            attempt += 1
            wait = 2 ** attempt
            print(f"  HTTP {response.status_code} from {url[:80]}... retrying in {wait}s")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()


def make_row(source: str, indicator_code: str, country_iso3: str, period: str,
             value: float, counterpart_iso3: str = '',
             indicator_name: Optional[str] = None,
             unit: Optional[str] = None) -> Optional[Dict]:
    """Build an economic_indicators row dict; None if the period is unusable."""
    period_date = period_to_date(period)
    if period_date is None or value is None:
        return None
    return {
        'source': source,
        'indicator_code': indicator_code,
        'indicator_name': indicator_name,
        'country_iso3': country_iso3,
        'counterpart_iso3': counterpart_iso3 or '',
        'frequency': frequency_of_period(period),
        'period': str(period).strip().upper(),
        'period_date': period_date,
        'value': float(value),
        'unit': unit,
        'fetched_at': datetime.utcnow(),
    }


def upsert_rows(session, rows: List[Dict], batch_size: int = BATCH_SIZE) -> int:
    """
    Idempotent bulk upsert into economic_indicators. Re-running an ingestion
    refreshes values in place via the uq_econ_series_period constraint.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    total = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        stmt = pg_insert(EconomicIndicator).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint='uq_econ_series_period',
            set_={
                'value': stmt.excluded.value,
                'indicator_name': stmt.excluded.indicator_name,
                'unit': stmt.excluded.unit,
                'period_date': stmt.excluded.period_date,
                'fetched_at': stmt.excluded.fetched_at,
            },
        )
        session.execute(stmt)
        total += len(chunk)
    return total


def print_status(session, source: str) -> None:
    """Print per-indicator row counts and period coverage for a source."""
    from sqlalchemy import func

    stats = (
        session.query(
            EconomicIndicator.indicator_code,
            func.count(EconomicIndicator.id),
            func.min(EconomicIndicator.period),
            func.max(EconomicIndicator.period),
            func.count(func.distinct(EconomicIndicator.country_iso3)),
        )
        .filter(EconomicIndicator.source == source)
        .group_by(EconomicIndicator.indicator_code)
        .order_by(EconomicIndicator.indicator_code)
        .all()
    )
    if not stats:
        print(f"No {source} rows in economic_indicators yet.")
        return
    print(f"{source} coverage in economic_indicators:")
    for code, count, first, last, countries in stats:
        print(f"  {code:<24} {count:>8} rows  {first} → {last}  ({countries} reporter countries)")


def clear_source(session, source: str) -> int:
    """Delete all rows for a source. Returns the number of rows deleted."""
    deleted = (
        session.query(EconomicIndicator)
        .filter(EconomicIndicator.source == source)
        .delete(synchronize_session=False)
    )
    return deleted
