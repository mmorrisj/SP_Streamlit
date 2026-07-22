"""
IMF Direction of Trade Statistics (DOTS / IMTS) - Ingestion Script

Fetches bilateral goods trade (exports FOB, imports CIF) from each influencer
country to each recipient country in shared/config/config.yaml and upserts the
series into the economic_indicators table (source='IMF_IMTS').

The IMF retired its legacy dataservices.imf.org API in 2025; this script uses
the current SDMX 3.0 REST API at api.imf.org, where DOTS lives in the IMTS
(International Merchandise Trade Statistics) dataflow:

    GET {base}/data/dataflow/{agency}/{dataflow}/{version}/{KEY}
    KEY = {COUNTRY}.{INDICATOR}.{COUNTERPART_COUNTRY}.{FREQUENCY}
    e.g. CHN.XG_FOB_USD.EGY.A?startPeriod=2015

Anonymous access works with tight rate limits. With an IMF data portal
account, put the subscription key in the IMF_API_KEY environment variable
(sent as the Ocp-Apim-Subscription-Key header) for higher limits.

Usage:
    python services/pipeline/ingestion/imf_dots.py
    python services/pipeline/ingestion/imf_dots.py --dry-run
    python services/pipeline/ingestion/imf_dots.py --status
    python services/pipeline/ingestion/imf_dots.py --clear
    python services/pipeline/ingestion/imf_dots.py --start-year 2018 --frequency M
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from shared.database.database import get_session
from shared.utils.countries import names_to_iso3
from services.pipeline.ingestion.econ_common import (
    econ_config, http_get_json, load_config, make_row,
    print_status, clear_source, upsert_rows,
)

SOURCE = 'IMF_IMTS'

# Dimension ids vary slightly across IMF dataflow versions
REPORTER_DIMS = ('COUNTRY', 'REF_AREA', 'REPORTER')
COUNTERPART_DIMS = ('COUNTERPART_COUNTRY', 'COUNTERPART_AREA', 'COUNTERPART')
INDICATOR_DIMS = ('INDICATOR', 'SERIES')
TIME_DIMS = ('TIME_PERIOD', 'TIME')


def parse_sdmx_json(payload: dict) -> List[dict]:
    """
    Flatten an SDMX-JSON data message into one dict per observation, with
    dimension ids as keys and the observation value under '_value'.

    Handles both SDMX-JSON 1.x (data.structure, singular) and 2.x
    (data.structures list, dataSet.structure index), and both the
    series-grouped and flat (dimensionAtObservation=AllDimensions) layouts.
    """
    data = payload.get('data', payload) or {}
    structures = data.get('structures')
    if structures is None:
        structure = data.get('structure')
        structures = [structure] if structure else []

    rows: List[dict] = []
    for dataset in data.get('dataSets', []):
        if not structures:
            break
        struct_idx = dataset.get('structure', 0)
        if not isinstance(struct_idx, int) or struct_idx >= len(structures):
            struct_idx = 0
        dims = structures[struct_idx].get('dimensions', {})
        series_dims = dims.get('series', [])
        obs_dims = dims.get('observation', [])

        def dim_labels(dim_list: list, key: str) -> dict:
            labels = {}
            for dim, idx_str in zip(dim_list, key.split(':')):
                values = dim.get('values', [])
                idx = int(idx_str)
                if idx < len(values):
                    labels[dim['id']] = values[idx].get('id')
            return labels

        def obs_value(obs):
            return obs[0] if isinstance(obs, (list, tuple)) and obs else obs

        if dataset.get('series'):
            for series_key, series in dataset['series'].items():
                base_labels = dim_labels(series_dims, series_key)
                for obs_key, obs in (series.get('observations') or {}).items():
                    labels = dict(base_labels)
                    labels.update(dim_labels(obs_dims, obs_key))
                    labels['_value'] = obs_value(obs)
                    rows.append(labels)
        elif dataset.get('observations'):
            all_dims = series_dims + obs_dims
            for obs_key, obs in dataset['observations'].items():
                labels = dim_labels(all_dims, obs_key)
                labels['_value'] = obs_value(obs)
                rows.append(labels)
    return rows


def _first(labels: dict, candidates: tuple) -> Optional[str]:
    for key in candidates:
        if labels.get(key):
            return labels[key]
    return None


def sdmx_rows_to_observations(parsed: List[dict]) -> List[dict]:
    """Map flattened SDMX rows to (reporter, indicator, counterpart, period, value)."""
    observations = []
    for labels in parsed:
        value = labels.get('_value')
        reporter = _first(labels, REPORTER_DIMS)
        counterpart = _first(labels, COUNTERPART_DIMS)
        indicator = _first(labels, INDICATOR_DIMS)
        period = _first(labels, TIME_DIMS)
        if value is None or not (reporter and counterpart and indicator and period):
            continue
        observations.append({
            'reporter': reporter,
            'counterpart': counterpart,
            'indicator': indicator,
            'period': period,
            'value': value,
        })
    return observations


def fetch_reporter(base_url: str, agency: str, dataflow: str, version: str,
                   reporter: str, indicators: List[str], counterparts: List[str],
                   frequency: str, start_year: int, end_year: int,
                   api_key: Optional[str]) -> List[dict]:
    """Fetch all indicators x counterparts for one reporter country."""
    key = f"{reporter}.{'+'.join(indicators)}.{'+'.join(counterparts)}.{frequency}"
    url = f"{base_url}/data/dataflow/{agency}/{dataflow}/{version}/{key}"
    params = {'startPeriod': str(start_year), 'endPeriod': str(end_year)}
    headers = {'Accept': 'application/vnd.sdmx.data+json'}
    if api_key:
        headers['Ocp-Apim-Subscription-Key'] = api_key
    payload = http_get_json(url, params=params, headers=headers)
    if payload is None:
        return []
    return sdmx_rows_to_observations(parse_sdmx_json(payload))


def main():
    parser = argparse.ArgumentParser(description='Ingest IMF DOTS/IMTS bilateral trade data')
    parser.add_argument('--dry-run', action='store_true', help='Fetch and parse without writing to the database')
    parser.add_argument('--status', action='store_true', help='Show ingestion coverage and exit')
    parser.add_argument('--clear', action='store_true', help='Delete all IMF_IMTS rows before ingesting')
    parser.add_argument('--start-year', type=int, help='Override economic_data.start_year')
    parser.add_argument('--end-year', type=int, help='Override end year (default: current year)')
    parser.add_argument('--frequency', choices=['A', 'Q', 'M'], help='Override economic_data.imf.frequency')
    args = parser.parse_args()

    if args.status:
        with get_session() as session:
            print_status(session, SOURCE)
        return

    config = load_config()
    econ = econ_config(config)
    imf = econ.get('imf', {})
    indicators: Dict[str, str] = imf.get('indicators', {})
    if not indicators:
        raise SystemExit("No indicators configured under economic_data.imf.indicators")

    base_url = imf.get('base_url', 'https://api.imf.org/external/sdmx/3.0')
    agency = imf.get('agency', 'IMF.STA')
    dataflow = imf.get('dataflow', 'IMTS')
    version = imf.get('dataflow_version', '+')  # '+' = latest
    frequency = args.frequency or imf.get('frequency', 'A')
    start_year = args.start_year or econ.get('start_year', 2015)
    from datetime import date
    end_year = args.end_year or date.today().year

    api_key = os.getenv('IMF_API_KEY')
    if not api_key:
        print("Note: IMF_API_KEY not set - using anonymous access (lower rate limits).")

    reporters = names_to_iso3(config.get('influencers', []))
    counterparts = names_to_iso3(config.get('recipients', []))
    print(f"Fetching {list(indicators)} for {len(reporters)} reporters x "
          f"{len(counterparts)} counterparts, {start_year}-{end_year} ({frequency})")

    all_rows = []
    for name, reporter_iso3 in sorted(reporters.items()):
        counterpart_iso3s = sorted(c for c in counterparts.values() if c != reporter_iso3)
        observations = fetch_reporter(
            base_url, agency, dataflow, version, reporter_iso3,
            list(indicators), counterpart_iso3s, frequency,
            start_year, end_year, api_key,
        )
        print(f"  {name} ({reporter_iso3}): {len(observations)} observations")
        for obs in observations:
            db_row = make_row(
                SOURCE, obs['indicator'], obs['reporter'], obs['period'],
                obs['value'], counterpart_iso3=obs['counterpart'],
                indicator_name=indicators.get(obs['indicator']),
                unit='USD',
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
