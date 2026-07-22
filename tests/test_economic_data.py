"""
Tests for the public economic data integration:
country name <-> ISO-3 mapping, period normalization, and the
World Bank WDI / IMF SDMX-JSON response parsers.

All tests here are pure-function tests using fixture payloads shaped like
real API responses — no database or network required.
"""

from datetime import date

import pytest

from shared.utils.countries import (
    canonical_name, iso3_to_name, names_to_iso3, to_iso3,
)
from services.pipeline.ingestion.econ_common import (
    frequency_of_period, make_row, period_to_date,
)
from services.pipeline.ingestion.wdi import parse_wdi_page
from services.pipeline.ingestion.imf_dots import (
    parse_sdmx_json, sdmx_rows_to_observations,
)


# ===========================================
# Country mapping
# ===========================================

class TestCountryMapping:
    def test_config_names_resolve(self):
        assert to_iso3('China') == 'CHN'
        assert to_iso3('United States') == 'USA'
        assert to_iso3('Saudi Arabia') == 'SAU'
        assert to_iso3('Palestine') == 'PSE'

    def test_aliases(self):
        assert to_iso3('UAE') == 'ARE'
        assert to_iso3('United Arab Emirates') == 'ARE'
        assert to_iso3('Türkiye') == 'TUR'
        assert to_iso3('Russian Federation') == 'RUS'
        assert to_iso3('West Bank and Gaza') == 'PSE'
        assert canonical_name('egypt, arab rep.') == 'Egypt'

    def test_unknown_returns_none(self):
        assert to_iso3('Atlantis') is None
        assert to_iso3('') is None

    def test_iso3_to_name_roundtrip(self):
        assert iso3_to_name('ARE') == 'United Arab Emirates'
        assert iso3_to_name(to_iso3('Jordan')) == 'Jordan'

    def test_names_to_iso3_dedupes_aliases(self):
        result = names_to_iso3(['UAE', 'United Arab Emirates', 'Egypt'])
        assert sorted(result.values()) == ['ARE', 'EGY']


# ===========================================
# Period normalization
# ===========================================

class TestPeriods:
    @pytest.mark.parametrize('period,expected', [
        ('2023', date(2023, 1, 1)),
        ('2023-Q1', date(2023, 1, 1)),
        ('2023-Q3', date(2023, 7, 1)),
        ('2023-M07', date(2023, 7, 1)),
        ('2023-07', date(2023, 7, 1)),
        ('garbage', None),
        ('2023-Q9', None),
        ('', None),
    ])
    def test_period_to_date(self, period, expected):
        assert period_to_date(period) == expected

    def test_frequency_of_period(self):
        assert frequency_of_period('2023') == 'A'
        assert frequency_of_period('2023-Q3') == 'Q'
        assert frequency_of_period('2023-M07') == 'M'
        assert frequency_of_period('2023-07') == 'M'

    def test_make_row(self):
        row = make_row('WDI', 'NY.GDP.MKTP.CD', 'EGY', '2023', 395.9e9,
                       indicator_name='GDP (current US$)')
        assert row['counterpart_iso3'] == ''
        assert row['frequency'] == 'A'
        assert row['period_date'] == date(2023, 1, 1)
        assert row['value'] == pytest.approx(395.9e9)

    def test_make_row_rejects_bad_period(self):
        assert make_row('WDI', 'X', 'EGY', 'not-a-period', 1.0) is None


# ===========================================
# World Bank WDI parser
# ===========================================

WDI_PAGE = [
    {'page': 1, 'pages': 1, 'per_page': 1000, 'total': 3, 'lastupdated': '2026-07-01'},
    [
        {
            'indicator': {'id': 'NY.GDP.MKTP.CD', 'value': 'GDP (current US$)'},
            'country': {'id': 'EG', 'value': 'Egypt, Arab Rep.'},
            'countryiso3code': 'EGY', 'date': '2023',
            'value': 395926000000.0, 'unit': '', 'obs_status': '', 'decimals': 0,
        },
        {   # null observation — should be dropped
            'indicator': {'id': 'NY.GDP.MKTP.CD', 'value': 'GDP (current US$)'},
            'country': {'id': 'SY', 'value': 'Syrian Arab Republic'},
            'countryiso3code': 'SYR', 'date': '2023',
            'value': None, 'unit': '', 'obs_status': '', 'decimals': 0,
        },
        {   # regional aggregate (2-char code) — should be dropped
            'indicator': {'id': 'NY.GDP.MKTP.CD', 'value': 'GDP (current US$)'},
            'country': {'id': 'ZQ', 'value': 'Middle East & North Africa'},
            'countryiso3code': '', 'date': '2023',
            'value': 3.0e12, 'unit': '', 'obs_status': '', 'decimals': 0,
        },
    ],
]


class TestWdiParser:
    def test_parses_valid_rows_only(self):
        rows = parse_wdi_page(WDI_PAGE)
        assert len(rows) == 1
        assert rows[0] == {
            'iso3': 'EGY',
            'indicator_code': 'NY.GDP.MKTP.CD',
            'indicator_name': 'GDP (current US$)',
            'period': '2023',
            'value': 395926000000.0,
            'unit': None,
        }

    def test_empty_result_set(self):
        assert parse_wdi_page([{'message': 'no data'}]) == []
        assert parse_wdi_page([{'page': 1}, None]) == []
        assert parse_wdi_page([]) == []


# ===========================================
# IMF SDMX-JSON parser
# ===========================================

_SDMX_DIMENSIONS = {
    'series': [
        {'id': 'COUNTRY', 'values': [{'id': 'CHN'}]},
        {'id': 'INDICATOR', 'values': [{'id': 'XG_FOB_USD'}, {'id': 'MG_CIF_USD'}]},
        {'id': 'COUNTERPART_COUNTRY', 'values': [{'id': 'EGY'}, {'id': 'SAU'}]},
        {'id': 'FREQUENCY', 'values': [{'id': 'A'}]},
    ],
    'observation': [
        {'id': 'TIME_PERIOD', 'values': [{'id': '2022'}, {'id': '2023'}]},
    ],
}

# SDMX-JSON 1.x layout: singular data.structure, series-grouped observations
SDMX_V1 = {
    'data': {
        'structure': {'dimensions': _SDMX_DIMENSIONS},
        'dataSets': [{
            'series': {
                '0:0:0:0': {'observations': {'0': [17000.5], '1': [18000.7]}},
                '0:1:1:0': {'observations': {'1': [9000.1]}},
            },
        }],
    },
}

# SDMX-JSON 2.x layout: data.structures list, flat AllDimensions observations
SDMX_V2_FLAT = {
    'data': {
        'structures': [{'dimensions': _SDMX_DIMENSIONS}],
        'dataSets': [{
            'structure': 0,
            'observations': {
                '0:0:0:0:0': [17000.5],
                '0:1:1:0:1': [9000.1],
            },
        }],
    },
}


class TestSdmxParser:
    def test_series_layout(self):
        observations = sdmx_rows_to_observations(parse_sdmx_json(SDMX_V1))
        assert len(observations) == 3
        exports = [o for o in observations if o['indicator'] == 'XG_FOB_USD']
        assert {(o['period'], o['value']) for o in exports} == {
            ('2022', 17000.5), ('2023', 18000.7),
        }
        assert all(o['reporter'] == 'CHN' and o['counterpart'] == 'EGY' for o in exports)

        imports = [o for o in observations if o['indicator'] == 'MG_CIF_USD']
        assert imports == [{
            'reporter': 'CHN', 'counterpart': 'SAU', 'indicator': 'MG_CIF_USD',
            'period': '2023', 'value': 9000.1,
        }]

    def test_flat_layout(self):
        observations = sdmx_rows_to_observations(parse_sdmx_json(SDMX_V2_FLAT))
        assert len(observations) == 2
        assert observations[0]['reporter'] == 'CHN'
        assert observations[0]['period'] == '2022'
        assert observations[1]['counterpart'] == 'SAU'
        assert observations[1]['period'] == '2023'

    def test_empty_payloads(self):
        assert parse_sdmx_json({}) == []
        assert parse_sdmx_json({'data': {'dataSets': []}}) == []
        assert parse_sdmx_json({'data': {'dataSets': [{'series': {}}]}}) == []
