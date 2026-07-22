"""
World Bank World Development Indicators (WDI) - Ingestion Script

Fetches country-level macro indicators (GDP, FDI inflows, trade share, ...)
for every influencer and recipient country in shared/config/config.yaml and
upserts them into the economic_indicators table (source='WDI').

Indicators and the start year are configured under economic_data.wdi in
shared/config/config.yaml. The World Bank API is free and unauthenticated:
https://api.worldbank.org/v2/country/{codes}/indicator/{code}?format=json

Usage:
    python services/pipeline/ingestion/wdi.py
    python services/pipeline/ingestion/wdi.py --dry-run
    python services/pipeline/ingestion/wdi.py --status
    python services/pipeline/ingestion/wdi.py --clear
    python services/pipeline/ingestion/wdi.py --start-year 2018 --end-year 2025
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.database.database import get_session
from shared.utils.countries import names_to_iso3
from services.pipeline.ingestion.econ_common import (
    econ_config, http_get_json, load_config, make_row,
    print_status, clear_source, upsert_rows,
)

SOURCE = 'WDI'
PER_PAGE = 1000


def parse_wdi_page(payload: list) -> List[dict]:
    """
    Extract data rows from one World Bank API response page.

    The API returns [metadata, rows]; rows is None when the query matched
    nothing. Rows with null values are dropped (no observation for that year).
    """
    if not payload or len(payload) < 2 or not payload[1]:
        return []
    rows = []
    for entry in payload[1]:
        if entry.get('value') is None:
            continue
        iso3 = entry.get('countryiso3code') or entry.get('country', {}).get('id', '')
        if len(iso3) != 3:
            continue  # aggregates like regions use 2-char codes
        rows.append({
            'iso3': iso3.upper(),
            'indicator_code': entry['indicator']['id'],
            'indicator_name': entry['indicator'].get('value'),
            'period': entry['date'],
            'value': entry['value'],
            'unit': entry.get('unit') or None,
        })
    return rows


def fetch_indicator(base_url: str, iso3_codes: List[str], indicator: str,
                    start_year: int, end_year: int) -> List[dict]:
    """Fetch all pages of one indicator for a set of countries."""
    url = f"{base_url}/country/{';'.join(iso3_codes)}/indicator/{indicator}"
    params = {
        'format': 'json',
        'per_page': PER_PAGE,
        'date': f'{start_year}:{end_year}',
        'page': 1,
    }
    all_rows: List[dict] = []
    while True:
        payload = http_get_json(url, params=params)
        if payload is None:
            break
        all_rows.extend(parse_wdi_page(payload))
        meta = payload[0] if payload else {}
        if params['page'] >= int(meta.get('pages', 1)):
            break
        params['page'] += 1
    return all_rows


def main():
    parser = argparse.ArgumentParser(description='Ingest World Bank WDI indicators')
    parser.add_argument('--dry-run', action='store_true', help='Fetch and parse without writing to the database')
    parser.add_argument('--status', action='store_true', help='Show ingestion coverage and exit')
    parser.add_argument('--clear', action='store_true', help='Delete all WDI rows before ingesting')
    parser.add_argument('--start-year', type=int, help='Override economic_data.start_year')
    parser.add_argument('--end-year', type=int, help='Override end year (default: current year)')
    args = parser.parse_args()

    if args.status:
        with get_session() as session:
            print_status(session, SOURCE)
        return

    config = load_config()
    econ = econ_config(config)
    wdi = econ.get('wdi', {})
    indicators: Dict[str, str] = wdi.get('indicators', {})
    if not indicators:
        raise SystemExit("No indicators configured under economic_data.wdi.indicators")

    base_url = wdi.get('base_url', 'https://api.worldbank.org/v2')
    start_year = args.start_year or econ.get('start_year', 2015)
    from datetime import date
    end_year = args.end_year or date.today().year

    countries = names_to_iso3(config.get('influencers', []) + config.get('recipients', []))
    iso3_codes = sorted(countries.values())
    print(f"Fetching {len(indicators)} WDI indicators for {len(iso3_codes)} countries, "
          f"{start_year}-{end_year}")

    all_rows = []
    for code, name in indicators.items():
        fetched = fetch_indicator(base_url, iso3_codes, code, start_year, end_year)
        print(f"  {code:<24} {len(fetched)} observations")
        for row in fetched:
            db_row = make_row(
                SOURCE, row['indicator_code'], row['iso3'], row['period'],
                row['value'], indicator_name=row['indicator_name'] or name,
                unit=row['unit'],
            )
            if db_row:
                all_rows.append(db_row)

    print(f"Parsed {len(all_rows)} total observations")
    if args.dry_run:
        print("Dry run - no database writes.")
        return

    with get_session() as session:
        if args.clear:
            deleted = clear_source(session, SOURCE)
            print(f"Cleared {deleted} existing {SOURCE} rows")
        written = upsert_rows(session, all_rows)
        print(f"Upserted {written} rows into economic_indicators")


if __name__ == '__main__':
    main()
